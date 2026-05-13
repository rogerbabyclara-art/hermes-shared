# Roger's VPS Infrastructure Map (85.121.123.59)

## Services on VPS (localhost)

| Service | Container | Internal Port | Public Port | Access Method | Notes |
|---------|-----------|--------------|-------------|---------------|-------|
| NEWAPI (new-api) | `new-api` | 0.0.0.0:3000 | 3000 | autossh tunnel from VM | Bypasses CF. |
| Sub2API | `sub2api` | 127.0.0.1:8081 | 3001 | autossh tunnel from VM | Bypasses CF. Tunnel maps VM:8081→VPS:3001 |
| Uptime Kuma | `uptime-kuma` | 127.0.0.1:3001 | - | CF tunnel only | Local 127.0.0.1 binding coexists with autossh 0.0.0.0:3001 |
| Homepage | `homepage` | 127.0.0.1:3100 | - | CF tunnel only | |
| Done Hub | `done-hub` | 127.0.0.1:3002 | - | CF tunnel only | |
| CLI Proxy API | `cpa` | 127.0.0.1:8317 | - | CF tunnel only | |
| n8n | `n8n` | 127.0.0.1:5678 | - | CF tunnel only | |

## Autossh Reverse Tunnels (VM 192.168.1.9 → VPS 85.121.123.59)

| Service | VM Port | VPS Port | Systemd Service | Status |
|---------|---------|----------|-----------------|--------|
| NEWAPI | 3000 | 3000 | `newapi-reverse-tunnel.service` | ✅ Working |
| Sub2API | 8081 | 3001 | `sub2api-reverse-tunnel.service` | ✅ Working |

Both tunnels use `sshpass + autossh -M 0 -N -R 0.0.0.0:<vps-port>:127.0.0.1:<vm-port> root@85.121.123.59` with password auth.

## Cloudflare Tunnel Config (/etc/cloudflared/)

Two tunnels configured:
- **Tunnel 5d832d10**: `*.bestcloudmail.com` → localhost:80 (nginx)
- **Tunnel 60c9ac9e**: `*.rogerbabyclara.online` → localhost:80 (nginx)

All tunnel ingress routes through nginx on port 80, which then proxies to individual containers.

## Cloudflare Domains → nginx → containers

| Domain | nginx config | Proxies to |
|--------|-------------|------------|
| newapi.bestcloudmail.com | /etc/nginx/sites-available/newapi | 127.0.0.1:3000 |
| sub.bestcloudmail.com | /etc/nginx/sites-available/sub2api | 127.0.0.1:8081 |
| hermes.bestcloudmail.com | ? | Hermes web UI |
| status.bestcloudmail.com | ? | 127.0.0.1:3001 (Uptime Kuma) |

## Direct-access endpoints (bypass Cloudflare)

| Service | Direct URL | Status |
|---------|-----------|--------|
| NEWAPI | http://85.121.123.59:3000 | ✅ Working |
| Sub2API | http://85.121.123.59:3001 | ✅ Working |

## VPS Firewall (iptables)

Default INPUT policy: ACCEPT (all ports open at OS level).
Explicitly allowed ports: 11899, 13843, 22138, 80, 443.
**However**, the cloud provider's security group may block ports not in use. Port 8082 was confirmed blocked at the provider level despite OS-level LISTEN. Ports 22 and 3000 are confirmed externally reachable. Port 3001 is confirmed externally reachable (via autossh binding).
