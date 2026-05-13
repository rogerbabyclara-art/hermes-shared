# Embedding a Puppeteer-Based Automation Flow into a CloakBrowser-Driven Electron Host

Scenario: you have an existing **standalone Node project** (V2) that automates a multi-page web flow (Azure signup, account farming, scraping) via `puppeteer.connect(browserURL)` against a fingerprint browser like ADS/MoreLogin. You want to **embed that flow** into a new Electron app (V3) where the fingerprint browser is replaced by CloakBrowser launched in a child process from the Electron main process.

This pattern is the natural follow-on to `references/electron-integration.md` once the CloakBrowser subprocess is healthy and you need to drive it from inside Electron.

## Architecture: three layers, decoupled by CDP wsEndpoint

```
┌─ Electron renderer (proxy tab UI)
│    [▶ open] [自动注册]  ← user clicks
│
├─ Electron main process (Node CJS)
│    proxy/ipc.js            ← spawns launcher.mjs, holds ACTIVE_BROWSERS Map
│    azure/index.js          ← exposes ipcMain.handle('azure:registerOne', ...)
│    azure/flow.js (copied)  ← V2's 5000-line flow, ZERO changes
│    azure/cloakbrowser.js   ← adapter implementing morelogin.js's 5-method API
│
└─ launcher.mjs (ESM subprocess, spawned per profile)
     launches CloakBrowser, captures browser.wsEndpoint(), emits as JSON line
```

Decoupling key: V2 flow.js calls `puppeteer.connect({browserURL/ws})`. Anything that yields a CDP endpoint matches the protocol — adapter just hands back the saved wsEndpoint.

## The 5-step migration recipe

### 1. Expose CDP wsEndpoint from the launcher

CloakBrowser internally uses `puppeteer.default.launch()` in WebSocket mode (not pipe), so `browser.wsEndpoint()` is always available.

```js
// launcher.mjs after launch()
let wsEndpoint = null;
try { wsEndpoint = browser.wsEndpoint(); } catch (_) {}
emit({ type: 'started', wsEndpoint });
```

### 2. Capture wsEndpoint in the ipc layer

```js
// proxy/ipc.js, in the launcher stdout parser
if (evt.type === "started" && !started) {
  started = true;
  if (evt.wsEndpoint) child._wsEndpoint = evt.wsEndpoint;  // ← attach to child obj
  resolve({ ok: true, pid: child.pid, wsEndpoint: evt.wsEndpoint || null });
}
```

Also export `ACTIVE_BROWSERS` so other modules can read it:
```js
module.exports = { register, shutdownAll, ACTIVE_BROWSERS };
```

### 3. Write the adapter (mimics V2's browser-engine module's API)

V2's `morelogin.js` / `ads.js` export exactly these 5 methods — the adapter must match shape AND return-value shape:

```js
// azure/cloakbrowser.js
function getActiveBrowsers() {
  // lazy require to avoid circular dep with ipc.js
  return require('../proxy/ipc').ACTIVE_BROWSERS;
}

async function startEnv(envId) {
  const child = getActiveBrowsers().get(String(envId));
  if (!child) throw new Error(`browser ${envId} not running — click ▶ first`);
  if (child.killed || child.exitCode !== null) throw new Error('browser exited');
  if (!child._wsEndpoint) throw new Error('wsEndpoint not captured');
  return { ws: child._wsEndpoint, browserURL: null, debugPort: null, webdriver: null };
}

async function stopEnv(_envId) { /* no-op — UI controls browser lifecycle */ }
async function isActive(envId) { /* ... */ }
async function listUsers() { /* ... */ }
async function resolveUserId(serial) { return String(serial); }

module.exports = { startEnv, stopEnv, isActive, listUsers, resolveUserId };
```

Note the semantic shift: in V2, `startEnv()` actually launches Chromium. In V3, the browser is already running (user clicked ▶); `startEnv()` just hands back the saved wsEndpoint. flow.js doesn't care — it only consumes `browserURL`/`ws`.

### 4. Copy the V2 source tree wholesale, swap one require

```bash
cp v2/src/{flow,stealth,typing,mail,profile,accounts,kana,phone,progress,alert,retry-queue}.js v3/azure/
```

Only edit needed in `flow.js`:
```diff
-const adsModule = require('./ads');
-const moreloginModule = require('./morelogin');
+const adsModule = require('./cloakbrowser');
+const moreloginModule = require('./cloakbrowser');
```

That's it. 5000+ lines stay untouched.

### 5. Wire up the IPC entry point in main.js

```js
try {
  const azureMod = require("./azure");
  azureMod.register(ipcMain, dataDir);
} catch (e) { console.error("[azure] register failed:", e); }
```

Plus preload exposure: `azureRegisterOne: (name) => ipcRenderer.invoke("azure:registerOne", name)`.

## CRITICAL PITFALL — puppeteer-core version: ESM vs CJS

**Symptom**: first invocation returns
```
{ok: false, stage: 'exception', reason: 'require() of ES Module ...'}
```

**Cause**: `puppeteer-core@25.x` is **pure ESM** (`"type": "module"`). V2 was written against `puppeteer-core@23.x` (CJS) using `require('puppeteer-core')`. When V3 hosts V2 code, the v25 install crashes V2 at first require.

**Diagnosis**:
```bash
grep -E '"type"|"main"' node_modules/puppeteer-core/package.json
# 25.x → "type": "module"
# 23.x → "type": "commonjs"
```

