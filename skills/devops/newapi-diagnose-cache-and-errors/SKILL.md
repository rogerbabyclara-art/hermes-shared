---
name: newapi-diagnose-cache-and-errors
description: Diagnose NEWAPI (one-api fork) prompt-cache misses, channel errors (400/5xx), and protocol-conversion issues by correlating the logs table `other` JSON field with container logs. Use when users report "cache not hitting on NEWAPI", upstream channel errors, or unexpected full-price billing despite prompts looking cacheable.
linked_files:
  - references/azure-ai-foundry-models-vs-deployments.md
---

# Diagnose NEWAPI cache / error issues

Use this skill when investigating NEWAPI (one-api / new-api fork) billing anomalies,
prompt-cache misses, or upstream 400/4xx errors on a specific channel.

## When to use

- User says "缓存没命中" / "cache not hitting" / "为什么还是全价"
- User asks to "绑定渠道" / "保持粘性" / "sticky routing" / "channel affinity" / "pin to one channel" on NEWAPI
- User wants a stable identifier (UUID, user_id, etc.) to make prompt cache survive across calls
- User shows screenshots of NEWAPI consumption dashboard with suspicious token counts
- `temperature is deprecated`, `model not found`, or other upstream channel errors
- Diffing "works via tool A, fails via tool B" against the same NEWAPI
- Azure AI Foundry endpoint returns `DeploymentNotFound` even though the API key works for listing models

## Pre-flight: locate the NEWAPI instance

Do NOT assume the NEWAPI host from memory — always verify from live configuration.

1. If the user is reporting from a Hermes-based client, look up the provider
   routing URL in the user's Hermes settings file (under `providers.<name>.api`).
   If that URL starts with `http://127.0.0.1:` or `http://localhost:`,
   NEWAPI is on THIS box.

2. Verify container is up:
   ```
   docker ps | grep new-api
   ss -ltnp | grep 3000
   ```

3. Find the compose file to get DB creds — typical location is
   `/opt/new-api/docker-compose.yml`. Postgres container is usually named
   `postgres`, user `root`, db `new-api`.

## Key schema facts

The `logs` table is the goldmine. Critical fields:

- `created_at` — **INTEGER epoch, but stored as if Shanghai time were UTC**.
  A row at Shanghai 08:20:54 on 2026-04-23 has `created_at = 1776903654`
  (which decodes as 2026-04-23 08:20:54 **UTC**). Convert user-visible Shanghai
  times to epoch using: `epoch = unix_ts(date) where date is treated as UTC`.
  Practical SQL: `to_timestamp(created_at) AT TIME ZONE 'Asia/Shanghai'` will
  display correctly if you *intended* the stored value to be Shanghai local.
- `username` — from API token owner (e.g. `rogerbaby`)
- `channel_id` — which upstream channel served the request
- `model_name` — model asked for
- `prompt_tokens` / `completion_tokens` / `quota` (in 500000 = $1 units usually)
- `content` — short summary, includes error message on failed requests
- `other` — **JSON blob with everything interesting** (see below)
- `is_stream`, `use_time` — stream flag, latency seconds
- `type` — 2 = success, other values = error

Error rows have `prompt_tokens=0, completion_tokens=0, quota=0` and error text in `content`.

## The `other` JSON fields that matter

```
cache_tokens             — cache READ hits on the upstream (0 = miss)
cache_creation_tokens    — cache WRITE (first-time prompt caching)
cache_creation_tokens_5m — 5-min TTL cache writes
cache_read_input_tokens  — alternative field name (depends on NEWAPI version)
request_path             — "/v1/messages" (Claude native) vs "/v1/chat/completions" (OpenAI)
request_conversion       — ["Claude Messages"]  = native, no conversion
                        — ["OpenAI Compatible","Claude Messages"] = OpenAI→Claude TRANSLATION
usage_semantic           — "anthropic" / "openai" — how NEWAPI parsed upstream usage
claude                   — true if upstream billing was anthropic-style
admin_info.channel_affinity, override_template, rule_name — routing metadata
use_channel              — array of channel ids tried
```

## Canonical diagnostic query

