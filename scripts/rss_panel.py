#!/usr/bin/env python3
"""
RSS 监控配置面板 - Flask Web UI
端口: 8765
"""
import json
import subprocess
import os
from pathlib import Path
from flask import Flask, request, jsonify, render_template_string

CONFIG = Path.home() / ".hermes/rss_monitor_config.json"
CRON_DB = Path.home() / ".hermes/scheduler.db"

app = Flask(__name__)

def load_config():
    with open(CONFIG, encoding="utf-8") as f:
        return json.load(f)

def save_config(cfg):
    with open(CONFIG, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)

def update_cron_schedule(minutes: int):
    """更新 hermes cron job 的 schedule"""
    import sqlite3
    JOB_ID = "0748b33b5633"
    schedule = f"*/{minutes} * * * *"
    try:
        conn = sqlite3.connect(str(CRON_DB))
        conn.execute(
            "UPDATE jobs SET schedule=? WHERE id LIKE ?",
            (schedule, f"{JOB_ID}%")
        )
        conn.commit()
        conn.close()
        return True, schedule
    except Exception as e:
        return False, str(e)

HTML = """<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>RSS 监控面板</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    background: #0d1117;
    color: #e6edf3;
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    min-height: 100vh;
    padding: 32px 24px;
  }
  h1 {
    font-size: 22px;
    font-weight: 600;
    margin-bottom: 28px;
    color: #f0f6fc;
    display: flex;
    align-items: center;
    gap: 10px;
  }
  h1 span { font-size: 20px; }
  .section {
    background: #161b22;
    border: 1px solid #30363d;
    border-radius: 10px;
    padding: 20px;
    margin-bottom: 20px;
  }
  .section-title {
    font-size: 13px;
    font-weight: 600;
    color: #8b949e;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    margin-bottom: 16px;
  }
  .tag-list {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    margin-bottom: 14px;
  }
  .tag {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    background: #21262d;
    border: 1px solid #30363d;
    border-radius: 20px;
    padding: 4px 12px;
    font-size: 13px;
    color: #e6edf3;
  }
  .tag .del {
    cursor: pointer;
    color: #6e7681;
    font-size: 15px;
    line-height: 1;
    padding: 0 2px;
    transition: color 0.15s;
  }
  .tag .del:hover { color: #f85149; }
  .input-row {
    display: flex;
    gap: 8px;
  }
  input[type=text], input[type=number] {
    background: #0d1117;
    border: 1px solid #30363d;
    border-radius: 6px;
    color: #e6edf3;
    padding: 7px 12px;
    font-size: 14px;
    outline: none;
    transition: border-color 0.15s;
  }
  input[type=text]:focus, input[type=number]:focus {
    border-color: #58a6ff;
  }
  input[type=text] { flex: 1; }
  input[type=number] { width: 90px; }
  button {
    background: #238636;
    border: 1px solid #2ea043;
    border-radius: 6px;
    color: #fff;
    cursor: pointer;
    font-size: 13px;
    padding: 7px 16px;
    transition: background 0.15s;
    white-space: nowrap;
  }
  button:hover { background: #2ea043; }
  button.danger {
    background: transparent;
    border-color: #f85149;
    color: #f85149;
  }
  button.danger:hover { background: #f8514920; }
  button.secondary {
    background: #21262d;
    border-color: #30363d;
    color: #e6edf3;
  }
  button.secondary:hover { background: #30363d; }
  .source-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 10px 0;
    border-bottom: 1px solid #21262d;
  }
  .source-row:last-child { border-bottom: none; }
  .source-name { font-size: 14px; font-weight: 500; }
  .source-url { font-size: 12px; color: #8b949e; margin-top: 2px; word-break: break-all; }
  .interval-row {
    display: flex;
    align-items: center;
    gap: 12px;
  }
  .interval-label { font-size: 14px; color: #8b949e; }
  .toast {
    position: fixed;
    bottom: 24px;
    right: 24px;
    background: #238636;
    color: #fff;
    border-radius: 8px;
    padding: 10px 18px;
    font-size: 13px;
    opacity: 0;
    transition: opacity 0.3s;
    pointer-events: none;
    z-index: 999;
  }
  .toast.show { opacity: 1; }
  .toast.error { background: #da3633; }
  .add-source-form {
    margin-top: 14px;
    display: flex;
    flex-direction: column;
    gap: 8px;
  }
  .add-source-form .input-row { flex-wrap: wrap; }
  hr { border: none; border-top: 1px solid #21262d; margin: 16px 0; }
</style>
</head>
<body>
<h1><span>📡</span> RSS 监控面板</h1>

<!-- 间隔 -->
<div class="section">
  <div class="section-title">推送间隔</div>
  <div class="interval-row">
    <span class="interval-label">每</span>
    <input type="number" id="interval" min="5" max="1440" value="{{ config.interval_minutes }}">
    <span class="interval-label">分钟扫描一次</span>
    <button onclick="saveInterval()">保存</button>
  </div>
</div>

<!-- 关键词 -->
<div class="section">
  <div class="section-title">关键词过滤</div>
  <div class="tag-list" id="keywords">
    {% for kw in config.keywords %}
    <span class="tag">{{ kw }}<span class="del" onclick="removeKeyword('{{ kw }}')">×</span></span>
    {% endfor %}
  </div>
  <div class="input-row">
    <input type="text" id="newKeyword" placeholder="新关键词，回车添加" onkeydown="if(event.key==='Enter')addKeyword()">
    <button onclick="addKeyword()">添加</button>
  </div>
</div>

<!-- 论坛来源 -->
<div class="section">
  <div class="section-title">论坛来源</div>
  <div id="sources">
    {% for src in config.sources %}
    <div class="source-row" id="src-{{ loop.index0 }}">
      <div>
        <div class="source-name">{{ src.name }}</div>
        <div class="source-url">{{ src.feed_url or src.url }}</div>
      </div>
      <button class="danger" onclick="removeSource('{{ src.name }}')">删除</button>
    </div>
    {% endfor %}
  </div>
  <hr>
  <div class="add-source-form">
    <div class="input-row">
      <input type="text" id="srcName" placeholder="名称（如 r/OpenAI）" style="flex:1">
      <input type="text" id="srcUrl" placeholder="RSS URL 或 页面 URL" style="flex:2">
    </div>
    <div>
      <button onclick="addSource()">添加论坛</button>
    </div>
  </div>
</div>

<div class="toast" id="toast"></div>

<script>
function showToast(msg, error=false) {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.className = 'toast show' + (error ? ' error' : '');
  setTimeout(() => t.className = 'toast', 2500);
}

async function api(path, body) {
  const r = await fetch(path, {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(body)
  });
  return r.json();
}

async function saveInterval() {
  const v = parseInt(document.getElementById('interval').value);
  if (!v || v < 5) return showToast('最小 5 分钟', true);
  const r = await api('/api/interval', {minutes: v});
  if (r.ok) showToast('已保存，间隔 ' + v + ' 分钟');
  else showToast(r.error || '保存失败', true);
}

async function addKeyword() {
  const inp = document.getElementById('newKeyword');
  const kw = inp.value.trim();
  if (!kw) return;
  const r = await api('/api/keywords/add', {keyword: kw});
  if (r.ok) {
    inp.value = '';
    location.reload();
  } else showToast(r.error || '添加失败', true);
}

async function removeKeyword(kw) {
  const r = await api('/api/keywords/remove', {keyword: kw});
  if (r.ok) location.reload();
  else showToast(r.error || '删除失败', true);
}

async function addSource() {
  const name = document.getElementById('srcName').value.trim();
  const url = document.getElementById('srcUrl').value.trim();
  if (!name || !url) return showToast('名称和 URL 不能为空', true);
  const r = await api('/api/sources/add', {name, url});
  if (r.ok) location.reload();
  else showToast(r.error || '添加失败', true);
}

async function removeSource(name) {
  if (!confirm('确定删除 ' + name + '？')) return;
  const r = await api('/api/sources/remove', {name});
  if (r.ok) location.reload();
  else showToast(r.error || '删除失败', true);
}
</script>
</body>
</html>"""

