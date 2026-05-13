# Cloudflare 524 on Tunnel -> nginx -> NEWAPI (Claude VSCode)

Use this reference when a self-hosted NEWAPI behind Cloudflare Tunnel shows `Error 524` for Claude / VSCode / long-running `/v1/messages` requests.

## Evidence pattern from a real incident

Topology confirmed from live config:

`Claude VSCode -> Cloudflare edge -> cloudflared -> nginx(:80) -> new-api(:3000)`

Live config clues:
- `/etc/cloudflared/config-new.yml` routes `newapi.bestcloudmail.com` to `http://localhost:80`
- `/etc/nginx/sites-enabled/newapi` proxies `/` to `http://127.0.0.1:3000`
- `new-api` container healthy on `:3000`

Incident timestamps correlated:

### nginx access log
```text
127.0.0.1 - - [09/May/2026:17:13:33 +0000] "POST /v1/messages?beta=true HTTP/1.1" 499 0 "-" "claude-cli/2.1.138 (external, claude-vscode, agent-sdk/0.2.138)"
```

### cloudflared journal
```text
ERR error="Incoming request ended abruptly: context canceled" originService=http://localhost:80
ERR failed to serve incoming request error="Failed to proxy HTTP: Incoming request ended abruptly: context canceled"
```

### Cloudflare error body seen by user
```json
{
  "status": 524,
  "detail": "The origin web server did not return a complete response within the 120-second Proxy Read Timeout window."
}
```

### NEWAPI DB query result
In the same incident window, generic API requests (`gpt-5.4`) were present in `logs`, but **no matching Claude `/v1/messages` row** existed.

Interpretation:
- public web site may still be up
- NEWAPI container may still be healthy
- generic requests may still succeed
- but Claude VSCode long-running request path is unhealthy
- if the DB lacks the matching Claude row, the request likely died before NEWAPI completed its normal request lifecycle

## What this means

This evidence pattern means:
1. nginx streaming config may have been necessary to fix, but
2. the remaining bottleneck is Cloudflare's edge timeout behavior for long Claude requests, not a dead NEWAPI container

Do **not** conclude "site works, so issue fixed".

## Minimum nginx baseline

```nginx
location / {
    proxy_pass http://127.0.0.1:3000;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;

    proxy_buffering off;
    proxy_request_buffering off;
    proxy_cache off;
    chunked_transfer_encoding off;

    proxy_read_timeout 3600s;
    proxy_send_timeout 3600s;
    send_timeout 3600s;
}
```

If these are missing, add them first. But if 524 persists with the evidence pattern above, stop pretending nginx is the last boss.

## Recommended next move once nginx is already fixed

Primary fix path for Claude / VSCode long requests:
- give the client a **non-Cloudflare path**
  - DNS-only subdomain directly to origin/VPS
  - direct IP + dedicated port
  - VPN / private-network path

Secondary / optional:
- tune `cloudflared originRequest.readTimeout`
- test direct origin vs Cloudflare path side-by-side

## Reporting language to use

Say all three if true:
- web console reachable
- NEWAPI service healthy
- Claude VSCode long `/v1/messages?beta=true` requests still die in Cloudflare path

That phrasing prevents the classic false reassurance where a healthy homepage is mistaken for a healthy coding path.
