---
name: cloudflare-524-bypass
description: Bypass Cloudflare's 120-second proxy read timeout (HTTP 524) for self-hosted API gateways serving long-running LLM requests. Use when services behind Cloudflare proxy (orange cloud) return 524 on Claude/GPT streaming or long-response requests.
tags: [cloudflare, 524, timeout, reverse-proxy, ssh-tunnel, nginx, newapi, sub2api]
---

# Bypass Cloudflare 524 Timeout for LLM API Gateways

## When to use

- User reports HTTP 524 from a `*.bestcloudmail.com` or any Cloudflare-proxied domain
- Error message contains "origin web server did not return a complete response within the 120-second Proxy Read Timeout window"
- Service behind Cloudflare handles LLM API requests (NEWAPI, Sub2API, any OpenAI/Anthropic-compatible gateway)
- Long-running model responses (Claude Opus, large context, extended thinking) exceed 120 seconds

## Root cause

Cloudflare's edge proxy enforces a **hard 120-second read timeout** on all plans (Free/Pro/Business). Only Enterprise plans can increase it. This is NOT configurable via `cloudflared` tunnel settings — `readTimeout` in tunnel config only affects cloudflared-to-origin, not the Cloudflare edge layer.

The chain that triggers 524:
```
Client → Cloudflare Edge (120s HARD limit) → Tunnel/Proxy → nginx → API gateway → upstream LLM
```

Even with `proxy_read_timeout 3600s` in nginx and streaming enabled, if the Cloudflare edge doesn't receive the first byte within 120s, it returns 524.

## Diagnosis checklist

1. **Confirm Cloudflare proxy is in the path:**
   ```bash
   dig +short <domain>
   # Cloudflare IPs (104.x.x.x, 172.67.x.x) = orange cloud / proxied
   ```

2. **Confirm origin is healthy (bypass Cloudflare):**
   ```bash
   # Direct to origin if accessible
   curl -s -o /dev/null -w "HTTP %{http_code} | %{time_total}s" --max-time 10 http://<origin-ip>:<port>/api/status
   ```

3. **Check the service is reachable locally on the VPS:**
   ```bash
   curl -s -o /dev/null -w "HTTP %{http_code}" http://127.0.0.1:<port>/
   ```

## Solution patterns (pick one)

### Pattern A: Direct port exposure via nginx (service runs on VPS)

Use when the API gateway container runs directly on the VPS (e.g., Sub2API on 127.0.0.1:8081).

1. Create a new nginx server block listening on a public port:
   ```bash
   sudo bash -c 'cat > /etc/nginx/sites-available/<service>-direct << "EOF"
   server {
       listen <public-port>;
       server_name _;
       client_max_body_size 256m;
       underscores_in_headers on;

       location / {
           proxy_pass http://127.0.0.1:<container-port>;
           proxy_http_version 1.1;
           proxy_set_header Host $host;
           proxy_set_header X-Real-IP $remote_addr;
           proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
           proxy_set_header X-Forwarded-Proto $scheme;
           proxy_set_header Upgrade $http_upgrade;
           proxy_set_header Connection "upgrade";
           proxy_buffering off;
           proxy_cache off;
           proxy_read_timeout 3600s;
           proxy_send_timeout 3600s;
       }
   }
   EOF
   ln -sf /etc/nginx/sites-available/<service>-direct /etc/nginx/sites-enabled/<service>-direct
   nginx -t && systemctl reload nginx'
   ```

2. **Open the port in the VPS security group / firewall.** This is the step that's easy to forget:
   - Cloud provider security group (Vultr/AWS/GCP/etc.) — must be opened in the web console
   - `ufw allow <port>` if ufw is active
   - `iptables` if used directly

3. Verify:
   ```bash
   curl -s -o /dev/null -w "HTTP %{http_code}" http://<vps-ip>:<public-port>/
   ```

4. Update client config to use `http://<vps-ip>:<public-port>` instead of `https://<cloudflare-domain>`

### Pattern B: Reverse SSH tunnel (service runs on a remote machine/VM)

Use when the API gateway runs on a different machine (e.g., home VM) that can't be directly reached from the internet.

1. On the machine running the service, set up autossh:
   ```bash
   # Install
   apt install -y autossh sshpass

   # Create the tunnel (forwards VPS:<public-port> → localhost:<service-port>)
   sshpass -p '<vps-password>' autossh -M 0 -N \
     -o PreferredAuthentications=password \
     -o PubkeyAuthentication=no \
     -o ServerAliveInterval=30 \
     -o ServerAliveCountMax=3 \
     -o ExitOnForwardFailure=yes \
     -o StrictHostKeyChecking=no \
     -R 0.0.0.0:<public-port>:127.0.0.1:<service-port> \
     root@<vps-ip>
   ```

2. On the VPS, ensure `GatewayPorts yes` in `/etc/ssh/sshd_config` (needed for `0.0.0.0` binding).

