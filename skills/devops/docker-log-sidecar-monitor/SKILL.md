---
name: docker-log-sidecar-monitor
description: Build a minimal sidecar monitoring dashboard for a Dockerized app by tailing docker logs, classifying errors, storing them in SQLite, and exposing a web UI via FastAPI behind Nginx.
version: 1.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [docker, monitoring, fastapi, nginx, sqlite, sidecar, logs]
---

# Docker Log Sidecar Monitor

Use when a production app runs as a Docker container from a stock image and you want a low-risk monitoring UI without modifying the app container.

## When to choose this
- The main service is a Docker container with no host bind mounts.
- Errors already appear in `docker logs`.
- You want the safest first version: no image rebuild, no app code changes, no downtime.
- Nginx already fronts the app and can expose an extra path like `/monitor/`.

## Proven approach
1. Verify the real runtime path first.
   - Check containers: `docker ps --format 'table {{.ID}}\t{{.Names}}\t{{.Image}}\t{{.Ports}}\t{{.Status}}'`
   - Check Nginx routing: `grep -RniE 'proxy_pass|3000|8081|your-domain' /etc/nginx /www/server/nginx 2>/dev/null | head -100`
   - Check PM2 only to rule it out: `pm2 list && pm2 describe all`
2. Confirm the target app is actually Dockerized and fronted by Nginx.
3. Inspect the target container before proposing changes.
   - `docker inspect <container> --format '{{json .}}'`
   - `docker inspect <container> --format '{{json .Mounts}}'`
   - `docker inspect <container> --format '{{range .Config.Env}}{{println .}}{{end}}'`
   - `docker logs --tail 200 <container> 2>&1`
4. If `Mounts` is `[]` or there is no source checkout on the host, do **not** try to patch the app in place.
   - Build a sidecar monitor instead.
5. Build a small FastAPI app that:
   - tails `docker logs --timestamps -f <container>`
   - parses known error patterns
   - stores aggregated events in SQLite
   - exposes JSON API + SSE stream + simple HTML UI
6. Put it behind the existing domain using Nginx path routing.
7. Add systemd so the monitor survives reboot.

## Minimal implementation structure
Recommended files:
- `app.py` — FastAPI app, SSE endpoint, startup thread for log follower
- `monitor_core.py` — parser + SQLite store
- `templates/index.html` — dashboard page
- `static/app.js` — fetch events, SSE updates, sound alerts, ack button
- `static/style.css` — severity coloring
- `tests/test_parser.py`
- `tests/test_store.py`
- `deploy/<service>.service`
- `deploy/nginx-monitor.conf`

## Useful parser categories seen in practice
Start with these event classes:
- `daily_limit_exceeded` — `DAILY_LIMIT_EXCEEDED`
- `auth_error` — `Invalid token` or `ValidateUserToken`
- `channel_error` — `channel error`
- `relay_error` — `relay error`
- `db_record_not_found` — generic `record not found`
- `suspicious_probe` — requests like `/.env` or `/.claude/.credentials.json`
- `upstream_5xx` — `status code: 5xx`
- `timeout` — `timeout` / `timed out`

Suggested severities:
- critical: auth errors, relay errors, 5xx, panic/fatal, DB/Redis connection failure
- warning: daily limit exceeded, channel errors, timeouts, suspicious probes
- info: single generic `record not found` style noise

Important ordering rule:
- Put specific auth patterns like `invalid token|ValidateUserToken` BEFORE generic `record not found`.
- Otherwise real authentication failures can be misclassified as low-severity DB noise and appear as monitor "漏报" for serious incidents.

## Implementation notes
- Use `docker logs --timestamps -f <container>` so the collector gets stable timestamps.
- Normalize request IDs and IPs before hashing so duplicates collapse correctly.
- Store `fingerprint`, `count`, `first_seen`, `last_seen`, `acknowledged` in SQLite.
- Expose collector-health fields in the API stats payload so live verification can distinguish "UI is up" from "collector is actually tailing logs". Useful fields proven in practice: `collector_alive`, `last_log_seen_at`, `last_collector_error`, `monitored_container`.
- Make the log follower resilient to transient `subprocess.Popen(...)` failures. A minimal proven pattern is: if spawning `docker logs -f` fails once, record the error, sleep briefly, and retry instead of letting the collector thread die silently.
- SSE is enough for real-time browser updates; WebSockets are optional.
- Use raw HTML/CSS/JS for the first version to keep deployment simple.