```sql
-- Find the time window first
SELECT id, to_timestamp(created_at) AT TIME ZONE 'Asia/Shanghai' AS ts,
       username, channel_id, model_name, prompt_tokens, completion_tokens
FROM logs ORDER BY created_at DESC LIMIT 15;

-- Then for a specific window (compute epoch: treat Shanghai as UTC):
SELECT id, to_timestamp(created_at) AT TIME ZONE 'Asia/Shanghai' AS ts,
       type, channel_id, prompt_tokens, completion_tokens, use_time,
       is_stream, quota, left(content,120) AS content
FROM logs
WHERE username='<user>'
  AND created_at BETWEEN <epoch_start> AND <epoch_end>
ORDER BY created_at;

-- Full usage details for specific rows:
SELECT id, prompt_tokens, completion_tokens, quota, other
FROM logs WHERE id BETWEEN <lo> AND <hi> ORDER BY id;
```

Run with: `docker exec postgres psql -U root -d new-api -P pager=off -At -F '|' -c "..."`

## Correlating with container logs

Container logs show request IDs, upstream errors, and HTTP status:

```
/opt/new-api/logs/oneapi-<TIMESTAMP>.log   — persistent file logs
docker logs new-api --since 2h              — live container logs
```

Grep for request id, error phrase, or time window. The `record consume log`
INFO line dumps the same `other` JSON you see in DB — useful if DB row is
missing. The `[GIN]` line at the end of a request reveals the HTTP path
(`POST /v1/chat/completions` vs `POST /v1/messages`) and status code.

## The #1 cache-miss pitfall: protocol conversion

If a row has:
- `request_path = "/v1/chat/completions"` AND
- `request_conversion = ["OpenAI Compatible","Claude Messages"]` AND
- `cache_tokens = 0, cache_creation_tokens = 0`

…then the cache miss is almost certainly because **the OpenAI→Claude translator
does not synthesize `cache_control` markers**. The OpenAI protocol has no
notion of prompt caching, so NEWAPI's converter sends a plain Claude request
with no ephemeral cache breakpoints. Every call pays full input price.

Compare against a `request_path = "/v1/messages"` row on the same channel:
cache will usually work because Anthropic-native clients (Claude Code, Claude
CLI, any proper SDK) emit `cache_control` themselves.

**Fix:** have the client speak Claude Messages protocol directly to
`/v1/messages`, not OpenAI Chat Completions. For a Hermes-based client this
means using an Anthropic-protocol provider entry pointed at `http://<host>:3000`
instead of an OpenAI-compatible provider entry pointed at `http://<host>:3000/v1`.

## The #1.5 pitfall: client emits markers but upstream still reports 0 cache_read

Even on a `/v1/messages` request from a known-good Anthropic-native client
(Claude Code, Hermes with `api_mode: anthropic_messages`, etc.), you can still
see every row report `cache_creation_tokens > 0, cache_tokens = 0` — i.e.
"writing fresh cache every time, never reading". When that happens, do not
stop at "client must be wrong" — verify in this order:

1. **Client really emits `cache_control`.** For Hermes:
   ```
   cd <hermes-agent> && .venv/bin/python -c "
   from agent.prompt_caching import apply_anthropic_cache_control
   msgs = [{'role':'system','content':'x'*2000},
           {'role':'user','content':'hi'},
           {'role':'assistant','content':'ok'},
           {'role':'user','content':'again'}]
   for m in apply_anthropic_cache_control(msgs, native_anthropic=True, cache_ttl='5m'):
       print(m['role'], 'cc=', m.get('cache_control') or
             [p.get('cache_control') for p in m['content'] if isinstance(p,dict)] if isinstance(m.get('content'),list) else None)
   "
   ```
   Every of system/last-3 should show `{'type':'ephemeral'}`. If not, the
   policy gate is wrong (see step 2).

2. **Policy gate fired.** In `run_agent.py` look at
   `_anthropic_prompt_cache_policy()`. It returns `(False, False)` when
   `"claude" not in model.lower()` even if `api_mode == "anthropic_messages"`.
   Models like `claude-opus-4-7` pass; aliased model names like `opus-latest`
   or `anthropic/<x>` may not. Verify:
   ```
   grep -E "^(model|api_mode):" ~/.hermes/config.yaml
   ```
   `model` must contain the literal substring `claude`.

3. **NEWAPI didn't strip the field.** Open the NEWAPI log row's ▶ details
   panel and inspect the request body sent **upstream** (not the request
   received from client). If `cache_control` is missing from the upstream
   body, NEWAPI's request transformer dropped it — usually a version bug
   or a `param_override` rule. Check the channel's `param_override` config.

