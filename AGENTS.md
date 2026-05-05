# AGENTS.md

## Purpose

Provision Vast.ai vLLM instances that sync a private R2-hosted Hugging Face model repo before serving.

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

Run a read-only launch/cost check with:

```bash
. env.vast-management
./run.sh scripts/select_and_launch.py \
  --launch-profile config/launch-profiles/qwen3.5-9b-awq.interruptible.json \
  --check-only \
  --top 1
```

Use `--skip-current-infra` with `--check-only` to skip querying current instances. Prefer `--check-only` over legacy `--dry-run` for no-prompt read-only checks.

## Launch flow

Use the guarded profile launcher:

```bash
. env.vast-management
./run.sh scripts/select_and_launch.py \
  --launch-profile config/launch-profiles/qwen3.5-9b-awq.interruptible.json
```

It must:

1. support `--check-only` for read-only offer/cost checks with no launch prompts
2. show current instances and known hourly burn unless `--skip-current-infra` is used with `--check-only`
3. note owned volumes are not checked
4. prompt before search/selection in launch mode
5. print selected offer and cost estimate
6. prompt before launch in launch mode
7. save runtime JSON locally only

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
