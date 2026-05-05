# Vast.ai vLLM-from-R2 template setup

This document is historical. The active implementation is now profile-based and local-template-source-of-truth based.

Use the current docs instead:

```text
AGENTS.md
QUICKSTART.md
docs/model-profile-pure-refactor-plan.md
docs/model-profile-refactor-plan.md
```

## Active template strategy

Use the official/cached Vast vLLM image. Do **not** build a custom image yet.

Why:

- official `vastai/vllm` layers are likely cached on many hosts
- model changes are profile/template changes, not image rebuilds
- `PROVISIONING_SCRIPT` is fine because each model/profile case uses a rendered template payload
- custom images only become worth it if install/bootstrap overhead is proven significant

## Local template source of truth

The public-safe base template is:

```text
config/templates/vllm-r2-base.public.json
```

Model-specific values come from:

```text
config/models/<model>.json
```

Private-but-not-secret values such as real R2 bucket/endpoint belong in ignored overlays such as:

```text
config/private/vllm-r2.local.json
```

Build a rendered template payload:

```bash
./run.sh scripts/build_vast_template.py \
  --template-spec config/templates/vllm-r2-base.public.json \
  --private-overlay config/private/vllm-r2.local.json \
  --model-profile config/models/qwen3.5-9b-awq.json \
  --out state/templates/vllm-r2.qwen3.5-9b-awq.rendered.json
```

Apply a reviewed payload:

```bash
. env.vast-management
./run.sh scripts/apply_vast_template.py \
  --hash-id <remote-template-hash> \
  --template state/templates/vllm-r2.qwen3.5-9b-awq.rendered.json \
  --update-launch-profile config/launch-profiles/qwen3.5-9b-awq.interruptible.json
```

Use `--create` for a new model/profile case so each case has a separate remote Vast template.

## Model artifact convention

Mirror the full Hugging Face/vLLM-compatible repo to R2. For the current model:

```text
HF repo:   cyankiwi/Qwen3.5-9B-AWQ-4bit
R2 prefix: cyankiwi/Qwen3.5-9B-AWQ-4bit
```

Expected R2 layout:

```text
s3://$R2_BUCKET/cyankiwi/Qwen3.5-9B-AWQ-4bit/
  config.json
  tokenizer.json
  tokenizer_config.json
  generation_config.json
  *.safetensors
  *.json
```

For vLLM models, transfer the whole repo unless a future profile explicitly supports single-file transfer.

```bash
source env.modeltransfer
./transfer_model_to_R2.sh --model-profile config/models/qwen3.5-9b-awq.json
```

## vLLM runtime args

Do not hardcode model-specific `VLLM_ARGS` in templates. The provisioning script generates `/etc/vllm-args.conf` from profile-derived environment variables:

```text
SERVED_MODEL_NAME
VLLM_DTYPE
VLLM_MAX_MODEL_LEN
VLLM_HOST
VLLM_PORT
VLLM_DOWNLOAD_DIR
VLLM_GPU_MEMORY_UTILIZATION
VLLM_TRUST_REMOTE_CODE
VLLM_FORCE_QUANTIZATION
VLLM_EXTRA_ARGS
```

`VLLM_FORCE_QUANTIZATION` should remain empty unless a model profile explicitly requires it. Prefer model-declared quantization.

## Auth

External OpenAI-compatible API calls use vLLM API key auth:

```bash
curl -H "Authorization: Bearer $VLLM_API_KEY" \
  http://<INSTANCE_IP>:<MAPPED_PORT_8000>/v1/models
```

The actual `VLLM_API_KEY` value must be configured as a Vast account-level env var and must not be committed.

## When changing models

Add or edit profile files:

```text
config/models/<model>.json
config/gpu-profiles/<gpu-profile>.json
config/launch-profiles/<launch-profile>.json
```

Then:

1. mirror the model with `transfer_model_to_R2.sh --model-profile ...`
2. build a rendered template payload from the model profile
3. create/apply a separate remote Vast template for that case
4. launch directly with the launch profile