4. **The channel's upstream actually honors cache_control.** Even when
   markers reach the upstream, if the channel points at *another* re-proxy
   (a chain of NEWAPI → reseller → Anthropic), the intermediate may strip
   markers or use a shared key fingerprint that defeats per-key cache scope.
   Verify in NEWAPI admin:
   - Channel type **must be** `Anthropic` (or `Claude`), not "OpenAI-format Claude wrapper".
   - Channel `base_url` should ideally be `https://api.anthropic.com` or
     a vendor known to forward `cache_control` verbatim
     (Bedrock, Vertex, LiteLLM in passthrough mode, MiniMax/Zhipu native).
   - If it's pointing at a no-name reseller, cache hits are not guaranteed
     even with a perfect client.

5. **Sticky binding actually held.** Across the rows in question, all
   `channel_id` values must be identical. If they drift, the
   `channel_affinity` rule isn't matching — re-check `key_path` against
   what the client actually sends (e.g. the client sends `metadata.user_id`
   but the rule is configured to read `user`).

6. **`key_fp` stable but cache still 0 — compare against a known-good client.**
   Stable `key_fp` across rows (e.g. all `48863636`) is necessary but NOT
   sufficient. Anthropic's cache namespace also depends on the exact upstream
   API key seen by Anthropic. The fastest way to localize the failure is to
   find a row from a different client (typically Claude Code) hitting the
   **same channel** and compare:
   ```sql
   SELECT id, to_timestamp(created_at) AT TIME ZONE 'Asia/Shanghai' AS ts,
          channel_id,
          (other::json->'admin_info'->'channel_affinity'->>'key_fp') AS key_fp,
          (other::json->'admin_info'->'channel_affinity'->>'key_hint') AS key_hint,
          (other::json->>'cache_tokens') AS cache_read,
          (other::json->>'cache_creation_tokens') AS cache_write
   FROM logs WHERE channel_id = <id>
   ORDER BY created_at DESC LIMIT 30;
   ```
   - If client A shows `cache_read > 0` and client B shows `cache_read = 0`
     on the same channel → the channel and upstream are fine; the fault is
     in client B's request shape (prompt prefix drift, cache_control layout,
     metadata field that's part of the cached prefix, etc.).
   - If both clients show 0 → upstream itself doesn't honor cache_control.
   - **Single-key channel does NOT mean shared cache namespace across clients.**
     Channel 41 (DIT.AI) has one key in PG but each `metadata.user_id`
     hashes to a different `key_fp`, putting clients in different cache
     namespaces. This is normal and expected.

If steps 1–3 pass but 4 or 6 fails, the fixes are: switch the channel's
upstream, align the failing client's request shape to mirror the working
client (especially the prompt prefix and metadata field), or accept the cost.

### 6.2 Multi-key channel: cache namespace rotation even with stable user_id

A NEWAPI channel can have **multiple upstream keys** in its `key` field
(newline-separated). NEWAPI round-robins or load-balances across them per
request. Anthropic's prompt cache is **scoped per upstream key**, so even
when:
- Hermes sends a stable `metadata.user_id`,
- the channel_affinity rule pins to the same channel_id,
- and Hermes-side SHA is byte-identical across calls,

…you will still see cache misses because NEWAPI rotates which upstream key
serves each call. Symptom shape (with byte-identical payloads):

```
call 1: cache_create=N, cache_read=0   ← key A writes
call 2: cache_create=N, cache_read=0   ← key B writes (also a miss!)
call 3: cache_create=~14, cache_read=N ← back to key A, finally hits
```

Two writes in a row on identical input is the giveaway — single-key
channels can never produce that pattern.

**Fastest reproduction (no Hermes needed)**: bypass Hermes entirely and hit
NEWAPI with raw `urllib` from the same host, byte-identical payload, 10x:

