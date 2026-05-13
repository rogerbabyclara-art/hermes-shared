# Embedding CloakBrowser inside an Electron app

## The core problem

`cloakbrowser` (Node version, 0.3.x) is **ESM-only**:

```json
// node_modules/cloakbrowser/package.json
{ "type": "module", "exports": { ".": { "import": "./dist/index.js" } } }
```

Electron's main process runs CommonJS by default. A naive `require('cloakbrowser/puppeteer')` blows up with:

```
Error [ERR_PACKAGE_PATH_NOT_EXPORTED]: No "exports" main defined
```

Dynamic `await import('cloakbrowser/puppeteer')` works but forces the entire IPC handler chain to be async and the browser lifecycle to share Electron's event loop — closing the Electron window can tear down the browser, and a crashed browser bubbles into the main process.

## The clean pattern: ESM launcher subprocess

Spawn a separate Node process running a `.mjs` launcher. Talk to it over stdout with one JSON event per line. This gives you:

- Browser process independent of Electron — closing the app doesn't kill the browser
- No ESM/CJS interop pain — the subprocess is pure ESM
- Cheap to scale — one subprocess per active account, killable individually
- Clear failure boundary — subprocess exit code + stderr separate from app crashes

### Layout

```
form-helper-v2/
├── main.js                  # Electron main (CJS)
├── preload.js               # contextBridge → window.api
├── proxy/
│   ├── launcher.mjs         # ESM, spawned per browser instance
│   ├── store.js             # proxies.json read/write (CJS)
│   └── ipc.js               # IPC handlers + spawn manager (CJS)
└── renderer/
    ├── proxy-tab.js         # UI logic
    └── index.html           # tab + page + modals
```

### launcher.mjs skeleton

```javascript
import { launch } from 'cloakbrowser/puppeteer';

const ACCOUNT_NAME = process.env.ACCOUNT_NAME;
const PROXY_URL = process.env.PROXY_URL;
const FINGERPRINT = parseInt(process.env.FINGERPRINT, 10);
const USER_DATA_DIR = process.env.USER_DATA_DIR;
const START_URL = process.env.START_URL || 'https://ipinfo.io/';

const emit = (o) => console.log(JSON.stringify(o));

(async () => {
  try {
    const browser = await launch({
      headless: false,
      humanize: true,
      geoip: true,
      proxy: PROXY_URL,
      userDataDir: USER_DATA_DIR,
      args: [`--fingerprint=${FINGERPRINT}`],
    });
    // Expose CDP wsEndpoint so external automation can re-attach via puppeteer.connect.
    // cloakbrowser internally calls puppeteer.default.launch() in default WS mode,
    // so browser.wsEndpoint() always returns 'ws://127.0.0.1:<port>/devtools/browser/<uuid>'.
    // Without this, external flows (e.g. ported reg scripts that used MoreLogin's
    // browserURL) have no way to drive the running browser — you'd be stuck routing
    // every page action through the launcher subprocess, which is unworkable.
    let wsEndpoint = null;
    try { wsEndpoint = browser.wsEndpoint(); } catch (_) {}
    emit({ type: 'started', wsEndpoint });

    const page = (await browser.pages())[0] || await browser.newPage();
    await page.goto(START_URL, { timeout: 60000, waitUntil: 'domcontentloaded' });

    browser.on('disconnected', () => {
      emit({ type: 'closed' });
      process.exit(0);
    });
    setInterval(() => {}, 60000); // keepalive
  } catch (e) {
    emit({ type: 'error', msg: String(e).slice(0, 500) });
    process.exit(1);
  }
})();
```

### Parent-side spawn (CJS, in main.js or ipc.js)

