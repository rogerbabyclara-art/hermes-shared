# Fingerprint Audit Checklist (CloakBrowser + Puppeteer)

Use when an existing automation **already runs** and you need to verify it isn't leaking. Different from initial-setup checks: at this stage there is usually hand-rolled stealth code, accumulated `Preferences` state, and `evaluateOnNewDocument` injects from earlier eras (puppeteer-extra-stealth, ADSPower migration, etc.) that **fight CloakBrowser's C++ patches**.

Symptom that triggers an audit: the user / project owner sees something obviously wrong (browser shows Chinese UI on a Japanese IP, captcha rates spike, accounts get banned right after signup) and asks "check if anything else is leaking before we burn more accounts".

## The mental model (critical — apply before every fix)

CloakBrowser is a **48-source-level-C++-patch Chromium**. Its job is to make `navigator.*`, `Intl.*`, Canvas/WebGL/Audio/font fingerprints look like a real Chrome on the configured platform/locale/timezone seed. **Anything you do in JS via `evaluateOnNewDocument` to "harden" stealth is at best redundant and at worst a regression** — because:

- Real Chrome accessors return `function get webdriver() { [native code] }`. JS `Object.defineProperty(Navigator.prototype, 'webdriver', { get: () => false })` returns `function () { [native code] }` — the function **name** is missing. FingerprintJS (2024+) specifically checks this toString shape and uses it as a stealth-plugin signature. The hook designed to hide bot-ness becomes the strongest bot signal.
- The same toString-leak applies to **every** `Object.defineProperty(Foo.prototype, 'bar', { get })` override. Languages, plugins, hardwareConcurrency, deviceMemory, WebGL parameter override, iframe.contentWindow — all of them.
- Hardcoded values across N profiles (e.g. WebGL renderer set to `"Intel Iris OpenGL Engine"` for all 100 accounts) collapse the per-seed entropy CloakBrowser worked to generate. 100 different fingerprint seeds suddenly share one identical GPU string. This is **detectable as a botpool** even if individual sessions pass.

**Rule:** if CloakBrowser's binary is supposed to handle a fingerprint dimension (and `references/cloakbrowser-api-knobs.md` lists what it covers), **do not also hand-roll it in JS**. Delete the JS layer, trust the binary, verify with the audit script below.

## Phase 1 — Static audit (grep the codebase)

Run these against the project root. Each hit is a candidate leak/regression to inspect:

```bash
# 1. Legacy JS prototype hooks (toString-leak risk)
grep -rn "defineProperty.*\(Navigator\|HTMLIFrameElement\|Screen\|Plugin\).*prototype" --include="*.js" .

# 2. Hardcoded fingerprint values (entropy collapse risk)
grep -rn "Intel Inc\.\|Intel Iris\|NVIDIA Corporation\|AMD\|GeForce\|Radeon\|Mesa" --include="*.js" .
grep -rn "navigator\.\(plugins\|languages\|platform\|userAgent\|hardwareConcurrency\|deviceMemory\)\s*=" --include="*.js" .

# 3. ChromeDriver cdc_ vars deletion (puppeteer doesn't inject these — deleting them flags you as "knows the stealth playbook")
grep -rn "cdc_adoQpoasnfa" --include="*.js" .

# 4. waitForTimeout in flow code (sends CDP traffic reCAPTCHA detects)
grep -rn "page\.waitForTimeout\|frame\.waitForTimeout" --include="*.js" .

# 5. page.fill vs page.type (fill bypasses keyboard events, behavioral analysis flags it)
grep -rn "page\.fill\|\.fill(" --include="*.js" .   # use page.type instead

# 6. Explicit locale/timezone in launch options (must be present when proxy is a gateway-style sticky session)
grep -rn "geoip\|locale:\|timezone:" proxy/ src/ launcher* 2>/dev/null

# 7. Are launch args minimal? Extra args overriding stealth defaults
grep -B1 -A5 "launchArgs\|args:\s*\[" proxy/launcher* 2>/dev/null
```

## Phase 2 — Runtime audit (DevTools self-check)

After `launcher` changes, open ONE browser via the management UI, open DevTools Console, paste this and share the output:

