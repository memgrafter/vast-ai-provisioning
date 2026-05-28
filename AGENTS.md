# AGENTS.md

## Quick reminders

- Vast maps container ports to random external host ports. Do not assume external `:8000` exists.
- Always read the instance `ports` mapping and use the mapped host port for API calls.
- Example: container `8000/tcp` may map to `http://<public_ip>:<HostPort>/v1`.

## Purpose

Provision Vast.ai vLLM instances that sync a private R2-hosted Hugging Face model repo before serving.

## One-off Python deps with uv

The project venv does not include every ad-hoc inspection dependency. For one-off R2/S3 inspection with `boto3`, prefer `uv run --with boto3` instead of modifying project dependencies.

Example:

```bash
. env.modeltransfer
uv run --quiet --with boto3 python - <<'PY'
import os
import boto3

s3 = boto3.client(
    "s3",
    endpoint_url=os.environ["R2_ENDPOINT"],
    aws_access_key_id=os.environ["AWS_ACCESS_KEY_ID"],
    aws_secret_access_key=os.environ["AWS_SECRET_ACCESS_KEY"],
    region_name=os.environ.get("AWS_DEFAULT_REGION", "auto"),
)
for page in s3.get_paginator("list_objects_v2").paginate(Bucket=os.environ["R2_BUCKET"]):
    for obj in page.get("Contents", []):
        print(obj["Key"], obj["Size"])
PY
```

Do not print secrets or commit generated R2 listings if they contain private identifiers.

## Secret rules

- This repo is public.
- Never commit secrets, live instance JSON, API keys, R2 credentials, Hugging Face tokens, or PII.
- Keep local secrets in ignored env files:
  - `env.modeltransfer`
  - `env.vast-management`
- Vast account-level env vars must contain:

```bash
AWS_ACCESS_KEY_ID
AWS_SECRET_ACCESS_KEY
VLLM_API_KEY
```

Do not put those values in public templates. Templates may reference `VLLM_API_KEY` by name only.

## Profile-based config

The active launch path uses profiles directly. Do not reintroduce a rendered legacy launch-policy adapter.

Current default model profile:

```text
config/models/qwen3.5-9b-awq.json
```

Current default GPU profile:

```text
config/gpu-profiles/qwen-9b-awq-1gpu.json
```

Current default launch profile:

```text
config/launch-profiles/qwen3.5-9b-awq.interruptible.json
```

Current default template spec:

```text
config/templates/vllm-r2-base.public.json
```

## Local template source of truth

Build Vast template payloads locally from:

```text
public-safe template spec + launch profile + model profile + ignored private overlay
```

The launch profile owns the remote template identity:

```json
"template": {
  "name": "...",
  "hash_id": "..."
}
```

Use the launch-profile-driven prepare command for remote create/update:

```bash
. env.vast-management
./run.sh scripts/prepare_vast_template.py \
  --launch-profile config/launch-profiles/qwen3.5-9b-awq.interruptible.json \
  --create
```

or update an existing remote template by hash:

```bash
. env.vast-management
./run.sh scripts/prepare_vast_template.py \
  --launch-profile config/launch-profiles/qwen3.5-9b-awq.interruptible.json \
  --hash-id <remote-template-hash>
```

Templates default to private. Use `--public` only for intentionally shareable templates whose overlay contains no private identifiers.

For review-only rendering without remote mutation:

```bash
./run.sh scripts/build_vast_template.py \
  --launch-profile config/launch-profiles/qwen3.5-9b-awq.interruptible.json \
  --template-spec config/templates/vllm-r2-base.public.json \
  --private-overlay config/private/vllm-r2.local.json \
  --out state/templates/qwen3.5-9b-awq.interruptible.rendered.json
```

The build writes `state/templates/manifest.json`. `scripts/apply_vast_template.py` only applies rendered templates listed in that manifest; running it with no args prints help.

`config/private/` is ignored and may contain private-but-not-secret values such as real R2 bucket and endpoint. Rendered/live/private template files belong in ignored local paths such as `state/` or ignored `templates/` snapshots. Do not commit them.

## Local setup

```bash
./run.sh
```

## Check-only availability/cost checks

Use `--check-only` for read-only offer and cost checks. It must not prompt or launch an instance.

```bash
. env.vast-management
./run.sh scripts/select_and_launch.py \
  --launch-profile config/launch-profiles/qwen3.5-9b-awq.interruptible.json \
  --check-only \
  --top 1
```

In check-only mode, the launcher prints current instances and known hourly burn, notes owned volumes are not checked, searches offers through the policy filter, summarizes the top passing offers, and exits before launch.

Useful check-only flags:

- `--skip-current-infra` skips querying current instances and only searches offers.
- `--top N` controls how many passing offers to summarize.

Prefer `--check-only` over `--dry-run` for no-prompt read-only checks. `--dry-run` shows the selected offer then exits, but launch mode can still prompt before that point.

## Launch flow

Use the guarded profile launcher for real launches:

```bash
. env.vast-management
./run.sh scripts/select_and_launch.py \
  --launch-profile config/launch-profiles/qwen3.5-9b-awq.interruptible.json
```

Launch mode must show current instances and known hourly burn, note owned volumes are not checked, prompt before search/selection, print the selected offer and cost estimate, prompt before launch, and save runtime JSON locally only. Use `--yes-current-infra` and `--yes-launch` only when intentionally skipping those prompts.

## Runtime output dirs

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

External vLLM API uses the account-level `VLLM_API_KEY`:

```bash
curl -H "Authorization: Bearer $VLLM_API_KEY" \
  http://<host>:<mapped_8000>/v1/models
```

Summarize vLLM runtime metrics with:

```bash
. env.vast-management
./run.sh scripts/summarize_vllm_metrics.py \
  --base-url http://<host>:<mapped_8000>/v1
```

or:

```bash
. env.vast-management
./run.sh scripts/summarize_vllm_metrics.py \
  --metrics-url http://<host>:<mapped_8000>/metrics
```

The metrics summary prints request counts, token totals, prefix-cache hit rate, prompt-token sources, TTFT buckets, queue time, and inference time. For a recent TPS gauge, take two scrapes with `--interval`:

```bash
. env.vast-management
./run.sh scripts/summarize_vllm_metrics.py \
  --base-url http://<host>:<mapped_8000>/v1 \
  --interval 10
```

Use shell `watch` around that command if repeated gauges are needed.

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

vLLM args are generated from profile-derived environment variables into:

```text
/etc/vllm-args.conf
```

## Model transfer to R2

Use local env and model profile:

```bash
source env.modeltransfer
./transfer_model_to_R2.sh --model-profile config/models/qwen3.5-9b-awq.json
```

The transfer script reads Hugging Face model ID and R2 prefix from the model profile.
