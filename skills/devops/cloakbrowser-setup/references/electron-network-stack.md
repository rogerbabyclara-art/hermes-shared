# Electron + proxy stack: the full "why isn't the proxy working" ladder

When a user's Electron desktop app integrates third-party proxies (residential / datacenter / VLESS) and the IPs all fail their first test, walk this ladder top-to-bottom. Each step has a one-shot diagnostic.

## 0. Confirm raw source IP (before anything else)

In the user's **PowerShell** (NOT git-bash, NOT WSL — those have different network namespaces):

```powershell
curl https://ipinfo.io/json
# or
node -e "require('https').get('https://ipinfo.io/json', r => r.on('data', c => console.log(c.toString())))"
```

The country in the response is what every outbound TCP from this app will look like UNTIL you change something. If the user is in mainland China and wants to use residential proxies whose ToS forbids CN source IPs (711proxy, many others), they need to route via a clean exit BEFORE the proxy library connects.

## 1. SOCKS5 reply codes (the proxy server is talking back!)

When the SOCKS5 handshake completes but the proxy REJECTS your connection, you get a reply code. Library error messages:

| Library output | RFC1928 code | Real meaning |
|---|---|---|
| `Socks5 proxy rejected connection - NotAllowed` | 0x02 | **Access rules disallow your source IP / username / target host**. Not auth failure, not network issue. Provider has a rule that says "this client cannot connect right now." |
| `... - NetworkUnreachable` | 0x03 | Proxy can't route to the target (rare for HTTPS targets) |
| `... - HostUnreachable` | 0x04 | DNS failure inside proxy or target down |
| `... - ConnectionRefused` | 0x05 | Target host actively refused |
| `... - GeneralFailure` | 0x01 | Catch-all — usually backend overload |

**`NotAllowed` is 95% of the time one of:**
1. Source IP geoblocked (Chinese IP → residential proxy that bans CN)
2. Source IP not in account whitelist (rare these days — most providers use auth+IP or pure auth, not pure IP)
3. Username syntax wrong (vendor parses zone/region/session params; bad params silently route to "blocked" rule)
4. Account out of credit / suspended

Curl reproduction without the library:
```bash
curl -sS --max-time 15 \
  --socks5-hostname HOST:PORT \
  --proxy-user "USER:PASS" \
  https://ipinfo.io/json
# curl exit 97 = "cannot complete SOCKS5 connection (2)" — same NotAllowed
```

## 2. Why your `require('socks-proxy-agent')` returned no errors but no IP came back

`socks-proxy-agent` v8+ is ESM-only. In Electron main (CJS), `require()` of an ESM module silently returns a Module object whose default export is a frozen empty namespace; constructing `new SocksProxyAgent(url)` then does NOT actually create a working agent. Symptoms:

- All tests fail
- No exception thrown
- `last_test_ip` stays empty
- `last_test_at` updates (so the request ran)
- DevTools Console (renderer) is clean — error is in main process

**Diagnostic** from inside Electron main:
```javascript
const mod = require('socks-proxy-agent');
console.log('SocksProxyAgent:', typeof mod.SocksProxyAgent);  // should be 'function', NOT undefined
```

**Fix**: dynamic `import()` with cached module — see `electron-integration.md` pitfall #7.

## 3. Electron Chromium ignores Windows system proxy

The Chromium engine inside Electron has its OWN proxy config. It does NOT read:
- Windows registry HTTP proxy settings (`Internet Settings\ProxyServer`)
- `HTTP_PROXY` / `HTTPS_PROXY` environment variables (Node `https` module also ignores these by default)
- PAC scripts set by v2rayN / Clash via "system proxy" toggle

Consequences:
- v2rayN "System Proxy = ON" → Edge/Chrome browse via proxy, but your Electron app does NOT
- A CloakBrowser subprocess launched by your Electron app does NOT either
- `require('https').get(...)` in main.js does NOT either
- `axios` / `node-fetch` in main.js does NOT either

**The fix is TUN mode** (kernel virtual NIC):
- v2rayN: Settings → enable TUN mode → first run installs wintun.dll → relaunch v2rayN as Admin
- Clash Verge / Clash for Windows: "TUN Mode" toggle
- After enabling, `curl https://ipinfo.io/json` from a fresh terminal MUST show the proxy's exit country. If it still shows the user's ISP, TUN didn't activate (driver install failed, or app not running as Admin).