```javascript
// FINGERPRINT SELF-CHECK — paste into DevTools Console of a CloakBrowser session
(async () => {
  const r = {
    // --- locale layer ---
    lang: navigator.language,
    langs: navigator.languages,
    tz: Intl.DateTimeFormat().resolvedOptions().timeZone,
    // --- automation layer ---
    webdriver: navigator.webdriver,
    // CRITICAL: this string must contain the property name "webdriver"
    // Real Chrome:  "function get webdriver() { [native code] }"
    // JS hook leak: "function () { [native code] }"  <-- bot signature
    webdriver_toString: Object.getOwnPropertyDescriptor(Navigator.prototype, 'webdriver')?.get?.toString() || '(no descriptor)',
    // --- entropy layer (must vary per seed) ---
    hardware_concurrency: navigator.hardwareConcurrency,
    device_memory: navigator.deviceMemory,
    platform: navigator.platform,
    ua: navigator.userAgent,
    plugins_count: navigator.plugins.length,
    plugins: Array.from(navigator.plugins).map(p => p.name),
    webgl_vendor: null,
    webgl_renderer: null,
  };
  try {
    const c = document.createElement('canvas').getContext('webgl');
    const ext = c.getExtension('WEBGL_debug_renderer_info');
    r.webgl_vendor = c.getParameter(ext.UNMASKED_VENDOR_WEBGL);
    r.webgl_renderer = c.getParameter(ext.UNMASKED_RENDERER_WEBGL);
  } catch (e) {}
  try {
    // --- network/proxy layer ---
    const ip = await fetch('https://ipapi.co/json/').then(r => r.json());
    r.ip = ip.ip;
    r.ip_country = ip.country_name;
    r.ip_tz = ip.timezone;
    r.ip_asn = ip.asn + ' ' + ip.org;
  } catch (e) {}
  console.log(JSON.stringify(r, null, 2));
})();
```

## Phase 3 — Interpretation grid

For an account region of e.g. Japan (ja-JP / Asia/Tokyo):

