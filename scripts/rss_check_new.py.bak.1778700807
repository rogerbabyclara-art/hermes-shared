#!/usr/bin/env python3
"""
扫描 RSS 新文章，关键词过滤后输出 JSON 给 cron agent。
配置文件: ~/.hermes/rss_monitor_config.json
"""
import json, os, subprocess, sqlite3
from pathlib import Path

BW = "/home/dev/.local/bin/blogwatcher-cli"
DB = Path.home() / ".blogwatcher-cli/blogwatcher-cli.db"
CONFIG = Path.home() / ".hermes/rss_monitor_config.json"
PROXY = "socks5h://93eb832fc3:zRtz9uxkhbdVsFG7uKaXJccH@174.139.197.25:11080"


def load_config():
    with open(CONFIG, encoding="utf-8") as f:
        return json.load(f)


def get_tracked_blogs():
    """从 blogwatcher DB 拿已有的论坛名列表"""
    if not DB.exists():
        return set()
    conn = sqlite3.connect(DB)
    rows = conn.execute("SELECT name FROM blogs").fetchall()
    conn.close()
    return {r[0] for r in rows}


def sync_sources(sources):
    """把配置里的论坛同步到 blogwatcher，缺的自动 add，多的自动 remove"""
    env = os.environ.copy()
    env["HTTPS_PROXY"] = PROXY
    env["HTTP_PROXY"] = PROXY

    tracked = get_tracked_blogs()
    config_names = {s["name"] for s in sources}

    # 新增
    for src in sources:
        if src["name"] not in tracked:
            cmd = [BW, "add", src["name"], src["url"]]
            if src.get("feed_url"):
                cmd += ["--feed-url", src["feed_url"]]
            subprocess.run(cmd, env=env, capture_output=True, timeout=30)

    # 删除（配置里没有的）
    for name in tracked:
        if name not in config_names:
            subprocess.run([BW, "remove", name], env=env, capture_output=True, timeout=10)


def scan():
    env = os.environ.copy()
    env["HTTPS_PROXY"] = PROXY
    env["HTTP_PROXY"] = PROXY
    subprocess.run([BW, "scan"], env=env, capture_output=True, timeout=90)


def get_unread():
    if not DB.exists():
        return []
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    cur = conn.execute("""
        SELECT a.id, a.title, a.url, a.published_date as published_at, b.name as blog_name
        FROM articles a
        JOIN blogs b ON a.blog_id = b.id
        WHERE a.is_read = 0
        ORDER BY a.published_date DESC
        LIMIT 200
    """)
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def mark_all_read():
    if not DB.exists():
        return
    conn = sqlite3.connect(DB)
    conn.execute("UPDATE articles SET is_read = 1 WHERE is_read = 0")
    conn.commit()
    conn.close()


def matched_keywords(article, keywords):
    text = (article.get("title", "") + " " + article.get("url", "")).lower()
    return [kw for kw in keywords if kw.lower() in text]


def main():
    cfg = load_config()
    keywords = cfg.get("keywords", [])
    sources = cfg.get("sources", [])

    sync_sources(sources)
    scan()

    articles = get_unread()
    matched = []
    for a in articles:
        kws = matched_keywords(a, keywords)
        if kws:
            a["keywords"] = kws
            matched.append(a)
    mark_all_read()

    output = []
    for a in matched[:30]:
        output.append({
            "title": a.get("title", ""),
            "url": a.get("url", ""),
            "blog": a.get("blog_name", ""),
            "published": a.get("published_at", ""),
            "keywords": a.get("keywords", []),
        })

    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
