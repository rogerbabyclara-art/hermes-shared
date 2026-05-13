# puppeteer.connect 重试 + slow-validation vs stuck 判别

两条踩坑级经验，跨项目通用。出自 Azure 自动注册 V3 (form-helper-v2 / CloakBrowser) 但模式适用于所有指纹浏览器 (ADS / MoreLogin / AdsPower / CloakBrowser / Multilogin)。

---

## 1. puppeteer.connect 必须重试,不能一次性超时

### 现象
指纹浏览器 `startEnv()` 返回 ws / browserURL 后立刻 `puppeteer.connect()`,大概率挂住或秒返但拿到的 browser 不可用。60 秒一次性超时 → 抛 STAGE_STUCK → 上层杀浏览器重开 → 进 attempt 死循环。

### 根因
指纹浏览器的 Chromium 启动后:
- CDP 端口虽然秒开,但 **extension manifest 加载 / 反指纹注入脚本 / 首屏 JS** 完成要 10-60 秒
- 没 ready 时连进去要么挂住,要么拿到不完整的 browser 实例(后续 `browser.pages()` / `newPage()` 会报莫名错)
- CloakBrowser 偶发还要等 anti-detect 扩展握手

### 正确做法
**3 次重试 × 90 秒,间隔 3 秒**,总上限 4.5 分钟,仍失败才 STAGE_STUCK:

```js
let browser = null;
let lastErr = null;
for (let attempt = 1; attempt <= 3; attempt++) {
  console.log(`[flow]   connect attempt ${attempt}/3 (90s timeout)`);
  try {
    browser = await Promise.race([
      puppeteer.connect(connectOpts),
      new Promise((_, reject) => setTimeout(() => reject(
        new Error(`puppeteer.connect 90 秒超时 (attempt ${attempt}/3)`)
      ), 90000)),
    ]);
    break;
  } catch (e) {
    lastErr = e;
    if (attempt < 3) await sleep(3000); // 让 CDP server 喘口气
  }
}
if (!browser) {
  throw Object.assign(
    new Error(`puppeteer.connect 重试 3 次仍失败: ${lastErr?.message}`),
    { code: 'STAGE_STUCK' }
  );
}
```

### 反模式
- `puppeteer.connect()` 不加 timeout → puppeteer 自己没内置 timeout,真挂住时永远不返回
- 单次 60 秒 timeout → 太短,且失败后没重试机会
- 失败后立刻 `closeEnv` 重开 → CDP 还没 ready 你就杀了它,下次更慢

---

## 2. "按钮 30 秒没启用" ≠ stuck,要区分 stuck 和 slow-validation

### 现象
SPA 表单(Azure / Google / Microsoft)填完字段后,提交按钮 disable → 后端校验 → enable。
代码循环等 30 秒按钮 enable,超时直接 STAGE_STUCK 关浏览器。但其实:
- 后端校验真的会慢 30+ 秒(尤其首次注册 / 风控严格的号)
- 或者 captcha 弹出来了,按钮永远不会自动 enable,要人通过

杀浏览器重开 = 之前填的全丢,死循环。

### 正确做法:三态判别

| 状态 | 判别 | 处理 |
|---|---|---|
| advanced | 已到下一页(URL 变 / 下页特征文本出现) | 流程继续 |
| btnEnable | 按钮 enable 了 | 自动点 |
| timeout | 30 秒还没动静 | **不是 stuck**,转报警等人工 5 分钟 |

`outcome === 'timeout'` 不抛 STAGE_STUCK,改 `alertAndWait`:

