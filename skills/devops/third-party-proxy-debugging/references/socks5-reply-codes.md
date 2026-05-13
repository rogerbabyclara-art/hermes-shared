# SOCKS5 reply codes (RFC 1928)

When a SOCKS5 server rejects a connection, it returns a 1-byte reply code. curl surfaces it in the `(N)` suffix on error 97 ("cannot complete SOCKS5 connection. (N)"). Library errors may include the raw number or a string version.

| Code | RFC name | What it actually means in proxy-vendor practice |
|------|----------|------------------------------------------------|
| 0x00 | succeeded | Connection OK |
| 0x01 | general SOCKS server failure | Catch-all. Often disguises auth failure or vendor-side outage |
| 0x02 | **connection not allowed by ruleset** | **IP whitelist block, zone misconfig, or account suspended.** Most common rejection from residential proxy vendors |
| 0x03 | Network unreachable | Proxy can't reach destination (your target host is down) |
| 0x04 | Host unreachable | Destination DNS resolves but unreachable |
| 0x05 | Connection refused | Destination actively refused |
| 0x06 | TTL expired | Routing loop, very rare |
| 0x07 | Command not supported | You sent SOCKS5 BIND or UDP ASSOCIATE to a TCP-only proxy |
| 0x08 | Address type not supported | You sent IPv6 to an IPv4-only proxy, or domain name to a proxy that requires resolved IPs |

## What library error messages map to

`socks-proxy-agent` (Node):
- `Socks5 proxy rejected connection - NotAllowed` → 0x02
- `Socks5 proxy rejected connection - GeneralFailure` → 0x01
- `Socks5 Authentication failed` → not in RFC, raised during the auth sub-negotiation (RFC 1929) before the main reply

`PySocks`:
- Throws `socks.GeneralProxyError` with the code number embedded

`curl`:
- Exit 97 + "cannot complete SOCKS5 connection. (N)" — N is the reply code in decimal
- Exit 5 — couldn't resolve proxy host
- Exit 7 — couldn't connect to proxy host

## Auth sub-negotiation errors (RFC 1929)

Before the connection reply, SOCKS5 with auth does a username/password handshake. Failures here are separate from the reply codes above:

| Status byte | Meaning |
|-------------|---------|
| 0x00 | Auth OK |
| 0x01..0xFF | Auth failed (server-defined reason, usually "bad credentials") |

A 0x01 auth failure is what you get with **wrong password**. A 0x02 connection reply is what you get with **right password but disallowed source IP / zone**. This distinction is gold for debugging: pass-then-reject means whitelist; immediate-reject means credentials.
