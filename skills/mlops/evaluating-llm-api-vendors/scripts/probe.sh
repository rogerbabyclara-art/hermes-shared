#!/usr/bin/env bash
# Canonical curl probe for OpenAI-compatible LLM endpoints.
# Handles the git-bash + Windows UTF-8 trap: -d '中文' is GBK-encoded by the
# MSYS shell on Windows and the vendor rejects with InvalidParameter.NonUTF8Body.
# Always write the JSON to a file first (which is UTF-8) and use --data-binary @file.
#
# Usage:
#   BASE_URL=https://ark.cn-beijing.volces.com/api/v3 \
#   API_KEY=sk-or-ark-or-whatever \
#   MODEL=doubao-1-5-pro-32k-250115 \
#   bash probe.sh
#
# Optional:
#   PROMPT='你的中文测试句' (default below)
#   DISABLE_THINKING=1     (adds "thinking": {"type": "disabled"} for Volcano Ark / etc)
#   RUNS=3                 (default 3)

set -u
BASE_URL="${BASE_URL:?set BASE_URL e.g. https://api.deepseek.com/v1}"
API_KEY="${API_KEY:?set API_KEY}"
MODEL="${MODEL:?set MODEL e.g. deepseek-chat}"
PROMPT="${PROMPT:-你好，测试一下API连接是否正常}"
RUNS="${RUNS:-3}"
DISABLE_THINKING="${DISABLE_THINKING:-0}"

TMPDIR="${TMPDIR:-/tmp}"
BODY="$TMPDIR/llm_probe_body_$$.json"
RESP="$TMPDIR/llm_probe_resp_$$.json"

# Build body with python (UTF-8 safe regardless of shell encoding).
# Falls back to here-doc cat if python is unavailable.
if command -v python >/dev/null 2>&1; then
  python - "$BODY" "$MODEL" "$PROMPT" "$DISABLE_THINKING" <<'PY'
import json, sys
out_path, model, prompt, disable_think = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
body = {
    "model": model,
    "messages": [{"role": "user", "content": prompt}],
    "temperature": 0.7,
}
if disable_think == "1":
    body["thinking"] = {"type": "disabled"}     # Volcano Ark
    body["enable_thinking"] = False              # Kimi / Qwen
with open(out_path, "w", encoding="utf-8") as f:
    json.dump(body, f, ensure_ascii=False)
PY
else
  # ASCII-safe fallback. Loses Chinese prompt if PROMPT had Chinese.
  cat > "$BODY" <<JSON
{"model":"$MODEL","messages":[{"role":"user","content":"$PROMPT"}],"temperature":0.7}
JSON
fi

echo "=== probe $BASE_URL  model=$MODEL  runs=$RUNS  disable_thinking=$DISABLE_THINKING ==="
for i in $(seq 1 "$RUNS"); do
  echo "--- run $i ---"
  curl -sS -w "HTTP %{http_code} | time_total %{time_total}s\n" \
       "$BASE_URL/chat/completions" \
    -H "Content-Type: application/json; charset=utf-8" \
    -H "Authorization: Bearer $API_KEY" \
    --data-binary @"$BODY" \
    -o "$RESP"
  if command -v python >/dev/null 2>&1; then
    python - "$RESP" <<'PY'
import json, sys
try:
    with open(sys.argv[1], encoding="utf-8") as f:
        d = json.load(f)
except Exception as e:
    print(f"  (parse failed: {e})")
    sys.exit(0)
u = d.get("usage", {})
ct = u.get("completion_tokens")
rt = (u.get("completion_tokens_details") or {}).get("reasoning_tokens", 0)
ch = (d.get("choices") or [{}])[0]
msg = (ch.get("message") or {}).get("content", "")
print(f"  completion_tokens={ct}  reasoning_tokens={rt}  reply={msg[:60].strip()!r}")
PY
  fi
done

rm -f "$BODY" "$RESP"