```js
if (outcome === 'timeout') {
  console.log('[flow] form1 30 秒后端校验未启用「次へ」, 报警等人工接管');
  const fp = await shot(page, envId, 'form1-slow-validation');
  progress.setBlocking(envId, 'form1 后端校验慢');
  try {
    await alertAndWait({
      title: `envId=${envId} form1 captcha 或后端校验慢`,
      message: `表单第 1 页等了 30 秒「次へ」按钮还没启用. 可能 (a) 后端校验慢 (b) 真出现 captcha. 请检查浏览器, 通过验证或手动点「次へ」后回 UI 点继续.\n截图: ${fp}`,
      envId,
      check: async () => {
        const s = await page.evaluate(() => {
          const btn = document.querySelector('#submit-btn-id');
          const txt = (document.body && document.body.innerText) || '';
          return {
            btnGone: !btn,
            btnEnabled: btn ? !btn.disabled : false,
            onNextPage: /下一页特征文本/s.test(txt),
          };
        }).catch(() => null);
        if (!s) return false;
        return s.onNextPage || s.btnGone || s.btnEnabled;
      },
      timeoutMs: 5 * 60 * 1000,
    });
    progress.clearBlocking();
  } catch (e) {
    progress.clearBlocking();
    // 5 分钟还没解才真 stuck
    throw Object.assign(new Error('form1 等了 5 分钟仍未响应, 真卡死'), { code: 'STAGE_STUCK' });
  }
}
```

### 关键设计
- **check() 三选一**: 下页 / 按钮消失 / 按钮 enable,任一都算解开 — 因为人工可能直接手点过去了
- **progress.setBlocking / clearBlocking**: UI 状态栏黄色暂停指示,人工才知道要去看
- **5 分钟超时**: 比单次 30 秒宽松 10 倍,真死了才升级 STUCK

---

## 3. captcha 关键词不能含登录页卖点文字

抽 helper 时容易把 `アカウントの保護` / `Protect your account` 当 captcha 信号 — 但这些**也是登录主页的卖点 panel 文字**,会误报。

### 安全词(确凿是 captcha)
```
ロボット | クイズに.*回答 | 本人確認 | 本当に人間ですか |
reCAPTCHA | hcaptcha | verify you are human | are you human
```

### 危险词(歧义,不要用)
- `アカウントの保護` / `Protect your account` — Microsoft 登录主页 panel
- `ロボットでないことを証明` 单独用 — 太泛,触发率高于实际 captcha 出现率

### 检测 helper 形状
独立模块 `captcha-detect.js`,导出:
- `CAPTCHA_HIT_RE` / `CAPTCHA_PASS_RE`(正则常量)
- `isCaptchaText(txt)` / `isCaptchaPassedText(txt)`(给字符串用)
- `pageHasCaptcha(page)` / `pageCaptchaPassed(page)`(包了 `page.evaluate`,正则.source 传进沙箱)

注意 `page.evaluate` 沙箱里 **不能 require 模块**,正则要内联或作为参数传进去。

---

## 4. 登录状态机:URL 早退兜底,别死等 DOM 特征

### 现象
Microsoft / Google / Azure 登录跑完凭据后,会有一个**纯 loading dots 的过渡页**(身份层已成功,等下一跳目标 SPA 渲染)。这时候:
- DOM body 几乎空,只有几个加载点
- `detectLoginStage(page)` 抓不到任何特征文字 → 返 `unknown`
- 状态机循环计 unknown,撑到全局 timeout (120s) → STAGE_STUCK → 杀浏览器
- 下个 attempt 浏览器恢复时 cookie 还在,**目标页其实已经成功打开**,但代码线程早死,没人接管填表

### 关键诊断信号
出问题时看 `login-global-timeout.png`:
- 顶部 header 已经显示登录的邮箱 + "サインアウト" / "Sign out" → 身份层已成功
- 主体区只有 loading dots / 空白 → 卡在"下一跳渲染"
- URL 已经离开 `login.live.com` / `login.microsoftonline.com` 进入 `signup.*.com` / `portal.*.com`

### 修法:URL 早退
在状态机循环里,**先判 URL,再判 stage**。URL 进入下游域 = 登录视为完成,直接 return,不等 stage 文本:

```js
const stage = await detectLoginStage(page);
console.log(`step=${step} stage=${stage}`);

// ★ URL 早退: URL 已离开登录域进入下游 SPA,登录视为完成
const curUrl = page.url();
if (/signup\.azure\.com|portal\.azure\.com/.test(curUrl)
    && !/login\.(live|microsoftonline)\.com/.test(curUrl)) {
  console.log(`✓ URL 已到下游 (${curUrl.slice(0,80)}), 登录完成, 早退`);
  progress.update(envId, 'login.done_by_url', `url=${curUrl.slice(0,60)}`);
  return;  // 退出登录状态机,让后续阶段接管
}
```

