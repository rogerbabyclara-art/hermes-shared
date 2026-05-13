#!/usr/bin/env python3
"""
扫描 RSS 新文章，关键词过滤后输出 JSON 给 cron agent。
Deploy to: ~/.hermes/scripts/rss_check_new.py
"""
import json, os, subprocess, sqlite3
from pathlib import Path

BW = "/home/dev/.local/bin/blogwatcher-cli"
DB = Path.home() / ".blogwatcher-cli/blogwatcher-cli.db"
PROXY = "socks5h://oapqwxqn:n1l45h99bz8q@45.38.111.11:5926"
KEYWORDS = ["公益", "中转", "api", "4.7", "便宜", "azure",
            "claude", "gpt", "hermes", "免费", "节点", "机场", "翻墙", "vps", "VPS"]

def scan():
    env = os.environ.copy()
    env["HTTPS_PROXY"] = PROXY
    env["HTTP_PROXY"] = PROXY
    subprocess.run([BW, "scan"], env=env, capture_output=True, timeout=60)

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

def keyword_match(article):
    text = (article.get("title", "") + " " + article.get("url", "")).lower()
    return any(kw.lower() in text for kw in KEYWORDS)

def main():
    scan()
    articles = get_unread()
    matched = [a for a in articles if keyword_match(a)]
    mark_all_read()

    output = []
    for a in matched[:30]:  # 最多推30条
        output.append({
            "title": a.get("title", ""),
            "url": a.get("url", ""),
            "blog": a.get("blog_name", ""),
            "published": a.get("published_at", ""),
        })

    print(json.dumps(output, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
