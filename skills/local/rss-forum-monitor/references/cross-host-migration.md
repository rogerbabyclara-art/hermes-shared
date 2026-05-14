# Cross-Host Migration of RSS/YT Monitor Stack

Verified workflow: move the entire blogwatcher + rss_check_new.py + yt_check_new.py + cron jobs stack from one Hermes host to another. Validated 2026-05-14 migrating from home VM (192.168.1.9, user `dev`, mainland China, behind proxy) → HK2 VPS (43.161.254.31, user `ubuntu`, HK datacenter, direct internet).

## When To Use

- Original host is unreliable (家里停电/断网)
- Moving from on-prem to cloud for 24/7 uptime
- Replacing a dead `hermes-gateway` rather than reviving it
- One host can't reach the other directly (NAT, internal network) — uses a middle machine

## Asset Inventory (what actually moves)

| Path | Purpose | Notes |
|---|---|---|
| `~/.hermes/scripts/rss_check_new.py` | RSS scan + JSON output | **Check for hardcoded paths/proxies before copying** |
| `~/.hermes/scripts/yt_check_new.py` | YouTube RSS scan | Same |
| `~/.hermes/scripts/rss_panel.py` | Flask config panel | Optional |
| `~/.hermes/rss_monitor_config.json` | Keywords + sources | ~1KB, pure config |
| `~/.hermes/yt_watched.json` | Already-pushed video IDs | Prevents re-pushing |
| `~/.blogwatcher-cli/blogwatcher-cli.db` | Article tracking SQLite | **Must migrate** — otherwise all old posts get re-pushed |
| `~/.local/bin/blogwatcher-cli` | Statically-linked Go ELF | x86_64; portable across Linux distros |
| `~/.hermes/cron/jobs.json` | Source of truth for job prompts | Read-only — re-register jobs on new host, don't copy |

## 3-Hop Transfer (when source and target can't reach each other)

If source (e.g. home internal `192.168.1.9`) can't SSH to target (e.g. cloud `43.161.254.31`), use a middle machine that can reach both:

```python
# On the middle machine (Win workstation in this session)
import paramiko
from pathlib import Path

STAGE = Path("./_tmp_migration")
STAGE.mkdir(exist_ok=True)

# 1. Pull from source
src = paramiko.SSHClient()
src.set_missing_host_key_policy(paramiko.AutoAddPolicy())
src.connect("192.168.1.9", 22, "dev", "PASSWORD", timeout=10)
sftp = src.open_sftp()
for remote, local_name in [
    ("/home/dev/.hermes/scripts/rss_check_new.py", "rss_check_new.py"),
    ("/home/dev/.hermes/scripts/yt_check_new.py", "yt_check_new.py"),
    ("/home/dev/.hermes/rss_monitor_config.json", "rss_monitor_config.json"),
    ("/home/dev/.hermes/yt_watched.json", "yt_watched.json"),
    ("/home/dev/.blogwatcher-cli/blogwatcher-cli.db", "blogwatcher-cli.db"),
    ("/home/dev/.local/bin/blogwatcher-cli", "blogwatcher-cli"),
]:
    sftp.get(remote, str(STAGE / local_name))
sftp.close(); src.close()

# 2. Patch scripts locally (remove /home/dev hardcodes, neutralize proxy defaults)
# Use sed or your patcher — see "Portability Patches" below

# 3. Push to target
tgt = paramiko.SSHClient()
tgt.set_missing_host_key_policy(paramiko.AutoAddPolicy())
tgt.connect("43.161.254.31", 22, "ubuntu", "PASSWORD", timeout=10)
sftp = tgt.open_sftp()
for local_name, remote, mode in [
    ("rss_check_new.py", "/home/ubuntu/.hermes/scripts/rss_check_new.py", 0o755),
    ("yt_check_new.py", "/home/ubuntu/.hermes/scripts/yt_check_new.py", 0o755),
    ("rss_monitor_config.json", "/home/ubuntu/.hermes/rss_monitor_config.json", 0o644),
    ("yt_watched.json", "/home/ubuntu/.hermes/yt_watched.json", 0o644),
    ("blogwatcher-cli.db", "/home/ubuntu/.blogwatcher-cli/blogwatcher-cli.db", 0o644),
    ("blogwatcher-cli", "/home/ubuntu/.local/bin/blogwatcher-cli", 0o755),
]:
    sftp.put(str(STAGE / local_name), remote)
    sftp.chmod(remote, mode)
sftp.close(); tgt.close()
```

