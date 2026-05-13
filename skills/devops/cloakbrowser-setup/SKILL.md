---
name: cloakbrowser-setup
description: Install and use CloakBrowser (stealth Chromium for bot detection bypass) on Windows, and build multi-profile manager UIs on top of it. Use when setting up CloakBrowser Python/Node SDK, hitting API mismatch with README, building reg/scrape bots that need to pass Cloudflare/Azure/BrowserScan checks, or designing AdsPower/MoreLogin-style account-list GUIs around CloakBrowser profiles.
---

# CloakBrowser Setup & API Reference

CloakBrowser is a source-patched Chromium (49 C++ patches) with humanize mouse/keyboard, geoip-aware fingerprint, and WebRTC leak protection. Drop-in for Playwright/Puppeteer. Replaces MoreLogin/ADS-style fingerprint browsers without per-profile cost.

GitHub: https://github.com/CloakHQ/CloakBrowser (MIT, 7.4k★)

## Install (Windows)

```powershell
# Python
pip install cloakbrowser

# Node — mmdb-lib is required if you'll use geoip: true (peer dep, not auto-installed)
npm install cloakbrowser puppeteer-core mmdb-lib

# Download stealth Chromium binary (~535 MB → C:\Users\<user>\.cloakbrowser\)
python -m cloakbrowser install
```

CLI subcommands: `install`, `info`, `update`, `clear-cache`.

### Extras for `geoip=True`

Plain `pip install cloakbrowser` does **not** pull the geoip2 dependency. If
you pass `geoip=True` to `launch()` without the extra, you get an `ImportError`
at launch time:

```
ImportError: geoip2 is required for geoip=True. Install it with:
  pip install cloakbrowser[geoip]
```

Always install with the extra when you intend to use geoip auto-matching:

```powershell
pip install "cloakbrowser[geoip]"   # quote in PowerShell — square brackets are glob chars
```

## CRITICAL: README is outdated

README still shows old `from cloakbrowser.playwright import async_playwright` wrap. **Real 0.3.x API is simpler**:

```python
from cloakbrowser import launch   # sync
# or
from cloakbrowser import launch_async   # async

browser = launch(
    headless=False,
    humanize=True,    # bezier mouse + real typing
    geoip=True,       # WebRTC leak fix + timezone/locale auto-match
    proxy="http://user:pass@host:port",  # or ProxySettings obj
    timezone="Asia/Tokyo",  # optional override
    locale="ja-JP",         # optional override
)
context = browser.new_context()
page = context.new_page()
page.goto("https://www.browserscan.net/")
browser.close()
```

`launch()` returns a Playwright `Browser` object directly. No async_playwright context manager needed for sync usage.

### Actual launch() signature

```
launch(headless=True, proxy=None, args=None, stealth_args=True,
       timezone=None, locale=None, geoip=False, backend=None,
       humanize=False, human_preset='default', human_config=None, **kwargs)
```

Note: `fingerprint=N` (seed) is **not** a top-level kwarg — pass via `args=['--fingerprint=12345']` or use `launch_persistent_context(user_data_dir)` for stable identity.

## Node version

```javascript
const { launch } = require('cloakbrowser/puppeteer');
const browser = await launch({ headless: false, humanize: true, geoip: true });
```

**Node-side `geoip: true` requires `mmdb-lib`** — see install section above. Without it, launch throws `Error: mmdb-lib is required for geoip: true`.

**Embedding in Electron (CJS host) — use a spawned ESM subprocess.** `cloakbrowser` is ESM-only (`"type": "module"`) so `require()` fails with `ERR_PACKAGE_PATH_NOT_EXPORTED`. Full pattern with launcher.mjs + spawn + JSON-line IPC is in `references/electron-integration.md`.

## Verify install works

Visit https://www.browserscan.net/ — CloakBrowser scores 95-100%. Plain Puppeteer scores 30-50%.

## Pitfalls