```python
# /tmp/cache_test.py — minimal repro
import json, time, urllib.request
BASE='https://<newapi-host>'; KEY='sk-...'
SYSTEM=('You are a helpful assistant. ' * 500).strip()  # ~6k tokens, > opus 1024 threshold
PAYLOAD={
  'model':'claude-opus-4-7','max_tokens':16,
  'metadata':{'user_id':'<the-stable-uuid-hermes-uses>'},
  'system':[{'type':'text','text':SYSTEM,'cache_control':{'type':'ephemeral'}}],
  'messages':[{'role':'user','content':'ok'}],
}
HDR={'x-api-key':KEY,'anthropic-version':'2023-06-01',
     'anthropic-beta':'prompt-caching-2024-07-31',
     'content-type':'application/json',
     'User-Agent':'anthropic-python/0.39.0'}  # avoid CF 1010
for i in range(1,11):
  req=urllib.request.Request(BASE+'/v1/messages',
    data=json.dumps(PAYLOAD).encode(), headers=HDR, method='POST')
  with urllib.request.urlopen(req,timeout=120) as r: u=json.loads(r.read())['usage']
  print(i, u.get('cache_creation_input_tokens'), u.get('cache_read_input_tokens'))
  time.sleep(2)
```

Pitfalls of this repro:
- Without `User-Agent`, Cloudflare in front of NEWAPI either returns
  **403 error code 1010** (UA-based bot block) OR — more confusingly —
  returns **HTTP 200 with `Content-Type: text/plain` and an empty/edge
  body** that never reaches origin (`Server-Timing: cfEdge;dur=N,cfOrigin;dur=0`).
  The 200+text/plain case is silent: requests look "successful" but
  every response parses to `{}` with no `usage` field. Default Python
  UA (`Python-urllib/3.x`) triggers this. Always set
  `User-Agent: curl/8.5.0` (or any real client UA) on raw probes.
- Some NEWAPI forks (e.g. "shellapi" v0.12.x) do **not** expose the
  serving channel id in response headers — you'll see
  `x-shellapi-request-id` and `x-oneapi-request-id` but no
  `new-api-channel-id`. From outside you cannot identify which
  channel/key handled a given call; you must infer from behavior
  (cache_create vs cache_read pattern) or from the NEWAPI admin DB/UI.
- Without `anthropic-beta: prompt-caching-2024-07-31`, some upstream
  resellers silently no-op `cache_control`.
- Use a system block ≥ ~5k bytes / ~1500 tokens to clear the Opus 1024
  threshold with margin; tiny prompts (e.g. 200 token blob) may not
  trigger cache write at all on some channels.

If this raw repro shows the "two writes then finally a read" pattern, the
fault is **NEWAPI multi-key rotation**, not Hermes and not the upstream.

**Fixes** (in order of preference):
1. NEWAPI admin → channel → "密钥/Key" field: reduce to a single key.
   Acceptable when one upstream key has enough rate budget for all
   traffic on this channel.
2. NEWAPI admin → channel: set its routing strategy to "sticky by
   metadata.user_id" or equivalent (varies by NEWAPI fork; check the
   channel's `param_override` / `key_strategy` fields).
3. Split into separate channels each holding one key, and use a
   `channel_affinity` rule keyed on `metadata.user_id` to pin clients to
   one channel.

The Hermes-side stable user_id binding is **necessary but not sufficient**
when the channel itself rotates keys; both layers must be stable.

#### Sub-case: dominant key_fp + minority bypass

Even with a working channel_affinity rule and a single configured upstream
key, a 1-hour sample can show a distribution like:

```
key_fp=48863636 → 41 rows   (dominant: metadata.user_id-bound traffic)
key_fp=453c15cf →  9 rows   (bypass)
key_fp=36c5082b →  3 rows   (bypass)
```

The minority `key_fp` rows usually have one of these signatures:
- `quota=0, prompt/completion≈0, frt=-1000` — internal probes / health
  checks NEWAPI fires to validate the channel; safe to ignore for billing.
- `key_hint` is a literal string like `"prob...able"` or similar
  placeholder — confirms it's a probe, not real traffic.
- Real client traffic that hit a different routing rule (e.g.
  `claude code trace` rule firing on a Claude-Code request that lacks
  `metadata.user_id`).

These don't break overall caching (the 41/53 dominant traffic still
benefits), but they do **lower the realized hit rate** because each probe
under a different fp writes a fresh cache entry that nobody reads. If the
user is chasing 100% hit rate, audit the channel's `param_override` /
`channel_affinity` rules to ensure every real request path matches the
sticky rule.

**Realistic post-fix expectation**: after fixing the dominant cache-hostile
problem (e.g. volatile fields in system prompt), expect hit rate to land
in the 60–80% range, not 100%. Anthropic's own cache layer has inherent
~10–20% miss jitter (multi-replica eventual consistency, key-bucket
eviction, beta header rollout cohorts) that no client-side fix can reach.
A jump from 30% → 70% with `cache_read` total roughly doubling is the
expected shape of "the fix worked".

