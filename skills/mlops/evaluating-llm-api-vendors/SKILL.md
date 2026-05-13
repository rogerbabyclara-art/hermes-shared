---
name: evaluating-llm-api-vendors
description: Systematically benchmark a third-party OpenAI-compatible LLM API endpoint (Volcano Ark / 火山方舟, Aliyun DashScope, Moonshot/Kimi, DeepSeek, OpenRouter, Azure AI Foundry, DIT.AI proxies, self-hosted vLLM/SGLang) BEFORE wiring it into a production bot/agent. Captures whether the key/model/route works at all, real first-token latency (TTFT) under streaming vs total latency under non-streaming, reasoning-mode overhead, cold-start vs warm patterns, and produces a one-page verdict on "is this fit for a TG/Discord chat bot vs background batch task". Use when a user pastes a curl command + API key and asks "能不能给 bot 用 / can I use this for my bot", when an existing bot feels slow and you suspect the vendor not the framework, or when picking between two candidate vendors.
---

# Evaluating LLM API vendors

## When to use this skill

Use when:
- User pastes a curl command + a fresh API key and asks "测下 / 能不能用 / 给 bot 用". The naive answer (run the curl, get HTTP 200, say "可以用") is wrong — non-streaming HTTP 200 doesn't tell you if first-token latency is 1s or 18s, and a chat bot dies at 5s+ TTFT.
- An existing bot's reply latency is bad and you want to isolate whether it's the vendor or your framework.
- Picking between vendors (e.g. Volcano Ark `doubao-seed-2-0-lite` vs `doubao-1-5-pro` vs DeepSeek-V3 vs Kimi) — need apples-to-apples numbers.
- Evaluating a proxy/aggregator (OpenRouter, DIT.AI, NEWAPI-style fork) sitting in front of an upstream model — the proxy adds its own latency you have to measure.

Do NOT use for:
- Local model inference (llama.cpp, ollama) — different toolchain, see `gguf-quantization` / `llama-cpp` skills.
- Quality eval (does the model give correct answers) — this skill measures *plumbing*, not quality. For quality use a domain-specific eval set.

## What to measure (and why)

| Metric | Why it matters | Target for chat bot | Target for batch task |
|---|---|---|---|
| HTTP status + token in/out | Key works, model id correct, response parses | 200 | 200 |
| **TTFT (streaming)** | "How long after user hits enter before the FIRST character appears in TG" | ≤2s good / ≤5s tolerable / >5s painful | irrelevant |
| Total time (non-streaming) | What batch jobs see — "how long until I have the full string" | irrelevant | ≤30s |
| Tokens/sec after first token | Whether the reply *streams smoothly* once it starts | ≥20 tok/s | irrelevant |
| `reasoning_tokens` / thinking tokens | Hidden overhead — model may be "thinking" 10s before any visible output | 0 (disable thinking for chat) | OK to keep |
| Cold-start vs warm pattern | First request often 2-3x slower than subsequent — affects first user after deploy | flat = ideal | accept slow first |
| Error rate / 5xx / 429 over 3-10 calls | Vendor stability under trivial load | 0/N | 0/N |

**Why streaming is non-negotiable for chat bots**: non-streaming TTFT === total time. Even a "fast" 4s model feels broken in chat because the user stares at "typing..." for 4 full seconds. With streaming, TTFT 1-2s + steady tok/s = words appearing live = perceived as fast even if total is 6s.

## The benchmark playbook

Five tests, in order. Stop at the first failure — no point measuring TTFT on a vendor whose key doesn't work.

### Test 1 — sanity: HTTP 200 + valid JSON

```bash
# Use --data-binary @file.json, NOT -d '...with chinese...'
# On Windows git-bash, -d '中文' encodes as GBK and the server returns
# InvalidParameter.NonUTF8Body — see scripts/probe.sh for the canonical recipe.
curl -sS -w "\n---HTTP %{http_code}---\n" $BASE_URL/chat/completions \
  -H "Content-Type: application/json; charset=utf-8" \
  -H "Authorization: Bearer $API_KEY" \
  --data-binary @body.json
```

Pass = HTTP 200 + parseable JSON with `choices[0].message.content`. Fail modes:
- `401` → key wrong / not provisioned
- `404` model → model id wrong (vendors disagree on naming, copy-paste from their dashboard)
- `400 InvalidParameter.NonUTF8Body` → git-bash + Chinese in `-d ''`, switch to `--data-binary @file.json`
- `429` → rate limited, wait and retry; if persistent the account isn't real-money provisioned
- `500/502/503/504` → vendor problem; note it, retry once, if still failing the vendor's broken right now