@app.route("/")
def index():
    cfg = load_config()
    return render_template_string(HTML, config=cfg)

@app.route("/api/interval", methods=["POST"])
def set_interval():
    data = request.json
    minutes = int(data.get("minutes", 15))
    if minutes < 5:
        return jsonify({"ok": False, "error": "最小 5 分钟"})
    cfg = load_config()
    cfg["interval_minutes"] = minutes
    save_config(cfg)
    ok, info = update_cron_schedule(minutes)
    return jsonify({"ok": True, "schedule": info})

@app.route("/api/keywords/add", methods=["POST"])
def add_keyword():
    kw = request.json.get("keyword", "").strip()
    if not kw:
        return jsonify({"ok": False, "error": "关键词不能为空"})
    cfg = load_config()
    if kw not in cfg["keywords"]:
        cfg["keywords"].append(kw)
        save_config(cfg)
    return jsonify({"ok": True})

@app.route("/api/keywords/remove", methods=["POST"])
def remove_keyword():
    kw = request.json.get("keyword", "").strip()
    cfg = load_config()
    cfg["keywords"] = [k for k in cfg["keywords"] if k != kw]
    save_config(cfg)
    return jsonify({"ok": True})

@app.route("/api/sources/add", methods=["POST"])
def add_source():
    name = request.json.get("name", "").strip()
    url = request.json.get("url", "").strip()
    if not name or not url:
        return jsonify({"ok": False, "error": "名称和 URL 不能为空"})
    # 自动推断 feed_url
    feed_url = url
    if "reddit.com/r/" in url and not url.endswith(".rss"):
        sub = url.rstrip("/").split("/r/")[-1].split("/")[0]
        feed_url = f"https://www.reddit.com/r/{sub}/.rss?limit=25"
    cfg = load_config()
    if any(s["name"] == name for s in cfg["sources"]):
        return jsonify({"ok": False, "error": f"'{name}' 已存在"})
    cfg["sources"].append({"name": name, "url": url, "feed_url": feed_url})
    save_config(cfg)
    return jsonify({"ok": True})

@app.route("/api/sources/remove", methods=["POST"])
def remove_source():
    name = request.json.get("name", "").strip()
    cfg = load_config()
    cfg["sources"] = [s for s in cfg["sources"] if s["name"] != name]
    save_config(cfg)
    return jsonify({"ok": True})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8765, debug=False)
