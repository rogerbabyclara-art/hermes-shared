# Cooperative pause / resume / stop control for state-machine runners

When the runner is a long-lived state machine (login → form1 → captcha → form2
→ payment, with retry/error loops) and the UI wants to let the operator
**pause anytime, resume from the current stage, or hard-stop**, you cannot
bolt this on with `kill -STOP` / process control. The Node.js event loop is
single-threaded — a `SIGSTOP` would freeze the puppeteer connection too. The
correct pattern is **cooperative checkpoints**: the runner voluntarily checks
a per-envId control flag at every awaitable boundary, and the UI flips the
flag.

This is the pattern V3 `form-helper-v2` uses for the [代理] tab's ▶/⏸/⏹
buttons. Documented here so the next port doesn't reinvent it.

---

## Three behaviors, one mechanism

| User action | UI button | Control flag | Runner behavior |
|---|---|---|---|
| Start | ▶ 注册 | (none — invokes IPC) | Enter `runOne`, status='running' |
| Pause | ⏸ 暂停 | `pauseRequested=true` | Next checkpoint sees flag → loop 200ms until `pauseRequested=false`. Browser stays connected, page state untouched. |
| Resume | ▶ 恢复 | `pauseRequested=false` | Checkpoint loop exits. State machine continues with current `detectStage()` — so it picks up wherever the page is. |
| Stop | ⏹ 停止 | `abortRequested=true` | Next checkpoint throws `AbortRunError`. `finally` block disconnects browser, status='stopped'. |

Key property: **resume is free**. The state machine is already
"look at the page, decide what to do" — it doesn't matter that it was paused
for 30 seconds. When the loop wakes up, `detectStage(page)` returns whatever
the page currently shows, and the existing `switch (stage)` handles it. No
"resume from saved checkpoint" logic needed.

---

## Module-scoped control map

```js
// azure/index.js
const RUN_STATE = new Map(); // envId -> { status, stage, lastMsg, startedAt, finishedAt,
                             //            pauseRequested, abortRequested, updatedAt }

function _ensureCtrl(envId) {
  const k = String(envId);
  let s = RUN_STATE.get(k);
  if (!s) {
    s = { status: 'idle', stage: null, lastMsg: '',
          pauseRequested: false, abortRequested: false,
          startedAt: null, finishedAt: null, updatedAt: Date.now() };
    RUN_STATE.set(k, s);
  }
  return s;
}

function broadcastRunState(envId) {
  const s = RUN_STATE.get(String(envId));
  if (!s) return;
  broadcast('azure:runState', { envId: String(envId), ...s });
}

class AbortRunError extends Error {
  constructor() { super('user_abort'); this.code = 'USER_ABORT'; }
}

async function checkControl(envId) {
  const ctrl = _ensureCtrl(envId);
  if (ctrl.abortRequested) throw new AbortRunError();
  while (ctrl.pauseRequested && !ctrl.abortRequested) {
    if (ctrl.status !== 'paused') {
      ctrl.status = 'paused';
      broadcastRunState(envId);
    }
    await sleep(200);
  }
  if (ctrl.abortRequested) throw new AbortRunError();
  if (ctrl.status === 'paused') {
    ctrl.status = 'running';
    broadcastRunState(envId);
  }
}
```

Three IPC handlers wire the UI buttons:

```js
ipcMain.handle('azure:pauseOne',  (_e, name) => {
  const c = _ensureCtrl(name); c.pauseRequested = true;
  broadcastRunState(name); return { ok: true };
});
ipcMain.handle('azure:resumeOne', (_e, name) => {
  const c = _ensureCtrl(name); c.pauseRequested = false;
  broadcastRunState(name); return { ok: true };
});
ipcMain.handle('azure:stopOne',   (_e, name) => {
  const c = _ensureCtrl(name); c.abortRequested = true;
  broadcastRunState(name); return { ok: true };
});
ipcMain.handle('azure:getRunState', () => {
  return Object.fromEntries(RUN_STATE);
});
```

---

## Where to put the checkpoints

`checkControl(envId)` must be called at every awaitable boundary that's slow
enough for the operator to "feel" the pause. Three categories:

