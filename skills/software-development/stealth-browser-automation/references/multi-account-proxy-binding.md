# Multi-Account ↔ Residential IP Binding (One-to-One)

When you're driving 10–100 stealth browser profiles against the same upstream service (Azure signup, Google account creation, social platforms), the IP↔profile mapping is the #1 thing detectors correlate on. This note captures a proven architecture for managing that mapping safely.

## The single rule

**One fingerprint seed ↔ one persistent profile dir ↔ one residential IP — for the life of the account.**

Breaking this rule once is what gets a whole batch flagged retroactively. A profile that has logged in 3 times from JP IP X, then suddenly appears from JP IP Y, is more suspicious than a brand-new profile from IP Y. Even worse: same IP appearing under two different Canvas fingerprints in the same hour.

This is why dynamic-sid / per-call IP rotation schemes (e.g. cliproxy's `sid-<random>` username param to get a fresh IP each request) are the WRONG default for account warming. Rotation is for scraping, not for account ops.

## Data model

Keep two tables (or two arrays in a single JSON), not one:

```jsonc
{
  "version": 2,
  "ip_pool": [
    {
      "id": "ip-001",
      "protocol": "socks5",          // socks5 / http
      "host": "us.cliproxy.io",
      "port": 3010,
      "username": "...",
      "password": "...",
      "provider": "cliproxy",         // detected from host string
      "status": "active",             // active | reserve | dead
      "bound_to": "azure-001",        // account name, or null
      "last_test_ip": "133.207.176.98",
      "last_test_geo": "JP / Tokyo / NTT",
      "last_test_at": 1735000000,
      "raw": "<original line user pasted>",
      "notes": ""
    }
  ],
  "accounts": [
    {
      "name": "azure-001",
      "ip_id": "ip-001",              // hard FK to ip_pool.id
      "fingerprint": 12345,
      "linked_csv_serial": "1039",    // optional cross-ref to source data
      "lock_status": "idle",          // idle | in_use
      "lock_owner": "local",          // user/host that holds the lock
      "lock_started_at": 0,
      "lock_note": "",                // free-text purpose
      "notes": ""
    }
  ]
}
```

Two-table over one-table because the same IP record's lifecycle (test results, status changes, eventual death) is independent of the account's lifecycle (created, warmed, monetized, archived). Joining them inline makes both messier.

## Three IP status states (not two)

- **active** — usable, currently bound or available to bind.
- **reserve** — held back as failover. Not handed out by batch-create; only the explicit "replace IP" action pulls from here.
- **dead** — proxy returned errors, exit IP got flagged, or user manually retired it. Never auto-bind.

The trap: only having `active` / `dead` means you have no buffer. When an account's IP suddenly stops working mid-session, you have nothing pre-vetted to swap in. Always keep ~20% of your purchased IPs in `reserve` after initial test-all.

## Manual lock (not auto-timeout)

For team scenarios where multiple humans share a pool of pre-registered accounts (case A: division of labor, not concurrent signup), automatic lock release based on time is the wrong primitive. A person walks away for lunch mid-task; auto-release lets a teammate grab the same account; both now drive the same profile from different machines and the account gets banned.

Use explicit start/stop:

- `[▶ Start]` button → set `lock_status=in_use`, record purpose, **launch the browser**.
- `[⏹ Stop]` button → kill the browser process, set `lock_status=idle`.
- Refuse to start a second session on a locked account, even from the same machine — show who locked it, when, and the purpose note.

The mental model is ADS-Power's start/stop, not Redis's `SET key value EX 600`.

## Failover: the "replace IP" action

Inevitable: the bound IP will go bad (provider rotates, ASN gets listed, residential user disconnects). The recovery flow:

1. User clicks `🔁 Replace IP` on the account row.
2. System pulls the next available `reserve` or unbound `active` IP, ordered by `id` (lowest first → predictable).
3. Old IP: `bound_to → null`, `status → dead` (assume it broke, user can manually revive to `active` later if it recovers).
4. New IP: `bound_to → <account>`, `status → active` (promote from reserve).
5. Append timestamp note to account: `notes += " [replaced IP @ 2026-05-13 04:12]"` — preserves history.

Refuse to replace if the account is `in_use` (locked) — operator must `[⏹ Stop]` first. Otherwise the running browser keeps using the dead IP.

## Batch-create: enforce 1:1 at creation time

When the operator clicks "create 50 accounts", do NOT pick IPs randomly or by hash. Sort `ip_pool` by `id` ascending, take the first 50 unbound-and-active, assign account-001↔ip-001, account-002↔ip-002, ... in order. Reasons:

- Predictable for the operator: account-007 always lives at ip-007. Easier to debug.
- Deterministic for re-runs: if half the batch fails and you retry, you don't shuffle previously-good bindings.
- Reserve IPs are skipped naturally because their status isn't `active`.

If `unbound_active_count < requested_count`, **fail the operation entirely** with a clear "need N IPs, have M" message. Do NOT partially fulfill — operator might not notice the deficit and end up with 30 of 50 accounts unbound.

## What goes on the central dashboard (when you build one)

For a multi-person team where one VPS dashboard shows lock state to everyone:

**DO publish:**
- Account name, lock status, lock holder, lock duration, purpose note.
- IP id (not full credentials — just the opaque id like `ip-007`).
- Last-test geo summary ("JP / Tokyo").

**DO NOT publish:**
- Raw proxy credentials (`host:port:user:pass`). Leaked from a dashboard = the provider sees abuse from 5 IPs and bans the underlying account.
- Account passwords, recovery emails, payment method last-4. Local DB only.
- Fingerprint seeds. They're not a secret per se, but no reason to expose.

Local DB is the source of truth. Dashboard is a read-mostly mirror with just enough info to coordinate "who's using what right now".

## Migration from rotating-sid schemes

If you previously used cliproxy / smartproxy / etc with per-call sid rotation:

1. Pick one fixed sid per account at creation time (`sid-<account_id>` works fine).
2. Bake the whole credential string into the `ip_pool` entry once.
3. Stop regenerating the sid at runtime. The whole point is that the egress IP stays as stable as the provider allows.

Some providers tie the same sid to the same exit IP for as long as the IP is healthy, then silently swap when it dies — that's the desired behavior. Other providers re-randomize the IP on each TCP connection regardless of sid; if so, that provider is unsuitable for 1:1 binding and you should switch to a sticky-session product (most residential providers have a "sticky 10/30/60 min" or "ISP" tier — pay for it).
