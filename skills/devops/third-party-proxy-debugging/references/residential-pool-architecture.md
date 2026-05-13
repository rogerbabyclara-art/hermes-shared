# Residential Pool Architecture — Account ↔ IP Binding Patterns

For workflows where N accounts must each get a stable, isolated residential IP (multi-account site automation, browser-fingerprint isolation, regulatory compliance), the data model and operations need to be designed up front. This is the architecture that survived contact with real users.

## Core principle: 1:1 binding, never multiplexed

**One account ↔ one IP, hard bound by ordinal.** `account-001` ↔ `ip-001`, `account-002` ↔ `ip-002`, etc.

Why not "pool of IPs, account picks one each session"?

- Sites fingerprint the (cookie, IP, browser) triplet. A varying IP triggers extra verification.
- Recovery (password reset, 2FA) breaks if the recovery email triggers from a different ASN than account creation.
- Reasoning about "which account is currently using which IP" becomes a coordination problem across machines/team members.

**Bind by ordinal, never by test result.** Don't filter to "only IPs that passed the smoke test" — residential pools are flaky (see `third-party-proxy-debugging` main file). Bind ip-001 → account-001 regardless. Failures in real use are handled by hot-swap (below), not by pre-flight gating.

## Data model (JSON file is fine for ≤ 1000 entries)

```json
{
  "version": 2,
  "ip_pool": [
    {
      "id": "ip-001",                  // padded, sortable
      "protocol": "socks5",
      "host": "...", "port": 10000,
      "username": "...", "password": "...",
      "provider": "711proxy",          // auto-detected, for UI grouping
      "status": "active",              // active | reserve | dead
      "bound_to": "azure-001",         // null if unbound
      "last_test_ip": "...",           // informational, not gate
      "last_test_geo": "JP / Tokyo / NTT",
      "last_test_at": 1735000000,
      "raw": "<original paste line>",  // for audit
      "notes": ""
    }
  ],
  "accounts": [
    {
      "name": "azure-001",
      "ip_id": "ip-001",               // points to ip_pool[].id
      "fingerprint": 12345,             // browser fingerprint seed
      "linked_csv_serial": "1039",      // optional cross-ref
      "lock_status": "idle",            // idle | in_use
      "lock_owner": "local",            // for future team mode
      "lock_started_at": 0,
      "lock_note": "",
      "notes": ""
    }
  ]
}
```

### Three IP states

- **active** — bind candidate, in regular rotation
- **reserve** — bind candidate, lower priority (extra capacity for hot-swap)
- **dead** — user **manually** confirmed broken after real-use failures. NEVER auto-set from test result.

Allow binding from `active` + `reserve` both. Exclude only `dead`. This makes the spare capacity available for batch-bind without forcing the user to micro-manage status.

## Manual lock model (vs auto-timeout)

Sites with strict per-account behavior detection (Azure portal, banking apps) cannot tolerate "session timed out, another worker grabbed the account mid-operation". So:

- Lock acquired by **explicit user action** (Start button)
- Lock released by **explicit user action** (Stop button)
- No timeout. No heartbeat. No "stale lock" cleanup.
- Optional lock_note records "what is this session doing right now" for visibility (especially valuable in team mode).

This is the ADS-Browser / MoreLogin model — Start opens browser, Stop closes browser, lock state mirrors that.

If the worker crashes with lock still held → user manually clicks Stop to clear. Trust the human to know.

## Hot-swap (the "replaceIP" operation)

When a bound IP turns out to be bad **during real use**, the user needs one-click rescue:

```
replaceIP(account_name, optional_new_ip_id):
  1. Find old_ip from account.ip_id
  2. If new_ip_id specified:
       new_ip = pool[new_ip_id]
       must not be bound to any other account
     Else:
       new_ip = lowest-id unbound IP in (active ∪ reserve)
  3. Old IP: bound_to = null, status = "dead" (rescue implies brokenness)
  4. New IP: bound_to = account_name, status promote reserve → active
  5. Account: ip_id = new_ip.id, append timestamped note
```

Key decision: **auto-mark old IP as dead**, not "back to active". The act of replacing is the user's strongest signal that the IP is bad. Letting it go back into rotation re-burns the next account that gets it.

## Random-sample testing (NOT full-pool testing)

After import or whenever the user feels paranoid, offer a "test 3 random" button rather than "test all 200". Reasons:

- Full-pool test produces alarming-looking 30% failure rates that mean nothing (see main skill file)
- Sample of 3-5 is enough to prove credentials and whitelist are correct
- Takes 3-10 seconds vs 1-3 minutes
- Doesn't trigger vendor-side anti-burst throttling

UI text matters: "随机抽测 3 个 / Sample 3" framing. Don't call it "quick test" — users will assume the result is comprehensive.

## Batch-bind UX language

When generating N accounts with 1:1 IP binding, make the binding rule visible in the modal:

> 按 IP id 顺序硬绑, 不看测试结果。失败的以后用 [🔁 换IP]
> (Bind by IP id order, ignore test results. Use [🔁 ChangeIP] later for failures.)

Without this, users see "100 active IPs but only 47 passed test" and assume they can only bind 47, which is wrong and demoralizing.

## Team-mode considerations (VPS readonly dashboard)

If a team of 3-5 needs to coordinate "who's using which account right now":

- Local machine is **single source of truth** for accounts, IPs, lock state
- VPS only **receives broadcasts** of lock_status changes (push, not pull)
- VPS dashboard is **read-only viewer** — no DB, no auth complexity, just shows current state
- Auth: HTTP Basic with shared password, IP allowlist (since team has VPN anyway)
- Do NOT replicate raw credentials (host/port/user/pass) to VPS — leak surface. Show only account names, lock status, lock note, IP geo. That's enough for "who has azure-007 right now".

This avoids the central-database complexity trap. Locally everything still works offline. VPS down doesn't block anyone.
