---
name: embedding-aiagent-in-external-host
description: Embed Hermes' AIAgent as a Python library inside an external custom host process (Telethon/Discord.py/Slack bot, scraper callback, webhook handler, userbot listener) so the host gets full agent powers — tools, memory, skills, multi-turn loop — without going through the gateway. Use when a user has a bare-LLM integration that should be upgraded to "full AI agent", when designing per-user/owner-vs-guest toolset gating, when fixing a custom listener whose `call_llm()` is a single chat.completions call and the user wants tools/memory, or when the host feels "too slow / not as cool as other bots" and needs intent-based fast-vs-agent routing plus typing-indicator UX.
version: 1.1.0
metadata:
  hermes:
    tags: [hermes, aiagent, embedding, library, run_agent, custom-host, telethon, userbot, listener, toolsets, session_id]
    related_skills: [hermes-agent, telegram-bot-to-bot-invisibility, webhook-subscriptions]
---

# Embedding AIAgent in an External Host

When a user has their **own** Python service (Telethon userbot, Discord.py bot, Slack-Bolt app, scraper-callback worker, custom webhook) and they want it to "have full AI agent powers" — meaning tools, persistent memory, skills, and the multi-turn agent loop — the right move is to import `run_agent.AIAgent` directly and call `run_conversation()`. **Don't** add a gateway platform adapter for this; that's the wrong layer when the user already owns the message-ingest path.

This skill is the recipe + the traps.

## When to use

Triggers (any of):
- User says "give X full agent / smart / tool capability" where X is their own non-gateway service
- The host's current LLM call is a bare `openai.OpenAI().chat.completions.create(...)` and the user wants tools or memory
- An integration log says `empty reply from Hermes; skip` because of an upstream error in a hand-rolled OpenAI client
- The user wants per-user session memory, owner-vs-guest tool gating, or skill access in their custom service

Don't use when: the user just wants a one-shot LLM rewrite of text (no tools/memory needed) — keep it bare. Or when the integration already runs through `hermes-gateway` (Telegram/Discord/Slack/etc. supported platforms) — fix the gateway side instead.

## Prerequisites

- Hermes installed at a known `HERMES_HOME` (typically `/home/dev/.hermes`, with source in `$HERMES_HOME/hermes-agent/`).
- Host process runs the Hermes venv's Python: `$HERMES_HOME/hermes-agent/.venv/bin/python` — needed so `run_agent` and its deps (httpx, openai, yaml, plugins) resolve.
- Host has read access to `$HERMES_HOME/config.yaml` and `.env`.

## Recipe

### 1. Bootstrap imports (top of host file, before importing `run_agent`)

```python
import os, sys
from pathlib import Path

HERMES_AGENT_DIR = Path("/home/dev/.hermes/hermes-agent")
sys.path.insert(0, str(HERMES_AGENT_DIR))
os.environ.setdefault("HERMES_HOME", "/home/dev/.hermes")

from run_agent import AIAgent  # noqa: E402
```

If you run via systemd, set the same in the unit file:
```ini
EnvironmentFile=/home/dev/.hermes/.env
Environment="HERMES_HOME=/home/dev/.hermes"
Environment="PYTHONPATH=/home/dev/.hermes/hermes-agent"
ExecStart=/home/dev/.hermes/hermes-agent/.venv/bin/python -u /path/to/your_listener.py
```

### 2. Build kwargs from config.yaml (don't hardcode model/provider)

```python
import yaml

def _agent_kwargs(*, is_owner: bool, session_id: str, user_name: str,
                  chat_id: str, platform: str = "custom") -> dict:
    with open("/home/dev/.hermes/config.yaml") as f:
        cfg = yaml.safe_load(f) or {}
    m = cfg.get("model", {}) or {}
    return dict(
        model=m.get("default") or m.get("model") or "claude-opus-4-7",
        provider=m.get("provider"),
        base_url=m.get("base_url"),
        api_key=m.get("api_key") or os.environ.get("OPENAI_API_KEY"),
        api_mode=m.get("api_mode"),
        enabled_toolsets=None if is_owner else GUEST_TOOLSETS,  # None = all default toolsets
        session_id=session_id,
        platform=platform,                # "telegram" / "discord" / "custom" — used in prompt + telemetry
        user_id=user_name_or_stable_id,
        user_name=user_name,
        chat_id=str(chat_id),
        chat_type="group",                # or "dm"
        quiet_mode=True,                  # NO stdout banners/spinners — critical under systemd
        skip_memory=not is_owner,         # only owner accumulates persistent memory
        skip_context_files=not is_owner,  # don't load AGENTS.md for guests (saves tokens)
        max_iterations=20,                # cap tool loops in chat context (default 90 is too many for chat)
    )
```

