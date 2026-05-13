---
name: electron-renderer-pitfalls
description: Diagnose and avoid Electron renderer gotchas — disabled `window.prompt/alert/confirm`, IPC/contextBridge issues, CSP blocking, Node API isolation, alarm UX (beep/notification unreliable, window-flash works), pause/resume button deadlocks (request-vs-state gap), and stale frontend-cache-Map bugs where out-of-band write paths (manual mark, admin override) update the persisted store but skip the renderer's runState broadcast leaving stale UI. Use when a renderer button "does nothing", when designing multi-account manager UIs (AdsPower/MoreLogin style), when alarms or pause toggles get stuck, or when a manual override succeeds in the store but UI displays prior state.
when_to_use: |
  - User reports "button has no reaction" / "弹窗没出来" / "点了不起作用" in an Electron desktop app
  - You're adding interactive UI (rename, add-tag, set-note, batch action) and reflexively reaching for prompt()/confirm()
  - Designing a multi-account fingerprint-browser / proxy / profile manager UI (AdsPower-style)
  - Renderer can't reach Node modules, fs, ipcRenderer, or window.api despite preload.js exposing them
  - Inline `<script>` or `eval()` works in plain browser but throws CSP error in Electron
  - User reports high/identical CPU across multiple Chromium subprocesses ("特占CPU" / "怎么一直占用率这么高" / suspicious uniform 5-10% per browser)
  - User reports orphan Chromium / "怎么后台一直有进程" / Task Manager shows surviving chrome.exe after closing the Electron app
  - BrowserScan / antibot test flags "Incognito mode" or persistent-profile dir is empty after first launch
  - Spawned browser child process needs reliable cleanup on Windows; you're calling `child.kill()` or `taskkill /F /IM chrome.exe` and chrome processes survive
  - Injecting page-level scripts via `evaluateOnNewDocument` (favicon/title labeling, anti-detection patches)
  - User reports a notification / alarm / beep / OS toast "didn't fire" / "一直没有修复" / "报警没响" even though the UI clearly knows about the event (badge changed, modal opened, log written) — likely Pitfall 17 (multi-path IPC, only some paths broadcast the alarm channel)
  - User explicitly says "声音报警没用 / 删了" or "弹窗没用 / 删了" — they're rejecting the entire alarm mechanism, not asking for tuning; replace sound + OS notification with window-flash (Pitfall 19)
  - User reports a pause / cancel / abort button gets stuck disabled, "按了暂停就死了 / 恢复不了 / 刷新还是暂停" — pause-request vs paused-state gap not rendered, button disabled without finally (Pitfall 20)
  - User reports manual mark-success / mark-failed action persisted but UI still shows old status, "标记成功了还显示失败 / 已经改了 UI 没更新 / 重启 helper 才正常" — out-of-band write path didn't broadcast to renderer's cache Map (Pitfall 23)
---

# Electron renderer pitfalls

Desktop Electron apps (form-helper-v2, azure-auto-reg, etc.) carry a pile of "this worked in Chrome devtools but does nothing in the packaged app" landmines. This skill is the catalog. **Always check this list before going deep on a bug in an Electron renderer.**

---

## Pitfall 1 — `prompt()` / `alert()` / `confirm()` silently disabled

**Symptom:** User clicks a button that calls `prompt("Tag name:")` → nothing happens. No console error. The click handler returns `null` immediately. Looks identical to a broken event listener.

**Root cause:** Electron's renderer has `prompt()` **disabled by default** since Electron 7+. `alert()` and `confirm()` are still allowed but block the entire renderer thread, which is fragile and also frowned upon. The Chromium console even warns once: `prompt() is and will not be supported.`

**Fix:** Build modal dialogs in HTML/CSS. Promisify them so the call-site reads almost like `prompt()`:

```js
// Promise-returning replacement
function showInput(title, hint, defaultValue) {
  return new Promise((resolve) => {
    $("input-title").textContent = title;
    $("input-hint").textContent = hint || "";
    const inp = $("input-text");
    inp.value = defaultValue || "";
    $("input-modal").classList.remove("hidden");
    setTimeout(() => { inp.focus(); inp.select(); }, 50);
    const ok = $("input-ok"), cancel = $("input-cancel");
    const close = () => {
      $("input-modal").classList.add("hidden");
      ok.removeEventListener("click", onOk);
      cancel.removeEventListener("click", onCancel);
      inp.removeEventListener("keydown", onKey);
    };
    const onOk = () => { const v = inp.value; close(); resolve(v); };
    const onCancel = () => { close(); resolve(null); };
    const onKey = (e) => {
      if (e.key === "Enter") { e.preventDefault(); onOk(); }
      else if (e.key === "Escape") onCancel();
    };
    ok.addEventListener("click", onOk);
    cancel.addEventListener("click", onCancel);
    inp.addEventListener("keydown", onKey);
  });
}

// Call-site:
const v = await showInput("Tag name", "Enter a label", "");
if (!v) return;
```

**Rule of thumb:** **Never call `prompt()` from an Electron renderer.** If you're tempted, build a modal. `confirm()` is tolerable for destructive ops (delete) but a styled modal is better UX. `alert()` is acceptable for fatal error fallback only.

See `references/prompt-replacement-modal.md` for a full reusable modal template (HTML + CSS + JS).

---

## Pitfall 2 — `window.api` undefined in renderer

**Symptom:** `Uncaught TypeError: Cannot read properties of undefined (reading 'proxyList')`

**Root causes (check in order):**
1. `preload.js` not registered in `BrowserWindow` `webPreferences.preload`
2. `contextIsolation: true` (correct, default) but using `window.api = ...` instead of `contextBridge.exposeInMainWorld("api", ...)`
3. `nodeIntegration: true` was used as a shortcut — works but is a security disaster, do not enable
4. preload.js threw an error before `contextBridge.exposeInMainWorld` ran → check the **main process console**, not renderer devtools

**Fix template (preload.js):**
```js
const { contextBridge, ipcRenderer } = require("electron");
contextBridge.exposeInMainWorld("api", {
  proxyList: () => ipcRenderer.invoke("proxy:list"),
  proxyBatchUpdate: (names, patch) => ipcRenderer.invoke("proxy:batchUpdate", names, patch),
});
```

Whenever you add an IPC handler in `main.js`, you must ALSO expose it in `preload.js`. Forgetting this is the #2 cause of "button does nothing".

---

## Pitfall 3 — Multi-account / AdsPower-style UI conventions

When building an Electron app to manage 20-100+ browser profiles (CloakBrowser, MoreLogin, AdsPower clones), users expect AdsPower / MoreLogin's UX idioms. Diverging causes pushback every time.

**The conventions:**

| Element | Pattern |
|---|---|
| Open / Close browser | **One-click, no confirm modal.** Click `▶` → opens; click `⏹` → closes. |
| Lock / Unlock | Implicit. Opening browser locks; closing unlocks. No separate buttons. |
| Multi-select | Row checkbox + header "select-all" (only affects visible/filtered rows). |
| Batch action bar | Appears when ≥1 row selected, sticks to top of table, shows count + actions. |
| Tags | Colored chips. Click `+` → modal with preset chips + custom input. Click `×` on chip removes. |
| Status | Single colored pill: `● Open` (green) / `🔒 Locked` (yellow) / `Idle` (gray). |
| User notes | Double-click to edit inline. **NEVER auto-written by backend.** |
| Event history | Separate column from notes. Backend events go HERE, not in notes. Last event shown inline; click to see full history modal. |
| Destructive ops only | Keep `confirm()` for delete / replace-IP. Everything else is one-click. |
| Tag presets | 10ish defaults shipped, user can customize colors + add/remove via a settings modal. |

**The killer rule:** **User-authored fields (notes, name) and system-generated event log are SEPARATE columns and SEPARATE storage.** If a user types a note and an "I tested the proxy" event overwrites it, the user loses trust immediately.

Data model:
```js
account = {
  name, ip_id, csv_serial,
  notes: "",          // user-typed only, never touched by backend
  tags: [],           // user-managed, chips
  events: [           // backend-appended, capped at 100
    { ts: 1234567890, kind: "opened", msg: "browser launched (IP-001)" },
    { ts: 1234567900, kind: "test-ok", msg: "proxy passed: 1.2.3.4 (JP)" },
  ],
  lock_status: "idle" | "in_use",
}
```

`kind` enum suggestion: `opened` / `closed` / `test-ok` / `test-fail` / `replace-ip` / `error`. Render with colored pills per kind.

See `references/adspower-ui-conventions.md` for a deeper checklist (column order, batch ops, search/filter, color palette).

---

## Pitfall 4 — Auto-clearing lock state on browser exit

**Symptom:** User clicks X on the Chromium window. UI still shows `🔒 Locked` for that account because the close happened outside the app's "Close" button.

**Fix:** In the main process, attach a listener to the spawned browser child process. On `exit` (any reason — user closed window, crash, kill signal), clear `lock_status` and append a `closed` event.

```js
child.on("exit", (code) => {
  ACTIVE_BROWSERS.delete(account.name);
  clearLock(dataDir, account.name);            // unlock automatically
  pushEvent(dataDir, account.name, "closed", `browser exited (code ${code})`);
});
```

Defense-in-depth: also have the renderer call `proxyUnlock(name)` after `proxyCloseBrowser(name)` for the explicit-close path. Belt and suspenders.

---

## Pitfall 5 — Default start URL "for UX" pollutes evidence

**Don't** auto-navigate launched browsers to `https://ipinfo.io/` "to show users the IP". Why:
- Adds a real HTTP request through every proxy on every launch → slow + leaks pattern to anti-bot
- The page sometimes doesn't load (regional blocks, residential IP rate limits) → user thinks the browser is broken
- Pollutes user's tab history; they expected a blank page to start their workflow

**Do:** Default to `about:blank`. Provide a separate "Test proxy" button (`proxy:testAccount`) that runs the IP check in the main process via fetch + agent, **not in the browser**. Results go to the events log, not the user notes.

```js
// launcher.mjs
if (START_URL && START_URL !== 'about:blank') {
  await page.goto(START_URL, { waitUntil: 'domcontentloaded' });
}
// else: leave it on about:blank
```

---

## Pitfall 6 — `nodeIntegration` shortcuts that come back to bite you

If a junior dev / AI agent solved a missing-API problem by setting `nodeIntegration: true, contextIsolation: false` — that's a security regression and a future bug. Fix it properly with `contextBridge`. Renderer should never `require('fs')` directly.

---

## Pitfall 7 — CSP / inline script blocking

Default Electron CSP blocks `eval()` and inline `<script>` blocks with content. Symptom: `Refused to execute inline script because it violates the following Content Security Policy directive...`