1. **README API mismatch**: don't trust the README's `cloakbrowser.playwright` import. Run `python -c "from cloakbrowser import launch; import inspect; print(inspect.signature(launch))"` to see real params.
2. **PowerShell `cd` doesn't need `/d`**: `cd D:\Projects\xxx` works. `cd /d D:\xxx` is cmd-only and errors in PowerShell.
3. **Python 3.14 on Windows**: scripts install to `C:\Users\<user>\AppData\Roaming\Python\Python314\Scripts` (not on PATH by default). Use `python -m cloakbrowser` instead of bare `cloakbrowser`.
4. **Don't launch headed browser from git-bash on Windows** — window may not render. Use cmd or PowerShell.
5. **Persistent identity**: same `fingerprint` seed = same browser fingerprint across runs. For account farming, store seed per account.
6. **Binary location**: `C:\Users\<user>\.cloakbrowser\chromium-<version>\chrome.exe`. Survives pip uninstall — manually delete to free 535 MB.
7. **Porting an existing puppeteer flow into a CloakBrowser/Electron host?** Read both the entry (`flow.js`) AND the orchestrator (`runner.js` / state machine). The entry exposes primitives; the orchestrator decides the call sequence with retry/captcha/stuck handling. A linear port from the entry alone WILL fail on real Azure/MS flows. Also: drop `puppeteer-core` to 23.x — v25 is pure ESM and breaks legacy CJS `require()`. Full pattern in `references/embedding-puppeteer-flow.md`.

## Key parameters cheat sheet

| Param | Purpose |
|---|---|
| `humanize=True` | Bezier mouse path, real typing cadence, scroll inertia |
| `geoip=True` | Auto timezone/locale + WebRTC IP match to proxy exit |
| `proxy` | HTTP/HTTPS/SOCKS5; pair with `geoip=True` |
| `stealth_args=True` (default) | All 49 C++ patches active |
| `human_preset` | `'default'`, `'fast'`, `'careful'` |
| `args=['--fingerprint=N']` | Stable identity seed |
| `launch_persistent_context(dir)` | Cookie/storage persistence |

## CRITICAL: locale/timezone must match proxy country (anti-fingerprint rule)

**Hardest fingerprint rule for account-farming/auto-reg work**: if proxy exits in country X, the browser MUST present as country X across every layer. Mismatch (e.g. JP residential IP + zh-CN locale + Asia/Shanghai timezone) is an instant red flag for Microsoft/Google/Stripe risk engines — you are obviously a proxy user, not a real Japanese resident.

User feedback verbatim: *"不能补中文啊，补中文不就露馅了嘛，这是指纹浏览器底层没有配置我的IP和语言一致"* — when an auto-click selector fails because the page renders in Chinese instead of expected Japanese, **do NOT add Chinese locale regex as a fix**. That makes the bot work but burns the account on first risk-check. Fix the locale layer instead.

### Why `geoip: true` alone is NOT enough

The README says `geoip: true` auto-matches locale/timezone to proxy IP. In practice it fails silently in several cases:

1. **SOCKS5 proxy**: CloakBrowser's geoip probe may resolve through the host's local IP, not the proxy exit — wrong country detected → defaults to system locale (Chinese on a Chinese-system host).
2. **mmdb-lib database lag/miss**: residential IP not in GeoLite2 → no match → fallback to system locale.
3. **Existing user-data-dir**: Chromium's `Preferences` file in `<user-data-dir>/Default/Preferences` caches `intl.accept_languages` from the first launch. Subsequent `launch({locale:'ja-JP'})` is overridden by the cached preference.

### Three-layer lockdown (mandatory for serious anti-detect)

Do all three, not just `geoip: true`:

```js
// Layer 1: launch-time C++ injection — beats geoip auto-detect
const launchOpts = {
  locale: 'ja-JP',           // EXPLICIT, do not rely on geoip
  timezone: 'Asia/Tokyo',    // EXPLICIT
  geoip: true,               // keep as fallback for other dimensions (WebRTC etc.)
  proxy: PROXY_URL,
};

// Layer 2: rewrite Preferences before launch (overrides cached user prefs)
// Chromium load order: command line --lang > Preferences.intl > system locale
// navigator.languages and Accept-Language header READ FROM Preferences
const prefPath = path.join(USER_DATA_DIR, 'Default', 'Preferences');
if (fs.existsSync(prefPath)) {
  const prefs = JSON.parse(fs.readFileSync(prefPath, 'utf8'));
  prefs.intl = prefs.intl || {};
  prefs.intl.accept_languages = 'ja,ja-JP,en-US,en';
  prefs.intl.selected_languages = 'ja';
  prefs.translate_blocked_languages = ['ja'];
  // Disable Chrome's "translate this page?" infobar — popping it = automation tell
  prefs.translate = prefs.translate || {};
  prefs.translate.enabled = false;
  fs.writeFileSync(prefPath, JSON.stringify(prefs), 'utf8');
}

// Layer 3: verify before trusting — run in DevTools console after launch
// Expected for JP: {lang:"ja-JP", langs:["ja","ja-JP","en-US","en"], tz:"Asia/Tokyo"}
// JSON.stringify({lang:navigator.language, langs:navigator.languages,
//                 tz:Intl.DateTimeFormat().resolvedOptions().timeZone})
```

### Symptom → diagnosis cheat sheet

