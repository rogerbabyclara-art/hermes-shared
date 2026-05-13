# Proxy verification — before you ever launch the browser

Residential proxy providers lie. The username flag you set (`region-JP`, `country-jp`, etc.) is **not standardized** — every provider has its own grammar, and a malformed/unsupported flag silently falls back to a random IP from the default pool. If you build automation on top of a proxy that claims to be JP but actually exits from China, your Azure/Google signup is dead before the browser opens.

**Rule: always verify exit IP, country, and ASN with curl BEFORE you wire the proxy into the browser.**

## The four-question check

A residential proxy is "good" only if all four are true:

1. **Connectivity** — curl can fetch via the proxy at all (not 403, not timeout, not "invalid SOCKS5 response").
2. **Country matches** — exit IP geolocates to the country you paid for.
3. **ASN is a consumer ISP** — `Comcast`, `NTT`, `KDDI`, `Verizon`, `Deutsche Telekom`, `China Telecom 5G`, `SoftBank` (real residential or mobile carrier). NOT `DigitalOcean`, `AWS`, `Linode`, `Tencent`, `Hetzner`, `OVH` (datacenter — site will flag immediately).
4. **Both protocols tested** — providers often run HTTP and SOCKS5 on **different ports**. The port you got might only speak one of them.

## One-shot verification script

Parameterize the proxy and run from any shell with curl available (git-bash on Windows is fine):

```bash
PROXY_HTTP="http://USER:PASS@HOST:PORT"
PROXY_SOCKS="socks5://USER:PASS@HOST:PORT"   # may be a different port

echo "=== Direct (baseline) ==="
curl -s --max-time 10 https://api.ipify.org; echo

echo "=== HTTP proxy → IP ==="
curl -s --max-time 30 -x "$PROXY_HTTP" https://api.ipify.org; echo

echo "=== HTTP proxy → ip-api.com (country/ISP/ASN) ==="
curl -s --max-time 30 -x "$PROXY_HTTP" \
  "http://ip-api.com/json/?fields=query,country,city,isp,org,as"; echo

echo "=== SOCKS5 proxy → IP ==="
curl -s --max-time 30 --proxy "$PROXY_SOCKS" https://api.ipify.org; echo

echo "=== SOCKS5 proxy → ip-api.com ==="
curl -s --max-time 30 --proxy "$PROXY_SOCKS" \
  "http://ip-api.com/json/?fields=query,country,city,isp,org,as"; echo
```

## Reading the output

**Good (real JP residential):**
```
{"query":"126.45.12.88","country":"Japan","city":"Tokyo",
 "isp":"NTT Communications","org":"NTT","as":"AS4713 NTT Communications"}
```

**Bad (datacenter masquerading as residential):**
```
{"query":"45.32.x.y","country":"Japan","city":"Tokyo",
 "isp":"Vultr Holdings","org":"Choopa","as":"AS20473 The Constant Company"}
```

**Worst (provider ignored your country flag entirely):**
```
{"query":"121.60.119.246","country":"China","city":"Wuhan",
 "isp":"China Telecom","org":"...","as":"AS137266 CHINATELECOM Hubei"}
```

In the third case the username was `zmeq107638-region-JP-sid-...` requesting Japan, but the provider didn't honor it. The IP is real residential (China Telecom 5G), so it would pass an ASN check — but it geolocates to China, which means a JP-region Azure signup will fail KYC. **Always check country AND ASN.**

## Common SOCKS5 failures

```
curl: (97) Received invalid version in initial SOCKS5 response.
```
→ The port you connected to doesn't speak SOCKS5 (probably HTTP-only). Check the provider dashboard for a separate SOCKS5 port (commonly 1080, 5000, 7777).

```
curl: (97) Can't complete SOCKS5 connection to host
```
→ SOCKS5 handshake OK but upstream blocked the target. Try a different target site.

```
curl: (7) Failed to connect to ... after N ms
```
→ Port closed entirely. Wrong port or service down.

## When ipinfo.io / ifconfig.me / api.myip.com return empty

`ipinfo.io` 503s, `api.myip.com` and `ifconfig.me` periodically reject Tencent/AWS source IPs. If a probe returns empty, retry with a different endpoint before blaming the proxy. The rotation order that's worked: `api.ipify.org` → `ip-api.com/json` → `ipapi.co/<ip>/json/`. The last one accepts an IP argument, so you can resolve geolocation even when the probe site won't talk to your direct IP.

## Don't loop the provider's auth

If you blast 7 concurrent variants (`region-JP`, `country-JP`, `country-jp`, `geo-JP`, `JP`, `zone-JP`, `region-jp`) to brute-force the parameter grammar, the provider will **rate-limit your account** and every subsequent request returns empty for several minutes. Test one variant at a time, wait 10 seconds between, and check provider docs first.

## After verification passes

Only then plug the proxy URL into `launch(proxy="http://...")`. With `geoip=True`, the browser will auto-match timezone and locale to the now-verified exit IP — no manual `timezone=` needed.
