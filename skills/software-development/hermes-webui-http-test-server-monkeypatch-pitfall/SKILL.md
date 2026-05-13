---
name: hermes-webui-http-test-server-monkeypatch-pitfall
description: Diagnose Hermes Web UI pytest failures when tests monkeypatch api.config locally but exercise routes over HTTP against the session-scoped server process.
version: 1.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [hermes-webui, pytest, test-architecture, debugging, regression]
    related_skills: [hermes-webui-test-auth-env, systematic-debugging, hermes-investigate]
---

# Hermes Web UI HTTP test server monkeypatch pitfall

Use this when a Hermes Web UI pytest test changes `api.config` with `monkeypatch`, but the assertions hit the app through HTTP using the shared test server from `tests/conftest.py`.

## Core lesson

A pytest `monkeypatch` inside the test process does not affect the already-running session-scoped `server.py` subprocess started by `tests/conftest.py`.

This creates a common false assumption:
- the test patches `api.config.SETTINGS_FILE` or `_get_config_path`
- then sends `POST /api/settings` to `BASE`
- then expects the server to write to the patched temporary file
- but the server is a separate process and still uses its own environment and import state

Result: route behavior may look wrong when the real problem is test architecture.

## Symptom pattern

Typical failure signatures:
- `FileNotFoundError` reading a tmp `config.yaml` that the test expected the server to create
- `config.reload_config()` in the test process does not show route-written values
- a newly added route exists in source but HTTP still returns `404` because the shared server process is still running older code
- confusion between module-local state in the pytest process and runtime state inside the server subprocess

## Where this comes from in Hermes Web UI

`tests/conftest.py` starts a session-scoped isolated Web UI server process with env vars like:
- `HERMES_WEBUI_PORT`
- `HERMES_WEBUI_STATE_DIR`
- `HERMES_HOME`

Tests then talk to it via `tests._pytest_port.BASE` over HTTP.

That means route execution happens inside the server subprocess, not in the same Python interpreter as the test function.

## Diagnostic workflow

1. Confirm whether the test is using HTTP helpers like:
   - `post("/api/settings", ...)`
   - `get("/api/settings")`
   - `BASE + path`

2. Check whether the fixture uses `monkeypatch.setattr(...)` on module variables such as:
   - `api.config.SETTINGS_FILE`
   - `api.config._get_config_path`

3. If both are true, assume process-boundary mismatch first.

4. Inspect `tests/conftest.py` to verify the server is session-scoped and started as a subprocess.

5. If a route was just added, remember the running shared test server may still be on old code until the pytest session/server restarts.

## Safe fix patterns

Choose one of these explicitly:

### Pattern A: Pure in-process unit/integration test

Do not use HTTP to the shared server.
Instead, call the route helper or save/config function directly in the same interpreter where monkeypatch is applied.

Use this when you want to verify:
- file-path overrides
- config writer behavior
- cache reload behavior
- exact internal side effects

### Pattern B: Real HTTP test against subprocess

Do not rely on monkeypatch for server-side paths.
Instead, pass the needed paths/state through environment variables before the server subprocess starts, or build a dedicated server fixture that starts a fresh subprocess with those env vars.

Use this when you want to verify:
- end-to-end HTTP contract
- route auth behavior
- actual request/response payloads
- persistence using the server's real runtime config

## Rule of thumb

If your assertion is about files written by the HTTP server, configure the server process.
If your assertion is about Python-side helpers and internal state, stay in-process.
Do not mix the two and assume monkeypatch crosses the process boundary.

## Extra pitfall: stale server code

Because the Web UI test server is session-scoped, adding a new route in source does not guarantee the currently running test server has it loaded.
If a newly added endpoint still returns `404` even though the source contains the route, restart the pytest session or ensure the server subprocess is recreated.

## Example failure cluster this skill is based on

A third-party settings test did all of the following:
- monkeypatched `api.config.SETTINGS_FILE`
- monkeypatched `api.config._get_config_path`
- used HTTP `POST /api/settings`
- then read a tmp `config.yaml`

Observed failures:
- tmp `config.yaml` missing
- `live_cfg["model"]` missing after reload
- `/api/settings/test-connection` appeared to return `404`

Most likely interpretation:
- the route was executing in the shared server subprocess, not the patched test interpreter
- the running server also had not yet been restarted onto the latest source

But there is an extra trap specific to connectivity tests:
- `POST /api/settings/test-connection` may itself be working correctly while the upstream probe URL returns an HTTP 404
- for example, `https://example.com/v1/models` returns an Example Domain HTML 404 page, so if the route forwards upstream status codes directly, the test will observe `404`
- this can be misread as “route missing” even though the route exists and handled the request

## Extra pitfall: placeholder probe URLs are not neutral

When a connectivity-test endpoint performs a real network probe, do not assume documentation domains behave like inert success stubs.

In particular:
- `https://example.com/v1/models` returns a real HTTP 404 response
- if your endpoint simply proxies upstream HTTP errors, your API test will also receive 404
- this makes endpoint-existence debugging misleading

Safer patterns for tests:
- use a local fake HTTP server that returns `{ "data": [] }`
- or mock/stub the probe call in-process
- or explicitly special-case the placeholder URL if the test contract only checks response shape, not real connectivity

Diagnostic check:
- if source contains the route, manually hit the endpoint once and inspect the JSON body
- if the body contains upstream HTML or upstream error text, the problem is probe behavior, not route registration

## Verification checklist

Before blaming route code, verify:
- Is the test using HTTP to the shared server?
- Is monkeypatch only applied in the pytest process?
- Does `tests/conftest.py` start a subprocess server?
- Has the test server been restarted since the route was added?

If yes, fix the test structure first.