1. **Top of each retry-loop iteration** — coarse-grained, catches abort before
   reopening the browser.
2. **Top of each state-machine step iteration** — fine-grained, catches abort
   between any two `detectStage()` calls.
3. **Before any `sleep()` longer than ~1 second** — so a 30-second wait
   doesn't ignore a pause click.

```js
async function runOne(name) {
  const ctrl = _ensureCtrl(name);
  ctrl.pauseRequested = false;       // clear stale flags from previous run
  ctrl.abortRequested = false;
  ctrl.status = 'running';
  ctrl.startedAt = Date.now();
  broadcastRunState(name);

  for (let attempt = 1; attempt <= MAX_STUCK; attempt++) {
    await checkControl(name);        // checkpoint #1
    let result = null;
    try {
      result = await flow.runToForm1(envId, profile, { keepOpen: true });
      await flow.runForm1Fill(result.page, profile, envId);

      for (let step = 0; step < 60; step++) {
        await checkControl(name);    // checkpoint #2
        const stage = await detectStage(result.page);
        // ... switch on stage ...
        await sleep(2000);
      }
    } catch (e) {
      if (e?.code === 'USER_ABORT') {
        emitProgress(envId, 'stopped', '用户停止');
        try { await result?.browser?.disconnect(); } catch {}
        ctrl.status = 'stopped';
        ctrl.finishedAt = Date.now();
        broadcastRunState(name);
        return { status: 'stopped', reason: 'user_abort' };
      }
      // ... other error handling ...
    }
  }
}
```

---

## Status terminal-state write-back — use a `finalize()` helper

Every `return { status, ... }` path must write the final status into `ctrl`,
clear control flags, AND broadcast — otherwise the UI badge sticks on
"running" forever, OR a stale `abortRequested=true` carries into the next
run. Don't inline three lines at every return — wrap them in a helper:

```js
// Single source of truth for terminal-state transition.
// Call this at EVERY return inside runOne (success / failed / stopped paths).
function finalizeCtrl(name, terminalStatus) {
  const c = _ensureCtrl(name);
  c.status = terminalStatus;        // 'success' | 'failed' | 'stopped'
  c.finishedAt = Date.now();
  c.pauseRequested = false;          // clear so re-run doesn't pause immediately
  c.abortRequested = false;          // clear so re-run doesn't abort immediately
  broadcastRunState(name);
}

// Use at every return:
finalizeCtrl(name, 'success'); return { status: 'reached_payment', ... };
finalizeCtrl(name, 'failed');  return { status: 'failed', reason: 'csv_resolve_failed' };
finalizeCtrl(name, 'stopped'); return { status: 'stopped', reason: 'user_abort' };
```

**Audit method** (run after every refactor):

```bash
# Every literal "ctrl.status = '...'" should be inside finalizeCtrl now.
# Naked "ctrl.status = 'success/failed/stopped'" at return sites is a bug.
grep -nE "ctrl\.status = '(success|failed|stopped)'" azure/index.js
# Expect: empty. All terminal writes go through finalizeCtrl.

# Cross-check: every return path is preceded by finalizeCtrl
grep -nE "return \{ status:" azure/index.js
# Each match should have a `finalizeCtrl(name, ...)` within 2 lines above.
```

Refactor recipe (one shot):

```python
# Bulk-replace inline "ctrl.status = 'X'; ctrl.finishedAt = Date.now(); broadcastRunState(name);"
# with "finalizeCtrl(name, 'X');"
import re
src = open('azure/index.js', 'r', encoding='utf-8').read()
pat = re.compile(r"ctrl\.status = '(success|failed|stopped)';\s*ctrl\.finishedAt = Date\.now\(\);\s*broadcastRunState\(name\);")
src = pat.sub(lambda m: f"finalizeCtrl(name, '{m.group(1)}');", src)
open('azure/index.js', 'w', encoding='utf-8').write(src)
```

Real refactor on form-helper-v2 hit 10 inline sites — every one was a
latent stale-flag bug waiting for a batch-stop or rapid-retry to surface.

---

## Stale flag cleanup — DO NOT blindly clear `abortRequested` on entry

Earlier guidance ("clear all stale flags at the top of `runOne`") is **wrong**
when the runner participates in a batch queue. The bug:

