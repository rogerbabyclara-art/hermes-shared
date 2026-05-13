---
name: stealth-browser-automation
description: Drive source-code-level anti-detection Chromium browsers (CloakBrowser, nodriver, camoufox) instead of relying on third-party fingerprint browser software (MoreLogin/ADSPower/Multilogin). Use when building automations that must pass Cloudflare Turnstile / reCAPTCHA v3 / FingerprintJS / BrowserScan, or when replacing a paid fingerprint browser dependency with a self-hostable stealth Chromium. Covers install, basic launch, fingerprint seeding, persistent profiles, proxy injection, and the common pitfalls of mixing stealth Chromium with vanilla Puppeteer/Playwright.
---

# Stealth Browser Automation

## When to use this skill

Use when:
- You need to pass aggressive bot detection (Cloudflare Turnstile, reCAPTCHA v3, FingerprintJS, BrowserScan, DataDome) and stock Puppeteer/Playwright gets a 30–50% trust score.
- You're trying to drop a paid fingerprint browser (MoreLogin/ADSPower/Multilogin/Kameleo) because the per-profile cost or local API instability is hurting throughput.
- You want one self-contained npm/pip install instead of "install fingerprint browser app → start local API server → connect Puppeteer over WebSocket → manage profiles via REST".
- An automation already in the codebase (e.g. `azure-auto-reg-v2`) has accumulated a stack of hand-rolled anti-bot defenses (KMSI auto-clickers, real-mouse radio clicks, typing rhythm helpers, IP probes) — stealth Chromium can replace most of them.

Do NOT use when:
- The site has zero bot detection (regular Puppeteer is fine and lighter).
- You actually need to manage 100+ profiles with team sharing — that's MoreLogin/ADS territory, not stealth Chromium's.

## Tool comparison (pick one)

| Tool | Language | Underlying | Drop-in | Notes |
|---|---|---|---|---|
| **CloakBrowser** | Node + Python | Patched Chromium (49 C++ patches, ~535MB binary) | Playwright + Puppeteer | Most active, has `humanize` + `geoip` + `fingerprint` seed. Pip + npm + docker. |
| **nodriver** | Python only | Stock Chrome via CDP, no WebDriver | Custom API (not Playwright) | Lighter, no binary download. Less stealth than patched Chromium. |
| **camoufox** | Python | Patched Firefox | Playwright | Firefox-based, good for sites that fingerprint Chromium specifically. |

Default to **CloakBrowser** unless you have a specific reason — it has the most coverage, the cleanest drop-in API, and pip/npm parity.

## Install (CloakBrowser)

Three pieces. All three are needed; the binary is separate from the library because it's 535MB.

```bash
# Python
pip install cloakbrowser

# Node (in your project directory)
npm install cloakbrowser puppeteer-core

# Browser binary (one-time, ~535MB download, cached in ~/.cloakbrowser/)
python -m cloakbrowser install
```

Verify:
```bash
python -m cloakbrowser info    # shows version, path, platform
```

The binary lands in `~/.cloakbrowser/chromium-<version>/chrome.exe` (Windows) or equivalent. Both Python and Node libraries find it automatically.

## Minimal launch (the canonical four-knob recipe)

The same four parameters work identically in Python and Node.

**⚠️ Python API note (v0.3.x):** The README on GitHub still shows the older `from cloakbrowser.playwright import async_playwright` wrapper pattern. **That import does not exist in 0.3.28+.** The current API exposes a top-level `launch()` that returns a Playwright `Browser` object directly. Always verify with `python -c "from cloakbrowser import launch; import inspect; print(inspect.signature(launch))"` before writing code against a remembered example.

Current 0.3.x signature:
```
launch(headless=True, proxy=None, args=None, stealth_args=True,
       timezone=None, locale=None, geoip=False, backend=None,
       humanize=False, human_preset='default', human_config=None, **kwargs)
```

**Python (current API — sync, 0.3.x):**
```python
from cloakbrowser import launch

browser = launch(
    headless=False,        # visible window — always start here while learning
    humanize=True,         # bezier-curve mouse, real keyboard rhythm, scroll
    geoip=True,            # WebRTC IP leak protection + auto timezone/locale from IP
    args=["--fingerprint=12345"],  # seed passed via Chromium arg, NOT a top-level kwarg
)
context = browser.new_context()
page = context.new_page()
page.goto("https://www.browserscan.net/")
```

