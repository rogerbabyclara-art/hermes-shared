# Captcha Alarm UX in the Electron Renderer

When a Puppeteer automation hits an anti-bot challenge and blocks waiting for a human, **the human has to actually notice**. The backend `alertAndWait` blocks for 3-5 minutes by default; if nobody clicks "continue" the task fails and risk escalates (repeat captcha on the same envId is a strong fingerprint flag). The longer this skill is silent, the worse the outcome.

This is the **renderer-side** counterpart to the backend pattern documented in the main SKILL.md (`captcha interception`, `progress.setBlocking`, `runner_alertAndTakeover`, etc.). The runner correctly detects captcha, screenshots it, and broadcasts an event — but a tab-buried Electron app is just as bad as silence. Operator awareness is part of the loop, not optional polish.

This file is the full UX recipe used in `form-helper-v2` (V3 Azure registration runner) and is the right starting point any time you're porting captcha handling into an in-app dashboard.

---

## The three components

```
┌─────────────────────────────────────────────────────────┐
│ 1. Backend broadcast      → azure:captcha (with screenshot path) │
│ 2. Renderer alarm loop    → beep + 5s repeat + system Notification + title flip │
│ 3. In-row "✅ 我过了, 继续" button → azureContinueOne(name) unblocks alertAndWait │
└─────────────────────────────────────────────────────────┘
```

The backend already has `blockOnCaptcha(page, envId, reason)` which screenshots + `emitProgress(envId, 'captcha', ...)` + `alertAndWait(...)`. The renderer doesn't need to know about `alertAndWait` — it only needs:

- A dedicated `azure:captcha` event (carries `envId` + `screenshot` path)
- A paired `azure:captcha-cleared` event (so the renderer stops the alarm without polling)
- An IPC handler `azure:continueOne(name)` that pokes the continue flag inside `alertAndWait` (unblocks the wait)

The renderer subscribes to `azure:captcha` and runs an alarm loop until either `azure:captcha-cleared` arrives (operator solved it / timeout / abort) or the operator clicks the in-row button (which calls `azureContinueOne` *and* stops the local alarm).

## Backend — the missing 4 lines

The existing `blockOnCaptcha` already does the screenshot and `emitProgress`. Add a paired broadcast at the start/end:

```js
async function blockOnCaptcha(page, envId, reason) {
  const fp = shotPath(envId, `99-captcha`);
  await page.screenshot({ path: fp, fullPage: true }).catch(() => {});
  emitProgress(envId, 'captcha', `${reason} — 截图 ${path.basename(fp)}`);

  // ★ Alarm event for renderer — picked up by onAzureCaptcha
  broadcast('azure:captcha', {
    envId: String(envId),
    reason,
    screenshot: fp,
    ts: Date.now(),
  });

  await alertMod.alertAndWait({ title, message, envId, check, timeoutMs: 3 * 60 * 1000 });

  // ★ Tell renderer to stop the alarm — paired with the start event
  broadcast('azure:captcha-cleared', { envId: String(envId), ts: Date.now() });
}
```

**Why not piggyback on `azure:runState` + `stage === 'captcha'`?** The renderer can derive *visibility* from runState (badge color, button choice) — but a dedicated alarm event lets the renderer be **edge-triggered** (start alarm exactly once when captcha appears) instead of having to debounce stage transitions. The `cleared` event is what guarantees the alarm stops even if the operator solved it via the desktop popup rather than the in-app button.

### ⚠️ CRITICAL: wire EVERY captcha-detect site, not just `blockOnCaptcha`

Real-session bug — `blockOnCaptcha` correctly broadcast `azure:captcha`, but the codebase ALSO had two other captcha detection paths in `flow.js` (`microsoftLogin` and `runForm2Fill`) that used `alertAndWait` directly without the prefix broadcast. UI badge fired (because `progress.setBlocking` was called) but no audio, no title flip, no Notification. Operator: "captcha detected but no alarm" — correct, because the alarm is a separate event channel from the status channel.