## Nginx pattern
If the main app already occupies `/`, add more specific locations before `location /`:
- `/monitor/`
- `/monitor/api/`
- `/monitor/api/stream`
- `/monitor/static/`

Be careful with path prefixes. If the app is mounted under `/monitor/`, either:
- make frontend requests relative to `/monitor/...`, or
- have Nginx proxy the root-level `/api/...` and `/static/...` paths too.

Critical trailing-slash rule learned in production:
- For `location /monitor/`, `proxy_pass http://127.0.0.1:8788/;` strips the `/monitor/` prefix before forwarding.
- That means a public request to `/monitor/` reaches the upstream as `/`, which can silently serve the root page instead of the prefixed monitor page.
- In one verified incident this caused the HTML to render with `window.MONITOR_BASE = ""` and `/static/app.js` instead of `/monitor/...`, so the backend had data but the dashboard looked blank or wrong.
- If you want the upstream to receive `/monitor/...` unchanged, use `proxy_pass http://127.0.0.1:8788;` with no trailing slash.
- After any change, verify the exact rendered HTML, not just API health.

## Systemd pattern
Use a simple service:
- `WorkingDirectory=<project-dir>`
- `ExecStart=/usr/bin/env uvicorn app:app --host 127.0.0.1 --port 8788`
- `Restart=always`
- `After=network.target docker.service`
- `Requires=docker.service`

## Verification checklist
- `pytest -q` passes.
- If tests use `fastapi.testclient`, ensure `httpx` is installed in the deployment venv; otherwise test collection can fail with `RuntimeError: The starlette.testclient module requires the httpx package to be installed` even when the app itself runs.
- `uvicorn app:app --host 127.0.0.1 --port 8788` starts locally.
- `curl http://127.0.0.1:8788/api/events` returns JSON.
- Verify the embedded stats include collector-health fields and show healthy values, e.g. `collector_alive=True`, recent `last_log_seen_at`, and `last_collector_error=null`.
- If you expose a prefixed UI, also verify `curl http://127.0.0.1:8788/monitor/api/events` when that route exists.
- Do not assume a `/stats` endpoint exists; many minimal monitors only expose stats embedded in `/api/events`.
- `nginx -t` passes after adding proxy locations.
- Dashboard loads through the public `/monitor/` path.
- Inspect the public HTML for the prefix-sensitive values, e.g. `window.MONITOR_BASE = "/monitor"` and `<script src="/monitor/static/app.js"></script>`.
- Verify public static and API paths directly: `/monitor/static/app.js`, `/monitor/api/events`, `/monitor/api/stream`.
- New matching log lines appear in the UI and trigger sound alerts.
- For auth/error parsing, perform one safe real-world injection test, e.g. a request with an intentionally invalid bearer token, then confirm:
  - the app returns 401
  - `docker logs` contains `Invalid token` and/or `ValidateUserToken: ... record not found`
  - the monitor records new `auth_error` events with critical severity

## Pitfalls learned
- Do not assume PM2 just because PM2 is installed; verify whether it runs app processes.
- Do not assume the app source exists on the host; `docker inspect ... Mounts` may show a pure image deployment.
- For pure image deployments, sidecar monitoring is usually the safest first version.
- Empty SQLite aggregates may return `null` for counts; coalesce to `0` in API responses.
- Prefix mounting under `/monitor/` needs explicit handling in frontend paths or Nginx rules.
- With current FastAPI/Starlette, `Jinja2Templates.TemplateResponse()` may expect the newer call form `TemplateResponse(request, 'index.html', context)`; using the older positional order can trigger confusing runtime errors like `TypeError: unhashable type: 'dict'`.
- After adding a `/monitor/` prefix, verify both HTML and API endpoints explicitly (`/monitor/`, `/monitor/api/events`, `/monitor/api/stream`, `/monitor/static/...`) instead of assuming root-path routes still cover them.
- Real production errors reaching `docker logs` can still be effectively missed if parser rules are too generic or in the wrong order. In one verified case, `Invalid token` and `ValidateUserToken: failed to get token: record not found` were present in container logs, but the monitor did not surface them correctly until a specific high-priority `auth_error` rule was added ahead of generic `record not found`.
- When validating a monitor fix, prefer one controlled real error injection over synthetic file writes if the collector follows `docker logs -f <container>` instead of log files.

## Why this skill exists
This approach worked well for a live deployment where:
- Nginx proxied the domain to a stock `new-api` Docker container
- PM2 was present but irrelevant
- container `Mounts` were empty
- production errors were visible in `docker logs`
- the user wanted a web error dashboard with sound alerts without touching the main service
