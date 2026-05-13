# User's Watched YouTube Channels

| Handle | Channel ID | Display Name |
|--------|-----------|--------------| 
| @joeyblog | UC_0Gn008Lj36lpoUSS8E_dg | Joey博客 |
| @kejilion | UCKqRheBWWCATRulqT1vxrww | 科技lion |
| @lingdujieshuo | UCvijahEyGtvMpmMHBu4FS2w | 零度解说 |
| @kejigongxiang | UCQoagx4VHBw3HkAyzvKEEBA | 科技共享 |

## Cron Job

- Job ID: `0e026720f658`
- Name: YouTube博主新视频摘要
- Schedule: `0 9 * * *` (daily 09:00 UTC)
- Script: `~/.hermes/scripts/yt_check_new.py`
- State file: `~/.hermes/yt_watched.json`

## Delivery Note

The cron job uses **httpx direct bot API** (not `send_message` tool) to push TG messages — `send_message` times out from cron sessions. See `hermes-cronjob-scheduling-pitfalls` for the exact httpx pattern. Proxy: `socks5://oapqwxqn:n1l45h99bz8q@45.38.111.11:5926`.

## Notes

- 科技共享 (@kejigongxiang) has subtitles disabled on most videos — expect title-only pushes.
- All 4 channels are Chinese-language tech/VPS/AI content.
- Channel IDs discovered via `curl -sL --proxy ... https://www.youtube.com/@HANDLE | grep -o 'channel_id=...'`