3. Make it persistent (systemd service or add to rc.local / crontab @reboot).

4. Verify from outside:
   ```bash
   curl -s -o /dev/null -w "HTTP %{http_code}" http://<vps-ip>:<public-port>/
   ```

### Pattern C: Cloudflare DNS-only (grey cloud)

Use when you can put a domain directly on the origin without Cloudflare proxy.

1. In Cloudflare DNS dashboard, change the record from **Proxied** (orange cloud) to **DNS only** (grey cloud).
2. The domain now resolves directly to the origin IP — no 120s limit.
3. **Downside**: loses Cloudflare DDoS protection and SSL termination. You'll need your own SSL cert (Let's Encrypt).

## Pitfalls

- **VPS security group is separate from OS firewall.** Even if `ufw` is inactive and `iptables` is open, cloud providers (Vultr, AWS, GCP, etc.) have their own security group rules at the hypervisor level. A newly opened nginx port will show `LISTEN` on `ss` but return `HTTP 000` / connection refused from outside until the security group is updated. Always check BOTH layers.
- **`readTimeout` in cloudflared config is a red herring.** It controls cloudflared-to-origin timeout, NOT the Cloudflare edge timeout. Setting it to 600s does nothing for the 524.
- **Streaming doesn't fully solve it.** Even with `stream: true`, if the model's first token takes >120s (common with extended thinking on large context), Cloudflare will 524 before any data flows.
- **Sub2API `api_base_url` config.** Sub2API's frontend config (`window.__APP_CONFIG__.api_base_url`) controls where API requests go. If it points to a dead/unresolved domain, the frontend works but API calls fail. Check this value in the HTML source.
- **nginx `proxy_buffering off` is essential** for streaming LLM responses. Without it, nginx buffers the entire response before forwarding, defeating streaming benefits.
- **Docker container on `127.0.0.1` vs `0.0.0.0`.** If the container binds to `127.0.0.1:<port>`, only local nginx can reach it (Pattern A works). If it binds to `0.0.0.0:<port>`, it's also directly accessible on that port from outside (if firewall allows), which may be the simplest solution — but check if you want auth/rate-limiting via nginx first.
- **Port already in use by another local-only service.** Before picking a VPS port for a reverse tunnel, check what's already listening. A port like 3001 might show `127.0.0.1:3001` (local only, e.g. Uptime Kuma), but autossh binds `0.0.0.0:<port>` which won't conflict with a `127.0.0.1` listener — SSH's `-R 0.0.0.0:3001` binds on all interfaces while the existing service only binds loopback. Still, verify with `ss -tlnp` after starting the tunnel.
- **User says "没有别的端口嘛" = don't open new ports, reuse what works.** When the user pushes back on opening a new port, the right move is to find a port that's already externally reachable or create a tunnel that uses SSH (port 22 is almost always open). Don't insist on Pattern A if the user can't or won't modify the security group.

## Decision tree: which pattern to use

1. **Service on VPS, port already open?** → Pattern A (nginx direct exposure). Simplest.
2. **Service on VPS, can't open new port (security group)?** → Pattern B (reverse SSH tunnel to VPS itself, using a port that's already open or known-reachable). Yes, you can autossh from a machine to itself if needed, or from the VM.
3. **Service on remote VM, not directly reachable?** → Pattern B (autossh reverse tunnel from VM to VPS).
4. **Can toggle Cloudflare proxy off?** → Pattern C (grey cloud). Quick but loses DDoS protection.

**Key lesson**: When Pattern A fails because you can't open a new port in the cloud security group, don't wait for the user to fix it in a web console. Pivot to Pattern B immediately — create a reverse SSH tunnel using a port that's already proven reachable (test with curl first).

## Instance history (this environment)

- **newapi.bestcloudmail.com** (May 2026): NEWAPI on VM 192.168.1.9:3000, solved with Pattern B. Autossh reverse tunnel VM:3000 → VPS:3000. Systemd service: `newapi-reverse-tunnel.service`. Client endpoint: `http://85.121.123.59:3000`.
- **sub.bestcloudmail.com** (May 2026): Sub2API on VM 192.168.1.9:8081. First tried Pattern A (nginx on VPS port 8082) — port was blocked by cloud security group, `ss -tlnp` showed LISTEN but external curl got connection refused. Pivoted to Pattern B: autossh reverse tunnel VM:8081 → VPS:3001. Systemd service: `sub2api-reverse-tunnel.service`. Client endpoint: `http://85.121.123.59:3001`.

## See also

- `references/roger-infra-map.md` — port/service mapping for this VPS
- `templates/reverse-tunnel.service` — systemd unit template for autossh reverse tunnels (Pattern B). Replace `__SERVICE__`, `__VM_PORT__`, `__VPS_PORT__`, `__VPS_IP__`, `__VPS_PASSWORD__`.
