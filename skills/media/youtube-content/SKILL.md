---
name: youtube-content
description: "YouTube transcripts to summaries, threads, blogs."
---

# YouTube Content Tool

## When to use

Use when the user shares a YouTube URL or video link, asks to summarize a video, requests a transcript, or wants to extract and reformat content from any YouTube video. Transforms transcripts into structured content (chapters, summaries, threads, blog posts).

Extract transcripts from YouTube videos and convert them into useful formats.

## Setup

In a Hermes venv environment (the default in this setup), the system Python is externally managed — use the venv pip directly:

```bash
# Hermes venv pip (works in this environment)
# Proxy: socks5h://127.0.0.1:2080 (updated 2026-05-04; was 127.0.0.1:12000)
pip3 install youtube-transcript-api --proxy socks5h://127.0.0.1:2080

# Verify it's visible to the agent's Python
python3 -c "import youtube_transcript_api; print('ok')"
```

**Pitfall**: `pip install --break-system-packages` installs into the system Python, NOT the `.venv` that Hermes runs in. The agent's `python3` resolves to `/home/dev/.hermes/hermes-agent/.venv/bin/python3` — always use `pip3` (which also resolves to the venv) or confirm with `which python3` first.

## Helper Script

`SKILL_DIR` is the directory containing this SKILL.md file. The script accepts any standard YouTube URL format, short links (youtu.be), shorts, embeds, live links, or a raw 11-character video ID.

```bash
# JSON output with metadata (proxy required in this environment)
HTTPS_PROXY=socks5h://127.0.0.1:2080 python3 SKILL_DIR/scripts/fetch_transcript.py "https://youtube.com/watch?v=VIDEO_ID"

# Plain text (good for piping into further processing)
HTTPS_PROXY=socks5h://127.0.0.1:2080 python3 SKILL_DIR/scripts/fetch_transcript.py "URL" --text-only

# With timestamps
HTTPS_PROXY=socks5h://127.0.0.1:2080 python3 SKILL_DIR/scripts/fetch_transcript.py "URL" --timestamps

# Chinese-first language fallback chain (recommended for zh channels)
HTTPS_PROXY=socks5h://127.0.0.1:2080 python3 SKILL_DIR/scripts/fetch_transcript.py "URL" --language zh-Hans,zh,en
```

## Output Formats

After fetching the transcript, format it based on what the user asks for:

- **Chapters**: Group by topic shifts, output timestamped chapter list
- **Summary**: Concise 5-10 sentence overview of the entire video
- **Chapter summaries**: Chapters with a short paragraph summary for each
- **Thread**: Twitter/X thread format — numbered posts, each under 280 chars
- **Blog post**: Full article with title, sections, and key takeaways
- **Quotes**: Notable quotes with timestamps

### Example — Chapters Output

```
00:00 Introduction — host opens with the problem statement
03:45 Background — prior work and why existing solutions fall short
12:20 Core method — walkthrough of the proposed approach
24:10 Results — benchmark comparisons and key takeaways
31:55 Q&A — audience questions on scalability and next steps
```

## Workflow

1. **Fetch** the transcript using the helper script with `--text-only --timestamps`.
2. **Validate**: confirm the output is non-empty and in the expected language. If empty, retry without `--language` to get any available transcript. If still empty, tell the user the video likely has transcripts disabled.
3. **Chunk if needed**: if the transcript exceeds ~50K characters, split into overlapping chunks (~40K with 2K overlap) and summarize each chunk before merging.
4. **Transform** into the requested output format. If the user did not specify a format, default to a summary.
5. **Verify**: re-read the transformed output to check for coherence, correct timestamps, and completeness before presenting.

## RSS Feed Monitoring (Cron Mode)

Use when the user wants to watch one or more YouTube channels and get notified of new videos automatically.

### Channel ID Discovery

YouTube RSS feeds require a channel ID (not a handle). To resolve `@handle` → channel ID:

```bash
# Works via proxy; grep for channel_id= in the page HTML
curl -sL --proxy socks5h://127.0.0.1:2080 "https://www.youtube.com/@HANDLE" \
  | grep -o 'channel_id=[A-Za-z0-9_-]*' | head -1
```

RSS feed URL once you have the ID:
```
https://www.youtube.com/feeds/videos.xml?channel_id=UC...
```

### Monitoring Script

`~/.hermes/scripts/yt_check_new.py` — checks configured channels against a state file (`~/.hermes/yt_watched.json`), outputs **only new video JSON** to stdout. Safe to run repeatedly; already-seen videos are skipped.

See `scripts/yt_check_new.py` in this skill for the canonical template.

### Cron Job Setup

```python
cronjob(
    action="create",
    name="YouTube博主新视频摘要",
    schedule="0 9 * * *",          # daily 09:00 UTC
    script="yt_check_new.py",       # relative to ~/.hermes/scripts/
    skills=["youtube-content"],
    enabled_toolsets=["terminal", "web"],
    prompt="""..."""                 # see references/rss-cron-prompt.md
)
```

**Pitfalls:**
- `script` path must be **relative** (`yt_check_new.py`), not absolute — the API rejects absolute paths.
- Always test the script standalone (`python3 ~/.hermes/scripts/yt_check_new.py`) before creating the cron job.
- First run returns all recent videos (up to 5 per channel) as "new" because the state file is empty. This is expected — subsequent runs only return genuinely new content.
- YouTube RSS returns the 15 most recent videos; the script keeps a rolling 20-ID seen-set per channel to avoid re-notifying after RSS rotation.
- All YouTube requests must go via proxy. Current observed proxy for this setup: `socks5h://127.0.0.1:2080`. Older notes may mention `45.38.111.11:5926`, `3.115.250.37:11080`, or `127.0.0.1:12000`; those are stale or unreliable here.
- Do not assume Telegram connectivity proves YouTube RSS connectivity. On 2026-05-05 the same proxy returned `HTTP/2 302` from `https://api.telegram.org` while YouTube RSS (`https://www.youtube.com/feeds/videos.xml?...`) timed out for 35s and `yt_check_new.py` failed with `subprocess.TimeoutExpired`. Verify YouTube RSS directly with curl before claiming the monitor works.

### Known Channel IDs (user's subscriptions)

See `references/watched-channels.md` for the current list.

## Error Handling

- **Transcript disabled**: tell the user; suggest they check if subtitles are available on the video page.
- **Private/unavailable video**: relay the error and ask the user to verify the URL.
- **No matching language**: retry without `--language` to fetch any available transcript, then note the actual language to the user.
- **Dependency missing**: run `pip install youtube-transcript-api` and retry.