**Two ways to fix; prefer #2:**

1. **Manual** — copy the `broadcast('azure:captcha', ...)` + paired `azure:captcha-cleared` into every detect site. Fragile: any new detect site added later silently re-introduces the bug.

2. **Auto-detect inside `alertAndWait`** — push the classification into the shared helper. Any current and future caller gets the alarm for free:

   ```js
   // azure/alert.js (the shared helper called from every blocking-wait site)
   async function alertAndWait({ title, message, envId, check, timeoutMs }) {
     const id = String(envId);
     const isCaptcha = /captcha|人机|アカウントの保護|ロボット/i.test(
       String(title) + ' ' + String(message)
     );

     if (isCaptcha) {
       const m = String(message).match(/截图[:：]\s*(.+\.png)/);
       notifyRenderer('azure:captcha', {
         envId: id, reason: title || 'captcha',
         screenshot: m ? m[1].trim() : '', ts: Date.now(),
       });
     }
     notifyRenderer('azure:blocking', { envId: id, title, message, timeoutMs, startedAt: Date.now() });

     // ... existing wait loop ...

     // CRITICAL: pair on EVERY exit path (user-flag, check-success, timeout, exception)
     if (isCaptcha) notifyRenderer('azure:captcha-cleared', { envId: id, ts: Date.now() });
   }
   ```

   Now `microsoftLogin`, `runForm2Fill`, `blockOnCaptcha`, and any future `alertAndWait({ title: '...captcha...' })` caller gets the alarm automatically.

**Audit command for any existing system**:

```bash
# Should match every code path that triggers a "blocking" condition
grep -rn "alertAndWait\|blockOnCaptcha\|setBlocking" azure/ flow/ runner/
# Then for each match, grep nearby for the alarm channel
grep -rn "broadcast.*azure:captcha\|notifyRenderer.*azure:captcha" azure/ flow/ runner/
```

The two lists should have the same set of files. If a file is in the first list but not the second, it's a silent-alarm bug.



## Renderer — `onAzureCaptcha` subscription + alarm map

```js
const captchaAlarms = new Map(); // name -> { timer, count, screenshot, titleFlip }

window.api.onAzureCaptcha((payload) => {
  if (!payload || !payload.envId) return;
  startCaptchaAlarm(payload.envId, payload.screenshot);
});
window.api.onAzureCaptchaCleared((payload) => {
  if (!payload || !payload.envId) return;
  stopCaptchaAlarm(payload.envId);
});
```

Keep alarms keyed by envId — two envIds can hit captcha simultaneously (rare but possible in batch mode with parallel pools), and each needs its own alarm state.

## Web Audio beep pattern (three-tone, no external files)

External audio files are a packaging nightmare in Electron (asar paths, file:// CSP). Use `AudioContext`:

```js
let _audioCtx = null;
function audioCtx() {
  if (!_audioCtx) {
    try { _audioCtx = new (window.AudioContext || window.webkitAudioContext)(); }
    catch (_) { return null; }
  }
  return _audioCtx;
}

function beep(duration = 350, freq = 880, volume = 0.25) {
  const ctx = audioCtx();
  if (!ctx) return;
  try {
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.type = 'sine';
    osc.frequency.value = freq;
    gain.gain.value = volume;
    osc.connect(gain).connect(ctx.destination);
    osc.start();
    setTimeout(() => { try { osc.stop(); } catch {} }, duration);
  } catch {}
}

function alarmPattern() {
  // Three-tone like a scaled-down siren — distinct from system notification sounds
  beep(200, 880);
  setTimeout(() => beep(200, 660), 250);
  setTimeout(() => beep(300, 880), 500);
}
```

**Pitfall — AudioContext "user gesture" requirement**: Chromium blocks `AudioContext` until the page sees a user interaction (click, key press). If the operator hasn't clicked anywhere in the app since launch, the first `osc.start()` will be silent. Mitigation: lazy-init the context in `audioCtx()` (so it's created at first beep, not at page load) — by the time captcha fires, the operator has almost certainly clicked something. If you must guarantee sound from the very first event, hook a `document.addEventListener('click', () => audioCtx().resume(), { once: true })` at app start.

