# Cloudflare Tunnel + internal VM + public VPS: direct-access pitfalls

Use this note when a user says "just use the VPS" or asks for an IP-direct workaround while the app actually runs on an internal VM.

## Evidence pattern from this session

Environment shape:
- App host VM: `192.168.1.9` (`hostname=ubuntu-web`)
- Public IPv4 observed from VM: `121.60.119.246`
- Cloudflare Tunnel fronts `newapi.bestcloudmail.com` -> `localhost:80`
- NEWAPI itself listens on `0.0.0.0:3000` on the VM
- Separate public VPS later provided: `85.121.123.59`

Critical findings:
1. Local service was healthy on VM:
   - `curl -I http://127.0.0.1:3000` returned `200 OK`
   - `docker ps` showed `new-api` healthy
2. Alleged "IP direct" from outside was **not proven** and then disproven:
   - probing `http://121.60.119.246:3000` from outside timed out
   - host firewall (`ufw`) was inactive, so simple local firewall blame was wrong
3. Public VPS could not reach the VM private IP:
   - from `85.121.123.59`, `ping 192.168.1.9` failed
   - `/dev/tcp/192.168.1.9/3000` timed out
4. Therefore the VM was not a directly reachable public server; it was an internal/NATed machine whose public exposure depended on Cloudflare Tunnel.

## What this means operationally

Do **not** promise any of these until they are verified:
- "just use the VM public IP"
- "open port 3000 on the VPS and forward it to 192.168.x.x"
- "VPS direct proxy to the VM"

A public VPS cannot magically dial a private RFC1918 address on someone else's LAN.

## Required verification before suggesting IP-direct

### 1. Prove the app is alive locally
```bash
curl -I http://127.0.0.1:3000
ss -ltnp | grep ':3000\b'
docker ps --format '{{.Names}}\t{{.Ports}}' | grep new-api
```

### 2. Prove the public IP really reaches that host externally
From a separate machine (or the public VPS):
```bash
curl -I --max-time 15 http://<public-ip>:3000
```
If this times out while local checks are healthy, assume NAT/edge/router involvement.

### 3. If using a separate VPS, prove VPS -> VM connectivity before building a forward
From the VPS:
```bash
timeout 10 bash -lc 'cat < /dev/null > /dev/tcp/<vm-private-ip>/3000'; echo $?
ping -c 1 -W 1 <vm-private-ip>
```
If these fail, a naive `socat TCP-LISTEN ... TCP:<private-ip>:3000` service is useless.

## Fast-path solutions when VPS cannot reach the VM

### Option A: reverse SSH tunnel from VM to VPS
Best emergency fix when:
- VM can reach the Internet
- VPS has a public IP
- Cloudflare causes 524s

Shape:
```bash
# run from VM
ssh -N -R 3000:127.0.0.1:3000 root@<vps-ip>
```
Then clients hit `http://<vps-ip>:3000` (or put nginx on the VPS in front of it).

For persistence, prefer `autossh` + systemd.

### Option B: router port-forward
If the VM sits behind a home/office router and the user controls it, forward external port -> `192.168.1.9:3000`.

### Option C: VPN/overlay network
Tailscale / ZeroTier / WireGuard when repeated admin access is needed.

## Anti-pattern to remember

Blindly installing `socat` on the VPS and forwarding to `192.168.1.9:3000` without proving connectivity wastes time and looks sloppy. Test reachability first.
