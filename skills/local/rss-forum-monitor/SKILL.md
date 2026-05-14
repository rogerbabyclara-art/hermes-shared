---
name: rss-forum-monitor
description: "Monitor Linux.do / NodeSeek / V2EX / Reddit RSS for keyword-matched posts and push to Telegram via cron job. Replaces PulseToTG."
version: 1.0.0
author: Hermes Agent
metadata:
  hermes:
    tags: [rss, forum, cron, telegram, monitoring]
---

# RSS Forum Monitor

Monitors Linux.do, NodeSeek, V2EX, and Reddit (r/LocalLLaMA, r/LLMDevs, r/ClaudeAI) RSS feeds for keyword-matched posts and pushes them to Telegram every 15 minutes. This setup replaced PulseToTG on 2026-05-04.

## Architecture

```
blogwatcher-cli (scan)
    → SQLite DB (~/.blogwatcher-cli/blogwatcher-cli.db)
    → rss_check_new.py (keyword filter + mark read)
    → JSON stdout
    → Hermes cron job (job_id: 0748b33b5633)
    → send_message → Telegram
```

## Installation

`blogwatcher-cli` binary lives at `~/.local/bin/blogwatcher-cli` (statically-linked Go ELF, ~17MB). Works on any x86_64 Linux.

Install if missing:
```bash
mkdir -p ~/.local/bin
# If host has internet (e.g. HK / overseas VPS): direct
curl -sL https://github.com/JulienTant/blogwatcher-cli/releases/latest/download/blogwatcher-cli_linux_amd64.tar.gz \
  | tar xz -C ~/.local/bin blogwatcher-cli
# If host needs proxy (e.g. mainland China): prefix with HTTPS_PROXY=socks5h://...
```

### Cross-host migration (copy from existing install)

Because the binary is statically linked and the SQLite DB is portable, the fastest way to clone the whole stack to a new host is `scp` + path adjustment. **The script paths in this skill assume `~` not `/home/dev/`** — they work for any user. If you see old `/home/dev/...` hardcodes anywhere, patch them to `Path.home() / ...` or `os.environ.get("BW_BIN")`.

See `references/cross-host-migration.md` for the verified end-to-end workflow.

## Configured Sources

| Name | Feed URL |
|------|----------|
| Linux.do | https://linux.do/latest.rss |
| NodeSeek | https://www.nodeseek.com/rss |
| V2EX | https://www.v2ex.com/index.xml |
| r/LocalLLaMA | https://www.reddit.com/r/LocalLLaMA/.rss?limit=25 |
| r/LLMDevs | https://www.reddit.com/r/LLMDevs/.rss?limit=25 |
| r/ClaudeAI | https://www.reddit.com/r/ClaudeAI/.rss?limit=25 |

Add/verify: `blogwatcher-cli blogs`

### Adding a Reddit feed

Reddit RSS works via `.rss` endpoint — requires proxy. Note: `blogwatcher-cli add` takes positional args, **not** `--name`/`--url` flags:

```bash
HTTPS_PROXY=socks5h://... blogwatcher-cli add "r/LocalLLaMA" \
  "https://www.reddit.com/r/LocalLLaMA/" \
  --feed-url "https://www.reddit.com/r/LocalLLaMA/.rss?limit=25"
```

Wrong (will fail): `blogwatcher-cli add --name "r/LocalLLaMA" --feed "..."` — flag names differ from docs.

## Config Web Panel (rss_panel.py)

A Flask-based config panel runs as a persistent systemd user service:

- **URL**: `http://<host-ip>:8765` (e.g. originally `http://192.168.1.9:8765` on the home VM; whatever LAN/WAN IP the host has)
- **Service**: `rss-panel.service` (systemctl --user)
- **Script**: `~/.hermes/scripts/rss_panel.py`
- **Python**: must be `<HERMES_HOME>/hermes-agent/.venv/bin/python3.11` (Flask is in the hermes-agent venv, not system python). Adjust path per host — e.g. `/home/ubuntu/.hermes/...` on HK2, `/home/dev/.hermes/...` on the home VM.

Features: keyword add/delete (tag UI), interval change (auto-syncs cron schedule in scheduler.db), source add/delete (auto feed_url inference for Reddit).

To restart: `systemctl --user restart rss-panel`
To check logs: `journalctl --user -u rss-panel -n 20`

### Flask install location pitfall