Note: `fingerprint` is **not** a top-level keyword argument in 0.3.x. Pass it through Chromium args: `args=["--fingerprint=<seed>"]`. Async variant: `from cloakbrowser import launch_async`.

**Node (Puppeteer API):**
```javascript
const { launch } = require('cloakbrowser/puppeteer');

const browser = await launch({
  headless: false,
  humanize: true,
  geoip: true,
  fingerprint: 12345,
});
const page = await browser.newPage();
await page.goto('https://www.browserscan.net/');
```

Templates: see `templates/demo_python.py` and `templates/demo_node.js`.

## The four knobs explained

- **`humanize`** — replaces hand-rolled "real mouse / real keyboard" helpers. When `true`, `page.click()` uses bezier-curve motion with overshoot; `page.type()` has per-keystroke jitter; scrolling is momentum-based. Removes the need for custom typing rhythm modules.
- **`geoip`** — when `true`, the browser's `Intl`, `navigator.language`, `Date.getTimezoneOffset()`, and WebRTC ICE candidates all match the egress IP. This is what trips most "your locale says JP but your IP is US" detectors. Replaces hand-rolled IP probes.
- **`fingerprint=N`** — integer seed. Same N produces the same Canvas/WebGL/AudioContext/font-list/screen/UA across the entire stack. Different N = different identity. This is the "free profile" — store the seed in your DB instead of paying MoreLogin per profile.
- **`headless`** — keep `false` during development. Stealth Chromium IS detectable in headless mode by some sites even with patches; use `--headless=new` only in production after you've verified the target site doesn't notice.

## Adding a proxy

`launch()` accepts `proxy` as either a URL string or a `ProxySettings` dict. The string form is simpler and works for HTTP/HTTPS/SOCKS5:

```python
# URL string form — preferred, works for HTTP and SOCKS5
browser = launch(
    headless=False, humanize=True, geoip=True,
    args=["--fingerprint=12345"],
    proxy="http://user:pass@host:port",
    # or "socks5://user:pass@host:port"
)
```

When `geoip=True`, the browser's timezone/locale auto-derives from the proxy's exit IP — do not manually pass `timezone` / `locale` (they will conflict with geoip).

**Always verify the proxy before launching the browser** — see `references/proxy-verification.md` for the curl-based HTTP/SOCKS5/ASN check. A "JP residential" proxy that actually exits from a Chinese 5G mobile IP will burn your Azure/Google signup before the browser even opens.

**CloakBrowser ≥0.3.x natively accepts `socks5://` in the `proxy` field** — it detects the scheme in `isSocksProxy()` and passes `--proxy-server=socks5://...` directly to Chromium. You do NOT need to install `socks-proxy-agent` for the browser itself. You DO need `socks-proxy-agent` (Node) or `httpx[socks]` / `python-socks` (Python) only when your management UI / verification code wants to call APIs (like ipinfo.io) over the proxy from outside the browser context. Typical Node-side install for that out-of-band check:

```bash
npm install socks-proxy-agent https-proxy-agent
```

## Persistent profiles (cookies, localStorage, etc.)

Use `launch_persistent_context` (sync) or `launch_persistent_context_async`. Pass a directory; everything in that dir (cookies, IndexedDB, service workers) survives across runs.

```python
from cloakbrowser import launch_persistent_context

context = launch_persistent_context(
    user_data_dir="./profiles/seed_12345",
    headless=False, humanize=True, geoip=True,
    args=["--fingerprint=12345"],
)
```

Pair the directory name with the fingerprint seed (e.g. `profiles/seed_12345/`) so you don't accidentally reuse a directory with a different seed — that produces the worst possible signal: "same cookies, different canvas".

## Migrating off MoreLogin / ADSPower / Multilogin

Typical migration from a `puppeteer.connect({browserWSEndpoint: ...})` setup against MoreLogin:

| Hand-rolled defense | Replaced by |
|---|---|
| MoreLogin REST API to start/stop profile env | `launch()` directly with a fingerprint seed |
| Custom typing rhythm module (`typing.js`) | `humanize=true` |
| "Real mouse" radio/checkbox clickers via bounding box + bezier | `humanize=true` |
| KMSI auto-clicker injected via `evaluateOnNewDocument` | Often still needed — humanize doesn't drive page logic, only input rhythm |
| IP probe (request httpbin, check egress, compare to expected locale) | `geoip=true` (matches automatically) |
| First-name validation / form sanity checks | Still needed — those check for OTHER bugs, not bot detection |