### 泛化原则
任何"按文本/DOM 特征做 stage 判别"的状态机,都要加 **URL 早退兜底**:
- stage 文本检测靠的是页面渲染完成,过渡页/空白页就废了
- URL 是 Chromium 层的事实,不依赖 DOM 渲染
- 同样适用于 Google OAuth、Stripe Checkout、Shopify 登录后跳商户域 等多跳 SPA

### 反模式
- "全局 timeout = 死了" → 不对,可能只是渲染慢但身份层已经成功
- "stage = unknown 等够 N 次就 stuck" → 加 URL 兜底,unknown 但 URL 已下游就是成功
- 杀浏览器重开"试试看" → cookie 还在的话其实早就成功了,杀浏览器纯属浪费

---

## 5. 整体哲学:STAGE_STUCK 是大杀器,不要随便用

只在以下情况才 STUCK + 关浏览器重开:
1. CDP server 多次连不上(已重试 3×90s)
2. 人工接管报警超时(5 分钟没人响应)
3. 页面 crash / Target closed / Protocol error

**不该 STUCK 的:**
- 按钮等待超时 → 转 alertAndWait
- 单次网络请求慢 → 重试
- 找不到元素 → 截图 + 报警让人确认页面状态
- captcha 出现 → 报警等人工

STAGE_STUCK 应该是"代码层确认环境真坏了"的最后手段,不是"等不耐烦了"的逃避。

---

## 6. 外层 retry 别杀浏览器 — 把人工接管提升到全流程级

§2 讲了**步骤级**(form1/form2 内部的 30s timeout 改 alertAndWait),§4 讲了 stage 检测的 URL 早退。这一条是更彻底的:**整个外层 try/catch 都不要走"杀浏览器重开新 attempt"**。

### 现象 (用户原话: "邮箱保持状态页面选完基本必掉")

KMSI / passkey 引导 / 安全信息确认 这些"用户已经在浏览器里点过一次"的页面,如果代码后续 detect 不到下一阶段:
1. detectLoginStage 一直返 unknown → 撑到 60s → 抛 STAGE_STUCK
2. 外层 catch 看到 STAGE_STUCK + attempt < MAX → `ads.stopEnv(userId)` **杀浏览器**
3. attempt 2 起新浏览器 → cookies 在但 KMSI 状态丢了 → 又卡 → 又杀 → 死循环

**用户的所有手动点击全部白干**。表面是"必掉",实质是"代码自己在杀自己的成果"。

### 反模式 (要根除)

```js
// ❌ 这套是 §1/§2/§4 的所有努力都白费的元凶
for (let attempt = 1; attempt <= MAX_RETRIES; attempt++) {
  try {
    return await runFlow(...);
  } catch (e) {
    if (e.code === 'STAGE_STUCK' && attempt < MAX_RETRIES) {
      await ads.stopEnv(userId);  // ← 杀手在这里
      await sleep(3000);
      continue; // 起新浏览器
    }
    throw e;
  }
}
```

### 正确做法:外层 catch 也走 alertAndWait,浏览器**永远不杀**