Flask is in `/home/dev/.hermes/hermes-agent/.venv` — NOT in system python3, NOT in uv cpython. Always use the hermes-agent venv python for this service. `pip install flask --user` and `uv pip install flask` both install to wrong locations and the service will fail with `ModuleNotFoundError: No module named 'flask'`.

### Interval save: writes scheduler.db directly

The panel updates `scheduler.db` directly via SQLite (table `jobs`, column `schedule`) using `job_id LIKE '0748b33b5633%'`. No restart needed — hermes scheduler picks up the new schedule on the next tick.

## User-facing management

All config lives in `~/.hermes/rss_monitor_config.json`. Script reads it on every run and auto-syncs blogwatcher. When user requests changes (via chat or the web panel at :8765):

| User says | Action |
|---|---|
| 加关��词 X | append X to `keywords` array in config |
| 删关键词 X | remove X from `keywords` array in config |
| 加论坛 {name} {url} | append to `sources` array (auto-detect feed_url); script will blogwatcher-add on next run |
| 删论坛 {name} | remove from `sources` array; script will blogwatcher-remove on next run |
| 改间隔 N分钟 | set `interval_minutes: N` in config, then `cronjob(action='update', job_id='0748b33b5633', schedule='*/N * * * *')` |

No need to touch blogwatcher-cli manually — the script calls `sync_sources()` on every run.

### Feed URL patterns for common platforms
- Reddit: `https://www.reddit.com/r/{sub}/.rss?limit=25`
- HN: `https://news.ycombinator.com/rss`
- Generic: pass the page URL, blogwatcher-cli will auto-discover

## Keywords Monitored

Stored in `~/.hermes/rss_monitor_config.json` → `keywords` array.

Current: `公益 中转 api 4.7 便宜 azure claude gpt hermes 免费 节点 机场 翻墙 vps proxy relay token openai anthropic litellm openrouter pricing rate limit reseller cheap free tier`

## Scripts & Templates

- `scripts/rss_check_new.py` — main scan script (LLM-agent mode: outputs JSON, cron prompt does formatting). **Portable** — no hardcoded paths or proxy. Set `RSS_PROXY` env var if your host needs a proxy.
- `scripts/rss_push_noagent.py` — **no_agent mode** alternative: scan + format + emit final Telegram text in one shot, **no LLM call**. Use when cron+LLM is flaky (see `references/no-agent-mode.md`) or when you just want to skip the LLM tax for a fixed-template task.
- `scripts/yt_check_new.py` — YouTube channel RSS scan + dedup via `yt_watched.json`. Set `YT_PROXY` for hosts that need proxy.
- `scripts/rss_panel.py` — Flask config panel (port 8765, dark UI, keyword/source/interval management)
- `templates/rss-panel.service` — systemd user service unit for the panel
- `references/cross-host-migration.md` — verified workflow for moving the whole stack between Hermes hosts (e.g. on-prem → cloud)
- `references/proxy-vless-probes.md` — benchmarking proxies/VLESS nodes before changing cron scripts
- `references/no-agent-mode.md` — when/how to switch cron to `no_agent: True` (bypasses cron LLM api_key/api_mode bugs) + TG bot polling single-owner rule

Deploy panel from scratch:
```bash
cp ~/.hermes/skills/local/rss-forum-monitor/scripts/rss_panel.py ~/.hermes/scripts/rss_panel.py
cp ~/.hermes/skills/local/rss-forum-monitor/templates/rss-panel.service ~/.config/systemd/user/rss-panel.service
systemctl --user daemon-reload && systemctl --user enable rss-panel --now
```

```bash
# Test run (should output [] if no new posts since last scan)
python3 ~/.hermes/scripts/rss_check_new.py
```

## Cron Job

- **Job ID**: `0748b33b5633` (original on 192.168.1.9; will differ per host after re-registration)
- **Name**: RSS论坛帖子推送
- **Schedule**: `*/60 * * * *` (hourly — was documented as `*/15` historically but actual jobs.json shows hourly)
- **Script**: `rss_check_new.py`
- **Toolsets**: `web` only (no terminal needed)
- **Deliver**: `telegram:-5294966218` (group, not DM) — **target group must already exist in `~/.hermes/channel_directory.json` on the host running cron**. Adding the bot to the group is not enough; the bot needs to receive at least one message in the group for the gateway to register it.

### Reading/modifying the prompt

The full job prompt (including formatting instructions) is stored in:
```
~/.hermes/cron/jobs.json
```
Use `cronjob(action='list')` to inspect via API, or read the file directly. Note: file uses key `id`, but the API returns `job_id`.