| Symptom | Root cause | Fix |
|---|---|---|
| MS login page Chinese, IP is JP | locale not locked | Layer 1 + 2 above |
| `navigator.language` = "zh-CN" but `locale:'ja-JP'` passed | Preferences cache | Layer 2 (rewrite intl.accept_languages) |
| Auto-click selector misses Japanese text | (Don't add Chinese regex) → page rendering wrong language | Fix locale, not selector |
| `Intl.DateTimeFormat().resolvedOptions().timeZone` = "Asia/Shanghai" | timezone not locked | Layer 1 (explicit `timezone:`) |
| "Translate this page to Chinese?" popup appears | `translate.enabled` not disabled | Layer 2 (`prefs.translate.enabled = false`) |

**Rule of thumb**: when an auto-detect helper *might* fail silently and the failure cost is high (account burn), bypass it with explicit values. `geoip: true` is for convenience, not for production account farms.

## Demo location

`D:\Projects\cloak-test\` contains working `demo_python.py` and `demo_node.js` minimal examples, plus `manager.py` + `proxies.csv` for batch proxy/identity management.

Support files in this skill:
- `templates/manager.py` — batch proxy/identity CLI (list/test/open)
- `templates/proxies.csv` — CSV schema starter
- `templates/tinyproxy.conf` — VPS upstream-chain forwarder config (drop-in `/etc/tinyproxy/tinyproxy.conf`)
- `scripts/probe_proxy.sh` — diagnostic probe distinguishing IP-block vs auth-fail vs region-misconfig
- `scripts/test_socks5_node.mjs` — standalone Node ESM probe with classified exit codes (NotAllowed / timeout / OK). Use when Electron app reports all-IPs-fail to rule out the SocksProxyAgent ESM trap.
- `references/vps-proxy-chain.md` — full walkthrough for chaining residential proxies via clean VPS when source-IP is blocked, including cloud security group, TUN loop, and country-verification pitfalls
- `references/electron-integration.md` — embedding CloakBrowser in Electron via spawned ESM launcher subprocess (ESM/CJS interop, env-var IPC, lifecycle isolation)
- `references/embedding-puppeteer-flow.md` — embedding an EXISTING standalone puppeteer-based automation flow (V2 Azure auto-reg style) into a CloakBrowser-driven Electron host: CDP wsEndpoint handoff, 5-method adapter pattern, puppeteer-core v25-ESM-vs-v23-CJS pitfall, "must read orchestrator file too" rule
- `references/electron-network-stack.md` — diagnosing "Electron + proxy doesn't work": SOCKS5 reply codes, ESM-only agent libraries, TUN-mode requirement for Chromium subprocess, batch-test concurrency pattern with progress events
- `references/adspower-style-account-manager-ui.md` — affirmative HTML/JS pattern for AdsPower-style multi-account managers: column layout, multi-select + batch bar, search/filter, inline-edit cells, chip tags, status pills, batch IPC handler shape with concurrency + progress polling
- `templates/proxy-account-manager.html` — minimal table skeleton (top bar + batch bar + 9-column thead) ready to drop into renderer/index.html

## Proxy troubleshooting (real-world)

### Symptom: residential proxy times out from datacenter IP

If `curl -x http://user:pass@proxy:port https://api.ipify.org` hangs and times out at 30s **even with wrong password**, the proxy provider is silently dropping packets from your source ASN. Common residential proxy vendors (cliproxy, IPRoyal, Bright Data) blacklist datacenter ASNs (Tencent AS132203, AWS, DigitalOcean, OVH) to prevent abuse.

**Diagnosis** — wrong-password test is the smoking gun:
```bash
# If this also hangs (not "407 auth required"), it's IP block, not auth
curl -v --max-time 15 -x "http://user:WRONGPASS@proxy:port" http://api.ipify.org
```

**Fix**: route the connection through a clean VPS (not in the vendor's ASN blacklist) running tinyproxy as an upstream-chain forwarder. Full walkthrough in `references/vps-proxy-chain.md`, ready-to-edit config in `templates/tinyproxy.conf`.

Quick form:
```bash
sudo apt-get install -y tinyproxy
# Edit /etc/tinyproxy/tinyproxy.conf — set Port, BasicAuth, Upstream
sudo systemctl restart tinyproxy
# THEN open the port in cloud security group (Tencent/AWS/Aliyun console)
```

Do NOT use 3proxy — not in Ubuntu 22.04/24.04 repos, requires source build. Tinyproxy is `apt`-available and uses ~1 MB RAM.

Other options that also work but are heavier:
- v2rayN/Clash TUN mode through a residential VPN
- SSH `-D` SOCKS tunnel through a residential VPS

### Symptom: proxy returns wrong country

User specifies `region-JP` in username but exit IP is China/random country. Provider's region param was silently ignored (no JP nodes in pool / account out of credit / wrong syntax variant).

**Always verify exit IP country before trusting it** — don't assume user-side params worked:
```bash
IP=$(curl -s --max-time 20 -x "$PROXY" https://api.ipify.org)
curl -s "https://ipapi.co/$IP/json/" | grep -E '"country_name"|"org"'
```

Username syntax varies by vendor: `country-JP`, `region-JP`, `geo-JP`, `zone-JP`, `-JP-`. Check vendor docs; don't guess.

### IP-check endpoints: always have 3+ fallbacks

- `api.ipify.org` — most reliable, plain text
- `ipapi.co/json/` — full geo info, occasional rate limits
- `api.myip.com` — JSON, good fallback
- `ip-api.com/json/` — free but blocks datacenter source IPs (returns "forbidden ip=X not supported")
- `ipinfo.io/json` — frequently returns 503; **don't rely on it**

### v2rayN TUN mode for system-wide routing

When you need ALL TCP traffic (including subprocess curl, Python requests) to route through a VLESS/Reality node:
1. Run v2rayN **as Administrator** (TUN requires elevation)
2. Enable TUN mode toggle (installs wintun driver first run)
3. Verify with `curl https://api.ipify.org` from a fresh terminal — should show VPS IP

Without TUN, only apps that read system HTTP_PROXY env var route through v2rayN. Python `requests` with explicit `proxies={}` parameter and curl with `-x` flag **bypass system proxy** and need TUN to be intercepted.

**Electron apps especially need TUN** — Chromium engine, main-process Node `https`, and spawned CloakBrowser subprocesses all ignore Windows system proxy. PAC mode / global mode in v2rayN does NOT route Electron traffic. See `references/electron-network-stack.md` for the full diagnostic ladder.

### Provider ToS gotchas observed

- **711proxy** (`global.rotgb.711proxy.com`): explicit ToS forbids mainland China source IPs. CN exit → `Socks5 NotAllowed`. Must TUN through HK/JP/SG before SOCKS5 handshake.
- **cliproxy** (`us.cliproxy.io:3010`): username format `<user>-region-<COUNTRY>-sid-<random>-t-<min>`. `region-JP` works; `country-JP` fails auth.
- **All residential providers**: never test from datacenter ASN (Tencent AS132203, AWS, OVH). Even with valid creds they silent-drop the packet. Diagnose with wrong-password test — see `references/vps-proxy-chain.md`.

### SOCKS5 reply codes — what the error actually means

| socks-proxy-agent message | RFC1928 code | Real meaning |
|---|---|---|
| `Socks5 proxy rejected connection - NotAllowed` | 0x02 | Provider rule blocks this client (geo/whitelist/zone/credit). NOT auth failure. |
| `... NetworkUnreachable` | 0x03 | Proxy can't reach target |
| `... HostUnreachable` | 0x04 | DNS / target down |
| `... ConnectionRefused` | 0x05 | Target refused |
| `... GeneralFailure` | 0x01 | Backend overload |

`NotAllowed` 95% of the time = source IP geo-blocked. Curl reproduction: `curl --socks5-hostname HOST:PORT --proxy-user "USER:PASS" https://ipinfo.io/json` — exit 97 means same thing.

## UI paradigm for multi-profile managers (AdsPower/MoreLogin model)

When building a GUI on top of CloakBrowser to manage many profiles (form-helper-v2, azure-auto-reg-v2, batch reg tools), the user expects **AdsPower/MoreLogin ergonomics**, not a "smart" auto-decorated experience. Hard rules learned the hard way:

1. **One-click launch AND one-click stop, no modal/confirm in between.** `[▶ 开始]` button → lock + spawn browser + toast. `[⏹ 停止]` button → close + unlock + toast. Do NOT pop a "what is this session for?" / "add a note?" / "确认停止?" / "confirm proxy?" dialog on either action. The user picks the row deliberately; don't ask again. Confirm dialogs are reserved for **destructive irreversible** actions only (delete account, delete IP, replace-IP-which-marks-old-dead). Anything that can be re-done with one more click should be fire-and-forget.
2. **No auto-injected window-title prefixes, no auto-favicon badges, no auto-color-coding.** When the user wants visual distinction across 20 windows, they will ask for it explicitly. Injecting title `[C001]` or canvas-drawn favicon badges via `evaluateOnNewDocument` is *over-engineering* and will be rejected. The MoreLogin/AdsPower bar at the top of the browser window (if any) is the only acceptable decoration — and CloakBrowser doesn't have one.
3. **Status annotation is user-driven, not test-driven.** Provide buttons the user clicks after the fact (`[✓ 完成]`, `[✗ 失败]`, custom chip labels). Do not auto-set status based on probe results, page detection, or heuristics. The user wants the system to record their decision, not make decisions for them.
4. **Tests are sampling, not gating.** Connectivity probes (proxy test, SOCKS5 reach) are diagnostic-only. Do not refuse to bind / launch / batch-create because tests failed. Residential IPs randomly fail handshakes; the binding is by ID order, not by test pass rate.
5. **Locks are manual.** `[▶ 开始]` locks, `[⏹ 停止]` unlocks. No auto-release on browser close, no auto-timeout. The user owns the account state.
6. **Defer aesthetics until asked.** Build the data plane and the action buttons first. Colors, labels, sort orders, badges — wait for the user to ask. If you "improve UX" speculatively, you'll get told to delete it.

Anti-pattern (what NOT to do):
```js
// ✗ Auto-injecting profile labels into every page
await page.evaluateOnNewDocument(`document.title = '[C001] ' + document.title`);
// ✗ Canvas-drawn favicon badge with profile number
// ✗ Modal asking "本次用途备注?" before launching
// ✗ Auto-marking account 'dead' because one probe failed
```

Right pattern:
```js
// ✓ Button click → lock + launch + toast. Done.
const r1 = await api.proxyLock(name, "");
const r2 = await api.proxyOpenBrowser(name);
toast(`✓ ${name} 已启动 (PID ${r2.pid})`);
```

This applies to any per-account/per-profile manager UI for this user, not just CloakBrowser — but CloakBrowser tools are where it comes up most.

## Batch proxy + identity management pattern

CloakBrowser has no GUI. Replicate MoreLogin's "account list + click to open" with CSV + script. See `templates/manager.py` and `templates/proxies.csv` for the working pattern:

- Each row = one identity (name, proxy, fingerprint_seed, note)
- `manager.py list` — show all identities
- `manager.py test` — batch test which proxies are alive
- `manager.py open <name>` — launch browser bound to that identity

**Discipline**: one account → one proxy → one fingerprint seed, forever. Mixing triggers fraud detection ("user's device suddenly changed").
