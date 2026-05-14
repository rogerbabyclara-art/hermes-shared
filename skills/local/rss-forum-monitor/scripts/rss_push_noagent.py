#!/usr/bin/env python3
"""
RSS 推送 cron 脚本 — no_agent 模式 (无需 LLM)

用途: 当 hermes-agent cron + LLM 出现 api_key/api_mode 解析 bug (例如
cron 上下文里 resolve_runtime_provider 返回正确但 AIAgent 内部发出
`Bearer None` + 顶层 system 字段触发 400) 时, 用纯脚本绕过 LLM。

行为:
- 扫 RSS, 关键词过滤
- 直接把格式化好的多条消息文本输出到 stdout
- Hermes cron `no_agent=True` 会把 stdout 当消息文本直接投递到 deliver target
- 空 stdout = 自动 silent (no_agent 不发空消息)

cron job 配置:
  no_agent: True
  script: rss_push_noagent.py
  prompt: ""  (no_agent 模式忽略 prompt)
  provider/model/skills: None (no_agent 不调 LLM)
  deliver: telegram:<chat_id>

配置文件: ~/.hermes/rss_monitor_config.json (keywords + sources)
代理: RSS_PROXY 环境变量 (空 = 直连, HK/海外机器一般直连即可)
"""
import json, os, subprocess, sqlite3, sys
from pathlib import Path

BW = os.environ.get("BW_BIN") or str(Path.home() / ".local/bin/blogwatcher-cli")
DB = Path.home() / ".blogwatcher-cli/blogwatcher-cli.db"
CONFIG = Path.home() / ".hermes/rss_monitor_config.json"
PROXY = os.environ.get("RSS_PROXY", "")


def load_config():
    with open(CONFIG, encoding="utf-8") as f:
        return json.load(f)


def get_tracked_blogs():
    if not DB.exists():
        return set()
    conn = sqlite3.connect(DB)
    rows = conn.execute("SELECT name FROM blogs").fetchall()
    conn.close()
    return {r[0] for r in rows}


def make_env():
    env = os.environ.copy()
    if PROXY:
        env["HTTPS_PROXY"] = PROXY
        env["HTTP_PROXY"] = PROXY
    return env


def sync_sources(sources):
    env = make_env()
    tracked = get_tracked_blogs()
    config_names = {s["name"] for s in sources}
    for src in sources:
        if src["name"] not in tracked:
            cmd = [BW, "add", src["name"], src["url"]]
            if src.get("feed_url"):
                cmd += ["--feed-url", src["feed_url"]]
            subprocess.run(cmd, env=env, capture_output=True, timeout=30)
    for name in tracked:
        if name not in config_names:
            subprocess.run([BW, "remove", name], env=env, capture_output=True, timeout=10)


def scan():
    subprocess.run([BW, "scan"], env=make_env(), capture_output=True, timeout=90)


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


def format_post(p):
    blog = p.get("blog", "")
    title = p.get("title", "")
    url = p.get("url", "")
    kws = p.get("keywords", []) or []
    kws_str = "、".join(kws) if kws else "未标记"
    published = p.get("published", "")
    return (
        f"📌 【{blog}】{title}\n"
        f"🔗 {url}\n"
        f"🏷 关键词：{kws_str}\n"
        f"🕒 时间：{published}"
    )


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
            matched.append({
                "title": a.get("title", ""),
                "url": a.get("url", ""),
                "blog": a.get("blog_name", ""),
                "published": a.get("published_at", ""),
                "keywords": kws,
            })
    mark_all_read()

    if not matched:
        # 空 stdout = no_agent 模式下 silent
        return

    # 每条帖子一段, 段间空行分隔 (TG 会自动按 4096 字符切分)
    blocks = [format_post(p) for p in matched[:30]]
    print("\n\n".join(blocks))


if __name__ == "__main__":
    main()
