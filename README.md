# Vast AI Provisioning

Utilities and notes for launching Vast.ai vLLM instances that load models from Cloudflare R2.

For technical details, operational rules, launch flow, template env vars, and secret handling, see:

```text
AGENTS.md
```

Read-only launch/cost check before renting:

```bash
. env.vast-management && ./run.sh scripts/select_and_launch.py \
  --launch-profile config/launch-profiles/qwen3.6-27b-awq.interruptible.json \
  --check-only \
  --top 1
```

Quick reminder: this repo is public. Do not commit secrets, live instance JSON, API keys, R2 credentials, Hugging Face tokens, or runtime output directories.