```javascript
const { spawn } = require('child_process');
const path = require('path');

function launchBrowser(account, config, dataDir) {
  return new Promise((resolve) => {
    const child = spawn(process.execPath, [path.join(__dirname, 'launcher.mjs')], {
      cwd: path.dirname(__dirname),  // project root, so node_modules resolves
      env: {
        ...process.env,
        ACCOUNT_NAME: account.name,
        PROXY_URL: buildProxyUrl(account, config),
        FINGERPRINT: String(account.fingerprint),
        USER_DATA_DIR: path.join(dataDir, 'cloak-profiles', account.name),
      },
      stdio: ['ignore', 'pipe', 'pipe'],
      windowsHide: true,
    });

    let settled = false;
    let buf = '';
    child.stdout.on('data', (c) => {
      buf += c.toString('utf8');
      let idx;
      while ((idx = buf.indexOf('\n')) >= 0) {
        const line = buf.slice(0, idx).trim();
        buf = buf.slice(idx + 1);
        if (!line) continue;
        try {
          const evt = JSON.parse(line);
          if (evt.type === 'started' && !settled) { settled = true; resolve({ ok: true, pid: child.pid }); }
          else if (evt.type === 'error' && !settled) { settled = true; resolve({ ok: false, error: evt.msg }); }
        } catch (_) {}
      }
    });
    child.on('exit', (code) => { if (!settled) resolve({ ok: false, error: `exit ${code}` }); });
  });
}
```

Track active children in a `Map<accountName, ChildProcess>` so the UI can kill individual browsers.

### Why env vars not argv

Proxy URLs contain `:`, `@`, `/` — quoting them in argv across shells (cmd vs powershell vs git-bash spawning) is fragile. Env vars are pass-through binary-safe.

## Pitfalls

1. **`mmdb-lib` is a peer dep** — Node version of CloakBrowser with `geoip: true` throws `Error: mmdb-lib is required for geoip: true. Install it with: npm install mmdb-lib`. Plain `npm install cloakbrowser` does not pull it. Always run:
   ```
   npm install cloakbrowser puppeteer-core mmdb-lib
   ```
   This is the **Node** equivalent of the Python `cloakbrowser[geoip]` extra.

2. **Use `process.execPath`** to spawn the launcher, not bare `'node'`. In a packaged Electron app, PATH may not have `node`, but `process.execPath` always points to the embedded Node runtime.

3. **`cwd` matters for module resolution** — set it to project root (where `node_modules/` lives), not to `__dirname` of the launcher file. Otherwise `import 'cloakbrowser/puppeteer'` fails to resolve.

4. **One JSON event per line** — child stdout is chunked. Buffer until `\n`, parse each line. Don't try to `JSON.parse(chunk)` directly.

5. **Don't `detached: true`** unless you also want browser to outlive parent crash — fine for some flows, but on Windows it spawns a console window even with `windowsHide`. Default `detached: false` is usually what you want.

6. **`userDataDir` per account** — store under app dataDir, e.g. `dataDir/cloak-profiles/<account_name>/`. Don't share across accounts or fingerprints leak between identities.

7. **`socks-proxy-agent` v8+ and `https-proxy-agent` v7+ are ESM-only** — same trap as `cloakbrowser` itself. Inside CJS Electron main, plain `require('socks-proxy-agent')` succeeds at import time on some Node versions but throws at runtime, or fails outright with `ERR_REQUIRE_ESM`. **Use cached dynamic import** in the testProxy helper:
   ```javascript
   let _socksMod, _httpsMod;
   async function getSocksAgent(url) {
     if (!_socksMod) _socksMod = await import('socks-proxy-agent');
     return new _socksMod.SocksProxyAgent(url);
   }
   async function getHttpsAgent(url) {
     if (!_httpsMod) _httpsMod = await import('https-proxy-agent');
     return new _httpsMod.HttpsProxyAgent(url);
   }
   ```
   Cache the module on first import to avoid re-loading on every proxy test (200 tests = 200 ESM resolutions otherwise). Pin older CJS-compatible versions (`socks-proxy-agent@7`, `https-proxy-agent@5`) only if you can't go async — but most Electron code paths are already async.