**Pitfall — don't use `Audio` element with a data URI**: Same gesture restriction, more memory, no synthesis flexibility. `AudioContext` is the right primitive.

## The repeat-alarm loop (5s cadence, hard cap)

A single beep is not enough — the operator may have just stepped away. Repeat every 5 seconds, but **cap the total** (after the backend's 3-min timeout, the alarm is pointless):

```js
function startCaptchaAlarm(name, screenshot) {
  if (captchaAlarms.has(name)) return;        // already alarming for this envId

  alarmPattern();                              // fire immediately
  toast(`🛑 ${name} 出现人机验证, 请在浏览器里通过`, "err");

  // Desktop OS notification — works even when Electron window is minimized
  try {
    if (window.Notification && Notification.permission === 'granted') {
      const n = new Notification(`Azure 注册 ${name} 触发人机验证`, {
        body: '请在 CloakBrowser 里通过验证, 然后回 UI 点「✅ 我过了, 继续」',
        requireInteraction: true,
      });
      n.onclick = () => { try { window.focus(); } catch {} n.close(); };
    } else if (window.Notification && Notification.permission !== 'denied') {
      Notification.requestPermission();
    }
  } catch {}

  const state = { count: 1, screenshot, titleFlip: false };
  state.timer = setInterval(() => {
    state.count++;
    if (state.count > 30) {                    // cap: 30 × 5s = 2.5 min, slightly under backend timeout
      clearInterval(state.timer);
      captchaAlarms.delete(name);
      return;
    }
    alarmPattern();
    // Title flip — visible in taskbar even when window is in the background
    state.titleFlip = !state.titleFlip;
    document.title = state.titleFlip ? `🛑 ${name} 人机验证!` : 'Form Helper V3';
  }, 5000);

  captchaAlarms.set(name, state);
}

function stopCaptchaAlarm(name) {
  const state = captchaAlarms.get(name);
  if (!state) return;
  clearInterval(state.timer);
  captchaAlarms.delete(name);
  if (captchaAlarms.size === 0) document.title = 'Form Helper V3';
}
```

**Why a hard count cap, not duration math?** The 5s interval drifts when the event loop is busy. Counting iterations is simpler and bounds the side effects (max 30 beeps).

**Why slightly under the backend timeout (2.5 min vs 3 min)?** The backend's 3-min timeout triggers `captcha_timeout` → close + reopen. If the alarm is still going at that moment, the operator gets a confusing "alarm still on, but the task is being retried" overlap. Cutting the alarm 30s early avoids it.

## Title flip — the cheapest cross-task-switch indicator

Most Electron apps forget `document.title` is the **single most reliable signal** when the app isn't focused:
- Visible in the OS taskbar / alt-tab list
- Picked up by Windows' "flashing taskbar" attention system on focus loss
- Survives even when the renderer page is throttled (background tab)

Always pair the title flip with the audio alarm. Two channels (audio + title), not one.

## Distinct badge state — `azs-captcha` with pulse animation

The status badge for `stage === 'captcha'` should be **visually distinct from the failure state**. Failure is dead red; captcha-waiting is *living* red (animation = "waiting for you"):

```css
.azs-captcha {
  background: rgba(248, 81, 73, 0.18);
  border-color: rgba(248, 81, 73, 0.85);
  color: #ff7b72;
  animation: azs-captcha-pulse 1.2s ease-in-out infinite;
  font-weight: 700;
}
@keyframes azs-captcha-pulse {
  0%, 100% { box-shadow: 0 0 0 0 rgba(248, 81, 73, 0.7); background: rgba(248,81,73,0.18); }
  50%      { box-shadow: 0 0 8px 3px rgba(248, 81, 73, 0.45); background: rgba(248,81,73,0.30); }
}
```

In the JS badge renderer, check `stage === 'captcha'` **before** checking `status` — captcha overrides whatever status says (often `running`):

```js
if (stage === 'captcha') {
  label = '🛑 人机验证 等待中';
  cls   = 'azs-captcha';
} else if (s === 'running') { ... }
```

Subtitle: instruct the operator what to do — `请在浏览器里通过, 然后点「✅ 我过了」`. Don't leave them guessing.

## The in-row "✅ 我过了, 继续" button

When `stage === 'captcha'`, the per-row action buttons swap from the normal `⏸/⏹` pair to a **green pulsing continue button**:

```js
const captchaWait = rs && rs.stage === 'captcha';
let regBtns = '';
if (captchaWait) {
  regBtns = `
    <button class="proxy-btn proxy-btn-captcha-ok" data-act="reg-captcha-ok"
            title="人工通过 captcha 后点这个继续">✅ 我过了, 继续</button>
    <button class="proxy-btn red" data-act="reg-stop" title="放弃这次注册">⏹</button>`;
} else if (regStatus === 'running') { ... }
```

```css
.proxy-btn-captcha-ok {
  background: #238636 !important;
  color: #fff !important;
  border-color: #2ea043 !important;
  font-weight: 700 !important;
  animation: az-captcha-btn-pulse 1.4s ease-in-out infinite;
}
.proxy-btn-captcha-ok:hover { background: #2ea043 !important; animation: none; }
@keyframes az-captcha-btn-pulse {
  0%, 100% { box-shadow: 0 0 0 0 rgba(46, 160, 67, 0.6); }
  50%      { box-shadow: 0 0 8px 3px rgba(46, 160, 67, 0.4); }
}
```

Click handler:

```js
} else if (act === "reg-captcha-ok") {
  btn.disabled = true;
  stopCaptchaAlarm(name);  // local alarm off immediately (don't wait for backend echo)
  const r = await window.api.azureContinueOne(name);
  if (r && r.ok === false) toast(`⚠ ${name}: ${r.reason || '无效'}`, "err");
  else toast(`✅ ${name} 已通知后端继续`, "ok");
}
```

**Stop the alarm *before* the IPC** — the IPC could be slow (a few hundred ms while `alertAndWait`'s polling loop wakes up), and the operator already gave the signal. Don't make them listen to another beep.

## Anti-patterns

- **Don't use `window.alert()` / `confirm()`** — they're disabled in Electron renderer by default (see `electron-renderer-pitfalls`), and even when enabled, a modal blocks the renderer's event loop, freezing other ongoing tasks' UI updates. Use the in-row button + alarm loop instead.
- **Don't poll `azureRunState` to detect captcha** — works, but you'll either alarm on every stage update or have to track previous state. The dedicated `azure:captcha` event is edge-triggered and trivially correct.
- **Don't put the continue button in a separate "captcha panel"** — operator's eyes are on the task row where the badge changed. Putting the action at the row level halves the time-to-click.
- **Don't reuse the failure red color** — operators learn to dismiss red as "this one is dead". Captcha-waiting needs its own animation so the eye is drawn back to *the live one*.
- **Don't skip the system Notification** — operators alt-tab away constantly. Notification is the only signal that survives the app being completely out of view.

## Reusability

This recipe applies any time the renderer needs to attract operator attention for a per-task event that requires human action:
- Captcha during automation
- Phone-verification SMS arrived (operator types code in)
- Bank 3DS prompt during payment
- Unexpected page that the state machine doesn't know how to handle ("takeover" mode)

The shape is always the same: dedicated `xxx:alert` + `xxx:alert-cleared` event pair → renderer alarm map keyed by entity → audio + title + Notification + distinct badge animation + in-row resumption button → click handler stops alarm + IPC unblocks backend.
