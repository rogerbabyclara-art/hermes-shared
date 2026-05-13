# CloakBrowser API knob reference

Versions verified: `cloakbrowser==0.3.28` (pip), `cloakbrowser` npm latest as of 2026-05, bundled Chromium `146.0.7680.177.4`.

## Launch parameters (Python `chromium.launch()` / Node `launch()`)

| Param | Type | Default | Effect | When it matters |
|---|---|---|---|---|
| `headless` | bool / `'new'` | `True` | Headless mode | Keep `False` during dev. Use `'new'` (Chromium new headless) in prod, NOT legacy headless |
| `humanize` | bool | `False` | Bezier-curve mouse, jittered keystrokes, momentum scroll | Always `True` for anti-bot sites |
| `geoip` | bool | `False` | WebRTC leak guard + auto timezone/locale from egress IP | Always `True` when using a proxy |
| `fingerprint` | int | random | Seed for Canvas/WebGL/Audio/font/screen/UA fingerprint | Set explicitly per account; store in DB |
| `proxy` | dict | `None` | `{server, username, password}` | Per-account proxy |
| `args` | list[str] | `[]` | Extra Chromium CLI args | E.g. `--lang=ja-JP` to force locale |
| `viewport` | dict | auto | `{width, height}` | Match common resolutions (1920x1080, 1366x768) |
| `user_data_dir` | path | None | Persistent profile dir (use `launch_persistent_context` in Python) | Save cookies/localStorage across runs |

## CLI commands

```bash
python -m cloakbrowser install       # download binary
python -m cloakbrowser info          # show version + path
python -m cloakbrowser update        # check for newer binary
python -m cloakbrowser clear-cache   # remove all cached binaries
```

Binary cache location: `~/.cloakbrowser/chromium-<version>/`.

## What humanize actually does (observed)

- `page.click(selector)`: cursor travels from current position along a bezier curve with overshoot, takes 200–800ms. NOT instant.
- `page.type(selector, text)`: per-char delay 50–180ms, varies. Occasional 300ms pause mid-word.
- `page.mouse.wheel(...)`: momentum scrolling, not single delta.
- Idle: cursor drifts slightly even when no action.

## What geoip actually does (observed)

- `navigator.language` and `navigator.languages` match IP country.
- `Intl.DateTimeFormat().resolvedOptions().timeZone` matches IP timezone.
- WebRTC `RTCPeerConnection` ICE candidates report ONLY the proxy IP (no LAN leak).
- `Date.getTimezoneOffset()` matches.

## Verification stack

Test in this order; if any fails, fix before moving on:

1. **`navigator.webdriver`** → must be `undefined` (open DevTools console).
2. **BrowserScan.net** → trust score 95%+.
3. **bot.sannysoft.com** → all green or near-all green.
4. **pixelscan.net** → "fingerprint consistent" + no WebRTC leak.
5. **Cloudflare Turnstile demo** → passes without human interaction (some demos still require click).

## Known limitations

- `fingerprint=N` does NOT change User-Agent string drastically — UA stays in the modern-Chrome range; the seed varies Canvas/WebGL/Audio/screen/font/hardware-concurrency. Don't expect "fingerprint=1 looks like iPhone Safari".
- `humanize` does not navigate intelligently — it only humanizes input. You still need to write the page flow logic.
- `geoip` does NOT route traffic — you still need a real proxy for the IP. It just makes the browser's locale match whatever IP it's already using.
