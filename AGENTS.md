# AGENTS.md

## Purpose

Provision Vast.ai vLLM instances that sync a private R2-hosted Hugging Face model repo before serving.

## Secret rules

- This repo is public.
- Never commit secrets, live instance JSON, API keys, R2 credentials, or Hugging Face tokens.
- Keep local secrets in ignored env files:
  - `env.modeltransfer`
  - `env.vast-management`
- Vast account-level env vars must contain:

```bash
AWS_ACCESS_KEY_ID
AWS_SECRET_ACCESS_KEY
```

Do not put those in public templates.

## Current model

```bash
MODEL_ID="cyankiwi/Qwen3.5-9B-AWQ-4bit"
R2_PREFIX="cyankiwi/Qwen3.5-9B-AWQ-4bit"
MODEL_DIR="/workspace/models/cyankiwi/Qwen3.5-9B-AWQ-4bit"
SERVED_MODEL_NAME="qwen3.5-9b-awq"
```

## Vast template

Private working template:

```text
name: vLLM_R2_Model_20260504
hash: 71660d832be5a4b7fb76730e6e36d1bc
```

Public-safe skeleton:

```text
templates/vllm-r2-template.public.json
```

The template should contain only non-secret env vars:

```bash
R2_BUCKET="<bucket>"
R2_PREFIX="cyankiwi/Qwen3.5-9B-AWQ-4bit"
R2_ENDPOINT="https://<account-id>.r2.cloudflarestorage.com"
AWS_DEFAULT_REGION="auto"
MODEL_DIR="/workspace/models/cyankiwi/Qwen3.5-9B-AWQ-4bit"
VLLM_MODEL="/workspace/models/cyankiwi/Qwen3.5-9B-AWQ-4bit"
VLLM_ARGS="--served-model-name qwen3.5-9b-awq --quantization awq --dtype half --max-model-len 8192 --host 127.0.0.1 --port 18000 --download-dir /workspace/models --gpu-memory-utilization 0.90 --trust-remote-code"
AUTO_PARALLEL="false"
PROVISIONING_SCRIPT="https://raw.githubusercontent.com/memgrafter/vast-ai-provisioning/main/provision_vast_vllm_from_r2.sh"
```

## Launch policy

Use:

```text
config/launch-policy.l40s-prototype.json
```

Current policy intent:

- interruptible market
- 1 GPU
- allowed GPU list, 21GB+ VRAM
- CUDA >= 13.0
- verified enforced in Vast search query only
- reliability >= 0.98
- 40GB disk
- max total hourly <= $0.65
- max storage <= $0.012/hr
- max network <= $3/TB down, $4/TB up
- bid cap <= $0.65/hr

Note: Vast returns `verified` as null on some offers even when `verified=true` is in the query. Do not post-filter `offer["verified"]`; trust the server-side query.

## Local setup

```bash
./run.sh
```

Run scripts with:

```bash
. env.vast-management
./run.sh scripts/select_and_launch.py --dry-run
```

## Launch flow

Use the guarded launcher:

```bash
. env.vast-management
./run.sh scripts/select_and_launch.py
```

It must:

1. show current instances and known hourly burn
2. note owned volumes are not checked
3. prompt before search/selection
4. print selected offer and cost estimate
5. prompt before launch
6. save runtime JSON locally only

Runtime output dirs are local/ignored and must not be committed:

```text
state/
offers/
instances/
```

## After launch

Fetch status:

```bash
. env.vast-management
.venv/bin/python - <<'PY'
from vastai import VastAI
import json
vast = VastAI()
print(json.dumps(vast.show_instance(id=<INSTANCE_ID>), indent=2, sort_keys=True, default=str))
PY
```

Wait for `actual_status == "running"`, then inspect port mappings for container port `8000`.

External vLLM API:

```bash
curl -H "Authorization: Bearer 1" \
  http://<host>:<mapped_8000>/v1/models
```

## Provisioning logs

The provisioner script is:

```text
provision_vast_vllm_from_r2.sh
```

Expected log markers:

```text
Provisioning model from R2
R2 source: s3://...
Target: /workspace/models/...
Syncing s3://...
```

Until those appear, the machine is probably still pulling the Docker image.

## Model transfer to R2

Use local env:

```bash
source env.modeltransfer
./transfer_model_to_R2.sh
```

For vLLM/AWQ, `HF_FILENAME` should be empty so the whole repo is mirrored.
