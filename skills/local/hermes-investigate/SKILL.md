---
name: hermes-investigate
description: Systematic investigation workflow for bugs, failures, and confusing behavior. Use to gather symptoms, inspect logs/config/code, form and test hypotheses, identify root cause, and only then recommend or apply fixes.
version: 0.1.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [debugging, investigation, root-cause, logs, diagnosis]
    related_skills: [systematic-debugging, hermes-qa]
---

# Hermes Investigate

Use this skill when the problem is not yet understood and the right next step is investigation rather than immediate code changes.

## Trigger phrases
- investigate this
- find the root cause
- why is this failing
- trace this bug
- diagnose this issue
- don't fix yet, just find out why

## Goals
- Establish the observed symptoms
- Inspect the live evidence first: logs, errors, config, state, repro steps
- Form explicit hypotheses
- Test hypotheses using tools
- End with the most likely root cause, confidence level, and suggested fix path

## Primary tools
- terminal for logs, processes, tests, environment checks
- read_file/search_files for config and code inspection
- browser_* tools if the issue is UI or web-flow related
- todo for multi-step investigations
- delegate_task for isolated second-pass analysis when useful

## Workflow
1. State the symptom being investigated.
2. Gather evidence before editing anything:
   - logs
   - stack traces
   - failing commands
   - relevant config
   - reproduction steps
3. Narrow scope to likely components.
4. Form one or more explicit hypotheses.
5. Test each hypothesis with tools.
6. Conclude with:
   - root cause or most likely cause
   - evidence supporting it
   - confidence level
   - safest next fix
7. Only implement a fix after the user asks or the task clearly includes fixing.

## Read-Only Hermes Web UI / Model Latency Investigation

When the user says Web UI is slow but explicitly says **"查，别动手" / don't fix yet**, run a read-only investigation only. Do not restart services, edit config, clear state, or run chat tasks that mutate sessions unless the user approves.

Checklist:
1. Confirm live services and ports without changing state:
   ```bash
   systemctl --user --no-pager --type=service --state=running | grep -i hermes
   ss -ltnp | grep -E ':(3000|3001|8787|8765)\\b|python|node'
   ```
2. Read effective units/config with secrets redacted:
   ```bash
   systemctl --user cat hermes-webui.service hermes-gateway.service
   python3 - <<'PY'
   import yaml, re
   p='/home/dev/.hermes/config.yaml'
   data=yaml.safe_load(open(p)) or {}
   # print model/fallback/auxiliary only; redact api_key/token/password/secret
   PY
   ```
3. Compare Web UI local latency vs model-provider latency:
   - Web UI static frontend: `GET http://127.0.0.1:3000`
   - Web UI API health-ish endpoints may require auth; `401` in ~70ms still proves local server responsiveness.
   - Journal request timings: `journalctl --user -u hermes-webui.service --no-pager -n 150`
4. Inspect model-call failures in logs before blaming Web UI:
   ```bash
   journalctl --user -u hermes-webui.service --since '30 min ago' --no-pager \
     | grep -E 'API call failed|Provider:|Model:|Endpoint:|HTTP 503|HTTP 403|Fallback|Non-retryable|/api/chat/start|/api/chat/stream'
   ```
5. If logs show `HTTP 503: 分组 default 下模型 <model> 无可用渠道（distributor）`, the root cause is NewAPI/channel availability, not Web UI. If fallback is the same model/provider, call that out as a non-fallback.
6. A minimal `/v1/models` or `/v1/chat/completions` ping is acceptable as a read-only provider probe, but label it as an external API call and keep it tiny (`max_tokens` under 10).

Report format:
- State "只读，没动" if no changes were made.
- Separate local Web UI timings from upstream model errors.
- Give root-cause priority and safest next fix path, but do not apply fixes until asked.



1. Check service status and recent errors first:
   ```bash
   systemctl --user status hermes-gateway.service --no-pager -l | tail -20
   journalctl --user -u hermes-gateway.service --no-pager -n 50 | grep -i "error\|fail\|retry\|exception" | tail -30
   ```