Make sure target dirs exist first (`mkdir -p ~/.hermes/scripts ~/.blogwatcher-cli ~/.local/bin`).

## Portability Patches (apply before pushing)

Older script revisions had two portability bugs. **Always grep and fix before deploying:**

### 1. Hardcoded user paths

```bash
# bad
BW = "/home/dev/.local/bin/blogwatcher-cli"
```
```python
# good
BW = os.environ.get("BW_BIN") or str(Path.home() / ".local/bin/blogwatcher-cli")
```

### 2. Hardcoded proxy URL as default

```python
# bad — breaks the moment you deploy on a host that doesn't have that proxy
PROXY = "socks5h://93eb832fc3:xxx@174.139.197.25:11080"
```
```python
# good — empty default, opt-in via env var, host decides
PROXY = os.environ.get("RSS_PROXY", "")
# ...then in subprocess env:
if PROXY:
    env["HTTPS_PROXY"] = PROXY
    env["HTTP_PROXY"] = PROXY
```

For yt_check_new.py's curl-based fetcher: `curl --proxy ""` is valid and means "disable proxy", so no extra conditional needed in the curl arg list.

## Re-Registering Cron Jobs On New Host

Don't copy `~/.hermes/cron/jobs.json` — it has stale `last_run_at` / `next_run_at` / state. Instead:

1. Read the original job's `prompt`, `schedule`, `script`, `deliver`, `enabled_toolsets` from source `cron/jobs.json`
2. On target, `hermes cron create` (or use the `cronjob` tool) with the same params
3. New job will get a fresh `job_id` — update any references

## Telegram Group Channel Registration Pitfall

If `deliver` targets a group like `telegram:-5294966218`, the **target host's** `~/.hermes/channel_directory.json` must contain that group. Two requirements:

1. Bot is **added** to the group as a member
2. Bot has **received at least one message** in the group since gateway started polling

Adding the bot is not enough by itself. Workflow:

1. User invites bot to the group
2. User posts any message in the group (`test` works)
3. Check `cat ~/.hermes/channel_directory.json | jq '.platforms.telegram'` — group should appear with negative ID
4. If still missing after a message: `systemctl --user restart hermes-gateway` and try again

## Stopping The Old Host (after target verified)

Once the new host has run RSS+YT cron jobs successfully and pushed to TG:

```bash
# On old host
systemctl --user stop rss-panel.service          # stops the web panel
systemctl --user disable rss-panel.service       # prevents auto-restart
# hermes-gateway on old host already inactive — leave it that way
# Don't delete files yet, keep as backup for ~1 week
```

If both hosts keep their `hermes-gateway` running with the **same** TG bot token, they'll fight over `getUpdates` (polling conflict). Only ONE host should poll any given bot.

## Verification After Migration

```bash
# 1. blogwatcher reads DB OK
~/.local/bin/blogwatcher-cli blogs   # should show all configured sources

# 2. Script runs without errors and produces JSON
python3 ~/.hermes/scripts/rss_check_new.py | head -50
# First run after migration: outputs everything still marked unread (the
# accumulated backlog from when old host died). Subsequent runs only
# return truly new posts.

# 3. Trigger cron once and verify TG delivery
hermes cron run <new-job-id>
# Wait ~60s, check TG group/DM for message
```