**Fix**: downgrade to puppeteer-core 23.x. CloakBrowser declares `peerDependency: puppeteer-core >=21.0.0` so 23 is fully compatible.
```bash
npm install puppeteer-core@23 --save
```

Also verify cloakbrowser's bundled launcher still works after downgrade — it uses its own `cloakbrowser/puppeteer` re-export, not the top-level puppeteer-core, so the downgrade does not affect launcher.mjs.

Other version trip-wires to watch on legacy puppeteer code:
- `page.waitForTimeout()` removed in puppeteer 22+. V2 code from 2024 may still use it. Grep before assuming compat.

## CRITICAL PITFALL — read the entry **AND** the orchestrator

When asked to "port V2 flow", the first instinct is to read `flow.js` (the named entry). **Don't stop there.** `flow.js` provides primitives (`runToForm1`, `runForm1Fill`, `runForm2Fill`, `detectForm3Reached`), but the actual **state machine that decides which primitive to call next** lives in `runner.js`.

For the V2 Azure flow specifically, the orchestrator is a 60-step polling loop:
```js
for (let step = 0; step < 60; step++) {
  const stage = await detectStage(page);
  if (stage === 'form3') return success;
  if (stage === 'captcha') await alertAndWait(...);    // block 5 min, Telegram alert
  if (stage === 'error_page') { recover(); reload(); errorRetries++; }
  if (stage === 'form1' && stuck > 60s) { reload(); refill(); }
  if (stage === 'form2' && !seen) { everSeenForm2 = true; runForm2Fill(); }
  await sleep(2000);
}
```

A naive linear port (`runToForm1 → form1Fill → form2Fill → detectForm3Reached`) will **fail** on:
- captcha appearing mid-login (no one to click it)
- form1 post-submit landing on `予期しないエラー` (need reload+retry)
- transient stuck states between form2 and form3 (need polling, not single check)

**Rule**: before claiming V2 ported, read the orchestrator file. For projects with a `runner.js` / `main.js` / `index.js` at the src root, that file outranks the named-entry module. The user **will** test this — they asked the boilerplate "did you actually read it?" question more than once.

## Lifecycle handoff: who owns the browser?

In V2, runner.js owns the browser fully: `startEnv` opens it, `stopEnv` closes it, `disconnect` on retry.

In V3-with-UI, **the UI's proxy tab owns the browser**:
- User clicks ▶ → browser launches, joins ACTIVE_BROWSERS
- User clicks 自动注册 → adapter hands flow.js the wsEndpoint; flow does `puppeteer.connect`
- Flow finishes → does `browser.disconnect()` (NOT `browser.close()`)
- User clicks ⏹ → ipc kills the launcher subprocess (= real close)

This means the V3 adapter's `stopEnv()` is a **no-op**. If you stop the browser inside flow, you fight the UI's "browser still showing as running" state. Let the UI control real lifecycle; flow only connects/disconnects.

Same logic for the final stage of registration: at `STAGE_PAYMENT_HIT` (Azure step 3 = payment), V2 originally stopped. V3 should `disconnect` but **leave browser open** so user can manually attach the credit card. CloakBrowser stays alive on the user's screen.

## Env vars the V2 modules expect (port them in V3 .env)

```ini
# accounts.csv path (used by accounts.js)
ACCOUNTS_CSV=D:/Projects/form-helper-v2/accounts.csv

# Roundcube webmail for verification code retrieval (mail.js)
WMHOTMAIL_BASE=http://wmhotmail.com

# Optional: Telegram alert when captcha hits (alert.js)
HERMES_TARGET=

# Azure signup landing page (flow.js)
AZURE_SIGNUP_URL=https://azure.microsoft.com/ja-jp/pricing/purchase-options/azure-account
```

Load via `require('dotenv').config({ path: ... })` in your integration entry (`azure/index.js`) BEFORE requiring `flow.js` / `accounts.js` — they read `process.env` at module load. Order matters.

## Verification ladder

Run these IN ORDER from DevTools console. Each step verifies one layer; don't skip ahead when an early step fails.

```js
// 1. Is CDP wsEndpoint captured?
api.proxyGetCDP('C001').then(console.log)
// Expect: {ok: true, wsEndpoint: 'ws://127.0.0.1:XXXXX/devtools/browser/...'}

// 2. Is the integration entry registered and can it find profiles?
api.azureRegisterOne('C999').then(console.log)
// Expect: {ok: false, stage: 'profile', reason: 'accounts.csv 找不到 serial=C999'}
//   ← integration alive, env loaded, accounts.js can read CSV, just no such row

// 3. Real run (consumes a real email, real phone field, possibly captcha alert)
api.azureRegisterOne('C001').then(console.log)
```

If step 2 returns the puppeteer-core ESM error from above, fix the version BEFORE attempting step 3.

## Anti-patterns observed

- **Don't** rewrite V2's flow.js in V3 style. It's 1979 lines of selector-specific knowledge battle-tested against real Azure UI. Touch one selector and you break a test farm worth of tuning.
- **Don't** introduce HTTP between V3 main process and V2 modules to "decouple". Native `require()` of the migrated files runs in the same V8 — no IPC overhead, single event loop, shared `ACTIVE_BROWSERS`.
- **Don't** auto-close the browser after flow finishes. The whole point of embedding in a UI is to give the user a final window to inspect/intervene/manually finish.
- **Don't** skip reading the orchestrator before claiming "I read V2's flow". The user will catch this and call it out.