### 6.1 Don't declare victory from a single cache-hit row

A common false-positive trap: you scroll the NEWAPI logs, find ONE row with
`cache_tokens > 0` on the right channel + key_fp, and conclude "cache works
now". That row may be:

- From a different client (Claude Code, another Hermes profile, a cron job)
  that happens to share the same channel.
- From an earlier time window before some regression.
- From a request whose prefix coincidentally matched a still-warm cache from
  another client.

**Required confirmation protocol** before claiming a cache fix:

1. Reset evidence: clear or rotate the Hermes-side dump file
   (`/tmp/hermes_anthropic_dump.log`) and note the current max `logs.id`
   in NEWAPI.
2. Have the user send **at least 2 short messages in the same session**,
   spaced < 5 minutes apart (well within the ephemeral TTL).
3. For each new request, capture BOTH ends:
   - Hermes side: SHA + length of `system`, `tools`, and each message's
     content from the dump hook (already implemented in
     `agent/anthropic_adapter.py` — search for
     `HERMES_DUMP_ANTHROPIC` / `_dump_path`).
   - NEWAPI side: the upstream request body actually sent to Anthropic
     (NOT the body received from the client). Pull from the row's
     `other` / details panel, or from container logs around the request id.
4. Compare prefixes byte-for-byte:
   - (A) Hermes-side SHA differs across the 2 calls → client is drifting
     (e.g. timestamp in system prompt, tool ordering, metadata field that's
     part of the cached prefix). Fix the client.
   - (B) Hermes-side SHA identical, but NEWAPI upstream body differs →
     NEWAPI is rewriting the body (param_override, model_mapping, tool
     translation). Fix the channel config.
   - (C) Both sides identical, second row still `cache_tokens=0` →
     upstream key namespace problem (different `key_fp`, channel rotation,
     or upstream reseller doesn't honor `cache_control`). Go back to
     steps 4–6 above.

Only after seeing `cache_tokens > 0` on row #2 of a freshly-captured pair
where you have both-end evidence should you say the issue is fixed.

### Temporary dump hook in Hermes (anthropic_adapter.py)

For diagnosis, `agent/anthropic_adapter.py` can carry a temporary dump
block at the end of `build_anthropic_kwargs` that writes
`/tmp/hermes_anthropic_dump.log` with: timestamp, model, metadata, SHA +
length of `system`/`tools`/each message, all `cache_control` marker
locations, and previews. Gated by env `HERMES_DUMP_ANTHROPIC` (default on
when the block is present). **Remove the block once diagnosis is complete**
— it logs prompt content and is not safe to leave running. Restart
`hermes-gateway` (user systemd) after toggling.

## The #2 pitfall: `temperature is deprecated` on Opus-4.x

Newer Claude models (Opus 4.x, Sonnet 4.x certain versions) reject `temperature`
entirely. If the upstream returns `400: temperature is deprecated for this model`
and the request came via OpenAI conversion, the client almost certainly sent a
default `temperature=0.3` (or similar) that got transparently forwarded.

For a Hermes-based client, inspect the helper `_fixed_temperature_for_model`
inside `agent/auxiliary_client.py`: only Kimi models return `OMIT_TEMPERATURE` —
every other model falls back to the caller's default (0.3 in `run_agent.py`).
If the user is hitting this on a Claude model, either:
- Add that model family to the `OMIT_TEMPERATURE` branch, OR
- Switch to Anthropic-protocol transport (preferred — fixes cache too).

## Querying NEWAPI DB for model-to-channel mapping

To find which channels carry a specific model (useful when troubleshooting "Invalid token" or testing new models):

```bash
# Identify the postgres container (NOT the new-api container)
docker ps --format "table {{.ID}}\t{{.Names}}\t{{.Image}}"

# Note: postgres container may not have 'psql' on PATH via exec sh
# Use the container name directly, e.g. 'postgres' or '80421eb39a88'
docker exec <postgres_container_id> psql -U root -d new-api -c \
  "SELECT id, name, LEFT(models,100) as models FROM channels WHERE models LIKE '%<model_fragment>%';"

# Examples
docker exec <postgres_id> psql -U root -d new-api -c \
  "SELECT id, name, LEFT(models,100) as models FROM channels WHERE models LIKE '%codex%' OR models LIKE '%5.3%' OR models LIKE '%5.4%';"
```

**Pitfall**: `docker exec <container> sh -c "psql ..."` fails with "executable file not found" on the postgres container — `sh` is not on PATH. Call `psql` directly as the command.

## The #4 pitfall: Azure AI Foundry `DeploymentNotFound` despite valid key

When a user configures an Azure AI Foundry endpoint (`*.services.ai.azure.com`) in NEWAPI and gets `DeploymentNotFound`, the key is valid but **no models have been deployed**. The `/openai/models` API returns 300+ models (the catalog), but `/openai/deployments/<name>/chat/completions` fails because deployments must be created explicitly in Azure Portal. The Playground works because it auto-creates serverless deployments behind the scenes.

See `references/azure-ai-foundry-models-vs-deployments.md` for diagnosis steps and NEWAPI configuration guide.

## Quick triage checklist

1. Grab 5–10 recent rows for the affected user/model.
2. For each row, note: `request_path`, `request_conversion`, `cache_tokens`, `cache_creation_tokens`.
3. If all failing rows share `request_path=/v1/chat/completions` with conversion
   list of length ≥ 2, the diagnosis is "wrong protocol" — fix on client side.
4. If cache_tokens is 0 on `/v1/messages` requests too, dig deeper:
   - Check prompt prefix drift (different system prompt each call)
   - Check `cache_creation_tokens_5m` — was it ever written?
   - Check 5-min TTL: if gap between requests > 5 min, ephemeral cache expired
5. For 400s: grep container log for the request id to see the verbatim upstream error.

## Pitfalls

- **Never assume NEWAPI host from memory** — each environment is different. Verify from live configuration.
- **Time zone trap** — `created_at` decodes as UTC but represents Shanghai wall-clock. If your queries return empty, recompute epoch.
- **Searching protected dirs silently fails** — recursive grep on paths the agent can't read returns a single "Permission denied" line that looks like a match. Use `search_files` with an accessible path instead.
- **`docker-compose ps` over SSH** may return empty string on success; verify with `docker ps` instead.
- **`other` field is text-JSON not jsonb** in older NEWAPI schemas — extract with string ops if jsonb operators fail.
- **Channel `other` JSON holds per-channel config** but is usually empty; real routing lives in the channel's `model_mapping` and `param_override` (not covered here).

## Channel stickiness + cache binding via stable identifier

NEWAPI's `channel_affinity` rule (stored in PG: `logs.other.admin_info.channel_affinity`,
configured per-instance) hashes a request field to pin a request to one upstream
channel + one API key. The same upstream key is what Anthropic uses to scope
ephemeral prompt cache, so a **stable identifier → sticky channel → stable key
fingerprint → cache hits**. Without it, requests rotate channels/keys and every
call looks like a fresh prompt to the upstream.