**Fix:** Move scripts to external `.js` files referenced by `<script src="...">`. Avoid `eval()` entirely. If absolutely needed, set a permissive CSP via `session.defaultSession.webRequest.onHeadersReceived` — but moving to external files is better.

---

## Pitfall 8 — MutationObserver in injected page scripts → self-recursion → CPU pegged

**Symptom:** Every Chromium child process (CloakBrowser / Puppeteer / Playwright managed) sits at a precise, identical CPU % (e.g. exactly 5.5% each, or 7-10% for a 6-process group). Pages are `about:blank` — they should be 0%. Memory creeps up slowly. Browser visually idle.

**Root cause:** Your injected page script (via `evaluateOnNewDocument`) installs a `MutationObserver` on `<head>` to detect when the site changes `<title>` or favicon, then re-applies your own label. The observer also fires when **you** `appendChild` the new favicon link — you trigger yourself, you re-trigger yourself, recursion runs as fast as the microtask queue allows. Profile-injected scripts are extra dangerous because the loop runs in **every page** in every browser — N accounts × 6 chrome processes each.

**Reproduction (the bug I wrote):**
```js
// applyFavicon: removes old <link rel=icon>, appends new one
function applyFavicon() {
  document.querySelectorAll("link[rel*='icon']").forEach(l => l.remove());
  const link = document.createElement('link');
  link.rel = 'icon'; link.href = makeFaviconDataUrl();
  document.head.appendChild(link);   // ← triggers our own observer
}

// Observer watching head for new icon links
new MutationObserver(records => {
  for (const r of records) for (const n of r.addedNodes)
    if (n.tagName === 'LINK' && /icon/i.test(n.rel)) applyFavicon();  // ← infinite
}).observe(document.head, { childList: true });
```

**Fix:** Add a silent flag around your own writes. Release it async so the MutationObserver microtask queue has flushed before re-enabling:

```js
function applyFavicon() {
  window.__cloakSilent = true;
  try {
    document.querySelectorAll("link[rel*='icon']").forEach(l => l.remove());
    const link = document.createElement('link');
    link.rel = 'icon'; link.href = makeFaviconDataUrl();
    document.head.appendChild(link);
  } finally {
    setTimeout(() => { window.__cloakSilent = false; }, 0);
  }
}
new MutationObserver(records => {
  if (window.__cloakSilent) return;   // ← guard
  // ... handle real external mutation
}).observe(document.head, { childList: true });
```

**Diagnostic recipe (Windows):** When you see suspicious idle CPU, sample CPU time twice with 10s gap and compute deltas per PID:

```powershell
# diag-cpu.ps1
Get-CimInstance Win32_Process -Filter "Name='chrome.exe'" | ForEach-Object {
  $cpu = [math]::Round(($_.KernelModeTime + $_.UserModeTime) / 10000000, 2)
  "PID={0,-6} PPID={1,-6} CPU={2}s" -f $_.ProcessId, $_.ParentProcessId, $cpu
}
```
Run twice, 10 sec apart. If a renderer accumulates 5+ seconds in 10 wall-clock seconds, it's burning a core. Idle about:blank should accumulate <0.1s.

**General rule for any observer pattern (MutationObserver, Proxy traps, setter interceptors, file watchers, Redux subscribers):** **The observer's callback must not synchronously call code paths that re-trigger the observer.** Either guard with a silent flag, or use a different mechanism (event delegation, dirty-flag + rAF) entirely.

---

## Pitfall 9 — `setInterval` in injected page scripts becomes a CPU tax that survives orphaning

**Symptom:** Multiple Chromium processes at identical low CPU % (e.g. 4× browsers all at exactly 5.5%) even after the controlling Electron / Node parent is dead. Killing Electron does nothing — chrome keeps running.

**Root cause:** Your `evaluateOnNewDocument` injected `setInterval(() => { applyTitle(); applyFavicon(); }, 2500)` "as a safety net for SPAs that aggressively rewrite their title". Once the Node parent dies, Chromium becomes an orphan and that interval runs forever. Even when the parent is alive, the polling is wasted work — each tick re-encodes a PNG, manipulates DOM, triggers style recalc.

**Fix:** Use event-driven triggers, never polling, for label re-injection:

```js
function tick() { applyFavicon(); applyTitle(); }

// Initial
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', tick);
} else { tick(); }
window.addEventListener('load', tick);

// When tab returns to foreground (common case the user notices)
document.addEventListener('visibilitychange', () => {
  if (!document.hidden) tick();
});

// When site itself mutates head (with silent guard from Pitfall 8)
new MutationObserver(records => {
  if (window.__cloakSilent) return;
  // detect external title/favicon changes, call tick()
}).observe(document.head, { childList: true });
```

**Heuristic:** If you find yourself writing `setInterval(..., < 5000)` inside `evaluateOnNewDocument`, stop. It will be wrong. Move to MutationObserver / event listeners.

---

## Pitfall 10 — Windows: `child.kill()` orphans Chromium subprocesses

**Symptom:** Task Manager shows many `chrome.exe` (15-30+) after closing your Electron app. They survive `taskkill /F /IM chrome.exe`. Memory consumed: hundreds of MB. `Get-Process -Id <pid>` returns PIDs but `Path` is empty and `taskkill /F /PID <pid>` reports "Access is denied" even from elevated cmd.

**Root cause:** Node's `child.kill()` on Windows maps to `TerminateProcess()` on **only the spawned PID**. Chromium spawns 5+ subprocesses (gpu, utility, renderer, network, plugin, …) that are NOT in a Win32 Job Object grouped with the launcher. When the launcher dies, its subprocesses live on. The Chromium main process is now the orphans' root; if it ALSO dies, the root grant is gone and even admin can't easily reach into the job.

**Fix — three layers, all needed:**

**Layer A — kill the tree, not just the root:**
```js
function killTree(pid) {
  if (process.platform === "win32") {
    try { require("child_process").execSync(`taskkill /F /T /PID ${pid}`, { stdio: "ignore" }); } catch (_) {}
  } else {
    try { process.kill(-pid, "SIGKILL"); } catch (_) {}
    try { process.kill(pid, "SIGKILL"); } catch (_) {}
  }
}
```
`/T` = tree. The `taskkill /T /PID <launcher_pid>` walks the parent-child chain and terminates every descendant.

