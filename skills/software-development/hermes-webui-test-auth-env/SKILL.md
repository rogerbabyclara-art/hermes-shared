---
name: hermes-webui-test-auth-env
description: Run Hermes Web UI pytest API tests correctly when auth-related environment variables affect route tests; avoid false 401s and isolate real validation failures.
version: 1.0.1
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [hermes-webui, pytest, auth, regression, tdd]
---

# Hermes Web UI test auth environment

Use this when debugging or adding Hermes Web UI API tests in environments where the shell may already export `HERMES_WEBUI_PASSWORD`.

## Why this exists

In this environment, shell-level `HERMES_WEBUI_PASSWORD` can be set even when the test suite expects auth to be disabled by default. That causes live API tests to fail with `401 Authentication required` before reaching the real route logic.

A real bug fixed with this workflow:
- `POST /api/chat` returned `500` when `session_id` was missing/empty
- but this was initially masked by `401` because auth was enabled from the shell environment

## When to use

- A Web UI API test unexpectedly returns `401`
- You expect a route-level `400/404/500` but keep hitting auth first
- `tests/test_sprint19.py::test_auth_status_disabled` fails because `auth_enabled` is unexpectedly true
- You are writing regression tests for request validation on `/api/*`

## Workflow

1. Check whether the auth env var exists without printing its value:

```bash
python - <<'PY'
import os
print('set' if 'HERMES_WEBUI_PASSWORD' in os.environ else 'unset')
PY
```

2. If set, re-run the relevant Web UI pytest command with the variable cleared for that command:

```bash
HERMES_WEBUI_PASSWORD= pytest tests/test_sprint3.py -q
```

Use the same pattern for focused runs:

```bash
HERMES_WEBUI_PASSWORD= pytest tests/test_sprint3.py -q -k chat_sync_requires_session_id
```

3. Follow TDD for API regressions:
- write the failing test first
- run the targeted test and confirm the actual failure
- only then patch the route
- re-run the focused tests
- re-run the containing test file (or broader suite) afterward

## Route-validation pattern

For POST handlers in `api/routes.py`, do not access `body["session_id"]` directly unless validation already happened.

Preferred pattern:

```python
try:
    require(body, "session_id")
except ValueError as e:
    return bad(handler, str(e))

try:
    s = get_session(body["session_id"])
except KeyError:
    return bad(handler, "Session not found", 404)
```

This keeps behavior consistent with other routes such as `/api/chat/start`:
- missing/empty `session_id` -> 400
- unknown session id -> 404
- no raw exception/500 from missing keys or failed lookup

## Example regression

Test added:

```python
def test_chat_sync_requires_session_id():
    result, status = post("/api/chat", {"session_id": "", "message": "hello"})
    assert status == 400
    assert "session_id" in result.get("error", "")
```

Fix location:
- `api/routes.py`
- `_handle_chat_sync()`

## Verification

Run at least:

```bash
HERMES_WEBUI_PASSWORD= pytest tests/test_sprint3.py -q -k 'chat_sync_requires_session_id or chat_start_requires_session_id or chat_start_requires_message'
HERMES_WEBUI_PASSWORD= pytest tests/test_sprint3.py -q
```

## Pitfalls

- If you forget to clear `HERMES_WEBUI_PASSWORD`, you may diagnose the wrong problem because auth intercepts `/api/*` first.
- A missing field and an empty string are both worth considering in request-validation tests. Clearing auth lets you see which route behavior is real.
- If a targeted test unexpectedly errors during server startup, verify whether the failure is environmental or caused by the same auth variable leaking into the test server.