2. Common root causes found so far:
   - **API provider Connection error** — upstream model endpoint down; gateway retries ×3 then logs `API call failed after 3 retries`. Self-resolves. No fix needed.
   - **edge_tts NoAudioReceived + timeout** — TTS provider returns empty audio; `asyncio.to_thread` call in `gateway/platforms/base.py` blocks up to 60s waiting for `ThreadPoolExecutor.result(timeout=60)`. Systemd kills gateway as "timeout". Fix: add short timeout (15s) around the `await asyncio.to_thread(text_to_speech_tool, ...)` call in `_handle_response` and degrade silently to text-only.
   - **Edge TTS voice/locale mismatch** — voice set to `en-US-*` but sending Chinese text → empty audio silently. Fix: ensure `tts.edge.voice` in config.yaml matches message language (e.g. `zh-CN-XiaoxiaoNeural`).

3. Key code locations:
   - Auto-TTS logic: `gateway/platforms/base.py` ~line 2436 (`_should_auto_tts_for_chat` + `await asyncio.to_thread`)
   - TTS generation: `tools/tts_tool.py` (`_generate_edge_tts`, ThreadPoolExecutor with 60s timeout)

## Reverse-proxy / Cloudflare 524 investigation for self-hosted APIs

When a user reports `Error 524` against a self-hosted API behind **Cloudflare Tunnel** (especially NEWAPI / Claude / VSCode / SSE-style traffic), do not stop at tunnel config folklore like "just raise `originRequest.readTimeout`". First verify the real path and collect evidence from each hop.

Checklist:
1. Identify the actual request chain from live config, not memory. Typical shape is:
   `client -> Cloudflare edge -> cloudflared -> local reverse proxy (:80) -> app container (:3000)`.
   Confirm with:
   ```bash
   sed -n '1,200p' /etc/cloudflared/config*.yml ~/.cloudflared/config*.yml 2>/dev/null
   ss -ltnp | grep -E ':(80|3000|3001|8787)\\b'
   docker ps --format '{{.Names}}\t{{.Ports}}'
   ```
2. Correlate the incident timestamp across three layers:
   - Cloudflare/cloudflared logs (`context canceled`, `Incoming request ended abruptly`)
   - reverse proxy access logs (`499` is the smoking gun that the upstream client/edge gave up)
   - app logs / DB rows to verify whether the app itself errored or was merely slow
3. If the reverse proxy fronts the app, inspect its live config before blaming cloudflared. For nginx:
   ```bash
   find /etc/nginx/sites-enabled /etc/nginx/conf.d -maxdepth 1 -type f -print
   grep -RInE 'server_name|proxy_pass|proxy_buffering|proxy_request_buffering|proxy_read_timeout|proxy_send_timeout|chunked_transfer_encoding' /etc/nginx/sites-enabled /etc/nginx/conf.d
   ```
4. For streaming/SSE-ish APIs (`/v1/messages`, Claude VSCode, long-running inference), treat these nginx settings as required candidates to inspect:
   - `proxy_buffering off;`
   - `proxy_request_buffering off;`
   - `proxy_cache off;`
   - `chunked_transfer_encoding off;`
   - long `proxy_read_timeout` / `proxy_send_timeout` / `send_timeout`
5. If the access log shows `POST /v1/messages?...` from a Claude/VSCode UA returning `499` at the same second cloudflared logs `context canceled`, and the app is otherwise alive on localhost, the likely root cause is the **reverse proxy not flushing streaming responses reliably enough for Cloudflare edge**, not a dead app.
6. Distinguish carefully:
   - `524` = Cloudflare edge timed out waiting for enough response progress
   - `cloudflared context canceled` = the edge side closed
   - nginx `499` = nginx saw its client vanish
   This combination usually points to a proxy-chain timeout/streaming problem, not an internal app crash.