**Layer B — graceful first, hard second (so profile dirs aren't corrupted):**
```js
async function stopBrowser(name) {
  const child = ACTIVE_BROWSERS.get(name);
  const pid = child.pid;
  try { child.stdin.end(); } catch (_) {}   // signal launcher to call browser.close()
  await new Promise(resolve => {
    let done = false;
    const t = setTimeout(() => { if (!done) { done = true; killTree(pid); resolve(); } }, 3000);
    child.once("exit", () => { if (!done) { done = true; clearTimeout(t); resolve(); } });
  });
  ACTIVE_BROWSERS.delete(name);
}
```

**Layer C — launcher self-destructs when parent dies (prevents orphans being created in the first place):**
```js
// inside launcher.mjs
process.on('SIGTERM', () => gracefulShutdown('SIGTERM'));
process.on('SIGINT',  () => gracefulShutdown('SIGINT'));
process.stdin.on('end',   () => gracefulShutdown('stdin-end'));
process.stdin.on('close', () => gracefulShutdown('stdin-close'));

// Parent-death watchdog — Windows doesn't auto-kill children, do it yourself
const PARENT_PID = process.ppid;
setInterval(() => {
  try { process.kill(PARENT_PID, 0); }       // signal 0 = liveness check
  catch (_) { gracefulShutdown('parent-dead'); }
}, 5000);

async function gracefulShutdown(reason) {
  try {
    await Promise.race([
      browser.close(),
      new Promise(r => setTimeout(r, 3000)),
    ]);
  } catch (_) {}
  process.exit(0);
}
```

**Layer D (Electron app exit):** Hook `app.on('before-quit')` and await your `shutdownAll()` before letting the app actually quit. `e.preventDefault()` once, run cleanup, then `app.quit()` again with a sentinel flag.

**Cleanup for existing orphans (right-click → Run as administrator):**
```bat
@echo off
taskkill /F /PID <pid1>
taskkill /F /PID <pid2>
pause
```
Save as ASCII (not UTF-8 BOM, not GBK) — cmd's default Chinese codepage will mangle UTF-8 `@echo` etc. into garbage like `'釜瀛ゅ効'`. Use plain ASCII English text in .bat files unless you also `chcp 65001` first.

See `references/windows-orphan-chromium-debug.md` for the full diagnostic transcript and 4-layer fix recipe.

---

## Pitfall 11 — `cloakbrowser/puppeteer` silently ignores `userDataDir` option

**Symptom:** BrowserScan / antibot tester flags your browser as "Incognito mode (-10%)" even though you passed `userDataDir: '/path/to/profile'` to `launch()`. Inspecting `/path/to/profile/<account>/` shows the directory was created but is **empty** — no `Preferences`, no `Cookies`, no `Local Storage`. Cookies don't persist across sessions.

**Root cause:** The Puppeteer wrapper in `cloakbrowser/puppeteer` doesn't pass `userDataDir` through to Chromium. Only the Playwright wrapper (`cloakbrowser/playwright`) handles it via `launchPersistentContext(userDataDir, …)`. Grep:
```
grep -rn "userDataDir" node_modules/cloakbrowser/dist/*.js | grep -v .map
# → only playwright.js has it
```

**Fix:** Pass via Chromium's CLI arg directly. Keep the high-level option for forward-compat:
```js
const launchArgs = [`--fingerprint=${FINGERPRINT}`];
if (USER_DATA_DIR) launchArgs.push(`--user-data-dir=${USER_DATA_DIR}`);
const opts = { headless: false, humanize: true, geoip: true, args: launchArgs };
if (USER_DATA_DIR) opts.userDataDir = USER_DATA_DIR;  // for cloakbrowser/playwright
const browser = await launch(opts);
```

**General principle when integrating fingerprint-browser SDKs:** Don't trust documented options blindly — verify the underlying Chromium CLI got the flag. A two-line check is `ls $userDataDir` after first launch: a real persistent profile has 20-50 files (`Preferences`, `Cookies`, `Local Storage/`, `Default/`, …); an empty directory means Chromium is in incognito and writing nowhere.

---

## Pitfall 12 — BrowserScan score is NOT a quality signal for fingerprint browsers

When a user says "AdsPower/MoreLogin scores 100, ours scores 70, what's wrong?" — push back. Fingerprint browsers' job is to MAKE the fingerprint look modified-but-unique across N accounts, not to mimic a stock Chrome. Commercial brands optimize aggressively against public test sites because users score-shop. Real metric is:
- Same profile launched twice → identical fingerprint (consistency)
- 100 different profiles → 100 different fingerprints (anti-link)
- Survives target site's actual signup / login flow (Azure, Google, etc.)

Only fix the genuinely-broken scores (Incognito mode = real bug, Pitfall 11). Don't try to "fix" WebGL / Audio entropy — those are the product working as intended.

---

## Pitfall 13 — `prompt()` ban applies to dependencies too

Some libraries (older form helpers, deprecated date pickers) internally call `window.prompt()`. They'll silently fail. Grep your `node_modules` for `window.prompt(` if a library "does nothing" in your renderer but works in their demo page.

---

## Pitfall 15 — Modal HTML uses class names CSS never defined → modal falls back to inline block

**Symptom:** User screenshot shows the modal title text colliding with the tab bar, the modal's "Cancel" / "OK" buttons overlapping the page toolbar buttons (`Cancel` literally pressed up against `测全部` and `测 active`), and the input field invisible. User says "看不见、点不上". From a code-only review everything looks fine: the HTML modal node exists, `.classList.remove("hidden")` runs, the JS event wiring is correct.

**Root cause:** The HTML template uses `<div class="modal-body">` (or `modal-panel`, `modal-container`, …) for the inner content, but `style.css` defines ONLY `.modal { position: fixed; }` and `.modal.hidden { display: none; }`. There is no rule for `.modal-body`. When `.hidden` is removed the outer `.modal` correctly becomes `position: fixed; inset: 0` — but its child `.modal-body` is just a plain block element with no positioning, no centering, no z-index, no backdrop. It renders at whatever spot in the document flow the browser computes for a `position: fixed` ancestor's natural-flow child — which on Chromium tends to be the **top-left** of the viewport, lining up exactly under the app's tab bar.

**Why this hurts more than `prompt()` failing:** A missing `prompt()` (Pitfall 1) silently returns null — bad, but invisible. A `.modal-body` class with no rule renders the modal contents **on top of your page UI** with no overlay, **fully clickable**. The user CAN click the modal's "OK" button, but they can also click any button under it, and they can't tell which is which. It looks like a layout bug, not a missing-style bug.

**Diagnostic:**
```bash
# In repo root — find the class names used in HTML, then check which are defined.
grep -oE '(modal-[a-z-]+|[a-z]+-modal)' renderer/index.html | sort -u > /tmp/html-classes.txt
grep -oE '\.(modal-[a-z-]+|[a-z]+-modal)' renderer/style.css | sed 's/^\.//' | sort -u > /tmp/css-classes.txt
comm -23 /tmp/html-classes.txt /tmp/css-classes.txt
# anything that prints = class used in HTML, not defined in CSS = silent layout bomb
```

**Fix — provide a generic class-level fallback so any future modal author can't forget:**

```css
.modal {
  position: fixed; inset: 0; z-index: 1000;
}
.modal.hidden { display: none; }

/* Auto-backdrop via pseudo-element — no markup change required */
.modal::before {
  content: ""; position: absolute; inset: 0;
  background: rgba(0,0,0,0.55); z-index: 0;
}

/* Catch-all for any inner panel class people invent */
.modal > .modal-body,
.modal > .modal-panel,
.modal > .modal-container {
  position: absolute; top: 50%; left: 50%;
  transform: translate(-50%, -50%);
  background: #1c2230; border: 1px solid #3a3f4a;
  border-radius: 8px; padding: 16px 20px;
  min-width: 360px; max-width: 90vw; max-height: 85vh;
  overflow: auto; z-index: 1; color: #e6edf3;
  box-shadow: 0 12px 48px rgba(0,0,0,0.7);
}
```

The `::before` backdrop is the critical trick — it works even when the developer forgot to add a `<div class="modal-mask">` element. The `> .modal-body` selector covers the common alternate name; add `.modal-panel`, `.modal-container` as you encounter them.

**General principle:** When you build a `.modal` system, **CSS must work even if the HTML author uses the wrong inner class name**. Provide a `:not(.hidden) > *` fallback OR style multiple candidate inner classes OR use `::before` for the backdrop so no markup is required. Code review for new modals must look at BOTH the HTML AND the CSS — a working JS handler + working visibility toggle is not enough.

**Frustration as a first-class signal:** User feedback like "看也看不见 点也点不上" / "I can't even tell what to click" almost always points to a layout/z-index/overlay bug, NOT a logic bug. Don't waste cycles re-reading the click handler. **Ask for the screenshot, run vision analysis, look for: (a) elements overlapping (b) missing backdrop (c) modal rendered at top-left instead of center.** Those three visual symptoms = missing `.modal-body` positioning 90% of the time.

---

## Pitfall 14 — Reusing renderer-only `window.x = ...` modules in the main process (shim pattern + same-key bugs)

**Symptom:** You have a pure-JS asset only used by the renderer — a kanji-romaji dictionary, a date-format helper, a validation rules table — and now the main process (or a Node-side worker) needs the same logic. The file ends with `window.romaji = { lastName, firstName };` so plain `require()` blows up with `ReferenceError: window is not defined`. Copying the file in half is wrong: now two copies of a 600-entry dictionary drift over time.

**Root cause:** Renderer JS often uses `window.X = ...` as its "export" (IIFE / script-tag style, no module wrapper). Node has no `window`. Two anti-patterns to avoid:
- ❌ Duplicate the file into `main/` and `renderer/` — drift is inevitable, you WILL find the two copies disagree.
- ❌ Convert to CommonJS exports + a `<script>` shim — every renderer caller breaks.

**Fix — shim `global.window` before require, snapshot the export, restore:**

```js
// azure/kanji-romaji.js (main-process wrapper)
'use strict';
const hadWindow = Object.prototype.hasOwnProperty.call(global, 'window');
const savedWindow = global.window;
if (!hadWindow) global.window = {};

try {
  // Executes the trailing `window.romaji = {...}` line into our shim
  require('../renderer/kanji_romaji');
} catch (e) {
  if (!hadWindow) delete global.window; else global.window = savedWindow;
  throw e;
}

const api = global.window.romaji || {};
// Restore so we don't pollute global for other modules
if (!hadWindow) delete global.window; else global.window = savedWindow;

if (typeof api.lastName !== 'function') {
  throw new Error('renderer/kanji_romaji.js did not expose window.romaji');
}

module.exports = { lastName: api.lastName, firstName: api.firstName };
```

The renderer file stays unchanged; both ends consume **one** source of truth. Works for any IIFE-style asset that ends `window.X = {...}` or `window.X = function() {...}`.

**The hidden bug this surfaces — duplicate keys in object literals:**

When you finally have a way to verify the dictionary from the main process, run an audit. JS object literals **silently let the last value win on duplicate keys**. A 600-entry hand-authored dictionary almost always has 5-20 such collisions, and the second value is usually the WRONG one (somebody pasted a variant reading without realizing they already had the standard one earlier).

```bash
node -e '
const fs = require("fs"); const re = /"([^"]+)"\s*:\s*"([^"]+)"/g;
const text = fs.readFileSync("renderer/kanji_romaji.js","utf8");
const seen = {}; let m; const dups = [];
while ((m = re.exec(text))) {
  const [, k, v] = m;
  if (seen[k] && seen[k] !== v) dups.push([k, seen[k], v]);
  seen[k] = v;
}
console.log("collisions:", dups.length);
dups.forEach(([k,a,b]) => console.log(`  ${k}: kept "${a}" earlier, overwritten by "${b}"`));
'
```

This caught **12 collisions** in a real 600-key dictionary file (`高木: Takagi → Takaki`, `豊田: Toyota → Toyoda`, `羽田: Hada → Haneda`). All three "after" values were variants the author paste-imported by accident; the "before" was the standard reading. The fix is to delete the second occurrence — the dictionary's organizing pass already put the canonical entry first.

**General rule:** When you bridge a hand-authored data file across module systems (renderer ↔ main, browser ↔ Node), **always run a duplicate-key audit immediately after wiring it up**. Two-line node script catches a class of bugs that has been silently corrupting output for months. Also true for hand-edited JSON when a tool emits warnings; for YAML where keys collide; for shell `.env` files where two `KEY=` lines mean only the last wins.

**Adjacent gotcha — non-ASCII in cross-system data:** The same dictionary work surfaced that a CSV "English name" column carried Japanese macron characters (`Yoshirō`, `Katō`, `Akirayō`). The downstream form is ASCII-only; the macron becomes `?` or worse. Strip with NFD + combining-mark removal:

```js
const stripDiacritics = (s) => s.normalize('NFD').replace(/[\u0300-\u036f]/g, '');
stripDiacritics('Yoshirō');  // → 'Yoshiro'
```

And prefer the dictionary value over the CSV-with-stripped-macron value when both exist — the dictionary stores canonical romaji (`晃洋 → Akihiro`), the CSV-stripped path returns whatever the human typed minus accents (`Akirayō → Akirayo`, still wrong spelling).

---

## Pitfall 16 — Process-memory-only state silently resets when the desktop app restarts

**Symptom (user-reported patterns):** Any of:
- "重启 helper 会丢失状态" / "重启后注册成功的标记没了"
- The status pill column shows `—` / `idle` for every row after relaunching the app, even for accounts that successfully completed a long task last session.
- "下一次打开浏览器不保留最后网页地址" — every browser launch starts at a fixed URL (or about:blank) instead of where the user left off.
- Batch progress bars reset to 0/N after a relaunch even though the underlying work (registered Azure accounts, opened tabs, fetched data) really did succeed and the artifacts (cookies, screenshots, downloaded files) are still on disk.

**Root cause family:** Electron desktop users expect **desktop-app durability** — quit → relaunch → state is exactly where you left it (Photoshop, VSCode, Chrome itself all behave this way). But Electron apps frequently keep important state ONLY in main-process memory (`Map` variables, module-scope `let`, in-flight `Promise`s) instead of writing it to the JSON / SQLite store. When the user quits, that memory dies and only what was persisted survives. Three concrete sub-cases this maps to:

1. **Runner / task status in `Map<envId, state>` in process memory** — e.g. `ctrlState = new Map()` in a state-machine runner module. `finalizeCtrl(name, 'success')` updates the map but doesn't write to disk. The UI reads from the map via IPC at startup, gets an empty map, displays everything as `idle`. The fact that the work succeeded is technically still in the JSON store (e.g. `account.events[]` has a `reached_payment` entry), but no aggregate `status` field was persisted, so the UI can't render a quick pill without parsing the event log row-by-row.

2. **Browser launcher hard-forced START_URL overrides Chrome's session restore** — launcher.mjs / launcher.js does `await page.goto(START_URL)` unconditionally on every spawn. Chromium's built-in "Continue where you left off" / session restore from the persistent profile (Pitfall 11) DOES carry tabs across launches, but the explicit `page.goto()` replaces them on the very first action. Users assume "I closed the browser on the Azure dashboard, next time I open it I'll be on the Azure dashboard" — instead they land on `about:blank` or your default URL every time.

3. **Active controller / pause-resume / in-flight retry state in the runner module** — pause toggles, abort flags, "current attempt N of 5" counters all live in process memory. If the Electron app is killed during a batch run, the next launch can't resume; the operator has to restart the whole batch.

**Fix family — three rules, in order:**

**Rule A — every UI-visible status pill / badge / count MUST have a persisted source field.** If the UI shows "✅ success / ❌ failed / — never tried" for an account, the JSON store must have a corresponding scalar field on the record (e.g. `account.last_run_status`, `account.last_run_at`, `account.last_run_screenshot`). The in-memory Map is a fast-path cache; the JSON field is the source of truth. `finalizeCtrl(name, status)` writes both:

```js
function finalizeCtrl(name, status) {
  // Fast path: in-memory map for live UI
  const c = ctrlState.get(name) || {};
  c.status = status; c.endedAt = Date.now();
  ctrlState.set(name, c);

  // Durable path: write into store so the next process can see it
  try {
    const data = loadProxies();
    const acc = data.accounts.find(a => a.name === name);
    if (acc) {
      acc.last_run_status = status;          // 'success' | 'failed' | 'stopped'
      acc.last_run_at = Date.now();
      saveProxies(data);
    }
  } catch (e) { /* don't crash the runner over a persist error */ }
}
```

On app startup, the IPC handler that builds the UI snapshot reads `account.last_run_status` directly from the store, NOT from the empty in-memory map. The map becomes a write-through cache for the current session's live updates only.

**Sub-rule A1 — `running` on disk + nothing in memory = `interrupted`, NOT `running`.**

When you persist status on every transition (including `runOne()` start writing `status: 'running'`), a crashed Electron app leaves accounts with `last_run_status === 'running'` on disk. On the next launch, the in-memory `ctrlState` Map is empty. If the snapshot function naively echoes the disk value, the UI will show "正在注册" for accounts that aren't running anywhere — the runner module isn't doing anything, no progress events will ever fire to update them. The pill is a lie.

Map this case explicitly:

```js
function snapshotAllRunState() {
  const out = {};
  // 1. Load persisted statuses from store
  const data = loadProxies(dataDir);
  for (const a of (data.accounts || [])) {
    if (!a.last_run_status) continue;
    let displayStatus = a.last_run_status;
    // If disk says running but live map has no entry → the previous process crashed
    if (displayStatus === 'running' && !ctrlState.has(a.name)) {
      displayStatus = 'interrupted';  // UI renders as "⚠ 上次被打断"
    }
    out[a.name] = { status: displayStatus, ...rest };
  }
  // 2. Live map overrides disk (current session's running accounts)
  for (const [k, c] of ctrlState.entries()) out[k] = { status: c.status, ...c };
  return out;
}
```

Renderer adds the badge:
```js
else if (s === 'interrupted') { label = '⚠ 上次被打断'; cls = 'azs-stopped'; }
```

This gives operators an honest summary on relaunch: "of 100 accounts, 8 succeeded, 2 failed, 1 was interrupted mid-run, 89 untried" — they can click the interrupted one to retry without wondering why it's stuck at "正在注册" forever.

**Rule B — let Chrome / Chromium do session restore instead of fighting it.** In the launcher, only `page.goto(START_URL)` if explicitly requested for THIS launch (e.g. operator clicked "open at signup page"). Default to skipping the navigation entirely:

```js
// launcher.mjs
const initPages = await browser.pages();
const page = initPages[0] || await browser.newPage();

// Skip forced navigation unless caller really wants it.
// Chromium's persistent-profile session restore handles tab recovery.
if (START_URL && START_URL !== 'about:blank' && FORCE_NAVIGATE) {
  try { await page.goto(START_URL, { waitUntil: 'domcontentloaded', timeout: 60000 }); }
  catch (e) { emit({ type: 'goto_warn', msg: String(e).slice(0, 200) }); }
}
```

For this to actually work the persistent-profile fix from Pitfall 11 (`--user-data-dir=` in args) MUST be in place. The two pitfalls compound: without persistent profile, there's nothing to restore; without skipping the forced goto, the restore is immediately overwritten. The user will see the "doesn't remember" symptom whichever half is missing.

If you want belt-and-suspenders, also persist `account.last_url` on browser close. **Do NOT hook the `disconnected` event to read `page.url()`** — by the time `disconnected` fires the page object is already detached and `page.url()` either throws or returns `about:blank`. Use a heartbeat + final-emit pattern instead, **inside the launcher subprocess** where the live browser handle exists:

```js
// proxy/launcher.mjs — runs in the child process that owns the browser handle

// (a) Heartbeat: every 10s emit the current active tab's url to the parent.
// Skip about:blank / chrome:// / devtools:// so we don't overwrite a real url with junk.
setInterval(async () => {
  try {
    const pages = await browser.pages();
    let url = '';
    for (let i = pages.length - 1; i >= 0; i--) {
      const u = pages[i].url();
      if (u && !u.startsWith('about:') && !u.startsWith('chrome:') && !u.startsWith('devtools:')) {
        url = u; break;
      }
    }
    if (url) emit({ type: 'url_tick', url });
  } catch (_) {}
}, 10000);

// (b) Final emit on graceful shutdown — covers the case where the user closes
// the browser between heartbeats, or batch mode calls stopBrowser immediately
// after the run finishes.
async function gracefulShutdown(reason) {
  emit({ type: 'shutdown', reason });
  try {
    const pages = await browser.pages();
    for (let i = pages.length - 1; i >= 0; i--) {
      const u = pages[i].url();
      if (u && !u.startsWith('about:') && !u.startsWith('chrome:') && !u.startsWith('devtools:')) {
        emit({ type: 'url_tick', url: u, final: true }); break;
      }
    }
  } catch (_) {}
  try { await Promise.race([browser.close(), new Promise(r => setTimeout(r, 3000))]); } catch (_) {}
  process.exit(0);
}
```

```js
// proxy/ipc.js — parent process: receive url_tick and write through to JSON store
child.stdout.on('data', (c) => {
  // ... parse line-delimited JSON ...
  if (evt.type === 'url_tick' && evt.url) {
    try { require('./store').updateLastUrl(dataDir, account.name, evt.url); } catch (_) {}
  }
});
```

Two wins from this pattern:
- The browser-side knows when it's about to die and can synchronously sample `page.url()`; the parent only has to record a string.
- Heartbeat-based persistence means even if the user force-kills the Electron app or the OS reboots, the last persisted url is at most 10 seconds stale — good enough for "open the browser on the page I was on".

**Pair this with the resume-from-disk path in `launchBrowser` (Rule A):**
```js
let effectiveStart = startUrlArg;
if (!effectiveStart && account.last_url) effectiveStart = account.last_url;  // resume
if (!effectiveStart) effectiveStart = 'about:blank';                          // first launch
```
Now the precedence is: explicit caller intent > persisted last url > blank. The user sees "where I left off" on every relaunch.

**Rule C — anything in-flight (running batch, current attempt) should write a checkpoint on every state transition.** Doesn't need to be elaborate — a single JSON field per account is plenty:

```js
acc.in_flight = { stage: 'form2_fill', attempt: 2, started_at: 1234567890 };
// or
acc.in_flight = null;  // when idle
```

On app launch, scan accounts where `in_flight !== null` AND `in_flight.started_at < Date.now() - STALE_MS` (e.g. 10 min) — those are crashed runs. Show them as `❓ interrupted` in the UI with a "resume" or "retry" button rather than silently treating them as idle. This is the same pattern as the failure-retry-dashboard in `puppeteer-fingerprint-browser-automation/references/failure-retry-dashboard.md` but for the much weaker case of "the app itself crashed mid-task".

**Diagnostic — quick way to find Rule A violations in an existing codebase:**

```bash
# Find every place where in-memory state is written but the store isn't
grep -nE "ctrlState\.set|status:\s*['\"]?(success|failed|stopped)" --include='*.js' -r .
# For each hit, check whether the same function body also calls the store's save function
# (save/write/persist + the store module name, e.g. saveProxies, saveAccounts, store.save, db.write)
# If not, it's a process-memory-only state that will reset on relaunch.
```

In a typical 5000-LOC Electron automation codebase this surfaces 5-15 violation sites — each one is a future "状态丢了" user report.

**General principle:** **For an Electron desktop app, in-memory state is fine for the UI render cycle and the current task's hot path. Anything the user expects to "still be there tomorrow morning" (statuses, last-run results, in-flight resume points, last-visited URL per profile) MUST be in the JSON / SQLite store on every transition, not just at app-quit time.** App-quit isn't reliable — power loss, force-kill from Task Manager, OS update reboot all skip the `before-quit` hook. Write-on-transition is the only durable pattern.

This pitfall is a sibling to Pitfall 4 (browser-exit lock-state cleanup) — same family, different specific bug. Pitfall 4 says "react to a child process dying"; Pitfall 16 says "react to your OWN process dying / being relaunched".

---

## Pitfall 17 — Multi-path IPC events: one semantic event, N code paths, only some broadcast the alarm channel

**Symptom (user-reported patterns):**
- "captcha 报警没响 / 这个地方一直没有修复" — operator sees the captcha screenshot, can click "继续" in the UI, but never gets the audible beep, the title flash, or the OS notification that was supposed to scream for attention.
- Works in some flows ("登录阶段 captcha 会响"), broken in others ("form2 阶段 captcha 不响").
- The blocking modal / orange badge in the row DOES appear, so the operator *can* respond if they happen to be looking — but the whole point of the alarm (call user away from their other monitor) is silently missed.

**Root cause family:** A single user-visible event (captcha detected, account flagged, balance critical, anti-bot soft-block) has **N independent detection sites** in the codebase — typically because the same business event can fire at different stages of the same flow:
- `azure/index.js` — form-stage state machine, calls `blockOnCaptcha(...)`
- `azure/flow.js:microsoftLogin` — login-stage step loop, calls `alertAndWait(...)` directly
- `azure/flow.js:form2Fill` — address-validation stage, calls `alertAndWait(...)` directly

Each path was written at a different time, with its own choice of "how to notify renderer". Only ONE of them happens to `broadcast('azure:captcha', ...)` (the channel the renderer's `startCaptchaAlarm(...)` listens to). The others only send `azure:blocking` (the generic blocking-modal channel) or a `progress` event. The frontend wires up exactly one alarm subscription — `window.api.onAzureCaptcha(...)` — and that subscription never fires from the other paths.

The bug is invisible in code review of any single file: each path "correctly notifies the user" by its own definition. The bug is in the **gap between** "we have a shared semantic event" and "we have a shared channel name for that semantic event".

**Diagnostic recipe — when the user reports "the alarm didn't go off but the UI knew about it":**

```bash
# 1. Find every detection site for the semantic event
grep -rn "captcha\|アカウントの保護\|ロボット\|verify you are human" --include='*.js' azure/ flow/ runner/

# 2. For each hit, check what it broadcasts to the renderer
# Look for: broadcast(, notifyRenderer(, webContents.send(, ipcMain.emit(
grep -B2 -A8 "blockOnCaptcha\|alertAndWait\|setBlocking" azure/*.js

# 3. Find what the renderer actually listens for
grep -n "onAzure\|ipcRenderer.on\|window.api\." renderer/*.js preload.js

# 4. Cross-reference: every channel the renderer subscribes to MUST be emitted by every detection site
# Any detection site that only emits a subset = silent-alarm bug
```

In a typical Azure-style automation codebase this surfaces 2-4 detection paths and 2-3 renderer subscriptions — easy to spot the gap once you list both sides.

**Fix family — three options, pick by what's least invasive:**

**Option A (best, used in form-helper-v2) — make the shared helper (`alertAndWait`) emit BOTH channels conditionally:**

The trick: every captcha path calls the same `alertAndWait(...)` helper for the actual blocking modal. Have THAT helper detect by title/message that the event is captcha-class and broadcast the extra alarm channel automatically. One change, fixes all current and future captcha sites.

```js
// azure/alert.js — alertAndWait(opts)
const isCaptcha = /captcha|人机|アカウントの保護|ロボット/i.test(
  String(opts.title) + ' ' + String(opts.message)
);
if (isCaptcha) {
  // Pull screenshot path out of message ("截图: D:\..." or "截图：xxx.png")
  let screenshot = '';
  const m = String(opts.message).match(/截图[:：]\s*(.+\.png)/);
  if (m) screenshot = m[1].trim();
  notifyRenderer('azure:captcha', {
    envId: id, reason: opts.title || 'captcha', screenshot, ts: Date.now(),
  });
}
notifyRenderer('azure:blocking', { envId: id, title, message, timeoutMs, startedAt: Date.now() });

// And on every unblock path (user clicked continue, check() returned true, timeout):
if (isCaptcha) notifyRenderer('azure:captcha-cleared', { envId: id, ts: Date.now() });
```

**Cleared-event symmetry is mandatory** — if you only fire the alarm-start channel but never the alarm-stop channel from these paths, the renderer's `setInterval` beep loop runs to its hard cap (e.g. 30 beeps × 5s = 2.5 minutes of beeping after the operator already cleared it). User trust gone.

**Option B — funnel all detection sites through a single dispatcher:**

```js
// azure/captcha-dispatch.js
function fireCaptcha(envId, reason, screenshot) {
  broadcast('azure:captcha', { envId, reason, screenshot, ts: Date.now() });
  // could also write to event log, send Telegram, etc — single place to extend
}
```
Refactor all 3 detection sites to call `fireCaptcha(...)` before their respective blocking-wait. Heavier change but more explicit.

**Option C — broaden the renderer subscription:**

Make `startCaptchaAlarm` listen to `azure:blocking` and inspect `payload.title` for captcha keywords. Cheaper but couples renderer to backend message formatting; fragile if titles get translated.

Prefer A. It puts the policy ("alarm class events get the loud channel") next to the helper that all paths already share, so a future fourth detection site benefits automatically.

**General principle — when a semantic event has multiple detection sites:**

1. **List every detection site and every renderer subscription on one page.** A spreadsheet, a comment header, anything. Force yourself to see the matrix.
2. **Every detection site MUST emit the superset of channels that any subscriber depends on.** Missing-channel is the bug; extra-channel is harmless.
3. **For every "start" channel there must be a paired "cleared" channel from the SAME site.** Half-emitted lifecycle = stuck UI state (alarm beeping after cleared, badge stuck after timeout).
4. **Prefer one shared helper that emits the full set** over N call-sites each emitting "their own correct subset". Subsets drift; the helper doesn't.
5. **Frustration signal "this is never fixed" / "你这个地方一直没有修复" — almost always means there's an N-path bug where the dev only fixed path 1.** Don't re-read the path you already fixed; grep for OTHER call-sites of the same semantic event.

**Adjacent — text-in-message extraction pitfall (URL / path / id):**

When you extract a side-channel datum from a human-readable message (e.g. screenshot path out of `截图: D:\foo.png`), your regex must handle BOTH Chinese full-width colon `：` and ASCII `:`. CJK-locale users will mix them. `/截图[:：]\s*(.+\.png)/` not `/截图:\s*(.+\.png)/`. Same gotcha for `URL：` / `URL:`, `id：` / `id:`.

---

## Pitfall 18 — Adding new buttons to a dynamically-rendered list but the event delegation selector excludes them

**Symptom:** You add a new button to a list-row template (`<button class="my-new-btn" data-act="my-new-act">`). The button renders, the user can click it, **nothing happens**. No console error. The same row's existing buttons (`▶ open`, `⏹ close`, etc.) all work fine. Re-reading the click handler shows your new `else if (act === "my-new-act")` branch — it's just never reached.

**Root cause:** The list uses **event delegation** — a single listener on the `<tbody>` that finds the clicked button via `e.target.closest(...)`. The selector is typically scoped to a class the existing buttons share, e.g.:

```js
tbody.addEventListener("click", async (e) => {
  const btn = e.target.closest("button.proxy-btn[data-act]");  // ← scoped to .proxy-btn
  if (!btn) return;
  const act = btn.dataset.act;
  if (act === "open") { ... }
  else if (act === "my-new-act") { ... }   // your new branch is fine, just never reached
});
```

Your new button has `class="my-new-btn"` only — no `proxy-btn` — so `closest("button.proxy-btn[data-act]")` returns null and the handler short-circuits. The `data-act` is present, the click bubbles to `tbody`, the listener fires, but the selector filter rejects it.

**This is invisible in code review** because the new branch in the handler logic looks complete and correct. You have to remember that the SAME EVENT DELEGATION SELECTOR governs all buttons in this list.

**Fix:** Always include the host class on dynamically-injected buttons that should be routed by an existing delegation listener:

```js
// Wrong — captured by no delegation
`<button class="my-new-btn" data-act="my-new-act">X</button>`

// Right — keep host class, add your own for styling
`<button class="proxy-btn my-new-btn" data-act="my-new-act">X</button>`
```

The host class (`.proxy-btn`) is invisible — only used for delegation matching. Your style-specific class (`.my-new-btn`) handles appearance. The button gets routed by the existing handler with zero changes to the delegation code.

**Alternative — broaden the selector** (if you genuinely have a different button family):

```js
const btn = e.target.closest("button[data-act]");  // any button with data-act
```

But this can over-match (table filter buttons, modal-internal buttons inside the same `<tbody>` ancestor) and break other features. Prefer adding the host class.

**Diagnostic — when a new button \"does nothing\":**

1. Open devtools, find the delegation listener: `getEventListeners(document.querySelector('tbody'))` or grep `tbody.addEventListener`.
2. Read the `closest(...)` selector it uses.
3. Inspect the rendered HTML of your new button (`Elements` panel). Does its class list include the substring used in `closest(...)`?
4. If not — add the host class to the template. One-line fix.

**General principle:** When a list is rendered via a template-function and click-handled via delegation on the container, **the template and the handler are coupled through the selector**. New buttons must satisfy both: appear in the template AND match the delegation selector. Code review of either alone won't catch the mismatch. If you're adding many new actions, consider lifting the selector into a named constant at the top of the file (`const ROW_BTN_SEL = "button.proxy-btn[data-act]"`) so future authors at least see what they need to comply with.

This is a sibling to Pitfall 2 (`window.api` undefined — checklist for \"button does nothing\" should now ask BOTH \"is the IPC wired in preload?\" AND \"is the button captured by delegation?\").

---

1. Open devtools (Ctrl+Shift+I) — any console errors?
2. Open the **main process** console (terminal running `npm start`) — any preload.js errors?
3. Did you call `prompt()` / `alert()` / `confirm()` anywhere in renderer code? Replace with modal.
4. Is `window.api.xxx` defined? Check preload.js exposed it AND main.js handles it.
5. Does the IPC handler exist? `grep -n "ipcMain.handle.\"proxy:xxx\"" main.js proxy/ipc.js`
6. Any CSP errors? Move inline scripts to external files.
7. **User says "看不见 / 点不上 / 错位" with a screenshot?** Run vision analysis. If you see overlapping elements or modal pinned to top-left → Pitfall 15 (HTML uses CSS class that doesn't exist, modal degrades to inline block). `comm -23` HTML classes vs CSS classes to find the gap.
8. **User says "报警没响 / 通知没出来 / 一直没有修复" but the UI obviously knows about the event (badge, modal, log line)?** → Pitfall 17 (N detection sites, only some broadcast the alarm channel). Grep all detection sites and cross-reference renderer subscriptions; the fix usually goes in the shared `alertAndWait` / dispatcher, not in any single detection site.
9. **User says "新加的按钮没反应 / new button does nothing" but existing buttons in the same row work?** → Pitfall 18 (event delegation selector excludes new button class). Read the `closest(...)` selector in the row container's listener; the new button must include the host class (e.g. `.proxy-btn`) the selector requires.
10. **User says "声音/弹窗/通知没用 / 报警没响 / 删了"** → Pitfall 19 (sound + OS notification are unreliable in Electron; window-flash is the durable answer).
11. **User says "暂停键变 disabled 恢复不了 / 按了暂停按钮就死了 / 刷新还是暂停"** → Pitfall 20 (button disabled without finally + UI ignores `pauseRequested` transition state). Two fixes are needed together: `finally { btn.disabled = false }` AND a `running && pauseRequested` UI branch.
12. **User says "标记成功了还显示失败 / 已经改了 UI 没更新 / 重启 helper 才正常"** → Pitfall 23 (out-of-band write path skipped the renderer broadcast; frontend Map cache still holds the old value). Grep all `updateAzureStatus` / `saveProxies` write sites for matching `broadcast('...:runState', ...)` calls — missing ones are the bug.

---

## Pitfall 19 — Electron alarm UX: sound + system notifications are unreliable; window-flash works

**Symptom (user-reported patterns):**
- "声音报警既然解决不了，就删了" / "弹窗也没看见过，没用也删了"
- AudioContext beep doesn't play (Chromium autoplay policy, user has speakers muted, focus on a different app)
- Electron `new Notification(...)` shows briefly then folds into Win11 Action Center where the user never sees it
- Browser-native `Notification.requestPermission()` either denied silently or the toast never appears in fullscreen / focus-assist
- Operator misses captcha / blocking events because the "alarm" was technically fired but invisible

**Root cause:** Three failure modes compound:
1. **Audio** — AudioContext often starts suspended until a user gesture, and even when it resolves the user may have system sound off / be wearing headphones playing music / be in another room.
2. **OS notifications** — Win11 folds notifications into Action Center after ~5s; the operator running a 100-account batch is rarely looking at the corner of the screen at the exact moment the toast appears. Electron multi-window setups also mis-identify which window is the "owner" and the notification has no return-to-app affordance.
3. **Title flash** — `document.title = '🛑 ...'` only matters if the user is looking at the taskbar AND the Electron window is not foreground (so the taskbar entry shows the title). For an operator with the Helper window open on a second monitor, title flash is invisible.

**The pattern that survives:** **Flash the Helper window itself.** A red pulsing inset border around the entire BrowserWindow is impossible to miss because the operator is by definition looking at *some* monitor, and a window-sized flashing red box catches peripheral vision from across the room. Add a fixed banner at the top with the call-to-action text so they know what to do.

**Fix template:**

```css
/* renderer/style.css */
body.helper-alarm {
  animation: helperAlarmFlash 1s ease-in-out infinite;
}
@keyframes helperAlarmFlash {
  0%, 100% {
    box-shadow: inset 0 0 0 6px rgba(248, 81, 73, 0.95),
                inset 0 0 30px rgba(248, 81, 73, 0.35);
  }
  50% {
    box-shadow: inset 0 0 0 6px rgba(248, 81, 73, 0.45),
                inset 0 0 60px rgba(248, 81, 73, 0.55);
  }
}
body.helper-alarm::before {
  content: "🚨 有任务需要人工接管 — 看下面行的红色徽章, 处理完点「✅ 我过了, 继续」";
  position: fixed; top: 0; left: 0; right: 0;
  background: #f85149; color: #fff; padding: 6px 12px;
  font-size: 13px; font-weight: 600; text-align: center;
  z-index: 9999; pointer-events: none;
  animation: helperAlarmBarPulse 1s ease-in-out infinite;
}
@keyframes helperAlarmBarPulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.6; }
}
```

```js
// renderer/proxy-tab.js — replace the entire beep/Notification subsystem
const alarms = new Map(); // envId -> { reason, screenshot }

function refreshAlarmClass() {
  if (alarms.size > 0) document.body.classList.add('helper-alarm');
  else document.body.classList.remove('helper-alarm');
}
function startAlarm(envId, screenshot) {
  if (alarms.has(envId)) return;
  alarms.set(envId, { screenshot });
  refreshAlarmClass();
  toast(`🛑 ${envId} 需要人工接管`, "err");
}
function stopAlarm(envId) {
  if (!alarms.delete(envId)) return;
  refreshAlarmClass();
}

// Wire to ALL blocking-event channels — not just captcha — so login-stuck /
// slow-validation / soft-block all flash the window too. Pair with Pitfall 17.
window.api.onAzureCaptcha(p => p && p.envId && startAlarm(p.envId, p.screenshot));
window.api.onAzureCaptchaCleared(p => p && p.envId && stopAlarm(p.envId));
window.api.onAzureBlocking(p => p && p.envId && startAlarm(p.envId, ''));
window.api.onAzureUnblocked(p => p && p.envId && stopAlarm(p.envId));
```

**Also delete the backend Notification path:**
```js
// azure/alert.js — DELETE popNotification(...)
// Electron Notification folds into Win11 Action Center and isn't seen.
// Frontend `helper-alarm` class is the reliable signal.
```

**General principle:** **For desktop-app operator alerts, the window itself is the only display surface you can trust.** Sound depends on hardware/policy you can't control. OS notifications depend on the OS notification subsystem (Win11 Action Center, macOS focus, GNOME do-not-disturb). The window's own pixels are guaranteed to be on a monitor the operator is looking at *some* of the time — make those pixels scream. Pair with auto-clearing on unblock so the alarm stops the instant the work is done.

**Adjacent — when the user says "删了" about a feature:** Don't try to fix the deleted feature. They're telling you the entire approach is wrong, not that the implementation is buggy. Replace with a fundamentally different mechanism. In this case the right move is: delete sound, delete OS notifications, build window-flash. Don't half-keep \"a quieter beep\" or \"a smaller notification\".

---

## Pitfall 20 — Pause/resume UI deadlock: button disabled without finally + UI ignores the request-vs-status gap

**Symptom (user-reported patterns):**
- "按了暂停键后，暂停键变为不可点击，刷新也会变成暂停键，恢复不了流程"
- "暂停按钮按下就死了"
- UI shows pause button still rendered but greyed out / unclickable after click
- After reloading the renderer, the same row still shows pause-button-disabled
- State machine appears to be \"running\" indefinitely; no `paused` indicator ever appears

**Root cause family — two compounding bugs:**

**Bug A — `btn.disabled = true` without `finally`:** The click handler disables the button to prevent double-clicks, then never re-enables it on the success/failure path:
```js
} else if (act === "reg-pause") {
  btn.disabled = true;
  const r = await window.api.azurePauseOne(name);   // ← await, no try/finally
  if (!r.ok) toast(`⚠ ${name}: ${r.reason}`, "err");
  else toast(`⏸ ${name} 暂停中...`, "ok");
  // btn never re-enabled. Permanently dead until renderAccounts() rebuilds the row.
}
```
If `renderAccounts()` rebuilds the row (`reload()` fires, status changes), the user gets a fresh button. If status doesn't change (because Bug B), the dead button stays dead.

**Bug B — UI only watches `status`, ignores `pauseRequested`:** The backend has TWO fields: `status: 'running' | 'paused' | ...` (the actual state) and `pauseRequested: boolean` (the *intent* — \"the user pressed pause, but the state machine hasn't reached a control-check yet\"). The state machine only flips `status` from `running` → `paused` at known checkpoints (`checkControl()` between steps, sleep boundaries). If the state machine is mid-step (e.g. inside a long `alertAndWait` loop, mid-puppeteer-action, awaiting a network call) when the user presses pause, `pauseRequested = true` immediately but `status` stays `running` until the next checkpoint — which may never come if the state machine is blocked.

UI renders:
```js
if (regStatus === 'running') {
  return `<button data-act=\"reg-pause\">⏸</button>`;   // still shown as \"available to pause\"
} else if (regStatus === 'paused') {
  return `<button data-act=\"reg-resume\">▶</button>`;
}
```
User sees the pause button (because `status === 'running'`), clicks it again (button is dead from Bug A), nothing happens. They reload — same status, same dead button. Permanent UI lock.

**Adjacent failure — `alertAndWait` blocking loop doesn't respect pause:** Many state machines have a per-step `alertAndWait({ check, timeoutMs })` helper for manual-intervention prompts. The loop typically only polls `check()` and the user's `provideContinue(envId)` flag — it doesn't look at `pauseRequested` or `abortRequested`. So even at a \"checkpoint\" the loop never breaks out.

**Fix family — four things to do together (any one alone is insufficient):**

**Fix 1 — every action button gets `try { ... } finally { btn.disabled = false }`:**
```js
} else if (act === \"reg-pause\") {
  btn.disabled = true;
  try {
    const r = await window.api.azurePauseOne(name);
    if (!r.ok) toast(`⚠ ${name}: ${r.reason}`, \"err\");
    else toast(`⏸ ${name} 暂停中...`, \"ok\");
  } finally {
    btn.disabled = false;
  }
}
```

**Fix 2 — broadcast `pauseRequested` to the renderer, not just `status`:**
```js
function broadcastRunState(envId) {
  const c = _ensureCtrl(envId);
  broadcast('azure:runState', {
    envId: String(envId),
    status: c.status,
    pauseRequested: !!c.pauseRequested,    // ← critical, makes the transition visible
    abortRequested: !!c.abortRequested,    // ← same family
    // ...rest
  });
}
```
Same for `snapshotAllRunState` — the initial UI render after reload also needs to see the in-flight intent.

**Fix 3 — add a `running && pauseRequested` UI branch (the transition state):**
```js
const regStatus = rs && rs.status;
const pauseReq = rs && rs.pauseRequested;

if (regStatus === 'running' && pauseReq) {
  // ★ Transition: user clicked pause, state machine hasn't checkpointed yet.
  //   Show \"cancel pause\" so the user can reverse intent, or wait for status flip.
  return `<button class=\"...resume\" data-act=\"reg-resume\">▶ 取消暂停</button>
          <button class=\"...stop\"   data-act=\"reg-stop\">⏹</button>`;
} else if (regStatus === 'running') {
  return `<button class=\"...pause\"  data-act=\"reg-pause\">⏸</button>
          <button class=\"...stop\"   data-act=\"reg-stop\">⏹</button>`;
} else if (regStatus === 'paused') {
  return `<button class=\"...resume\" data-act=\"reg-resume\">▶</button>
          <button class=\"...stop\"   data-act=\"reg-stop\">⏹</button>`;
}
```
Three states, three button sets. User always has a way out, no dead button.

**Fix 4 — wire pause/abort into long-blocking helpers like `alertAndWait`:**
```js
async function alertAndWait({
  title, message, envId, check, timeoutMs, pollMs,
  isPaused = null,   // optional ()=>bool
  isAborted = null,  // optional ()=>bool
}) {
  // ...
  const deadline = Date.now() + timeoutMs;
  let pausedSince = 0, pausedTotalMs = 0;
  while (Date.now() < deadline + pausedTotalMs) {
    if (isContinued(id)) return { reason: 'flag' };
    if (isAborted && isAborted()) throw new Error('user-abort');
    if (isPaused && isPaused()) {
      if (!pausedSince) pausedSince = Date.now();
      await sleep(pollMs); continue;     // freeze timeout, skip check()
    } else if (pausedSince) {
      pausedTotalMs += Date.now() - pausedSince;
      pausedSince = 0;
    }
    if (await check()) return { reason: 'check' };
    await sleep(pollMs);
  }
}
```
Two wins:
- Operator's wall-clock during manual intervention doesn't count against the timeout (pause freezes the deadline).
- A long wait can be cleanly cancelled by pressing stop, instead of waiting out the full timeout.

**Avoid forcing every call-site to wire `isPaused` / `isAborted`** — inject them centrally via the helper's bind step:
```js
// alert.js
let _ctrlOf = null;
function bindElectron(electronMod, opts = {}) {
  if (typeof opts.ctrlOf === 'function') _ctrlOf = opts.ctrlOf;
}
// inside alertAndWait, fall back to _ctrlOf if caller didn't provide isPaused/isAborted:
if (!isPaused && _ctrlOf) isPaused = () => { const c = _ctrlOf(id); return !!(c && c.pauseRequested); };
if (!isAborted && _ctrlOf) isAborted = () => { const c = _ctrlOf(id); return !!(c && c.abortRequested); };

// azure/index.js — register the lookup once, all alertAndWait calls inherit it
alertMod.bindElectron(electron, {
  ctrlOf: (envId) => {
    const c = RUN_STATE.get(String(envId));
    return c ? { pauseRequested: !!c.pauseRequested, abortRequested: !!c.abortRequested } : null;
  },
});
```

**General principle — request-state machines need request-state UIs:**

Any state machine that exposes a \"please pause / please stop\" toggle from outside (UI button, signal, API call) almost always has TWO fields per request: the **intent** (`pauseRequested`) and the **realized state** (`status === 'paused'`). The gap between them is real wall-clock time — anywhere from milliseconds (next sleep boundary) to forever (blocked on a syscall, an unresponsive network call, a manual-takeover prompt).

The UI must render all three observable phases:
1. `running && !pauseRequested` — fully active, show pause button
2. `running && pauseRequested` — pause requested, transitioning, show \"cancel pause\" + stop
3. `paused` — confirmed paused, show resume + stop

And every action button MUST `try { ... } finally { btn.disabled = false }`. Treat raw `btn.disabled = true` followed by an `await` as a code smell — search for it during review.

**Diagnostic — when user reports \"暂停键死了\":**

```bash
# 1. Find all places that set btn.disabled = true without finally
grep -B1 -A6 \"btn.disabled = true\" renderer/*.js | grep -B6 \"await\" | grep -v finally

# 2. Find if the backend exposes pauseRequested to the renderer
grep -n \"pauseRequested\" renderer/ azure/ proxy/ preload.js

# 3. Find if the renderer renders a 'running && pauseRequested' branch
grep -n \"pauseRequested\\|pauseReq\" renderer/*.js
```
If all three return empty / one-sided results → confirmed Pitfall 20 in this codebase.

This pitfall pairs with Pitfall 17 (multi-path IPC, only some paths broadcast). Both stem from the same architectural mismatch: backend has richer state than the renderer's channels expose, and the renderer can't render what it doesn't see.

---

## Pitfall 21 — Page-injected favicon/title labels disappear on SPA route changes

**Symptom (user-reported patterns):**
- \"图标上还是没有环境号\" / \"有时候页面跳转就不显示\"
- The injected favicon + title prefix work on first load, then vanish after the user navigates inside Azure / Microsoft login / any SPA
- New tabs opened from `target=_blank` or `window.open(...)` start without the label
- F5 refresh sometimes restores it, sometimes doesn't (race with the site's own `<head>` rewrites)

**Root cause family:**
1. **SPA pushState/replaceState** — Modern login flows (Microsoft, Azure, Google) are SPAs. They navigate via `history.pushState(...)` which fires NO new-document event. `evaluateOnNewDocument` only runs at new document creation; pushState reuses the existing document, so your injection script doesn't re-run. The site then rewrites `<head>` to its own title/favicon and your label is gone.
2. **`evaluateOnNewDocument` race on `puppeteer.connect()` newPage** — If your automation does `puppeteer.connect(...)` to attach to an already-running browser, the `evaluateOnNewDocument` registration is per-`Page` and may miss tabs created by the user / by `window.open` between connect and the attach handler firing.
3. **Site replaces `<head>` wholesale on route change** — Some SPAs (Microsoft is one) replace `<head>` contents on `history.pushState`, blowing away your `<link rel=icon>` AND your title. MutationObserver scoped to `head` watches childList but the parent reset happens via innerHTML replacement on a wrapper, so the observer doesn't fire.

**Fix — five-layer redundancy:**

**Layer A — visible badge inside the page viewport, not just the tab chrome.** A fixed `position: fixed` overlay div in the page top-left is impossible for the SPA to delete unless it explicitly targets your element id, AND it's visible even when the tab strip is hidden / on a different monitor. Use `all: initial` to immunize against page CSS:

```js
function applyBadge() {
  if (!document.body) return;
  const BID = '__cloak_env_badge__';
  const old = document.getElementById(BID);
  if (old && old.dataset.label === ENV_NAME) return;  // already correct
  if (old) old.remove();
  window.__cloakSilent = true;
  try {
    const box = document.createElement('div');
    box.id = BID;
    box.dataset.label = ENV_NAME;
    box.textContent = SERIAL ? `${ENV_NAME} · ${SERIAL}` : ENV_NAME;
    box.style.cssText = [
      'all: initial',                      // ← critical: ignore page CSS
      'position: fixed; top: 6px; left: 6px',
      'z-index: 2147483647',               // max int32, top of stack
      'background: ' + LABEL_COLOR,
      'color: #fff; padding: 6px 12px',
      'font: 700 16px/1 -apple-system,\"Segoe UI\",\"Microsoft YaHei\",Arial,sans-serif',
      'border-radius: 8px',
      'box-shadow: 0 2px 8px rgba(0,0,0,0.35), 0 0 0 2px rgba(255,255,255,0.25) inset',
      'pointer-events: none',              // ← don't block page clicks
      'user-select: none',
      'white-space: nowrap',
      'opacity: 0.92',
    ].join(';');
    document.body.appendChild(box);
  } finally {
    setTimeout(() => { window.__cloakSilent = false; }, 0);
  }
}
```

`pointer-events: none` is non-negotiable — without it the badge eats clicks on whatever's underneath.

**Layer B — intercept SPA navigation methods:**
```js
try {
  const _ps = history.pushState, _rs = history.replaceState;
  history.pushState    = function() { const r = _ps.apply(this, arguments); setTimeout(tick, 50); return r; };
  history.replaceState = function() { const r = _rs.apply(this, arguments); setTimeout(tick, 50); return r; };
  window.addEventListener('popstate',   () => setTimeout(tick, 50));
  window.addEventListener('hashchange', () => setTimeout(tick, 50));
} catch (e) {}
```
The 50ms delay lets the SPA finish its DOM mutations before you re-inject (otherwise the SPA's rewrite happens AFTER your injection and wipes it).

**Layer C — MutationObserver on `<body>` (in addition to `<head>` from Pitfall 8):**
```js
function watchBody() {
  if (!document.body) { setTimeout(watchBody, 200); return; }
  new MutationObserver(() => {
    if (window.__cloakSilent) return;
    if (!document.getElementById('__cloak_env_badge__')) applyBadge();
  }).observe(document.body, { childList: true });
}
watchBody();
```
Only watch direct childList changes of body — subtree:true is too expensive on heavy pages. The check `getElementById(...)` is cheap; calling it on every body mutation is fine.

**Layer D — 2s sanity-check interval (the ONE place a low-frequency interval is justified):** Pitfall 9 says no setInterval in injection scripts — that's true for things that *do work* (DOM rewrites, PNG encoding, expensive ops). A bare `getElementById` + early-return is microseconds and fine to poll at 2s:
```js
setInterval(() => {
  if (!document.getElementById('__cloak_env_badge__')) tick();
}, 2000);
```
If you find yourself bumping this below 2s or having it do anything other than `getElementById + maybe-re-inject`, you've drifted into Pitfall 9 territory.

**Layer E — double-injection: launcher's `evaluateOnNewDocument` + post-connect `page.evaluate` fallback.** When `azure/flow.js` does `puppeteer.connect(...)` and then `newPage()` or grabs existing pages, immediately also call `page.evaluate(buildLabelInjectScript(...))` on each. Belt and suspenders for the connect race.

**General principle for any page-injected UI affordance (label, watermark, debug overlay):** The page is hostile. SPAs rewrite `<head>`, route changes don't fire `load`, MutationObservers can miss innerHTML replacements on wrapper nodes. Build redundancy: a body-level fixed element (Layer A), navigation interception (Layer B), DOM observation (Layer C), low-frequency sanity check (Layer D), and re-inject after every cross-process attach (Layer E). Any single layer can fail; all five failing simultaneously is rare.

**Adjacent — favicon ALONE is insufficient as an environment label.** The browser tab chrome may not be visible (full-screen, taskbar-icon-only mode, multi-monitor where the operator is looking at a different window). The Windows taskbar icon shows `chrome.exe`'s built-in `.ico`, NOT your favicon — that's a Win32 resource baked into the binary, unreachable from JS. Make peace with this: **for environment identification across 20+ open browsers, use an in-page badge (Layer A) as the primary signal**, and treat the tab favicon as a nice-to-have secondary indicator.

---

## Pitfall 22 — Two copies of the same injection script (launcher.mjs + flow.js or main + worker) drift silently

**Symptom (user-reported patterns):**
- You fix a bug in `proxy/label-inject.js` (or `azure/inject.js`, or wherever) — verified in dev — but in production some pages still show the old broken behavior
- Adding a new feature to the injection script: works in the first-launch path, doesn't work after `puppeteer.connect()` reattaches
- Hot-fixing the script in one file but the bug reappears: \"我改了一遍了，怎么又出来了？\"

**Root cause:** Page-injection scripts often live in TWO places by design:
1. `proxy/launcher.mjs` — passes the script to `evaluateOnNewDocument` at first browser launch (`.mjs`, ESM)
2. `azure/flow.js` or `azure/inject-helper.js` — re-injects after `puppeteer.connect()` because `evaluateOnNewDocument` races with newPage from another process (`.js`, CommonJS)

The dev (or AI agent) copy-pasted the script body into both locations. They start identical, but every subsequent edit only touches one — usually whichever file the bug report happened to point at. Within weeks the two are 60% the same / 40% drifted, and you spend hours wondering why your fix \"doesn't take\" in some flows.

**Diagnostic — find suspected duplicates:**
```bash
# Look for two functions building the same injection script
grep -rn \"function buildInjectScript\\|function buildLabelInjectScript\\|evaluateOnNewDocument\" --include='*.js' --include='*.mjs' .
```
If you see two `buildXxxScript` definitions in different files, you have a drift bomb.

**Fix — make CommonJS the single source of truth, ESM wraps it via `createRequire`:**

```js
// proxy/label-inject.js — CJS, the authoritative source
'use strict';
function buildLabelInjectScript(envName, serial, labelColor) {
  // ... all the injection logic ...
  return `(function() { /* ... */ })();`;
}
module.exports = { buildLabelInjectScript };
```

```js
// proxy/launcher.mjs — ESM, delegates to CJS
import { launch } from 'cloakbrowser/puppeteer';
import { createRequire } from 'module';
const _require = createRequire(import.meta.url);
const { buildLabelInjectScript: _buildLabel } = _require('./label-inject.js');

function buildInjectScript(envName, serial, labelColor) {
  // Delegate — one source of truth, both call sites get future fixes for free
  return _buildLabel(envName, serial, labelColor);
}
// ...rest of launcher
```

```js
// azure/flow.js — also CJS, plain require
const { buildLabelInjectScript } = require('../proxy/label-inject');
async function applyStealthToBrowser(browser, accountInfo) {
  for (const page of await browser.pages()) {
    try { await page.evaluate(buildLabelInjectScript(accountInfo.name, accountInfo.serial, accountInfo.color)); } catch (_) {}
  }
  browser.on('targetcreated', async (t) => {
    try {
      const p = await t.page(); if (!p) return;
      await p.evaluate(buildLabelInjectScript(accountInfo.name, accountInfo.serial, accountInfo.color));
    } catch (_) {}
  });
}
```

**Why `createRequire` and not converting launcher.mjs to CJS:** ESM is the modern default and many SDKs (`cloakbrowser/puppeteer`, anything using top-level `await`) effectively require .mjs. `createRequire(import.meta.url)` is the standard escape hatch — pulls in CJS modules from an ESM file with full Node.js semantics. One-line bridge, no toolchain changes needed.

**General principle — never copy-paste a non-trivial script body across module systems.** If you have an asset (injection script, validator, dictionary, template) used from both ESM and CJS, **CommonJS is the lowest common denominator** — ESM can `createRequire` it, CJS can `require` it directly. Define once, import twice, never drift. Same logic applies to JSON config files (define once, import from both sides), regex patterns, and string-constant tables.

This is the same family as Pitfall 14 (renderer-only `window.x =` modules reused in main) — both are \"single source of truth across module-system boundaries\" problems. The shim pattern from Pitfall 14 is for files you can't restructure; `createRequire` is for files you control.

---

## Pitfall 23 — State-write paths that skip the renderer broadcast → frontend cache Map displays stale status

**Symptom (user-reported patterns):**
- 「标记成功了，还显示失败？」/ 「我已经点了 ✅, UI 一直是 ❌」
- User clicks a manual mark-success / mark-failed / mark-ip-dead button. Toast says "已标记成功". The persisted JSON store actually got updated (verify with `cat data/proxies.json | jq '.accounts[] | select(.name==\"C015\")'`). But the UI status pill / row badge still shows the previous status — usually a stale failure message from the last batch run (e.g. "❌ 失败 批量模式: 跑完关浏览器").
- Reloading the renderer (`Ctrl+R`) FIXES IT — that's the giveaway. If reload fixes it, the bug is in the live in-memory cache, not the persisted state.
- Multi-window setup: only the window that fired the action eventually catches up (via `reload()` / `proxyList` reread); other windows stay stale until manually refreshed.

**Root cause family:** The renderer keeps a `Map<envId, runState>` (`azureRunState`, `taskState`, etc.) populated by **two channels**:
1. Initial snapshot on mount via `azure:getRunState` IPC (reads from disk + live runner module)
2. Live updates via `azure:runState` broadcast (fired from `emitProgress` inside the long-running task)

When you add a **third write path** that bypasses the long-running task — manual mark-success/failed handler in `proxy/ipc.js`, dashboard HTTP POST `/api/mark-success`, CLI tool that mutates the store directly, cronjob that ages out stale entries — it typically writes ONLY to the persistent store. It does not broadcast `azure:runState` because it never imports the `broadcast` helper from `azure/index.js`.

Result: store has new value, in-memory `RUN_STATE` map inside `azure/index.js` has new value (if the handler bothered to update it), but the **renderer's `azureRunState` Map still holds the last value broadcast by the long-running task** — which is whatever the task left there when it died/finished. For a batch that completed with "跑完关浏览器" as the final lastMsg, that's the message that stays glued to the row even after the user manually overrides the result.

`reload()` only reloads the proxy list (`proxyList` IPC). It does **not** re-fetch the run-state snapshot. So even after a deliberate reload by the user-action handler, the stale Map entry survives because nothing tells the renderer "throw away your cached run-state for envId X and read it again".

**Diagnostic recipe — when user says "UI 没更新, 但点击操作后端确实写了":**

```bash
# 1. Find every IPC handler / HTTP endpoint that mutates the persisted store
grep -rn "updateAzureStatus\|saveProxies\|update.*Status" --include='*.js' . | grep -v node_modules
# Each hit is a write path. List them.

# 2. For each write path, check whether it broadcasts azure:runState (or equivalent)
grep -B5 -A20 "updateAzureStatus" proxy/ipc.js | grep -E "broadcast|webContents.send|azure:runState"
# Missing = silent stale-UI bug

# 3. Find the canonical broadcast helper
grep -rn "azure:runState\|broadcast.*runState" --include='*.js' azure/ proxy/ main.js | grep -v node_modules
# Usually one in azure/index.js (used by the long-running task), zero in proxy/ipc.js

# 4. Find the renderer's cache Map and its update path
grep -n "Run.*State.*= new Map\|RunState\.set\|runState\.set" renderer/*.js
# Confirms the Map exists and is only fed by the broadcast channel
```

If steps 1-3 show write paths that don't broadcast, and step 4 confirms the renderer caches by Map (not by re-reading from store every render), you've got Pitfall 23.

**Fix — two layers, both needed:**

**Layer A — every state-write path broadcasts:** Add a small `broadcastRunState(envId, patch)` helper in the module that owns the write (e.g. `proxy/ipc.js`), require `electron` for `BrowserWindow.getAllWindows()`, and call it after every `updateAzureStatus(...)` / `saveProxies(...)` that changes a user-visible field.

```js
// proxy/ipc.js
const electron = require("electron");

function broadcastAzureRunState(envId, patch) {
  try {
    const payload = {
      envId: String(envId),
      status: patch.status || "idle",
      stage: patch.stage || "",
      lastMsg: patch.lastMsg || "",
      updatedAt: Date.now(),
      // startedAt / finishedAt deliberately omitted — let the renderer keep the
      // long-running task's earlier timestamps. We only override what the manual
      // action directly touches: status / stage / lastMsg.
      paused: false,
      pauseRequested: false,
    };
    for (const win of electron.BrowserWindow.getAllWindows()) {
      if (win.webContents && !win.webContents.isDestroyed()) {
        win.webContents.send("azure:runState", payload);
      }
    }
  } catch (_) {}
}

ipcMain.handle("proxy:azureMarkSuccess", (_e, name) => {
  const ok = store.updateAzureStatus(dataDirFn(), name, {
    status: "success", stage: "reached_payment", lastMsg: "手动标记成功",
  });
  if (ok) broadcastAzureRunState(name, { status: "success", stage: "reached_payment", lastMsg: "手动标记成功" });
  return { ok };
});
```

**Important — the payload shape must match what the long-running task emits.** If `azure/index.js` broadcasts `{ envId, status, stage, lastMsg, updatedAt, startedAt, finishedAt, paused, pauseRequested }`, your manual-path broadcast must use the same key names, otherwise the renderer's `azureRunState.set(envId, payload)` clobbers fields the renderer expected (e.g. blanking out `startedAt` makes "运行时长" disappear). Either copy all fields from the existing cache entry first OR document explicitly which fields you intend to overwrite vs preserve.

**Layer B — frontend mirrors the update locally as a belt-and-suspenders:** The broadcast can race with `reload()` (especially across multiple windows / multiple monitors / when devtools is open and slowing the IPC tick). Have the action handler ALSO `azureRunState.set(name, ...)` directly so the row re-renders in the same tick as the toast:

```js
} else if (act === "azure-mark-success") {
  if (!confirm(...)) return;
  btn.disabled = true;
  try {
    const r = await window.api.proxyAzureMarkSuccess(name);
    if (r.ok) {
      // Mirror the broadcast locally — don't wait for the round-trip
      azureRunState.set(name, {
        status: 'success', stage: 'reached_payment',
        lastMsg: '手动标记成功', updatedAt: Date.now(),
      });
      toast(`✅ ${name} 已标记成功`, "ok");
    } else {
      toast(`✗ ${name}: ${r.error || '失败'}`, "err");
    }
  } finally {
    btn.disabled = false;   // Pitfall 20 — never await without finally
  }
  await reload();
}
```

Both layers together: Layer A makes the broadcast right (fixes multi-window + first-load consistency), Layer B makes the source window's UI flip instantly (fixes the user-visible "I clicked, why is it still red?" complaint).

**General principle — broadcast parity for every state-write site:**

Whenever a backend has BOTH a long-running task that broadcasts state changes AND out-of-band manual handlers that mutate the same state (admin override, CLI fix-up, cronjob, HTTP endpoint), **every out-of-band path must broadcast on the same channels the renderer subscribes to**, with payload-shape parity. Treat the renderer's in-memory Map as a write-through cache where ANY backend write is a cache invalidation event — there is no "this update is too small to broadcast" exception, because the user sees stale state immediately.

Sibling to:
- Pitfall 17 (multi-detection-site, only some broadcast the alarm channel) — same architectural mismatch, different specific event class
- Pitfall 16 Rule A (in-memory state must be persisted on transitions) — Pitfall 23 is the dual: persisted state must also be broadcast on transitions, otherwise UI cache drifts the other way

**Diagnostic shortcut — frustration phrase index:**

| User says | Likely pitfall |
|---|---|
| "标记成功了, 还显示失败" / "已经改了, UI 没更新" / "重启 helper 才正常" | Pitfall 23 (this one) |
| "按了暂停就死了 / 暂停键恢复不了" | Pitfall 20 |
| "报警没响 / 弹窗没出来, 但 UI 知道" | Pitfall 17 |
| "状态丢了 / 重启 helper 后没了" | Pitfall 16 |
| "新加的按钮没反应, 旧按钮正常" | Pitfall 18 |
| "看不见 / 点不上 / 错位" | Pitfall 15 |
| "声音 / 通知没用 / 删了" | Pitfall 19 |

---

## Files

- `references/prompt-replacement-modal.md` — full HTML+CSS+JS template for a styled prompt replacement
- `references/adspower-ui-conventions.md` — detailed UX conventions for multi-account browser-manager UIs
- `references/windows-orphan-chromium-debug.md` — diagnostic recipe + 4-layer fix for Windows orphan Chromium subprocesses
- `references/spa-injection-five-layer-redundancy.md` — full template for the SPA-resilient label injection (badge + pushState hooks + observers + interval + post-connect re-inject)
