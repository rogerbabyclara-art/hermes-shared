# Windows orphan Chromium subprocesses — debugging recipe

A field-tested playbook for an Electron app that spawns a fingerprint browser (CloakBrowser / Puppeteer / Playwright) and leaves dozens of `chrome.exe` orphans in Task Manager.

This reference complements **Pitfalls 8/9/10** in the parent SKILL.md.

---

## Symptom checklist (any of these)

- Task Manager shows 15-30+ `chrome.exe` after closing the Electron app
- `taskkill /F /IM chrome.exe` returns "Access is denied" or kills only some
- Multiple `chrome.exe` show **identical CPU %** (e.g. all exactly 5.5%, or all 7-10%)
- Memory creeps up over time even with no active browsing
- New `npm start` runs over time produce more and more chrome.exe

---

## Diagnostic step 1: who's the parent?

Find each chrome.exe's parent PID and check whether it's still alive. Save as `diag-tree.ps1`:

```powershell
$procs = Get-CimInstance Win32_Process -Filter "Name='chrome.exe' or Name='chromium.exe'"
$groups = $procs | Group-Object ParentProcessId
foreach ($g in $groups) {
  $ppid = $g.Name
  try {
    $parent = Get-CimInstance Win32_Process -Filter "ProcessId=$ppid" -ErrorAction Stop
    $parentName = $parent.Name
    $parentAlive = "ALIVE"
  } catch {
    $parentName = "<dead>"
    $parentAlive = "ORPHAN"
  }
  Write-Output ("PPID={0} ({1}) [{2}] -> {3} child chrome.exe" -f $ppid, $parentName, $parentAlive, $g.Count)
}
```

Run with: `powershell -NoProfile -ExecutionPolicy Bypass -File diag-tree.ps1`

Outcomes:

- **PPID alive (electron.exe / node.exe):** chrome was spawned by your launcher. Cleanup didn't run when launcher died. → Apply fixes A + B + C.
- **PPID `<dead>` (ORPHAN):** launcher already exited. These are stuck. → Manual kill via Pitfall-10 .bat below + add fix C so future launchers don't leak.

---

## Diagnostic step 2: who's burning CPU?

Sample CPU time **twice with a 10-second gap** and compute deltas. Save as `diag-cpu.ps1`:

```powershell
$procs = Get-CimInstance Win32_Process -Filter "Name='chrome.exe'"
foreach ($p in $procs) {
  $cpu = [math]::Round(($p.KernelModeTime + $p.UserModeTime) / 10000000, 2)
  $mem = [math]::Round($p.WorkingSetSize / 1MB, 0)
  Write-Output ("PID={0,-6} PPID={1,-6} Mem={2}MB CPU={3}s" -f $p.ProcessId, $p.ParentProcessId, $mem, $cpu)
}
```

Math: idle `about:blank` should accumulate **< 0.1s in 10s**. Anything that grew by 1+ second of CPU per 10s of wall clock is doing real work. The biggest contributors will be the renderer process (largest memory) and the GPU process — both run page JS or compositor work.

If many browsers all grew by the **same** number of seconds → shared bug (same injected polling script, same MutationObserver loop). See Pitfalls 8 & 9 in parent SKILL.md.

---

## Manual cleanup .bat (right-click → Run as administrator)

```bat
@echo off
echo Killing orphan chrome processes...
taskkill /F /PID <pid1>
taskkill /F /PID <pid2>
taskkill /F /PID <pid3>
echo.
echo Remaining chrome.exe count:
tasklist | findstr /I "chrome.exe" | find /C "chrome.exe"
echo.
pause
```

**Critical:** save as **plain ASCII**. UTF-8 (with or without BOM) gets mis-decoded by cmd's default GBK code page on a Chinese Windows host — you'll see `'釜瀛ゅ効' 不是内部或外部命令` and `'?echo' 不是内部或外部命令`. If you must include Chinese characters in echo lines, prepend `chcp 65001 >nul` before any echo.

`/T` (kill tree) on the launcher's PID sometimes fails with "Access is denied" if the launcher already died — Windows lost the job-object root. In that case kill each leaf PID individually as above.

---

## Permanent fixes — 4 layers, ALL needed

### Layer A — `killTree(pid)` helper

```js
function killTree(pid) {
  if (!pid) return;
  if (process.platform === "win32") {
    try {
      require("child_process").execSync(
        `taskkill /F /T /PID ${pid}`,
        { stdio: "ignore" }
      );
    } catch (_) {}
  } else {
    try { process.kill(-pid, "SIGKILL"); } catch (_) {}
    try { process.kill(pid, "SIGKILL"); } catch (_) {}
  }
}
```

