# Azure Registration Flow — Real Bug Analysis (2026-05-11, updated 2026-05-12)

Project: `D:\Projects\azure-auto-reg` → fixed version: `D:\Projects\azure-auto-reg-v2`

---

## Bug 1: Login stage captcha closes window silently

**Symptom**: 邮箱登录阶段，captcha 出现后窗口直接关闭，没有报警没有弹窗。

**Root cause** (`src/flow.js` `microsoftLogin()`):
```js
// Original — bails immediately
if (captchaHit) {
  throw new Error('captcha_skip');  // runner catches → marks failed → closes window
}
```

**Fix**: Replace throw with `alertAndWait` block. Resume state machine loop after human resolves.
```js
if (captchaHit) {
  await alertAndWait({
    check: async () => !await pageHasCaptchaText(page),
    timeoutMs: 15 * 60 * 1000,
  });
  unknownSince = 0;  // reset unknown timer
  continue;          // resume loop
}
```

**Key**: After resolving, `continue` back into the for-loop. The next iteration of `detectLoginStage` will find the correct new stage.

---

## Bug 2: Form1 / Form2 captcha closes window silently

**Symptom**: FORM1 页面出现人机验证，等了约20秒，没有报警没有弹窗，直接关闭窗口。

**Root cause** (`src/flow.js` `runForm1Fill()` and `runForm2Fill()`):
```js
// Original
if (outcome === 'captcha') {
  throw new Error('captcha_skip');
}
```

**Fix**: Same `alertAndWait` pattern. After resolving:
1. Re-check if button is now enabled
2. If still on same form and button enabled → auto-click 「次へ」
3. Return `{ ok: true }` to continue flow

```js
if (outcome === 'captcha') {
  await alertAndWait({ check: async () => { /* btn enabled OR onForm2 */ } });
  // post-resolve: auto-click if button now enabled
  const post = await page.evaluate(() => ({
    btnDisabled: document.querySelector('#accept-terms-submit-button')?.disabled,
    onForm2: /ステップ\s*2/.test(document.body.innerText),
  }));
  if (!post.onForm2 && !post.btnDisabled) {
    await clickHuman(page, '#accept-terms-submit-button');
  }
  return { ok: true, btnReady: true };
}
```

**Also**: `runner.js` had its own `detectStage()` captcha check that also killed the task. Fixed runner's check to also `alertAndWait` instead of `return failed`.

---

## Bug 3: 都道府県 dropdown 「京都」no_match

**Symptom**: form2 填写失败: 都道府県下拉里找不到「京都」: `{"error":"no_match","total":96,"sample":["--選択--","--選択--","北海道",...]}`

**Root cause** (`src/flow.js` `selectPrefectureDropdown()`):
```js
// Original — strict equality
const hit = items.find(el => el.innerText.trim() === target);
// "京都" !== "京都府" → no match
```

**Why 96 items for 47 prefectures**: pidl renders each option twice in the DOM (likely for animation/transition). Fuzzy match still picks the first hit correctly.

**Fix**: Two-level match:
```js
// Level 1: exact match (keeps correctness for unambiguous names)
let hit = items.find(el => el.innerText.trim() === target);
// Level 2: substring match in either direction
if (!hit) {
  hit = items.find(el => {
    const t = el.innerText.trim();
    return t.length > 0 && (t.includes(target) || target.includes(t));
  });
}
// Debug: on no_match, log ALL option texts (not just sample 5)
if (!hit) return { error: 'no_match', total: items.length, all: allTexts };
```

**Coverage**:
- Profile `「京都」` → matches dropdown `「京都府」` ✓
- Profile `「大阪」` → matches `「大阪府」` ✓  
- Profile `「東京」` → matches `「東京都」` ✓
- Profile `「北海道」` → exact match ✓
- Profile `「神奈川県」` → exact match ✓

---

## Bug 3b: FORM2 邮箱输入后关窗

**Symptom**: 第三次登录到了FORM2，刚输了邮箱，又关闭窗口了。

**Actual cause**: This was NOT form2's email field. It was `confirm_backup_email` in the login state machine — filling the backup email then waiting for `waitForStageChange` which timed out (→ `STAGE_STUCK` → close). Fixed by Bug 1's `alertAndWait` pattern covering the login state machine.