Practical repair for nginx-backed NEWAPI:
```nginx
location / {
    proxy_pass http://127.0.0.1:3000;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;

    proxy_buffering off;
    proxy_request_buffering off;
    proxy_cache off;
    chunked_transfer_encoding off;

    proxy_read_timeout 3600s;
    proxy_send_timeout 3600s;
    send_timeout 3600s;
}
```

### Important verification update: this nginx fix is often necessary but may still NOT solve Claude VSCode 524s

A real-world failure mode found in session evidence:
- nginx already patched for streaming (`proxy_buffering off`, long timeouts, etc.)
- public site and local `curl` probes are healthy (`GET /` works, `new-api` container healthy)
- yet Claude VSCode still gets `Error 524` on `POST /v1/messages?beta=true`
- nginx access log shows `499 0` for the Claude VSCode UA at the exact second
- `cloudflared` logs `Incoming request ended abruptly: context canceled`
- NEWAPI DB (`logs` table) shows **no matching row** for that Claude request in the incident window

Interpretation: the request died in the Cloudflare edge / tunnel path before NEWAPI completed a normal request lifecycle. Once you have this evidence pattern, stop treating the problem as an nginx-only issue. The bottleneck is Cloudflare's proxy read timeout window for long-running Claude traffic.

Required next-step guidance in conclusions:
1. Say explicitly that the site/app being healthy does **not** mean the Claude request path is healthy.
2. Distinguish three simultaneous states if present:
   - Web console reachable
   - generic API requests working
   - Claude VSCode long `/v1/messages?beta=true` requests still timing out
3. Recommend a **non-Cloudflare path** for long-running coding traffic as the primary fix:
   - DNS-only subdomain to the VPS / origin
   - direct IP / high-port access
   - VPN / private network path
4. Phrase `cloudflared originRequest.readTimeout` tuning as secondary/optional, not the main fix, once Cloudflare has already emitted a 524 and nginx is streaming-safe.

Also note in conclusions: raising `cloudflared originRequest.readTimeout` may still be worth testing, but it is **not** sufficient evidence-based diagnosis when Cloudflare already returned a 524 and an intermediate nginx hop exists.

See `references/cloudflare-524-nginx-streaming-triage.md` for the evidence pattern and the point at which you should pivot from nginx tuning to bypassing Cloudflare for Claude/VSCode traffic.

## Reverse-proxy / Cloudflare 524 investigation for self-hosted APIs

When a user reports `Error 524` against a self-hosted API behind **Cloudflare Tunnel** (especially NEWAPI / Claude / VSCode / SSE-style traffic), do not stop at tunnel config folklore like "just raise `originRequest.readTimeout`". First verify the real path and collect evidence from each hop.

Checklist:
1. Identify the actual request chain from live config, not memory. Typical shape is:
   `client -> Cloudflare edge -> cloudflared -> local reverse proxy (:80) -> app container (:3000)`.
   Confirm with:
   ```bash
   sed -n '1,200p' /etc/cloudflared/config*.yml ~/.cloudflared/config*.yml 2>/dev/null
   ss -ltnp | grep -E ':(80|3000|3001|8787)\\b'
   docker ps --format '{{.Names}}\t{{.Ports}}'
   ```
2. Correlate the incident timestamp across three layers:
   - Cloudflare/cloudflared logs (`context canceled`, `Incoming request ended abruptly`)
   - reverse proxy access logs (`499` is the smoking gun that the upstream client/edge gave up)
   - app logs / DB rows to verify whether the app itself errored or was merely slow
3. If the reverse proxy fronts the app, inspect its live config before blaming cloudflared. For nginx:
   ```bash
   find /etc/nginx/sites-enabled /etc/nginx/conf.d -maxdepth 1 -type f -print
   grep -RInE 'server_name|proxy_pass|proxy_buffering|proxy_request_buffering|proxy_read_timeout|proxy_send_timeout|chunked_transfer_encoding' /etc/nginx/sites-enabled /etc/nginx/conf.d
   ```