Key kwargs (full list at `run_agent.py:875` `AIAgent.__init__`):
- `enabled_toolsets`: list of toolset names, or `None` for "all defaults". Names match `toolsets.py` and CLI: `web, browser, terminal, file, code_execution, vision, image_gen, tts, skills, memory, session_search, delegation, cronjob, clarify, messaging, search, todo`.
- `disabled_toolsets`: subtractive — apply on top of `enabled_toolsets`.
- `session_id`: the **persistence key**. Same id → same conversation history + per-session memory. Design carefully (see §4).
- `quiet_mode=True`: suppress all progress prints. Mandatory under systemd/headless or you'll spam journal.
- `skip_memory=True`: disables loading + writing the persistent memory store. Use for untrusted/guest invocations so strangers don't poison your memory.
- `skip_context_files=True`: skips loading `AGENTS.md` and skills directives. Use for guests — saves ~5-15k input tokens.
- `max_iterations`: lower for chat (10-20) than CLI (90). Each tool call = one iteration.

### 3. Run a turn (sync API, dispatch from asyncio)

`AIAgent.run_conversation()` is **synchronous**. From an async host (Telethon, discord.py, FastAPI), wrap in an executor and apply a timeout:

```python
import asyncio

async def call_hermes(prompt: str, *, is_owner: bool, session_id: str,
                     user_name: str, chat_id: str) -> str:
    loop = asyncio.get_running_loop()

    def _do() -> str:
        try:
            agent = AIAgent(**_agent_kwargs(
                is_owner=is_owner, session_id=session_id,
                user_name=user_name, chat_id=chat_id))
        except Exception as e:
            log.exception("AIAgent init failed: %s", e)
            return ""
        try:
            result = agent.run_conversation(user_message=prompt)
        except Exception as e:
            log.exception("AIAgent run_conversation failed: %s", e)
            return ""
        if not isinstance(result, dict):
            return str(result or "").strip()
        if result.get("failed"):
            log.warning("AIAgent failed: %s", result.get("error"))
        text = (result.get("final_response") or "").strip()
        if "<think>" in text:
            import re as _re
            text = _re.sub(r"<think>.*?</think>\s*", "", text, flags=_re.DOTALL).strip()
        return text

    try:
        # Tool loops can take a while; chat-style timeouts: 60-180s.
        return await asyncio.wait_for(loop.run_in_executor(None, _do), timeout=180)
    except asyncio.TimeoutError:
        log.warning("AIAgent timed out")
        return ""
```

`run_conversation()` returns a dict with these keys (see `run_agent.py` ~10634, ~13371):
- `final_response` (str) — the assistant's final text. **This is what you send back.**
- `messages` (list) — full message history for this turn.
- `api_calls` (int)
- `completed` / `failed` (bool), `error` (str when failed)

### 4. Session ID design — the most important part

`session_id` controls memory+history continuity. Bad design = either zero memory or cross-user contamination. Pattern:

| Caller | session_id pattern | Notes |
|---|---|---|
| Owner / main user | `{service}_owner_{chat_id}` | One persistent thread per chat; owner builds long-term memory |
| Guest / strangers | `{service}_guest_{user_id}_{chat_id}` | Isolated per (user, chat); set `skip_memory=True` |
| Bot/scraper feeding the agent | `{service}_{source_name}` | Shared, no per-user state, `skip_memory=True` |
| One-shot fire-and-forget | `{service}_oneshot_{uuid}` | New every call — no continuity |

**Never** use just `{user_id}` without a service prefix — collides with CLI sessions in the same `HERMES_HOME`.

### 5. Toolset gating for safety (owner-vs-guest)

Default rule: if your host can be triggered by people who aren't the operator, **do not** give them the full toolset. Suggested split:

```python
GUEST_TOOLSETS = ["web", "search", "session_search", "skills", "memory", "vision"]
# Owner gets all defaults: enabled_toolsets=None
```

What's deliberately **excluded** for guests: `terminal`, `file`, `code_execution`, `cronjob`, `delegation`, `browser` (can scrape internal-network URLs), `tts`, `image_gen`. These are either write-capable, network-pivot capable, or expensive.

If your host has multiple platforms (e.g. one process serves Telegram + Discord), gate on a stable `(platform, sender_id)` tuple, not just sender_id, since IDs from different platforms can collide.

### 6. Avoid feedback loops (critical for chat hosts)

