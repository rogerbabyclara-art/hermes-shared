# VPS Proxy Chain: residential-proxy-from-blocked-IP pattern

## When to use

Your residential proxy vendor (cliproxy, IPRoyal, Bright Data, 922 S5, PYProxy)
silently drops packets from your source ASN — usually because it's a datacenter
IP (Tencent, AWS, DigitalOcean, OVH, etc.). Symptoms:

- `curl -x http://user:pass@proxy:port https://api.ipify.org` hangs to timeout
- `curl -x http://user:WRONGPASS@proxy:port ...` **also** hangs (no 407 returned)
- TCP CONNECT succeeds, CONNECT request sent, then nothing comes back

This is **packet-level drop based on source IP**, not auth failure.

## Fix: chain through a clean VPS

```
client → vps:9999 (tinyproxy, BasicAuth) → residential-proxy:3010 → exit IP
```

Pick a VPS that is **not** in the datacenter ASN blacklist. In practice almost
any HK/JP/US VPS works because the residential vendor only blocks the biggest
ASNs. If your first VPS is also blocked, try another region.

## Setup (Ubuntu 22.04+ / Debian 12+)

```bash
# 1. SSH to VPS, install tinyproxy
sudo apt-get update && sudo apt-get install -y tinyproxy

# 2. Drop in the templates/tinyproxy.conf from this skill,
#    replacing the four CHANGE_ME placeholders
sudo cp /etc/tinyproxy/tinyproxy.conf /etc/tinyproxy/tinyproxy.conf.bak
sudo nano /etc/tinyproxy/tinyproxy.conf   # paste the template

# 3. Restart and verify
sudo systemctl restart tinyproxy
sudo systemctl status tinyproxy --no-pager | head -10
sudo ss -tlnp | grep 9999    # confirm LISTEN 0.0.0.0:9999

# 4. Verify on VPS itself (loopback test bypasses firewall)
curl -s --max-time 30 -x "http://CHANGE_ME_USER:CHANGE_ME_STRONG_PASS@127.0.0.1:9999" https://api.ipify.org
# Should print residential exit IP. Verify country:
IP=<that-IP>
curl -s "https://ipapi.co/$IP/json/" | grep -E '"country_name"|"org"|"city"'

# 5. Open cloud security group / firewall (see pitfall below) then test from client
```

## Why **NOT** 3proxy

3proxy was a common pick before, but `3proxy` package is **not in Ubuntu 22.04
or 24.04 main repos**. You'd have to compile from source. Tinyproxy is in
`apt`, supports upstream-with-auth chain, and uses ~1 MB RAM. Use tinyproxy.

## PITFALL 1: Cloud security group blocks the port

Tinyproxy listens on `0.0.0.0:9999` and `ss` shows it LISTEN. From the VPS
itself loopback works. From the outside world, **connection times out at TCP
handshake**. This is **cloud provider security group / firewall**, not
tinyproxy.

Tencent Cloud, Alibaba Cloud, AWS, GCP all default-deny inbound. You **must**
open the port in the cloud console:

| Provider | Where |
|---|---|
| Tencent Cloud | 控制台 → CVM → 安全组 → 入站规则 → 添加 TCP:9999 |
| AWS EC2 | Security Groups → Inbound rules → Custom TCP 9999 |
| Aliyun | ECS → 安全组 → 添加安全组规则 → TCP 9999 |
| DigitalOcean | Networking → Firewalls → Inbound rules |

Source can be `0.0.0.0/0` (BasicAuth protects you) or restricted to your
client public IP for paranoia. **`ufw` is NOT used by default on Tencent Cloud
Ubuntu images — the gating layer is the cloud security group.**

Diagnostic: from VPS itself, `curl -x http://creds@<vps-public-ip>:9999 ...`
should also fail/timeout when the security group is closed. Loopback through
`127.0.0.1` is the only thing that works until you open the port.

## PITFALL 2: TUN-mode loop / hairpin

If your client machine has v2rayN/Clash TUN mode routing **through the same
VPS** you're now also using as the tinyproxy host, you get a routing loop:

```
client → TUN → VPS-A → public internet → VPS-A:9999 → ...
```

Symptoms:
- `curl https://api.ipify.org` from client shows VPS-A IP (TUN working)
- `curl -x vps-a:9999 https://api.ipify.org` from client hangs

The TCP packet to `vps-a:9999` goes into the TUN tunnel back to VPS-A and gets
NAT'd weirdly. Fix one of:

- **Add an exclusion route in v2rayN/Clash**: `vps-a-ip/32` → direct (bypass TUN)
- **Use a different VPS for the tinyproxy chain** than the one you're tunneling through
- **Disable TUN** for the duration of the test, use only proxy-aware client tools

Most natural fix: a residential-proxy-chain VPS should be a **third party** to
the client and the VPN exit. Don't double-duty.

## PITFALL 3: residential proxy returned wrong country

User specified `region-JP` in upstream username but exit IP is China/random.
Always verify country **after** the chain is up, never trust the user param:

```bash
IP=$(curl -s --max-time 20 -x "http://creds@vps:9999" https://api.ipify.org)
echo "Exit IP: $IP"
curl -s "https://ipapi.co/$IP/json/" | grep -E '"country_name"|"city"|"org"|"asn"'
```

If wrong country: vendor doesn't have nodes in that region, account out of
credit, or syntax variant is different (try `country-JP`, `geo-JP`, `zone-JP`,
`-JP-`). Don't burn signup attempts on a misconfigured proxy.

## PITFALL 4: choose tinyproxy port carefully

`8888` and `3128` (squid default) are commonly scanned by abuse bots. Use a
higher random port (`9999`, `48721`, etc.) to reduce log noise. BasicAuth still
gates real access but you save log volume.

## Full chain verification checklist

After setup, all four must pass:

1. ✅ `sudo ss -tlnp | grep 9999` shows tinyproxy LISTEN on VPS
2. ✅ VPS loopback: `curl -x http://creds@127.0.0.1:9999 https://api.ipify.org` returns residential IP
3. ✅ External TCP: `nc -zv <vps-ip> 9999` from client succeeds (rules out firewall)
4. ✅ Country check: `curl -s https://ipapi.co/<exit-ip>/json/` shows expected country + non-datacenter org

Then plug `http://creds@vps:9999` into CloakBrowser's `proxy=` param.
