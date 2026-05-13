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

`blogwatcher-cli` binary is at `/home/dev/.local/bin/blogwatcher-cli` (v0.2.0).

Install if missing:
```bash
mkdir -p /home/dev/.local/bin
curl -sL --proxy socks5h://91575d8a92:y0O65lbtnkwv0HvOTes0B0cN@3.115.250.37:11080 \
  https://github.com/JulienTant/blogwatcher-cli/releases/latest/download/blogwatcher-cli_linux_amd64.tar.gz \
  | tar xz -C /home/dev/.local/bin blogwatcher-cli
```

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

- **URL**: http://192.168.1.9:8765
- **Service**: `rss-panel.service` (systemctl --user)
- **Script**: `~/.hermes/scripts/rss_panel.py`
- **Python**: `/home/dev/.hermes/hermes-agent/.venv/bin/python3.11` (Flask is in hermes-agent venv)

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

- `scripts/rss_check_new.py` — main scan script (reads config, syncs blogwatcher, keyword filter, JSON output)
- `scripts/rss_panel.py` — Flask config panel (port 8765, dark UI, keyword/source/interval management)
- `templates/rss-panel.service` — systemd user service unit for the panel

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

- **Job ID**: `0748b33b5633`
- **Name**: RSS论坛帖子推送
- **Schedule**: `*/15 * * * *`
- **Script**: `rss_check_new.py`
- **Toolsets**: `web` only (no terminal needed)
- **Deliver**: `telegram:-5294966218` (group, not DM)

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

All RSS fetches use `socks5h://91575d8a92:y0O65lbtnkwv0HvOTes0B0cN@3.115.250.37:11080` via `HTTPS_PROXY` / `HTTP_PROXY` env vars passed to the scan subprocess.

Updated 2026-05-05 (old `45.38.111.11:5926` confirmed dead). Same credentials apply to hermes-gateway (`~/.config/systemd/user/hermes-gateway.service.d/proxy.conf`) and both rss/yt scripts.

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