If this recurs specifically in form2: check `runForm2Fill`'s 30-second post-fill wait for button to enable. If captcha appears during that wait, Bug 2's fix now handles it.

---

## Bug 4: Post-captcha runner doesn't re-engage form → closes window (2026-05-12)

**Symptom**: Human solves captcha in ADS browser → clicks "接管后继续" in dashboard/FormHelper → runner acknowledges the flag → but instead of continuing the registration flow, the window closes and the env restarts from scratch (or fails with STAGE_STUCK).

**Root cause** (`src/runner.js` captcha handler in main loop):
```js
// Original — just continues the detect loop without acting
if (stage === 'captcha') {
  await runner_alertAndTakeover(page, envId, 'captcha');
  errorRetries = 0;
  form1FilledAt = Date.now();
  continue;  // ← goes back to detectStage loop without re-engaging
}
```

After `alertAndWait` returns:
1. Runner `continue`s to next iteration of detect loop
2. `detectStage()` returns `form1` (captcha solved, back on form1)
3. No one clicks 「次へ」submit button
4. 60 seconds pass → FORM1_STUCK triggers reload + retry
5. Retry fills form again but may hit captcha again → escalating risk loop
6. After MAX_STUCK_RETRIES → STAGE_STUCK → window closes

**Fix**: After captcha alert resolves, immediately detect post-captcha stage and take action:
```js
await runner_alertAndTakeover(page, envId, 'captcha', { timeoutMs: 5 * 60 * 1000 });
errorRetries = 0;

// Post-captcha: re-detect stage and re-engage
await sleep(1500);
const postStage = await detectStage(page);
if (postStage === 'form3') return finalizeReachedPayment(page, envId, t0);
if (postStage === 'form1') {
  await flow.runForm1Fill(page, profile, envId);  // re-fills AND clicks submit
} else if (postStage === 'form2' && !everSeenForm2) {
  everSeenForm2 = true;
  await flow.runForm2Fill(page, profile, envId);
}
form1FilledAt = Date.now();
continue;
```

**Also fixed**: `runner_alertAndTakeover` timeout was hardcoded 1 minute for all cases. Captcha needs longer (5 min) since human must: notice popup → switch to ADS browser → solve captcha → click continue in dashboard. Changed to accept `opts.timeoutMs` parameter.

**Compound risk**: Each unnecessary window-close + reopen cycle increases Azure's anti-fraud score for that environment. The original bug could trigger 3-5 restarts per captcha event, severely raising risk of account block.

---

## Bug 5: "Already registered" env shows unexpected page → detached Frame error

**Symptom**: P495 already successfully registered Azure. Re-running it opens the Azure portal (not registration flow) → runner encounters unexpected page → Puppeteer frame gets detached → `Attempted to use detached Frame` error.

**Root cause**: No "already registered" detection. The runner assumes every env will show the registration flow.

**Workaround**: Manual mark-success in FormHelper or via runtime.json edit:
```js
const r = rt.results.find(x => x.envId === 'P495');
r.status = 'reached_payment';
r.reason = 'manual_mark_already_registered';
```

**Future fix**: Add detection in `detectStage()` for Azure portal/dashboard pages (post-registration). If detected, return `'already_done'` stage and auto-mark success.

---

## Lessons

1. **Any captcha detection = alertAndWait, never bail**. The whole point of fingerprint browsers is to get a human in if needed.
2. **`captcha_skip` should be the last resort** (after 15min timeout), not the first response.
3. **Fuzzy dropdown matching**: profile data and page option text rarely match exactly (suffix 府/県/都/道 differences).
4. **Log ALL option texts on no_match** — `sample: items.slice(0,5)` is useless when the real item is #40.
5. **SPA form captcha**: always wait 20-30s before deciding outcome — Azure's Arkose captcha iframe can take 15s to load.
6. **Post-alert flow resumption is critical**: After any human intervention (captcha, takeover), the runner MUST re-detect the page state and re-engage the form. A bare `continue` back to the detect loop is insufficient because no one will click the submit button.
7. **Timeout should match the intervention type**: Captcha (5 min) > error page recovery (1 min). One size does not fit all.
8. **Window restarts compound risk**: Each unnecessary close/reopen cycle raises anti-fraud scores. Bugs that cause multiple restarts per task are especially dangerous.