```js
// ❌ BUG — destroys pre-emptive stop signal
async function runOne(name) {
  const ctrl = _ensureCtrl(name);
  ctrl.pauseRequested = false;
  ctrl.abortRequested = false;   // ← user clicked "全部停止" 2 seconds ago
                                  //   while this envId was still queued.
                                  //   That signal is now gone.
  ctrl.status = 'running';
  // ... runs to completion ignoring the stop request
}
```

Scenario: operator selects 10 accounts → clicks `▶ 批量注册` → backend marks
all 10 `queued` → starts running envId 1 → operator clicks `⏹ 全部停止` →
backend sets `abortRequested=true` on envIds 2..10 (still queued). When
envId 1 finishes and the loop advances to envId 2, the `ctrl.abortRequested
= false` line on entry wipes the signal and envId 2 runs anyway.

**Correct pattern**:

- Clear `pauseRequested` on entry (you don't want a stale pause sticking).
- Do NOT clear `abortRequested` on entry — it might be a fresh pre-emptive
  stop from the batch UI. Let `checkControl()` see it and abort immediately.
- Terminal-state writes (via `finalizeCtrl`) clear both flags — so a
  *naturally finished* prior run leaves a clean slate.

```js
async function runOne(name) {
  const ctrl = _ensureCtrl(name);
  // Don't clear abortRequested — it might be a pre-emptive stop from batch UI.
  // (finalizeCtrl clears it at the END of any prior run, so a normal finish
  //  leaves a clean slate anyway.)
  ctrl.pauseRequested = false;
  ctrl.status = 'running';
  ctrl.startedAt = Date.now();
  ctrl.finishedAt = 0;
  broadcastRunState(name);

  // Immediate sentinel check — if pre-emptive stop is set, bail out now
  // before opening any browser or touching network.
  try { await checkControl(name); }
  catch (e) {
    if (e?.code === 'USER_ABORT') {
      finalizeCtrl(name, 'stopped');
      return { status: 'stopped', reason: 'aborted_before_start' };
    }
    throw e;
  }
  // ... rest of state machine
}
```

This is the only safe interleaving: clean exit (`finalizeCtrl`) clears
flags, pre-emptive stop survives until consumed, manual re-run from idle
also starts clean (last run's `finalizeCtrl` already cleared everything).

---

## UI side: three-state button group + live badge

The UI shows different button sets based on `ctrl.status`:

| Status | Buttons | Notes |
|---|---|---|
| idle / success / failed / stopped | `▶ 注册` | Disabled if browser not open yet |
| running | `⏸ 暂停` `⏹ 停止` | Pulsing animation on ⏹ |
| paused | `▶ 恢复` `⏹ 停止` | Pulsing animation on ▶ 恢复 |

Renderer subscribes to `azure:runState`:

```js
const azureRunState = new Map();
window.api.onAzureRunState((p) => {
  azureRunState.set(p.envId, p);
  // Update only this row's status cell + button group — DON'T full re-render
  const tr = document.querySelector(`tr[data-name="${CSS.escape(p.envId)}"]`);
  if (tr) {
    tr.querySelector('.ad-reg-status').innerHTML = renderBadge(p);
    tr.querySelector('.ad-action-cell').innerHTML = renderButtons(p);
  }
});
```

Status badge classes (5):

```css
.azs-running { color: blue; }    /* ⏳ prefix via ::before */
.azs-paused  { animation: pulse-pause 1.6s ease-in-out infinite; }
.azs-success { color: green; }
.azs-failed  { color: red; }
.azs-stopped { color: gray; }
```

The badge typically shows two lines: bold status word on top
(`运行中` / `已暂停` / `✅成功` / `❌失败` / `⏹已停止`) and small grey
stage name underneath (`form1_fill`, `captcha_alert`, etc.). Hover for the
last message.

On first render of the tab, call `api.azureGetRunState()` once to seed the
map — otherwise rows that started running in a previous renderer load
appear as "idle" until the next state change.

---

## Why this beats alternatives

- **kill -STOP / SIGSTOP**: freezes the puppeteer WS connection. Browser
  thinks the automation died, may close on its own. Unrecoverable.
- **Save checkpoint to disk + restart from checkpoint**: huge complexity, and
  the page state on a paused browser is *already* the checkpoint. Reloading
  loses cookies and captcha solutions.
- **Cancellation tokens (AbortController)**: works for abort, but resume
  semantics are awkward — you'd need a fresh token after every pause.
  Manual flag + while-loop is simpler and more readable.
- **Worker threads / child process per envId**: would let you actually kill
  the worker. But you lose the in-process `ACTIVE_BROWSERS` Map and have to
  pass wsEndpoint over IPC. Not worth it unless you also need parallel runs.

---

## Batch queue — `queued` status, serial execution, batch pause/stop

When the UI offers `▶ 批量注册` (select N accounts → register them serially),
the obvious implementation is `for (name of names) await runOne(name)`. That
works mechanically but produces a terrible UX:

- UI sees 10 accounts selected, clicks ▶ 批量注册, and only envId 1 shows
  status `running` — envIds 2..10 are still `idle`. Operator wonders if the
  click registered.
- If operator clicks `⏹ 全部停止` while envId 5 is running, the loop will
  still launch envIds 6..10 one by one (the `abortRequested` flag is per-
  envId, and 6..10 haven't been touched yet).

**Fix — introduce a `queued` status, mark the whole batch up-front, check
abort before each iteration:**

```js
ipcMain.handle('azure:registerBatch', async (_e, names) => {
  const queue = (names || []).slice();

  // 1. Mark the WHOLE batch queued immediately — UI shows all 10 as 🕒 排队中.
  queue.forEach((nm, idx) => {
    const c = _ensureCtrl(nm);
    c.status = 'queued';
    c.stage = 'queued';
    c.lastMsg = `排队中 #${idx + 1}/${queue.length}`;
    c.updatedAt = Date.now();
    c.pauseRequested = false;
    c.abortRequested = false;
    broadcastRunState(nm);
  });

  // 2. Serial loop with pre-emptive cancel check.
  const results = [];
  for (let i = 0; i < queue.length; i++) {
    const name = queue[i];
    const c = _ensureCtrl(name);
    // User pressed "全部停止" between iterations → skip remaining queue items.
    if (c.abortRequested && c.status === 'queued') {
      c.status = 'stopped';
      c.stage = 'cancelled';
      c.lastMsg = '批量停止前已取消';
      c.finishedAt = Date.now();
      broadcastRunState(name);
      results.push({ name, status: 'stopped', reason: 'batch_cancelled' });
      continue;
    }
    const r = await runOne(name);  // runOne flips queued → running internally
    broadcast('azure:result', { envId: String(name), ...r });
    results.push({ name, ...r });
  }
  return { ok: true, results };
});
```

**Batch control IPCs** (companion to per-envId `pauseOne`/`stopOne`):

```js
// "全部暂停" — flip pauseRequested on every running envId
ipcMain.handle('azure:pauseAll', () => {
  let n = 0;
  for (const [, c] of RUN_STATE.entries()) {
    if (c.status === 'running') { c.pauseRequested = true; n++; }
  }
  return { ok: true, paused: n };
});

