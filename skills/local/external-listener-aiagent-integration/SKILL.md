---
name: external-listener-aiagent-integration
description: Wire an external chat listener (Telegram userbot, Discord bot, Slack, etc.) to Hermes AIAgent for full-tool agent functionality. Covers the bare-LLM-to-AIAgent migration, owner privilege gating, fast-vs-agent intent routing, typing/keepalive UX, and the cooldown-silent-drop UX trap. Trigger when user asks to "give bot X full AI agent functionality", "make my listener smart", or wants tools (web/browser/terminal/etc.) accessible from a non-Hermes chat surface.
---

# External Listener → AIAgent Integration

## When to use
You have an external chat listener (Telegram userbot/Discord bot/Slack/IRC/etc.) currently doing bare LLM `chat.completions` calls — it can chat but can't search/browse/run code. User wants to upgrade it to a real agent (web/browser/terminal/file/code_exec/skills/memory). Don't replace existing routing/rate-limit/auth logic — only swap the LLM call.

## Architecture (4 layers)

```
┌─ Telethon/Discord.py event handler  (DON'T touch — auth, dedup, anti-feedback)
├─ Rate limit + cooldown layer        (PATCH: exempt owner; never silently drop)
├─ Intent router  (NEW)                fast path = bare LLM ~2s
│                                      agent path = AIAgent.run_conversation ~30-120s
└─ Reply layer     (PATCH: wrap with platform "typing" indicator for keepalive)
```

## Step-by-step

### 1. Make hermes-agent importable
At top of listener:
```python
import sys, os
sys.path.insert(0, "/home/dev/.hermes/hermes-agent")  # or wherever hermes-agent lives
os.environ.setdefault("HERMES_HOME", "/home/dev/.hermes")
from run_agent import AIAgent
```
Run service via the hermes-agent venv: `ExecStart=/home/dev/.hermes/hermes-agent/.venv/bin/python -u listener.py`

### 2. Owner privilege constant
```python
OWNER_USER_ID = 7971261104  # the platform's user ID for the human operator
GUEST_TOOLSETS = ["web", "search", "session_search", "skills", "memory", "vision"]
OWNER_TOOLSETS = None  # None = all default toolsets (CLI parity)
```
**Pitfall**: For Telegram **userbots** (Telethon login as a person), the userbot's own `client.get_me().id` is NOT the owner — it's the bot persona. The owner is a *different* user account that talks to the bot. Don't conflate them. Listener already has `if sender_id == MY_ID: return` for self-message anti-feedback, which correctly skips userbot-self; OWNER_USER_ID is the human's separate account ID.

### 3. AIAgent wrapper (run in executor — AIAgent is sync)
```python
def _agent_kwargs(is_owner, session_id, user_name, chat_id):
    cfg = yaml.safe_load(open("/home/dev/.hermes/config.yaml"))
    m = cfg.get("model", {}) or {}
    return dict(
        model=m.get("default") or "claude-opus-4-7",
        provider=m.get("provider"), base_url=m.get("base_url"),
        api_key=m.get("api_key") or os.environ.get("OPENAI_API_KEY"),
        api_mode=m.get("api_mode"),
        enabled_toolsets=OWNER_TOOLSETS if is_owner else GUEST_TOOLSETS,
        session_id=session_id,                    # stable per (user, chat) for memory continuity
        platform="telegram", user_id=str(...), user_name=user_name,
        chat_id=str(chat_id), chat_type="group",
        quiet_mode=True,                          # suppress CLI progress prints
        skip_memory=not is_owner,                 # only owner accumulates persistent memory
        skip_context_files=not is_owner,          # AGENTS.md only for owner
        max_iterations=20,                        # cap for chat context (default 90 too high)
    )

async def call_agent(prompt, *, is_owner, session_id, user_name, chat_id):
    loop = asyncio.get_running_loop()
    def _do():
        agent = AIAgent(**_agent_kwargs(is_owner, session_id, user_name, chat_id))
        result = agent.run_conversation(user_message=prompt)
        if not isinstance(result, dict): return str(result or "").strip()
        return (result.get("final_response") or "").strip()
    return await asyncio.wait_for(loop.run_in_executor(None, _do), timeout=180)
```
`run_conversation` returns `{"final_response": str, "messages": [...], "completed": bool, "failed": bool, "error": str|None, "api_calls": int}`. **Always read `final_response`**, not the last message.

### 4. session_id strategy
- Owner: `f"<botname>_owner_{chat_id}"` — single persistent thread per chat, accumulates memory
- Guest: `f"<botname>_guest_{sender_id}_{chat_id}"` — isolated per user
- System bot (e.g. PulseToTG-style aggregator): `"<botname>_<systemname>"` shared, no per-user state, set `skip_memory=True`

