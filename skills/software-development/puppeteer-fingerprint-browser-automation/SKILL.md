---
name: puppeteer-fingerprint-browser-automation
description: >
  Automate multi-step web flows with Puppeteer + fingerprint browsers (ADS/MoreLogin/CloakBrowser).
  Covers login state machines, SPA form filling, captcha interception, dropdown quirks,
  human-rhythm interaction helpers, blocking-alert patterns for manual fallback,
  puppeteer.connect retry against flaky CDP servers, stage-stuck vs slow-validation
  discrimination, URL-early-exit fallback for login state machines that stall on
  post-credential loading-dots pages, and **never-kill-browser retry policy** that
  promotes manual takeover from step-level (form timeout) to flow-level (outer
  catch) so expensive user clicks (KMSI / passkey / captcha) are not lost on retry. Use when building or debugging Puppeteer automations against hardened
  sites (Microsoft, Azure, Google, etc.) that use React/SPA forms, anti-bot detection,
  and multi-factor login.
  See references/cdp-connect-and-stuck-vs-slow.md for the retry/timeout playbook.
triggers:
  - puppeteer automation
  - fingerprint browser (ADS / MoreLogin / AdsPower / CloakBrowser)
  - Microsoft / Azure / Google login automation
  - SPA form filling (React controlled inputs)
  - captcha interception in Puppeteer
  - human-like clicking and typing
  - login state machine
  - puppeteer.connect timeout / CDP server flaky
  - stage-stuck vs slow-validation discrimination
tags:
  - puppeteer
  - playwright
  - fingerprint-browser
  - anti-bot
  - spa-forms
  - captcha
  - login-automation
  - cdp-timeout
  - human-fallback
linked_files:
  - references/azure-reg-flow-bugs.md
  - references/fork-merge-workflow.md
  - references/failure-retry-dashboard.md
  - references/diagnose-script.md
  - references/form-helper-app-architecture.md
  - references/captcha-retry-graduated-strategy.md
  - references/timeout-and-unattended-patterns.md
  - references/post-login-navigation-stall.md
  - references/electron-host-port.md
  - references/cooperative-pause-resume-control.md
  - references/captcha-alarm-renderer-ux.md
  - references/detector-regex-and-stuck-pattern.md
---

# Puppeteer + Fingerprint Browser Automation

> **Sibling skills — when to use which:**
> - This skill covers the **third-party-fingerprint-browser** path (ADS / MoreLogin / AdsPower over a local API). For the **self-hosted source-patched stealth Chromium** path (CloakBrowser / nodriver / camoufox) — no paid profile manager, no local API server, integer fingerprint seeds — see `stealth-browser-automation`. The two skills overlap on selector strategy, React quirks, captcha interception, and state-machine design (anything page-side is the same). They differ on browser lifecycle, profile storage, and proxy injection. If you're starting fresh, prefer `stealth-browser-automation`. If you're maintaining an existing ADS/MoreLogin codebase, stay here. The migration guide is at `stealth-browser-automation/references/migration-from-fingerprint-browsers.md`.
> - For the **Electron desktop UI** side of these projects (form-helper, form-helper-v2, FormHelper Azure tab, batch profile manager UIs) — `window.prompt` disabled in Electron renderer, AdsPower-style multi-account table conventions, batch action bars, tag chips, event log vs user notes separation, contextBridge IPC — see `electron-renderer-pitfalls`. The two skills are deliberately complementary: this one is Node-side / browser-side, the other is Electron renderer-side.

## When to load this skill
- Building or debugging Puppeteer scripts that drive ADS / MoreLogin / AdsPower fingerprint browsers
- Automating login flows (especially Microsoft / Azure / Google with MFA, passkey prompts, KMSI)
- Filling React/SPA forms where `input.value =` gets silently reset
- Handling captcha interception — need to block/wait rather than bail
- Debugging "window closed unexpectedly" failures in multi-stage flows
- Working on FormHelper Electron app (`form-helper-app`) — account management, company library, Azure runner control, or Claude enrich features
- Forking/cloning an Electron companion app alongside its backend project (e.g. form-helper-v2 for azure-auto-reg-v2)
- Comparing or merging features between FormHelper's Azure tab and v2 dashboard
- Adding new backend API features to FormHelper Electron app (5-file IPC bridge pattern: main.js → preload.js → index.html → tab.js → style.css)
- Adding mark-success / retry / progress features to FormHelper when runner is offline (direct runtime.json fallback)

---

## puppeteer-core: pin to 23.x for CJS codebases

**Symptom on `npm install puppeteer-core` followed by `require('puppeteer-core')`:**
```
Error [ERR_REQUIRE_ESM]: require() of ES Module .../puppeteer-core/lib/esm/...
  not supported.
Instead change the require ... to a dynamic import().
```
or in Electron renderer/main loading paths: silent failure with module not found.

**Root cause:** puppeteer-core 25.0.0 (and the 24.x late branch) shipped as
**pure ESM** — `"type": "module"` in its package.json with no CJS export. Any
`require('puppeteer-core')` call site breaks. Most existing Puppeteer
automation codebases (`flow.js`, `runner.js`, `ads.js`, `morelogin.js`, the
2023-era `azure-auto-reg` family, anything Electron-main-process) are CJS.

**Fix — pin to puppeteer-core 23.x:**
```bash
npm install puppeteer-core@23 --save
# resolves to 23.11.1 which is still CJS
```

23.11.1 is the highest CJS-compatible release. cloakbrowser / playwright /
real-browser-launcher peers all accept `>=21.0.0`, so 23.x stays compatible.

**General rule:** When integrating Puppeteer with an existing CJS codebase
(Electron main process, older Node scripts, CommonJS automation libs), check
the package.json `"type"` field of `node_modules/puppeteer-core` immediately
after install. If it says `"module"`, downgrade. Don't try to convert the
whole codebase to ESM just to use a newer Puppeteer — the version-pin fix is
two commands and three seconds.

**Forward-looking note:** When the time comes to migrate to ESM (top-level
`await` worth it, want latest Puppeteer features), do it as a deliberate
codebase-wide change, not as a side effect of `npm install`. The CJS↔ESM
boundary is hostile to incremental migration.

---

## When the user reports "stuck again, V2 老毛病" — ask, don't guess

When the user gives a vague symptom report about a long-running automation ("过了 captcha 又自动重启了", "卡住了", "又掉线了", "V2 老毛病重现"), there are usually 3–5 distinct failure modes that all produce a similar surface symptom (browser closes / window blanks / progress restarts), and they have completely different fixes. Speculating which one is happening and proposing a patch from the conversation alone wastes a debugging round AND erodes user trust ("you fixed it last time and it's still broken").

**Reflex: send back a small symptom table with 3–4 numbered cells. Ask the user to mark which row matches. THEN debug.** This works because the user already has the screen / log in front of them and picking from a list takes 5 seconds, whereas describing the failure in free text takes 2 minutes and is usually ambiguous.

Real-session template that worked (post-captcha self-restart in an Azure registration bot):

```
"过了验证码又自动掉了重启" 这里有几种可能,
我得知道是哪一种才能精准修:

| 现象                                                | 你看到的 |
|----------------------------------------------------|----------|
| A. 你点了「✅ 我过了」, 红警报消了, 浏览器**自己关了**重开 |    ?     |
| B. 警报消了, 浏览器没关但流程**重头跑**                 |    ?     |
| C. 警报压根没消, 过了好久才超时关掉                    |    ?     |
| D. 浏览器自己跳回登录页                              |    ?     |

最有可能是 A (V2 老毛病基本都是这个). 想确认请做两件事:
  1. 把日志关键 10 行截图发我
  2. 你按「我过了」那一刻, 浏览器画面是验证码刚打勾, 还是已经跳到下一页了?
```

Then your top candidate hypothesis with the proposed fix sketch, so the user knows you have a direction — but DO NOT apply the fix until they confirm the row.

**Why this beats "I'll add more logging and you re-run":**
- A symptom table is 30 seconds for the user; a re-run with new logs is a full task cycle (often 10+ minutes for Azure-style flows that need a fresh account / IP).
- The user often DOES know the answer from their last failed run — they just don't know which fact you need.
- Forces YOU to enumerate distinct failure modes before proposing a fix. Half the time, drawing up the table reveals you'd been ignoring an alternative explanation.

**Pitfall — don't auto-apply a fix when the user says "卡住了" with no specifics.** Even if you have a strong prior. The 3–5-row table is cheap insurance. The cost of fixing the wrong mode is a wasted retest + another round of "still broken".

This is the same energy as the existing `captcha-alarm-renderer-ux.md` reference's "human-in-the-loop event" handling: long flows have many failure modes that look identical from outside; build cheap disambiguation into your communication loop.

---

## Architecture pattern

```
runner.js (task queue + retry loop)
  └─ flow.js (staged flow: open → login state machine → form1 → form2 → payment)
       ├─ ads.js / morelogin.js (fingerprint browser lifecycle)
       ├─ stealth.js (navigator.credentials patch, WebAuthn disable)
       ├─ typing.js (typeHuman / clickHuman)
       ├─ mail.js (IMAP verification code fetch)
       └─ alert.js (Windows popup + polling blocker)
```

**Key principle**: stages are one-way checkpoints. On any failure, the runner retries from the top (re-open browser), not mid-stage. Never retry mid-state-machine.

### The orchestrator vs the primitives — read the right file first

`flow.js` looks like a linear pipeline (it exports `runToForm1`, `runForm1Fill`, `runForm2Fill`, `close` and a long list of helpers). **It is not the orchestrator.** The actual sequencing — the `for attempt 1..5` retry loop, the `for step 0..60` state-machine poll, the `detectStage()` → switch on `form3 / captcha / error_page / form1_stuck / form2`, the captcha-timeout-then-reopen logic — all lives in `runner.js`. If you only read flow.js and ship a linear `runToForm1 → form1Fill → form2Fill → done` flow, you will ship a bot with no captcha handling, no error_page recovery, and no STUCK retry. It will die on the first real envId.

**Rule before porting any multi-stage Puppeteer automation:**

1. Identify the orchestrator — name patterns: `runner.*`, `scheduler.*`, `orchestrator.*`, `loop.*`, anything with `runOne`/`runAll`/`runBatch`.
2. Identify the primitives — name patterns: `fill*`, `click*`, `wait*`, `detect*`, `recover*`, `submit*`, the `flow.*` file itself.
3. Read the orchestrator end-to-end FIRST. Note every `case '<stage>':`, every `if (stage === ...)` branch, every retry counter, every timeout escape hatch.
4. Then read the primitives only to understand what each branch calls.
5. After writing the port, diff the stage sets: `grep -E "case '\w+':|if \(stage === " original/runner.js | sort -u` vs the same on your port. Any missing stage is a silent bug.

Compile-clean (`node -e "require('./your-port')"` + lint OK) is **not** behavioral parity. The static loader will happily accept a port that's missing 4 out of 5 state-machine branches.

### CRITICAL: Look at the older project's working solution before reinventing

When a multi-version project line exists (V1 → V2 → V3, each its own directory like `azure-auto-reg`, `azure-auto-reg-v2`, `form-helper-v2`), and the user says something like "you did this in V2, think about how", **always `grep -rn` the older directories for the relevant keyword first** before sitting down to design a fresh solution. The earlier version almost certainly has a working pattern that was tuned through real production failures. Reinventing wastes the user's debugging time and discards hard-won knowledge.

```bash
# Real example — user asked how to handle Microsoft's KMSI "stay signed in" page
cd D:\Projects\azure-auto-reg-v2
grep -rn "サインイン\|stay.*sign\|kmsi\|はい" src/ | head -30
# → finds the evaluateOnNewDocument auto-clicker in src/flow.js:167
#   with the exact #idSIButton9 + value="はい" + text-match selector hierarchy
```

This is the right starting point even when the older code can't be used as-is (different runtime: standalone Node vs Electron main process; different browser adapter: ADS vs CloakBrowser). The **algorithm** transfers; only the **substrate** changes.

**User signal** — "你V2最终版是做到了，想想当时怎么做的" / "you did this in V2, think about how" — is a direct instruction to do exactly this. Don't acknowledge and then design from scratch; grep the older code first, then port + adapt.

### Porting a standalone runner into an Electron main process

