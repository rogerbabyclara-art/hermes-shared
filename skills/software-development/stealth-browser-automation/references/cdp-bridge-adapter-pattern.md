# CDP-Bridge Adapter Pattern — keep the old automation, swap the browser

Alternative to a full rewrite (`migration-from-fingerprint-browsers.md`). Use this when you have a working MoreLogin/ADS-based automation (5000+ lines of `flow.js` etc.) and want to drop the fingerprint browser dependency **without rewriting any business logic**.

## When this pattern beats the full-rewrite migration

| Situation | Full rewrite (`migration-from-fingerprint-browsers.md`) | Adapter shim (this doc) |
|---|---|---|
| Old code is <500 LOC, simple | ✅ rewrite is cheap | ❌ overkill |
| Old code is 1000–10000 LOC, battle-tested | ❌ huge regression risk | ✅ zero-risk swap |
| You want to A/B compare old vs new on the same flow | ❌ can't, you deleted old | ✅ just toggle adapter |
| Browser is launched/managed by a separate UI (Electron, dashboard) | ❌ rewrite owns lifecycle | ✅ adapter respects UI ownership |
| The fingerprint browser API is what's flaky, the flow code works | ✅ kills both birds | ✅ keeps the working half |

Rule of thumb: if your `flow.js` already passes the bot detection you care about and the pain is **only** the fingerprint browser layer (API timeouts, per-profile cost, app-must-be-running), use the adapter shim. Save the full rewrite for when stealth itself is what's failing.

## The core insight: CloakBrowser already exposes a CDP WebSocket endpoint

CloakBrowser's puppeteer wrapper (`cloakbrowser/puppeteer`) internally calls vanilla `puppeteer.default.launch()`. Puppeteer-core defaults to WebSocket transport, which means the returned `browser` object has a working `browser.wsEndpoint()` returning `ws://127.0.0.1:<random>/devtools/browser/<uuid>`.

You do NOT need `--remote-debugging-port=N` Chromium flag. You do NOT need to pre-allocate a port. Just call `browser.wsEndpoint()` after `launch()` and you have the CDP URL.

Verify on your install:
```javascript
const { launch } = require('cloakbrowser/puppeteer');
const b = await launch({ headless: false, humanize: true });
console.log(b.wsEndpoint());  // ws://127.0.0.1:NNNNN/devtools/browser/...
```