### 5. Intent router (fast vs agent)
Bare LLM (1-3s) for chat; AIAgent (30-120s) for tool-y intent. Keyword + URL + length + slash-prefix:
```python
_AGENT_KEYWORDS = (
    "用 web", "搜一下", "查一下", "查询", "总结链接", "打开网页", "github上",
    # real-time intent — anything time-sensitive needs web
    "最近", "最新", "今天", "现在", "实时", "比分", "赛程", "新闻", "天气", "股价",
    "use web", "browse ", "fetch ", "latest", "today", "current",
)
_AGENT_PREFIXES = ("/hermes", "/agent", "/search", "/web", "/查", "/搜")  # explicit override

def _needs_agent(text):
    t = text.strip().lower()
    if any(t.startswith(p) for p in _AGENT_PREFIXES): return True
    t = t.replace("@yourbotname", " ")  # strip mention so it doesn't match
    if any(kw.lower() in t for kw in _AGENT_KEYWORDS): return True
    if re.search(r"https?://", text): return True  # URL → likely wants summary
    if "```" in text: return True                  # code block
    if len(text) > 220: return True                # long prompt
    return False
```
**Test the router offline before shipping** — write 8-10 expected (text → fast/agent) cases in a Python script and run it. Don't make the user be the test harness.

### 6. UX traps (the ones that bit me)

**Cooldown silent drop** — if user retries within cooldown window the listener returns silently, user sees zero response and assumes bot is broken. Two fixes:
- Exempt owner from cooldown entirely: `if not is_owner: enforce cooldown`
- Or send a tiny "稍等，刚回过你" reply on cooldown so user knows

**No keepalive during slow agent turn** — agent loop takes 1-2 min, user thinks bot died. Use platform's typing indicator:
- Telethon: `async with client.action(chat_id, "typing"): reply = await call_agent(...)` — auto-refreshes ~5s, survives long turns
- Discord: `async with channel.typing():`
- Slack: post a placeholder, edit it later

**Bare LLM lies about its capabilities** — fast path's system prompt MUST say "I can't browse the web; ask 'use web …' to engage tools". Otherwise on borderline routes user gets "I can't do that" from the chat-only model when the real agent could have done it.

### 7. Verify before declaring victory
```bash
# 1. Restart and verify listener attaches to platform
systemctl --user restart <bot>.service
sleep 8 && journalctl --user -u <bot>.service -n 6 | grep -E 'Logged in|running|ERROR'

# 2. Tail and watch one real round-trip
journalctl --user -u <bot>.service -f | grep -E 'route=|trigger=|replied|empty reply'

# 3. Verify routing log lines appear (`route=fast` vs `route=agent`)
```
Don't claim "works" until you see `route=agent` followed by `replied (N chars)` for a real tool-using prompt.

## Common errors

- **`empty reply from Hermes; skip`** — agent returned empty `final_response`. Check `errors.log` and `agent.log` for upstream HTTP error, AIAgent `failed: True`, or iteration cap hit.
- **`AIAgent init failed`** — usually missing `provider`/`api_mode` in config.yaml; AIAgent requires explicit values, not auto-detect.
- **Hangs forever** — no `asyncio.wait_for` wrapper. Always cap with timeout=180s.
- **First reply great, second reply nothing** — cooldown silent drop (see UX traps).

## Proxy configuration (Telethon userbot)

The Telethon `TelegramClient` takes a `proxy=` tuple — it does NOT read `HTTPS_PROXY` env vars. Must be set explicitly:

```python
PROXY = ("socks5", "127.0.0.1", 12000)          # old SSH tunnel
PROXY = ("socks5", "45.38.111.11", 5926, True, "oapqwxqn", "n1l45h99bz8q")  # auth proxy
# format: (type, host, port, rdns, username, password)

client = TelegramClient(SESSION, API_ID, API_HASH, proxy=PROXY, ...)
```

When the system-wide proxy changes (e.g. switching from SSH tunnel to external SOCKS5), update **all three places**:
1. `listener.py` PROXY constant
2. `~/.hermes/.env` `TELEGRAM_PROXY=`
3. `~/.config/systemd/user/hermes-gateway.service.d/proxy.conf` `TELEGRAM_PROXY=`

**Pitfall**: forgetting to update Telethon's tuple format — it uses positional args `(type, host, port, rdns, user, pass)`, not a URL string like the rest of the stack.

## File layout (Pana reference)
- `/home/dev/hermes-userbot/listener.py` — ~500 lines, the canonical example (currently stopped: `hermes-userbot.service` disabled 2026-05-04)
- `/home/dev/hermes-userbot/listener.py.bak.YYYYMMDD-HHMMSS` — pre-AIAgent backup
- `~/.config/systemd/user/hermes-userbot.service` — uses hermes-agent venv
- **Current status**: service disabled (`systemctl --user disable hermes-userbot.service`) — Pana userbot stopped because its PulseToTG summarization role was taken over; userbot infrastructure preserved if needed later

## Batching high-volume system messages (N-or-timeout flush)

When a system bot (RSS pusher, monitor, alert relay) floods the listener with per-item LLM calls, switch from per-event to **batch-N-or-timeout** to cut LLM cost and TG noise. Trigger: user says "每收到 N 个再发一次" / "summaries are too noisy" / per-item prompts cost real money.

**Architecture decision** (3 places it can live; pick #2 unless you have a reason):
1. **Source-side batch** (PulseToTG sends 1 message containing N posts): tightest coupling, source has to know about consumer, hard to tune. Avoid.
2. **Listener-side buffer** ✅ — source unchanged, listener buffers + flushes. Decoupled, easy to tune (`PULSE_BATCH_SIZE`/`PULSE_FLUSH_TIMEOUT_SEC`), independent restart. **Default choice.**
3. **Source batches raw text** (no LLM) — degrades to "noisy bulletin board"; loses summary value.

**Implementation skeleton** (asyncio, in-process state — accept the restart-loses-buffer tradeoff unless persistence is explicitly required):

```python
PULSE_BATCH_SIZE = 5
PULSE_FLUSH_TIMEOUT_SEC = 1800  # 30 min ceiling — without this, quiet days never flush