Keep hand-rolled defenses that protect against **flow correctness** (KMSI page appearing unexpectedly, form fields not committing). Drop hand-rolled defenses that protect against **fingerprint/rhythm detection** — humanize+geoip+fingerprint cover those.

## Common pitfalls

1. **Mixing stock `puppeteer` with `cloakbrowser/puppeteer`** — install `puppeteer-core` (NOT `puppeteer`). Stock `puppeteer` ships its own Chromium and the two will fight over which binary to launch. CloakBrowser's launcher injects the patched binary path; let it.

2. **Running from git-bash on Windows when the browser needs to be visible** — git-bash's MSYS subsystem sometimes mishandles GUI process spawning. If `headless=False` produces no visible window, retry from cmd or PowerShell.

3. **`python -m cloakbrowser install` fails behind corporate proxy** — the installer downloads from CloakBrowser's CDN, not GitHub. Set `HTTPS_PROXY` env var before running it.

4. **Same fingerprint seed across different proxies** — defeats the point. The site will see "same Canvas fingerprint from 5 different IPs in 10 minutes" which is worse than no stealth at all. Rule: one fingerprint seed ↔ one persistent profile dir ↔ one proxy identity.

5. **Assuming `humanize=true` makes `page.click(selector)` slow** — it does add 200–800ms per action. For high-throughput scenarios this matters; for account registration it's a feature, not a bug.

6. **PATH warnings during pip install** — `cloakbrowser.exe` / `playwright.exe` scripts install under `%APPDATA%\Python\Python3XX\Scripts\` which is often not on PATH. You don't need them on PATH if you call via `python -m cloakbrowser ...` instead of bare `cloakbrowser`. The warning is cosmetic.

7. **`headless=True` defeats stealth on some sites** — even patched Chromium leaks the `HeadlessChrome` UA token and missing window decorations in true headless mode. Use `--headless=new` (Chromium's new headless mode) via launch args, not legacy headless, and verify on BrowserScan first.

8. **README on GitHub is behind the published package** — the README in `CloakHQ/CloakBrowser` repo shows playwright-wrap patterns (`from cloakbrowser.playwright import async_playwright`) that no longer exist in 0.3.28+. Trust `inspect.signature(launch)` over the README. The README also shows `fingerprint=N` as a top-level kwarg; in 0.3.x it's `args=["--fingerprint=N"]`.

9. **Proxy provider lies about exit country** — username parameters like `region-JP`, `country-jp`, `geo-JP` are NOT a standard; each provider has its own grammar, and a malformed/unsupported flag silently falls back to a random IP in the default pool. Always verify the actual exit IP and ASN with curl before trusting the proxy (see `references/proxy-verification.md`). A real example from a live session: a `zmeq107638-region-JP-sid-...` username on cliproxy.io returned a Chinese 5G mobile IP in Wuhan, not Japan.

10. **Electron host does NOT inherit Windows system proxy** — if you embed stealth Chromium inside an Electron app (management UI launches browser children), and the user has v2rayN / Clash / Shadowsocks set to "PAC mode" or "Global mode" (system proxy), **neither Electron itself nor any Node child processes it spawns will route through the proxy**. Chromium ignores Windows system proxy by default; Node's `http`/`https` modules never read it. Symptoms: vendor returns `NotAllowed` / `Connection refused` from inside the app, but the same proxy works when tested with `curl` from cmd/PowerShell with system proxy on. **Fix: instruct user to enable v2rayN TUN mode** (virtual NIC, kernel-level traffic capture). TUN intercepts everything including Electron/Chromium/Node regardless of system proxy settings, and is also what the actual production automation needs anyway (so fixing it now prevents the same bug at run-time). Verify with `node -e "require('https').get('https://ipinfo.io/json', r => r.on('data', c => console.log(c.toString())))"` — must show the proxy's egress country.

11. **`socks-proxy-agent` v8+ and `https-proxy-agent` v7+ are ESM-only** — they ship as pure ESM, no CommonJS exports. In a CJS Electron main process (`require()`-based), `require("socks-proxy-agent")` throws `ERR_REQUIRE_ESM`. Fix without rewriting the whole project to ESM: use dynamic `import()` lazily and cache the module:

    ```js
    let _socksMod;
    async function getSocksAgent(url) {
      if (!_socksMod) _socksMod = await import("socks-proxy-agent");
      return new _socksMod.SocksProxyAgent(url);
    }
    ```

    Note this only matters for **out-of-band proxy checks** from your management code (e.g. testing a proxy entry with a quick HTTPS request through it). CloakBrowser itself doesn't need these libraries — it accepts `socks5://` directly. Avoid pinning to v6/v5 of the old packages — they have known TLS bugs with modern Node.

