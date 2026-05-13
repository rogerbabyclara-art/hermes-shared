# Azure AI Foundry: Models vs Deployments

## The Problem

User configures a `services.ai.azure.com` endpoint + API key in NEWAPI, tries to test a model, gets `DeploymentNotFound`. But the same key works fine in Azure AI Foundry Playground.

## Root Cause

Azure AI Foundry distinguishes between **models** (catalog of what's available) and **deployments** (what you've actually provisioned for API access).

| Concept | What it means | API call |
|---|---|---|
| **Models** | 309+ models listed in the catalog. This is the "menu". | `GET /openai/models?api-version=2024-10-21` → returns all |
| **Deployments** | Model instances you created that are callable via API. | `GET /openai/deployments/...` → only deployed ones |

The Playground auto-creates temporary/serverless deployments behind the scenes. Those aren't visible or callable via raw API.

## Diagnosis

```bash
# List models (this works — proves the key is valid)
curl -s -H "api-key: <KEY>" "https://<resource>.services.ai.azure.com/openai/models?api-version=2024-10-21" | python -c "import sys,json; data=json.loads(sys.stdin.read(),strict=False); print(len(data['data']),'models')"

# Try to call a model (this fails with DeploymentNotFound)
curl -s -H "api-key: <KEY>" -H "Content-Type: application/json" \
  "https://<resource>.services.ai.azure.com/openai/deployments/gpt-4o-mini/chat/completions?api-version=2024-10-21" \
  -d '{"messages":[{"role":"user","content":"hi"}],"max_tokens":10}'
# → {"error":{"code":"DeploymentNotFound","message":"The API deployment for this resource does not exist..."}}
```

If `/openai/models` returns data but `/openai/deployments/<name>/chat/completions` returns `DeploymentNotFound`, the user hasn't created deployments.

## Fix

User must go to Azure AI Foundry portal and **deploy** each model they want to use via API:
1. Go to Azure AI Foundry → Models → Find model (e.g. gpt-4o-mini)
2. Click "Deploy" → choose deployment name and configuration
3. Note the **deployment name** (this is what goes in the API path, NOT the model name)
4. Use that deployment name in NEWAPI channel configuration

## NEWAPI Configuration

In NEWAPI, when adding an Azure OpenAI channel:
- **Type**: Azure OpenAI
- **Base URL**: `https://<resource>.services.ai.azure.com` (no trailing `/openai/`)
- **Key**: the API key
- **Model mapping**: map model names to deployment names (e.g. `gpt-4o-mini` → `my-gpt4o-mini-deployment`)

The deployment name is user-chosen during deployment creation and may differ from the model name.

## Notable Models Available (as of 2026-05)

Chat models include: gpt-4o, gpt-4o-mini, gpt-4.1 series, gpt-5 series, o4-mini, DeepSeek-R1/V3/V3.1, claude-opus-4-6, claude-sonnet-4-6, grok-3/4, Llama-3.3-70B, Qwen-3-32B, Mistral-Large-3, Phi-4 series, and 150+ more.

Non-chat: DALL-E 3, TTS, Whisper, Stable Diffusion 3.5, FLUX, Sora, embeddings (ada-002, text-embedding-3-small/large), and more.
