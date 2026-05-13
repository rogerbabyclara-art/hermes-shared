# Porting a Puppeteer state-machine runner into an Electron main process

Concrete pattern when you have a working standalone Node.js automation runner
(`runner.js` + `flow.js` + `alert.js` + file-based IPC) and need to host it
inside an Electron desktop app so the UI can drive single tasks, see live
progress, and unblock captchas via in-app buttons.

Real case this came from: V2 `azure-auto-reg-v2` (MoreLogin + standalone runner
+ HTTP dashboard on :7777) → V3 `form-helper-v2` (CloakBrowser + Electron
main process + renderer-driven UI).

---

## Architecture transform

```
V2 (standalone Node)                  V3 (Electron main process)
─────────────────────                 ────────────────────────────
runner.js (loops tasks.json)    →     ipcMain.handle('azure:registerOne', runOne)
flow.js   (UNCHANGED)           →     flow.js  (UNCHANGED — primitives stay)
alert.js  (rundll32 + TG +      →     alert.js (Electron Notification +
           continue-*.flag                       ipcMain events +
           file polling)                         in-memory Map)
HTTP dashboard :7777            →     [代理] tab in BrowserWindow
ads.js / morelogin.js           →     cloakbrowser.js (read in-process
  (start/stop browser via                          ACTIVE_BROWSERS Map for
   vendor API, return                              wsEndpoint; do NOT start
   debugPort, connect)                             /stop — browser owned by
                                                   another tab's lifecycle)
```

**Critical: flow.js does NOT change.** It already takes `(page, profile, envId)`
and uses `progress.update()` + `alertAndWait()` abstractions. Keep those
interfaces stable; rewire what's behind them.

---

## Where the work actually lives

### 1. Adapter layer replacing `ads.js`/`morelogin.js`

The old vendor adapters did three things: `startEnv(userId) → {debugPort}`,
`stopEnv(userId)`, and `puppeteer.connect({browserURL})`. In Electron-hosted
mode, the browser is launched and kept alive by a separate tab/IPC handler
(e.g. proxy tab's `▶ 启动` button). For single-task UI runs, the Azure runner
just **acquires** a running browser. For batch queue runs and STAGE_STUCK
retry inside flow.js, the adapter MUST also be able to open and close
browsers on demand — see "the read-only-adapter bug" below.

#### Wrong first attempt (do not copy)

```js
// azure/cloakbrowser.js — read-only, this is BROKEN for queue/retry
const { ACTIVE_BROWSERS } = require('../proxy/ipc');
async function startEnv(userId) {
  const child = ACTIVE_BROWSERS.get(userId);
  if (!child) throw new Error(`browser for ${userId} not running`);
  return { ws: child._wsEndpoint };
}
async function stopEnv(_userId) { /* no-op — owner closes it */ }
```

This compiles, passes a smoke test where the operator manually opens the
browser first, and then dies horribly the moment flow.js does a STAGE_STUCK
retry (see below).

#### Correct adapter — self-bootstrap + real stopEnv

```js
// azure/cloakbrowser.js — works for single-task AND queue/retry
const path = require('path');

async function startEnv(envId) {
  const name = String(envId);
  const { ACTIVE_BROWSERS, launchBrowser } = require('../proxy/ipc');
  const { loadProxies } = require('../proxy/store');
  let child = ACTIVE_BROWSERS.get(name);

  // Self-bootstrap: not running → launch it. Same code path serves
  // (a) runOne first call, (b) flow.js STAGE_STUCK retry after stopEnv.
  if (!child || child.killed || child.exitCode !== null) {
    console.log(`[cloakbrowser] startEnv: ${name} not running, launching`);
    const dataDir = path.resolve(__dirname, '..');
    const data = loadProxies(dataDir);
    const acc = data.accounts.find((a) => a.name === name);
    if (!acc) throw new Error(`account ${name} not found`);
    if (!acc.ip_id) throw new Error(`account ${name} has no IP bound`);
    const ip = data.ip_pool.find((x) => x.id === acc.ip_id);
    if (!ip) throw new Error(`account ${name} IP ${acc.ip_id} not in pool (dangling)`);
    const lr = await launchBrowser(acc, ip, dataDir, undefined);
    if (!lr || !lr.ok) throw new Error(`launch failed: ${lr?.error || 'unknown'}`);

    // wsEndpoint reports asynchronously — CloakBrowser cold-start +
    // launcher up-report is 3-10 seconds. Poll, don't blind-sleep.
    const t0 = Date.now();
    while (Date.now() - t0 < 30000) {
      const c = ACTIVE_BROWSERS.get(name);
      if (c && c._wsEndpoint) { child = c; break; }
      await new Promise((r) => setTimeout(r, 500));
    }
    if (!child || !child._wsEndpoint) {
      throw new Error(`wsEndpoint not reported within 30s for ${name}`);
    }
  }

  if (!child._wsEndpoint) {
    throw new Error(`${name} wsEndpoint missing (launcher didn't report)`);
  }
  return { ws: child._wsEndpoint, browserURL: null, debugPort: null };
}