12. **Orphan Chromium processes on Windows when host kills the launcher** — if your management UI spawns a Node launcher that calls `launch()`, and you stop the browser by calling `child.kill()` / `child.kill('SIGTERM')` on the Node child, **on Windows the Chromium browser process (and its 5–10 renderer/GPU/utility children) are NOT killed**. `child.kill()` on Windows maps to `TerminateProcess()` on the single PID — there is no signal delivery, no parent-tracked process group, and Chromium's main process detaches itself from the Node launcher at startup. Result: every "start → stop" cycle leaks ~6 Chromium processes consuming 100–300MB each. After a few hours of testing the task manager shows 30+ orphan `chrome.exe` and the machine swaps. Symptoms in the UI: status indicator stuck on "running" / "locked" because the launcher exited but children kept the lock file alive; user clicks refresh / kills manually. **Two distinct symptom patterns to recognize**: (a) RAM symptom — chrome.exe count grows monotonically across start/stop cycles; (b) CPU symptom — **identical CPU% across N orphan Chromium rows in Task Manager** (e.g. 4 processes all at exactly 5.5%), which means each orphan's renderer is running the same injected `setInterval` doing periodic work (favicon repaint, polling fetch, etc.) and those intervals never stop because the parent isn't there to tell them to. The CPU pattern is also a smoking gun that your `evaluateOnNewDocument` injected code uses polling where MutationObserver would do. **Fix is two-stage shutdown PLUS a parent-death watchdog in the launcher — see `references/windows-process-tree-cleanup.md` for the full recipe** (graceful stdin-close → `taskkill /F /T /PID` fallback, `app.on('before-quit')` hook for Electron hosts, `process.on('SIGTERM'|'SIGINT')` + `process.stdin.on('end'|'close')` listeners in the launcher to call `browser.close()` cleanly so the profile dir isn't corrupted, AND a `setInterval(() => process.kill(ppid, 0), 5000)` self-suicide watchdog covering the case where Electron hard-crashes and stdin never gets closed cleanly). The reference also documents the MutationObserver+visibilitychange replacement for polling injects, and the "even admin taskkill can't kill these" recovery path once orphans already exist.

14. **`cloakbrowser/puppeteer` silently ignores the `userDataDir` option** — the Playwright wrapper (`cloakbrowser/playwright`) routes `userDataDir` to `chromium.launchPersistentContext()`, so persistence works. **The Puppeteer wrapper (`cloakbrowser/puppeteer`) has no equivalent code path** — it passes `options` to `puppeteer-core.launch()` which simply discards `userDataDir` (Puppeteer wants `--user-data-dir=` in `args`, not a top-level option). Symptoms: (a) the directory you specified gets `mkdir`'d by your management code but stays **empty** — no `Default/`, no `Preferences`, no `Cookies` — across multiple browser sessions; (b) BrowserScan / FingerprintJS detection labels the session as **"incognito" / "InPrivate" −10%** because Chromium falls back to an in-memory temp profile; (c) cookies/localStorage do not survive close/reopen, so re-login is required every session — this is the most damaging symptom for 100-account workflows because it negates the whole "one-fingerprint-one-profile" architecture.

    **Fix: pass `--user-data-dir=<path>` through `args` alongside any `userDataDir` field** (keep the field for playwright-wrapper compatibility, but the args entry is what Chromium actually reads in the puppeteer path):

    ```javascript
    const launchArgs = [`--fingerprint=${FINGERPRINT}`];
    if (USER_DATA_DIR) launchArgs.push(`--user-data-dir=${USER_DATA_DIR}`);

    const launchOpts = {
      headless: false, humanize: true, geoip: true,
      args: launchArgs,
    };
    if (PROXY_URL) launchOpts.proxy = PROXY_URL;
    if (USER_DATA_DIR) launchOpts.userDataDir = USER_DATA_DIR; // harmless on puppeteer, needed on playwright
    const browser = await launch(launchOpts);
    ```

    **Verification — do this before trusting any "profile per account" claim:** open a browser via your management UI, navigate to any site, close it cleanly. Then run `ls <profile_dir>` from the shell — you must see at least `Default/`, `Local State`, `Preferences`. An empty directory means the option was ignored regardless of what the management UI shows. Cross-check with BrowserScan — the "incognito mode" indicator must NOT trigger; if it does, the args fix isn't in effect.

    Path quoting on Windows: `--user-data-dir=C:\Users\roger\path with spaces` — Chromium accepts the unquoted form when passed through Puppeteer's spawn (each arg is its own argv entry; no shell quoting needed). Don't wrap the value in extra `"`s, that lands in argv as a literal quote character and Chromium falls back to default.