When hosting an existing runner inside an Electron app (UI-driven single-task execution + live progress + in-app captcha unblock buttons), the primitives in `flow.js` should NOT change. What changes:

- `alert.js` rewires from `rundll32+msg.exe+PowerShell MessageBox+TG+continue-{envId}.flag file polling` → Electron `Notification` API + `BrowserWindow.webContents.send` events + in-memory `Map<envId, true>` for the continue flag.
- The vendor adapter (`ads.js`/`morelogin.js`) becomes a thin **read-only** `cloakbrowser.js` that fetches `wsEndpoint` from a shared `ACTIVE_BROWSERS` Map populated by another tab's `▶ 启动` IPC handler. The runner does NOT open or close browsers — another tab owns lifecycle.
- `tasks.json` / `runtime.json` / `progress.jsonl` / HTTP dashboard go away entirely. UI checkboxes are the task input, the rendered table is the result store, `azure:result` events update the table in real-time.
- Captcha timeout shortens from 5 min (V2 desktop popup, operator may be away) to 3 min (operator is in the app). On timeout, `browser.disconnect()` + outer `attempt++` reopens the connection. **In single-task mode**, prefer disconnect-only so the operator can keep poking at the browser; **in queue mode**, the adapter's `stopEnv()` MUST really close the browser (see next bullet for why).
- **CRITICAL — `stopEnv` must NOT be no-op in queue/retry mode**. Early ws-attach adapters were written as `async stopEnv(_envId) { /* no-op */ }` on the theory that "another tab owns the lifecycle, we just attach." This is **wrong** as soon as flow.js's STAGE_STUCK retry kicks in. Flow.js's recovery sequence is `browser.disconnect()` → `ads.stopEnv()` → `await sleep(3000)` → loop top → `startEnv()` again. If `stopEnv()` is a no-op, the browser stays running with the same now-stale ws (often the underlying CDP target detached but the launcher cache still has the old URL). Next `startEnv()` returns the same dead ws → `puppeteer.connect()` hangs the full 60s → STAGE_STUCK again → infinite loop, 3 attempts × 60s = task dies after 3 minutes of doing nothing. **Real symptom in logs**: `[flow] ✗ failed: puppeteer.connect 60秒超时` repeated 3 times back-to-back with no other activity, and the user reports the bot is "stuck and not doing anything". **Fix**: `stopEnv()` must call the real `stopBrowser(name)` from the proxy/profile module (the same one the [代理] tab's ⏹ button calls) AND the adapter's `startEnv()` must self-bootstrap if the browser isn't running (lookup account+IP from proxies.json, call `launchBrowser`, poll `child._wsEndpoint` until ready). Once both halves are wired, the same code path serves three callers: (a) batch queue auto-open at runOne entry, (b) flow.js's STAGE_STUCK reset-and-retry, (c) manual ▶ from the [代理] tab. See `references/electron-host-port.md` for the full adapter code.\n- **wsEndpoint readiness is async — DO NOT blind-sleep**. Whether you open via `launchBrowser()` at runOne entry or via the adapter's self-bootstrap, the CloakBrowser/stealth Chromium kernel takes **3-10 seconds** to start and have its launcher process up-report `child._wsEndpoint`. A flat `await new Promise(r => setTimeout(r, 1500))` is too short → `startEnv` reads an empty `_wsEndpoint` → either throws "未捕获" or returns garbage → next puppeteer.connect hangs 60s. **Correct pattern**: poll the `ACTIVE_BROWSERS` Map every 500ms for up to 30s waiting for `child._wsEndpoint` to become truthy, then sleep an extra 1.5s for the browser's internal page to be ready, then return. Both runOne's entry-time open AND the adapter's self-bootstrap need this. Code skeleton:\n  ```js\n  const wsReady = await new Promise((res) => {\n    const t0 = Date.now();\n    const iv = setInterval(() => {\n      const c = ACTIVE_BROWSERS.get(name);\n      if (c && c._wsEndpoint) { clearInterval(iv); res(c._wsEndpoint); return; }\n      if (Date.now() - t0 > 30000) { clearInterval(iv); res(null); }\n    }, 500);\n  });\n  if (!wsReady) { await stopBrowser(name); throw new Error('wsEndpoint 30s timeout'); }\n  await sleep(1500);  // page-ready buffer\n  ```\n- **Diagnostic logging — always print the `ws` URL** right before `puppeteer.connect()`. One line: `console.log(\"[flow] got ws=\" + info.ws.slice(0,80))`. When the user reports "stuck at puppeteer.connect 60s" you instantly know whether `startEnv` returned a real-looking ws (then the kernel side is broken) or empty/garbage (then the adapter or launcher is broken). Without this log you waste a debugging round asking the user to add it.\n- **Lifecycle exception for queue mode**: the "another tab owns lifecycle" rule is correct for **single-task UI-driven** runs (operator clicks ▶ on one row → wants to keep the browser open after to inspect → may run another task on the same browser). But for **batch queue mode** ("一次只开一个浏览器, 跑完关下一个开"), the runner has to drive lifecycle itself or the queue can't run at all. Two pieces are needed:
  1. The proxy/profile module must export `launchBrowser(account, ipEntry, dataDir, startUrl)` and `stopBrowser(name)` from its `module.exports`, not just register them as IPC handlers. Pure IPC works for the renderer but not for sibling modules in main process.
  2. The runner's `runOne(name)` checks `ACTIVE_BROWSERS.has(name)` at entry — if false, it calls `launchBrowser` itself (looking up the account + IP from `proxies.json` directly). The batch loop then calls `stopBrowser(name)` after each `runOne` returns, and sleeps ~1.5s before the next one to let ws / file handles release. Single-task `azureRegisterOne` does NOT go through the close path — the operator wants the browser to stay open.
  3. UI side: drop the pre-open phase (`proxyBatchOpen(needBoot, concurrency: 5)`) entirely. Mark all selected envIds as `queued` optimistically, then fire-and-forget `azureRegisterBatch(names)`. The backend opens browsers one at a time as the queue advances. Concurrency-5 pre-open exists in V3 codebases as a legacy from before this pattern existed — it causes 5 browser windows to fight for resources / VRAM / proxy slots and was the original "computer melts" pain.
- Preload must expose both invokers (`azureRegisterOne`/`azureContinueOne`/`azureRegisterBatch`) AND event subscribers (`onAzureProgress`/`onAzureBlocking`/`onAzureUnblocked`/`onAzureResult`). Rip out all dangling V2 IPC API names (`azureState`/`azureTasks`/`azureRuntime`/`azureStartRunner`/`azureMarkSuccess`/etc.) — they'll trigger silent `invoke()` errors when stale renderer code references them.

See `references/electron-host-port.md` for the full V2→V3 transform: skeleton code for `azure/index.js` (state-machine runner inside `ipcMain.handle`), the `alert.js` Electron rewrite, the read-only `cloakbrowser.js` adapter, the `bindElectron(electron)` injection pattern, and the lesson narrative from the real port where reading flow.js first led to a wrong linear pipeline.

### CRITICAL: Skip completed stages after redirect

When `page.goto(siteURL)` redirects to a login page (e.g. Azure signup → `login.live.com`), the intermediate step (clicking an entry link on the landing page) has already been bypassed by the redirect. The runner MUST check the post-navigation URL and skip steps that are no longer relevant:

```js
({ browser, page, userId } = await openSite(envId));

const postOpenUrl = page.url();
const alreadyOnLogin = /login\.(live|microsoftonline|microsoft)\.com/.test(postOpenUrl);
if (alreadyOnLogin) {
  console.log(`Already on login domain (${postOpenUrl.slice(0, 80)}), skipping entry click`);
} else {
  await clickEntryLink(page, envId);  // only needed when on the landing page
}
await doLogin(page, profile, envId);  // always needed
```

**Bug pattern without this**: `openSite()` returns after a redirect timeout → runner calls `clickEntryLink()` → no entry link exists on the login page → throws `STAGE_STUCK` → window killed → retry → same redirect → same failure → task marked failed after max retries. The entry link step was never needed because the redirect already skipped it.

### CRITICAL: Timeout protection on all external calls

**Bug pattern**: Runner freezes at `open.browser_launch` stage, dashboard "continue" button has no effect, process appears hung.

**Root cause**: `puppeteer.connect()`, `ads.startEnv()`, `morelogin.call()`, and `page.goto()` can all hang indefinitely with no timeout. When this happens, the runner's main loop is blocked in an `await` — no `alertAndWait` is running, so flag files go unpolled. The dashboard button writes a flag nobody reads.

**Fix**: Every external call in the startup path must have a timeout wrapper:

```js
// 1. Fingerprint browser API calls — add AbortController to fetch
async function call(path, body = {}) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 30000); // 30s
  try {
    const res = await fetch(url, { ...opts, signal: controller.signal });
    clearTimeout(timer);
    // ... process response
  } catch (e) {
    clearTimeout(timer);
    if (e.name === 'AbortError') throw new Error(`API 30秒超时: ${path}`);
    throw e;
  }
}

// 2. puppeteer.connect — no built-in timeout, use Promise.race
const browser = await Promise.race([
  puppeteer.connect(connectOpts),
  new Promise((_, reject) => setTimeout(() => reject(
    Object.assign(new Error('puppeteer.connect 60秒超时'), { code: 'STAGE_STUCK' })
  ), 60000)),
]);

// 3. safeGoto wrapper — REPLACE ALL page.goto WITH THIS
// PITFALL: On redirect chains (e.g. Azure signup → login.live.com), Puppeteer's
// domcontentloaded may never fire even though the destination page is fully loaded
// and interactive. Individual try/catch blocks per-goto are fragile and lead to
// repeated bug-fix cycles. Use a single wrapper function for ALL navigation:
async function safeGoto(page, url, timeoutMs = 30000) {
  try {
    await page.goto(url, { waitUntil: 'domcontentloaded', timeout: timeoutMs });
  } catch (e) {
    const curUrl = page.url();
    const onKnown = /login\.(live|microsoftonline|microsoft)\.com|signup\.azure\.com|portal\.azure\.com|azure\.microsoft\.com|account\.microsoft\.com/.test(curUrl);
    if (onKnown) {
      console.warn(`safeGoto timeout but URL on known domain (${curUrl.slice(0,80)}), continuing`);
      return;
    }
    if (curUrl === 'about:blank') throw e; // truly didn't navigate
    // URL moved to unknown domain — let state machine decide
    console.warn(`safeGoto timeout, URL=${curUrl.slice(0,80)}, attempting to continue`);
  }
}
// Then replace EVERY page.goto in the codebase:
//   openAzure: IP probe, main URL, entry link click
//   clickEntry: entry href navigation
// The state machine handles "where did we actually land" — navigation success/failure
// is NOT the right signal for flow control.

// 4. IP probe before main goto — detect dead proxies in 15s instead of 60s
// PITFALL: Do NOT use .ico/.png/.pdf URLs — fingerprint browsers treat them as downloads
// and pop a "Save As" dialog that blocks the automation. Use an HTML endpoint.
// NOTE: Use safeGoto for the probe too — it will throw on about:blank (true network failure)
// but absorb timeouts if the probe URL redirected to a known login domain.
try {
  await safeGoto(page, 'https://login.microsoftonline.com/common/oauth2/authorize', 15000);
} catch (e) {
  throw Object.assign(new Error('IP probe failed: ' + e.message.slice(0, 60)), { code: 'STAGE_STUCK' });
}
```

**Why `STAGE_STUCK` code**: The timeout error must carry `{ code: 'STAGE_STUCK' }` so the runner's existing graduated retry logic catches it and does close-window → reopen → retry. Without this code, the error falls through to the generic failure handler and the task is marked failed with no retry.

**General rule**: If an `await` in the runner's hot path could hang forever, it MUST have a timeout that throws `STAGE_STUCK`. The runner's retry loop is the safety net — but only if the error reaches it.

### Browser engine abstraction

When supporting multiple fingerprint browsers (ADS, MoreLogin, etc.), **never hardcode vendor names** in log messages, alerts, or UI text. Use a dynamic label:

```js
function engineLabel(task) {
  return ((task && task.browser) || 'ads') === 'morelogin' ? 'MoreLogin' : 'ADS';
}

// ❌ console.log(`重启 ADS`);
// ✅ console.log(`重启 ${engineLabel(task)}`);
```

The `pickBrowser(task)` function returns the module (ads.js or morelogin.js), while `engineLabel(task)` returns the human-readable name. Keep both in runner.js scope. For flow.js (which receives the module, not the task), use generic terms like "浏览器" in log messages.

### Graduated retry strategy (CRITICAL)

**Bug pattern**: Login succeeds → form loads slowly → 30s timeout → STAGE_STUCK → `stopEnv()` → ADS window killed → cookies lost → next attempt must re-login → may hit captcha → risk escalation.

**Root cause**: The retry loop calls `ads.stopEnv()` on EVERY STAGE_STUCK, even the first attempt. This destroys the browser session including cookies, forcing a complete restart.

**Fix**: Use graduated retries:
- **Attempts 1-2**: Only `browser.disconnect()` — keep ADS window alive, preserve cookies. `startEnv` on next attempt returns existing connection info.
- **Attempts 3+**: `stopEnv()` for hard reset — the soft approach isn't working, start fresh.

```js
if (e.code === 'STAGE_STUCK' && attempt < MAX_STUCK_RETRIES) {
  const hardReset = attempt >= 3;
  console.log(`[runner] ${hardReset ? 'hard reset (stopEnv)' : 'soft retry (disconnect only)'}`);
  if (result) {
    try { await result.browser?.disconnect(); } catch {}
    if (hardReset) {
      try { await ads.stopEnv(result.userId); } catch {}
    }
  }
  await sleep(3000);
  continue;
}
```

**Why this works**: ADS/MoreLogin `startEnv()` returns the existing connection when the environment is already running. So disconnect + reconnect reuses the same browser profile with cookies intact. The user's login session survives, and the flow picks up much faster on retry.

**Exception — dead proxy IP or IP-stuck navigation**: When the error message contains "IP 探活失败" (IP probe failure) or carries `hint: 'ip_stuck'` (post-login navigation stalled), ALWAYS do hard reset (`stopEnv`) regardless of attempt number. Soft retry (disconnect only) reuses the same proxy session = same dead/stuck IP = wasted attempt.

```js
const isDeadIP = e.message && e.message.includes('IP 探活失败');
const isIPStuck = e.hint === 'ip_stuck';
const hardReset = isDeadIP || isIPStuck || attempt >= 3;
// Dead/stuck IP → close window + stop env → reopen gets new proxy session
```

---

## Browser-level auto-clickers via evaluateOnNewDocument

**When Puppeteer code is blocked** (stuck in `await page.goto`, `await waitForAny`, etc.), it cannot execute actions on the page — even if the page is fully loaded and interactive. The user sees a clickable button, but the code can't reach it.

**Solution**: Inject a self-running script into every new page via `evaluateOnNewDocument`. This runs in the browser's JS context, completely independent of Puppeteer's Node.js event loop. It works even when the Node process is blocked in an `await`.

```js
// Inject right after page creation, BEFORE any navigation
await page.evaluateOnNewDocument(() => {
  const INTERVAL = setInterval(() => {
    try {
      if (!document.body) return;
      const txt = document.body.innerText || '';
      // Example: auto-click KMSI "はい" button
      if (!txt.includes('サインインの状態を維持')) return;
      const btn = document.querySelector('#idSIButton9')
        || document.querySelector('input[type="submit"][value="はい"]')
        || Array.from(document.querySelectorAll('button, input[type="submit"]'))
            .find(b => (b.innerText || b.value || '').trim() === 'はい');
      if (btn) {
        console.log('[auto-click] detected target, clicking');
        btn.click();
        clearInterval(INTERVAL);
      }
    } catch {}
  }, 1500);
  // Auto-stop after 60s (each new navigation re-injects, so this is per-page)
  setTimeout(() => clearInterval(INTERVAL), 60000);
});
```

**Key properties**:
- Runs in **browser context**, not Node.js — works even when Puppeteer is stuck in `await`
- `evaluateOnNewDocument` re-injects on **every navigation** (including redirects) — no need to manually re-inject
- Uses `btn.click()` which IS `isTrusted: true` when called from the page's own JS context (unlike `dispatchEvent` from `page.evaluate`)
- The `setInterval` + `clearInterval` pattern ensures it fires exactly once
- 60s timeout prevents eternal polling; re-injection on next navigation restarts the clock

**When to use**: For any known intermediate page that always needs the same action (click a button, dismiss a prompt). The KMSI "stay signed in" page is the canonical example — it always appears, always needs "はい" clicked, and the redirect after clicking is what causes `page.goto` to hang.

**Defense-in-depth**: This is Layer 1. The state machine's `case 'kmsi': await clickKmsiYes(page)` is Layer 2. Having both means the auto-clicker handles the common case instantly (before the state machine even sees KMSI), and the state machine handles edge cases where the auto-clicker didn't fire (page took >60s to load, button ID changed, etc.).

**Pitfall**: `evaluateOnNewDocument` must be called BEFORE the first `page.goto` / `safeGoto`. If called after navigation has started, it won't apply to the current page — only to subsequent navigations.

**Pitfall — fails silently under ws-attach + reload**: When `flow.js` is not opening the browser but **attaching to an externally-launched browser via `puppeteer.connect({ browserWSEndpoint })`** (the V3 / CloakBrowser / FormHelper pattern), `evaluateOnNewDocument` is registered on the puppeteer-side `Page` object — but that Page is a thin proxy over the existing target. Any in-process `page.reload()`, target re-attach after a captcha popup, or new tab handoff can detach the registration. The auto-clicker simply stops firing, with no error, no log, no symptom — until the operator notices the KMSI page is stuck and nobody clicks はい.

In ws-attach mode you must add a **second layer**: have the state machine's `detectStage` (or whatever runs on every tick of the main loop) actively try the click itself, every poll. This way the auto-clicker is "best-effort fast path" and the state machine is "guaranteed eventual path":

```js
async function detectLoginStage(page) {
  // Active KMSI click — fires every detect tick, doesn't depend on
  // evaluateOnNewDocument staying alive across reloads / target re-attach
  try {
    const clicked = await page.evaluate(() => {
      try {
        const txt = (document.body && document.body.innerText) || '';
        if (!txt.includes('サインインの状態を維持')) return false;
        const btn = document.querySelector('#idSIButton9')
          || document.querySelector('input[type="submit"][value="はい"]')
          || Array.from(document.querySelectorAll('button, input[type="submit"]'))
              .find((b) => ((b.innerText || b.value || '').trim() === 'はい'));
        if (!btn) return false;
        const r = btn.getBoundingClientRect();
        if (r.width < 5 || r.height < 5) return false;
        btn.click();
        return true;
      } catch { return false; }
    }).catch(() => false);
    if (clicked) {
      console.log('[detect] ★ KMSI auto-clicker fired, clicked はい');
      await new Promise((r) => setTimeout(r, 800));  // give nav a moment
    }
  } catch {}

  // ... rest of stage detection ...
}
```

**Rule**: if the codebase uses `puppeteer.connect({ browserWSEndpoint })` (attaching to a pre-launched browser), **never rely on `evaluateOnNewDocument` alone** for any auto-clicker. Always pair it with an active-polling tick inside the state machine. If the codebase uses `puppeteer.launch()` (puppeteer owns the browser lifecycle), `evaluateOnNewDocument` is reliable on its own — but it costs nothing to have both layers anyway.

---

## Login state machine

Microsoft login is a SPA with non-deterministic step order. Use a loop + stage detector, not a linear sequence.

```js
for (let step = 1; step <= 30; step++) {
  const stage = await detectLoginStage(page);
  switch (stage) {
    case 'email':       await fillEmail(...); break;
    case 'password':    await fillPassword(...); break;
    case 'phone_confirm': await switchToOtherMethod(...); break;
    case 'verify_method_picker': await pickBackupEmail(...); break;
    case 'confirm_backup_email': await fillBackupEmailConfirm(...); break;
    case 'verify_code': await fillVerifyCode(...); break;
    case 'kmsi':        await clickKmsiYes(...); break;
    case 'passkey_prompt': await clickPasskeyNext(...); break;  // WebAuthn disabled → fallback
    case 'azure_form1': return;  // done
    case 'unknown':     // wait + screenshot, timeout after 40s
  }
}
```

**Pitfall**: `waitForNavigation` is unreliable on SPA login flows. Use `waitForAny(page, selectors, timeout)` — poll for any of N selectors every 400ms.

**Pitfall**: Stage detection must use `reallyVisible()` checks (bounding rect + parent chain display/visibility/opacity) not just `page.$()` — SPA keeps off-screen elements in DOM.

---

## Captcha interception — NEVER bail silently

**Critical pattern**: when captcha is detected, do NOT throw and close the window. Block and wait for human.

```js
// ❌ WRONG — closes window without warning
if (captchaHit) throw new Error('captcha_skip');

// ✅ CORRECT — alert + block + auto-detect resolution
if (captchaHit) {
  await alertAndWait({
    title: `envId=${envId} 登录阶段人机验证`,
    message: `步骤 ${step} 出现 captcha，请手动过验证后点继续...`,
    envId,
    check: async () => {
      const stillHas = await page.evaluate(() =>
        /captcha|reCAPTCHA|hcaptcha|ロボット/.test(document.body?.innerText || '')
      ).catch(() => true);
      return !stillHas;  // resolve when captcha gone
    },
    timeoutMs: 5 * 60 * 1000,  // 5 min for captcha — human needs time to switch, solve, continue
  });
  unknownSince = 0;  // reset unknown timer after manual intervention
  continue;          // resume state machine
}
```

Apply this pattern at **every captcha check point**:
- Login state machine (each step)
- Form1 post-fill validation (outcome === 'captcha')
- Form2 post-fill validation (outcome === 'captcha')
- Runner's own `detectStage()` loop

The `alertAndWait` `check` function should verify the captcha is actually gone AND that the flow can proceed (button enabled, or page advanced).

### Enhanced check + auto-advance after captcha resolution

The simple "captcha text gone" check is insufficient. The improved pattern checks multiple conditions:

```js
check: async () => {
  const s = await page.evaluate(() => {
    const btn = document.querySelector('#accept-terms-submit-button'); // form1's submit
    const txt = (document.body && document.body.innerText) || '';
    const hasCaptcha = /captcha|reCAPTCHA|hcaptcha|ロボット/.test(txt);
    const btnEnabled = btn ? !btn.disabled : false;
    const onNextForm = /ステップ\s*2\s*\/\s*4/.test(txt); // already advanced
    return { hasCaptcha, btnEnabled, onNextForm };
  }).catch(() => null);
  if (!s) return false;
  return !s.hasCaptcha && (s.btnEnabled || s.onNextForm);
},
```

After captcha resolves, auto-click the submit button if the page hasn't already advanced:

```js
// After alertAndWait resolves:
const postState = await page.evaluate(() => ({
  btnDisabled: btn ? btn.disabled : true,
  btnGone: !btn,
  onNextForm: /next-form-pattern/.test(txt),
})).catch(() => null);
if (postState && !postState.onNextForm && !postState.btnGone && !postState.btnDisabled) {
  await clickHuman(page, '#submit-button').catch(() => {});
  await sleep(randInt(1500, 2500));
}
```

### progress.setBlocking / clearBlocking integration

Wrap alertAndWait with `progress.setBlocking(envId, reason)` before and `progress.clearBlocking()` after (both success and error paths). This feeds the dashboard/status panel so operators see which envId is blocked and why.

---

## React/SPA form filling

React-controlled inputs reject naive `input.value = x`. Use native input descriptor setter:

```js
async function reactSet(page, selector, value) {
  await page.evaluate((sel, val) => {
    const el = document.querySelector(sel);
    const proto = Object.getPrototypeOf(el);
    const desc = Object.getOwnPropertyDescriptor(proto, 'value');
    if (desc && desc.set) desc.set.call(el, val);
    else el.value = val;
    el.dispatchEvent(new Event('input', { bubbles: true }));
    el.dispatchEvent(new Event('change', { bubbles: true }));
  }, selector, value);
}
```

**For reliable input** (fields that verify on blur): use `typeHuman` with `mode: 'safe'` — real keyboard events, not setter. Setter gets reset by React's blur validation on some fields.

**Verify after fill**: wait ~10s then re-read all field values and re-fill any that got reset. React can reset fields on state updates triggered by filling adjacent fields.

### React form field value pollution (cross-field leakage)

**Bug pattern**: After filling all fields, `firstName` contains the expected value PLUS trailing digits from the phone number (e.g. `啓之81768125` instead of `啓之`). The phone field itself shows the correct formatted value (`080 8176 8125`).

**Root cause**: React's phone field has auto-formatting (inserting spaces into the phone number on input events). During formatting, React triggers DOM re-render which can cause keyboard events from `typeText` to leak into the previously-focused field if that field hasn't fully detached from the input event stream.

**Two-layer fix**:

1. **Blur isolation after auto-formatting fields**: After typing into any field that has React auto-formatting (phone numbers, postal codes, credit card numbers), immediately `blur()` and wait 800-1500ms BEFORE moving to the next field:

```js
await typeHuman(page, '#work-phone-input', profile.phoneMobile, { mode: 'safe' });
// blur + wait for React formatting to complete — prevents event leakage to adjacent fields
await page.evaluate(() => {
  const el = document.querySelector('#work-phone-input');
  if (el) el.blur();
});
await sleep(randInt(800, 1500));
```

2. **Value comparison verification** (not just empty-check): The post-fill verify must compare actual values against expected values, not just check for empty:

```js
// ❌ WRONG — only catches empty fields, not polluted ones
if (!fullCheck.firstName) fixes.push('firstName');

// ✅ CORRECT — catches pollution like "啓之81768125" ≠ "啓之"
const norm = (s) => String(s || '').replace(/[\s　\-_]/g, '');
if (!fullCheck.firstName || norm(fullCheck.firstName) !== norm(profile.firstNameKanji)) {
  fixes.push('firstName');
}
```

**General rule**: Any time you see a field whose value is longer than expected and contains characters from an adjacent field's value, suspect React auto-formatting event leakage. The fix is always: blur the formatting field + wait + verify-by-value-comparison.

**Note**: `typeHuman` already has a blur-before-focus step (L166-173 in typing.js), but that only blurs the *previous* active element when *starting* to type in a new field. The phone field's React formatter fires *after* typing completes, so the blur must happen *after* `typeHuman` returns, not before the next field starts.

---

## Dropdown (pidl combobox) selection

Azure's pidl combobox is not a `<select>`. The menu exists in DOM but is hidden; clicking the button exposes it.

```js
// 1. Click button to open menu
await page.click('#pidlInput_region');
await sleep(500);

// 2. Wait for menu to have expected items (e.g. >= 47 for 都道府県)
// Retry up to 6 times

// 3. Find item — use FUZZY MATCHING not strict equality
//    Profile data "京都" must match option "京都府"
const hit = items.find(el => {
  const t = (el.innerText || '').trim();
  return t === target || t.includes(target) || target.includes(t);
});

// 4. Dispatch full event sequence on the <li>
hit.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, ... }));
hit.dispatchEvent(new MouseEvent('click', { bubbles: true, ... }));

// 5. Verify button text changed
const buttonText = await page.$eval('#pidlInput_region', el => el.innerText.trim());
if (!buttonText.includes(target)) {
  // Fallback: setter on button + dispatchEvent change
}
```

**Pitfall**: items array may contain duplicates (96 items for 47 prefectures = each listed twice). Fuzzy match still picks the first hit correctly.

**Pitfall**: if no match after fuzzy, log ALL item texts (not just sample) — makes debugging trivial.

---

## Human-rhythm interaction helpers

All clicks and types must use human-paced helpers to avoid bot detection:

- `typeHuman(page, sel, text, { mode: 'safe' })` — real key events with per-key random delay
- `clickHuman(page, sel)` — mouse move to element, random dwell, then click
- `findAndClickHuman(page, finderFn, label)` — find element in page context, wait 5s, then clickHuman; retries 3x before falling back to `dispatchClick`
- Before any `clickNextButton`, wait 5s to let React state + backend validation stabilize

### Button click reliability hierarchy

For **stable-ID buttons** (e.g. `#idSIButton9`, `#accept-terms-submit-button`), use `page.click()` as **primary** strategy — it calculates element center coordinates via CDP, produces `isTrusted: true` events, and is more reliable than custom mouse trajectories. Fall back to `clickHuman()` only if `page.click()` fails.

For **dynamic/SPA buttons** found via text matching (no stable ID), use `clickHuman()` with `page.click(selector)` as fallback:

```js
try {
  await clickHuman(page, found.selector);
  return found;
} catch (e) {
  // clickHuman mouse trajectory missed → page.click as fallback
  try {
    await page.click(found.selector);
    return found;
  } catch (e2) {
    return null;
  }
}
```

**KMSI example** — `clickKmsiYes()` must try multiple methods AND **verify after each attempt** that the page actually navigated away. The old pattern (try method → return without checking → wait 40s in main loop → discover it didn't work) wastes 80+ seconds per failure cycle.

```js
async function clickKmsiYes(page) {
  await page.waitForSelector('#idSIButton9', { visible: true, timeout: 15000 });
  await sleep(randInt(2000, 3000)); // let React finish binding

  const clickMethods = [
    { name: 'page.click',     fn: () => page.click('#idSIButton9') },
    { name: 'mouse.down/up',  fn: async () => { /* get bbox, mouse.move, down, up */ } },
    { name: 'JS submit',      fn: () => page.evaluate(() => { btn.click(); btn.form?.submit(); }) },
    { name: 'keyboard Enter', fn: async () => { await page.focus('#idSIButton9'); await page.keyboard.press('Enter'); } },
  ];

  for (const method of clickMethods) {
    try {
      await method.fn();
      await sleep(3000); // let page navigate
      // CRITICAL: verify the click actually worked
      const stillKmsi = await page.evaluate(() =>
        document.body?.innerText.includes('サインインの状態を維持')
      ).catch(() => false);
      if (!stillKmsi) return; // success — page moved on
    } catch {}
  }
  throw Object.assign(new Error('KMSI all methods failed'), { code: 'STAGE_STUCK' });
}
```

**Key insight**: The main loop should NOT have its own `waitForStageChange` after `clickKmsiYes` — the function itself already verified navigation. Double-waiting is a waste:

```js
// ✅ CORRECT — clickKmsiYes verifies internally
case 'kmsi':
  await clickKmsiYes(page);
  break;

// ❌ WRONG — redundant wait adds 40-80s on failure
case 'kmsi':
  await clickKmsiYes(page);
  await waitForStageChange(page, 'kmsi', 40000); // unnecessary
  break;
```

**General rule**: `page.evaluate(() => el.click())` is **always wrong** for React apps — it produces `isTrusted: false`. Use `page.click(selector)` (CDP-level) or `clickHuman(page, selector)` (which wraps CDP click with human-rhythm delays). Both produce `isTrusted: true`.

---

## Window close strategy (rolling)

Rolling window pattern: previous success window stays open until the next task starts, then gets closed (30-60s delay). This avoids closing a window immediately after success (risk signal).

```js
// On task start (before opening new window):
if (prevSuccessEnvId) {
  await sleep(randInt(30, 60) * 1000);
  await browserMod.stopEnv(prevSuccessEnvId);
  markClosed(prevSuccessEnvId);
}
// On task failure:
await browserMod.stopEnv(failedEnvId);  // close immediately
```

**Never** close on captcha detection. Keep window open for human intervention.

---

## alert.js — Windows blocking alert

`alertAndWait({ title, message, envId, check, timeoutMs })`:
1. Sends Hermes/Telegram alert if `HERMES_TARGET` env var configured
2. Plays Windows `MessageBeep` 3×
3. Shows `msg.exe` notification + PowerShell MessageBox (async, doesn't block Node)
4. Polls `check()` every 3s and `data/continue-<envId>.flag` file
5. Returns when check passes OR flag file created; throws after `timeoutMs`

Touch `data/continue-<envId>.flag` to force-unblock from terminal.

**Verified working (Win11)**: All three layers (rundll32 beep, msg.exe popup, PowerShell MessageBox) produce sound/popup. `HERMES_TARGET` env var must be set to `telegram:<chat_id>` for remote Telegram alerts — without it, only local sound+popup fire (easy to miss if not at the desk).

### Timeout strategy: context-dependent timeouts

**Don't** set long timeouts (e.g. 6 hours) hoping a human will show up. Also **don't** set 1-minute timeouts for captcha — human needs to: notice popup → switch to ADS browser → solve captcha → click continue in dashboard. 1 minute is too short.

- **Captcha**: **5 minutes** — proven minimum for human intervention cycle. Set in BOTH flow.js (`alertAndWait`) AND runner.js (`runner_alertAndTakeover`)
- **Other alerts** (error pages, form stuck): 1 minute — auto-recoverable or not worth waiting

**CRITICAL — the wait-for-human time MUST be subtracted from any enclosing wall-clock deadline.** If `microsoftLogin()` has `const loginDeadline = Date.now() + 120000` and captcha takes 90s of human time, the next `Date.now() > loginDeadline` check immediately throws STAGE_STUCK → entire browser killed → progress lost. Symptom looks like "state lost on browser restart" but the real bug is the parent flow killed itself **because the human's takeover time was charged against the autonomous-flow deadline**. Always extend the deadline by the actual wait duration:

```js
let loginDeadline = Date.now() + 120000;  // 'let' not 'const'
// ... before alertAndWait:
const t0 = Date.now();
await alertAndWait({ ... });
loginDeadline += Date.now() - t0;   // pause the deadline during human takeover
```

Same rule applies to any `form1FilledAt`-style "stuck since" timestamp used in step loops — push the timestamp forward by the takeover duration. See `references/timeout-and-unattended-patterns.md` Problem 9 for the full pattern and a diagnostic anti-checklist.

```js
// runner_alertAndTakeover accepts opts.timeoutMs
async function runner_alertAndTakeover(page, envId, reason, opts = {}) {
  const timeout = opts.timeoutMs || 60 * 1000;  // default 1 min
  // ...
}

// Captcha gets 5 minutes
await runner_alertAndTakeover(page, envId, 'captcha', { timeoutMs: 5 * 60 * 1000 });
// Other alerts keep 1 minute default
await runner_alertAndTakeover(page, envId, 'error_page');
```

After timeout: **do NOT immediately mark as failed** — use the unattended retry pattern (see "Unattended captcha retry" section above). Close window → reopen → try once more. Only mark failed after the second captcha timeout. The failure tracking system then handles morning recovery:

1. **Record the failure** — `progress.addFailed(envId, reason, { browser, note })` with full context
2. **Dashboard retry** — operator can click "retry single" or "retry all failed" when ready
3. **Manual mark-success** — some envIds fail because of restarts showing unexpected pages, but are actually done. Dashboard has a "mark success" button.

This lets the automation run unattended overnight — failures collect in a queue and get batch-retried the next morning.

### CRITICAL: Post-captcha flow resumption

**Bug pattern**: Human solves captcha → clicks "continue" → runner does `continue` back to main loop → `detectStage()` sees form1 → nobody clicks submit → 60s timeout → STAGE_STUCK → window closes → reopens → may hit captcha again → infinite loop increasing risk.

**Root cause**: After `alertAndWait` returns, the runner just went back to the detect-stage loop without re-engaging the form. The form is sitting there with captcha solved but the submit button unclicked.

**Fix**: After captcha alert resolves, immediately detect the current stage and take appropriate action:

```js
// In runner's captcha handling block:
await runner_alertAndTakeover(page, envId, 'captcha', { timeoutMs: 5 * 60 * 1000 });
errorRetries = 0;

// v2: Post-captcha flow resumption — DO NOT just continue
await sleep(1500);
const postStage = await detectStage(page);
console.log(`[runner] captcha resolved, stage=${postStage}`);

if (postStage === 'form3') {
  return finalizeReachedPayment(page, envId, t0);
}
if (postStage === 'form1') {
  // Still on form1 → re-fill and submit
  await flow.runForm1Fill(page, profile, envId);
} else if (postStage === 'form2' && !everSeenForm2) {
  // Advanced to form2 → fill address
  everSeenForm2 = true;
  await flow.runForm2Fill(page, profile, envId);
}
form1FilledAt = Date.now();
continue;
```

**Key insight**: The runner's state machine must treat captcha resolution as a "page state may have changed" event, not a no-op. Always re-detect and re-engage after any human intervention.

---

## Failure tracking + retry queue pattern

For multi-environment automation runners, implement a failure management system:

### Architecture

```
progress.js   → failedTasks[] array (in-memory, exposed via snapshot)
                addFailed(envId, reason, extra)
                removeFailed(envId)
                markSuccess(envId)

retry-queue.js → in-memory FIFO queue (same process as runner)
                push(envId, browser) — deduplicating
                shift() → next item
                length() / list() / remove()

dashboard.js  → HTTP endpoints:
                POST /api/mark-success { envId }
                POST /api/retry { envId }
                POST /api/retry-all

runner.js     → after finishing main task list, enter retry-queue drain loop
                → also checks retry-queue during 30s polling wait
```

### Key design decisions

- **Same-process shared memory** — dashboard HTTP server and runner main loop share the Node.js event loop, so retry-queue is a simple module-level array. No file-based IPC needed.
- **Deduplication** — both `failedTasks` and `retryQueue` deduplicate by envId. Re-adding overwrites.
- **Dashboard buttons per failed env** — each row gets "🔁 Retry" and "✅ Mark Success" buttons. Global "🔁 Retry All Failed" button at top.
- **Retry results feed back** — if retry succeeds → removed from failed list. If retry fails again → re-added to failed list with updated reason/timestamp.
- **runtime.json tracking** — retry results get `isRetry: true` flag in results array for post-analysis.

### v2 Dashboard: full runner control panel (port 7777)

The v2 dashboard evolved from a simple status page into a full runner control panel rivaling FormHelper's Azure tab. It's a single-file embedded HTTP server (`src/dashboard.js`, ~27KB) with dark theme and 5-second auto-refresh.

**Full API surface:**
- `GET /` — complete HTML dashboard (dark theme, auto-refresh)
- `GET /api/state` — JSON: progress snapshot + tasks + runtime + failed + retryQueue
- `POST /api/continue` / `/api/takeover` — unblock captcha/manual alerts
- `POST /api/mark-success` / `/api/retry` / `/api/retry-all` — failure management
- `POST /api/gen-tasks { from, to, browser }` — generate tasks.json (range of envIds)
- `POST /api/reset-runtime` — clear runtime.json for fresh start
- `POST /api/set-index { index }` — jump to any task position
- `POST /api/stop-runner` — graceful `process.exit(0)`

**UI sections (top to bottom):**
1. Header with v2 branding + runner status dot
2. Progress bar with completion % and success rate
3. Current task detail (envId, stage, elapsed time, blocking indicator)
4. Control buttons (continue / takeover / stop runner)
5. Task list with color-coded status icons + per-task ▶ start-from buttons
6. Task generator form (from/to envId + browser selector)
7. Failed environments table with retry/mark-success per row + retry-all
8. History timeline (reverse chronological, last 20 results)

**Architectural note:** v2 dashboard lives inside the runner process. No separate Electron shell, no IPC, no child-process management. The tradeoff: can't "start" the runner from dashboard (runner IS the host), but everything else works. For account management and company library, FormHelper remains the tool.

### FormHelper offline fallback (runtime.json direct write)

When the runner isn't running, dashboard API endpoints (mark-success, retry) return errors. FormHelper needs a fallback that writes directly to `runtime.json`:

```js
// In azure-tab.js — mark-success button handler:
el.querySelectorAll(".az-task-mark-ok").forEach((btn) => {
  btn.addEventListener("click", async (e) => {
    e.stopPropagation();
    const envId = btn.dataset.envid;
    if (!confirm("确认标记 " + envId + " 为成功？")) return;
    // Try dashboard API first
    const r = await window.api.azureMarkSuccess(envId);
    if (r && r.ok) { refresh(); return; }
    // Fallback: direct runtime.json edit
    const rt = await window.api.azureRuntime();
    if (rt && rt.results) {
      for (const res of rt.results) {
        if (String(res.envId) === String(envId)) {
          res.status = "reached_payment";
          res.reason = "manual_mark";
        }
      }
      await window.api.azureSaveRuntime(rt);
      refresh();
    }
  });
});
```

This requires an `azure:saveRuntime` IPC handler in main.js:
```js
ipcMain.handle("azure:saveRuntime", (_e, rt) => {
  try {
    const fp = azurePath("config/runtime.json");
    fs.writeFileSync(fp, JSON.stringify(rt, null, 2), "utf8");
    return { ok: true };
  } catch (e) { return { ok: false, error: e.message }; }
});
```

And exposed via preload.js:
```js
azureSaveRuntime: (rt) => ipcRenderer.invoke("azure:saveRuntime", rt),
```

**Why this matters**: Users often notice failures after the runner has finished and been stopped. Without offline fallback, they'd have to manually edit JSON files or restart the runner just to mark a success.

### Task list inline action buttons

Don't only put mark-success/retry buttons in a separate "failed management" panel — users expect to see them **on each task row** in the task list. A task showing ❌ with no action button nearby is frustrating.

```js
// In renderTaskList — add ✅ button next to each failed task
if (r && r.status === "failed") {
  html += `<button class="az-task-mark-ok" data-envid="${esc(t.envId)}" title="标记为成功">✅</button>`;
}
```

Use event delegation on the task list container for click handlers, with the same API-first + runtime.json-fallback pattern.

### Runner main loop integration

```js
// After main task list completes:
while (retryQueue.length() > 0) {
  const item = retryQueue.shift();
  progress.removeFailed(item.envId);
  const result = await runOne(item.envId, { browser: item.browser });
  if (result.status !== 'reached_payment') {
    progress.addFailed(item.envId, result.reason, { browser: item.browser });
  }
}
// Then 30s poll for new tasks OR new retry items
```

---

## Stage detection in SPA

SPA keeps old form nodes in DOM even after navigating to next form. Do NOT use selector presence alone:

```js
// ❌ WRONG
const onForm2 = await page.$('#pidlInput_postal_code') !== null;

// ✅ CORRECT — use visible text content
const stage = await page.evaluate(() => {
  const txt = document.body?.innerText || '';
  if (/captcha|reCAPTCHA/.test(txt)) return 'captcha';
  if (/ステップ\s*3\s*\/\s*4.*支払い/.test(txt)) return 'form3';
  if (/ステップ\s*2\s*\/\s*4/.test(txt)) return 'form2';
  if (/ステップ\s*1\s*\/\s*4|プロフィール情報/.test(txt)) return 'form1';
  return 'unknown';
});
```

---

## React radio buttons: isTrusted requirement

**Root cause**: React's synthetic event system only processes events with `isTrusted: true`. Events created via `new Event()` or `dispatchEvent()` in `page.evaluate()` always have `isTrusted: false`. So even though `radio.checked = true` changes the DOM, React's internal state doesn't update, and the next render resets it.

**Solution**: Use Puppeteer's CDP-level click (`page.click()` / `clickHuman()`) which produces real browser events with `isTrusted: true`.

```js
async function selectUsageIndividual(page) {
  const labelSel = 'label[for="account-usage-purpose-personal"]';
  const radioSel = '#account-usage-purpose-personal';

  for (let attempt = 1; attempt <= 3; attempt++) {
    // Real mouse click on label (largest click target, also toggles radio)
    try {
      await page.waitForSelector(labelSel, { timeout: 5000 });
      await clickHuman(page, labelSel);
      await sleep(randInt(600, 1200));
    } catch {
      // Label not found → click radio directly
      try {
        await page.waitForSelector(radioSel, { timeout: 3000 });
        await clickHuman(page, radioSel);
        await sleep(randInt(600, 1200));
      } catch {}
    }

    // Verify React actually registered it
    const checked = await page.evaluate(() => {
      const r = document.querySelector('#account-usage-purpose-personal');
      return r && r.checked;
    });
    if (checked) return { ok: true, via: 'click', attempt };

    // Fallback: setter + dispatchEvent (may work on some React versions)
    console.warn(`[flow] radio attempt ${attempt} not checked, setter fallback + retry`);
    await page.evaluate(() => {
      const radio = document.querySelector('#account-usage-purpose-personal');
      if (!radio) return;
      const desc = Object.getOwnPropertyDescriptor(Object.getPrototypeOf(radio), 'checked');
      if (desc && desc.set) desc.set.call(radio, true);
      else radio.checked = true;
      radio.dispatchEvent(new Event('input', { bubbles: true }));
      radio.dispatchEvent(new Event('change', { bubbles: true }));
    });
    await sleep(randInt(500, 1000));
  }

  // Final fallback: [role="radio"] text match
  // ... (find visible element matching /個人使用|個人/, scrollIntoView, click)
  return null;
}
```

**General rule**: Any React-controlled form element (radio, checkbox, toggle) that doesn't respond to automation → suspect `isTrusted` filtering. Switch from `page.evaluate(() => el.click())` to `page.click(selector)` or `clickHuman(page, selector)`.

### Click-then-verify anti-pattern

**Anti-pattern**: Click a button → return immediately → let the calling code `waitForStageChange(40s)` → discover it didn't work → try again → wait another 40s. Wastes 80+ seconds per cycle.

**Correct pattern**: Click → wait 3s → verify the expected DOM change happened → if not, try next method immediately. The click function owns verification, not the caller.

This applies to **any SPA button click** where the expected result is page navigation or content change:
- KMSI "はい" → verify `サインインの状態を維持` text disappears
- Radio "個人" → verify `radio.checked === true`
- "次へ" login button → verify login stage changes
- Form submit → verify step indicator changes

```js
// Generic click-then-verify template
async function clickWithVerify(page, methods, verifyFn, label) {
  for (const method of methods) {
    try {
      await method.fn();
      await sleep(3000);
      if (await verifyFn()) return; // success
      console.log(`${label}: ${method.name} clicked but no effect, trying next`);
    } catch {}
  }
  throw Object.assign(new Error(`${label}: all methods failed`), { code: 'STAGE_STUCK' });
}
```

---

## Unattended captcha retry (sleep mode)

For truly unattended operation (overnight runs), captcha timeout should NOT immediately fail the task. Instead:

```
CAPTCHA detected → alert (sound + popup + Telegram)
    ↓ wait 5 min
Human solved it? → continue flow normally
    ↓ timeout (nobody there)
Close window → stop env → wait 3s → reopen from scratch
    ↓ re-login succeeds
Another CAPTCHA? → alert again → wait 5 min
    ↓ timeout again
Mark failed (reason: captcha_unattended_timeout) → move to next envId
```

Implementation in runner.js:

```js
const MAX_CAPTCHA_RETRIES = 1; // reopen once, fail on second captcha
let captchaTimeouts = 0;       // counter persists across attempts for same envId

// In the captcha handling block:
if (stage === 'captcha') {
  try {
    await runner_alertAndTakeover(page, envId, 'captcha', { timeoutMs: 5 * 60 * 1000 });
    // Human solved it — continue normally
  } catch (alertErr) {
    // Timeout — nobody there
    captchaTimeouts++;
    if (captchaTimeouts <= MAX_CAPTCHA_RETRIES) {
      console.log(`captcha timeout ${captchaTimeouts}/${MAX_CAPTCHA_RETRIES}, reopening`);
      await browser?.disconnect();
      await ads.stopEnv(userId);
      await sleep(3000);
      continue; // back to top of retry loop — fresh browser session
    }
    // Exhausted retries
    return { status: 'failed', reason: 'captcha_unattended_timeout' };
  }
}

// Same pattern for flow.js captcha_skip errors in catch block:
if (e.message === 'captcha_skip') {
  captchaTimeouts++;
  if (captchaTimeouts <= MAX_CAPTCHA_RETRIES) {
    // close + reopen
    continue;
  }
  return { status: 'failed', reason: 'captcha_unattended_timeout' };
}
```

**Key design choices:**
- `captchaTimeouts` counter is per-envId (declared before the retry loop, persists across attempts)
- Only 1 retry (not infinite) — if the same envId hits captcha twice, it's likely IP/fingerprint flagged
- Hard reset (stopEnv) on captcha retry — need fresh browser fingerprint
- Failure reason `captcha_unattended_timeout` is distinct from `captcha_alert_timeout` for dashboard filtering

---

## Post-login navigation stall (KMSI → Azure redirect)

**Bug pattern**: KMSI "はい" button is clicked successfully, the `サインインの状態を維持` text disappears, but the page hangs during the redirect from `login.microsoftonline.com` → `signup.azure.com`. The `detectLoginStage` returns `unknown`, and the old 40s timeout kills the window — even though the click worked and the redirect just needs more time (or a fresh IP).

**Root cause**: The redirect from Microsoft login to Azure signup goes through several server-side hops. With residential proxies, this redirect can be slow (30-90s) or completely stall. The old code treated all `unknown` stages the same — 40s timeout → STAGE_STUCK → window killed. But KMSI-after-click is fundamentally different from "page didn't load at all."

**User's manual workflow**: "换IP重新开窗口" — never reload, always switch IP and reopen. Refreshing a stalled redirect page is useless.

**Fix — domain-aware unknown handler**:

```js
case 'unknown': {
  const curUrl = page.url();
  const onLoginDomain = /login\.(microsoftonline|live|microsoft)\.com/.test(curUrl);
  const onAzureDomain = /signup\.azure\.com|portal\.azure\.com/.test(curUrl);

  // 1. Still on login domain = redirect in progress → wait up to 90s
  if (onLoginDomain && unknownElapsed < 90000) {
    if (unknownElapsed > 10000 && unknownElapsed % 10000 < 2500) {
      console.log(`[flow] URL still on login domain, waiting for redirect (${Math.round(unknownElapsed / 1000)}s)`);
    }
    await sleep(2000);
    break;
  }

  // 2. On Azure domain but blank → DON'T reload (useless), wait 40s then IP-stuck
  if (onAzureDomain && unknownElapsed > 40000) {
    throw Object.assign(
      new Error(`Azure page blank > 40s, IP stuck`),
      { code: 'STAGE_STUCK', hint: 'ip_stuck' }
    );
  }
  if (onAzureDomain) {
    await sleep(2000);
    break;
  }

  // 3. Unknown domain or login domain > 90s → generic timeout at 60s
  if (unknownElapsed > 60000) {
    throw Object.assign(new Error(`unknown stage > 60s`), { code: 'STAGE_STUCK' });
  }
  await sleep(2000);
  break;
}
```

**Three key rules**:
1. **Login domain + unknown = redirect in progress** — give it 90 seconds, not 40
2. **Azure domain + blank = IP is stuck** — don't reload (reload never fixes this), throw `ip_stuck` so runner does hard reset with new proxy
3. **Reload is useless for stalled redirects** — user confirmed from manual experience. The fix is always: close window → switch IP → reopen

**Runner side**: The `ip_stuck` hint triggers `hardReset = true` (same as dead IP probe), so the runner closes the browser environment and reopens with a new proxy session.

---

## Persisted `last_url` poisoning by Chromium session restore (user-data-dir mode)

When a Puppeteer/CDP automation uses `--user-data-dir=<path>` so the same Chromium profile is reused across runs (cookie persistence, fingerprint stability), and the runner persists `account.last_url` so the next manual "open browser" click resumes where the operator left off, there is a **two-level bug** that produces `AADSTS900144: The request body must contain the following parameter: 'client_id'` (or similar OAuth single-use-token failures) on next open.

### Level 1 — over-broad URL whitelist persists OAuth redirect URLs

A naive "save the current tab's URL every 10s" emitter that only excludes `about:`, `chrome:`, `devtools:` will happily save URLs like:

```
https://login.microsoftonline.com/common/oauth2/authorize?client_id=...&state=...&nonce=...&code_challenge=...
```

These URLs are **single-use** — the `client_id` / `state` / `code_challenge` parameters are bound to one in-flight login session that has long since expired. Restoring this URL next session returns AADSTS900144. The fix is a strict **domain whitelist**, not a blacklist:

```js
function isRestorableUrl(u) {
  if (!u) return false;
  if (u.startsWith('about:') || u.startsWith('chrome:') || u.startsWith('devtools:')) return false;
  try {
    const host = new URL(u).hostname.toLowerCase();
    // Whitelist: pages the user reaches AFTER auth is complete
    return /(^|\.)azure\.microsoft\.com$|(^|\.)signup\.azure\.com$|(^|\.)portal\.azure\.com$/.test(host);
  } catch (_) { return false; }
}
```

**Rule**: only persist URLs from **post-auth product domains** (signup / portal / app). Never persist anything from `login.microsoftonline.com`, `login.live.com`, `login.microsoft.com`, `accounts.google.com`, or any OAuth IdP. Apply the same filter at every emission site: 10s heartbeat, `gracefulShutdown`, terminal-state finalize.

### Level 2 — Chromium's own session restore re-opens the failed tab

Even after Level 1 is fixed, the bug reproduces on the very first open after a previous run that was killed with `taskkill /F` / `SIGKILL`. Symptom: the operator sees the "ページを復元しました / Chromium did not shut down correctly" toast in the upper-right, and the page loads straight to AADSTS900144. This is **Chromium's built-in tab restore**, completely independent of your `last_url` logic — it reads the profile's `Default/Preferences` file at startup and reopens whatever tabs were live, including the failed OAuth redirect.

**Fix**: before every launch, rewrite the profile's Preferences to claim a clean exit:

```js
if (USER_DATA_DIR) {
  try {
    const fsx = await import('fs');
    const px = await import('path');
    const prefPath = px.join(USER_DATA_DIR, 'Default', 'Preferences');
    if (fsx.existsSync(prefPath)) {
      const prefs = JSON.parse(fsx.readFileSync(prefPath, 'utf8'));
      prefs.profile = prefs.profile || {};
      prefs.profile.exit_type = 'Normal';
      prefs.profile.exited_cleanly = true;
      // restore_on_startup = 5 → "New Tab Page" (never restore tabs)
      // 1 = restore last session, 4 = open specific URLs, 5 = NTP
      prefs.session = prefs.session || {};
      prefs.session.restore_on_startup = 5;
      fsx.writeFileSync(prefPath, JSON.stringify(prefs), 'utf8');
    }
  } catch (_) { /* non-fatal */ }
}
```

**Why both fixes are needed**: Level 1 stops *your code* from poisoning future opens. Level 2 stops *Chromium itself* from restoring poisoned tabs that pre-date the fix (or that were captured by the browser before your filter ran). Without Level 2 you still see the bug on the first open after upgrading; without Level 1 a fresh session can re-poison itself within minutes.

**Sanity-check existing data after deploying Level 1**: scan the persisted store and clear any `last_url` that no longer passes `isRestorableUrl`. One-liner:

```js
const data = store.loadProxies(dataDir);
for (const a of data.accounts || []) {
  if (a.last_url && !isRestorableUrl(a.last_url)) a.last_url = '';
}
store.saveProxies(dataDir, data);
```

If this scan returns 0 cleared entries on a system that's still reproducing AADSTS900144, the culprit is Level 2 (Chromium's own restore), not your filter.

---

## Multi-source alarm events — wire ALL backend paths, not just one

When the same logical event (captcha detected, takeover needed, payment 3DS prompt, etc.) can be raised from multiple code locations, and the renderer subscribes to a dedicated event channel for alarming, **every emission site must broadcast the channel** — not just the canonical one.

**Real-session bug**: A captcha alarm system used `broadcast('azure:captcha', ...)` from `azure/index.js:blockOnCaptcha` (the form-state-machine path) but the **other two captcha detection sites** — `azure/flow.js:microsoftLogin` (login-stage captcha) and `azure/flow.js:runForm2Fill` (address-validation captcha) — used `alertAndWait` directly without the prefix broadcast. Both still showed a status badge update (via `azure:blocking`), but **no beep, no title flip, no notification**. Operator's report: "captcha detected but no alarm" — and that was correct: the UI saw `azure:blocking` and showed the badge, but never saw the dedicated `azure:captcha` event, so `startCaptchaAlarm` was never called.

**Root cause symptom**: an event channel that's used for alarming is implemented at one site but the codebase has 2+ other sites that detect the same condition through different code paths.

**Generalization — any multi-channel renderer event has this risk**:

| Channel split that broke this session | Generic shape |
|---|---|
| `azure:blocking` (UI badge) + `azure:captcha` (alarm) | Status channel + alarm channel |
| `azure:runState` (table cell) + `azure:result` (toast) | State channel + result channel |
| `progress.update` (dashboard) + alarm | Telemetry + interactive alert |

The bug pattern: **only the alarm channel is missed**, because the status channel is implicit (`emitProgress` always fires) and the developer assumes "if status updated, alarm fires." But the alarm is a separate broadcast — and `alertAndWait` (the generic blocking helper) doesn't know whether the blocking reason is a captcha or a phone-verify or a 3DS prompt.

### Two viable fixes — prefer Fix 2 (downstream owns the channel)

**Fix 1 (fragile)**: Add `broadcast('azure:captcha', {...})` at every captcha-detect site. Pitfall: any new detection site added later silently re-introduces the bug. Forgetting one site is invisible to tests.

**Fix 2 (durable)**: Make the **generic alarm helper** (`alertAndWait`) auto-detect captcha-class blocks from the title/message and broadcast the alarm channel itself. Now any future detection site that calls `alertAndWait` gets the alarm for free.

```js
async function alertAndWait({ title, message, envId, check, timeoutMs }) {
  const id = String(envId);
  // ★ classify by title/message; broadcast alarm-class channel automatically
  const isCaptcha = /captcha|人机|アカウントの保護|ロボット/i.test(
    String(title) + ' ' + String(message)
  );

  if (isCaptcha) {
    // pull screenshot path out of message if present
    const m = String(message).match(/截图[:：]\s*(.+\.png)/);
    notifyRenderer('azure:captcha', {
      envId: id,
      reason: title || 'captcha',
      screenshot: m ? m[1].trim() : '',
      ts: Date.now(),
    });
  }

  notifyRenderer('azure:blocking', { envId: id, title, message, timeoutMs, startedAt: Date.now() });

  // ... wait loop ...

  // On EVERY exit path (user-flag, check-success, timeout), pair the cleared event
  if (isCaptcha) notifyRenderer('azure:captcha-cleared', { envId: id, ts: Date.now() });
}
```

Now `microsoftLogin`, `runForm2Fill`, `blockOnCaptcha`, and any future captcha-detect call site all get the alarm just by calling `alertAndWait({ title: '... captcha ...', ... })`. The classification heuristic only has to live in one file.

### Verification checklist when adding/auditing alarm channels

When you add a new renderer-side alarm (sound + notification + animation), verify all three:

1. **Backend emit sites** — `grep -rn "broadcast.*<channel>\|notifyRenderer.*<channel>" backend/` — confirm every condition that should alarm also calls the channel. If multiple files emit, prefer pulling the broadcast into the shared helper they all call.
2. **Cleared-event symmetry** — for every code path that emits the start event, there must be a paired clear event on completion, timeout, AND error. Missing the error path leaves the operator with a beeping app after a backend exception.
3. **Renderer subscription** — `grep -n "on<EventName>\|<channel>" preload.js renderer/*.js` — confirm the renderer actually subscribes. `preload.js` must export the `onXxx` API; renderer must bind it on app start, not lazily.

### When the operator says "I didn't hear an alarm"

Run a quick three-question disambiguation before patching anything (echoes the "ask, don't guess" pattern at the top of this skill):

```
1. UI badge changed to the captcha-pulse red? (Yes = backend reached `emitProgress('captcha', ...)`)
2. Window title flashed `🛑 ...`?               (Yes = renderer received `azure:captcha`)
3. System notification popped?                   (Yes = renderer's `Notification` path ran)
```

| 1 | 2 | 3 | Diagnosis |
|---|---|---|-----------|
| ✓ | ✗ | ✗ | Backend emits status but NOT the alarm channel → wire the alarm at this detection site (or pull it into the shared helper) |
| ✗ | ✗ | ✗ | Captcha not detected at all → check the detector regex and which code path the page is on |
| ✓ | ✓ | ✗ | `Notification.permission !== 'granted'` → request on app start, not lazily |
| ✓ | ✓ | ✓ but no sound | `AudioContext` user-gesture lockout → see `references/captcha-alarm-renderer-ux.md` lazy-init mitigation |

---

## "Notation/state lost on restart" can mean three different things — disambiguate

When the operator reports "the registration state disappeared" after an Electron restart or a long pause, there are **at least three distinct causes** that look identical from the UI (status cell showing `—` instead of the previous ✅/❌/⏳). Patching the wrong one wastes a debugging round.

| What's happening on disk | What's happening in memory | UI shows | Real cause |
|---|---|---|---|
| `azure_status = 'running'`, no recent `emitProgress` | `RUN_STATE.get(name)` is empty (Electron restarted) | should be ⚠ `interrupted`, sometimes blank if `snapshotAllRunState` ran before persistence layer wired up | **Orphaned running record** — finalizeCtrl never ran (kill -9, Electron crash). `snapshotAllRunState` must convert `running` + no in-memory entry → `interrupted`. |
| `azure_status = ''`, but `events[]` has a `reached_payment` screenshot | N/A (run finished pre-feature) | `—` (no badge) | **Historical run pre-dates the persistence feature.** Not a bug — these accounts ran successfully before you added `azure_status` writes. Either backfill from events or accept the gap. |
| `azure_status = 'success'` is on disk | `RUN_STATE` is empty (Electron just started) | `—` for a frame, then ✅ | **UI fetched runState before persistence layer was injected** — `_dataDir` was still `null` when `snapshotAllRunState` ran. Re-call `azureGetRunState` after `ensureEnv` completes, or block the IPC handler until ensureEnv finishes. |

**Diagnostic — always run this script BEFORE patching anything**:

```js
node -e "
const store = require('./proxy/store');
const d = store.loadProxies(process.cwd());
for (const a of (d.accounts || [])) {
  if (!a.azure_status && !(a.events||[]).length) continue;
  const lastEvent = (a.events||[]).slice(-1)[0];
  console.log(a.name, '| status=', JSON.stringify(a.azure_status),
    '| stage=', JSON.stringify(a.azure_stage),
    '| events=', (a.events||[]).length,
    '| lastEvent=', lastEvent && (lastEvent.kind||lastEvent.type),
    '| finished_at=', a.azure_finished_at);
}
"
```

Now you can see for each account: is the disk record `running` (→ orphan), empty with old events (→ historical), or `success` (→ UI timing / persistence-injection bug)?

**Rule — do NOT propose a fix until the operator confirms which row of the table matches.** Echo the symptom table back ("which of these three is what you're seeing for account X?"). The cost of asking is 30 seconds; the cost of fixing the wrong row is a wasted retest round.

This pattern is the same energy as the "stuck again, V2 老毛病" disambiguation table at the top of this skill — long-running state-bearing systems have many failure modes that all manifest as "the UI doesn't show what I expect." Build cheap disambiguation into the loop.

---

## Detector regex pitfalls — ambiguous keywords that also appear in product UI

When writing a `detectStage` / `hasCaptcha` regex, every keyword you add becomes a **false-positive risk** if it also appears in the product's own UI text (marketing copy, security panel labels, sidebar headers). The classic symptom: code reports `hasCaptcha=true` on a page that has no captcha at all, so the runner immediately throws STAGE_STUCK or pops a useless alarm. Or worse — the opposite, where the operator stares at a page screaming "captcha detected" while the detector calmly returns `false` because the **actually-triggered captcha** uses a different phrase than the one you keyed on.

**Real-session bug**: An Azure signup detector used `アカウントの保護` (account protection) as a captcha keyword. But Azure's signup-page **product sidebar** also contains the literal phrase `アカウントの保護` next to a shield icon as a **marketing bullet** ("we protect your account"). Detector flagged every fresh page load as captcha → alarm fired wrongly OR the operator saw "captcha not detected" because the actual captcha (`ロボットでないことを証明`) was the matching key while the operator thought he'd already passed it (sidebar text still showing). Either way, the bot loops on garbage.

**Rules for captcha / sensitive-stage keyword lists**:

1. **Strongly prefer task-imperative phrasings**: `ロボットでないことを証明してください` (prove you're not a robot), `クイズに回答してください` (answer the quiz), `本人確認` (identity verification), `verify you are human`. These show up only when the captcha actually runs.
2. **Reject vague nouns** that the product itself uses as marketing/security copy: `アカウントの保護`, `セキュリティ`, `保護`, `安全`, `verification`, `security check` (without an imperative verb). They produce false positives on the landing/login/dashboard pages.
3. **Brand names of captcha vendors are safe** because the product won't reference them in flavor text: `reCAPTCHA`, `hcaptcha`, `Arkose`, `FunCaptcha`, `Cloudflare Turnstile`.
4. **Anchor on the captcha widget's iframe origin, not body text, when possible**: `document.querySelector('iframe[src*="recaptcha"], iframe[src*="hcaptcha"], iframe[src*="arkoselabs"]')`. Iframe checks have zero false-positive risk against product copy. Combine with text detection as a backup.
5. **Centralize the regex in ONE constant exported from a helper module.** This session had **11 separate copies** of the captcha regex across `flow.js` + `index.js` (login phase, form1 phase, form2 phase, runner-loop, recovery, etc.). When one detector site's regex is wrong, the bug only manifests in that one stage and is hard to attribute. Refactor: `const CAPTCHA_RE = /ロボットでないことを証明|クイズに.*回答|本人確認|本当に人間ですか|reCAPTCHA|hcaptcha|verify you are human/;` exported from `azure/captcha-keywords.js`, imported everywhere.
6. **Test the regex against a known clean page before shipping.** A 30-second test: `page.goto(productHomepage); console.log(CAPTCHA_RE.test(await page.evaluate(()=>document.body.innerText)));` should print `false`. If it prints `true`, your keyword list overlaps product copy.

**General principle**: a captcha keyword should be **a sentence the user must obey to proceed**, not a noun the marketing team chose to put on the page. Imperatives don't appear in product UI; nouns do.

---

## "Button not enabled within 30s" → wait + alarm, NOT close-window-reopen

A common reflex for SPA form automation: "I filled the form, then I poll for the submit button to become `enabled`. If it doesn't enable within 30s, the page is stuck → throw STAGE_STUCK → outer retry closes the browser and reopens." This pattern is **wrong** on hardened sites with backend-validated forms, and the cost is brutal.

**Real-session bug**: `runForm1Fill` polled `#mobile-navigation-next` for `disabled === false` over 30 iterations × 1s = 30s. Some accounts had slow backend validation (long email domain, suspect IP region, fresh proxy session) and took 40-60s. Code hit 30s → throw `form1 提交后 30 秒未响应` with `code: 'STAGE_STUCK'` → runner caught it → `browser.disconnect()` + `stopEnv()` → 3s sleep → relaunch + re-login + re-fill. **Total cost of the false alarm: ~3 minutes of work thrown away, often re-encountering captcha on the second attempt.** Operator's perception: "the bot keeps restarting itself even though everything was filling correctly."

**The diagnostic is brutal**: the *correct* state was reached by the second attempt eventually (just took longer than 30s), so logs look like "intermittent flake" instead of "design bug". Operators report "form1 sometimes works, sometimes doesn't" and chase phantom React quirks for weeks.

### The four outcomes of a slow submit-button check

When a submit button doesn't enable within the expected window, there are **four** possible reasons. Three of them want you to **keep waiting**, only one wants STAGE_STUCK:

| Outcome | What's true | Right action |
|---|---|---|
| **A. Backend slow** | Form is valid, backend validation is just slow (proxy region, long email, signup site under load) | Keep waiting — extend timeout 2-4x or treat as `pending`, alarm operator at 60s for visibility |
| **B. Real captcha** | Backend returned "needs captcha" — captcha widget appeared | Branch to captcha alarm path (`alertAndWait`) — do not reload |
| **C. Field validation error** | One of the filled fields is rejected (typo, format, blocked domain). Error message appears inline. | Detect the inline error message, log it, throw a distinct `FIELD_REJECTED` code — outer code may relaunch with different data, NOT just retry blind |
| **D. Page genuinely dead** | Network actually broken, browser crashed, IP blackholed | STAGE_STUCK + close window + new proxy. This is the rare case. |

**The 30s-timeout-then-STAGE_STUCK pattern treats every outcome as D.** That's the bug. On hardened SPAs, A is by far the most common.

### Correct pattern

```js
// 1. Initial poll — generous timeout, allow advance OR captcha as escape hatches
let outcome = 'pending';
for (let i = 0; i < 60; i++) {        // 60s, not 30s
  await sleep(1000);
  const s = await page.evaluate(() => {
    const btn = document.querySelector('#submit-button');
    const txt = document.body?.innerText || '';
    return {
      btnDisabled: btn ? btn.disabled : true,
      btnGone:     !btn,
      hasCaptcha:  CAPTCHA_RE.test(txt),
      onNextStep:  /ステップ\s*2/.test(txt),
      fieldError:  /入力に問題があります|invalid|エラー/.test(txt),
    };
  }).catch(() => null);
  if (!s) continue;
  if (s.onNextStep || s.btnGone) { outcome = 'advanced'; break; }
  if (s.hasCaptcha)              { outcome = 'captcha';  break; }
  if (s.fieldError)              { outcome = 'rejected'; break; }
  if (!s.btnDisabled)            { outcome = 'enabled';  break; }
}

// 2. If still pending after 60s — DO NOT throw STAGE_STUCK
//    Alarm the operator (5-min wait) just like captcha
if (outcome === 'pending') {
  await alertAndWait({
    title: `envId=${envId} form1 backend slow`,
    message: `表单提交后 60 秒「次へ」按钮仍未启用,可能是后端校验慢或风控. 请检查浏览器, 通过后点继续.`,
    envId,
    check: async () => {
      const s = await page.evaluate(() => {
        const btn = document.querySelector('#submit-button');
        const txt = document.body?.innerText || '';
        return {
          ok: (btn && !btn.disabled) || /ステップ\s*2/.test(txt),
        };
      }).catch(() => null);
      return s && s.ok;
    },
    timeoutMs: 5 * 60 * 1000,    // human gets 5 minutes to decide
  });
  outcome = 'enabled';
}

// 3. Now branch on real outcomes
if (outcome === 'captcha')   /* alarm + wait, see captcha section */;
if (outcome === 'rejected')  /* log inline error, throw FIELD_REJECTED */;
if (outcome === 'enabled')   /* click submit, proceed */;
if (outcome === 'advanced')  /* already on next step, skip submit */;
```

### Why "alarm" is better than "close window and reopen"

- The form was filled **correctly** (verified by post-fill value check) and the captcha you'll trigger on reopen is **the cost of being wrong**. Throwing away a valid filled state to retry from scratch is the most expensive wrong move.
- The operator is sitting there anyway during overnight runs — if the bot stalls 60s on the submit button, the operator has 5 minutes to look, decide, and click ▶继续 or press the submit button manually. Either way the registration completes.
- Captcha and "backend slow" both need a human-in-the-loop fallback. Use the **same** alarm channel for both, with different messages. Don't model "backend slow" as a fatal error.
- If the captcha appears on reopen, you've now paid two costs: thrown away the filled form AND triggered captcha on a fresh session. With the alarm pattern, you pay neither cost — the operator notices, glances at the page, the button enables, flow continues.

### When STAGE_STUCK *is* right

STAGE_STUCK + close-window-reopen is correct when:
- IP probe failed before navigation (dead proxy)
- `page.url() === 'about:blank'` after 60s on a goto (truly didn't navigate)
- `puppeteer.connect()` 60s timeout (browser-side broken)
- The state machine has been in `unknown` stage for > 90s with no domain matching login/Azure (truly lost)
- `runForm1Fill` couldn't even find the first input field — i.e. the page never loaded

The common pattern: STAGE_STUCK is for "we never got to the page we were trying to reach". It is **not** for "we're on the right page, the form is filled, the button is just slow."

### Audit your codebase

```bash
grep -rn "STAGE_STUCK" azure/ src/                          # every emission site
grep -rn "throw .* STAGE_STUCK\|code: 'STAGE_STUCK'" azure/ src/
```

For each hit, ask: *is this case really "we never reached the page" — or is it "we're on the right page and giving up too early"?* The latter should be alarm + wait, not STAGE_STUCK.

---

## Known Azure-specific quirks

- **Microsoft login domains**: Microsoft uses AT LEAST 3 different login domains: `login.microsoftonline.com` (org accounts), `login.live.com` (personal accounts, some Azure signup), `login.microsoft.com` (newer unified). Any domain regex MUST check all three: `/login\.(microsoftonline|live|microsoft)\.com/`. Missing `login.live.com` caused a real production bug where `page.goto` timeout on redirect was misidentified as a network failure.
- **`page.goto` redirect timeout**: When navigating to Azure signup, the server may redirect to a login domain. Puppeteer's `domcontentloaded` can fail to fire during multi-hop redirects even though the destination page is fully loaded. Always wrap in try/catch and check `page.url()` against known domains before re-throwing.
- **`runToForm1` MAX_KMSI_RETRIES**: Must be >= 3 (not 1). The login+open phase is the most failure-prone (MoreLogin API hang, puppeteer connect timeout, blank login page). With retries=1, any single transient failure kills the task. With 3, most network hiccups self-heal.
- **Microsoft login**: SPA, step order is non-deterministic. Always state-machine loop.
- **Passkey prompt**: disable `navigator.credentials.create` via stealth.js → MS falls back automatically. Click 「次へ」 to trigger fallback.
- **Form1 email field**: Azure pre-fills from login; only fill if empty.
- **Form1 radio**: `#account-usage-purpose-personal` — React setter + `dispatchEvent('change')` does NOT work reliably because React only recognizes `isTrusted: true` events from real user interaction. `page.evaluate()` dispatched events always have `isTrusted: false`. **Must use Puppeteer's real mouse click** (`clickHuman(page, 'label[for="account-usage-purpose-personal"]')`) which produces `isTrusted: true`. Implement with retry loop (up to 3 attempts): click label → verify `.checked` → if not checked, setter fallback + retry click → final fallback to `[role="radio"]` text match. See below for full pattern.
- **Form2 postal code**: React setter pattern + double-verify — field can reset when other fields change.
- **Form2 都道府県**: pidl combobox, profile data often omits 「府/県」suffix → use fuzzy match.
- **KMSI button**: Primary strategy: `page.click('#idSIButton9')` (stable ID, CDP-level click). Fallback: `clickHuman` with text-match finder (`text=はい` → `#idSIButton9` → any visible submit). NEVER use `page.evaluate(() => btn.click())` — React ignores `isTrusted: false`. The `findAndClickHuman` 3-retry + `dispatchClick` fallback also fails because `dispatchClick` is `isTrusted: false`. Use `page.click()` as primary for any button with a stable ID.

---

## Windows .bat launcher pitfalls

When creating a .bat launcher script for a Node.js automation project on Windows:

### Encoding: CJK characters in .bat files

cmd.exe defaults to GBK (codepage 936/932). A UTF-8 .bat with Chinese/Japanese text becomes mojibake → `cd` paths break → node can't find entry file → crash.

**Fix:**
1. Write file with **UTF-8 BOM** (`EF BB BF` byte prefix) — tells cmd.exe the file is UTF-8
2. First line after `@echo off`: **`chcp 65001 >nul`** — force UTF-8 codepage
3. **Avoid CJK in critical paths** — use English for `title`, echo messages, comments
4. **Use `cd /d`** — handles cross-drive paths (e.g. `D:\` when cmd starts on `C:\`)
5. **Guard the entry point** — `if not exist src\runner.js (echo ERROR & pause & exit /b 1)`

**Writing .bat from agent tools (git-bash/MSYS):**
- `printf` from bash mangles `\r`, `\P`, `\a` as escape sequences → corrupts paths
- `python -c` with non-raw strings has the same issue (`\a` → bell, `\P` → warning)
- **Use `execute_code`** (Python sandbox) with proper `os.path.join()` or raw strings
- Always **verify the written file** by reading it back and printing each line

### Launching Electron apps from .bat

Electron apps **cannot** be started from git-bash/MSYS2 (`app.whenReady()` → TypeError: undefined). Always use cmd.exe. If the .bat also starts a Node.js runner, launch Electron in a separate cmd window:

```bat
@echo off
chcp 65001 >nul
title Azure Auto-Reg v2

REM Launch Electron companion in separate cmd window
start "" cmd /c "cd /d D:\Projects\form-helper-v2 && npm start"

REM Start runner in this window
cd /d "D:\Projects\azure-auto-reg-v2"
timeout /t 3 /nobreak >nul
node src\runner.js
pause
```

### Template (runner-only .bat)

```bat
@echo off
chcp 65001 >nul
title Azure Auto-Reg v2
cd /d "D:\Projects\azure-auto-reg-v2"
if not exist src\runner.js (
    echo ERROR: runner.js not found
    pause
    exit /b 1
)
echo.
echo   Starting azure-auto-reg-v2 ...
echo.
node src\runner.js
pause
```

---

## Monitoring runner state from agent terminal (Windows git-bash)

When checking runner status via `curl` + `node` on Windows git-bash, `/dev/stdin` doesn't exist — Node.js resolves it as `C:\dev\stdin`. Always write to a temp file first:

```bash
TMPF="C:/Users/roger/AppData/Local/Temp/az_state.json"
curl -s http://127.0.0.1:7777/api/state > "$TMPF"
node -e "const s=JSON.parse(require('fs').readFileSync(process.argv[1],'utf8')); ..." "$TMPF"
```

Also check `runtime.json` directly for offline state (doesn't need runner to be running):
```bash
node -e "const s=JSON.parse(require('fs').readFileSync(process.argv[1],'utf8')); const r=s.results||[]; console.log('idx:',s.currentIndex,'results:',r.length); r.forEach(x=>console.log(x.envId,x.status,x.reason||'',x.durationMs?Math.round(x.durationMs/1000)+'s':''))" "D:/Projects/azure-auto-reg-v2/config/runtime.json"
```

---

## Diagnostic script pattern

For long-running Node.js automation runners, create a `scripts/diagnose.js` that the agent can run on demand to get full system state without guessing. This is critical for AI-assisted debugging — the agent reads structured output, not raw logs.

### What it should report

1. **File health** — do runtime.json, tasks.json, progress.jsonl exist? Size? Last modified?
2. **Runtime state** — current index, pending count, last run time
3. **Result statistics** — success/fail/skip counts, success rate, avg duration
4. **Failure analysis** — group errors by category (captcha, timeout, frame detached, data mismatch, etc.), show repeat-failures per envId
5. **Auto-diagnosis** — consecutive failures, stalled runner, low success rate, known bug patterns
6. **Recent events** — last N lines from progress.jsonl

### CLI modes

```
node scripts/diagnose.js              # full report
node scripts/diagnose.js --env P492   # single envId trace (all events + screenshots)
node scripts/diagnose.js --errors     # failures only
node scripts/diagnose.js --recent 30  # last 30 events
node scripts/diagnose.js --live       # current progress.txt snapshot
```

### Error categorization (for Azure reg specifically)

Map raw error strings to actionable categories:
- `captcha|人機` → 🤖 captcha (may need proxy rotation)
- `都道府県|no_match` → 🗾 data mismatch (check profile data quality)
- `Navigation timeout` → ⏰ network/page load issue
- `frame.*detach` → 💥 fingerprint browser compat issue
- `missing_romaji|missing_kana` → 📛 profile data incomplete
- `予期しないエラー` → 💢 Azure backend error (transient, auto-retry)
- `等待人工接管超時` → ⏳ unattended timeout (expected overnight)

See `references/diagnose-script.md` for the full implementation.

---

## References
- `references/azure-reg-flow-bugs.md` — Bug analysis from real runs: login captcha close bug, form1/form2 captcha close bug, 「京都」prefecture no_match bug, and their fixes.
- `references/fork-merge-workflow.md` — How to maintain a v2 fork alongside an actively-edited source directory: re-clone strategy, selective enhancement merge, diff verification. Also covers forking Electron companion apps (npm install required, git-bash can't launch Electron, path pointer verification).
- `references/failure-retry-dashboard.md` — Failure tracking, retry queue, and dashboard recovery pattern: fail-fast timeout (60s), in-memory retry queue, mark-success for false failures, dashboard HTTP endpoints.
- `references/diagnose-script.md` — Self-serve diagnostic script pattern for Node.js automation runners: structured health check, failure categorization, envId tracing, and CLI modes.
- `references/form-helper-app-architecture.md` — FormHelper Electron companion app: 3-tab architecture (account viewer, batch creator, Azure runner control), multi-country company library, Claude Haiku enrich engine, and feature comparison with v2 dashboard.
- `references/captcha-retry-graduated-strategy.md` — Specific bugs from real runs: post-captcha window close, first-login window kill, and captcha timeout too short. Includes graduated retry strategy code and Windows alert system verification.
- `references/timeout-and-unattended-patterns.md` — Timeout protection for browser API hangs, unattended captcha retry implementation, cross-field value pollution fix, React isTrusted radio button fix, dead proxy IP detection with probe URL pitfalls, KMSI click-then-verify pattern, download dialog trap from binary probe URLs.
- `references/post-login-navigation-stall.md` — Post-KMSI redirect stall diagnosis: 3-layer defense (browser auto-clicker via evaluateOnNewDocument + safeGoto wrapper + state machine fallback), domain-aware unknown handler, runner ip_stuck hint for hard reset, why reload never fixes stalled redirects, and the lesson "don't patch navigation — bypass it."
- `references/electron-host-port.md` — Porting a standalone runner.js+flow.js+alert.js+dashboard automation into an Electron main process: read-only browser adapter (wsEndpoint from ACTIVE_BROWSERS Map), in-memory continue-flag Map replacing file-polling IPC, Notification API + webContents.send events replacing rundll32/msg.exe/PowerShell/TG, 3-minute captcha timeout with disconnect-then-reopen (not stopEnv), UI checkboxes replacing tasks.json, **two-layer identity (profile-name vs CSV-serial) with name-match-first three-tier resolution (NEVER auto-pick from pool)**, the "verify async vs sync before calling legacy modules" rule, and the "read the orchestrator before the primitives" lesson from a real botched port.
- `references/cooperative-pause-resume-control.md` — Pause/resume/stop control for long-running state-machine runners via cooperative checkpoints. Per-envId `RUN_STATE` Map with `pauseRequested`/`abortRequested` flags, `checkControl()` at every loop boundary, `AbortRunError` with `code: 'USER_ABORT'`, **`finalizeCtrl()` helper for terminal-state writes (audit with grep)**, **rule against clearing `abortRequested` on entry (breaks pre-emptive batch stop)**, **batch queue with `queued` status + `pauseAll`/`resumeAll`/`stopAll` IPCs + optimistic UI seeding**, **fire-and-forget batch dispatch (don't await)**, **failed-badge subtitle shows error text not stage**, three-state UI button group (▶/⏸/⏹) driven by `azure:runState` broadcast, why this beats SIGSTOP / checkpoint-to-disk / AbortController / worker-thread alternatives.
- `references/captcha-alarm-renderer-ux.md` — Renderer-side captcha alarm UX: dedicated `azure:captcha` / `azure:captcha-cleared` event pair, Web Audio 3-tone beep without external files, 5s repeat with 30-iteration cap, system `Notification` with `requireInteraction`, `document.title` flipping for taskbar visibility, distinct `azs-captcha` pulse animation (live red ≠ dead failure red), in-row "✅ 我过了, 继续" green pulse button calling `azureContinueOne`, stop-alarm-before-IPC ordering, AudioContext user-gesture pitfall and lazy-init mitigation. Reusable for any human-in-the-loop event (captcha, SMS verify, 3DS, takeover).
- `references/detector-regex-and-stuck-pattern.md` — Two related debugging lessons: (1) detector regex must use task-imperative phrases not product nouns (`ロボットでないことを証明` not `アカウントの保護`), 11 scattered copies → centralize to `CAPTCHA_RE` constant + iframe-origin probe as primary signal; (2) "button not enabled in 30s → throw STAGE_STUCK → close + reopen" is the most expensive wrong pattern on hardened SPAs — A/B/C/D outcome table, 60s poll + 5min alarm replaces 30s timeout, full audit grep.
- `scripts/backfill-azure-status.js` — Re-runnable one-shot for backfilling `azure_status='success'` on historical successful accounts whose `logs/flow/<name>/` has a `reached-payment.png` screenshot but pre-dates the status-persistence feature. Dry-run by default; `--apply` to write. Skips already-success accounts. Customize STORE_MODULE / LOG_DIR / pattern constants at the top.