async function stopEnv(envId) {
  const name = String(envId);
  try {
    const { stopBrowser, ACTIVE_BROWSERS } = require('../proxy/ipc');
    if (ACTIVE_BROWSERS && ACTIVE_BROWSERS.has(name) && typeof stopBrowser === 'function') {
      console.log(`[cloakbrowser] stopEnv: closing ${name} for real`);
      await stopBrowser(name);
    }
  } catch (e) {
    console.warn(`[cloakbrowser] stopEnv ${name} failed (swallowed):`, e?.message || e);
  }
}
```

Two things this requires the proxy/profile module to support:
1. `module.exports` must include `launchBrowser` and `stopBrowser` (not just
   register them as IPC handlers). Pure IPC works for the renderer but not
   for sibling modules in the same main process.
2. `proxy/store` (or equivalent) must export `loadProxies(dataDir)` so the
   adapter can look up account/IP without going through IPC.

#### The read-only-adapter bug (real production deadloop)

When `stopEnv` is a no-op and `startEnv` only verifies, flow.js's existing
STAGE_STUCK retry path hangs the entire bot. The retry path is:

```js
// flow.js — existing recovery logic, do not touch
if (e.code === 'STAGE_STUCK' && attempt < MAX_KMSI_RETRIES) {
  try { await browser?.disconnect(); } catch {}
  try { await ads.stopEnv(userId); } catch {}    // ← no-op in broken adapter
  await sleep(3000);
  continue;                                       // retry from top
}
```

What happens in the broken version:
1. attempt 1: `puppeteer.connect()` hangs 60s, throws STAGE_STUCK
2. recovery: `disconnect()` succeeds; `stopEnv()` is no-op; browser still running
3. attempt 2: `startEnv()` returns the **same stale wsEndpoint** from the
   still-running launcher
4. `puppeteer.connect()` hangs 60s again, throws STAGE_STUCK
5. attempt 3: same as attempt 2
6. After ~3 min of doing literally nothing, task fails with
   `puppeteer.connect 60秒超时` three times in the log

Symptom from the operator side: the bot is "stuck on opening browser",
clicking the in-app continue button does nothing (there's no captcha alert
to continue from), the browser window may even be visible and usable —
but the Node side is locked in `await puppeteer.connect()` against a dead
WebSocket. The log is a tell:

```
[flow] ✗ failed: puppeteer.connect 60秒超时
[flow] stuck_retry — stuck (1/5) — puppeteer.connect 60秒超时
[flow] ===== envId=C003 =====
[flow] starting CloakBrowser env ...
[flow] puppeteer.connect ...
[flow] ✗ failed: puppeteer.connect 60秒超时        ← same error, same duration
[flow] stuck_retry — stuck (2/5) — puppeteer.connect 60秒超时
... (3 times total then task dies)
```

#### Why "browser owned by another tab" is the wrong mental model in queue mode

The earlier version of this skill said *"the Azure runner just acquires a
running browser, never opens/closes one — the operator's proxy tab owns
lifecycle"*. That is correct for **single-task UI runs**: operator clicks ▶
on one row, wants the browser to stay open after to inspect the result, may
want to run another task on the same browser. It is **wrong** for two other
modes:

- **Batch queue mode** ("一次只开一个浏览器, 跑完关下一个开"): the queue
  must open/close browsers itself as the queue advances. Nobody else does it.
- **STAGE_STUCK retry inside flow.js**: when puppeteer.connect or some
  other startup step hangs, the recovery code in flow.js wants to fully
  kill and recreate the browser. If the adapter refuses to do that,
  flow.js retries against the same dead state forever.

The correct rule: the adapter manages the browser when nobody else does.
If the operator opened it manually via the proxy tab, the operator owns
its eventual close (the runner won't kill it because `runOne` only closes
in batch mode, see "lifecycle exception for queue mode" in the main SKILL).
If `runOne` opened it via the self-bootstrap path, `runOne` is also
responsible for closing it on batch completion. flow.js's STAGE_STUCK
recovery is always allowed to call `stopEnv()` to force a reset — it
became the orphaned browser when it disconnected, and someone has to
clean up.

#### Pitfall: page page-ready vs ws-ready

Even after `child._wsEndpoint` is reported and `puppeteer.connect` succeeds,
the browser's initial blank tab may not be fully constructed — `await
browser.pages()` may return `[]` for another 500-1500ms. Always sleep ~1.5s
after the poll loop returns the ws endpoint, before handing the page off to
flow.js. This is in the code skeleton above as `await sleep(1500)` after the
poll.

#### Pitfall: wsEndpoint vs browserURL

When flow.js does `puppeteer.connect({browserURL: ...debugPort})`, that path
needs a browserURL. CloakBrowser-style stealth Chromium typically exposes
`wsEndpoint` instead (no debug HTTP server, only the WebSocket), so the
adapter must hand back `{ws}` and flow.js must `puppeteer.connect({
browserWSEndpoint: ws})`. If flow.js still hardcodes `browserURL`, you'll
get "Failed to fetch /json/version" because there's no debug HTTP server,
just the WebSocket. Fix flow.js's connect call, don't try to spin up a CDP
HTTP endpoint.

#### Diagnostic: log the wsEndpoint at every connect attempt

Add one line to flow.js right before `puppeteer.connect`:

```js
console.log(`[flow] got ws=${(info.ws || '').slice(0, 80)}`);
const browser = await puppeteer.connect({ browserWSEndpoint: info.ws, ... });
```

This single line makes the difference between "user reports stuck for 60s,
agent guesses at 3 possible root causes" and "user pastes log, agent sees
empty ws → adapter bug" or "user pastes log, agent sees plausible ws →
kernel-side problem". Without it, every adapter-layer bug looks identical
to every kernel-layer bug.

### 2. Replacing file-flag IPC with in-memory + Electron events

V2's `alertAndWait`: 5-minute polling loop, beep + msg.exe + PowerShell
MessageBox + Telegram, polling `data/continue-{envId}.flag` file. Three
problems in Electron context:
- file-flag polling has ~3 sec latency, feels laggy in UI
- desktop popups duplicate what the Electron window already shows
- Telegram alerts redundant when the user is already looking at the app

Replacement contract:

```js
// alert.js — Electron version
const continueFlags = new Map();          // envId → true (set by UI button)
let _ipcMain, _BrowserWindow, _Notification;