If your host listens to a group/channel where the agent's own replies appear, you **must** filter:
- The host's own user/bot id
- Any sibling Hermes bot's id (e.g. you're running `hermes-gateway`'s Telegram bot AND a Telethon userbot in the same group)
- The trigger source itself when it's a bot whose messages auto-trigger you

Trigger keywords (`hermes`, `助手`, etc.) commonly appear in the agent's *own* reply. Without sender filtering, you self-trigger forever and burn API credits.

```python
if sender_id == MY_ID: return                      # self-message
if sender_id == OTHER_HERMES_BOT_ID: return        # sibling agent
# Then check trigger conditions
```

Also rate-limit per-user (e.g. 30s cooldown) and per-process (e.g. 5/minute) — defense-in-depth against trigger storms. **Exempt the owner from cooldowns and rate limits** — if the operator can't trust their own bot to respond when they spam it, the bot is broken from their POV. Gate on `sender_id == OWNER_USER_ID`.

### 7. Latency & UX — making the host feel "as fast as other bots"

A bare-LLM bot replies in 1-3s. A full AIAgent reply with tool calls is 30-180s. Users will perceive the agent host as "broken/slow" unless you address two things explicitly: **route by intent** and **show progress**.

#### 7a. Two-tier routing: fast path vs agent path

The cheapest, biggest win: don't run the agent loop for chitchat. Add an intent classifier that decides per-message:

- **fast path** → one-shot `chat.completions.create()` (no tools, no AIAgent, ~1-3s). Default for greetings, casual chat, PulseToTG-style fixed-format summaries.
- **agent path** → full `AIAgent.run_conversation()` (~30-180s). Triggered only when the message looks tool-y.

Heuristic that works well in practice:

```python
import re
_AGENT_KEYWORDS = (
    # explicit Chinese tool requests
    "用 web", "用web", "搜一下", "搜下", "查一下", "查下", "查查", "帮我查",
    "总结链接", "打开网页", "打开链接", "抓一下", "帮我跑", "帮我运行",
    "运行一下", "执行一下", "github 上", "截图", "下载",
    # English equivalents
    "use web", "search the web", "browse ", "open url",
    "run this", "execute ", "fetch ", "summarize this link",
    # tool-name mentions
    "browser", "terminal", "code_exec", "code execution", "cronjob",
)
_URL_RE = re.compile(r"https?://\S+")

def _needs_agent(text: str) -> bool:
    if not text: return False
    t = text.lower().replace("@your_bot", " ")
    if any(kw.lower() in t for kw in _AGENT_KEYWORDS): return True
    if _URL_RE.search(text): return True   # URL → likely fetch/summary
    if "```" in text: return True          # code block → likely execute/review
    if len(text) > 220: return True        # long prompt → substantive task
    return False
```

For PulseToTG-style scraper feeds where the prompt is "summarize in N-段 format", **always** use the fast path — the format is structured, no tools needed, and you save ~10x latency and ~10x cost.

If you want even faster chat, set `model.fast_model` in `config.yaml` to a cheap/quick model (e.g. `gpt-4o-mini`, `claude-haiku`, `deepseek-chat`) and have the fast path read it; the agent path keeps the main model. The model itself isn't the slow part of agent runs (the loop is), so this only helps the fast path.

#### 7b. Typing indicator during long turns

The agent path will be slow no matter what. Show "typing..." so the user knows it's working:

```python
# Telethon: action() refreshes ~every 5s, so it stays alive across long turns
async with client.action(event.chat_id, "typing"):
    reply = await call_hermes(prompt, ...)