### Current prompt format

Each matched post is sent as a **separate Telegram message**. The user explicitly corrected the desired format on 2026-05-05: this is **not** a summary/digest task. Do not fetch/open the post, do not summarize, do not classify, and do not add “重点/一句话总结”. Telegram should generate the thumbnail/description preview from the link itself.

Required per-post format:

```
📌 【{blog}】{title}
🔗 {url}
🏷 关键词：{keywords 用顿号连接；如果为空写“未标记”}
🕒 时间：{published}
```

Rules:
- Every matched post is sent as a separate Telegram message; do not merge multiple posts.
- URL stays on its own line for Telegram preview/unfurl.
- Only include title, link, matched keywords, and time.
- No summaries, no category labels, no bullet “重点”, no “一句话总结”, no dividers, no meta explanation.
- `rss_check_new.py` should include a `keywords` array per matched article so the cron prompt can render the matching terms.

To change formatting, update via `cronjob(action='update', job_id='0748b33b5633', prompt='...')`.

### Removing the "To stop or manage this job" footer

Hermes appends this footer to all cron deliveries by default (`wrap_response=True`). To disable **globally** (affects all cron jobs):

```yaml
# ~/.hermes/config.yaml
cron:
  wrap_response: false
```

There is no per-job override — it's global only. Disabling removes the `Cronjob Response: ...` header and the stop-reminder footer from every cron job's Telegram output.

## DB Schema Pitfall

blogwatcher-cli v0.2.0 uses this schema for articles — NOT the intuitive column names:

```sql
id, blog_id, title, url, published_date, discovered_date, is_read, categories
```

- Read flag: `is_read` (BOOLEAN, 0/1) — **not** `read_at` or `read`
- Date column: `published_date` — **not** `published_at`
- No `--json` flag on `blogwatcher-cli articles` — must query SQLite directly

## Proxy

Reference: see `references/proxy-vless-probes.md` for the reusable workflow to benchmark SOCKS proxies and temporary VLESS/Cloudflare nodes with sing-box before changing cron scripts.

**Proxy is OPTIONAL.** Whether you need one depends on the host's geography:

| Host location | Linux.do / NodeSeek / V2EX | Reddit | YouTube |
|---|---|---|---|
| Mainland China (e.g. 192.168.1.9) | direct ✅ | **needs proxy** | **needs proxy** |
| HK / overseas VPS (e.g. HK2 43.161.254.31) | direct ✅ | direct ✅ | direct ✅ |

**Script behavior** (current versions): both `rss_check_new.py` and `yt_check_new.py` read `RSS_PROXY` / `YT_PROXY` from environment. **Empty = direct.** Do NOT hardcode proxy URLs in the scripts themselves — older revisions had `socks5h://93eb832fc3:...@174.139.197.25:11080` baked into `rss_check_new.py` and that broke portability when migrating to overseas hosts.

If you need to set a proxy on a per-host basis:
```bash
# In ~/.hermes/cron/jobs.json job's prompt, or as systemd Environment=, or in a wrapper script
export RSS_PROXY=socks5h://user:pass@host:port
```

Useful trick: `curl --proxy ""` (empty string) **disables** the proxy for that curl call — used in `yt_check_new.py` when `PROXY=""`.

### Gateway proxy startup pitfall

httpx in hermes-gateway connects to the SOCKS5 proxy at startup. If the proxy isn't reachable at that exact moment, the Telegram polling enters a reconnect loop (`attempt 1/10`) and **never recovers** — even after the proxy comes back. Fix: `systemctl --user restart hermes-gateway` after confirming proxy is alive with `curl --proxy socks5h://... https://api.telegram.org`.

Diagnosis: `journalctl --user -u hermes-gateway -n 10 --no-pager | grep -E 'Proxy|ConnectError|polling'`

Note: `curl` succeeding does NOT mean hermes-gateway will succeed — they're separate processes. Always verify gateway logs after proxy changes.

## What Replaced What

| Old | New |
|-----|-----|
| PulseToTG (`pulsetotg-scheduler.service`) | blogwatcher-cli + rss_check_new.py cron |
| PANA userbot (`hermes-userbot.service`) | Stopped — no replacement needed |
| `myhappycapy_bot` (unknown bot in group) | Kicked from group |

PulseToTG and PANA services are stopped and disabled as of 2026-05-04.
