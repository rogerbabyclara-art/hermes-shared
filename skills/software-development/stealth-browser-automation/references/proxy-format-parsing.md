# Residential Proxy Format Parsing

Residential proxy providers each ship credentials in their own format. When the operator buys from 2–3 providers (typical for diversification), the import box needs to swallow any format the operator pastes. This note catalogs the formats seen in the wild and gives a parser recipe.

## Formats observed in production

| # | Format | Example | Notes |
|---|---|---|---|
| 1 | `host:port:user:pass` | `us.cliproxy.io:3010:zmeq107638-region-JP-sid-bpceuR4v-t-60:f57bgpcg` | cliproxy, 711proxy, smartproxy backconnect — most common |
| 2 | `socks5://user:pass@host:port` | `socks5://user:pass@1.2.3.4:1080` | URL form, unambiguous |
| 3 | `http://user:pass@host:port` | `http://u:p@proxy.example.com:8080` | URL form, HTTP/HTTPS |
| 4 | `user:pass@host:port` | `myuser:mypass@1.2.3.4:1080` | URL form minus scheme; default to SOCKS5 |
| 5 | `host:port@user:pass` | `1.2.3.4:1080@user:pass` | Reverse simplified — some Chinese dashboards |
| 6 | `host:port` | `1.2.3.4:1080` | No auth — IP-whitelist provisioned |
| 7 | `user:pass:host:port` | `myuser:mypass:1.2.3.4:1080` | Reverse 4-segment — rare but exists |
| 8 | `socks5://host:port` | `socks5://us.cliproxy.io:3010` | URL form, no auth |

The operator will paste a mix of these in one textarea. Reject nothing; classify everything.

## Parser strategy

1. **Strip comments.** Lines starting with `#` or `//`, plus inline `... # note`.
2. **URL scheme first.** If the line matches `/^(socks5|socks5h|socks4|http|https):\/\//i`, peel the scheme and parse the rest. Normalize: `socks5h` → `socks5`, `socks4` → `socks5`, `https` → `http`. The remainder either has `@` (auth) or doesn't.
3. **`@`-separated next.** If the raw line contains `@`, split on the first `@`. Identify which side is `host:port` by testing whether one part is `<host-like>:<numeric-port>`. The other side is `user:pass`. This handles formats 4 and 5 in one shot.
4. **Colon count.** No `@`, fall through to splitting on `:`:
   - 4 segments → format 1 or 7. Test which end is `host:port` by `isHostLike(s1) && isPort(s2)`. The host-like end gives you host:port; the other end is user:pass.
   - 2 segments → format 6.
   - 5+ segments → password contained a `:`. Anchor on whichever end is `host:port` and treat the rest as user:pass(:...).
5. **Default protocol.** When no scheme was given, default to `socks5`. Most residential providers default to SOCKS5 these days; HTTP-only providers (rare) will have explicitly written `http://`.

### `isHostLike` predicate

- IPv4: `/^\d{1,3}(\.\d{1,3}){3}$/`
- Domain: contains a dot, ends with letters: `/^[a-zA-Z0-9][-a-zA-Z0-9.]*\.[a-zA-Z]{2,}$/`
- Literal `localhost`
- Rejects strings with `/`, `@`, spaces

This is what disambiguates `user:pass:host:port` vs `host:port:user:pass` when both have 4 segments — only one end will pass `isHostLike + isPort`.

### Output shape

Normalize every successful parse to one shape:

```javascript
{
  protocol: "socks5",   // or "http"
  host: "us.cliproxy.io",
  port: 3010,
  username: "...",      // "" if none
  password: "...",      // "" if none
  raw: "<original line>"  // keep for the operator to grep later
}
```

From there, `buildProxyUrl()` reconstructs `socks5://user:pass@host:port` for CloakBrowser, and signatures for dedup are `${protocol}://${host}:${port}|${username}`.

## Provider auto-detection

Detect from the host string and tag for filtering/reporting:

| Host contains | Provider tag |
|---|---|
| `cliproxy` | cliproxy |
| `711proxy` or `rotgb` | 711proxy |
| `smartproxy` | smartproxy |
| `brightdata` or `luminati` | brightdata |
| `oxylabs` | oxylabs |
| `iproyal` | iproyal |
| `packetstream` | packetstream |

This is cheap and helps the operator see "I have 30 from cliproxy and 20 from 711proxy" without manual tagging.

## Dedup on import

Two pasted lines for the same `host:port|username` are almost certainly the same physical proxy (the same provider account, same backconnect endpoint, same session selector). Skip silently and report the count: `imported 47 new · skipped 3 duplicates`.

Password is intentionally NOT part of the dedup signature — if the operator updated the password upstream and re-pasted, the parser should still skip the row (it'll fail with a clear auth error on next test, which is more obvious than "why are there two of these now").

## Per-line error reporting

When a line fails to parse, capture the line number and content but DO NOT abort the batch. Operators paste 100 lines and want 99 imported plus a list of 1 that needs fixing. Return:

```javascript
{
  proxies: [...],         // successful parses
  errors: [{line: 42, content: "<garbled stuff>"}]
}
```

Surface error count and first 3 examples in the toast: `imported 97 · 3 lines failed (e.g. line 42: <preview>)`. Operator scrolls back, fixes, re-pastes — the deduper handles the re-paste.

## Sanity test for a parser implementation

A correct parser should handle this 9-line input with 9/9 success:

```
us.cliproxy.io:3010:zmeq107638-region-JP-sid-bpceuR4v-t-60:f57bgpcg
global.rotgb.711proxy.com:10000:USER354468-zone-custom:76cca8
socks5://user:pass@1.2.3.4:1080
http://myuser:mypass@proxy.example.com:8080
user:pass@1.2.3.4:1080
1.2.3.4:1080@user:pass
1.2.3.4:1080
zmeq107638-region-JP-sid-X:f57bgpcg@us.cliproxy.io:3010
socks5://us.cliproxy.io:3010
```

If any line fails, the parser is missing a branch — usually either the no-auth URL form (line 9) or the reverse `@` form (line 6).