Common `key_path` values to check on the NEWAPI side:
- `metadata.user_id` — Anthropic Messages protocol (`/v1/messages`)
- `user` — OpenAI Chat Completions protocol (`/v1/chat/completions` body field)
- header-based routing (`X-Channel-Id` to force a specific channel)

**Binding from the Hermes side** (already implemented in
`agent/anthropic_adapter.py` `build_anthropic_kwargs`, near the end of the
function): a fixed install-wide UUID is injected as `metadata.user_id` on every
`/v1/messages` request. Search for `_HERMES_ANTHROPIC_USER_ID` to find or
change it. Verify it lands in real outbound requests with:

```
.venv/bin/python -c "
from agent.anthropic_adapter import build_anthropic_kwargs
kw = build_anthropic_kwargs(model='claude-opus-4-7',
    messages=[{'role':'user','content':'hi'}], tools=[], max_tokens=100,
    reasoning_config=None, tool_choice=None, is_oauth=False,
    preserve_dots=False, context_length=200000,
    base_url='https://<newapi-host>/', fast_mode=False)
print(kw.get('metadata'))
"
```

After changing the constant, restart `hermes-gateway` (user systemd service)
so the gateway reloads the new module. Confirm by comparing
`stat -c '%y' agent/anthropic_adapter.py` against
`systemctl --user show hermes-gateway -p ActiveEnterTimestamp --value`.