16. **Hand-rolled `stealth.js` left over from pre-CloakBrowser era is now a leak source, not a defense** — projects migrated from MoreLogin / ADSPower / puppeteer-extra-stealth often carry a `stealth.js` file applied via `evaluateOnNewDocument` after `puppeteer.connect()`. Every `Object.defineProperty(Foo.prototype, 'bar', { get: () => ... })` in that file is now a **regression**: (a) CloakBrowser's binary already returns the correct values; (b) the JS-defined accessor's `toString()` shape differs from a real `[native code]` getter (function **name** is missing — real Chrome returns `function get bar() { [native code] }`, the hook returns `function () { [native code] }`), and FingerprintJS (2024+) explicitly checks this shape as a stealth-plugin signature. Hardcoded values like `WebGLRenderingContext.prototype.getParameter` returning `'Intel Inc.'` / `'Intel Iris OpenGL Engine'` (mac string!) collapse per-seed entropy — 100 fingerprint seeds all share one GPU string, detectable as a botpool. **Fix: delete the stealth.js file's prototype-hook section entirely.** Keep only items that are business logic, not stealth — e.g. `navigator.credentials.create/get` rejection to prevent the OS-level "Save passkey?" dialog after Microsoft login. Trust CloakBrowser's binary for webdriver/plugins/languages/WebGL/iframe — verify with the self-check script in `references/fingerprint-audit-checklist.md`. **When the project owner says "check if anything else is leaking", run the static grep audit + DevTools self-check from that reference before touching code.**

   **Gut-rewrite procedure (do not edit-in-place, replace the file):**
   1. `cp azure/stealth.js azure/stealth.js.bak-$(date +%s)` — 30-second rollback path.
   2. Overwrite `azure/stealth.js` with `templates/stealth_webauthn_only.js` from this skill (drop-in, same exports — `applyStealth` / `applyStealthToBrowser` / `STEALTH_SCRIPT` — callers do not change).
   3. `node --check azure/stealth.js && node -e "console.log(require('./azure/stealth.js').STEALTH_SCRIPT.length)"` — expect ~860 chars vs the legacy ~4500.
   4. `grep -rn "stealth" azure/ proxy/ main.js | grep -v node_modules | grep -v .bak` — confirm no caller imports symbols beyond the three exports.
   5. Launch one fresh account (not one that already ran on the old code — cookies are fine, but verify the new injects actually fire) and run the DevTools self-check from `references/fingerprint-audit-checklist.md`. Required deltas: `webdriver_toString` becomes `function get webdriver() { [native code] }`, `plugins.length` becomes 1, `webgl_renderer` becomes an ANGLE-prefixed Windows GPU string (not "Intel Iris OpenGL Engine").
   6. Already-completed accounts (cookies in place, no re-login needed) are unaffected. In-flight accounts mid-flow keep the old inject until the browser restarts — usually fine, but if paranoid, finish them on the old code and let new starts pick up the rewrite.