### Test 2 — non-streaming total latency × 3

Run the same request 3 times back-to-back. **Three is the minimum** — single number tells you nothing about variance, two doesn't reveal the cold-warm pattern. Look for:
- All 3 similar → stable vendor
- First much slower than 2,3 → cold-start (often connection pool init or model wake-up)
- Increasing → vendor is loading / scaling up / queuing
- Wildly variable → vendor is overloaded, don't trust

### Test 3 — check for hidden `reasoning_tokens`

```json
{"usage": {"completion_tokens": 370, "reasoning_tokens": 292}}
```

If `reasoning_tokens > 0` AND the user wants a chat bot, disable it. Vendor-specific:
- Volcano Ark / 火山方舟 doubao-seed-*: `"thinking": {"type": "disabled"}` in request body
- DeepSeek-R1: use `deepseek-chat` model id (V3 path), not `deepseek-reasoner`
- OpenAI o1: cannot disable — pick a different model for chat
- Kimi k2/k2.6: `"enable_thinking": false`
- Qwen QwQ: `"enable_thinking": false`

Re-run Test 2 after disabling. If total time drops 40-70%, confirmed thinking was the bottleneck.

### Test 4 — streaming TTFT × 3

This is the test that decides chat-bot fitness. Use `scripts/stream_probe.py` (in this skill) — it measures **time to first content delta**, not time to first SSE byte (which is misleading because vendors send `: ping` keepalive bytes before any real content).

Three runs, record:
- TTFT each run
- Total time each run
- Number of content chunks (more chunks = smoother streaming)
- Compute tok/s = `completion_tokens / (total_time - ttft)`

Verdict matrix:

| TTFT (median of 3) | Chat bot fitness | Notes |
|---|---|---|
| <1.5s | ✅ Production-ready | Premium tier (OpenAI gpt-4o-mini, Anthropic haiku, DeepSeek-V3 official, Kimi k2.5-fast) |
| 1.5-3s | ✅ Acceptable | Most healthy vendors here |
| 3-5s | ⚠ Marginal | User feels lag; OK if reply is long (lag hidden by streaming) |
| 5-10s | ❌ Not for chat | Background tasks only (summary, classification) |
| >10s | ❌ Not for anything realtime | Vendor is overloaded / model in low-priority queue / wrong model class |

### Test 5 — error rate over 10 calls

Only if Tests 1-4 pass. Loop 10 streaming requests, count non-200 / parse failures / connection drops. >1/10 = vendor unreliable. Note time-of-day — vendors have peak hours.

## Common findings & gotchas

### Volcano Ark / 火山方舟 doubao-* family

- **`doubao-seed-2-0-lite-260428` defaults to thinking ON** — `reasoning_tokens` usually 200-400 even for "hello world". Total latency 10-18s typical. Disable with `"thinking": {"type": "disabled"}` → drops to 5-12s, still slow because the lite tier is shared/queued.
- **`doubao-1-5-pro-32k-*` runs on higher-priority queue** — same key works, TTFT 1-3s. Use this for chat.
- **`doubao-1-5-lite-32k-character-*`** — character-tuned, chat-optimized. TTFT 1-2s, good price/perf for chat bots.
- All accept `"thinking": {"type": "disabled"}` whether the model supports thinking or not (no-op on non-thinking models, no error).
- Base URL: `https://ark.cn-beijing.volces.com/api/v3` — strictly CN-Beijing, expect 100-300ms RTT from CN, 200-500ms from JP/SG, much worse from US/EU.
- OpenAI-SDK compatible: `OpenAI(base_url=..., api_key="ark-...")` works directly.

### DeepSeek (official `api.deepseek.com`)

- `deepseek-chat` = V3, no thinking, TTFT 1-2s good for chat.
- `deepseek-reasoner` = R1, ALWAYS thinks 5-30s before first content token. Background only.
- Official endpoint sometimes 429s during APAC peak — have a fallback.

### Kimi (Moonshot)

- `moonshot-v1-8k/32k/128k` — non-thinking, fast.
- `kimi-k2-*` newer models — check if thinking default on.

### Aggregator / proxy vendors (OpenRouter, DIT.AI, NEWAPI forks)

- **Always add 200-2000ms over the upstream**'s native latency. The proxy fetches, sometimes transforms, sometimes caches.
- **Watch for multi-key round-robin** — same `metadata.user_id` may still rotate cache namespace if the proxy round-robins upstream API keys. Symptoms: cache hit rate 30-50% when you'd expect 100% on sticky user. (See note on DIT.AI in user memory.)
- Test the SAME prompt twice in a row, check `usage.prompt_tokens_details.cached_tokens` — if it's 0 when it should be hot, the proxy has a cache problem.

