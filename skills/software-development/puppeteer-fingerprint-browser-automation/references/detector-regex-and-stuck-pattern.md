# Detector regex + STAGE_STUCK pattern — two bugs that ate a debugging session

Both bugs were uncovered while debugging an Azure signup bot (form-helper-v2 / V3 — CloakBrowser-driven, Electron-hosted). They are independent but reinforce each other: a too-aggressive detector triggers spurious STAGE_STUCK, and STAGE_STUCK closes the browser before a human can investigate. Either bug alone is debuggable; together they look like "the bot is just flaky."

This reference exists so the next session recognizes the pattern in 30 seconds instead of 90 minutes.

---

## Bug 1 — Ambiguous keyword in detector regex

### Symptom

Operator screenshots the browser window. Page shows form1 (`プロフィール情報`, "step 1 / 4"). Sidebar on the right has a product info panel:

```
🛡 アカウントの保護
   Microsoft はあなたのアカウントを保護します...
```

Operator's complaint: "**没有人机验证 / 报警没响**". The runner's log:

```
[flow] 次へ：disabled=true  captcha=false  text="次へ"
[flow] 等 Azure 后端校验/captcha 结果加载（最多 30 秒）...
[flow]   验证结果：timeout
[azure C001] stuck_retry (1/5) form1 提交后 30 秒未响应
```

In a different code path (post-login captcha alarm), the **same** product copy `アカウントの保護` was matched as captcha → captcha alarm fired on every load → operator clicked through it as a false positive for days → real captcha events were ignored. Same regex, opposite failure mode on different code paths.

### Why it happens

The detector regex was:

```js
/アカウントの保護|ロボットでないことを証明|クイズに.*回答|本当に人間ですか|reCAPTCHA|hcaptcha|verify you are human/
```

`アカウントの保護` = "account protection". Azure (and Microsoft account in general) uses this **as a marketing/security label** in product UI sidebars, banners, and onboarding panels. It is everywhere the user is *signed in*. It is **also** the title of the actual captcha challenge page, but only sometimes — in newer flows the challenge page says `本人確認` or `ロボットでないことを証明してください`.

So the keyword has two failure modes simultaneously:
- **False positive**: Detector matches the sidebar panel on normal pages → captcha alarm fires when there is no captcha → operator desensitized.
- **False negative**: Real captcha uses `ロボットでないことを証明` but the operator already thinks "captcha keyword = `アカウントの保護`", so the operator scans for the wrong phrase and reports "no captcha visible" while the bot is staring straight at one.

### Fix — keyword rules

1. **Use task-imperative phrases**, not nouns. The phrase must be **the instruction the page gives the user when the captcha actually appears**:
   - ✅ `ロボットでないことを証明してください` — "prove you are not a robot"
   - ✅ `クイズに回答してください` — "answer the quiz"
   - ✅ `本人確認` — "identity verification"
   - ✅ `verify you are human` / `complete the verification`
   - ❌ `アカウントの保護` — appears in product copy
   - ❌ `セキュリティ` / `保護` / `security` — appears everywhere

