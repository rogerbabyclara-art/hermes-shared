# UI 文本匹配 i18n 三语对照表 (JP / EN / zh-CN / zh-TW)

按"功能"分组,每组列出实际页面上出现过的文本变体。**复制到正则前先校验**:

- 简繁体差异在汉字层面(代码/代碼、发送/發送、登录/登錄)
- 微软自家产品 zh-TW 多写"登錄",但 Azure 注册页有时混 "登入" — 写正则时两者都覆盖
- 日文"方法"和"やり方"是同义两套
- 英文匹配用 `/i` flag,大小写不敏感

## Microsoft 登录 — "其他登录方式"链接

| locale | 文本变体 |
|---|---|
| ja | その他のサインイン方法 / 別のサインイン方法 / 他のサインイン方法 / その他の認証方法 / 別の方法 / 確認コードを使用 / パスワードを使用 |
| en | Use a different verification option / Sign in another way / Try another way / I can't use my Microsoft Authenticator / Use a password / Use a code |
| zh-CN | 其他登录方法 / 使用其他登录方法 / 其他验证方法 / 换一种方法 / 换一种登录方式 / 另一种方式 / 另一种登录方法 / 使用密码 / 使用代码 / 无法使用 |
| zh-TW | 其他登錄方法 / 其他登入方法 / 使用其他登錄方法 / 其他驗證方法 / 換一種方法 / 換一種登錄方式 / 另一種方式 / 另一種登入方法 / 使用密碼 / 使用代碼 / 無法使用 |

## Microsoft 登录 — "向 xxx 发送验证码"按钮

| locale | 文本变体 |
|---|---|
| ja | xxx@…にコードを送信する / コードを送信 / メールでコードを受け取る |
| en | Email xxx@… / Send a code to xxx@… / Email a code / Get a code via email |
| zh-CN | 向 xxx 发送代码 / 向 xxx 发送验证码 / 发送代码到 xxx / 通过电子邮件发送代码 |
| zh-TW | 向 xxx 發送代碼 / 向 xxx 發送驗證碼 / 發送代碼到 xxx / 透過電子郵件發送代碼 |

## Microsoft 登录 — 备用邮箱兜底关键词

| locale | 文本变体 |
|---|---|
| ja | Eメール / メール / メールアドレス |
| en | Email / E-mail |
| zh-CN | 邮箱 / 电子邮件 / 电邮 |
| zh-TW | 郵箱 / 電子郵件 / 電郵 |

## Microsoft 登录 — KMSI ("保持登录状态") 蓝色按钮

| locale | 文本变体 |
|---|---|
| ja | はい (蓝) / いいえ (灰) |
| en | Yes / No |
| zh-CN | 是 / 否 |
| zh-TW | 是 / 否 |

注意 KMSI 主动点蓝色"是"才能省一次跳转,自动化里要 `findAndClickHuman` 主动点。

## 通用模板:写正则前自查清单

```
□ JP 汉字 + JP 假名两套都列了吗?
□ EN 用 /i flag 了吗? "Sign In" / "sign in" / "SIGN IN" 都要 hit
□ zh-CN 列了吗?
□ zh-TW 列了吗? (繁体不是简体,香港台湾用户跑必踩)
□ 是否有 ko / de / fr 也要列? (按目标用户群定)
□ 关键词是否会跟登录主页的卖点 panel 文字冲突? (参考 §3 危险词)
□ 找不到时是否走 alertAndWait 而非 STAGE_STUCK? (参考 §7 正确模式)
```

## 调试技巧:locale 切换不用 reset profile

Chromium 命令行参数 `--lang=zh-CN` / `--lang=ja-JP` 可以临时切渲染语言,验证正则覆盖度。在 puppeteer-extra 启动配置里:

```js
const browser = await puppeteer.launch({
  args: ['--lang=zh-CN'],  // 或 ja-JP / zh-TW / en-US
  ...
});
```

CloakBrowser / AdsPower 这种指纹浏览器,locale 通常绑 profile,要在 profile 设置里改后重开。