```

Discord.py: `async with channel.typing():`. Slack: post an ephemeral "thinking..." message and `chat.update` it with the final answer.

#### 7c. Cooldowns must not be silent drops

If you cooldown a user (e.g. `last_reply_time + 30s > now`), and the listener returns `None` without telling them, the user thinks the bot is broken. Two acceptable choices:

- Drop with a log line **only** (current behavior) — but then exempt the owner so the operator never hits this.
- Reply once with a one-liner ("稍等下，你触发太频繁") then drop subsequent triggers in the cooldown window.

Either is fine; **silent drop with no owner exemption** is the trap that wastes an hour of debugging "why didn't it reply".

#### 7d. The "I sent twice and got nothing" UX bug

Common pattern: user sends message A, listener replies; user immediately sends message B; listener silently cooldowns B; user thinks B failed and resends as C; C goes through 100s later. Three messages, one reply, user is confused. The owner-exempt-from-cooldown fix from §7c eliminates this for the operator. For guests, emit a one-liner so they don't resend.

## Verification

After wiring:

1. **Import smoke test** (no Telegram/Discord connect needed):
   ```bash
   /home/dev/.hermes/hermes-agent/.venv/bin/python -c "
   import sys, os
   sys.path.insert(0, '/home/dev/.hermes/hermes-agent')
   os.environ.setdefault('HERMES_HOME', '/home/dev/.hermes')
   import importlib.util
   spec = importlib.util.spec_from_file_location('h', '/path/to/your_listener.py')
   m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
   print('OK', m.AIAgent)
   "
   ```
2. **Restart the systemd unit**, check it stays `active (running)` for >30s and logs reach the host's "listening / ready" line.
3. **Live test**:
   - Owner sends a tools-required prompt ("用 web 查 X 的实时数据") → expect 30-60s wait then real-data reply.
   - Guest sends an obviously off-limits prompt ("跑一下 `ls /etc`") → expect refusal or fallback to plain text (terminal toolset wasn't enabled, so the agent literally has no such tool).
4. **Confirm session continuity**: owner sends "记住我喜欢 X"; in a later message asks "我喜欢什么?" — should remember. Guests should NOT have continuity (different `session_id` rules and `skip_memory=True`).

## Pitfalls

- **`empty reply from Hermes; skip` after upgrade** — if the host previously logged this with a bare OpenAI client, the cause was an upstream 400/401. After embedding AIAgent the symptom usually moves to `result["failed"]=True` with a real error in `result["error"]`. Log it; don't silently swallow.
- **Guest filling up persistent memory** — forgetting `skip_memory=True` for guests means strangers' chatter gets written to your memory store. Cleanup is `hermes memory ...` but prevention is the kwarg.
- **`max_iterations` default (90) eats credits** — that default is for CLI tasks. For chat replies, cap at 10-20.
- **Running with the system Python instead of the Hermes venv** — `from run_agent import AIAgent` may import but later fail mid-loop with missing-dep errors (e.g. `openai`, `httpx`, optional plugins). Always use `$HERMES_HOME/hermes-agent/.venv/bin/python`.
- **Calling `run_conversation()` directly from an async coroutine** — it's sync and does blocking I/O; running it on the event-loop thread freezes your host. Always use `loop.run_in_executor`.
- **Two AIAgent instances sharing a session_id concurrently** — race on the SQLite session store. Either serialize per `session_id` (per-key `asyncio.Lock`) or accept that one of two parallel turns from the same session may lose its history append.
- **`platform` left as `None`** — some prompt-builder branches and metadata routing key off it. Set to a stable string (`"telegram"`, `"discord"`, or your own tag like `"my-userbot"`).
- **Forgetting `quiet_mode=True` under systemd** — floods journal with progress prints + ANSI escape sequences, and slows the loop on every print.
- **Owner hits their own cooldown** — `PER_USER_COOLDOWN_SEC` and `MAX_REPLIES_PER_MINUTE` get applied to the operator too if you don't gate `if not is_owner:` around them. Symptom: "I sent twice and got nothing" while the journal quietly says `user X on cooldown; skipping`. Always exempt the owner from rate-limits and from any random think-delay (`asyncio.sleep(random.uniform(...))`) added for human-likeness.
- **Routing every message through the agent loop** — if the host runs AIAgent for "你好" / "在吗" / casual chitchat, every reply takes 30-100s, costs ~10x more tokens (full toolset schema is ~10-15k input tokens per turn), and the user complains the bot is slow vs other group bots. Add a fast-path/agent-path intent router (see §7a) — chat goes one-shot bare LLM in 1-3s, only tool-y messages enter the agent loop.
- **No typing indicator on the host side** — even with intent routing, agent-path runs are 30-180s. Wrap the call in `client.action(chat, "typing")` (Telethon) / `channel.typing()` (discord.py) / etc. Without it the chat looks frozen and users assume the bot crashed.
- **Variable bound only on one branch of the routing if/else** — when you split into fast vs agent paths, it's easy to set e.g. `system = ...` inside the fast branch and reference it later. Verify all three paths (fast-pulse, fast-chat, agent) close on every variable they read. AST parses fine; the bug surfaces at runtime as `NameError`.

## Related

- `hermes-agent` (the master skill) — for CLI/gateway/config questions, slash commands, full kwarg list at `run_agent.py:875`.
- `telegram-bot-to-bot-invisibility` — relevant when your host is a Telegram bot expected to read another bot's messages (it can't — must use a userbot).
- `webhook-subscriptions` — alternative path: instead of embedding AIAgent in your service, expose a Hermes webhook and let the gateway run the agent. Use this when you don't want to manage the agent loop yourself.
