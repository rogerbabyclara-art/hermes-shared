---
name: hermes-browser-daemon-false-negative
description: "Work around agent-browser local mode false negatives where the first session command reports 'Daemon failed to start (socket: ...)' even though the daemon/socket are already alive; includes exact Hermes-side retry strategy and verification steps."
version: 1.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [hermes, browser, agent-browser, debugging, retry, local-daemon]
    related_skills: [systematic-debugging, hermes-agent]
---

# Hermes browser daemon false-negative workaround

## When to use

Use this skill when Hermes browser tools in local mode intermittently fail on the first command with:

- `Daemon failed to start (socket: /tmp/.../agent-browser.sock)`

…while evidence suggests the daemon actually started successfully.

Typical symptoms:
- `browser_navigate` fails immediately
- `browser_snapshot` returns nothing because the page never opened
- direct local `agent-browser --session <id> open <url>` may succeed on retry without changing the session/socket dir

## Root cause pattern

In some `agent-browser` 0.13.0 local-mode flows, the first non-close session command can return a false negative:
- CLI exits non-zero
- stderr says daemon failed to start
- but the daemon process and Unix socket are already alive in the same socket directory

This is a startup race / readiness-reporting issue in the browser helper, not necessarily a real startup failure.

## Safe Hermes-side workaround

Apply a minimal retry in Hermes rather than patching the third-party package first.

Target file:
- `tools/browser_tool.py`

Target function:
- the helper that shells out to local browser commands (`_run_browser_command` in this environment)

Logic:
1. Run the command normally.
2. If `returncode == 0`, return success as usual.
3. If `returncode != 0`, parse stderr/stdout into an error message.
4. Only if ALL of the following are true, retry exactly once:
   - command is in local mode
   - command is a session command (non-close)
   - error text contains exact substring `Daemon failed to start (socket:`
   - retry has not already happened
5. Re-run the same command in the same `AGENT_BROWSER_SOCKET_DIR` and with the same session id.
6. If retry succeeds, return that success result.
7. Otherwise surface the original/second failure normally.

Important constraints:
- Retry exactly once
- Do not broaden matching to unrelated daemon errors
- Keep same socket dir and same session; creating a fresh session can hide the bug instead of working around it safely
- Do not swallow non-matching errors

## Why this is low risk

- Triggers only for a very specific known false-negative message
- A real failure still fails after the single retry
- No behavior changes for successful commands or unrelated errors
- Avoids modifying vendor code or requiring a pinned downgrade

## Regression tests to add

Add tests around the local command wrapper to verify:

1. Retry on false negative
- first subprocess result: rc=1, stderr contains `Daemon failed to start (socket: ...)`
- second subprocess result: rc=0 with valid JSON
- expected: wrapper returns success and subprocess called twice

2. No retry on unrelated errors
- rc=1 with different stderr
- expected: wrapper fails immediately and subprocess called once

3. Retry only once
- two consecutive false-negative failures
- expected: wrapper stops after second attempt and returns failure

In this environment, tests were added in:
- `tests/tools/test_browser_homebrew_paths.py`

## Verification procedure

### 1) Run focused tests

From Hermes repo root:

`pytest -q tests/tools/test_browser_homebrew_paths.py -q`

Expected:
- all tests pass

### 2) Verify low-level helper behavior

Run a direct Python snippet against `_run_browser_command` using a stable temp session id and socket dir.

Expected evidence:
- first call logs the false-negative message
- Hermes logs that it is retrying once with the same session/socket_dir
- final result is `success=True`

### 3) Verify end-to-end browser tools

Use actual browser tools against a simple page such as `https://example.com`:
- `browser_navigate`
- `browser_snapshot`

Expected:
- navigate succeeds
- snapshot contains page content like `Example Domain` and `Learn more`

## Troubleshooting notes

If retry does not help:
- confirm the socket path exists after the first failure
- inspect whether daemon process is alive
- verify the command is truly local mode and not remote/browserless mode
- check whether a newer `agent-browser` release fixes the startup readiness bug upstream

If you later confirm an upstream fix:
- remove or narrow the workaround
- keep the regression tests unless upstream behavior is fully stable

## Known-good environment note

Observed in Hermes running against local `agent-browser` 0.13.0. A Hermes-side one-time retry restored:
- `browser_navigate`
- `browser_snapshot`

without requiring a package downgrade.
