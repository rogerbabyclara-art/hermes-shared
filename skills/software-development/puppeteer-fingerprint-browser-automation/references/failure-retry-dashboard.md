# Failure Tracking + Retry Queue + Dashboard Recovery

## Problem
Browser automation runner processes many environments sequentially. Some fail due to captcha, network errors, or unexpected page states. With long timeouts (6h), the entire queue stalls waiting for one stuck environment. With no retry mechanism, failed envs require manual re-entry into the task list.

## Solution: Fail Fast + Dashboard Recovery

### Three new modules

**1. `progress.js` additions**
- `failedTasks[]` — accumulates all failures with `{ envId, reason, at, browser, note }`
- `addFailed(envId, reason, extra)` — deduplicates by envId (keeps latest)
- `removeFailed(envId)` — clears when retried or marked success
- `markSuccess(envId)` — removes from failed + adds to recent as `reached_payment` with `手动标记成功`
- `snapshot()` now includes `failedTasks` array

**2. `retry-queue.js` (new file)**
- Module-level array `queue[]` — shared in-process between dashboard HTTP handler and runner event loop
- `push(envId, browser)` — returns false if already queued (dedup)
- `shift()` — FIFO pop for runner consumption
- `remove(envId)` — cancel a queued retry (e.g. when marking success)

**3. `dashboard.js` new endpoints + UI**
- `POST /api/mark-success { envId }` → calls `progress.markSuccess()` + `retryQueue.remove()`
- `POST /api/retry { envId, browser? }` → pushes to retry queue (auto-detects browser from failedTasks if not provided)
- `POST /api/retry-all` → pushes ALL failedTasks to retry queue
- UI: failed table with per-row "🔁 Retry" and "✅ Mark Success" buttons, plus global "🔁 Retry All Failed"

### Runner main loop changes

After the main task list finishes (or during the 30s idle poll), runner drains the retry queue:

```js
while (retryQueue.length() > 0) {
  const item = retryQueue.shift();
  progress.removeFailed(item.envId);
  progress.startTask(item.envId, { note: '重跑失败环境' });
  const result = await runOne(item.envId, { browser: item.browser });
  // ... record in runtime.json with isRetry: true
  if (result.status !== 'reached_payment') {
    progress.addFailed(item.envId, result.reason, { browser: item.browser });
  }
}
```

The 30s idle poll now also checks `retryQueue.length() > 0` as a wakeup condition.

### Timeout change: 6h → 60s

All 4 `alertAndWait` calls changed from `6 * 60 * 60 * 1000` to `60 * 1000`:
- `flow.js` L250: login captcha
- `flow.js` L1301: form2 captcha
- `flow.js` L1715: form1 captcha
- `runner.js` L256: runner_alertAndTakeover

On timeout, the existing `captcha_skip` error path fires → runner records failure → `progress.addFailed()` → moves to next env.

### Use case: "environment already finished but runner doesn't know"
Some envIds fail because of process restart — the browser shows an unexpected page (e.g. Azure dashboard instead of registration form). These are actually successful. The operator clicks "✅ Mark Success" in the dashboard to record `reached_payment` without re-running the flow.
