# Vast.ai vLLM-from-R2 template setup

Goal: fast fresh-machine launches with minimal rework when swapping models. Assumption: when the model changes, you rent/replace the machine.

## Recommended strategy

Use the official/cached Vast vLLM image. Do **not** build a custom image yet.

Why:

- official `vastai/vllm` layers are likely cached on many hosts
- model changes are env-var changes, not image rebuilds
- `PROVISIONING_SCRIPT` is fine because each model change uses a fresh machine
- custom image only becomes worth it if install/bootstrap overhead is proven significant

## Launch modes

### Production

Use:

```text
Docker ENTRYPOINT
```

The image runs as designed. The official image entrypoint starts Vast tooling, Supervisor, Instance Portal, Ray, and vLLM.

Use env file:

```text
env.vast-vllm.production.example
```

### Discovery/debug

Use:

```text
Jupyter + SSH
```

In SSH/Jupyter modes Vast overrides the Docker entrypoint, so paste the contents of this file into the template on-start field:

```text
onstart.vast-vllm-discovery.sh
```

It restores the image startup with:

```bash
exec /opt/instance-tools/bin/entrypoint.sh
```

Use env file:

```text
env.vast-vllm.discovery.example
```

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

For vLLM/AWQ, download/upload the **whole repo**, not a single file.

## Vast env vars

Core model-specific values:

```bash
R2_PREFIX="cyankiwi/Qwen3.5-9B-AWQ-4bit"
MODEL_DIR="/workspace/models/cyankiwi/Qwen3.5-9B-AWQ-4bit"
VLLM_MODEL="/workspace/models/cyankiwi/Qwen3.5-9B-AWQ-4bit"
VLLM_ARGS="--served-model-name qwen3.5-9b-awq --quantization awq --dtype half --host 127.0.0.1 --port 18000 --download-dir /workspace/models --gpu-memory-utilization 0.90 --trust-remote-code"
AUTO_PARALLEL="false"
```

Port `18000` is the internal vLLM port. Vast exposes API access through external/mapped port `8000` via the portal/proxy.

## Provisioning

Host this file at a raw HTTPS URL:

```text
provision_vast_vllm_from_r2.sh
```

Then set:

```bash
GITHUB_USER="memgrafter"
GITHUB_REPO="vast-ai-provisioning"
GITHUB_BRANCH="main"
PROVISIONING_SCRIPT="https://raw.githubusercontent.com/${GITHUB_USER}/${GITHUB_REPO}/${GITHUB_BRANCH}/provision_vast_vllm_from_r2.sh"
```

The script:

1. validates R2/model env vars
2. installs `awscli` if missing
3. configures S3/R2 multipart/concurrency
4. syncs `s3://$R2_BUCKET/$R2_PREFIX` to `$MODEL_DIR`
5. skips sync if model files already exist
6. lets vLLM start after provisioning completes

## Startup sequence

```text
Vast pulls cached vLLM image
container boots
provisioning syncs model from R2 to /workspace/models/...
vLLM supervisor waits until provisioning is done
vLLM starts from local MODEL_DIR
Instance Portal exposes the API
```

## Checks on first boot

Inside SSH/Jupyter terminal:

```bash
supervisorctl status
supervisorctl tail -f vllm
curl http://localhost:18000/v1/models
```

External API call uses the mapped external port for `8000` and the `OPEN_BUTTON_TOKEN` bearer token:

```bash
curl -X POST \
  -H "Authorization: Bearer <OPEN_BUTTON_TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{"model":"qwen3.5-9b-awq","messages":[{"role":"user","content":"Hello!"}]}' \
  http://<INSTANCE_IP>:<MAPPED_PORT_8000>/v1/chat/completions
```

## When changing models

Replace machine and change only env vars:

```bash
R2_PREFIX="new/org-or-user/model"
MODEL_DIR="/workspace/models/new/org-or-user/model"
VLLM_MODEL="$MODEL_DIR"
VLLM_ARGS="--served-model-name new-name ..."
```

Keep the same official image and same provisioning script URL.
