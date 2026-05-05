# Quickstart

Goal: launch the public Vast vLLM template, pull the model from private R2, and serve vLLM.

## 1. Add Vast account-level secrets

In Vast account environment variables, add:

```bash
AWS_ACCESS_KEY_ID
AWS_SECRET_ACCESS_KEY
```

Do **not** put these in the public template.

## 2. Ensure model is in R2

Expected prefix:

```text
s3://<R2_BUCKET>/cyankiwi/Qwen3.5-9B-AWQ-4bit/
```

## 3. Add env vars to your private template copy

Make a private copy of the public template, then add/override these **non-secret** env vars in the template environment section:

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

## 4. Launch

Use the `vLLM_R2_Model_20260504` template.

Start with one GPU and enough disk, e.g. 80GB.

## 5. Check inside instance

```bash
tail -f /var/log/portal/provisioning.log
supervisorctl status
supervisorctl tail -f vllm
curl http://localhost:18000/v1/models
```

## 6. External API

Fetch mapped external port for container port `8000`, then call:

```bash
curl -H "Authorization: Bearer <OPEN_BUTTON_TOKEN>" \
  http://<host>:<mapped_8000>/v1/models
```
