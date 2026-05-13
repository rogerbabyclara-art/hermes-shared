# Windows Chromium process-tree cleanup

When a Node/Electron host spawns a launcher that opens Chromium (CloakBrowser, Puppeteer, Playwright, real Chrome), **stopping the browser cleanly on Windows requires more than `child.kill()`**. This file documents the bug, the two-stage shutdown recipe, and the verification commands.

## The bug

Architecture (typical):

```
Electron main (main.js)
  └─ child_process.spawn('node', ['launcher.mjs', ...])   ← ACTIVE_BROWSERS.set(name, child)
       └─ Chromium main process (cloak/chrome binary)      ← detaches at startup
            ├─ renderer process
            ├─ renderer process
            ├─ GPU process
            ├─ network service process
            ├─ utility process
            └─ ... (5–10 children typical)
```

The Node launcher's `child` handle in Electron only points to the Node PID. The Chromium binary that Node spawned via `puppeteer.launch()` detaches itself at startup and is **not** a `child_process` of Node — it's a sibling, just orphaned to the same console session.

On **Linux/Mac**, `child.kill('SIGTERM')` lets you kill a process group with `process.kill(-pid)` IF the child was started with `detached: true`, and Chromium tends to forward signals to its children. Survivable.

On **Windows**, `child.kill()` calls `TerminateProcess()` on **exactly one PID**. No signal, no process group, no propagation. The Node launcher dies; every Chromium process keeps running.

### Symptoms

