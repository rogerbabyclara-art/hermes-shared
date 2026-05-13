#!/usr/bin/env python
"""
Streaming TTFT probe for OpenAI-compatible LLM endpoints.

Measures *time to first content delta* (not time to first SSE byte — vendors
send `: ping` keepalives before content, which would skew TTFT lower than reality).

Usage:
    BASE_URL=https://ark.cn-beijing.volces.com/api/v3 \\
    API_KEY=ark-... \\
    MODEL=doubao-seed-2-0-lite-260428 \\
    python stream_probe.py

Optional env:
    PROMPT='你的中文测试句'
    DISABLE_THINKING=1   (adds "thinking": {"type": "disabled"} + "enable_thinking": false)
    RUNS=3
    TIMEOUT=60
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request


def main() -> int:
    base = os.environ.get("BASE_URL", "").rstrip("/")
    key = os.environ.get("API_KEY", "")
    model = os.environ.get("MODEL", "")
    if not (base and key and model):
        print("set BASE_URL, API_KEY, MODEL", file=sys.stderr)
        return 2

    prompt = os.environ.get("PROMPT", "你好，测试一下API连接是否正常")
    runs = int(os.environ.get("RUNS", "3"))
    timeout = int(os.environ.get("TIMEOUT", "60"))
    disable_thinking = os.environ.get("DISABLE_THINKING", "0") == "1"

    body = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.7,
        "stream": True,
    }
    if disable_thinking:
        body["thinking"] = {"type": "disabled"}  # Volcano Ark
        body["enable_thinking"] = False          # Kimi / Qwen

    payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
    url = f"{base}/chat/completions"

    print(
        f"=== stream probe {url}  model={model}  runs={runs}  "
        f"disable_thinking={disable_thinking} ==="
    )
    ttfts: list[float] = []
    totals: list[float] = []
    for run in range(1, runs + 1):
        t0 = time.time()
        first_token_ts: float | None = None
        chunks = 0
        text_parts: list[str] = []
        req = urllib.request.Request(
            url,
            data=payload,
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "Authorization": f"Bearer {key}",
                "Accept": "text/event-stream",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                for raw in resp:
                    line = raw.decode("utf-8", errors="replace").strip()
                    if not line:
                        continue
                    if line.startswith(":"):  # SSE comment / keepalive — IGNORE
                        continue
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        obj = json.loads(data)
                        delta = (obj.get("choices") or [{}])[0].get("delta", {})
                        content = delta.get("content")
                        if content:
                            if first_token_ts is None:
                                first_token_ts = time.time()
                            chunks += 1
                            text_parts.append(content)
                    except Exception:
                        pass
        except urllib.error.HTTPError as e:
            err_body = e.read()[:300].decode("utf-8", errors="replace")
            print(f"run{run}: HTTP {e.code}  {err_body}")
            continue
        except Exception as e:
            print(f"run{run}: error {type(e).__name__}: {e}")
            continue

        total = time.time() - t0
        ttft = (first_token_ts - t0) if first_token_ts else None
        reply = "".join(text_parts)
        ttft_s = f"{ttft:.2f}s" if ttft is not None else "n/a"
        print(
            f"run{run}: TTFT={ttft_s}  total={total:.2f}s  "
            f"chunks={chunks}  reply={reply[:60]!r}"
        )
        if ttft is not None:
            ttfts.append(ttft)
        totals.append(total)

    if ttfts:
        ttfts_sorted = sorted(ttfts)
        median_ttft = ttfts_sorted[len(ttfts_sorted) // 2]
        print(
            f"\nsummary  TTFT min={min(ttfts):.2f}s "
            f"median={median_ttft:.2f}s max={max(ttfts):.2f}s  "
            f"total median={sorted(totals)[len(totals)//2]:.2f}s"
        )
        if median_ttft <= 1.5:
            verdict = "✅ premium tier, production-ready for chat"
        elif median_ttft <= 3:
            verdict = "✅ acceptable for chat"
        elif median_ttft <= 5:
            verdict = "⚠ marginal — long replies tolerable, short replies feel slow"
        elif median_ttft <= 10:
            verdict = "❌ not for chat, background tasks only"
        else:
            verdict = "❌ not for anything realtime — wrong tier / overloaded"
        print(f"verdict: {verdict}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