function bindElectron(electron) {
  _ipcMain = electron.ipcMain;
  _BrowserWindow = electron.BrowserWindow;
  _Notification = electron.Notification;
}
function provideContinue(envId) { continueFlags.set(String(envId), true); }
function isContinued(envId)     { return continueFlags.has(String(envId)); }
function clearContinue(envId)   { continueFlags.delete(String(envId)); }

function broadcast(channel, payload) {
  for (const win of _BrowserWindow.getAllWindows()) {
    if (!win.webContents.isDestroyed()) win.webContents.send(channel, payload);
  }
}

async function alertAndWait({ title, message, envId, check,
                              timeoutMs = 3 * 60 * 1000, pollMs = 2000 }) {
  clearContinue(envId);
  if (_Notification?.isSupported?.()) {
    new _Notification({ title, body: message.slice(0, 300),
                        timeoutType: 'never' }).show();
  }
  broadcast('azure:blocking', { envId: String(envId), title, message,
                                timeoutMs, startedAt: Date.now() });

  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (isContinued(envId)) {
      clearContinue(envId);
      broadcast('azure:unblocked', { envId, reason: 'user' });
      return { reason: 'flag' };
    }
    try { if (await check()) {
      broadcast('azure:unblocked', { envId, reason: 'auto' });
      return { reason: 'check' };
    } } catch (_) {}
    await sleep(pollMs);
  }
  broadcast('azure:unblocked', { envId, reason: 'timeout' });
  throw new Error(`${Math.round(timeoutMs/60000)} 分钟超时`);
}

