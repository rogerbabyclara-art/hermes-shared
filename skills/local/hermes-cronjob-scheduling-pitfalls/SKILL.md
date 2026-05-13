---
name: hermes-cronjob-scheduling-pitfalls
description: Create Hermes cronjob schedules robustly, including handling cron-expression failures when croniter is unavailable to the scheduler runtime and using natural-language interval fallbacks.
version: 0.1.0
author: Hermes Agent
metadata:
  hermes:
    tags: [cronjob, scheduling, automation, pitfalls]
---

# Hermes Cronjob Scheduling Pitfalls

Use this when creating, adjusting, removing, or diagnosing missing Hermes `cronjob` tasks, especially fixed-time schedules such as `0 9 * * *`, daily reports, health checks, recurring Telegram deliveries, or user reports like “the scheduled thing did not arrive.”

## Workflow

1. **List existing jobs first** when modifying/removing jobs:
   - Use `cronjob(action='list')` and never guess job IDs.

2. **Prefer explicit recurring intervals for robustness** when exact wall-clock time is not required:
   - `every 30m`
   - `every 2h`
   - `every 24h`

3. **Use cron expressions only when fixed wall-clock timing matters**:
   - Example: `0 9 * * *` for 09:00 daily.
   - If creation fails with `Cron expressions require 'croniter' package`, do not assume installing `croniter` in the current agent Python will immediately fix the scheduler runtime. The cronjob tool/scheduler may be using a different environment or already-running process.

4. **Safe fallback when cron expressions fail**:
   - Create the job with a natural-language interval such as `every 24h` so the user gets a working automation immediately.
   - Clearly state that this is interval-based from creation time, not fixed local time.
   - If an accidental one-shot job was created while testing, remove it immediately after listing/confirming its returned job ID.

5. **Verification**:
   - Call `cronjob(action='list')` after creation/update/removal.
   - Report job name, job ID, schedule, enabled state, and next run time.

6. **Diagnosing a missing scheduled delivery**:
   - First list Hermes cron jobs; an empty list or missing job may itself explain why nothing arrived.
   - Inspect gateway/service state and recent gateway logs to distinguish “job did not exist/run” from “job ran but Telegram delivery failed.”
   - Check recent cron session files under `$HERMES_HOME/sessions/session_cron_*` and request dumps for evidence of last run, model/API errors, or delivery attempts.
   - If the user recently asked to disable/remove monitors, compare the missing delivery with the removed job names/IDs before looking for unrelated services.
   - For suspected external pushers (RSS/forum/PulseToTG/n8n/etc.), verify live processes, systemd units/timers, crontab, Docker containers, and project files before claiming they exist.

## Gotcha observed

A daily report was intended for fixed `0 9 * * *`, but `cronjob(action='create')` failed with:

```text
Cron expressions require 'croniter' package. Install with: pip install croniter
```

Installing `croniter` via the available `python3` did not make the cronjob tool immediately accept cron expressions. The reliable workaround was to create the job as `every 24h`, verify with `cronjob(action='list')`, and explain the timing limitation to the user.

## Pitfall: Telegram cron delivery can fail until gateway reconnects cleanly

A cron job may show `last_status: ok` while `last_delivery_error` contains:

```text
delivery error: Telegram send failed: httpx.ConnectError:
```

This means the script/model part completed, but Telegram delivery failed. Diagnose and recover in this order:

1. List cron jobs and inspect `last_delivery_error`:
   ```bash
   hermes cron list
   ```
2. Check gateway state and recent logs:
   ```bash
   systemctl --user is-active hermes-gateway
   journalctl --user -u hermes-gateway -n 80 --no-pager | grep -Ei 'telegram|proxy|polling|connect|error|failed|cron'
   ```
3. Verify the configured proxy with `curl` before blaming Hermes. Example current known-good RSS/TG proxy pattern:
   ```bash
   curl -sS --max-time 20 --proxy socks5h://USER:PASS@HOST:PORT https://api.telegram.org >/tmp/tg_probe.out && echo OK
   ```
