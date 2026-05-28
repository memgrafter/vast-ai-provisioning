# Vast SDK automation plan

This document is historical. The active implementation is now profile-based and local-template-source-of-truth based.

Use the current docs instead:

```text
AGENTS.md
QUICKSTART.md
docs/model-profile-pure-refactor-plan.md
docs/model-profile-refactor-plan.md
```

## Current active flow

### Profiles

Current profile files:

```text
config/models/qwen3.5-9b-awq.json
config/gpu-profiles/qwen-9b-awq-1gpu.json
config/launch-profiles/qwen3.5-9b-awq.interruptible.json
```

The launcher consumes launch profiles directly:

```bash
. env.vast-management
./run.sh scripts/select_and_launch.py \
  --launch-profile config/launch-profiles/qwen3.5-9b-awq.interruptible.json
```

### Template source of truth

Do not patch remote Vast templates as the source of truth. Build local rendered payloads from:

```text
config/templates/vllm-r2-base.public.json
config/models/<model>.json
config/private/<ignored-overlay>.json
```

Build:

```bash
./run.sh scripts/build_vast_template.py \
  --template-spec config/templates/vllm-r2-base.public.json \
  --private-overlay config/private/vllm-r2.local.json \
  --model-profile config/models/qwen3.5-9b-awq.json \
  --out state/templates/vllm-r2.qwen3.5-9b-awq.rendered.json
```

Apply only reviewed rendered payloads listed in `state/templates/manifest.json`:

```bash
. env.vast-management
./run.sh scripts/apply_vast_template.py \
  --hash-id <remote-template-hash> \
  --template state/templates/vllm-r2.qwen3.5-9b-awq.rendered.json \
  --update-launch-profile config/launch-profiles/qwen3.5-9b-awq.interruptible.json
```

Create separate remote templates per model/profile case with `--create`.

### Secrets and auth

Required Vast account-level runtime env vars:

```bash
AWS_ACCESS_KEY_ID
AWS_SECRET_ACCESS_KEY
VLLM_API_KEY
```

External OpenAI-compatible API auth uses vLLM's API key:

```bash
curl -H "Authorization: Bearer $VLLM_API_KEY" \
  http://<host>:<mapped_8000>/v1/models
```

Caddy/OpenButton auth is not the API auth path for `/v1/chat/completions`.

## Historical note

Older notes in this file described planned scripts such as `fetch_templates.py`, `patch_template.py`, and `launch_vllm_instance.py`, plus direct remote patching and Caddy/OpenButton API auth. Those are obsolete and should not be reintroduced.