End-to-end verification: send several messages and run the canonical
diagnostic query above — `channel_id` should be identical across rows and
`cache_tokens` (or `cache_read_input_tokens`) should be > 0 from row #2 onward.

## The #3 pitfall: volatile fields in Hermes system prompt invalidate the whole prefix

`run_agent.py::_build_system_prompt` historically appended a block like:

```
Conversation started: Saturday, May 02, 2026 05:50 PM
Session ID: <uuid>
Model: claude-opus-4-7
Provider: custom
```

to the end of the system prompt. Both `Conversation started:` (live wall-clock
at agent start) and `Session ID:` (per-session UUID) drift on every new
session, every gateway restart, and across parallel workers (TUI, Web UI,
cron jobs, subagents). Anthropic's prompt cache keys on the **byte-exact**
prefix, so any drift in the *tail* of the system prompt invalidates the
entire 20k+ system block in front of it. Symptom in NEWAPI logs:
`cache_creation_tokens` ~10–20k on every row, `cache_tokens=0` even when
two requests fire seconds apart in the same chat.

**Diagnosis** — capture the dump (see "Temporary dump hook" above) over
~10 requests from a busy agent and look at the `system: sha=...` line:

- All identical SHA within one session, different across sessions →
  volatile-tail problem, fix by removing the volatile fields from the
  cached prefix.
- Different SHAs **within** one session → some other prefix drift
  (workspace tag, available_skills list, dynamic context file). Hunt
  with `system_tail_400` from the dump.

**Fix** — drop volatile fields from the cached system prompt; keep only
stable identity (Model / Provider). The conversation start time is
recoverable from session metadata if needed; the agent does not need it
in the prompt to function. Patch shape in `_build_system_prompt`:

```python
# OLD (cache-hostile):
timestamp_line = f"Conversation started: {now.strftime(...)}"
if self.pass_session_id and self.session_id:
    timestamp_line += f"\nSession ID: {self.session_id}"
if self.model:    timestamp_line += f"\nModel: {self.model}"
if self.provider: timestamp_line += f"\nProvider: {self.provider}"
prompt_parts.append(timestamp_line)

# NEW (cache-stable):
if self.model or self.provider:
    lines = []
    if self.model:    lines.append(f"Model: {self.model}")
    if self.provider: lines.append(f"Provider: {self.provider}")
    prompt_parts.append("\n".join(lines))
```

### Pitfall: restarting hermes-gateway is NOT enough to verify this fix

`_build_system_prompt` runs **once per Agent instance** at session start;
the result is cached on the instance. `systemctl --user restart hermes-gateway`
only kills the gateway process — pre-existing chat sessions keep their old
cached system prompt. After patching, the dump's `system_tail_400` will
still show `Conversation started: ...` for the active session.

**Verification protocol**:

1. Patch + restart gateway + clear `/tmp/hermes_anthropic_dump.log`.
2. **Open a brand-new chat** in Web UI / TUI (don't reuse the active one).
3. Send 2 short messages < 5 minutes apart.
4. Confirm in dump: `system_tail_400` no longer contains `Conversation started:`,
   and the two requests have **identical** `system: sha=...`.
5. Confirm in NEWAPI: row #2 shows `cache_tokens` ≈ size of system block,
   `cache_creation_tokens` ≈ 0 (or only the size of the new user turn).

Only then is the fix verified.

### Other volatile fields to audit in the same prompt assembly

When reviewing `_build_system_prompt` for cache-stability, also check:

- `<available_skills>` block — list of skills and their descriptions; any
  skill add/remove/edit changes the prefix. Consider sorting deterministically
  and stripping descriptions, or moving to lazy-load.
- Workspace tag (`[Workspace: /path/...]`) — usually injected per-message
  rather than into system, but verify it isn't bleeding in.
- `build_environment_hints()` output — shouldn't contain timestamps or PIDs.
- `build_context_files_prompt()` — fine if files are stable, but a file
  whose mtime triggers re-read every call (or whose content includes a
  timestamp) will silently break cache.

## Related Hermes code paths (for fixes on the Hermes client side)

- `hermes-agent/agent/auxiliary_client.py` — temperature policy (`_fixed_temperature_for_model`, `OMIT_TEMPERATURE`)
- `hermes-agent/run_agent.py` — where temperature is injected into API kwargs
- `hermes-agent/agent/prompt_caching.py` — Anthropic prompt caching logic (only active on native Anthropic protocol)