17. **Persistent profile `Preferences.intl.accept_languages` overrides command-line `--lang`** — once a profile dir has been launched once with a wrong/missing locale, `Default/Preferences` records `intl.accept_languages = "zh-CN,..."` (taken from system locale). On every subsequent launch, **this user-preference layer wins against the launcher's `locale: 'ja-JP'`** for HTTP `Accept-Language` headers and Chrome's translate infobar. The C++ patch (`--fingerprint-locale=ja-JP`) still affects `navigator.language` and `Intl`, so DevTools shows the correct locale — but the Microsoft login server sees `Accept-Language: zh-CN` from the request headers and **serves Chinese UI** anyway. Smoking gun: page UI is Chinese while `navigator.language` is `ja-JP`. Fix: in the launcher's pre-launch pref-clean block (same place `exit_type = 'Normal'` is applied), explicitly rewrite `prefs.intl.accept_languages`, `prefs.intl.selected_languages`, `prefs.translate_blocked_languages`, and `prefs.translate.enabled = false`. The translate flag disables Chrome's "Translate this page?" infobar, which on a Chinese OS pops up for every Japanese page and is itself a tell that OS locale ≠ page locale.

18. **Gateway-style SOCKS5 + `geoip: true` alone fails silently — explicit `locale`/`timezone` is mandatory** — when the proxy is a sticky-session gateway (`us.cliproxy.io:3010` with usernames encoding the exit region like `region-JP-sid-XXX-t-60`), `geoip: true` does a DNS lookup on the proxy hostname and a GeoIP lookup on **that IP** (the gateway, usually US-located) — NOT the exit IP the username selects. Result: `Intl` and `navigator.language` get set to the gateway's region, **not the target region encoded in the username**. The browser ships with the wrong locale on a JP-targeted account and instantly fails detection. Also: WebRTC IP spoofing (`--fingerprint-webrtc-ip=auto`) fails the same way — gateway resolution returns the wrong IP or no IP, the flag is removed silently, WebRTC reports the user's REAL local IP next to a JP-locale browser. Diagnostic in CloakBrowser log: `Could not resolve proxy exit IP for WebRTC spoofing; removing --fingerprint-webrtc-ip=auto`. **Fix: always pass explicit `locale` + `timezone` for gateway-style proxies. Keep `geoip: true` (explicit values win in `args.js` dedup, geoip still tries WebRTC resolution). If you've separately probed the exit IP for each account and stored it (`account.last_test_ip`), inject it directly: `launchArgs.push(\\`--fingerprint-webrtc-ip=${account.last_test_ip}\\`)` — bypasses mmdb-lib's flaky resolution. CloakBrowser's README confirms this in one line: "For rotating residential proxies, the DNS-resolved IP may differ from the exit IP. Pass explicit `timezone`/`locale` in those cases."

19. **Mainland-CN-egress vendor restrictions** — most major residential proxy vendors (711proxy explicitly, others implicitly) **refuse connections from mainland China egress IPs** at the SOCKS handshake level. The error looks identical to "wrong password" / "not whitelisted" (`NotAllowed`, reply code 2). If your user is in CN and reports universal NotAllowed across a vendor, **check the vendor's TOS / dashboard first** — most have a banner stating "not available from mainland China network". Solution is for the user to put a non-CN egress (HK/JP/SG VPS via TUN-mode VPN) in front of the vendor. This is BEFORE the stealth browser ever opens.

## Verification

After install, verify stealth is actually working before building anything on top:

```bash
# from D:\Projects\cloak-test or wherever you installed
python templates/demo_python.py
```

Open BrowserScan / pixelscan.net / bot.sannysoft.com and check the score:
- Stock Puppeteer: 30–50% (lots of red)
- puppeteer-extra-stealth: 70–85%
- CloakBrowser default: 95–100%

If you see <90%, something's wrong — usually `humanize` or `geoip` is off, or you're behind a proxy whose locale doesn't match `geoip`'s output. Open DevTools, check `navigator.webdriver` (should be `undefined`), check `navigator.languages` matches IP.

## Reference material