### Layer B — `stopBrowser(name)` graceful-then-hard

```js
async function stopBrowser(name) {
  const child = ACTIVE_BROWSERS.get(name);
  if (!child) return { ok: false, error: "not running" };
  const pid = child.pid;
  try { child.stdin.end(); } catch (_) {}     // tell launcher to call browser.close()
  const exited = await new Promise((resolve) => {
    let done = false;
    const t = setTimeout(() => { if (!done) { done = true; resolve(false); } }, 3000);
    child.once("exit", () => { if (!done) { done = true; clearTimeout(t); resolve(true); } });
  });
  if (!exited) killTree(pid);                 // hard kill if graceful timed out
  ACTIVE_BROWSERS.delete(name);
  clearLock(dataDirFn(), name);
  return { ok: true };
}
```

For batch close, run with `Promise.all(...)` not a serial loop — otherwise N browsers takes N × 3 seconds.

### Layer C — launcher.mjs self-destruct

```js
// at the top, after `const browser = await launch(opts);`
browser.on('disconnected', () => process.exit(0));

async function gracefulShutdown(reason) {
  try {
    await Promise.race([
      browser.close(),
      new Promise(r => setTimeout(r, 3000)),
    ]);
  } catch (_) {}
  process.exit(0);
}

process.on('SIGTERM', () => gracefulShutdown('SIGTERM'));
process.on('SIGINT',  () => gracefulShutdown('SIGINT'));
process.stdin.on('end',   () => gracefulShutdown('stdin-end'));
process.stdin.on('close', () => gracefulShutdown('stdin-close'));

// Parent-death watchdog — the critical piece on Windows
const PARENT_PID = process.ppid;
setInterval(() => {
  try { process.kill(PARENT_PID, 0); }     // signal 0 = "are you alive?" check
  catch (_) { gracefulShutdown('parent-dead'); }
}, 5000);
```

The parent-death watchdog is what prevents new orphans from being created when Electron crashes or is force-killed.

### Layer D — Electron `before-quit` hook

Export a `shutdownAll()` from your IPC module and call it before app quit:

```js
// proxy/ipc.js
async function shutdownAll() {
  const names = Array.from(ACTIVE_BROWSERS.keys());
  await Promise.all(names.map(name => stopBrowser(name).catch(() => {})));
}
module.exports = { register, shutdownAll };

// main.js
let _shuttingDown = false;
const { register, shutdownAll } = require("./proxy/ipc");
register(ipcMain, dataDir);

app.on("before-quit", async (e) => {
  if (_shuttingDown) return;
  e.preventDefault();
  _shuttingDown = true;
  try { await shutdownAll(); } catch (_) {}
  app.quit();
});
```

The `_shuttingDown` flag prevents `app.quit()` from re-triggering `before-quit` infinitely.

---

## Verification protocol

After applying all 4 layers:

1. `npm start`, launch 2 browsers, let them sit `about:blank` for 30 seconds.
2. Task Manager → expand the `Chromium (N)` group. Each browser should be `0 - 0.5%` CPU. If still high, you have an injected-script self-recursion bug (Pitfall 8).
3. Click X on one Chromium window. Within 2 seconds the row in your UI should flip from ⏹ red back to ▶ green. If only after manual refresh, you have a missing IPC event push to the renderer (separate concern, not a process-tree bug).
4. `Alt+F4` the Electron app (or kill it from Task Manager to simulate crash). Within 5 seconds **all** chrome.exe should disappear from Task Manager. This proves Layer C parent-death watchdog is working.
5. Repeat steps 1-4 three times. The chrome.exe count after each "fully closed" state should always return to your machine's baseline (only Electron-app embedded Chromium of unrelated apps remain — Hermes Web UI, Cursor, ToDesk, etc.).

If step 4 leaves orphans, Layer C isn't firing. Check that `process.ppid` is the Electron main process, not an intermediate shell, and that the launcher is spawned with `{ stdio: ["pipe", "pipe", "pipe"] }` so stdin actually exists.

---

## Anti-pattern that caused this

```js
// BAD — only kills the Node launcher, leaves all Chromium subprocesses
function stopBrowser(name) {
  const child = ACTIVE_BROWSERS.get(name);
  child.kill();              // SIGTERM to Node, Chromium never sees it
  ACTIVE_BROWSERS.delete(name);
}
```

The Chromium main process is `child.spawn()`'d by `puppeteer-core` *inside* the Node launcher. Killing the launcher doesn't propagate. On POSIX you can put the launcher in a new process group and `kill(-pgid)`; on Windows you need a Job Object or `taskkill /T`. The 4-layer recipe above is the minimum that's portable and reliable.
