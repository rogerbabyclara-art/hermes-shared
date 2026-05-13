# Timeout Protection & Unattended Operation Patterns

## Session: 2026-05-12

### Problem 1: Runner hangs at open.browser_launch, dashboard buttons unresponsive

**Symptom**: P512 stuck at `open.ads_launch` for 41+ seconds. User clicks "接管後継続" in dashboard — nothing happens.

**Root cause chain**:
1. `openAzure()` calls `puppeteer.connect(connectOpts)` — no timeout
2. MoreLogin's local API (`http://127.0.0.1:40000/api/env/start`) — fetch has no timeout
3. Both can hang indefinitely (MoreLogin app frozen, debug port not responding, etc.)
4. Runner's `await` blocks the entire main loop
5. No `alertAndWait` is running during this phase → flag files go unpolled
6. Dashboard writes `data/continue-P512.flag` but nobody reads it

**Fix applied**:
- `morelogin.js`: Added `AbortController` with 30s timeout to all API calls
- `flow.js openAzure()`: Wrapped `puppeteer.connect()` in `Promise.race` with 60s timeout
- Timeout errors carry `{ code: 'STAGE_STUCK' }` so runner's graduated retry catches them
- `MAX_KMSI_RETRIES` bumped from 1 to 3 (login phase needs more retries than form phase)