8. **Electron does NOT inherit Windows system proxy** — neither PAC mode nor "global mode" in v2rayN / Clash etc. routes Electron's Chromium subprocess or the main-process Node HTTPS calls. The user MUST switch their proxy client to **TUN mode** (kernel-level virtual NIC), otherwise the SOCKS5 proxy library in main.js, the CloakBrowser subprocess, and the renderer's `fetch()` all hit the raw upstream from the source IP. Add an early diagnostic that calls `curl https://ipinfo.io/json` in the user's PowerShell and confirms the country before they import any IPs. See `references/electron-network-stack.md` for the full ladder of "why isn't the proxy working".

## Exposing CDP wsEndpoint for external automation (the critical hook)

Whenever you embed CloakBrowser in a manager UI, **always emit `browser.wsEndpoint()` in the `started` event** (pattern shown in the launcher.mjs skeleton above). Then capture it on the parent side and surface it via IPC. This is the difference between "the browser is a black box owned by the UI" and "the browser is a substrate other code can drive."

Real-world need: migrating an existing reg/scrape script (originally written against MoreLogin's `/api/env/start` → returns `browserURL`) onto CloakBrowser. The legacy code does:

```javascript
const browser = await puppeteer.connect({ browserURL: info.browserURL });
```

With wsEndpoint exposed, the only change needed is:

```javascript
const browser = await puppeteer.connect({ browserWSEndpoint: info.wsEndpoint });
```

5000 lines of `flow.js` / `mail.js` / `phone.js` unchanged.

### Parent-side capture (extends the spawn snippet above)

In the stdout JSON-line loop, when `evt.type === 'started'`:

```javascript
if (evt.type === 'started' && !settled) {
  settled = true;
  if (evt.wsEndpoint) child._wsEndpoint = evt.wsEndpoint;  // stash on ChildProcess
  resolve({ ok: true, pid: child.pid, wsEndpoint: evt.wsEndpoint || null });
}
```

Stashing it on the `ChildProcess` object (Maps keyed by accountName → child) keeps it accessible without a parallel data structure.

### Surface it to renderer

Two ways, both useful:

**A. Include in proxy:list** — every row gets `_ws_endpoint: ''` (when stopped) or `'ws://...'` (when running). Cheap if the renderer already polls list.

```javascript
const child = ACTIVE_BROWSERS.get(a.name);
a._running = !!child;
a._ws_endpoint = (child && child._wsEndpoint) || '';
```

**B. Dedicated `proxy:getCDP(name)` handler** — point lookup, returns `{ok, wsEndpoint, pid, error?}`. Use this from the automation entry point (e.g. "▶ 自动注册" button) so you don't waste a list-load every probe.

```javascript
ipcMain.handle('proxy:getCDP', (_e, name) => {
  const child = ACTIVE_BROWSERS.get(name);
  if (!child) return { ok: false, error: '浏览器未运行' };
  if (child.killed || child.exitCode !== null) {
    ACTIVE_BROWSERS.delete(name);
    return { ok: false, error: '浏览器进程已退出' };
  }
  if (!child._wsEndpoint) return { ok: false, error: 'wsEndpoint 未捕获' };
  return { ok: true, wsEndpoint: child._wsEndpoint, pid: child.pid };
});
```

Expose via preload: `proxyGetCDP: (name) => ipcRenderer.invoke('proxy:getCDP', name)`.

### Verification one-liner

From the renderer's DevTools console after launching a browser:

```js
api.proxyGetCDP('C001').then(r => console.log(r))
// → { ok: true, wsEndpoint: 'ws://127.0.0.1:54321/devtools/browser/abc...', pid: 12345 }
```

If `wsEndpoint` is missing/empty, the launcher is on the old code path — re-check that `emit({ type: 'started', wsEndpoint })` is firing **after** `browser.wsEndpoint()` resolves (not before launch returns).

### Why this matters architecturally

A manager UI built on CloakBrowser without wsEndpoint exposed is a dead-end for automation — you can launch and visually inspect, but you can't script. Adding wsEndpoint up front (cost: 3 lines in launcher.mjs, 2 lines in parent capture, 12 lines for the IPC handler) keeps the door open to: pasting credentials, filling forms, scraping cookies, running multi-step reg flows, dispatching to a job queue. Do this on **day one** of any embedded-CloakBrowser project, not when you discover you need it.