### Self-hosted vLLM / SGLang / TGI

- TTFT typically 0.3-1s on hot model, 5-30s on cold model.
- First request after deploy is ALWAYS slow (model loading from disk, KV cache warmup).
- Warm up with a fire-and-forget request at deploy time.

## How to deliver the verdict

When the user asks "测下能不能用 / can I use this", deliver:

1. **One-line verdict first**: "✅ 能用 / ❌ 不能用 / ⚠ 只能做后台任务"
2. **Table of measurements** — HTTP, TTFT range, total range, reasoning tokens, error rate
3. **Specific advice with vendor parameter names** — not "disable thinking" but `"thinking": {"type": "disabled"}` exactly
4. **Recommendation: this model for chat, OR switch to that model on the same key** — vendors usually have 3-5 SKUs and the user just picked the wrong one
5. **DO NOT auto-rewrite the user's code** unless they explicitly asked. Many users want to choose between vendors first.

## Pitfalls

1. **Reporting non-streaming numbers and calling it good** — Non-streaming 8s == user staring at "typing..." for 8s. Always measure streaming TTFT for chat use cases. The vendor's marketing page quotes non-streaming "average latency" precisely because it hides this.

2. **Single-shot benchmark** — One run reveals nothing. 3 minimum, 10 for stability. The first-call cold-start is real and measurable; don't quote a 1-call number.

3. **git-bash + curl + `-d '中文 prompt'` on Windows** → `400 InvalidParameter.NonUTF8Body`. Symptom: vendor rejects with encoding error, but the same body sent via Python `requests` works. Cause: git-bash's MSYS shell interprets the `'...'` arg in GBK (Windows ANSI codepage on CN systems), curl forwards the GBK bytes. Vendor parses as latin-1 / utf-8 strict and rejects. **Fix: always use `--data-binary @file.json` for any body containing non-ASCII**. Write the JSON to a file with `write_file` (which is UTF-8), then `--data-binary @path`. See `scripts/probe.sh`.

4. **Confusing TTFT with time-to-first-SSE-byte** — Vendors send `: ping` SSE keepalive bytes before any content. A naive timer that records "first byte received" undercounts TTFT. Wait for the first chunk with `choices[0].delta.content` non-empty. `scripts/stream_probe.py` does this correctly.

5. **Not disabling thinking before deciding "model too slow"** — User concludes "doubao 太慢" and switches vendor when the actual fix was a one-line `"thinking": {"type": "disabled"}` (or equivalent for that vendor). **Always check `usage.completion_tokens_details.reasoning_tokens` in Test 1's response**. Non-zero = there's thinking to disable.

6. **Mixing `Content-Type` capitalization with strict CDN/WAF** — Some vendors' edges (especially Aliyun-fronted) reject `content-type: application/json` (lowercase) but accept `Content-Type: application/json`. RFC says case-insensitive, real world doesn't. Always pass `Content-Type` capitalized.

7. **Quoting `Authorization: Bearer "${KEY}"`** — Inside double quotes the variable expands but the literal `"` chars don't end up in the header; that's correct. But if you do `Authorization: Bearer \"${KEY}\"` (escaped quotes), curl sends `Bearer "ark-..."` with literal quotes and the vendor rejects with `401 InvalidAuthHeader`. Don't escape quotes around bearer tokens.

8. **Treating proxy/aggregator latency as the upstream model's latency** — If you measure `DIT.AI → Claude` and get TTFT 4s, that's the proxy adding 2-3s on top of Claude's native ~1s. Don't tell the user "Claude is slow"; tell them "this proxy adds latency, native Claude would be faster".

9. **Forgetting the API key is sensitive** — never paste the user's key into a skill's reference file, README, or commit. Use placeholders. The TTFT numbers from a session are useful; the key isn't.

10. **Skipping the streaming test because the user asked "just check if it works"** — A non-streaming HTTP 200 answer is a half-answer for any user who's going to wire it into a chat interface. Volunteer the streaming test even if not asked; takes 30 seconds, prevents a "bot feels slow" follow-up next week.

## Files

- `scripts/probe.sh` — canonical curl probe (handles git-bash UTF-8 trap)
- `scripts/stream_probe.py` — streaming TTFT measurement, 3 runs, correctly waits for first content delta (not first SSE byte)