If this prints a `ws://` URL, the adapter pattern is viable. (If it throws "wsEndpoint is not a function", you're on a pipe-mode launch — pass `pipe: false` or check your wrapper version.)

## Architecture

```
┌────────────────────────────────┐
│ Old flow.js (UNTOUCHED)        │
│   require('./morelogin')       │ ← change this line ONLY
│   ads.startEnv(envId) → { ws } │
│   puppeteer.connect({           │
│     browserWSEndpoint: ws       │
│   })                            │
└─────────────┬──────────────────┘
              │
              ▼
┌────────────────────────────────┐
│ cloakbrowser-adapter.js (NEW)  │
│   Mimics morelogin.js exactly: │
│   - startEnv(id) → { ws }      │
│   - stopEnv(id) → no-op        │
│   - isActive(id)               │
│   - listUsers()                │
│   - resolveUserId(serial)      │
└─────────────┬──────────────────┘
              │ reads ACTIVE_BROWSERS map or
              │ calls launcher API
              ▼
┌────────────────────────────────┐
│ CloakBrowser launcher           │
│   emits wsEndpoint via stdout   │
│   keeps browser alive           │
└────────────────────────────────┘
```

## Step 1 — launcher emits wsEndpoint

Wherever you call `launch()` and `console.log(JSON.stringify({type:'started'}))`, grab the endpoint and include it. CloakBrowser uses WS transport by default so this always works:

```javascript
const browser = await launch(launchOpts);
let wsEndpoint = null;
try { wsEndpoint = browser.wsEndpoint(); } catch (_) {}
emit({ type: 'started', wsEndpoint });
```

Pitfall: if you previously suppressed the wsEndpoint capture (some samples just log `{type:'started'}` with no payload), the host has no way to recover it later without restarting the browser. Always include it at start.

## Step 2 — host stores wsEndpoint on the child handle

In the host (Electron main or Node parent) parser of launcher stdout:

```javascript
const evt = JSON.parse(line);
if (evt.type === 'started') {
  child._wsEndpoint = evt.wsEndpoint || null;
  resolve({ ok: true, pid: child.pid, wsEndpoint: evt.wsEndpoint });
}
```

Keep it on the `ChildProcess` instance itself, not a separate map keyed by name — survives whatever lifecycle accounting you do. If the child dies, the property dies with it.

Expose two read paths:
- `proxy:list` (or your equivalent) — include `_ws_endpoint` on every running entry, useful for status UI
- A dedicated `proxy:getCDP(name)` IPC handler that returns `{ ok, wsEndpoint, pid }` and validates the child is still alive — what the adapter actually calls

## Step 3 — write the adapter shim (template)

Look at the legacy `morelogin.js` or `ads.js` you're replacing. Note its **exact** function signatures and return shapes. Mirror them exactly. Example for MoreLogin:

```javascript
// cloakbrowser-adapter.js — drop-in replacement for morelogin.js

// Lazy require avoids circular dep with the ipc module that owns ACTIVE_BROWSERS
function getActive() {
  return require('../proxy/ipc').ACTIVE_BROWSERS;
}

async function startEnv(envId) {
  const name = String(envId);
  const child = getActive().get(name);
  if (!child) throw new Error(`browser ${name} not running, start it from UI first`);
  if (child.killed || child.exitCode !== null) throw new Error(`browser ${name} dead`);
  if (!child._wsEndpoint) throw new Error(`browser ${name} wsEndpoint not captured`);
  return {
    ws: child._wsEndpoint,   // matches morelogin.js return shape
    browserURL: null,
    debugPort: null,
    webdriver: null,
  };
}

async function stopEnv(_envId) {
  // V3 model: UI owns browser lifetime, adapter is read-only.
  // flow.js calls stopEnv to "rotate IP" but in V3 that's a separate UI action,
  // so no-op here is correct — let flow.js's browser.disconnect() do its thing.
}

async function isActive(envId) {
  const child = getActive().get(String(envId));
  const live = child && !child.killed && child.exitCode === null && child._wsEndpoint;
  return { status: live ? 'Active' : 'Inactive' };
}

async function listUsers(_page, _pageSize) {
  const list = [];
  for (const [name, child] of getActive().entries()) {
    if (child.killed || child.exitCode !== null) continue;
    list.push({ user_id: name, serial_number: name, name });
  }
  return { list, total: list.length };
}

async function resolveUserId(serial) { return String(serial); }

module.exports = { startEnv, stopEnv, isActive, listUsers, resolveUserId };
```

## Step 4 — point flow.js at the adapter

In `flow.js` (and `runner.js`, anywhere that requires the browser layer):

```diff
- const adsModule = require('./ads');
- const moreloginModule = require('./morelogin');
+ const adsModule = require('./cloakbrowser-adapter');
+ const moreloginModule = require('./cloakbrowser-adapter');
```

Both require the same module so the runtime `BROWSER_ENGINE` env-var switch becomes a no-op. The rest of `flow.js` doesn't change.

## Critical semantic shift: lifecycle ownership

This is the trap. In the old design, `flow.js` calls `startEnv` to **launch** the browser and `stopEnv` to **kill** it. In the adapter design, that's wrong — the UI launches the browser when the operator clicks ▶, and only the UI kills it.

Consequences for `flow.js`:
- `startEnv` must be called AFTER the UI has launched the browser; otherwise the adapter throws. Document this as a precondition.
- `stopEnv` is a no-op. Code in `flow.js` like "if KMSI fails 3 times, stopEnv + retry" no longer rotates the browser — the next iteration will reuse the same browser. Either accept this (the old retry path is dead code) or have `flow.js` instead signal the UI ("please rotate this account's browser") through a separate channel.
- `browser.disconnect()` in `flow.js` still works — it disconnects the puppeteer client but the browser keeps running. This is the desired behavior — the operator sees the browser idle on the success page and decides what to do next.

If your flow code intermixes `browser.disconnect()` and `stopEnv()` for different cleanup paths, audit each call site. `disconnect` = drop the CDP client, browser stays up. `stopEnv` (now no-op) = used to kill the browser. After the adapter, both look the same to flow.js, but only `disconnect` actually does anything.

## Where to wire the entry point

If the host is Electron, expose a single `ipcMain.handle('azure:registerOne', name => ...)` that:
1. Loads `.env` (CSV path, etc.) if business code needs it
2. Calls `buildProfile(name)` from your existing profile module
3. Calls `flow.runToForm1(name, profile, { keepOpen: true })`
4. Chains through `runForm1Fill`, `runForm2Fill`, `detectForm3Reached`
5. Returns `{ ok, stage, reason?, finalUrl? }` to renderer

`keepOpen: true` is mandatory in this model — the adapter can't restart the browser, so flow code must not destroy it on its way out.

Always have a smoke-test path before the real run: pass a known-bad name (e.g. `C999` that doesn't exist in CSV) and verify the chain returns `{ok:false, stage:'profile'}` quickly. Confirms the IPC + adapter + module loading all work without spending a real email/phone.

## Pitfalls specific to this pattern

1. **Circular require if adapter lives inside the proxy/IPC module's directory tree** — `proxy/ipc.js` registers IPC handlers and exports `ACTIVE_BROWSERS`; `azure/cloakbrowser-adapter.js` requires `proxy/ipc`. If `proxy/ipc` ever requires anything from `azure/`, you have a cycle. Solution: lazy-require inside `getActive()` (already shown above) — by the time it's called, both modules are fully loaded.

2. **Adapter returns `ws` field, flow.js might expect `browserURL`** — old MoreLogin code branches on `if (info.ws) connectOpts.browserWSEndpoint = info.ws; else connectOpts.browserURL = info.browserURL;`. CloakBrowser returns a WS URL, so populate `ws` and leave `browserURL` null. Don't swap them — `browserURL` expects `http://host:port`, not `ws://...`, and puppeteer.connect will hang trying to GET `/json/version` from a WebSocket.

3. **Adapter is called before the UI launched the browser** — operator clicks "register" before clicking "open browser". Throw a clear error: "start browser from [proxy] tab first" — don't silently auto-launch from the adapter, because then the UI's lock/status state will be wrong and orphans become possible.

4. **Long-running adapter sessions and wsEndpoint staleness** — if the browser is restarted by the UI mid-flow, the wsEndpoint on the child handle is the new one but any `puppeteer.connect()` already established by flow.js still points at the dead old one. Either snapshot the endpoint at the start of the flow and accept that mid-flow restarts kill the flow, or have the UI propagate "browser restarted" events back into flow code and let it `disconnect + reconnect`. The former is simpler; the latter is needed only if mid-flow IP rotation is part of your design.

5. **Don't put `puppeteer.connect()` inside the adapter** — let `flow.js` call connect itself. The adapter's job is "return the address"; the flow's job is "establish the session". Keeping these separate means the adapter stays a 50-line shim that's trivially correct, and the flow's connect-timeout / stealth-patch / disconnect logic stays where it always was.