| Field | Expected | Bad signal |
|---|---|---|
| `lang` | `"ja-JP"` | `"zh-CN"`, `"en-US"` ← Preferences leaks system locale |
| `langs` | `["ja","ja-JP","en-US","en"]` | `["zh-CN","en"]` ← Preferences.intl.accept_languages wrong |
| `tz` | `"Asia/Tokyo"` | `"Asia/Shanghai"`, `"America/New_York"` ← geoip resolved gateway IP instead of exit IP |
| `webdriver` | `false` | `true` ← C++ patch not active (wrong binary?) |
| `webdriver_toString` | contains the name `webdriver` and `[native code]` | name missing → JS hook leak; not `[native code]` → hook |
| `hardware_concurrency` | varies per seed (4/6/8/12/16) | identical across all profiles |
| `webgl_renderer` | varies per seed, plausible Windows GPU | `"Intel Iris OpenGL Engine"` (mac string) or identical across all profiles |
| `plugins` | `["PDF Viewer", "Chrome PDF Viewer", "Chromium PDF Viewer", "Microsoft Edge PDF Viewer", "WebKit built-in PDF"]` (modern Chrome's default 5) | 0 plugins (headless) or other counts (custom inject) |
| `ip_country` | matches target region | mismatch = burned proxy or wrong username flag |
| `ip_tz` | matches `tz` | mismatch = locale layer doesn't match network layer = strongest detection signal |

## Phase 4 — Known leak patterns and their fixes

These are the **specific regressions** seen in real V3-migration projects:

### 4.1 Inherited `stealth.js` from a pre-CloakBrowser era

Pattern: a file like `azure/stealth.js` or `src/anti-detect.js` exists from when the project ran on ADSPower / MoreLogin / puppeteer-extra-stealth, applying `evaluateOnNewDocument` overrides. After migration to CloakBrowser it's still being injected via `applyStealthToBrowser(browser)` after `puppeteer.connect()`.

**Diagnosis:** every prototype hook in that file is now a regression. CloakBrowser's binary already returns the correct values; the JS hook overwrites them with a hooked-looking accessor.

**Fix:** delete the file entirely, OR keep only the items that are **business logic, not stealth**:
- ✅ keep: WebAuthn / `navigator.credentials.create/get` disabling (prevents the OS-level "Save passkey?" dialog popping up after Microsoft login — that's a UX/flow concern, not a fingerprint concern)
- ❌ delete: webdriver override, plugins override, languages override, WebGL parameter override, iframe.contentWindow override, `delete window.cdc_*`

### 4.2 Hardcoded values across all profiles

Pattern: `WebGLRenderingContext.prototype.getParameter` returns `'Intel Inc.'` / `'Intel Iris OpenGL Engine'` for all profiles.

**Diagnosis:** 100 fingerprint seeds → 1 GPU string. Per-seed entropy collapsed.

**Fix:** delete the override. CloakBrowser generates a different (plausible Windows) GPU per fingerprint seed in the C++ layer.

### 4.3 Gateway-style sticky-session proxy + `geoip: true` alone

Pattern: proxy is something like `us.cliproxy.io:3010` with username `region-JP-sid-XXX-t-60` — one DNS entry, the locale/region is encoded in the username. `launch({ geoip: true })` is set but `locale` / `timezone` are not.

**Diagnosis:** `geoip: true` uses `mmdb-lib` to do a DNS lookup on the proxy host, then a GeoIP lookup on **that IP** — which is the gateway IP, often US-located, not the exit IP that the username selects. Result: `Intl` and `navigator.language` get set to the gateway's region (en-US), not the target region (ja-JP). Browser UI shows Chinese-via-system-locale or English-via-gateway; either way doesn't match the proxy exit IP's country → strongest possible detection signal.

CloakBrowser's README confirms this in one line: *"For rotating residential proxies, the DNS-resolved IP may differ from the exit IP. Pass explicit `timezone`/`locale` in those cases."*

**Fix:** always set explicit `locale` + `timezone` when the proxy is gateway-style. Keep `geoip: true` as well — explicit values win in `args.js` dedup logic but `geoip` still resolves the real exit IP for WebRTC spoofing (`--fingerprint-webrtc-ip=auto` → `--fingerprint-webrtc-ip=<exit_ip>`).

```javascript
const launchOpts = {
  locale: 'ja-JP',
  timezone: 'Asia/Tokyo',
  geoip: true,   // keep it for WebRTC IP resolution
  proxy: PROXY_URL,
  args: launchArgs,
};
```

### 4.4 Persistent profile `Preferences` retaining old locale

Pattern: profile was created during a test run with system locale `zh-CN` and no explicit `locale` argument. `~/.cloakbrowser/<profile>/Default/Preferences` now contains:

```json
{ "intl": { "accept_languages": "zh-CN,zh,en-US,en", "selected_languages": "zh-CN" } }
```

Even after fixing the launcher to pass `locale: 'ja-JP'`, this user preference layer **overrides** Chromium's command-line `--lang` for HTTP `Accept-Language` headers and the in-page UI strings.

**Diagnosis:** Chromium's effective language resolution: command-line `--lang` → `Preferences.intl.accept_languages` → system locale. Per-profile preferences win against the command line for actual page rendering.

**Fix:** at every launch, before connecting, **rewrite** the `Default/Preferences` file to force the target locale. Same place the `exit_type = 'Normal'` fix is applied (see launcher pref-clean block) — just add the intl keys:

```javascript
prefs.intl = prefs.intl || {};
prefs.intl.accept_languages = 'ja,ja-JP,en-US,en';
prefs.intl.selected_languages = 'ja';
prefs.translate_blocked_languages = ['ja'];
prefs.translate = prefs.translate || {};
prefs.translate.enabled = false;   // suppress "translate this page?" prompt for ja pages
```

The translate-prompt suppression matters: a Chinese system seeing a Japanese page will pop the translate bar, which is a strong tell that the OS locale ≠ page locale. Disabling Chrome's translate feature in Preferences kills it.

### 4.5 WebRTC IP not explicitly bound

Pattern: `geoip: true` and `proxy:` are both set, but the proxy is a gateway-style SOCKS5 with sticky-session usernames. mmdb-lib's exit-IP resolution often fails for this kind of proxy because it does a DNS lookup on the host (returns gateway IP) instead of a real connection probe.

**Diagnosis:** when exit-IP resolution fails, CloakBrowser logs `Could not resolve proxy exit IP for WebRTC spoofing; removing --fingerprint-webrtc-ip=auto` and falls back to the real local IP for WebRTC ICE candidates. Sites that probe WebRTC (Cloudflare bot management does) see the user's actual Chinese residential IP next to a JP-locale browser → instant detection.

**Fix:** if you already know the exit IP for each account (e.g. you probed it during proxy setup and stored `last_test_ip`), inject it explicitly via args:

```javascript
const launchArgs = [`--fingerprint=${FINGERPRINT}`];
if (USER_DATA_DIR) launchArgs.push(`--user-data-dir=${USER_DATA_DIR}`);
if (account.last_test_ip) launchArgs.push(`--fingerprint-webrtc-ip=${account.last_test_ip}`);
```

This skips mmdb-lib's flaky resolution entirely. The flag is the same one `geoip:true` would set on success.

### 4.6 Translate prompt revealing system locale mismatch

Pattern: page loads in Japanese (correctly localized by CloakBrowser), but Chrome's translate infobar pops up offering "Translate to Chinese?" because the user's OS locale is `zh-CN`.

**Diagnosis:** Chrome translate uses the OS UI language as the target language, not Preferences. A Chinese OS will always offer to translate non-Chinese pages.

**Fix:** disable translate entirely in Preferences (see 4.4). Also consider `translate_blocked_languages: ['ja', 'en']` to whitelist the source languages you visit.

## When in doubt: lean toward the binary

The team behind CloakBrowser ships and updates a hardened Chromium binary specifically for this purpose. Their JS surface is intentionally minimal. **Every line of stealth JS you write is a line that has to be maintained in lockstep with Chromium's evolving exposed-attribute surface** (e.g. when Chrome 145 added `navigator.userAgentData` — does your override cover it? when Chrome 146 changed the toString shape of getters?). Delete first, verify with the self-check, add JS overrides only when the audit shows a specific binary-side gap.