module.exports = { bindElectron, alertAndWait, provideContinue, ... };
```

Then in `azure/index.js`:
```js
const electron = require('electron');
const alertMod = require('./alert');
alertMod.bindElectron(electron);          // do this in register(), once

ipcMain.handle('azure:continueOne', (_e, name) => {
  alertMod.provideContinue(name);
  return { ok: true };
});
```

Preload exposes `api.azureContinueOne` and four event subscribers:
```js
onAzureProgress:  cb => { const fn=(_e,p)=>cb(p); ipcRenderer.on('azure:progress',fn); return ()=>ipcRenderer.removeListener('azure:progress',fn); },
onAzureBlocking:  ...
onAzureUnblocked: ...
onAzureResult:    ...
```

### 3. Timeout-then-reopen vs timeout-then-fail

V2 default `alertAndWait` timeout was 5 minutes (operator might be away from
desk, need time to switch to ADS browser, solve captcha, click continue in
the dashboard). In Electron mode the operator is **in the app** — 3 minutes
is enough. After timeout, the right behavior is:

```js
// In runner's captcha block
try {
  await blockOnCaptcha(page, envId, 'captcha 人机验证');  // 3 min
} catch (alertErr) {
  captchaTimeouts++;
  if (captchaTimeouts <= MAX_CAPTCHA_RETRIES) {
    try { await result.browser?.disconnect(); } catch {}
    await sleep(3000);
    break;  // jump out of inner step loop, outer attempt++ retries
  }
  return { status: 'failed', reason: 'captcha_unattended_timeout', ...};
}
```

Outer attempt retry will call `runToForm1` again, which now needs a still-
running browser to reconnect to (the user-owned proxy tab keeps it alive).
**Do NOT call `stopEnv()` here** — in V3 you don't own the browser lifecycle.

### 4. UI selection drives task input — no tasks.json

V2 read `tasks.json` (generated from `from/to` envId range) and iterated.
V3 drops this entirely: the UI table has checkboxes per row, "批量自动注册"
button → `api.azureRegisterBatch(['C001','C002',...])`. Failures stay
visible in the table; user re-checks rows and re-clicks. No `runtime.json`,
no `currentIndex`, no "resume from N", no `progress.jsonl` — the UI is the
source of truth.

This means: rip out `azureState / azureRuntime / azureTasks /
azureResetRuntime / azureStartRunner / azureStopRunner / azureMarkSuccess /
azureRetry / azureRetryAll / azureSaveRuntime` from preload.js. Don't
leave them as dangling IPC API names — they'll cause silent `invoke()` errors
when something in the renderer references them.

---

## Lessons (the painful ones)

### Read the orchestrator BEFORE copying the primitives

The first attempt at this port wrote a **linear flow** in `azure/index.js`:
`buildProfile → runToForm1 → form1Fill → form2Fill → detectForm3Reached`.
It loaded clean, all wiring worked, the user gave the green light to test —
and it would have failed on the first real envId, because the actual V2
runner is a **state-machine** with `for attempt 1..5 { for step 0..60 {
detectStage → switch{form3 | captcha | error_page | form1_stuck | form2}
} }`. The linear version has no captcha branch, no error_page recovery,
no STUCK retry. It would die at the first hiccup.

The error was reading `flow.js` (the primitives) and assuming linear use,
without first reading `runner.js` (the orchestrator). flow.js exports
`runToForm1`, `runForm1Fill`, `runForm2Fill` — it *looks* like a linear
pipeline. It is not. The runtime sequencing lives entirely in `runner.js`,
which polls `detectStage(page)` every 2 seconds and decides what to do next.

**Rule:** When porting a multi-stage automation, the file you must read
first is the one that calls the primitives in a loop, not the primitives
themselves. Names that signal "this is the orchestrator": `runner.*`,
`scheduler.*`, `main.*`, `loop.*`, `orchestrator.*`, anything ending in
`runOne`/`runAll`/`run`. Names that signal "this is a primitive":
`fill*`, `click*`, `wait*`, `detect*`, `recover*`, `submit*`. If you only
read the latter and ship something, you'll ship a linear pipeline against
a state-machine reality.

User actually called this out mid-session: *"V2 注册流程仔细看了没？"* (Did
you actually read the V2 registration flow?). The lesson is to read all
603 lines of runner.js, not just the 60-line export surface of flow.js.

### Two-layer identity: profile/browser ID vs registration/data ID

The thing the UI passes to `azure:registerOne(name)` is the **browser-profile
identity** (`C001`..`C100` in V3 = `proxies.json.accounts[].name` = the
CloakBrowser profile directory). It is NOT the same as the **registration
identity** (`accounts.csv.serial`, which holds values like `1036`, `test001`,
`456` — whatever the operator happened to drop into the CSV). The two are
joined by `proxies.json.accounts[].linked_csv_serial`, which can be empty.

If your `runOne(envId)` does `buildProfile(envId)` directly with the UI-passed
name, you'll get `profile_not_found` on the very first call against any
not-yet-bound account, because `C001` has no row in the CSV. The runner will
ship clean, lint OK, integration smoke return `{ok:false, reason:'profile not
found'}`, and you'll think it's a CSV problem.

**Rule:** at the entry of `runOne(name)`, resolve the two IDs explicitly —
**but match the user's actual data model, do not invent fancy auto-binding**.

#### Three-tier resolution (correct, name-match-first)

```js
async function runOne(name) {
  // name is the browser-profile ID (C001..C100). flow.js / cloakbrowser.js
  // use it as `envId` for browser handoff. We also need a CSV serial for
  // buildProfile().
  const r = await resolveCsvSerialForName(name);
  if (r.error) return { status:'failed', reason: r.error };
  const csvSerial = r.csvSerial;

  const profile = await buildProfile(csvSerial);
  const envId = name;
  await flow.runToForm1(envId, profile, ...);
}

async function resolveCsvSerialForName(name) {
  const all = await accountsMod.loadAll();   // async — see below

  // Tier 1 — DEFAULT — same-name direct bind.
  // When the operator named the profile after the CSV serial intentionally
  // (C001..C100 ↔ C001..C100), this is the only correct binding.
  const direct = all.find(r => String(r.serial).trim() === String(name).trim());
  if (direct) return { csvSerial: direct.serial, source: 'name_match' };

  // Tier 2 — explicit pointer fallback (only when names diverge).
  // Operator manually set proxies.json.accounts[name].linked_csv_serial
  // because the CSV row number doesn't match the profile name.
  const data = proxyStore.loadProxies(_dataDir);
  const acc = (data.accounts || []).find(a => a.name === name);
  if (acc?.linked_csv_serial) {
    const linked = all.find(r => String(r.serial).trim() === String(acc.linked_csv_serial).trim());
    if (linked) return { csvSerial: linked.serial, source: 'linked_pointer' };
  }

  // Tier 3 — error. NEVER silently pick a random "available" CSV row.
  return { error: `no CSV row matches name=${name} (no same-name serial, no linked_csv_serial)` };
}
```

#### Anti-pattern that bit us in production

```js
// ❌ DO NOT WRITE THIS. Looks helpful, ruins the operator's day.
//   Pick "any CSV row with done='' and isUsable" → silently bind C001 to test001
//   because test001 happens to be the first usable row.
const cand = all.find(r => !used.has(r.serial) && !(r.done||'').trim()
                            && r.isUsable !== false);
if (!cand) return { error: 'CSV pool exhausted' };
acc.linked_csv_serial = cand.serial;
proxyStore.saveProxies(_dataDir, data);  // ← also writes garbage to disk
return { csvSerial: cand.serial, autoBound: true };
```

What goes wrong:
- Operator's mental model: "I deleted the risky CSV rows, the remaining ones
  are mine to use." Auto-binder ignores this — it picks the first qualifying
  row, which is often a leftover test record (`test001`, `demo`, etc.).
- Once written back to `proxies.json`, the bad binding survives across
  restarts. Operator finds C001 registering under the wrong account days
  later, can't figure out why.
- Even if you remove the persistence (in-memory bind only), you've removed
  agency: the operator can no longer trust that "C050 means C050". Silent
  fuzzy matching is worse than a clear error.

#### When to use "auto-bind from pool" (almost never)

Auto-binding is only correct when **the data layer has no inherent identity**
— e.g. a pool of pre-paid phone numbers where any unused number is
interchangeable. Account-registration data is the opposite: each CSV row is
a specific human-like persona that maps to a specific browser profile by
operator intent. Treat it as a join key, not a queue.

If you genuinely need pool-style allocation, make it **explicit and
loud**: a separate "Bind from pool" button in the UI, not a silent fallback
inside `runOne`. The operator clicks it, sees the picked row, confirms.

#### Migration / cleanup script

If a previous version auto-bound, clean it up before shipping the fix:

```js
// scripts/cleanup-autobind.js — strip stale linked_csv_serial pointers
const proxyStore = require('../proxy/store');
const data = proxyStore.loadProxies(dataDir);
let stripped = 0;
for (const acc of data.accounts || []) {
  // If the linked serial matches the name, it's redundant; drop it
  // (Tier 1 will rebind it). If it points at something else, keep it
  // unless the operator confirms it was an auto-bind mistake.
  if (acc.linked_csv_serial && acc.linked_csv_serial === acc.name) {
    delete acc.linked_csv_serial;
    stripped++;
  }
}
proxyStore.saveProxies(dataDir, data);
console.log(`Stripped ${stripped} redundant same-name pointers.`);
```

Run a `grep linked_csv_serial proxies.json` first to count what's there
before deleting anything.

#### General rule for ID join logic in ported code

When porting a runner that joins two ID spaces (profile manager ↔ data
provider), the V2 author may have written a smart "auto-allocate" path
because their CSV had no naming convention. If V3's CSV does have a
convention (`serial` literally equals the profile name), the V2 logic is now
**wrong** — not just unneeded. Strip it; don't carry it forward "for
flexibility". Flexibility you don't need = silent footguns you can't see.

Memory pitfall: if you previously saved a note like "X-prefix IDs map 1:1 to
CSV serials", verify against `proxies.json` AND the actual CSV before
trusting it. The notes drift; the on-disk truth is the truth.

### Don't assume `loadAll()` is sync just because it has no `await` in the call site

The `accounts.js` module from V2 has `async function loadAll()` — Promise
returning. Calling it as `loadAll().filter(...)` blows up with
`TypeError: filter is not a function` because the Promise object has no
`.filter`. Lint won't catch this, `node -e "require('./azure/index')"` won't
catch it, the static loader is happy. It only blows up at the first
invocation.

**Rule before calling any function from a legacy CJS module:**

```bash
# Cheap check that takes 2 seconds
grep -nE "^(async )?(function|exports\.|module\.exports.+=)" module-file.js | head
```

If the line says `async function loadAll()`, it returns a Promise. If you
need the array, `await` it. If the surrounding function isn't already async,
make it async (and propagate `await` upward).

Same caveat for: `parseCsv`, `getByEnvId`, `getBySerial`, anything I/O. Spot
the `async` keyword before writing the consumer.

### Verify the port by diffing stage handlers, not by linting

`node -e "require('./azure/index')"` will load and `lint: ok` will pass
even when the entire state machine is missing. Compile-clean ≠ behaviorally
equivalent. After a port, do this check:

```bash
# Find every stage the original handles
grep -E "case '(\w+)':|if \(stage === " original/runner.js | sort -u
# Find every stage the port handles
grep -E "case '(\w+)':|if \(stage === " ported/index.js | sort -u
# Diff — any missing stage is a silent bug
```

For the V2→V3 port: 5 stages (`form3`, `captcha`, `error_page`,
`form1`, `form2`) plus the implicit `unknown` fallthrough. Plus the outer
attempt loop. Plus the inner step counter. Each missing piece is a
specific class of failure that will only show up under load.

---

## Quick reference — minimal Electron-hosted runner skeleton

```js
// azure/index.js
const path = require('path');
const electron = require('electron');
try { require('dotenv').config({ path: path.join(__dirname, '..', '.env') }); }
catch (_) {}

const alertMod = require('./alert');
const flow     = require('./flow');
const { buildProfile } = require('./profile');

function broadcast(ch, payload) {
  for (const w of electron.BrowserWindow.getAllWindows())
    if (!w.webContents.isDestroyed()) w.webContents.send(ch, payload);
}
const emit = (envId, stage, message) =>
  broadcast('azure:progress', { envId, stage, message, ts: Date.now() });

async function runOne(envId) {
  const t0 = Date.now();
  const profile = await buildProfile(envId);
  if (!profile)         return { status:'failed', reason:'profile_not_found' };
  if (!profile.isUsable) return { status:'skipped_unusable',
                                  reason: profile.warnings?.join(',') };

  const MAX_STUCK = 5, MAX_CAPTCHA = 1;
  let captchaTimeouts = 0;

  for (let attempt = 1; attempt <= MAX_STUCK; attempt++) {
    let result = null;
    try {
      result = await flow.runToForm1(envId, profile, { keepOpen: true });
      if (!result.ok) throw Object.assign(new Error(result.reason),
                                           { code: 'STAGE_STUCK' });
      await flow.runForm1Fill(result.page, profile, envId);

      let errRetries = 0, everSeenForm2 = false;
      let form1FilledAt = Date.now();

      for (let step = 0; step < 60; step++) {
        const stage = await detectStage(result.page);
        if (stage === 'form3')      return finalize(result, envId, t0);
        if (stage === 'captcha')    { /* alertMod.alertAndWait + reopen logic */ continue; }
        if (stage === 'error_page') { /* recoverFromErrorPage / reload */ continue; }
        if (stage === 'form1' && !everSeenForm2 &&
            (Date.now() - form1FilledAt) > 60000) { /* reload + refill */ continue; }
        if (stage === 'form2' && !everSeenForm2) {
          everSeenForm2 = true;
          await flow.runForm2Fill(result.page, profile, envId);
        }
        await sleep(2000);
      }
      throw Object.assign(new Error('120s no form3'), { code: 'STAGE_STUCK' });

    } catch (e) {
      if (e.code === 'STAGE_STUCK' && attempt < MAX_STUCK) {
        try { await result?.browser?.disconnect(); } catch {}
        await sleep(3000);
        continue;
      }
      return { status: 'failed', reason: e.message };
    } finally {
      try { await flow.close(result, { stopEnv: false }); } catch {}
    }
  }
  return { status: 'failed', reason: '5 attempts exhausted' };
}

function register(ipcMain) {
  alertMod.bindElectron(electron);
  ipcMain.handle('azure:registerOne', async (_e, name) => {
    const r = await runOne(name);
    broadcast('azure:result', { envId: name, ...r });
    return r;
  });
  ipcMain.handle('azure:continueOne', (_e, name) => {
    alertMod.provideContinue(name); return { ok: true };
  });
  ipcMain.handle('azure:registerBatch', async (_e, names) => {
    const results = [];
    for (const n of names || []) {
      const r = await runOne(n);
      broadcast('azure:result', { envId: n, ...r });
      results.push({ name: n, ...r });
    }
    return { ok: true, results };
  });
}
module.exports = { register };
```