_pulse_buffer: list[str] = []
_pulse_first_at: float = 0.0
_pulse_lock: asyncio.Lock | None = None  # MUST lazy-init inside event loop, not at import

async def _enqueue_pulse(client, text: str) -> None:
    global _pulse_lock, _pulse_first_at
    if _pulse_lock is None:
        _pulse_lock = asyncio.Lock()
    async with _pulse_lock:
        if not _pulse_buffer:
            _pulse_first_at = asyncio.get_running_loop().time()
        _pulse_buffer.append(text)
        full = len(_pulse_buffer) >= PULSE_BATCH_SIZE
    if full:
        await _flush_pulse(client)   # release lock BEFORE flushing — flush re-acquires

async def _flush_pulse(client) -> None:
    global _pulse_buffer, _pulse_first_at
    async with _pulse_lock:
        if not _pulse_buffer: return
        posts, _pulse_buffer, _pulse_first_at = _pulse_buffer, [], 0.0
    prompt = _build_batch_prompt(posts)        # "summarize each of these N posts independently…"
    reply = await call_fast(prompt, _SYSTEM)   # one LLM call for the whole batch
    if reply:
        for chunk in _split_for_telegram(reply):
            await client.send_message(GROUP_ID, chunk)
            await asyncio.sleep(1.0)

async def _pulse_watchdog(client) -> None:
    """60s tick — flush if oldest buffered item exceeds timeout."""
    while True:
        try:
            await asyncio.sleep(60)
            if _pulse_buffer and (asyncio.get_running_loop().time() - _pulse_first_at) >= PULSE_FLUSH_TIMEOUT_SEC:
                await _flush_pulse(client)
        except asyncio.CancelledError: raise
        except Exception: log.exception("watchdog tick crashed; continuing")

# in main() AFTER client is connected, BEFORE run_until_disconnected:
asyncio.create_task(_pulse_watchdog(client))

# in event handler — early return for the batched reason:
if reason == "pulsetotg":
    await _enqueue_pulse(client, text)
    return
```

**Pitfalls**
- **Lock must be lazy-initialized** inside an async function; `asyncio.Lock()` at module level binds to a different/missing loop and deadlocks or errors.
- **Always release lock before awaiting downstream work** (LLM call, send_message). Hold it only around buffer mutation. Otherwise a slow LLM call blocks new enqueues for 30+s.
- **Timeout watchdog is mandatory** — without it, a quiet feed leaves N-1 posts buffered indefinitely. 30-min ceiling is a sane default.
- **Bump `call_fast` `max_tokens`** — single-post prompts work at 600; batch-of-5 needs ~2000. And bump timeout 45→60s. Otherwise the batch reply gets truncated mid-summary or times out.
- **Buffer is in-process only** — listener restart drops up to N-1 unflushed posts. Acceptable for low-stakes feeds; if not, persist to SQLite (`(id INTEGER, text TEXT, queued_at REAL)`) and reload on startup.
- **Don't set `PULSE_BATCH_SIZE=1`** thinking it disables batching — it skips the buffer but still pays the watchdog overhead. To disable batching, just remove the early-return.

**Verification**: tail logs for `pulse: buffered N/5` lines, then on the 5th expect `pulse: flushing 5 post(s)` followed by `pulse: sent batch summary`. To test the timeout path, temporarily set `PULSE_FLUSH_TIMEOUT_SEC=120` and send 1-2 posts, watch for `pulse: timeout flush` after 2 minutes.

## When NOT to use this approach
- Listener that already runs in-process with hermes (e.g. native Hermes platform plugin) — use `gateway/run.py` patterns instead
- Listener with hard latency budget (must reply <2s always) — keep bare LLM, don't add agent
- One-shot data summarization workers (PulseToTG-style) — bare LLM is faster and cheaper