After TUN activates, **restart the Electron app** — running Electron processes cache their network stack at startup; TUN added afterwards may not be picked up by existing sockets.

## 4. Provider-specific gotchas observed in the wild

### 711proxy (rotgb.711proxy.com)
- Explicit ToS: "代理产品均不支持在中国大陆网络环境下使用" — CN source IP → `NotAllowed`
- Solution: TUN through HK/JP/SG node before connecting

### cliproxy (us.cliproxy.io)
- Username format: `<user>-region-<COUNTRY>-sid-<random>-t-<minutes>`
- `region-JP` is valid; `country-JP` returns 407 auth failure
- Each `sid` is a separate sticky session — same `sid` reused = same exit IP for `t` minutes, then rotates

### 711proxy username format
- `<user>-zone-custom-region-<COUNTRY>-session-<digits>-sessTime-<minutes>-sessAuto-1`
- `zone-custom` must exist in their dashboard before use
- `session-<digits>` is sticky session ID

## 5. Verify the proxy in 3 layers, in order

```
Layer 1: HTTP smoke from a plain shell (NOT via Electron)
  curl --socks5-hostname HOST:PORT --proxy-user "USER:PASS" https://ipinfo.io/json
  → Confirms credentials + source IP + provider ACL

Layer 2: Node SOCKS5 agent in isolation
  node -e "..." (see scripts/test_socks5_node.mjs)
  → Confirms socks-proxy-agent version is compatible

Layer 3: Inside the Electron app
  Click your in-app "Test single IP" button
  → Confirms the app's actual code path works
```

If layer 1 fails: provider blocks the source IP or credentials are wrong. Fix the network or the auth, no point looking at code.
If layer 1 works but layer 2 fails: Node module issue (likely ESM).
If layer 1 + 2 work but layer 3 fails: app code bug, not infrastructure.

## 6. Batch proxy test design

Designing the "test all" button for 100-500 IPs:

| Aspect | Wrong | Right |
|---|---|---|
| Concurrency | Serial (1 at a time) | 10 in parallel |
| User feedback | "测试中..." static text | `进度 47/200 · 通 38 失 9` updating |
| State persistence | Save once at end | Save every N (e.g. 20) tests so a crash/close doesn't lose data |
| Cancellation | None | A cancel flag the worker loop checks each iteration |
| Timeout per IP | None or 60s | 15s — anything slower is unusable in production anyway |

Implementation pattern (Electron main):
```javascript
ipcMain.handle('proxy:testAll', async (e, filter) => {
  const pool = loadPool(filter);
  let done = 0, ok = 0, fail = 0, cursor = 0;
  const CONCURRENCY = 10, SAVE_EVERY = 20;
  const push = () => e.sender.send('proxy:testProgress', { done, ok, fail, total: pool.length });

  async function worker() {
    while (cursor < pool.length) {
      const ip = pool[cursor++];
      const r = await testProxy(ip, 15000);
      if (r.ok) { ip.last_ip = r.ip; ok++; } else fail++;
      ip.last_test_at = Date.now() / 1000 | 0;
      done++;
      if (done % SAVE_EVERY === 0) save(pool);
      push();
    }
  }
  await Promise.all(Array.from({ length: CONCURRENCY }, worker));
  save(pool);
  return { ok: true, summary: { total: pool.length, ok, fail } };
});
```

Renderer subscribes via `ipcRenderer.on('proxy:testProgress', ...)` exposed through `preload.js` contextBridge.

## 7. Anti-pattern: testing IP and "scraping geo" at the same time

`ipinfo.io/json` returns both `ip` and `country/city/org` in one round trip — great. But it rate-limits at ~50k/day on free tier. For 500 IPs × 10 tests/day = 5000 hits, fine. For 5000 IPs × hourly tests, you'll hit limits.

Backup endpoints when ipinfo.io 503s (it does, frequently):
- `https://api.ipify.org?format=json` — IP only, no geo, but very stable
- `https://ipapi.co/json/` — geo lookup of YOUR IP (call separately with `/<ip>/json/` to look up arbitrary IP)
- `https://api.myip.com` — IP + country only

Don't call `ip-api.com` from datacenter IPs — it returns `"forbidden ip=X not supported"`.
