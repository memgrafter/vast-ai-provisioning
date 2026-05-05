# Quickstart

Goal: launch the Vast vLLM template, pull the profiled model from private R2, and serve vLLM.

## 1. Add Vast account-level secrets

In Vast account environment variables, add:

```bash
AWS_ACCESS_KEY_ID
AWS_SECRET_ACCESS_KEY
VLLM_API_KEY
```

Do **not** put these values in public templates, profile files, docs, or committed config.

## 2. Use the current model profile

Current default profile:

```text
config/models/qwen3.5-9b-awq.json
```

Expected R2 prefix from the profile:

```text
s3://<R2_BUCKET>/cyankiwi/Qwen3.5-9B-AWQ-4bit/
```

Mirror the model with:

```bash
source env.modeltransfer
./transfer_model_to_R2.sh --model-profile config/models/qwen3.5-9b-awq.json
```

## 3. Build local template payload

The local public-safe template spec is:

```text
config/templates/vllm-r2-base.public.json
```

Build a rendered template payload for review:

```bash
./run.sh scripts/build_vast_template.py \
  --template-spec config/templates/vllm-r2-base.public.json \
  --model-profile config/models/qwen3.5-9b-awq.json \
  --out state/templates/vllm-r2.qwen3.5-9b-awq.rendered.json
```

The public spec uses placeholders for private R2 identifiers. Keep any private overlay or rendered live template under ignored local paths only.

## 4. Launch

Use the profile-based launcher:

```bash
. env.vast-management
./run.sh scripts/select_and_launch.py \
  --launch-profile config/launch-profiles/qwen3.5-9b-awq.interruptible.json
```

The launcher reads:

```text
config/launch-profiles/qwen3.5-9b-awq.interruptible.json
config/models/qwen3.5-9b-awq.json
config/gpu-profiles/qwen-9b-awq-1gpu.json
```

## 5. Check inside instance

```bash
tail -f /var/log/portal/provisioning.log
supervisorctl status
supervisorctl tail -f vllm
curl -H "Authorization: Bearer $VLLM_API_KEY" http://localhost:18000/v1/models
```

## 6. External API

Fetch mapped external port for container port `8000`, then call:

```bash
curl -H "Authorization: Bearer $VLLM_API_KEY" \
  http://<host>:<mapped_8000>/v1/models
```
