# Vast SDK automation plan

Goal: launch vLLM-from-R2 instances from a template without manual UI work, then discover the random external ports Vast assigns.

## Current known base template

Fetched private template:

```text
name:    vLLM_R2_Model_20260504
id:      404766
hash_id: 21483c1ed2cf1c2d8f551d0a093d783a
image:   vastai/vllm
 tag:    v0.20.0-cuda-13.0
runtype: args
onstart: entrypoint.sh
```

Important inherited behavior:

- Template uses Vast's official `vastai/vllm` image.
- Template keeps official Vast port style:
  ```bash
  -p 1111:1111 -p 7860:7860 -p 8080:8080 -p 8000:8000 -p 8265:8265
  ```
- `PORTAL_CONFIG` maps external/container service ports to internal app ports:
  ```text
  1111 -> 11111 Instance Portal
  7860 -> 17860 Model UI
  8000 -> 18000 vLLM API
  8265 -> 28265 Ray Dashboard
  8080 -> 18080 Jupyter
  ```
- On Vast, the public host port is random per instance. The declared `-p 8000:8000` is a container/template mapping, not the final public port.

## Desired flow

```text
load config/env
find or create patched template from inherited vLLM template
search offers
create instance with template_hash
poll until running
fetch instance details
extract external random ports
print API/portal URLs
optionally health-check vLLM
```

## Config layers

### Global/account-level secrets

Prefer Vast account env vars for secrets:

```bash
AWS_ACCESS_KEY_ID
AWS_SECRET_ACCESS_KEY
```

Do not bake these into public templates.

### Per-model launch config

```bash
MODEL_ID="cyankiwi/Qwen3.5-9B-AWQ-4bit"
R2_BUCKET="..."
R2_PREFIX="$MODEL_ID"
R2_ENDPOINT="https://<account-id>.r2.cloudflarestorage.com"
MODEL_DIR="/workspace/models/$MODEL_ID"
SERVED_MODEL_NAME="qwen3.5-9b-awq"
VLLM_ARGS="--served-model-name qwen3.5-9b-awq --quantization awq --dtype half --host 127.0.0.1 --port 18000 --download-dir /workspace/models --gpu-memory-utilization 0.90 --trust-remote-code"
PROVISIONING_SCRIPT="https://raw.githubusercontent.com/memgrafter/vast-ai-provisioning/main/provision_vast_vllm_from_r2.sh"
AUTO_PARALLEL="false"
```

## Template strategy

Do not create from scratch if avoidable.

Use the fetched user template as base:

```text
templates/vLLM_R2_Model_20260504.21483c1ed2cf1c2d8f551d0a093d783a.json
```

Patch only:

- `name`
- `desc`
- `env` values for model/R2/vLLM/provisioning
- optionally `recommended_disk_space`

Preserve from base:

- image
- tag
- runtype
- onstart
- ports
- `PORTAL_CONFIG`
- official Vast defaults

## Docker env/options patching

The template `env` field is a Docker options string, e.g.:

```bash
-p 1111:1111 ... -e VLLM_MODEL="..." -e VLLM_ARGS="..."
```

Automation needs a safe parser/patcher:

1. tokenize with `shlex.split(env)`
2. preserve all `-p` entries
3. parse `-e KEY=VALUE` entries
4. replace/add these keys:
   - `R2_BUCKET`
   - `R2_PREFIX`
   - `R2_ENDPOINT`
   - `AWS_DEFAULT_REGION=auto`
   - `MODEL_DIR`
   - `VLLM_MODEL`
   - `VLLM_ARGS`
   - `AUTO_PARALLEL`
   - `PROVISIONING_SCRIPT`
5. preserve existing official keys:
   - `OPEN_BUTTON_PORT`
   - `OPEN_BUTTON_TOKEN`
   - `JUPYTER_DIR`
   - `DATA_DIRECTORY`
   - `PORTAL_CONFIG`
   - `RAY_ADDRESS`
   - `RAY_ARGS`
6. rebuild Docker options string with `shlex.quote`

## Instance launch

Use SDK:

```python
vast.create_instance(
    id=offer_id,
    template_hash=template_hash,
    disk=disk_gb,
    label=label,
)
```

or use `launch_instance` once query behavior is validated.

Search query should start conservative, e.g. single GPU, verified, rentable:

```text
num_gpus=1 verified=true rentable=true gpu_ram>=24 direct_port_count>=1
```

Sort by value/performance as appropriate:

```text
dlperf_usd-
```

## Polling and failure handling

Poll:

```python
info = vast.show_instance(id=instance_id)
status = info.get("actual_status")
```

Continue on:

```text
loading
starting
```

Success:

```text
running
```

Abort/destroy or report on:

```text
exited
unknown
offline
```

Add timeout so automation does not loop forever while charges accrue.

## Port discovery

After running:

```python
info = vast.show_instance(id=instance_id)
```

Save raw output first:

```text
instances/<instance_id>.json
```

Then inspect actual fields. Need to discover exact SDK/API shape.

Extractor goal:

```python
get_public_host(info) -> str
get_mapped_port(info, container_port=8000) -> int
```

Expected output URLs:

```text
vLLM API:        http://<host>:<mapped_8000>/v1
Instance Portal: http://<host>:<mapped_1111>/
Model UI:        http://<host>:<mapped_7860>/
Ray Dashboard:   http://<host>:<mapped_8265>/
Jupyter:         http://<host>:<mapped_8080>/
```

External API calls require `OPEN_BUTTON_TOKEN` bearer auth unless auth is disabled.

Open question: whether SDK exposes the token. Docs guarantee it exists inside the instance environment as `OPEN_BUTTON_TOKEN`; if not exposed by SDK, fetch via SSH/Jupyter or rely on known template value only during initial debugging.

## Health checks

Inside instance/local port:

```bash
curl http://localhost:18000/v1/models
```

External:

```bash
curl -H "Authorization: Bearer <OPEN_BUTTON_TOKEN>" \
  http://<host>:<mapped_8000>/v1/models
```

Chat completion:

```bash
curl -X POST \
  -H "Authorization: Bearer <OPEN_BUTTON_TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{"model":"qwen3.5-9b-awq","messages":[{"role":"user","content":"Hello!"}]}' \
  http://<host>:<mapped_8000>/v1/chat/completions
```

## Planned scripts

### `scripts/fetch_templates.py`

- fetch my templates
- save raw JSON into `templates/`
- identify base template by hash/name

### `scripts/patch_template.py`

- load base template JSON
- patch Docker options env vars
- dry-run diff/output
- optionally create/update template via SDK

### `scripts/launch_vllm_instance.py`

- search offers
- create instance with template hash
- poll status
- save `instances/<id>.json`
- print mapped URLs

### `scripts/inspect_instance_ports.py`

- read saved instance JSON or fetch by ID
- discover/print port mapping fields
- used to harden extractor after first launch

## Open questions to resolve on first test instance

1. Exact `show_instance` fields for public IP/host.
2. Exact `show_instance` fields for random external port mappings.
3. Whether `OPEN_BUTTON_TOKEN` appears in SDK output.
4. Whether `runtype=args` + `onstart=entrypoint.sh` behaves like desired Docker ENTRYPOINT mode for this inherited template.
5. Whether account-level env vars are injected into instances launched from SDK templates.
