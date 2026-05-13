#!/usr/bin/env python3
"""
?? YouTube ?? RSS??????????? state ????
?? JSON ? stdout?? cron job agent ???
"""
import json
import os
import subprocess
import sys
import xml.etree.ElementTree as ET

DEFAULT_PROXY = "socks5h://127.0.0.1:2080"
PROXY = os.environ.get("YT_PROXY") or os.environ.get("HTTPS_PROXY") or DEFAULT_PROXY
STATE_FILE = os.path.expanduser("~/.hermes/yt_watched.json")

CHANNELS = {
    "joeyblog": "UC_0Gn008Lj36lpoUSS8E_dg",
    "kejilion": "UCKqRheBWWCATRulqT1vxrww",
    "lingdujieshuo": "UCvijahEyGtvMpmMHBu4FS2w",
    "kejigongxiang": "UCQoagx4VHBw3HkAyzvKEEBA",
}


def log(msg: str) -> None:
    print(msg, file=sys.stderr)


def fetch_rss(channel_id: str) -> str:
    url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
    cmd = [
        "curl", "-fsSL",
        "--connect-timeout", "8",
        "--max-time", "20",
        "--proxy", PROXY,
        url,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=25, check=True)
        return result.stdout
    except subprocess.TimeoutExpired:
        log(f"[yt_check_new] RSS timeout: channel_id={channel_id} proxy={PROXY}")
    except subprocess.CalledProcessError as exc:
        stderr = (exc.stderr or "").strip()
        log(f"[yt_check_new] RSS fetch failed: channel_id={channel_id} rc={exc.returncode} err={stderr[:200]}")
    return ""


def parse_videos(xml_str: str, limit: int = 5):
    videos = []
    try:
        root = ET.fromstring(xml_str)
        ns = {
            "atom": "http://www.w3.org/2005/Atom",
            "yt": "http://www.youtube.com/xml/schemas/2015",
        }
        for entry in root.findall("atom:entry", ns)[:limit]:
            vid_id = entry.find("yt:videoId", ns)
            title = entry.find("atom:title", ns)
            published = entry.find("atom:published", ns)
            if vid_id is not None and title is not None and vid_id.text:
                videos.append({
                    "id": vid_id.text,
                    "title": title.text or "",
                    "url": f"https://www.youtube.com/watch?v={vid_id.text}",
                    "published": published.text if published is not None else "",
                })
    except Exception as exc:
        log(f"[yt_check_new] XML parse failed: {exc}")
    return videos


def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_state(state):
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def main():
    state = load_state()
    new_videos = []

    for name, cid in CHANNELS.items():
        xml_str = fetch_rss(cid)
        if not xml_str.strip():
            continue
        videos = parse_videos(xml_str)
        seen = set(state.get(name, []))
        for v in videos:
            if v["id"] not in seen:
                item = dict(v)
                item["channel"] = name
                new_videos.append(item)
        all_ids = [v["id"] for v in videos]
        state[name] = list(dict.fromkeys(list(seen) + all_ids))[-20:]

    save_state(state)
    print(json.dumps(new_videos, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
