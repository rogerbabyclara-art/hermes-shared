# Captcha + Retry Strategy Fixes (2026-05-12)

## Bug 1: Post-captcha window close

**Symptom**: Human solves captcha → clicks "接管后继续" in dashboard → runner resumes → immediately closes ADS window → reopens → may hit captcha again.

**Root cause chain**:
1. `runner_alertAndTakeover()` returns after flag detected
2. Runner does `continue` back to main detect-stage loop
3. `detectStage()` returns `form1` (captcha solved, but form not submitted)
4. Nobody clicks submit → form1 sits for 60s → `FORM1_STUCK_MS` exceeded
5. Error retry → reload → still stuck → `STAGE_STUCK` thrown
6. Catch block calls `ads.stopEnv()` → window killed

**Fix in runner.js**: After captcha alert resolves, immediately detect page state and take action:
```js
await runner_alertAndTakeover(page, envId, 'captcha', { timeoutMs: 5 * 60 * 1000 });
errorRetries = 0;

// CRITICAL: re-engage the form after captcha
await sleep(1500);
const postStage = await detectStage(result.page);
if (postStage === 'form3') return finalizeReachedPayment(...);
if (postStage === 'form1') await flow.runForm1Fill(page, profile, envId);
else if (postStage === 'form2' && !everSeenForm2) {
  everSeenForm2 = true;
  await flow.runForm2Fill(page, profile, envId);
}
form1FilledAt = Date.now();
continue;
```

## Bug 2: First login success → window killed

**Symptom**: First attempt logs in successfully → form1 loads slowly or captcha iframe takes 10-20s → 30s timeout fires → STAGE_STUCK → `stopEnv()` → window closed → attempt 2 reopens → works (cookies cached).

**Root cause**: `STAGE_STUCK` catch always called `ads.stopEnv()`, even on attempt 1. This destroyed the session including login cookies.

**Fix in runner.js**: Graduated retry strategy:
- Attempts 1-2: `browser.disconnect()` only (preserve ADS window + cookies)
- Attempts 3+: `ads.stopEnv()` (hard reset)

```js
const hardReset = attempt >= 3;
if (result) {
  try { await result.browser?.disconnect(); } catch {}
  if (hardReset) try { await ads.stopEnv(result.userId); } catch {}
}
```

## Bug 3: Captcha timeout too short (1 min)

**Symptom**: Captcha alert fires → by the time user sees popup, switches to ADS browser, solves captcha, clicks continue → already timed out (1 min) → marked as failed.

**Fix**: All captcha `alertAndWait` timeouts changed to 5 minutes:
- flow.js L250: login captcha → 5 min
- flow.js L1301: form2 captcha → 5 min  
- flow.js L1715: form1 captcha → 5 min
- runner.js L132: runner-level captcha → 5 min (via opts.timeoutMs)
- runner.js `runner_alertAndTakeover()` now accepts `opts.timeoutMs`, defaults to 1 min for non-captcha alerts

## Alert system verification

Tested all three Windows alert layers — all work on this Win11 machine:
| Layer | Mechanism | Works |
|-------|-----------|-------|
| 1 | rundll32 user32.dll,MessageBeep | ✅ |
| 2 | msg.exe popup | ✅ |
| 3 | PowerShell MessageBox (async) | ✅ |

`HERMES_TARGET` env var is NOT SET — Telegram alerts disabled. Only local sound+popup fire.

## Bug 4: Unattended captcha — no retry before fail (2026-05-12)

**Symptom**: Running overnight. CAPTCHA appears → alert fires → nobody solves it within 5 min → immediately marked `captcha_alert_timeout` → next envId starts. No attempt to reopen and retry.

**User requirement**: "I want to sleep. If captcha appears, alert me. If nobody handles it in time, close the window, reopen, try again. If captcha appears a SECOND time, THEN mark failed and move on. I'll deal with failures when I wake up."

**Root cause**: Both the runner main-loop captcha handler and the `captcha_skip` catch block did `return { status: 'failed' }` immediately on timeout. No retry.

**Fix**: Added `captchaTimeouts` counter (per-envId, persists across retry-loop attempts):

```js
let captchaTimeouts = 0;
const MAX_CAPTCHA_RETRIES = 1;

// In captcha handler (runner main loop):
try {
  await runner_alertAndTakeover(page, envId, 'captcha', { timeoutMs: 5 * 60 * 1000 });
} catch (alertErr) {
  captchaTimeouts++;
  if (captchaTimeouts <= MAX_CAPTCHA_RETRIES) {
    // Close window + reopen from scratch
    await browser?.disconnect();
    await ads.stopEnv(userId);
    await sleep(3000);
    continue; // back to top of for-loop
  }
  return { status: 'failed', reason: 'captcha_unattended_timeout' };
}

// Same pattern in catch(e) for captcha_skip from flow.js
```

**Key design choices**:
- Hard reset (stopEnv) on captcha retry — fresh browser fingerprint may avoid captcha
- Failure reason changed: `captcha_alert_timeout` → `captcha_unattended_timeout` (distinguishes attended vs unattended timeout)
- Counter is per-envId lifetime, not per-attempt — ensures max 1 reopen even if multiple stages hit captcha

## Bug 5: React radio button isTrusted (2026-05-12)

**Symptom**: `selectUsageIndividual()` returns `{ ok: true }` but the 「個人使用向け」radio visually unselected. User had to click it manually. Subsequent form fill continues but form validation fails (radio not selected in React state).

**Root cause**: Function used `page.evaluate()` with `radio.checked = true` + `dispatchEvent(new Event('change'))`. These events have `isTrusted: false`. React's synthetic event system filters out untrusted events — DOM changes but React state doesn't sync. Next render resets the radio.

**Fix**: Replaced entire function with Puppeteer real-click approach:
1. `clickHuman(page, 'label[for="..."]')` → produces `isTrusted: true` click
2. Verify `.checked` via `page.evaluate()`
3. If not checked: setter fallback + retry (up to 3 attempts)
4. Final fallback: `[role="radio"]` text match with `.click()`

**General principle**: For any React controlled form element, prefer Puppeteer CDP clicks over `page.evaluate(() => el.click())`. The latter dispatches from JS context (`isTrusted: false`), the former goes through Chrome DevTools Protocol (`isTrusted: true`).

## Bug 6: firstName polluted by phone number (2026-05-12)

**Symptom**: `firstName` verify shows `啓之81768125` instead of `啓之`. The trailing digits `81768125` are the last 8 digits of the phone number `08081768125`. Phone field itself shows correct formatted value `080 8176 8125`.

**Root cause**: Azure's phone input has React auto-formatting (inserts spaces). During formatting, keyboard events leak to the previously-active firstName field. `typeHuman` already has a blur-before-focus step, but that fires when *starting* the next field — the phone formatter fires *after* typeHuman returns for the phone field.

**Two-layer fix**:
1. **Blur isolation**: After typing into any auto-formatting field, immediately blur + wait 800-1500ms:
```js
await typeHuman(page, '#work-phone-input', profile.phoneMobile, { mode: 'safe' });
await page.evaluate(() => { document.querySelector('#work-phone-input')?.blur(); });
await sleep(randInt(800, 1500));
```

2. **Value comparison verify**: Changed from empty-check to value-match:
```js
// Before: if (!fullCheck.firstName) fixes.push('firstName');
// After:
if (!fullCheck.firstName || norm(fullCheck.firstName) !== norm(profile.firstNameKanji))
  fixes.push('firstName');
```