4. For streaming/SSE-ish APIs (`/v1/messages`, Claude VSCode, long-running inference), treat these nginx settings as required candidates to inspect:
   - `proxy_buffering off;`
   - `proxy_request_buffering off;`
   - `proxy_cache off;`
   - `chunked_transfer_encoding off;`
   - long `proxy_read_timeout` / `proxy_send_timeout` / `send_timeout`
5. If the access log shows `POST /v1/messages?...` from a Claude/VSCode UA returning `499` at the same second cloudflared logs `context canceled`, and the app is otherwise alive on localhost, the likely root cause is the **reverse proxy not flushing streaming responses reliably enough for Cloudflare edge**, not a dead app.
6. Distinguish carefully:
   - `524` = Cloudflare edge timed out waiting for enough response progress
   - `cloudflared context canceled` = the edge side closed
   - nginx `499` = nginx saw its client vanish
   This combination usually points to a proxy-chain timeout/streaming problem, not an internal app crash.
7. If nginx is patched correctly and 524s still occur, check whether the user is trying to turn an **internal VM (`192.168.x.x`) into a public VPS**. Test the alleged public IP from outside; if it times out while local `0.0.0.0:3000` is listening and host firewall is inactive, conclude the machine is **behind NAT / not directly reachable**. Do not promise "IP direct" until you have proved external reachability.
8. If a user provides a separate public VPS and wants a quick bypass, do **not** assume the VPS can reach the VM's private IP. First test from the VPS to the VM target (`/dev/tcp/<private-ip>/<port>` or `nc -vz`). If unreachable, the right fast path is **reverse SSH tunnel / autossh from the VM to the VPS**, or router port-forward/VPN/Tailscale — not a blind TCP forward on the VPS.

Practical repair for nginx-backed NEWAPI:
```nginx
location / {
    proxy_pass http://127.0.0.1:3000;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;

    proxy_buffering off;
    proxy_request_buffering off;
    proxy_cache off;
    chunked_transfer_encoding off;

    proxy_read_timeout 3600s;
    proxy_send_timeout 3600s;
    send_timeout 3600s;
}
```

Also note in conclusions: raising `cloudflared originRequest.readTimeout` may still be worth testing, but it is **not** sufficient evidence-based diagnosis when Cloudflare already returned a 524 and an intermediate nginx hop exists.

## References
- `references/cloudflare-524-nginx-streaming-triage.md` — evidence pattern and repair path for Cloudflare Tunnel -> nginx -> NEWAPI 524s on Claude VSCode / streaming requests.
- `references/cloudflare-tunnel-vm-vps-direct-access.md` — NAT/private-IP pitfalls and when to switch from public-forward fantasies to reverse tunnels.

## Guardrails
- No speculative fixes before evidence.
- Prefer smallest reproducible test over broad random changes.
- If evidence is incomplete, say what is known vs unknown.
- Distinguish symptom, trigger, and root cause.

## "But you already checked this!" — scope-disambiguation pattern

When a user pushes back with phrases like "你不是检查过嘛？", "didn't you verify this already?", "I thought you fixed this", do NOT defend or re-run the same check. The complaint almost always means the previous check covered a **different layer** from what's currently failing. Resolve by separating:

1. **What was checked before** — name it explicitly (e.g. "上次查的是 stealth/指纹/IP 探活/UI 同步").
2. **What the current symptom actually points to** — name the layer (data quality? config? cache? race?).
3. **Verify the new layer independently** before making any claim about whether prior work was correct.

Common layer split for app-level bugs:
- **Runtime/code layer** — flow, race, async, IPC, broadcast
- **Data layer** — CSV rows, DB rows, JSON store, persisted state
- **UI/display layer** — caching, stale frame, missed event
- **Environment layer** — proxy, fingerprint, locale, network

A single symptom string in the UI (e.g. `missing_address`, `failed`, `stuck`) can originate in any layer. The fastest disambiguation:
- Find the **literal source string** in code (`grep -r "missing_address"` etc.) → trace **which inputs trigger it** → verify those inputs against the persisted data → only then conclude whether code, data, or display is wrong.

