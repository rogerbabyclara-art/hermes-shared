---
name: third-party-proxy-debugging
description: Diagnose third-party residential/datacenter proxy connection failures (SOCKS5/HTTP) — auth rejects, IP whitelist blocks, malformed username patterns. Use when integrating proxy vendors like 711proxy, cliproxy, Bright Data, Oxylabs, IPRoyal, Smartproxy and connections fail with NotAllowed / 407 / timeout / TLS errors. Covers vendor-specific quirks and the standard 3-layer isolation method (lib → curl → direct).
---

# Third-Party Proxy Debugging

When a residential or datacenter proxy fails, the question is always: **vendor's fault, our credentials, or our code?** This skill answers it in under 2 minutes.

## When to load

- App reports proxy connection error and you don't know if it's code, creds, network, or vendor
- New proxy vendor onboarding ("does this even work?")
- 200 proxies "all failed" — you need to know if it's systemic or per-entry
- User pastes proxy strings and wants to know "are these usable from my machine?"

## The 3-layer isolation method

Run these IN ORDER. The first layer that breaks tells you where the problem is.

### Layer 1 — Direct connection (no proxy)

```bash
curl -sS --max-time 8 https://ipinfo.io/json
```

- ✓ Works → your machine has internet. Your machine's egress IP is in the response (`ip` field). **Remember this IP — most vendors require it on a whitelist.**
- ✗ Fails → fix your network first, proxy debugging is pointless.

### Layer 2 — Raw curl through the proxy

For SOCKS5:
```bash
curl -sS --max-time 15 \
  --socks5-hostname HOST:PORT \
  --proxy-user "USER:PASS" \
  https://ipinfo.io/json
```

For HTTP/HTTPS proxy:
```bash
curl -sS --max-time 15 \
  -x "http://USER:PASS@HOST:PORT" \
  https://ipinfo.io/json
```

Interpret the result by error code (see references/socks5-reply-codes.md for full table):

| curl exit / message | Meaning | Action |
|---|---|---|
| 0 (200 OK, body has IP) | ✓ Vendor + creds + your IP all good | Issue is in your code |
| `(97) cannot complete SOCKS5 connection. (2)` | SOCKS5 reply 2 = **rule not allowed** | Vendor blocked you — usually IP whitelist or zone misconfiguration |
| `(97) ... (1)` | SOCKS5 reply 1 = general failure | Often auth failure dressed up — verify password |
| `Received HTTP code 407` | HTTP proxy auth failed | Wrong user/pass |
| `Connection timed out` | Can't even reach proxy host | DNS or firewall, not auth |
| `(35) SSL/TLS handshake failed` | Proxy reached but TLS broken | Endpoint port wrong, or vendor needs different scheme |

### Layer 3 — Library (socks-proxy-agent, requests, puppeteer, etc.)

Only reach this layer if Layer 2 succeeded. If curl works but your library doesn't, it's almost always:
- Username/password not URL-encoded (special chars like `@` `:` `/` in user)
- Wrong agent class (HttpsProxyAgent vs SocksProxyAgent vs node `http.Agent`)
- Library doing DNS locally instead of through SOCKS5 (use `socks5h://` schema)

## Vendor whitelist quick reference

Most residential proxy vendors require IP whitelisting **in addition to** username/password auth. If Layer 2 returns NotAllowed despite seemingly-correct creds, **check the vendor dashboard for whitelist settings first**.

| Vendor | Whitelist location | Default state |
|---|---|---|
| 711proxy / rotgb | Dashboard → 白名单管理 / Whitelist | Required, empty by default |
| cliproxy | Dashboard → IP authentication | Optional (user+pass alone usually works) |
| Bright Data | Zone → Trusted IPs | Optional but recommended |
| Oxylabs | Dashboard → Whitelist | Optional |
| IPRoyal | Dashboard → IP Authentication | Optional |
| Smartproxy | Endpoint generator → IP whitelist | Optional |

When in doubt, **add your egress IP to the whitelist** — it never hurts and fixes ~60% of NotAllowed cases.

## Username pattern decoding

Modern residential proxy users encode session/region/zone parameters in the username itself. Decode them before assuming they're valid:

```
USER354468-zone-custom-region-JP-session-11126370-sessTime-60-sessAuto-1
       │         │            │            │              │             │
   account_id  zone_name   region/country  session_id   session_min   auto_rotate
```

Each vendor has its own dialect. Common gotchas:
- `zone-custom` requires you to have **pre-created** a zone called `custom` in the dashboard. Fresh accounts often only have `zone-residential` or similar.
- `region-JP` vs `country-jp` vs `state-jp` — case-sensitive and vendor-specific.
- `session-XXXX` numeric range varies by vendor (some require ≥ 8 digits).
- `sessTime-60` is minutes for some, seconds for others.

**Verification step**: most vendor dashboards have a "Connection example" / "Test endpoint" page that generates a known-working username string for your account. Use one of those first as a positive control before testing your bulk list.

## Smoke-test script pattern (Node, for batch proxy lists)

When the user imports N proxies and reports "all failed", run a single one through the same library the app uses, with verbose output:

```js
// _smoketest.js — keep this pattern handy, delete after use
const fs = require("fs");
const { SocksProxyAgent } = require("socks-proxy-agent");
const https = require("https");

const d = JSON.parse(fs.readFileSync("./proxies.json", "utf8"));
const ip = d.ip_pool[0];  // pick first
const url = `socks5://${encodeURIComponent(ip.username)}:${encodeURIComponent(ip.password)}@${ip.host}:${ip.port}`;
console.log("URL:", url.replace(ip.password, "***"));

const agent = new SocksProxyAgent(url);
const t0 = Date.now();
const req = https.request({
  host: "ipinfo.io", port: 443, path: "/json", agent, timeout: 15000,
  headers: { "User-Agent": "test", Accept: "application/json" }
}, res => {
  let b = ""; res.on("data", c => b += c);
  res.on("end", () => console.log(`OK ${Date.now()-t0}ms`, b.slice(0, 200)));
});
req.on("error", e => console.log("ERR", Date.now()-t0, "ms:", e.message, e.code || ""));
req.on("timeout", () => console.log("TIMEOUT", Date.now()-t0, "ms"));
req.end();
```

If this script reproduces the failure → bug is **not** in your IPC/UI layer, it's at the network/credential level. Confirm with Layer 2 curl test.

## Common pitfalls

1. **Don't assume vendor-side failure means code is correct.** Library bugs (wrong agent, no URL encoding) can also produce NotAllowed-like errors. Always verify with curl (Layer 2) before blaming the vendor.
2. **`socks5://` vs `socks5h://`**: the `h` variant pushes DNS resolution to the proxy. Without it, your local DNS leaks AND can resolve to IPs the proxy rejects. Default to `socks5h://` for residential pools.
3. **Password truncation**: vendor dashboards often show only first/last 4 chars. Make sure the user copied the FULL password, not the masked display.
4. **Wrong port for protocol**: many vendors run SOCKS5 on one port (e.g. 10000) and HTTP on another (e.g. 8000). Trying SOCKS5 against the HTTP port returns garbled errors.
5. **Trial accounts with regional caps**: free trials sometimes block CN egress IPs entirely. Whitelist won't help — the account itself is geo-restricted.

## Reporting back to the user

When you've isolated the failure layer, give the user a concrete action item, not just a diagnosis:

- Layer 2 NotAllowed → "Log into [vendor] dashboard, add `<egress IP>` to IP whitelist"
- Layer 2 407 → "Password is wrong. Re-copy from dashboard, full string"
- Layer 2 timeout → "Can't reach `host:port` — check the host/port pair, possibly typo or vendor changed endpoint"
- Layer 3 only fails → "Vendor is fine, our code needs URL-encoded auth / different agent class"

Always tell them what their **egress IP** is — they'll need it for the whitelist.

## Residential rotating-IP pools: testing philosophy

Residential rotating-IP vendors (711proxy, Bright Data residential, IPRoyal, etc.) issue a **new egress IP per SOCKS5 session**, even with the same username. This has implications you must internalize:

1. **A "failed" test does NOT mean that proxy entry is dead.** The same username will likely succeed on the next attempt with a different upstream peer. The failure rate per single test can be 10-30% even for a perfectly healthy account.
2. **Do NOT gate downstream actions (account binding, task assignment) on test pass/fail.** Bind/assign by configured ordinal (ip-001 → account-001), not by last test result. Treat the test as informational only.
3. **Sample-test, don't full-test.** For batch validation, run a random sample of 3-5 entries from the pool. If ≥ 2/3 pass, the credentials and whitelist are fine — that's all the test is proving. A full 200-entry sweep produces alarming-looking failures that mean nothing actionable.
4. **`dead` state must be set manually by user**, not auto-flipped from a single test failure. A separate "user marks as confirmed dead after 3+ real-use failures" path is the only safe auto-degrade rule.
5. **When user reports "half failed in batch but worked when retried individually"** — that's not a bug, that's residential pool reality. The lesson is to lower concurrency and add jitter (next section), not to fix the test logic.

### Concurrency limits when batch-testing vendor endpoints

Slamming a single vendor endpoint with N parallel SOCKS5 handshakes triggers vendor-side rate limits that LOOK like auth failures (NotAllowed, Connection refused, sudden timeouts). Empirical limits:

| Vendor type | Safe concurrency | Add jitter | Notes |
|---|---|---|---|
| Residential rotating (711proxy, BrightData res) | **5** | 0-400ms random | Each "session" opens fresh upstream; bursts overwhelm dispatcher |
| Datacenter (cliproxy non-residential, OVH lists) | 10-20 | 0-100ms | More tolerant |
| Free / trial endpoints | 2-3 | 500ms+ | Aggressive throttling |

Implementation pattern (Node worker pool):

```js
const CONCURRENCY = 5;
const JITTER_MS = 400;
let cursor = 0;
async function worker() {
  while (cursor < pool.length) {
    const ip = pool[cursor++];
    await new Promise(r => setTimeout(r, Math.random() * JITTER_MS));
    const r = await testProxy(ip);
    // record result, push progress event
  }
}
await Promise.all(Array.from({length: CONCURRENCY}, worker));
```

Stream progress (`done/total · ok/fail`) back to the UI per completion — a long-running batch with no progress reads as "frozen" and the user will retry/cancel.

## See also

- `references/socks5-reply-codes.md` — full RFC 1928 reply code table
- `references/proxy-string-formats.md` — multi-vendor proxy string formats and parser logic
- `references/residential-pool-architecture.md` — account-IP 1:1 binding, manual-lock, hot-swap design notes