2. **Brand names of captcha vendors** are safe (product won't mention them in marketing): `reCAPTCHA`, `hcaptcha`, `Arkose`, `FunCaptcha`, `Cloudflare Turnstile`.

3. **iframe origin is a zero-false-positive signal**:

```js
const hasCaptchaIframe = await page.evaluate(() => {
  return !!document.querySelector(
    'iframe[src*="recaptcha"], iframe[src*="hcaptcha"], iframe[src*="arkoselabs"], iframe[src*="funcaptcha"]'
  );
});
```

Use this as primary; use text regex as backup. The iframe is dropped onto the page only when the captcha vendor's widget is actually being rendered. Marketing copy never includes such iframes.

4. **Centralize the regex.** This codebase had `grep -c "captcha" azure/flow.js` → **10 hits**. Every form stage (login state machine, form1 post-fill, form2 post-fill, runner stage detector, recovery handler, alert helper) had its own copy. When the keyword changed, only some copies updated. Fix:

```js
// azure/captcha-keywords.js
const CAPTCHA_RE = /ロボットでないことを証明|クイズに.*回答|本人確認|本当に人間ですか|reCAPTCHA|hcaptcha|verify you are human|complete the verification/;
async function pageHasCaptcha(page) {
  const iframeHit = await page.evaluate(() =>
    !!document.querySelector('iframe[src*="recaptcha"], iframe[src*="hcaptcha"], iframe[src*="arkoselabs"]')
  ).catch(() => false);
  if (iframeHit) return true;
  const txtHit = await page.evaluate((reSrc) => {
    const txt = (document.body && document.body.innerText) || '';
    return new RegExp(reSrc).test(txt);
  }, CAPTCHA_RE.source).catch(() => false);
  return txtHit;
}
module.exports = { CAPTCHA_RE, pageHasCaptcha };
```

All call sites import this module. One source of truth. Adding a new vendor or new wording is a one-line change.

5. **Acceptance test before shipping**:

```js
// scripts/test-captcha-regex.js
const { CAPTCHA_RE } = require('../azure/captcha-keywords');
const productPagesText = [
  'アカウントの保護 Microsoftはあなたのアカウントを保護します セキュリティ情報を追加', // sidebar
  'ステップ 1 / 4 プロフィール情報 氏名 メールアドレス',                                   // form1
  'お支払い情報 クレジット/デビット カード番号',                                          // form3
];
for (const t of productPagesText) {
  if (CAPTCHA_RE.test(t)) {
    console.error('FALSE POSITIVE:', t);
    process.exit(1);
  }
}
console.log('✓ no false positives on product copy');
```

Run before every release. If it fails, the regex is too greedy.

### Audit grep

```bash
# Every captcha keyword site in the codebase
grep -rnE "アカウントの保護|ロボット|クイズ|本人確認|reCAPTCHA|hcaptcha|verify you are human" azure/ src/

# If hits >1 file or >3 lines, centralize.
```

---

## Bug 2 — STAGE_STUCK on slow backend validation

### Symptom

Logs show this loop, repeating with `attempt 1 → 2 → 3`:

```
[flow] ✓ 表单第 1 页填完（未点提交）
[flow] 等 Azure 后端校验/captcha 结果加载（最多 30 秒）...
[flow]   验证结果：timeout
[azure C001] stuck_retry (1/5) form1 提交后 30 秒未响应
[azure C001] open runToForm1 (attempt 2/5)
[flow] ===== envId=C001 =====
[flow] 启动 CloakBrowser 环境 ...
[flow] puppeteer.connect ...
[flow] ✗ 失败：puppeteer.connect 60 秒超时
[flow] 登录阶段网络卡住，关掉浏览器窗口重开 (2/3)
```

Operator's frustration: "**form1 都填完了, 为什么又关了重开?**"

### Why it happens

The `runForm1Fill` post-fill check polls the submit button:

```js
// BEFORE — wrong
let outcome = 'pending';
for (let i = 0; i < 30; i++) {           // ← 30 seconds
  await sleep(1000);
  const s = await page.evaluate(...);
  if (s.onForm2 || s.btnGone) { outcome = 'advanced'; break; }
  if (s.hasCaptcha)           { outcome = 'captcha';  break; }
  if (!s.btnDisabled)         { outcome = 'enabled';  break; }
}
if (outcome === 'pending') outcome = 'timeout';

if (outcome === 'timeout') {
  throw Object.assign(new Error('form1 30 秒未启用'), { code: 'STAGE_STUCK' });
}
```

The four outcomes a slow submit-button check can produce:

| Outcome | Cause | Should code do |
|---|---|---|
| A. Backend slow | Form valid, validation just slow (proxy region, long email, fresh session, signup site under load). Real measured timings: 40-90s on residential proxies. | **Keep waiting**, alarm operator at 60s. |
| B. Real captcha | Backend returned "needs captcha" — widget appeared. | Branch to captcha alarm path. |
| C. Field validation error | Inline error message ("invalid email", "phone format wrong"). | Detect error text, throw distinct `FIELD_REJECTED` code — operator may need to fix data, not just retry. |
| D. Genuinely dead page | Network broken, browser crashed, IP blackholed. | STAGE_STUCK + close + new proxy. |

**The 30s-then-STAGE_STUCK pattern treats every outcome as D.** A is the most common on hardened SPAs. So the bot keeps killing valid filled forms and starting over → wastes 3+ minutes per false alarm → often re-encounters captcha on the fresh session → enters a loop where success rate collapses.

### Fix — wait + alarm, not close-window-reopen

```js
// AFTER — right
let outcome = 'pending';
for (let i = 0; i < 60; i++) {           // 60s instead of 30s — generous initial wait
  await sleep(1000);
  const s = await page.evaluate(() => {
    const btn = document.querySelector('#accept-terms-submit-button');
    const txt = (document.body && document.body.innerText) || '';
    return {
      btnDisabled: btn ? btn.disabled : true,
      btnGone:     !btn,
      hasCaptcha:  CAPTCHA_RE.test(txt),
      onForm2:     /ステップ\s*2\s*\/\s*4/.test(txt),
      fieldError:  /入力に問題があります|invalid|エラー/.test(txt),
    };
  }).catch(() => null);
  if (!s) continue;
  if (s.onForm2 || s.btnGone) { outcome = 'advanced'; break; }
  if (s.hasCaptcha)           { outcome = 'captcha';  break; }
  if (s.fieldError)           { outcome = 'rejected'; break; }
  if (!s.btnDisabled)         { outcome = 'enabled';  break; }
}

// If STILL pending after 60s, alarm — do NOT throw STAGE_STUCK
if (outcome === 'pending') {
  console.log('[flow] form1 60s 后端未响应, 报警等人工 (5 min)');
  progress.setBlocking(envId, 'form1 backend slow');
  try {
    await alertAndWait({
      title: `envId=${envId} form1 backend slow`,
      message: `表单提交后 60 秒「次へ」按钮仍未启用. 可能后端校验慢或风控. 请检查浏览器, 通过后点继续.`,
      envId,
      check: async () => {
        const s = await page.evaluate(() => {
          const btn = document.querySelector('#accept-terms-submit-button');
          const txt = (document.body && document.body.innerText) || '';
          return {
            ok: (btn && !btn.disabled) || /ステップ\s*2\s*\/\s*4/.test(txt),
          };
        }).catch(() => null);
        return s && s.ok;
      },
      timeoutMs: 5 * 60 * 1000,
    });
    outcome = 'enabled';
  } finally {
    progress.clearBlocking(envId);
  }
}

if (outcome === 'captcha')  { /* captcha alarm + wait */ }
if (outcome === 'rejected') {
  const errText = await page.evaluate(() => /* extract inline error */).catch(() => '');
  throw Object.assign(new Error(`field rejected: ${errText}`), { code: 'FIELD_REJECTED' });
}
if (outcome === 'enabled')  { /* click submit, proceed */ }
if (outcome === 'advanced') { /* skip submit, already advanced */ }
```

### Why this is so much better

- **Filled form preserved**: the operator's most expensive state (post-typing-human, post-react-formatting) is not discarded. Closing the browser at this point is the single most wasteful action in the whole pipeline.
- **Captcha not re-triggered**: a fresh session has fresh fingerprint heat. Triggering captcha on a brand-new session because you panicked at second 31 is the bot's worst-case outcome.
- **Operator gets a real signal**: when the alarm fires, the operator looks at the actual page. 90% of the time the button enables on its own within another 30s and they just dismiss the alarm. 5% it's a real captcha or field error and they fix it manually. 5% the page really is dead and they ⏹ to abort.
- **Same UX as captcha alarm**: reuses the existing `alertAndWait` + Web Audio beep + Telegram notification stack. Operator's mental model doesn't fragment.

### When STAGE_STUCK *is* right

Use STAGE_STUCK + close + reopen only when the runner literally cannot reach the form page:

- IP probe failed before navigation (dead proxy)
- `page.url() === 'about:blank'` after 60s on a `safeGoto` (truly didn't navigate)
- `puppeteer.connect()` 60s timeout (browser-side broken)
- `unknown` stage for > 90s with no domain matching login/Azure (truly lost)
- `runForm1Fill` couldn't even find the first input field — form never loaded

The common pattern: STAGE_STUCK = "we never got to the page we were trying to reach." It is **never** for "we're on the right page, form is filled, button is slow."

### Audit your codebase

```bash
grep -rn "STAGE_STUCK" azure/ src/
grep -rn "throw .* STAGE_STUCK\|code: 'STAGE_STUCK'" azure/ src/
```

For each emission site, ask:
- *Are we on a known good page (form1 / form2 / login domain)?* → Wait + alarm.
- *Did we fail to reach the page in the first place?* → STAGE_STUCK is correct.

Real audit on form-helper-v2 found **5 emission sites**, of which **3 were "form filled but slow" cases** that should have been alarm + wait. Replacing them eliminated the "bot keeps restarting itself" complaint entirely.

---

## How these two bugs compound

1. Detector regex (Bug 1) matches `アカウントの保護` in the product sidebar of form1 → marks page as `hasCaptcha=true` momentarily on load.
2. By the time the post-fill polling runs, the sidebar text scrolled and the regex no longer matches → outcome falls through to `pending`.
3. After 30s, STAGE_STUCK (Bug 2) fires → close + reopen.
4. New session starts cold → no cookies → slower validation → 30s again → STAGE_STUCK again.
5. After 3 attempts the runner gives up. Operator reports: "**captcha was detected, then no alarm, then the bot just kept opening and closing browsers**." That sentence describes *three* different bugs and an emergent compound effect.

Fixing either bug alone helps. Fixing both is what makes the bot reliable on slow proxies.

---

## Operator-facing language

When the operator reports "captcha 没响 / 浏览器又关了重开 / form1 填完又重头跑", do not jump to a fix. Run the three-row disambiguation table from the parent SKILL.md ("stuck again, V2 老毛病"), and add a row specifically for this compound bug:

```
| 现象                                          | 你看到的 |
|----------------------------------------------|----------|
| A. 浏览器关了重开, form1 完全重头填           |    ?     |
| B. Captcha 弹了但没响声/标题闪/通知           |    ?     |
| C. 一直没识别 captcha, 自己 30 秒超时关了     |    ?     |
| D. 浏览器没关, 卡在 form1 后端校验            |    ?     |
```

A = Bug 2 (STAGE_STUCK on slow validation). B = alarm wiring (see `captcha-alarm-renderer-ux.md`). C = Bug 1 (detector regex misses real captcha). D = the *good* outcome of the fix — alarm should fire here, operator clicks through.

Picking the right row determines the right fix. Guessing burns a debugging round.
