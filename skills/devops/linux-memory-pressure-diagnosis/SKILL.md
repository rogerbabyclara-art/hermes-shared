---
name: linux-memory-pressure-diagnosis
description: Diagnose and relieve Linux server memory pressure — swap usage, hung processes, OOM risk, and safe cleanup steps. Use when a server feels slow, responses are sluggish, or swap usage is high. Covers self-hosted agent stacks (Hermes/OpenClaw) and general VPS scenarios.
tags: [linux, memory, swap, devops, vps, performance]
---

# Linux Memory Pressure Diagnosis & Cleanup

## When to use
- Server responses feel slow / API calls lag
- User reports "回复慢" / "掉线"
- You suspect swap thrashing or OOM kills
- After a long-running session where processes may have leaked

## CRITICAL CONCEPT: RAM vs Disk — Never Confuse These
- **RAM (memory)**: what running processes consume. `free -h` shows this. Determines speed.
- **Disk (storage)**: where files live. `df -h` shows this. Does NOT affect runtime performance directly.
- **Swap**: disk space used as overflow RAM. When swap is heavily used → everything slows down.
- **DO NOT** say "that machine has 51GB free so we can move a service there" if 51GB refers to disk space and the RAM is unknown.

## Step 1 — Full snapshot (run first, always)
```bash
free -h && echo "===" && \
ps aux --sort=-%mem | head -20 && echo "===" && \
df -h / && echo "===" && \
ps aux | awk '$8=="Z"' | wc -l && echo "zombies" && \
ps aux | grep -E "rg |bash -c rg" | grep -v grep | wc -l && echo "hung rg procs"
```

Key numbers to read:
- `available` in `free -h` → what processes can actually use (more meaningful than `free`)
- Swap `used` > 200MB → already thrashing, needs relief
- Any zombies → parent process leak
- Hung `rg` / `bash -c rg` → Hermes tool calls that never exited

## Step 2 — Identify top memory consumers
```bash
ps aux --sort=-%mem | awk 'NR<=15{printf "%-10s %5s %5s %s\n", $1, $3, $4, $11}'
```

Hermes stack typical consumers (on 4GB VM):
| Process | Normal RSS | Peak |
|---|---|---|
| hermes-gateway | ~200MB | ~1.2GB (leak over time) |
| hermes-webui | ~200MB | ~2.2GB (peak on heavy use) |
| hermes mcp serve ×2 | ~84MB each | — |
| hermes-wechat | ~40MB | ~106MB |
| hermes-metrics + rss_panel | ~50MB total | — |

## Step 3 — Kill hung processes
Hermes `rg` tool calls from past sessions sometimes hang indefinitely:
```bash
# Identify
ps aux | grep -E "rg |bash -c rg" | grep -v grep

# Kill all (get PIDs from above, then)
kill -9 <pid1> <pid2> ...

# Or kill all in one shot
ps aux | grep -E "bash -c rg" | grep -v grep | awk '{print $2}' | xargs -r kill -9
```

## Step 4 — Force swap clear (reclaim memory)
Only do this when swap > 100MB and available RAM > 500MB — otherwise you risk OOM:
```bash
sudo swapoff -a && sudo swapon -a
```
This flushes swap back to RAM. `used` in `free -h` may jump temporarily (that's normal — swap pages moving to RAM), then settle lower.

## Step 5 — Safe disk cleanup (no service impact)
```bash
# /tmp large artifacts
du -sh /tmp/* 2>/dev/null | sort -rh | head -10
rm -rf /tmp/camoufox-* /tmp/sub2api-* /tmp/ytvenv /tmp/hermes-snap-*.sh /tmp/node-compile-cache

# apt cache
sudo apt-get clean

# journal logs (keep 100MB)
sudo journalctl --vacuum-size=100M

# pip cache (safe — doesn't affect installed packages)
pip cache purge 2>/dev/null || rm -rf ~/.cache/pip/
```

Typical recoverable disk space on a Hermes VM after months of use:
| Source | Typical Size |
|---|---|
| /tmp (camoufox, build artifacts) | 600–900MB |
| apt cache | 400–600MB |
| journal logs | 500–700MB |
| pip cache | 50–100MB |

## Step 6 — Restart leaking services
If gateway has been running for days and RSS is > 500MB, restart it:
```bash
systemctl --user restart hermes-gateway.service
# Wait 30s then verify
sleep 30 && ps aux | grep "gateway run" | grep -v grep | awk '{printf "%sMB\n", $6/1024}'
```

## Step 7 — Verify improvement
```bash
free -h && df -h /
```
Compare `available` and swap `used` to Step 1 baseline.

## Step 5b — Deep cache cleanup (check before deleting)

These are large but require confirmation before deleting — ask the user:

```bash
# Full cache survey
du -sh ~/.cache/* 2>/dev/null | sort -rh | head -10
find /home/dev -name ".venv" -maxdepth 4 2>/dev/null | while read d; do du -sh "$d"; done
docker system df
docker volume prune -f   # only removes UNUSED volumes
```

| Cache | Typical Size | Safe to delete? | Consequence |
|---|---|---|---|
| `~/.cache/uv` | 3–5GB | ✅ Yes, always | uv re-downloads on next install |
| `~/.cache/camoufox` | 1–2GB | ✅ if not using browser tool | re-download needed |
| `~/.cache/ms-playwright` | 500MB–1GB | ✅ if not using playwright | re-download needed |
| `~/.cache/huggingface` | varies | ⚠️ Ask first | re-download on next model use |
| `~/.cache/pip` | 50–200MB | ✅ Yes | no effect on installed packages |
| `~/.cache/node-gyp` | 50–100MB | ✅ Yes | rebuild on next native npm install |

```bash
# uv cache — always safe, biggest win
uv cache clean

# playwright (if not in use)
rm -rf ~/.cache/ms-playwright

# camoufox (if not using browser tool)
rm -rf ~/.cache/camoufox
```

**Hermes automation tasks (YouTube monitor, RSS push) do NOT use playwright or camoufox** — those scripts use plain HTTP/curl. Safe to delete caches for those tools if the user isn't actively using `/browser`.

## Pitfalls
- `free` column ≠ actually usable. Always read `available`, not `free`.
- `swapoff -a && swapon -a` temporarily increases RAM `used` — this is expected, not a problem.
- Two `hermes mcp serve` processes running simultaneously is normal (each tool connection spawns one). Only kill extras if more than 2 exist.
- `hermes-socks-tunnel.service` in `failed` state is a separate issue — check if it's needed before fixing.
- Disk space and RAM are completely different resources. A machine with 51GB disk free but 512MB RAM free cannot run a 2GB-peak service.

## References
- `references/hermes-vm-memory-profile.md` — typical Hermes stack memory breakdown on 4GB VM