```js
} catch (e) {
  const fp = page ? await shot(page, envId, 'fail') : null;

  // captcha_skip / puppeteer.connect 失败 (page/browser 为 null) 这两种走 fail
  if (e.code === 'STAGE_STUCK' && page && browser && e.message !== 'captcha_skip') {
    progress.setBlocking(envId, `登录卡住, 等人工: ${e.message.slice(0, 60)}`);
    try {
      await alertAndWait({
        title: `envId=${envId} 登录卡住, 请手动接管`,
        message: `自动登录在 [${e.message.slice(0, 80)}] 卡住. 请在浏览器里手动操作到目标页, 然后回 UI 点继续.\n截图: ${fp}`,
        envId,
        check: async () => {
          // URL 已到下游 = 成功
          const url = page.url();
          if (/signup\.azure|portal\.azure/.test(url) && !/login\.(live|microsoftonline)/.test(url)) return true;
          // DOM 兜底: 下一阶段特征文本出现
          return await page.evaluate(() => {
            const txt = (document.body && document.body.innerText) || '';
            return /ステップ\s*1\s*\/\s*4|プロファイル|会社名/.test(txt);
          }).catch(() => false);
        },
        timeoutMs: 10 * 60 * 1000, // 10 分钟够人慢慢搞
      });
      progress.clearBlocking();

      // 人工搞定 → 看当前 URL 决定下一步
      const curUrl = page.url();
      if (/signup\.azure|portal\.azure/.test(curUrl)) {
        // 直接成功,跳过外层 attempt
        return { ok: true, stage: 'STAGE_FORM1_REACHED', browser, page, userId };
      }
      // 还在登录域 (人工只过了 captcha 但没等到跳转) → 重进状态机, 不杀浏览器
      try {
        await microsoftLogin(page, profile, envId);
        return { ok: true, stage: 'STAGE_FORM1_REACHED', browser, page, userId };
      } catch (e2) {
        // 二次卡住,**仍然不杀浏览器**,走 fail 但 keepOpen=true
        return { ok: false, stage: 'failed', reason: e2.message, browser, page, userId };
      }
    } catch (waitErr) {
      // 用户主动取消等待 → 不重试,不杀浏览器
      progress.clearBlocking();
      return { ok: false, stage: 'failed', reason: `用户取消接管: ${waitErr.message}`, browser, page, userId };
    }
  }

  // 非 STAGE_STUCK 或拿不到 page/browser → 老兜底, 但 keepOpen 时**绝不** stopEnv
  if (!keepOpen) {
    try { await browser?.disconnect(); } catch {}
    try { await ads.stopEnv(userId); } catch {}
  }
  return { ok: false, stage: 'failed', reason: e.message, screenshotPath: fp, browser, page, userId };
}
```

### 关键设计点

1. **`keepOpen` 缺省 true**: 注册流程的默认期待是"出错也保留浏览器让人接手",`stopEnv` 只在显式 `keepOpen=false` 时调用
2. **alertAndWait 通过条件 = URL 下游 ‖ DOM 特征**: 两条路任一满足就放行,跟 §2 的 check() 三选一同样思路
3. **二次卡住也不杀**: 人工接管后又卡了,直接走 fail (返还 browser/page 给上层),让用户决定要不要手动点 ✅ 标成功 / 重启浏览器
4. **`progress.setBlocking` 必配**: 状态栏黄色暂停 + UI 浮出「继续」按钮,人工才知道要去看浏览器

### 心智模型转变

**老思路**:"代码自动跑,卡住就重试,重试不行就放弃" — 像 CI/CD 的失败重试。
**新思路**:"代码尽力跑,卡住就让人接,人接完代码继续" — 像 IDE 的断点 + 单步。

适用范围: **任何成本高(花钱注册账号 / 长流程多次点击 / 短信验证码消耗)** 的自动化都该用后者。重试便宜的场景(纯 HTTP 抓取)再用前者。

### 防回归 checklist

修完后 grep 一遍源码:

```bash
# 不应该再出现的模式: catch 块里 stopEnv + sleep + continue
grep -rn "stopEnv.*\n.*sleep.*\n.*continue" --include="*.js"

# 应该出现的模式: catch 块里 alertAndWait + 不调 stopEnv
grep -rn "STAGE_STUCK.*alertAndWait\|alertAndWait.*STAGE_STUCK" --include="*.js"
```

如果还有 `ads.stopEnv(userId)` 在 catch 路径里非显式 keepOpen=false 触发,就是回归了。

---

## 7. UI 文本匹配的 i18n 陷阱 — locale 一变就杀流程

### 现象 (Azure V3 zh-CN 案例)

`switchToOtherSigninMethod` / `pickBackupEmailMethod` 这种"按文本找按钮再点"的 helper,正则只覆盖了 JP + EN:

```js
return /その他のサインイン方法|別のサインイン方法|Use a different|Sign in another way/.test(t);
```

用户浏览器 locale 是 zh-CN,Microsoft 登录页渲染成"其他登录方法" / "向 xxx 发送代码" → 正则无匹配 → helper 返 false → `case 'phone_confirm'` 直接抛 STAGE_STUCK → 流程死。

**这跟"代码 bug"是两回事,locale 切换不应该让流程崩**。但单纯补一种语言治标不治本,下次微软 A/B 改文案、加 zh-TW、上 ko-KR 一样炸。

### 治标:覆盖所有目标 locale

任何"按 UI 文本找元素"的正则,必须列全:

- **JP**: 日文汉字 + 平假名两套(如「方法」可能写作「方法」也可能整词换成「やり方」)
- **EN**: 大小写不敏感,覆盖 "Use a different way" / "Sign in another way" / "Try another method"
- **zh-CN 简体**: 「其他登录方法」「换一种方式」「使用其他验证方法」「发送代码/验证码」
- **zh-TW 繁体**: 「其他登錄方法」「換一種方式」「發送代碼/驗證碼」 — **不要漏繁体**,香港台湾用户的浏览器 locale 是 zh-TW

举例(Microsoft 登录页"其他登录方法"链接):

```js
return /その他のサインイン方法|別のサインイン方法|他のサインイン方法|その他の認証方法|
       Use a different|Sign in another way|I can't use|別の方法|コードを送信|
       其他登录方法|其他登錄方法|使用其他登录方法|使用其他登錄方法|
       其他验证方法|其他驗證方法|换一种方法|換一種方法|
       另一种方式|另一種方式|发送代码|發送代碼|发送验证码|發送驗證碼|
       无法使用|無法使用/.test(t);
```

参考:`templates/i18n-ui-text-regex.md` 有 Microsoft / Google / Stripe 常见交互文本的 zh+ja+en 三语对照表。

### 治本:auto-click 失败永远不抛 STAGE_STUCK,改 alertAndWait

正则再全也会漏(微软 A/B、新版界面、不在列表的 locale)。**结构上**:任何"按文本找元素再点"的 case,失败时不应该杀流程,而是报警等人接管。

#### 反模式

```js
// ❌ 自动点失败 = 流程死刑
case 'phone_confirm': {
  const ok = await switchToOtherSigninMethod(page);
  if (!ok) {
    const fp = await shot(page, envId, 'phone-confirm-no-switch');
    throw Object.assign(
      new Error(`找不到"その他のサインイン方法"链接. 截图: ${fp}`),
      { code: 'STAGE_STUCK' }
    );
  }
  await waitForStageChange(page, 'phone_confirm', 40000);
  break;
}
```

#### 正确模式 (跟 §6 一脉相承)

```js
case 'phone_confirm': {
  let ok = await switchToOtherSigninMethod(page);
  if (!ok) {
    // 自动点失败 → 报警等人工切换,**不杀流程**
    const fp = await shot(page, envId, 'phone-confirm-no-switch');
    progress.setBlocking(envId, 'phone_confirm: 自动点"其他登录方法"失败, 等人工');
    try {
      await alertAndWait({
        title: `envId=${envId} 自动点"其他登录方法"失败`,
        message: `可能是新 locale / 新 UI 变体. 请手动点页面上等效链接 (任何"换一种登录方式"按钮均可), 跳到选择验证方式页后回 UI 点继续.\n截图: ${fp}`,
        envId,
        check: async () => {
          // 跳到验证方式选择页 / 跳到下一阶段 / URL 已到下游 — 任一满足即解锁
          const s = await detectLoginStage(page).catch(() => 'unknown');
          if (s !== 'phone_confirm' && s !== 'unknown') return true;
          const url = page.url();
          return /signup\.azure|portal\.azure/.test(url);
        },
        timeoutMs: 5 * 60 * 1000,
      });
      progress.clearBlocking();
    } catch (waitErr) {
      progress.clearBlocking();
      throw Object.assign(
        new Error(`phone_confirm 人工接管超时/取消: ${waitErr.message}`),
        { code: 'STAGE_STUCK' }
      );
    }
  } else {
    await waitForStageChange(page, 'phone_confirm', 40000);
  }
  break;
}
```

### 心智模型

**老**:`autoClick失败 = 找不到元素 = 页面坏了 = STUCK`
**新**:`autoClick失败 = 文本/选择器没覆盖到当前变体 = 人能看懂 = alertAndWait`

页面真坏(URL 跳错域、白屏、Target closed)才是 STUCK。文本对不上不是。

### 防回归 grep

```bash
# 不应该再出现: auto-click 失败直接 throw STAGE_STUCK
grep -rn "if (!ok)" --include="*.js" -A 3 | grep -B 1 "STAGE_STUCK"

# 应该出现: auto-click 失败走 alertAndWait
grep -rn "if (!ok)" --include="*.js" -A 8 | grep -B 1 "alertAndWait"
```