// "全部恢复"
ipcMain.handle('azure:resumeAll', () => {
  let n = 0;
  for (const [, c] of RUN_STATE.entries()) {
    if (c.status === 'paused' || c.pauseRequested) { c.pauseRequested = false; n++; }
  }
  return { ok: true, resumed: n };
});

// "全部停止" — optionally scope to selected `names`, else stop all live work
ipcMain.handle('azure:stopAll', (_e, names) => {
  let n = 0;
  const targets = Array.isArray(names) && names.length
    ? names
    : Array.from(RUN_STATE.keys()).filter((k) => {
        const c = RUN_STATE.get(k);
        return c && (c.status === 'running' || c.status === 'paused' || c.status === 'queued');
      });
  for (const name of targets) {
    const c = _ensureCtrl(name);
    if (['success','failed','stopped','idle'].includes(c.status)) continue;
    c.abortRequested = true;
    c.pauseRequested = false;
    try { alertMod.provideContinue(name); } catch {}  // unblock alertAndWait
    n++;
  }
  return { ok: true, stopped: n };
});
```

**The `provideContinue` call** in `stopAll` is critical: an envId that's
blocked inside `alertAndWait` (captcha) won't see `abortRequested=true`
until its `check()` polls and resolves the promise — but `check()` polls
the page, not the control map. Calling `alertMod.provideContinue(name)`
manually resolves the alert promise so the runner exits the wait, hits
the next `checkControl()`, and aborts.

---

## UI: queued badge, error-content subtitle, busy = running/paused/queued

The badge must support 6 statuses (was 5 in the original three-state spec —
`queued` is new):

```js
function azureBadge(rs) {
  if (!rs || !rs.status || rs.status === 'idle') return '—';
  const s = rs.status;
  let label, cls;
  if (s === 'running')      { label = '正在注册';  cls = 'azs-running'; }
  else if (s === 'queued')  { label = '排队中';   cls = 'azs-queued';  }  // 🕒 grey
  else if (s === 'paused')  { label = '已暂停';   cls = 'azs-paused';  }
  else if (s === 'success') { label = '✅ 成功';  cls = 'azs-success'; }
  else if (s === 'failed')  { label = '❌ 失败';  cls = 'azs-failed';  }
  else if (s === 'stopped') { label = '⏹ 已停止'; cls = 'azs-stopped'; }
  // Subtitle: stage for live states, error message for terminal failures
  let subText;
  if (s === 'failed' || s === 'stopped') subText = rs.lastMsg || rs.stage;
  else if (s === 'queued')                subText = rs.lastMsg || rs.stage;
  else                                    subText = rs.stage;
  if (subText && subText.length > 28) subText = subText.slice(0, 26) + '…';
  // Full message in tooltip
  return `<div class="azs-badge ${cls}" title="${escapeHtml(rs.lastMsg || rs.stage)}">
            <b>${label}</b>
            ${subText ? `<span class="azs-stage">${escapeHtml(subText)}</span>` : ''}
          </div>`;
}
```

**Key UX rule for error display**: when status is `failed` / `stopped`, the
subtitle line should show **`lastMsg` (the actual error)**, not the stage
name. Operator scanning a list of 100 rows wants to see "csv_resolve_failed:
not_found" inline, not just "stuck_retry". Stage is hover-only via tooltip.

**Busy check must include queued**:

```js
function isAzureBusy(name) {
  const rs = azureRunState.get(name);
  return rs && (rs.status === 'running' || rs.status === 'paused' || rs.status === 'queued');
}
```

Used to gate `▶ 注册` button — queued accounts should show `⏹` (stop),
not `▶` (re-register), otherwise the operator double-clicks and the batch
loop fights with a fresh `runOne()` call on the same envId.

---

## Batch button handler — DO NOT pre-open browsers, let the backend open one at a time

**Old approach (rejected)**: front-end batch-opens all N browsers up-front
with `concurrency: 5`, then dispatches `azureRegisterBatch`. The intent was
"warm up the pool so registrations start faster," but it has two killer
problems:

1. **Resource explosion** — 100 CloakBrowsers do not fit on a 16 GB laptop.
   Even 10 sometimes peaks CPU enough that several fail to bind ws ports.
2. **Wasted profile loads** — the registrations run *serially* (one
   `runOne` at a time inside the backend loop), so 9 out of 10 browsers sit
   idle for the entire run waiting their turn. They consume RAM the whole
   time and risk being killed by the OS before their turn arrives.

**Correct approach — "one browser at a time, owned by the queue runner"**:

```
front-end:  optimistic queued badges  →  fire-and-forget registerBatch(names)
                                                          │
                                                          ▼