4. If curl works but Hermes send still fails, restart the gateway and wait for the log line `Connected to Telegram (polling mode)`:
   ```bash
   systemctl --user restart hermes-gateway
   sleep 8
   tail -120 ~/.hermes/logs/gateway.log | grep -Ei 'Proxy detected|Connected to Telegram|Cron ticker started|ConnectError'
   ```
5. Prove end-to-end delivery with `send_message` to the real target before re-triggering the cron job. Do not claim recovery based only on `systemctl active`; polling and send can still be broken.
6. Re-trigger the job with `cronjob(action='run', job_id='...')` only after a successful probe message.

Note: `journalctl` may only show restart lines after the new process starts; `~/.hermes/logs/gateway.log` often contains the useful Telegram adapter messages (`Proxy detected`, `Connected to Telegram (polling mode)`, `Cron ticker started`).

## Pitfall: send_message tool times out or ConnectErrors from Web UI / cron sessions

`send_message(target="telegram")` can time out when called from a Web UI session or a cron job agent session, returning `"Telegram send failed: Timed out"`. The gateway itself may be healthy and polling normally — the issue is in the internal routing path from the Web UI context to the gateway send endpoint.

**Workaround — bypass send_message, call bot API directly via httpx:**

```python
import os, asyncio, httpx
from dotenv import load_dotenv
load_dotenv('/home/dev/.hermes/.env')
token = os.getenv('TELEGRAM_BOT_TOKEN')
chat_id = os.getenv('TELEGRAM_HOME_CHANNEL')
proxy = 'socks5://oapqwxqn:n1l45h99bz8q@45.38.111.11:5926'

async def send(text: str):
    async with httpx.AsyncClient(proxy=proxy, timeout=15) as c:
        r = await c.post(
            f'https://api.telegram.org/bot{token}/sendMessage',
            json={'chat_id': chat_id, 'text': text}
        )
        return r.status_code  # 200 = delivered

asyncio.run(send("your message here"))
```

**Note**: httpx socks proxy requires `httpx[socks]` (already present in hermes venv). Use `socks5://` (not `socks5h://`) with httpx — the `h` variant causes `ConnectError` in httpx's SOCKS implementation.

**Update 2026-05-04**: The original send_message timeout was caused by the SSH tunnel proxy at `127.0.0.1:12000` degrading. After switching the gateway to a direct SOCKS5 proxy (`socks5h://oapqwxqn:n1l45h99bz8q@45.38.111.11:5926`), `send_message` works normally from Web UI and cron sessions. If send_message times out, first verify/swap the proxy before using the httpx workaround.

In cron job prompts that need to push to TG, instruct the agent to use this httpx pattern instead of `send_message`. The cron job's `deliver` field can stay as `local` (not `telegram`) since delivery is handled manually in the prompt's Python code.

## Where cron job prompts are stored

Cron job data (including the full prompt) is stored in:
```
~/.hermes/cron/jobs.json
```

NOT in `~/.hermes/scheduler.db` (that file exists but is empty), and NOT in `~/.hermes/state.db` (that's session/message history only).

To read a specific job's prompt directly:
```python
import json
with open('/home/dev/.hermes/cron/jobs.json') as f:
    data = json.load(f)
# data is a list of job dicts; key is 'id' not 'job_id'
job = next(j for j in data if j['id'] == 'YOUR_JOB_ID')
print(job['prompt'])
```

The `cronjob(action='list')` tool returns `job_id` but the JSON file uses key `id` — don't mix them up.

## User-facing explanation pattern

When using the fallback, say something like:

> 我原本尝试设成每天固定 9 点，但当前 cron 表达式依赖 `croniter`，调度器仍未识别，所以先用稳定的 `every 24h` 创建成功，避免任务卡住。以后如果需要固定时区时间，可以再修复调度器环境后改回 cron 表达式。
