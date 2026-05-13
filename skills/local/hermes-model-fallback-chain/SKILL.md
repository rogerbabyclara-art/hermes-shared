---
name: hermes-model-fallback-chain
description: Configure Hermes Agent's primary model + fallback_providers chain in config.yaml for tiered routing (cheap default → expensive backup → alt-vendor backup), and verify each tier with direct curl probes against the configured base_url. Use when the user asks to set up cost-tiered routing, add a fallback model, or test that all tiers in the chain actually work end-to-end.
version: 1.0.0
---

# Hermes Model Fallback Chain Setup + Verification

Use this when the user wants tiered model routing on Hermes (e.g. cheap default, expensive for coding, plus alt-vendor failover) and wants you to confirm every tier actually responds before declaring it done.

## When to trigger
- "Use sonnet by default, opus for coding"
- "Add grok as a fallback if claude is down"
- "Test all my models in the routing chain"
- Any request to edit `model` + `fallback_providers` together

## Steps

### 1. Discover what models the upstream actually serves
Don't trust the user's spelling — middleman gateways (NEWAPI, one-api forks, oneapi) often have their own model IDs. Query `/v1/models`:

```bash
curl -s "$BASE_URL/v1/models" -H "Authorization: Bearer $KEY" \
  | python3 -c "import json,sys;d=json.load(sys.stdin);[print(m['id']) for m in d.get('data',[])]"
```

Filter for the family the user mentioned (claude, grok, gpt, etc.). Map fuzzy user names to real IDs:
- "sonnet 4.6" / "sonic 4.6" → `claude-sonnet-4-6`
- "opus 4.7" → `claude-opus-4-7`
- "grok 4.2" → likely `grok-4-20-reasoning` (4.20, not 4.2)
- "grok 4.1" → `grok-4-1-fast-reasoning`

### 2. Edit `~/.hermes/config.yaml`
Structure:

```yaml
model:
  provider: custom            # or anthropic, openai, etc.
  default: claude-sonnet-4-6  # cheap daily driver
  base_url: https://your-gateway/
  api_key: sk-...
  api_mode: anthropic_messages  # or openai_chat
  timeout: 30                 # per-attempt timeout

fallback_providers:
  - provider: custom
    base_url: https://your-gateway/
    api_key: sk-...
    api_mode: anthropic_messages
    model: claude-opus-4-7
    timeout: 30
  - provider: custom
    base_url: https://your-gateway/
    api_key: sk-...
    api_mode: openai_chat        # grok lives on /v1/chat/completions
    model: grok-4-1-fast-reasoning
    timeout: 30
  - provider: custom
    base_url: https://your-gateway/
    api_key: sk-...
    api_mode: openai_chat
    model: grok-4-20-reasoning
    timeout: 30
```

Pitfalls:
- **`api_mode` matters per-model**. Claude family → `anthropic_messages`. Grok/GPT/DeepSeek → `openai_chat`. Mixing them silently 400s.
- **api_key must be the full literal** in the file. If you're using `read_file` partial views, the key may be displayed truncated like `sk-sls...VOpn` — re-grep the original to recover the full key before editing, or you'll write the placeholder into the file and break everything.
- **Order in `fallback_providers` is the failover order.** Cheaper/faster models first.
- **Hermes reloads config per message** (no restart needed for config.yaml model changes), but gateway services should be `/restart`-ed to be safe.

### 3. Verify every tier with direct curl probes
Don't trust "config looks right" �� actually hit each model. Use one prompt, capture HTTP code + latency + reply:

```python
# Per model, dispatch the right endpoint shape
# Anthropic family:
curl -sS -m 30 -w "\n__HTTP__%{http_code}__TIME__%{time_total}" $BASE/v1/messages \
  -H "x-api-key: $KEY" -H "anthropic-version: 2023-06-01" -H "content-type: application/json" \
  -d '{"model":"<id>","max_tokens":40,"messages":[{"role":"user","content":"用一句中文回答：你是谁？只说模型名"}]}'

# OpenAI-compatible (grok, gpt, deepseek):
curl -sS -m 30 -w "\n__HTTP__%{http_code}__TIME__%{time_total}" $BASE/v1/chat/completions \
  -H "Authorization: Bearer $KEY" -H "content-type: application/json" \
  -d '{"model":"<id>","max_tokens":40,"messages":[{"role":"user","content":"用一句中文回答：你是谁？只说模型名"}]}'
```

Print a table: model | http | seconds | self-reported identity.

### 4. Detect upstream remapping (important)
Middleman gateways often **remap model names to cheaper backends without telling you**. The "ask the model who it is" probe in step 3 is exactly to catch this:
- If `claude-sonnet-4-6` replies "我是 DeepSeek-V3" → the gateway is silently routing to DeepSeek.
- If `grok-x` replies "I'm Claude" → same problem reversed.

Surface this to the user explicitly. Don't just say "all 4 models work" if one of them is lying about its identity. Self-reports aren't 100% reliable (some models hallucinate identity), but a consistent wrong answer is a strong signal.

### 5. Report
Give a compact table (HTTP / latency / self-id) and call out any remap or anomaly. Ask the user whether to accept the remapped tier or hunt for the real one in the gateway's model list.

## Diagnosing a full-chain collapse (all tiers fail simultaneously)

When ALL models in the chain fail — primary + every fallback — the most likely cause is **shared upstream failure**, not model-level issues.

### Symptoms
- `AssertionError` with empty error text on primary (connection-layer error, not HTTP 4xx/5xx)
- All fallbacks immediately return empty responses (0 tokens, no content)
- Gateway crashes with `exit-code 75 (TEMPFAIL)` and auto-restarts

### Diagnosis steps
1. Check `journalctl --user -u hermes-gateway.service -n 100 --no-pager` for the error window
2. Look for `AssertionError` with blank `📝 Error:` — this is a connection-layer failure (TCP/SSL/DNS), not API error
3. Confirm all fallbacks point to the same `base_url` — if yes, a single upstream outage kills all tiers
4. After upstream recovers, `/restart` will restore normal operation

### Key insight
If `fallback_providers` all use `provider: custom` with the same `base_url`, the fallback chain provides **zero resilience against upstream outages**. It only helps with per-model errors (rate limits, model deprecation, empty responses from a specific model).

For real resilience, at least one fallback tier should point to a **different vendor/endpoint** (e.g. direct Anthropic API, OpenRouter, or a second newapi instance).

### Do not confuse with model-switching issues
If the error IS `Could not resolve authentication method` (not AssertionError), the cause is a missing API key for a provider — usually happens when someone switches the active model to a different provider mid-session (e.g. switching to openrouter without configuring `providers.openrouter.api_key`).

## Anti-patterns
- Editing `model.default` without also confirming `model.api_mode` matches the new model family.
- Adding fallback entries without `timeout` (defaults can be too long, defeating the point of failover).
- Declaring success based on config-file lint or "no error on save" — always probe live.
- Trusting partial-view tool output of secrets; always re-grep the full key from disk.
- Building a fallback chain where all tiers share the same upstream — this is a false safety net.