Reply pattern when this happens:
- Acknowledge the prior scope honestly: "上次查的是 X，没查 Y。"
- Show the new evidence path in 1-2 short blocks.
- Give a verdict: data is wrong / code is wrong / display is wrong.

## Project-specific investigation references
- `references/form-helper-v2-account-failure-trace.md` — end-to-end trace for "C0XX 标红/失败" symptoms in form-helper-v2: UI string → `azure_last_msg` → `profile.js` warnings → CSV field check → `resolveCsvSerialForName` name-direct vs `linked_csv_serial` fallback. Use when user reports a specific account showing red/failed/missing_* in the FormHelper UI.
- `references/form-helper-v2-flow-stage-divergence.md` — "C0XX 卡住" / "stage 不动" symptoms. Critical: proxies.json `azure_stage` does NOT reflect microsoftLogin's internal progress — read `logs/progress.txt` + `logs/flow/<envId>/*.png` first. Also covers the `detectLoginStage` title-vs-body race that produces `phone-confirm-no-switch.png` style false failures.

## Password reset / account recovery on self-hosted apps

When a user says an app account password is forgotten and asks you to reset it, treat this as a live recovery task, not a guess-the-config exercise.

Checklist:
1. Identify deployment shape first:
   ```bash
   docker ps --format 'table {{.Names}}\t{{.Image}}\t{{.Ports}}'
   docker inspect <app-container> --format '{{json .Config.Env}}'
   docker inspect <app-container> --format '{{json .Mounts}}'
   ```
   Look for app/db container names, bind mounts, bootstrap env like `ADMIN_EMAIL` / `ADMIN_PASSWORD`, and DB connection env.
2. Verify whether bootstrap env is still authoritative. Many apps only use `ADMIN_PASSWORD` during first install; later changes live in the database. Do **not** assume changing env or restarting will overwrite an existing admin password.
3. Find the real user store before changing anything:
   - inspect app data dir / config files
   - inspect DB tables (`\dt`, `\d users`, sample rows)
   - identify the exact admin user row(s)
4. Prefer the smallest reversible reset path:
   - first choice: app-native reset CLI/API if present and clearly documented
   - second choice: direct DB update of the password hash for the specific admin row
   - if 2FA/TOTP would still block access, clear it in the same targeted update **only for that user**
5. If you need a bcrypt hash and no app-native helper exists:
   - determine the existing hash format/cost from the DB (`$2a$05$...`, `$2y$...`, etc.)
   - PostgreSQL `pgcrypto` is a valid fallback: `crypt('<newpw>', gen_salt('bf', <cost>))`
   - if `gen_salt` / `crypt` is missing, check extensions and `CREATE EXTENSION IF NOT EXISTS pgcrypto;`
6. Verify with the real login endpoint, not just by inspecting the row:
   ```bash
   curl -sS -X POST http://127.0.0.1:<port>/api/.../login \
     -H 'Content-Type: application/json' \
     --data '{"email":"...","password":"..."}'
   docker logs --tail 20 <app-container>
   ```
   Success means real token/session issuance or a successful authenticated response, plus matching app logs.

Pitfalls:
- `ADMIN_PASSWORD` in container env may be stale bootstrap-only data; database state wins after initialization.
- `pgcrypto` may not be enabled even on a healthy Postgres container.
- `gen_salt('bf', cost)` will fail until `pgcrypto` is installed.
- Resetting the hash without clearing enabled TOTP can leave the user still locked out.
- Do not rotate all users or wipe auth tables just because one admin forgot a password. Surgical, not sitcom-energy.

Verification standard:
- Name the exact login URL used.
- State which user row was modified.
- Confirm whether TOTP was disabled during recovery.
- Confirm a real login succeeded.


## References
- `references/cloudflare-524-nginx-streaming-triage.md` — evidence pattern and repair path for Cloudflare Tunnel -> nginx -> NEWAPI 524s on Claude VSCode / streaming requests.
