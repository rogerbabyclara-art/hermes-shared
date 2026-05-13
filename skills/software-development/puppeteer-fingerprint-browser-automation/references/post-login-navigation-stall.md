# Post-Login Navigation Stall (KMSI → Azure Redirect)

## Sessions: 2026-05-12 (initial), 2026-05-12 (auto-clicker evolution)

### User insight that drove the fix

> "登录完到了保持状态界面后，会发生一个跳转，这个跳转老是被网卡住，刷新是无用的，我自己注册时也会碰到，我的手动处理方式就是换IP重新开窗口继续"

Key facts from user:
1. The KMSI click itself works — the page transitions away from "サインインの状態を維持しますか"
2. The redirect from login.microsoftonline.com → signup.azure.com gets stuck by network
3. **Reloading is useless** — user tested manually, never works
4. **Only fix is switch IP + reopen window** — user's proven manual workflow

### Evolution of the fix (3 rounds)

The fix went through 3 iterations in one session. Each round fixed one symptom but exposed the next layer of the same root problem: **Puppeteer's `page.goto` navigation events are unreliable on Microsoft's redirect chains**.

#### Round 1: Domain-aware unknown handler (insufficient)
- Made the `unknown` stage handler give login domains 90s instead of 40s
- Removed `page.reload()` for Azure-domain white screens (user confirmed reload is useless)
- Added `hint: 'ip_stuck'` for runner hard-reset routing

**Problem**: KMSI page was loaded and clickable, but code was stuck in `openAzure()`'s `page.goto` — never reached the state machine at all.

#### Round 2: safeGoto wrapper (better but still insufficient)
- Created `safeGoto()` to absorb goto timeouts when URL is on a known domain
- Added `runToForm1` skip-clickEntry when already on login domain
- Replaced ALL `page.goto` calls with `safeGoto`

**Problem**: Even with safeGoto, the code flow was: `safeGoto` → return → `clickEntry` or skip → `microsoftLogin` state machine → detect KMSI → click. By the time the state machine reached the KMSI step, the page may have already been sitting there for 30+ seconds. And if the goto timeout consumed 30s, that's 30s wasted.

#### Round 3: evaluateOnNewDocument auto-clicker (root fix)
- Inject a self-running JS script into every new page that auto-clicks KMSI
- Works in browser context, completely independent of Node.js event loop
- Fires even when Puppeteer code is stuck in `await safeGoto()`

**Why this is the root fix**: The fundamental problem was that Puppeteer's code-level flow control (goto → detect → click) is inherently serial and blocked by navigation events. The auto-clicker operates at the browser level, in parallel with Puppeteer's code. It sees the button the moment the page renders and clicks it immediately — no dependency on goto completing, state machine reaching the right step, or any other Node.js-level logic.

### What was wrong before (original code)

The `unknown` stage handler in the login state machine treated all unknown pages identically:
- Azure domain + white screen → `page.reload()` after 15s → reset timer → wait another 40s → STAGE_STUCK
- Login domain (redirect in progress) → same 40s → STAGE_STUCK
- Any other unknown → same 40s → STAGE_STUCK

The `page.reload()` was actively harmful — wasted 30 seconds on a reload that never fixes a stalled redirect, then reset the timeout counter giving false hope.

### Final architecture (3-layer defense)

| Layer | Mechanism | When it fires |
|---|---|---|
| 1. Browser auto-clicker | `evaluateOnNewDocument` JS injection | Page renders KMSI → clicks within 1.5s, even if Node.js is blocked |
| 2. `safeGoto` | Navigation timeout absorption | goto times out but URL is on known domain → no error thrown |
| 3. State machine | `detectLoginStage` → `clickKmsiYes` 4-method exhaustion | Fallback if auto-clicker didn't fire |

### flow.js domain-aware unknown handler

| URL domain | Behavior | Timeout | On timeout |
|---|---|---|---|
| `login.microsoftonline.com` / `login.live.com` / `login.microsoft.com` | Wait patiently (redirect in progress) | 90s | STAGE_STUCK (generic) |
| `signup.azure.com` / `portal.azure.com` | Wait, NO reload | 40s | STAGE_STUCK + `hint: 'ip_stuck'` |
| Other | Wait | 60s | STAGE_STUCK (generic) |

### runner.js STAGE_STUCK handler — ip_stuck hint

```js
const isDeadIP = e.message && e.message.includes('IP 探活失败');
const isIPStuck = e.hint === 'ip_stuck';
const hardReset = isDeadIP || isIPStuck || attempt >= 3;
```

Both `isDeadIP` and `isIPStuck` force immediate `stopEnv` (hard reset) — no soft retry with same proxy.

### Why reload doesn't work for stalled redirects

When Microsoft's auth server is processing a redirect, the browser is waiting for a server-side response (HTTP 302/303). The URL in the address bar may show a transitional endpoint or still the login domain. Reloading at this point:
- If on login domain: reloads the login page → may need to re-login entirely
- If on Azure domain but blank: the page JS hasn't loaded → reload fetches same stalled resource from same IP

Neither helps. The underlying problem is the proxy IP's route to Azure's CDN is degraded. Only a fresh proxy session (new IP) fixes it.

### page.goto timeout on redirect — the deeper bug

**Symptom**: Dashboard shows `open.browser_launch` for 34+ seconds, KMSI page is visible and clickable in the browser window, but the runner never proceeds to the login state machine. User clicks "はい" manually, page advances to Azure form, but code has already timed out and abandoned the page.

**Root cause**: `page.goto(AZURE_URL, { waitUntil: 'domcontentloaded', timeout: 30000 })` throws timeout because:
1. Azure signup URL redirects to `login.live.com` (not `login.microsoftonline.com`)
2. The redirect chain involves server-side auth hops
3. Puppeteer's `domcontentloaded` event fires for the *final* navigation, but during multi-hop redirects it may never receive the signal even though the destination page is fully loaded
4. After 30s timeout, `openAzure()` throws → runner catches as STAGE_STUCK → kills window

**Critical detail**: Microsoft uses AT LEAST 3 login domains. Missing any one in the regex causes misidentification.

**Fix**: `safeGoto` wrapper (see main SKILL.md) + `evaluateOnNewDocument` auto-clicker.

### Lesson: Don't patch navigation — bypass it

The session went through 3 rounds of fixing the same class of problem (Puppeteer navigation events unreliable on redirect chains). Each patch fixed one manifestation but exposed the next:
1. "Give more time" → still times out on slow networks
2. "Catch timeout and continue" → code still has to reach the click step
3. "Auto-click in browser context" → works regardless of Node.js state

**General principle**: When a page always needs a predictable action (click a known button, dismiss a prompt), inject the action at the browser level via `evaluateOnNewDocument`. Don't try to make the Node.js flow control arrive at the right moment — it depends on too many unreliable signals (navigation events, timeouts, stage detection timing). Let the browser handle what the browser can see.

### Diagnostic pattern

In runner logs, look for:
```
[flow] ✓ KMSI 自动点击器已注入
[flow] safeGoto → 超时但 URL 在已知域名 (https://login.live.com/...)，继续
[flow] 页面已在登录域名 (https://login.live.com/...)，跳过 clickEntry
```

Browser console (visible in DevTools):
```
[KMSI-auto] 检测到 KMSI 页面，自动点击はい
```

If you see the auto-clicker log in browser console but no corresponding state machine log, it means the auto-clicker handled KMSI before the state machine got there — this is the desired behavior.
