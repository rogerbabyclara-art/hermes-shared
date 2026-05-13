# Proxy/VLESS client probe notes

Session learning from testing a SOCKS proxy and a VLESS+Cloudflare node on a VM.

## Quick probe sequence

1. First separate raw reachability from actual proxy usability:
   - ICMP/TCP to proxy host: `ping`, Python `socket.connect()` loops.
   - Then real proxied `curl` targets. A live port can still fail SOCKS auth or stall upstream.
2. If a SOCKS URL requires credentials and scripts already contain it, extract without echoing secrets:
   - `re.search(r'PROXY\\s*=\\s*"([^"]+)"', Path(...).read_text()).group(1)`
   - Do not print the full proxy URL back to chat.
3. For VLESS/WS/TLS/CF links, install/use `sing-box`, create a temporary local mixed inbound, then test through `127.0.0.1:2080`.

## sing-box install workaround

Direct GitHub downloads from the VM can be painfully slow/reset. If direct release download stalls, use `ghproxy.net`:

```bash
mkdir -p /tmp/singbox-install && cd /tmp/singbox-install
curl -fsSL --connect-timeout 15 --max-time 240 \
  -o sing-box.tar.gz \
  'https://ghproxy.net/https://github.com/SagerNet/sing-box/releases/download/v1.13.11/sing-box-1.13.11-linux-amd64.tar.gz'
tar -xzf sing-box.tar.gz
/tmp/singbox-install/sing-box-1.13.11-linux-amd64/sing-box version | head -n 1
```

Docker pull of `ghcr.io/sagernet/sing-box` may fail on IPv6/GHCR with connection reset, so don't rely on Docker as the first fallback.

## Minimal VLESS WS TLS config pattern

Map VLESS URL params like:
- `server` / `server_port`: URL host/port
- `uuid`: URL username
- `tls.server_name`: `sni`
- `tls.utls.fingerprint`: `fp`
- `transport.type`: `ws`
- `transport.path`: decoded `path`
- `transport.headers.Host`: `host`

Use local mixed inbound:

```json
{
  "inbounds": [{"type":"mixed","listen":"127.0.0.1","listen_port":2080}],
  "outbounds": [{
    "type":"vless",
    "server":"HOST",
    "server_port":443,
    "uuid":"UUID",
    "tls":{"enabled":true,"server_name":"SNI","utls":{"enabled":true,"fingerprint":"chrome"}},
    "transport":{"type":"ws","path":"PATH","headers":{"Host":"WS_HOST"}}
  }],
  "route":{"final":"vless"}
}
```

Run:
```bash
sing-box check -c /tmp/singbox-install/config.json
sing-box run -c /tmp/singbox-install/config.json
```

## Test targets that matter for this user's monitors

Use short, repeated `curl --proxy socks5h://127.0.0.1:2080` probes with `--connect-timeout` and `--max-time`:

- `https://api.telegram.org`
- `https://www.google.com/generate_204`
- `https://www.youtube.com/feeds/videos.xml?channel_id=UC_x5XG1OV2P6uZZ5FSM9Ttw`
- `https://www.cloudflare.com/cdn-cgi/trace`
- `https://speed.cloudflare.com/__down?bytes=100000`

Report `total`, `ttfb`, `speed`, `code`, and whether failures are timeout vs SSL errors. Don't overtrust CF self-tests: a CF VLESS node can make Google/YouTube fast while Cloudflare trace/speed itself times out.

## Interpretation pitfall

A proxy can look fine at TCP/connect level but fail real traffic. Conversely, a CF VLESS node can be useful for YouTube RSS even if Cloudflare-owned test endpoints fail. Recommend per-workload routing when results differ: e.g. use VLESS for YouTube RSS but keep/compare another proxy for Telegram sending.