- After `start → stop` cycles, Task Manager shows ever-growing `chrome.exe` count (each cycle leaks ~6 processes × 100–300MB).
- Management UI status indicator stays on "running" / "locked" because the lock file outlives the launcher (the launcher's exit handler runs but the browser children kept the profile dir busy).
- After ~5 cycles the machine is in swap and the operator complains "为什么后台一直有进程".
- Killing Electron does not clean up — orphans survive until reboot or manual `taskkill`.

### Detection one-liner

```bash
tasklist | grep -iE "chrome\.exe|chromium" | wc -l
```

If this number grows after every start/stop cycle and never decreases without a reboot, you have the bug.

### CPU-pattern fingerprint — orphans pegging the same %

When orphans are also **eating CPU** (not just RAM), the giveaway is **identical CPU% across N orphan processes**. Task Manager shows e.g. four `Chromium` rows all at exactly 5.5% — that precise uniformity is impossible from organic activity; it means each orphan has the **same injected script running on the same interval**, doing identical work. Common culprits:

- A `setInterval` in `evaluateOnNewDocument`-injected code that does expensive work every N seconds (canvas redraw + `toDataURL('image/png')` + DOM mutation is a classic — see "Anti-pattern: polling injects" below).
- A polling health-check inside the page (e.g. `setInterval(() => fetch('/ping'), 1000)`).
- A WebSocket reconnect loop that never finds the dead parent and retries forever.

Confirm by checking accumulated CPU time per PID — if you see hours of CPU on a process that's been "idle":

```powershell
Get-Process -Id <pid> | Select-Object Id, ProcessName, @{n='CPU_s';e={$_.CPU}}, @{n='RAM_MB';e={[math]::Round($_.WorkingSet64/1MB,1)}}
```

A truly idle browser has `CPU_s` near zero. Hours of accumulated CPU on a backgrounded orphan = active loop inside the renderer.

### Anti-pattern: polling injects from `evaluateOnNewDocument`

If your launcher injects per-page setup code (favicon labeling, title rewriting, KMSI auto-handlers, etc.), **do not use `setInterval` for "just in case the page changes things back"** — that interval will run forever inside every orphaned renderer process when the parent dies, and the work compounds across all orphan windows.

Bad pattern (this session's actual root cause of 4 × 5.5% CPU):

```javascript
// Inside evaluateOnNewDocument-injected script — runs in every page in every window
setInterval(function() {
  applyTitle();    // mutates document.title
  applyFavicon();  // creates 64x64 canvas, paints rounded rect, calls toDataURL('image/png'), swaps <link rel=icon>
}, 2500);
```

Each `toDataURL('image/png')` is a synchronous PNG encode of the canvas pixels. At 2.5s cadence in N tabs × M orphaned windows, this is enough to pin a CPU core.

Good pattern — event-driven, zero idle cost:

```javascript
function tick() { applyTitle(); applyFavicon(); }

// Initial run
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', tick);
} else { tick(); }
window.addEventListener('load', tick);

// Re-apply when tab returns to foreground (cheap, fires only on user action)
document.addEventListener('visibilitychange', () => { if (!document.hidden) tick(); });

// Observe head for new <link rel=icon> or <title> elements that pages might add
function watch() {
  const head = document.head || document.getElementsByTagName('head')[0];
  if (!head) { setTimeout(watch, 500); return; }
  new MutationObserver((records) => {
    let needFavicon = false, needTitle = false;
    for (const r of records) {
      for (const n of r.addedNodes || []) {
        if (n.tagName === 'LINK' && /icon/i.test(n.rel || '')) needFavicon = true;
        if (n.tagName === 'TITLE') needTitle = true;
      }
    }
    if (needFavicon) applyFavicon();
    if (needTitle)   applyTitle();
  }).observe(head, { childList: true });

  const titleEl = document.querySelector('title');
  if (titleEl) {
    new MutationObserver(applyTitle).observe(titleEl, { childList: true, characterData: true, subtree: true });
  }
}
document.readyState !== 'loading' ? watch() : document.addEventListener('DOMContentLoaded', watch);
```

MutationObserver fires only when the page actually mutates the watched nodes — zero cost while idle. `visibilitychange` covers the "SPA changed things while tab was hidden" case without polling.

### Second footgun: MutationObserver self-feedback infinite loop

When you switch the polling pattern to MutationObserver, there is a **worse failure mode** than the original `setInterval`: an infinite recursive feedback loop that pegs CPU at 25–50% per browser (vs 5.5% for the polling version).

The trap: your reapply functions **mutate the same nodes the observer is watching**. `applyFavicon()` calls `head.appendChild(<link rel=icon>)`. `applyTitle()` sets `document.title`. So the sequence becomes:

1. Observer watches `head` childList.
2. `applyFavicon()` runs once at page load → appends `<link rel=icon>`.
3. Observer fires (`needFavicon = true` because a new icon link was added).
4. Observer calls `applyFavicon()` again.
5. Step 2 again. Forever.

Same story for title: `MutationObserver` on the `<title>` element with `characterData: true` fires when you write `document.title`, which calls `applyTitle()`, which writes `document.title`...

The CPU symptom is different from the polling bug — instead of 4 orphans all at 5.5%, you get **active browsers** (not orphans) all at 25–50% with RAM growing monotonically (each iteration creates a new canvas + PNG encode + DOM node).

**Fix: silent-flag guard + microtask-deferred release.** Wrap your own writes in a flag the observer checks before responding:

```javascript
function applyFavicon() {
  var url = makeFavicon();
  if (!url) return;
  window.__cloakSilent = true;          // mute self-triggered observer fires
  try {
    var olds = document.querySelectorAll("link[rel*='icon']");
    olds.forEach(function(l){ l.parentNode && l.parentNode.removeChild(l); });
    var link = document.createElement('link');
    link.rel = 'icon'; link.type = 'image/png'; link.href = url;
    (document.head || document.documentElement).appendChild(link);
  } finally {
    // Defer release to next microtask so the MutationObserver callback
    // queued for THIS mutation runs while the flag is still true.
    setTimeout(function() { window.__cloakSilent = false; }, 0);
  }
}

function applyTitle() {
  var orig = document.title || '';
  if (orig.indexOf(TITLE_PREFIX) === 0) return;
  var clean = orig.replace(/^\[.*?\]\s*/, '');
  window.__cloakSilent = true;
  try { document.title = TITLE_PREFIX + clean; }
  finally { setTimeout(function() { window.__cloakSilent = false; }, 0); }
}

// And in the observer callbacks:
new MutationObserver(function(records) {
  if (window.__cloakSilent) return;     // ignore our own writes
  // ...handle real page-originated mutations
}).observe(head, { childList: true });
```

**Why `setTimeout(..., 0)` instead of immediate `window.__cloakSilent = false`?** MutationObserver callbacks run as **microtasks**, after the current synchronous block finishes but before the next macrotask. If you set the flag back to `false` synchronously inside `applyFavicon()`'s `finally`, the observer's microtask sees `false` and re-fires the loop. `setTimeout(..., 0)` schedules a macrotask, which runs **after** all pending microtasks (including the observer's reaction to your write). By then the observer has already short-circuited on `__cloakSilent === true` and discarded the event.

A `queueMicrotask(() => { window.__cloakSilent = false; })` does NOT work for the same reason — it queues at the same priority as the observer's callback, ordering is implementation-detail. Stick with `setTimeout(..., 0)`.

**Verification:** open one browser, leave it on `about:blank` for 30 seconds, check Task Manager. Each Chromium row should be 0.0–0.3% CPU. If you see anything above 1% on an idle tab, the silent guard is missing or misplaced. To pinpoint which function loops, comment out `applyFavicon()` first; if CPU drops, the bug is in the favicon path; if not, it's `applyTitle()`.

**Don't try to fix this with `observer.disconnect()` / `observer.observe()` around your write** — works in isolation, but if a real page mutation happens to land in the same tick window, you miss it permanently. The silent-flag pattern is correct because the observer is never disconnected; it just chooses not to respond to known-self events.

## Defense in depth: parent-death self-suicide in the launcher

Stage 1 (stdin-close) and Stage 3 (Electron `before-quit`) handle the **graceful** parent-exit paths. They do NOT cover:

- Electron main process **hard crash** (segfault, OOM kill, force-quit via Task Manager).
- Operator killing the Electron process with `taskkill /F` on the parent only.
- Power loss / BSOD recovery where Electron didn't get to run cleanup.

In all of these, `child.stdin` on the launcher side is never closed cleanly — it just stops receiving data. The launcher keeps running, the Chromium children keep running, and you get orphans that are now **unkillable by normal means** (see next section).

The fix is a self-suicide watchdog inside the launcher itself:

```javascript
// In launcher.mjs, after browser is created:
const PARENT_PID = process.ppid;
setInterval(() => {
  try {
    process.kill(PARENT_PID, 0);   // signal 0 = existence check only, does not actually kill
  } catch (_) {
    // Parent is dead. Clean up and exit.
    gracefulShutdown('parent-dead');
  }
}, 5000);
```

`process.kill(pid, 0)` is the cross-platform "is this PID alive?" probe. It throws `ESRCH` when the PID is gone. The 5-second cadence is cheap (a single syscall) and bounds the orphan lifetime to 5s + the `browser.close()` flush window even under hard-crash conditions.

Caveat: PID reuse. On a long-uptime Windows host, the OS may reassign the parent's PID to a new process before the watchdog fires. The watchdog will then mistakenly think the parent is still alive. In practice this is rare (Windows PIDs are 32-bit and not reused aggressively within hours) and the worst case is one extra cycle of an orphan — better than orphans living until reboot. If you need stricter guarantees, also cross-check `process.ppid` on each tick: if it changes from the value captured at launch (Windows reparents orphans to PID 0 or to `services.exe` depending on session), trigger shutdown.

## When existing orphans can't be killed

Once parent processes have died and orphan Chromium has been adopted by the OS reaper, you may find that **even `taskkill /F /PID <pid>` returns "Access Denied"** — including from an admin shell. Observed in this session:

```
ERROR: The process with PID 38376 (child process of PID 30976) could not be terminated.
Reason: Access is denied.
```

What's happening: when the parent died, the security descriptor / process token reference that allowed cross-process termination went with it. The orphan now belongs to a session whose owner token is partially invalid. Even admin-level `taskkill` is denied because the ACL on the process object was set by the now-gone parent.

Workarounds, in order of preference:

1. **Don't get here in the first place** — the parent-death watchdog above prevents this entire class.
2. **Reboot.** Cleanest fix once you're in this state.
3. **Process Explorer (Sysinternals) → right-click → Kill Process Tree** — runs as SYSTEM with `SeDebugPrivilege` enabled, can usually override the ACL.
4. **`pskill -t <pid>` from Sysinternals** as Administrator. Same SeDebugPrivilege path.
5. **`wmic process where ProcessId=NNNN delete`** — sometimes succeeds where `taskkill` fails because it goes through WMI's different access path. Note `wmic` is deprecated/removed on Windows 11 24H2+; check availability first.

Plain `taskkill /F` from a normal admin cmd will fail. Don't waste cycles retrying it — escalate to Process Explorer or accept the reboot.

## The fix: two-stage shutdown

**Stage 1 — graceful**: signal the launcher to close the browser via the SDK (`browser.close()`), giving Chromium a chance to flush the profile directory cleanly. Profile corruption causes cookies/localStorage/IndexedDB loss on next launch.

**Stage 2 — force**: if the launcher hasn't exited in 3 seconds, kill the entire process tree with `taskkill /F /T /PID <pid>`. The `/T` flag is what kills the children — without it you just kill the launcher and you're back to square one.

### Patches needed in three files

#### 1. `launcher.mjs` — listen for graceful-shutdown triggers

The launcher must accept "please close" signals so stage 1 has something to talk to. The simplest cross-platform IPC: parent closes `child.stdin`, child detects `stdin.on('end' | 'close')` and calls `browser.close()`.

```javascript
// At the end of your launcher, after browser is created:
async function gracefulShutdown(reason) {
  emit({ type: 'shutdown', reason });
  try {
    await Promise.race([
      browser.close(),                              // let Chromium flush profile
      new Promise((r) => setTimeout(r, 3000)),      // ceiling — don't hang forever
    ]);
  } catch (_) {}
  process.exit(0);
}
process.on('SIGTERM', () => gracefulShutdown('SIGTERM'));
process.on('SIGINT',  () => gracefulShutdown('SIGINT'));
process.stdin.on('end',   () => gracefulShutdown('stdin-end'));   // works on Windows
process.stdin.on('close', () => gracefulShutdown('stdin-close'));
```

`SIGTERM`/`SIGINT` are kept for Linux/Mac and for human Ctrl-C debugging. The stdin listeners are the Windows-friendly path.

#### 2. `proxy/ipc.js` (or wherever you manage child processes) — two-stage `stopBrowser`

```javascript
function killTree(pid) {
  if (!pid) return;
  if (process.platform === 'win32') {
    try {
      require('child_process').execSync(`taskkill /F /T /PID ${pid}`, { stdio: 'ignore' });
    } catch (_) {}
  } else {
    try { process.kill(-pid, 'SIGKILL'); } catch (_) {}   // process group
    try { process.kill( pid, 'SIGKILL'); } catch (_) {}   // fallback
  }
}

async function stopBrowser(name) {
  const child = ACTIVE_BROWSERS.get(name);
  if (!child) return { ok: false, error: 'not running' };
  const pid = child.pid;

  // Stage 1: graceful — close stdin, launcher calls browser.close()
  try { child.stdin && child.stdin.end(); } catch (_) {}

  // Stage 2: wait up to 3s; if still alive, taskkill /T the whole tree
  await new Promise((resolve) => {
    let done = false;
    const t = setTimeout(() => {
      if (done) return;
      done = true;
      killTree(pid);
      resolve();
    }, 3000);
    child.once('exit', () => {
      if (done) return;
      done = true;
      clearTimeout(t);
      resolve();
    });
  });

  ACTIVE_BROWSERS.delete(name);
  return { ok: true };
}
```

For **batch close** (closing 10–20 browsers at once), use `Promise.all`, NOT sequential `await`. Sequential takes `count × 3s`; parallel takes 3s total:

```javascript
await Promise.all(names.map(async (name) => {
  try { await stopBrowser(name); } catch (_) {}
}));
```

Important: `stopBrowser` is now **async**. Every caller must `await` it (`proxy:closeBrowser` handler, `proxy:batchClose` handler, replace-IP flow, etc.). Forgetting to await means the lock-clearing code below the call races with the actual shutdown and you write `idle` to the lock file before the children are dead.

#### 3. Electron `main.js` — clean up on app quit

If the user clicks the X on the Electron window, `app.quit()` does NOT call your shutdown logic; Electron just closes the BrowserWindow. The Node launcher children inherit nothing and become orphans.

Export a `shutdownAll()` from your IPC module and call it in `before-quit`:

```javascript
// In proxy/ipc.js:
async function shutdownAll() {
  const names = Array.from(ACTIVE_BROWSERS.keys());
  await Promise.all(names.map(async (name) => {
    try { await stopBrowser(name); } catch (_) {}
  }));
}
module.exports = { register, shutdownAll };
```

```javascript
// In main.js:
let _proxyShutdownAll = null;
try {
  const mod = require('./proxy/ipc');
  mod.register(ipcMain, dataDir);
  _proxyShutdownAll = mod.shutdownAll;
} catch (e) { console.error(e); }

app.on('before-quit', async (e) => {
  if (!_proxyShutdownAll || app._proxyCleanupDone) return;
  e.preventDefault();                       // pause quit until cleanup finishes
  try { await _proxyShutdownAll(); } catch (_) {}
  app._proxyCleanupDone = true;             // guard against re-entry on app.quit()
  app.quit();
});
```

The `_proxyCleanupDone` guard prevents an infinite loop — `app.quit()` re-fires `before-quit`, and without the flag your handler would call itself forever.

## Verification recipe

After applying the patches:

1. Baseline: `tasklist | grep -iE "chrome\.exe|chromium" | wc -l` — record N.
2. Open 5 browsers via the UI.
3. Confirm Chromium count rose to roughly `N + 5×6 = N+30`.
4. Click "stop" on all 5 (or use batch close).
5. Wait 5 seconds. Re-run the tasklist command. Should be back to **exactly N**.
6. Open 5 again, then close the Electron window (X button) without stopping browsers first. Wait 5 seconds. Tasklist should be back to **exactly N**.

Any number above N after either path = the patch isn't complete. Common culprits:
- A caller of `stopBrowser` missing its `await` (lock state advances before kill).
- `taskkill` invoked from git-bash without `cmd /c` (MSYS interprets `/F` as a path — see "Invoking taskkill from git-bash" below).
- A launcher that doesn't listen for stdin close (stage 1 silently does nothing; stage 2 still works but profile may be corrupted).

## Invoking taskkill from git-bash

If you need to manually clean up orphans (e.g. during incident response), git-bash mangles `/F /T /IM` into path arguments. Use one of:

```bash
# Option A — explicit cmd shim
cmd //c "taskkill /F /T /IM chrome.exe"

# Option B — escape via MSYS no-conversion
MSYS_NO_PATHCONV=1 taskkill -F -T -IM chrome.exe

# Option C — drop into native cmd.exe
cmd
> taskkill /F /T /IM chrome.exe
```

Inside Node (via `execSync` or `spawnSync`), this is never an issue — Node calls the Windows CreateProcess API directly, no MSYS translation layer. The git-bash problem only affects interactive shell usage.

## Why not just `taskkill /F /T` always and skip stage 1?

Two reasons:

1. **Profile corruption**. Chromium writes cookies, IndexedDB, localStorage, and session restore data lazily. A `SIGKILL`-equivalent termination during a flush leaves the profile in an inconsistent state — next launch loses recently-set cookies, sometimes corrupts the entire user data directory and forces re-login. Stage 1's `browser.close()` flushes everything cleanly.

2. **Operator-triggered crashes look like Chromium crashes** in your logs. With stage 1, you get a clean "shutdown / stdin-close" event in the launcher's stdout log; with brute-force kill, the launcher's `browser.on('disconnected')` fires unexpectedly and your logs read like the browser crashed. Triage gets harder.

The 3-second timeout is the sweet spot — Chromium normally closes in 200–800ms; anything longer than 3s means it's hung and the user is waiting.

## Related host-cleanup tasks worth doing at the same time

While fixing this, also harden `proxy:list` to self-heal: every time the UI polls for status, scan `ACTIVE_BROWSERS` and remove entries where `child.killed || child.exitCode !== null`. This catches the case where the user kills the Chromium window manually via Windows close button — `browser.on('disconnected')` fires inside the launcher, the launcher exits, but the management UI doesn't notice until the next list call.

Optionally add a per-row `🔄 refresh` button that runs `process.kill(pid, 0)` (signal 0 = existence check, no-op if alive, throws if dead) and clears the lock state if the process is gone. This is the user-facing escape hatch for the rare case where everything else fails.
