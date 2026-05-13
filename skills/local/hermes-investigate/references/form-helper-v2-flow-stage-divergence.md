# form-helper-v2 / azure-auto-reg-v3 — flow.js stage divergence + detectLoginStage races

Use this reference when investigating "C0XX stuck / never progressing" symptoms in `D:\Projects\form-helper-v2` (V3 of the Azure auto-registration bot). Common surface: UI shows `stage='start'` + `lastMsg='开始注册'` forever, or `azure_last_msg='登录卡住, 等人工: <something> 找不到 ...'`.

## DO NOT diagnose flow.js progress by reading proxies.json

`form-helper-v2` has **two parallel progress channels**, and they are NOT synchronized:

| Channel | Writer | Reaches |
|--------|--------|---------|
| `emitProgress(envId, stage, msg)` in `azure/index.js` | only called inside `runOne` outer loop + retry catch | `RUN_STATE` map → `broadcast('azure:runState')` → renderer UI; also `proxyStore.updateAzureStatus` → **proxies.json** `azure_stage` / `azure_last_msg` |
| `progress.update(envId, stage, extra)` in `azure/progress.js` | called *throughout* `azure/flow.js` (`microsoftLogin`, `runForm1Fill`, `runForm2Fill`, captcha branches…) | `logs/progress.jsonl` (append) + `logs/progress.txt` (overwrite snapshot) + `console` only |

Consequence: during the entire `microsoftLogin` state machine, `proxies.json` stays at whatever `emitProgress` last wrote (typically `stage='start', lastMsg='开始注册'` from `runOne` line ~340). The flow IS advancing internally; the UI/JSON mirror just doesn't reflect it.

Conclusion you must NOT jump to: "flow.js is stuck at `start`". It almost certainly is not. Always check `logs/progress.txt` and `logs/flow/<envId>/*.png` first.

## Correct evidence-gathering order for "C0XX 卡住"

1. **`logs/progress.txt`** — current blocking reason + recent task line. If you see `🚨 阻塞中：envId=C0XX 原因: ...`, that string IS the real current state. The substring after `登录卡住, 等人工:` is the `e.message` of the STAGE_STUCK that triggered `alertAndWait` at `azure/flow.js:1291`.
2. **`logs/flow/C0XX/*.png`** — the named screenshot in the blocking reason is the literal page state when flow.js gave up. Sort by mtime. Names like `phone-confirm-no-switch.png`, `picker-no-backup.png`, `login-stuck-<stage>.png` map 1:1 to the throw site in `flow.js`.
3. **`logs/progress.jsonl` tail** — full event sequence with timestamps. Grep `envId` to see the stage progression that proxies.json never recorded.
4. Only AFTER 1–3, look at `proxies.json` — and only for `linked_csv_serial`, `ip_id`, `last_url`. Ignore `azure_stage` / `azure_last_msg` during active login flow.

## detectLoginStage title-vs-body race

`detectLoginStage` (azure/flow.js ~line 565) classifies pages partly by `document.title`, partly by `bodySnippet`. The `phone_confirm` branch (line 668) matches on `title` alone:

```js
if (state && (/電話番号を確認|電話番号確認/.test(state.title) || /欠落している番号/.test(state.bodySnippet))) {
  return 'phone_confirm';
}
```

Microsoft login pages on slow proxies (e.g. Japan residential) frequently have the new `<title>` set *before* the central panel DOM renders. Sequence observed in `C032` evidence:

1. Microsoft redirects to phone_confirm page → `<title>電話番号を確認する</title>` set early.
2. Body still rendering — only footer (`ヘルプ` / `使用条件` / `プライバシーと Cookie`) present.
3. flow.js step loop ticks → `detectLoginStage` matches title → returns `phone_confirm`.
4. Branch (line 425) calls `switchToOtherSigninMethod` → queries `a, button, [role="link"]` → finds none in real-rendered area → returns `null`.
5. Throws `STAGE_STUCK: phone_confirm 页找不到"その他のサインイン方法"链接`.
6. Outer catch invokes `alertAndWait` — correct fallback, but the root cause is the **premature detection**, not a missing link.

Screenshot signature: `logs/flow/<envId>/*-phone-confirm-no-switch.png` shows an essentially empty central panel + only the footer links visible.

## Fix patterns

For any `detectLoginStage` branch that matches on `state.title` only, the click action should be guarded:

```js
case 'phone_confirm': {
  // Wait for body to actually render before attempting the click
  await page.waitForFunction(() => {
    const links = document.querySelectorAll('a, button, [role="link"], [role="button"]');
    return Array.from(links).some(el => {
      const t = (el.innerText || el.textContent || '').trim();
      return t.length > 0 && el.getBoundingClientRect().width > 5;
    });
  }, { timeout: 15000 }).catch(() => {});
  const ok = await switchToOtherSigninMethod(page);
  ...
}
```

Alternative (cheaper): retry the `switchToOtherSigninMethod` call 3× with 2s sleep, falling through to STAGE_STUCK only after final failure. This converts the title-vs-body race from a hard failure into a transient retry.

For the **UI-mirror gap**, the minimal patch is to bridge `progress.update` into `emitProgress`. One approach: in `azure/index.js` after `emitProgress` is defined, monkey-patch `progress.update`:

```js
const _origUpdate = progress.update;
progress.update = function(envId, stage, extra) {
  _origUpdate.call(progress, envId, stage, extra);
  try { emitProgress(envId, stage, typeof extra === 'string' ? extra : JSON.stringify(extra || '')); } catch {}
};
```

This makes the renderer + proxies.json reflect login-state progression in near-real-time. Verify with: stage on the FormHelper card should change from `start` → `login.email` → `login.password` → `login.kmsi` → ... within ~30s of a fresh run.

## Patterns to keep in mind for other "stage_X 找不到 Y" symptoms in flow.js

Same race applies to these branches in `azure/flow.js` (all `case 'X':` in `microsoftLogin`):
- `verify_method_picker` → `pickBackupEmailMethod` (line 436+)
- `confirm_backup_email` → `fillBackupEmailConfirm` (line 447+)
- `security_info_confirm` → `問題ありません` button click
- `passkey_prompt` → cancel link
- `kmsi` → `はい` blue button

All read `document.title` + bodySnippet early; all may fire before central panel DOM is ready on slow proxies. The same `waitForFunction(non-empty interactive elements present)` guard applies. The blocking-screenshot filename in `logs/flow/<envId>/` tells you which branch tripped.

## Anti-pattern to avoid

Do NOT propose "stage is stuck at start, microsoftLogin must be hanging" before reading `logs/progress.txt`. That conclusion has been wrong every time the user has reported this symptom — it is always the UI-mirror gap, with the real flow.js failure being something specific that surfaces only in the progress.txt blocking reason.