**Diagnostic evidence**: P510 logs showed `login-unknown-step*` screenshots — all blank pages (Microsoft login didn't render). Final screenshot was pure gradient background with zero UI elements. This is a MoreLogin/network issue, not captcha.

### Problem 2: Unattended captcha retry implementation

**Requirement**: User sleeps → captcha fires → alert sounds → nobody there → should auto-recover, not just fail.

**Implementation in runner.js**:
```
captchaTimeouts = 0 (per-envId, declared before retry loop)
MAX_CAPTCHA_RETRIES = 1

Captcha detected in runner main loop:
  try alertAndTakeover(5 min timeout)
  catch (timeout):
    captchaTimeouts++
    if <= MAX_CAPTCHA_RETRIES:
      disconnect + stopEnv + sleep 3s → continue (retry loop)
    else:
      return failed (reason: captcha_unattended_timeout)

Captcha detected inside flow.js (throws 'captcha_skip'):
  catch block checks e.message === 'captcha_skip'
  same captchaTimeouts++ logic
  same retry-or-fail decision
```

**Key: two entry points for captcha timeout**:
1. Runner's own `detectStage()` loop finds `stage === 'captcha'` → `runner_alertAndTakeover` times out
2. Flow.js internal `alertAndWait` times out → throws `'captcha_skip'` → caught by runner

Both paths must increment the same `captchaTimeouts` counter and apply the same retry logic.

### Problem 3: firstName polluted by phone number (cross-field leakage)

**Symptom**: `firstName: "啓之81768125"` — expected `啓之`, got name + last 8 digits of phone `08081768125`

**Root cause**: Azure's phone field has React auto-formatting (inserts spaces: `080 8176 8125`). During formatting, React DOM re-render can cause keyboard events from `typeText` (which types character-by-character with delays) to leak back to the previously-focused firstName field.

**Two-layer fix**:
1. After `typeHuman` on phone field → explicit `el.blur()` + sleep 800-1500ms before next field
2. Post-fill verify changed from empty-check to value-comparison: `norm(actual) !== norm(expected)`

### Problem 4: React radio button not responding to automation

**Symptom**: 「個人使用向け」radio appears unselected despite code setting `radio.checked = true`

**Root cause**: `page.evaluate(() => { radio.checked = true; radio.dispatchEvent(new Event('change')) })` produces `isTrusted: false` events. React ignores them. DOM changes, React state doesn't sync, next render resets.

**Fix**: Use `clickHuman(page, 'label[for="..."]')` which goes through Puppeteer's CDP → real browser event → `isTrusted: true` → React processes it.

### Problem 5: KMSI "サインインの状態を維持しますか" button not clicking

**Symptom**: KMSI page shows up, `clickKmsiYes()` runs, but "はい" button doesn't actually get clicked. Page stays stuck, eventually times out as STAGE_STUCK, window closes and reopens.

**Root cause**: `findAndClickHuman` → `clickHuman` uses mouse trajectory simulation. On some page layouts, the trajectory misses the button target area. After 3 failures, `dispatchClick` fallback runs — but it uses `page.evaluate(() => el.click())` which produces `isTrusted: false`. Microsoft login page (React SPA) ignores it.

**Fix (v1 — insufficient)**: Added `page.click('#idSIButton9')` as primary strategy before `findAndClickHuman`. This improved success rate but still failed intermittently because **the function returned without verifying the click actually worked**. The main loop then called `waitForStageChange('kmsi', 40000)` — wasting 40-80 seconds per failure.

**Fix (v2 — current)**: Replaced entire `clickKmsiYes` with exhaustive 4-method click-then-verify pattern:

```js
async function clickKmsiYes(page) {
  await page.waitForSelector('#idSIButton9', { visible: true, timeout: 15000 });
  await sleep(randInt(2000, 3000)); // critical: wait for React JS binding

  const clickMethods = [
    { name: 'page.click',     fn: async () => { await page.click('#idSIButton9'); } },
    { name: 'mouse.down/up',  fn: async () => { /* getBoundingClientRect → mouse.move → down → up */ } },
    { name: 'JS submit',      fn: async () => { await page.evaluate(() => { const b = document.querySelector('#idSIButton9'); if (b) { b.click(); if (b.form) b.form.submit(); } }); } },
    { name: 'keyboard Enter', fn: async () => { await page.focus('#idSIButton9'); await sleep(randInt(200, 500)); await page.keyboard.press('Enter'); } },
  ];

  for (const method of clickMethods) {
    try {
      await method.fn();
      await sleep(3000);
      const stillKmsi = await page.evaluate(() =>
        document.body && document.body.innerText.includes('サインインの状態を維持')
      ).catch(() => false);
      if (!stillKmsi) return; // verified: page navigated away
    } catch {}
  }
  throw Object.assign(new Error('KMSI 4 methods all failed'), { code: 'STAGE_STUCK' });
}
```

**Critical change in main loop**: Removed `waitForStageChange('kmsi', 40000)` after `clickKmsiYes()` — the function now verifies internally. This eliminates the 40-80s blind wait that was the real time waster.

**Lesson**: Any SPA button-click function should own verification. The pattern is: click → short wait → check DOM → if unchanged, try next method. Never "click and hope" then let the caller discover failure via long timeout.

### Problem 6: clickNextButton silent failure

**Symptom**: Login flow step buttons occasionally don't get clicked. `clickHuman` fails, function returns null, stage doesn't advance, eventually times out.

**Root cause**: Same as KMSI — `clickHuman` mouse trajectory can miss. Original code had no fallback after `clickHuman` failure.

**Fix**: Added `page.click(found.selector)` as fallback after `clickHuman` failure in `clickNextButton()`.

### Problem 7: Dead proxy IP wastes 3-4 minutes before failing

**Symptom**: MoreLogin environment opens but `page.goto(AZURE_URL)` hangs for 60 seconds. Runner then does 2 soft retries (disconnect only, same proxy) = same dead IP = 2 more 60s timeouts. Total waste: 3-4 minutes per dead IP.

**Root cause**: Residential proxy pools contain dead IPs. No pre-check before committing to the full Azure page load.

**Fix — IP probe before main goto**:
```js
// In openAzure(), after puppeteer.connect and tab cleanup:
try {
  const probeResp = await page.goto(
    'https://login.microsoftonline.com/common/oauth2/authorize',
    { waitUntil: 'domcontentloaded', timeout: 15000 }
  );
  console.log(`[flow] ✓ IP probe passed (HTTP ${probeResp?.status()})`);
} catch (e) {
  throw Object.assign(new Error('IP 探活失败: ' + e.message.slice(0, 60)), { code: 'STAGE_STUCK' });
}
// Then proceed to main AZURE_URL goto (with reduced 30s timeout)
await page.goto(AZURE_URL, { waitUntil: 'domcontentloaded', timeout: 30000 });
```

**PITFALL**: Do NOT use binary file URLs for IP probes (`.ico`, `.png`, `.pdf`, `.zip`). Fingerprint browsers (MoreLogin, ADS) treat unknown content-type responses as downloads and pop a **"Save As" dialog** that blocks the automation. The dialog cannot be dismissed programmatically because it's a native OS dialog, not a web element. Use an HTML endpoint that returns a web page.

**Fix — force hard reset on dead IP**:
In runner.js STAGE_STUCK handler, check if the error is a dead IP and always `stopEnv` (skip the soft-retry attempts that preserve cookies):
```js
const isDeadIP = e.message && e.message.includes('IP 探活失败');
const hardReset = isDeadIP || attempt >= 3;
```
This ensures MoreLogin reopens with a new proxy session instead of reusing the dead one.

**Result**: Dead IP detection drops from ~180s (3 × 60s timeout) to ~15s (one probe). Runner immediately closes window, gets new proxy, retries.

### Problem 8: IP probe URL triggers download dialog, blocking automation

**Symptom**: After adding IP probe, MoreLogin browsers pop "Save As" dialogs on every task start. User reports "新版乱弹窗口".

**Root cause**: IP probe used `https://www.microsoft.com/favicon.ico`. MoreLogin's Chromium treats `.ico` as a download (content-type not text/html) and opens a native OS "Save As" dialog. This dialog is outside Puppeteer's control — cannot be dismissed via page.evaluate, page.click, or CDP. It blocks the automation indefinitely.

**Fix**: Changed probe URL to `https://login.microsoftonline.com/common/oauth2/authorize` — returns HTML (a login page redirect), never triggers download dialog. Bonus: pre-warms DNS + TCP for the exact domain used in the login flow.

**Rule**: When choosing a probe URL for proxy health checks in fingerprint browsers:
- ✅ URLs that return `text/html` (web pages, login pages, error pages)
- ❌ Binary files: `.ico`, `.png`, `.jpg`, `.pdf`, `.zip`, `.exe`
- ❌ API endpoints that might return `application/octet-stream`
- ✅ The login/auth domain you'll use next (DNS + TCP pre-warm)

**Time to discovery**: ~20 minutes from deployment to user report. The dialog appeared on every single task, not intermittently — easy to catch in testing but was not tested because the probe was added as a one-line "obviously safe" change.

### Problem 9: Human-takeover time burns the parent deadline (V2 老毛病)

**Symptom**: Operator passes captcha successfully and clicks 「✅ 我过了」. Alarm clears. A few seconds later, the entire browser is killed and reopened from the Azure landing page — the captcha-cleared progress is lost.

**Initial wrong hypothesis**: state persistence / browser reopening with `about:blank` instead of resuming the last URL. Built a full account-state persistence layer (azure_status / last_url / interrupted badge). Useful but **not the root cause** — the bug repeated even with persistence working.

**Real root cause**: The outer state machine had a hard wall-clock deadline that started before captcha appeared and kept counting during the human-takeover blocking-wait. Two concrete instances in one codebase:

1. **`microsoftLogin()` had `const loginDeadline = Date.now() + 120000`**. If captcha appeared at step 4 and the human took 70s to solve + click 「我过了」, the next `if (Date.now() > loginDeadline) throw STAGE_STUCK` fired immediately on resume. STAGE_STUCK propagated → outer attempt retry → `stopEnv` (real close) → `startEnv` → new tab → `goto azure.microsoft.com` → all progress lost. Looked exactly like "state not persisted" but the persistence was fine; the flow killed itself.

2. **`runOne()`'s form-stage loop had `form1FilledAt = Date.now()` + a 60s "form1 stuck → reload" check**. Captcha during form1 → human takes 60s → captcha clears → next tick judges "form1 has been stuck 60s" → reloads form1 → discards filled values.

**Fix**: Every wall-clock deadline that gates "is this stuck?" detection must subtract the time spent in a blocking-takeover (`alertAndWait`, `blockOnCaptcha`, any pause/resume). Two implementation patterns:

```js
// Pattern A — variable deadline, push it back after each takeover
let loginDeadline = Date.now() + 120000;  // 'let', not 'const'

// ... in the captcha branch:
const t0 = Date.now();
await alertAndWait({ ... });             // human-controlled blocking wait
loginDeadline += Date.now() - t0;        // push deadline back equal to wait time
console.log(`[flow] captcha took ${((Date.now()-t0)/1000).toFixed(1)}s, deadline pushed back`);
```

```js
// Pattern B — push the reference timestamp back
let form1FilledAt = Date.now();
const FORM1_STUCK_MS = 60000;

// ... in the captcha branch of the step loop:
const captchaT0 = Date.now();
await blockOnCaptcha(page, envId, '...');
const captchaSpent = Date.now() - captchaT0;
form1FilledAt += captchaSpent;           // pretend the form-stuck timer never ran during captcha
```

Both patterns are equivalent — the goal is "wall-clock time spent in human takeover MUST NOT count as autonomous-flow stuck time."

**Rule — whenever you introduce a long blocking-wait (`alertAndWait`, `blockOnCaptcha`, manual pause), audit every `Date.now() > X` and every `Date.now() - Y > THRESHOLD` in the calling chain.** If any of those checks gate the "stuck → retry → close browser" path, they need to be told the wait happened. Otherwise the human just spent 90s passing captcha and the automation throws away their work.

**Why the wrong hypothesis was tempting**: the visible symptom (browser closes, reopens at landing page) looks identical to "state lost on browser restart." Both can be true in the same codebase, but the "deadline burned" version is **strictly faster to repro and strictly worse** — it fires every single time the human takes more than a few seconds, regardless of whether state persistence works. Diagnostic ordering rule: **before designing a feature (state persistence) to recover from a symptom, find the kill point.** Read the log line that immediately precedes `stopEnv` / `disconnect` / `attempt X/Y` and trace what threw. In this session the log line was a clear `[flow] 登录阶段网络卡住，关掉浏览器窗口重开 (1/3)` which is exactly the STAGE_STUCK retry — pointing straight at flow.js's deadline check.

**Related**: this is the same class as the existing `captcha-alarm-renderer-ux` advice ("treat human-in-the-loop events as first-class") and `cooperative-pause-resume-control`'s pause checkpoints — anywhere the flow pauses for a human, all surrounding "is this stuck?" timers must be paused too.

---

### General pattern: button click reliability hierarchy

For React SPAs (Microsoft login, Azure forms), button click methods ranked by reliability:

1. **`page.click(selector)`** — CDP-level, calculates element center, `isTrusted: true`. Best for stable-ID buttons.
2. **`clickHuman(page, selector)`** — Custom mouse trajectory + human delays, `isTrusted: true`. Best for anti-bot scenarios requiring human-like behavior.
3. **`page.evaluate(() => el.click())`** — DOM-level click, `isTrusted: false`. **FAILS on React.** Never use as primary.
4. **`dispatchEvent(new MouseEvent('click'))`** — Same as above, `isTrusted: false`. **FAILS on React.** Only useful for non-React elements.

**Best practice for stable-ID buttons**: `page.click()` primary → `clickHuman()` fallback
**Best practice for dynamic buttons**: `clickHuman()` primary → `page.click()` fallback