backend:    for (name of queue) {
              if (!ACTIVE_BROWSERS.has(name)) launchBrowser(name);  ← open ONE
              await runOne(name);                                    ← register
              if (ACTIVE_BROWSERS.has(name)) stopBrowser(name);     ← close it
              await sleep(1500);                                     ← let WS settle
            }
```

This means the front-end only does optimistic UI seeding and a single
fire-and-forget IPC call. No `proxyBatchOpen`, no `needBoot` calculation, no
concurrency cap to tune.

### Front-end handler — minimal

```js
$("proxy-batch-reg-start").addEventListener("click", async () => {
  if (selected.size === 0) return;
  const names = Array.from(selected);

  // Optional: warn about accounts with no IP bound (backend will fail them)
  const d = await window.api.proxyList();
  const nameToAcc = new Map((d.accounts || []).map((a) => [a.name, a]));
  const noIp = names.filter((nm) => {
    const a = nameToAcc.get(nm);
    return a && !a.ip_id;
  });
  if (noIp.length > 0) {
    if (!confirm(`${noIp.length} 个账号未绑 IP, 这些会被跳过 (失败). 继续派 ${names.length - noIp.length} 个?`)) return;
  }

  // Optimistic UI write — queued status visible before backend round-trip
  names.forEach((nm, idx) => {
    azureRunState.set(nm, {
      status: 'queued', stage: 'queued',
      lastMsg: `排队中 #${idx + 1}/${names.length}`,
      updatedAt: Date.now(),
    });
  });
  renderAccounts();

  // Fire-and-forget dispatch — backend opens browsers on demand, one at a time
  window.api.azureRegisterBatch(names).catch((e) => {
    toast("✗ 派单失败: " + (e?.message || e), "err");
  });
  toast(`✓ 已派 ${names.length} 个进队列, 串行注册 (一次只开一个浏览器)`, "ok");
});
```

### Backend — runOne opens browser on entry if missing

`runOne` needs to know how to open a browser, which means the proxy module
must export `launchBrowser` and `stopBrowser` (not just register them as IPC
handlers). Patch the proxy module's exports:

```js
// proxy/ipc.js
module.exports = { register, shutdownAll, ACTIVE_BROWSERS, launchBrowser, stopBrowser };
```

Then `runOne` checks `ACTIVE_BROWSERS` and opens if missing:

```js
// azure/index.js — inside runOne, after profile is ready, before flow.runToForm1
const proxyIpc = require('../proxy/ipc');
if (!proxyIpc.ACTIVE_BROWSERS.has(name)) {
  emitProgress(name, 'browser_boot', '浏览器未启动, 现在打开');
  const { loadProxies } = require('../proxy/store');
  const data = loadProxies(_dataDir);
  const acc = data.accounts.find((a) => a.name === name);
  if (!acc?.ip_id) {
    finalizeCtrl(name, 'failed');
    return { status: 'failed', reason: 'no_ip' };
  }
  const ip = data.ip_pool.find((x) => x.id === acc.ip_id);
  if (!ip) {
    finalizeCtrl(name, 'failed');
    return { status: 'failed', reason: 'ip_dangling' };  // see below
  }
  const lr = await proxyIpc.launchBrowser(acc, ip, _dataDir, undefined);
  if (!lr?.ok) {
    finalizeCtrl(name, 'failed');
    return { status: 'failed', reason: 'launch_failed', detail: lr?.error };
  }
  await sleep(1500);  // let wsEndpoint settle before flow.js connects
}
// ... continues into flow.runToForm1, etc.
```

### Backend — close browser after each runOne in batch mode

The batch loop wraps every `await runOne(name)` with a post-run close, so
exactly one browser exists at a time:

```js
ipcMain.handle('azure:registerBatch', async (_e, names) => {
  const queue = (names || []).slice();
  queue.forEach((nm, idx) => { /* seed queued status as before */ });

  const results = [];
  for (let i = 0; i < queue.length; i++) {
    const name = queue[i];
    const c = _ensureCtrl(name);
    if (c.abortRequested && c.status === 'queued') {
      // batch-stopped before this envId's turn
      c.status = 'stopped'; c.lastMsg = '批量停止前已取消';
      c.finishedAt = Date.now(); broadcastRunState(name);
      results.push({ name, status: 'stopped', reason: 'batch_cancelled' });
      continue;
    }
    const r = await runOne(name);  // opens browser internally if missing
    broadcast('azure:result', { envId: String(name), ...r });
    results.push({ name, ...r });

    // ★ Close this browser before starting the next one — frees RAM + ws port
    try {
      const proxyIpc = require('../proxy/ipc');
      if (proxyIpc.ACTIVE_BROWSERS.has(name)) {
        emitProgress(name, 'browser_close', '批量模式: 跑完关浏览器');
        await proxyIpc.stopBrowser(name);
      }
    } catch (e) {
      console.warn(`[batch] stopBrowser ${name} failed:`, e?.message || e);
    }
    await sleep(1500);  // let resources release before next browser starts
  }
  return { ok: true, results };
});
```

**Single-shot `registerOne` does NOT auto-close** — operator may want to
inspect the browser after a one-off registration. Only the batch loop closes.

### Dangling IP-id after "delete all IPs"

If the operator clears the IP pool but keeps `accounts[].ip_id` references
intact (so re-importing the same IPs auto-restores bindings), some accounts
will reach `runOne` with `ip_id` set but `ip_pool.find(...) === undefined`.
That's a **dangling reference**, not a missing-IP error. Report it
separately as `reason: 'ip_dangling'` so the UI can prompt "重新分配 IP"
rather than "去绑 IP". See the "delete all IPs preserves account ip_id"
decision in the FormHelper architecture notes.

### Why this is better than pre-opening

- **RAM ceiling is one CloakBrowser, not N.** Run 1000 accounts overnight on
  a 16 GB laptop without OOM.
- **No concurrency tuning.** `proxyBatchOpen(needBoot, {concurrency: 5})`
  required guessing the right number per machine. Now it's always 1.
- **Stale-browser problem solved.** Pre-opened browsers that wait 30+
  minutes for their turn can get killed by Windows defender, lose proxy
  sessions, or have stale cookies. Open-on-demand is always fresh.
- **Failure isolation.** If a launch fails, only that account fails — the
  next launch is independent. With pre-open, one bad launch can cascade.

**Don't `await azureRegisterBatch(names)`** — it blocks for the entire run
(could be hours for 100 accounts). The UI must remain interactive so the
operator can click pause/stop. The promise's `result` array is redundant
anyway — every envId's outcome was already broadcast via `azure:result`.

---

## Pitfall checklist

- [ ] `checkControl` called at the **top** of every loop iteration, not at
  the bottom. Bottom-of-loop misses the case where pause was clicked while
  the loop body was running.
- [ ] Every terminal-state `return` inside `runOne` goes through
  `finalizeCtrl(name, 'success'|'failed'|'stopped')`. Audit with
  `grep -nE "ctrl\.status = '(success|failed|stopped)'" azure/index.js` —
  expect empty (all writes routed through helper).
- [ ] `runOne` entry does NOT clear `abortRequested` (only `pauseRequested`).
  Clearing both wipes pre-emptive stop signals from batch UI. A `checkControl`
  sentinel at the very top of `runOne` consumes any pending abort.
- [ ] `AbortRunError` carries `code: 'USER_ABORT'` so the `catch` block can
  distinguish it from `STAGE_STUCK`. Without the code, it falls into the
  retry path and the abort loses.
- [ ] Renderer subscribes to `azure:runState` AND calls `getRunState()` once
  on mount. Without the seed call, rows are blank until first change.
- [ ] `isAzureBusy()` returns true for `queued` AND `running`/`paused` —
  otherwise the row shows `▶ 注册` for queued accounts and a double-click
  spawns a parallel `runOne` fighting the batch loop.
- [ ] Batch handler does optimistic local `azureRunState.set(nm, {status:
  'queued'})` BEFORE invoking `azureRegisterBatch` — UI shows the queue
  state without waiting for backend round-trip.
- [ ] Batch handler fire-and-forgets `azureRegisterBatch(names)` (no await).
  Awaiting blocks the renderer for the entire batch duration.
- [ ] `stopAll` calls `alertMod.provideContinue(name)` for every abort
  target — otherwise envIds blocked in `alertAndWait` can't exit until the
  alert's `check()` resolves.
- [ ] Badge subtitle for `failed`/`stopped` shows **`lastMsg`** (error text),
  not stage. Operator scanning 100 rows needs the error inline.
- [ ] CSS pulse animation only on `paused` and `resume`-eligible state, not
  on success/failed — those should be static.
- [ ] Browser is owned by another tab (proxy tab's ▶ 启动), so the **stop**
  path disconnects but does **not** call `stopEnv` / close the
  CloakBrowser process. Pausing the runner ≠ closing the browser.