- `templates/demo_python.py` — minimal Python launch (0.3.x API), visits BrowserScan
- `templates/demo_node.js` — same in Node
- `templates/stealth_webauthn_only.js` — drop-in replacement for legacy `stealth.js` files inherited from MoreLogin/ADSPower/puppeteer-extra-stealth era. WebAuthn rejection only; all prototype hooks removed. Same exports (`applyStealth`, `applyStealthToBrowser`, `STEALTH_SCRIPT`) so callers do not change. Pair with pitfall #16's gut-rewrite procedure.
- `references/cloakbrowser-api-knobs.md` — full parameter reference + when each one matters
- `references/migration-from-fingerprint-browsers.md` — step-by-step migration plan from MoreLogin/ADS-based automations (full rewrite path)
- `references/cdp-bridge-adapter-pattern.md` — **alternative to full rewrite**: keep the old `flow.js` (5000+ LOC) untouched and only swap the browser layer beneath it via a CDP wsEndpoint adapter shim. Use when the old automation is battle-tested or the browser is owned by a separate UI (Electron panel). Covers: how CloakBrowser exposes `browser.wsEndpoint()` for free, the launcher→host stdout protocol, the 5-function adapter shim template mirroring `morelogin.js`, the lifecycle-ownership shift (`stopEnv` becomes no-op, UI owns the browser), and 5 pitfalls (circular require, ws vs browserURL field confusion, premature adapter calls, mid-flow restart staleness, where puppeteer.connect should live).
- `references/proxy-verification.md` — curl-based HTTP/SOCKS5/ASN check to run BEFORE wiring a proxy into the browser (catches fake residential / mislabeled country)
- `references/proxy-format-parsing.md` — parsing the 8 residential proxy credential formats operators paste (`host:port:user:pass`, `socks5://...`, reverse forms, no-auth, etc.). Includes the 9-line sanity test input.
- `references/multi-account-proxy-binding.md` — architecture for 1:1 account↔IP binding with reserve pool, manual lock, and the "replace IP" failover flow. Use when running 10–100 long-lived accounts (Azure signup, social ops) as opposed to scraping.
- `references/multi-window-visual-labeling.md` — favicon-canvas + title-MutationObserver injection so an operator running 20+ concurrent windows can tell them apart in the Windows taskbar. Covers the 3 Puppeteer integration points (`evaluateOnNewDocument` + initial pages + `targetcreated`) needed for labels to survive navigations / OAuth popups / SPAs, **and the two-process race when an upstream worker `puppeteer.connect()`s to a launcher's wsEndpoint and `newPage()`s before the launcher's `targetcreated` finishes registering injects — both sides must inject, the idempotency guard makes it cheap**.
- `references/account-panel-ux.md` — how the management UI on top of `multi-account-proxy-binding.md` should *feel*: AdsPower-style table (multi-select + Shift+click range-select with text-selection cleanup + batch bar + inline edit + tag chips + tag preset management modal with color-chip quick-pick + status pill), hard rules (no confirms on routine actions, no auto-writing into user's `notes`, no `ipinfo.io` default page, process-exit must clear lock state, top-toolbar entry buttons for essential features must NOT be `ghost`-styled), and the columns + interactions to ship by default.
- `references/windows-process-tree-cleanup.md` — two-stage shutdown recipe for killing Chromium **and all its children** when the host is Node/Electron on Windows. Covers the `child.kill()` orphan-process bug, the `taskkill /F /T` fix, launcher-side SIGTERM/stdin listeners for graceful `browser.close()`, batch parallel close, the Electron `before-quit` cleanup hook, **the CPU-pattern fingerprint of orphan loops (identical % across N processes = injected `setInterval` running forever in renderers), the MutationObserver+visibilitychange replacement for polling injects, the MutationObserver self-feedback infinite loop footgun (worse CPU than the original polling — needs silent-flag + `setTimeout(0)` deferred release), the parent-death self-suicide watchdog in the launcher (`process.kill(ppid, 0)` every 5s) covering hard-crash paths stdin can't, and what to do when orphans are unkillable even with admin `taskkill` (Process Explorer / pskill / reboot)**.
- `references/fingerprint-audit-checklist.md` — **audit an already-running CloakBrowser automation for fingerprint regressions.** Use when the owner reports a smoking gun (Chinese UI on JP IP, captcha rate spike, account bans right after signup) and you need to systematically verify nothing is leaking. Covers: the static grep audit (legacy prototype hooks, hardcoded GPU strings, `cdc_*` deletes, `waitForTimeout`, missing `locale`/`timezone`), the DevTools Console self-check script with field-by-field interpretation grid (lang/langs/tz/webdriver/toString-shape/WebGL/IP-country), and the 6 specific leak patterns seen in real V3-migration projects with their fixes (inherited stealth.js prototype hooks, hardcoded WebGL across all profiles, gateway-proxy + geoip-alone, persistent `Preferences.intl` retaining old locale, WebRTC IP not explicitly bound, translate prompt revealing OS-locale mismatch). **Mental model: every JS stealth override fights CloakBrowser's binary patches — delete first, verify with the self-check, add back only when audit shows a specific binary-side gap.**
