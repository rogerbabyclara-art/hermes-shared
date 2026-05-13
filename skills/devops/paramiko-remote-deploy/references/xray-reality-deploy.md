# Xray VLESS Reality deploy — fresh Ubuntu 22 reference

End-to-end recipe for deploying Xray-core with VLESS + Reality (XTLS-vision flow) on a fresh Tencent Cloud / AWS / generic Ubuntu 22.04 VPS, terminated on :443 with a microsoft.com SNI mask. This is the protocol used by v2rayN/v2rayNG/Shadowrocket/Clash Meta clients.

## Why Reality

Reality replaces TLS with a real handshake to a real public site (e.g. `www.microsoft.com`). To a passive observer the traffic IS TLS to Microsoft. There is no self-signed cert, no Let's Encrypt, no domain to register. Active probing (curl to your :443) gets forwarded to the real site and returns the real site's response. As of 2025-2026 this is the gold standard for GFW-resistant tunnels.

## Prereqs

- Fresh Ubuntu 22.04 VPS (Tencent Cloud HK / Singapore / etc.)
- Default user `ubuntu` with sudo password
- Port 443 unused (verify with `ss -tlnp 'sport = :443'`)
- Cloud security group will need 443/TCP opened (do this LAST in the cloud console)

## Steps

### 1. Probe + install Xray

```bash
# from your workstation, via paramiko-remote-deploy/scripts/probe_vps.py
python scripts/probe_vps.py <ip> ubuntu '<password>'

# install xray-core via official script (uses beta channel for latest reality fixes)
ssh <user>@<ip> 'sudo bash -c "$(curl -L https://github.com/XTLS/Xray-install/raw/main/install-release.sh)" @ install --beta'
```

systemd unit `xray.service` is installed and enabled. Default config at `/usr/local/etc/xray/config.json`.

### 2. Generate keys + UUID + short-id

```bash
ssh <user>@<ip> 'xray x25519'
# Output (v26+):
#   PrivateKey: <43-char base64url>
#   Password (PublicKey): <43-char base64url>
#   Hash32: <43-char base64url>
```

**Parser gotcha**: v25 used `PublicKey: xxx`. v26+ uses `Password (PublicKey): xxx`. Regex:

```python
re.search(r"(?:Password|PublicKey|公钥)[^:]*:\s*([A-Za-z0-9_\-]+)", out)
```

Generate UUID + 8-char hex short-id locally:
```python
import uuid, secrets
uid = str(uuid.uuid4())          # client ID
sid = secrets.token_hex(4)       # short-id (8 hex chars = 4 bytes)
```

### 3. Build config.json

```json
{
  "log": {
    "loglevel": "warning",
    "access": "/var/log/xray/access.log",
    "error":  "/var/log/xray/error.log"
  },
  "inbounds": [{
    "listen": "0.0.0.0",
    "port": 443,
    "protocol": "vless",
    "settings": {
      "clients": [{"id": "<UUID>", "flow": "xtls-rprx-vision"}],
      "decryption": "none"
    },
    "streamSettings": {
      "network": "tcp",
      "security": "reality",
      "realitySettings": {
        "show": false,
        "dest": "www.microsoft.com:443",
        "xver": 0,
        "serverNames": ["www.microsoft.com"],
        "privateKey": "<PRIV>",
        "shortIds": ["<SID>"]
      }
    },
    "sniffing": {
      "enabled": true,
      "destOverride": ["http", "tls", "quic"],
      "routeOnly": true
    }
  }],
  "outbounds": [
    {"protocol": "freedom", "tag": "direct"},
    {"protocol": "blackhole", "tag": "block"}
  ],
  "routing": {
    "domainStrategy": "IPIfNonMatch",
    "rules": [{"type": "field", "ip": ["geoip:private"], "outboundTag": "block"}]
  }
}
```

### 4. Deploy config — SFTP staging pattern

**Do NOT** `echo $config | sudo tee /usr/local/etc/xray/config.json` in a paramiko `run()` helper if the helper wraps the whole thing in `sudo bash -c '...'`. The outer single quotes will fight the inner ones. Use SFTP-to-tmp + sudo-cp:

```python
sftp = client.open_sftp()
with sftp.open("/tmp/xray_config.json", "w") as f:
    f.write(json.dumps(config, indent=2))
sftp.close()

run("cp /tmp/xray_config.json /usr/local/etc/xray/config.json && "
    "chown root:root /usr/local/etc/xray/config.json && "
    "chmod 644 /usr/local/etc/xray/config.json && "
    "xray -test -config /usr/local/etc/xray/config.json")
# expect: 'Configuration OK.'
```

### 5. Restart + verify on-host

```python
run("systemctl restart xray && sleep 2 && systemctl is-active xray")
# expect: 'active'

run("ss -tlnp 'sport = :443'")
# expect: LISTEN  0  4096  *:443  *:*  users:(("xray",pid=...,fd=4))

# self-check: does the Reality fallback to real microsoft.com work?
run("curl -sI --max-time 8 --resolve www.microsoft.com:443:127.0.0.1 https://www.microsoft.com/ -k | head -3", sudo=False)
# expect: HTTP/2 200 + server: AkamaiGHost  (proves Reality is forwarding to real upstream)
```

### 6. Open cloud security group

**Critical and easy to forget.** `iptables -I INPUT -p tcp --dport 443 -j ACCEPT` on the VPS does nothing if the cloud security group blocks 443 at the network edge.

- Tencent Cloud: 控制台 → 云服务器 → 实例 → 安全组 → 入站规则 → Add `TCP:443 / 0.0.0.0/0`
- AWS: EC2 → Security Groups → Inbound rules → Add `Custom TCP / 443 / 0.0.0.0/0`
- Alibaba: ECS → 网络与安全 → 安全组 → 配置规则 → Add `TCP / 443 / 0.0.0.0/0`

This step is manual via cloud console. Programmatic via cloud APIs is possible but rarely worth the setup for one-off deploys.

### 7. Output client import link

```python
import urllib.parse
remark = urllib.parse.quote("MyVPS-HK")
link = (
    f"vless://{UUID}@<ip>:443"
    f"?encryption=none&flow=xtls-rprx-vision&security=reality"
    f"&sni=www.microsoft.com&fp=chrome&pbk={PUB}&sid={SID}"
    f"&type=tcp&headerType=none#{remark}"
)
```

Paste into v2rayN / V2RayNG / Shadowrocket / Clash Meta — they all parse this URL scheme natively.

## Common failure modes

| Symptom | Cause | Fix |
|---|---|---|
| `xray -test` says Configuration OK but `:443` not listening | systemd restart failed silently | `journalctl -u xray --no-pager -n 50` |
| Client connects but no data flows | `flow` mismatch — client must also use `xtls-rprx-vision` | re-import link, don't hand-edit flow |
| `tls: handshake failure` from client | wrong PublicKey or wrong ShortID | regenerate, redeploy, re-import |
| External client cannot connect at all | cloud security group | open 443 in cloud console |
| Slow / inconsistent | upstream microsoft.com regional latency | switch SNI to `www.tesla.com`, `www.lovelive-anime.jp`, or another fast TLS 1.3 site. Must be a site that supports TLS 1.3 and HTTP/2. |

## Recommended SNI targets

- `www.microsoft.com` — fast, global, never blocked
- `www.tesla.com` — fast in most regions
- `www.lovelive-anime.jp` — good for Asian routes
- `www.cloudflare.com` — works but CDN edges may MITM
- AVOID: SNIs that don't support TLS 1.3 or HTTP/2 (Reality requires both)
