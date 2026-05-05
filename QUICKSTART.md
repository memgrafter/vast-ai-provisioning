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

## 3. Build/apply remote template from launch profile

The local public-safe template spec is:

```text
config/templates/vllm-r2-base.public.json
```

The ignored private overlay supplies private-but-not-secret R2 identifiers:

```text
config/private/vllm-r2.local.json
```

Prepare a remote template directly from the committed launch profile:

```bash
. env.vast-management
./run.sh scripts/prepare_vast_template.py \
  --launch-profile config/launch-profiles/qwen3.5-9b-awq.interruptible.json \
  --create
```

This renders a local payload under `state/templates/`, writes/updates `state/templates/manifest.json`, creates a remote Vast template, and writes the returned `template.hash_id` back into the launch profile. Templates default to private. Use `--public` only for intentionally shareable templates whose overlay contains no private identifiers.

To update an existing remote template instead:

```bash
. env.vast-management
./run.sh scripts/prepare_vast_template.py \
  --launch-profile config/launch-profiles/qwen3.5-9b-awq.interruptible.json \
  --hash-id <remote-template-hash>
```

For review-only rendering without remote mutation:

```bash
./run.sh scripts/build_vast_template.py \
  --launch-profile config/launch-profiles/qwen3.5-9b-awq.interruptible.json \
  --template-spec config/templates/vllm-r2-base.public.json \
  --private-overlay config/private/vllm-r2.local.json \
  --out state/templates/qwen3.5-9b-awq.interruptible.rendered.json
```

## 4. Optional one-command smoke loop

For a short end-to-end test that launches, waits for readiness, sends one chat completion, and destroys the instance either way:

```bash
. env.vast-management
./run.sh scripts/smoke_chat_once.py \
  --launch-profile config/launch-profiles/qwen3.5-9b-awq.interruptible.json
```

For the 27B AWQ profile, use this composed one-liner:

```bash
. env.vast-management && ./run.sh scripts/smoke_chat_once.py --launch-profile config/launch-profiles/qwen3.6-27b-awq.interruptible.json --launch-attempts 2 --ready-timeout 1800 --message 'Say hello in one short sentence.'
```

## 5. Check launch availability and cost

Run the launcher in read-only check mode to show current infra, offer-policy PASS/FAIL reasons, and the selected offer without launching:

```bash
. env.vast-management && ./run.sh scripts/select_and_launch.py \
  --launch-profile config/launch-profiles/qwen3.6-27b-awq.interruptible.json \
  --check-only \
  --top 1
```

Use `--skip-current-infra` if you only want the marketplace offer check. Use `--top N` to summarize more than one passing offer.

## 6. Launch manually

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

## 7. Check inside instance

```bash
tail -f /var/log/portal/provisioning.log
supervisorctl status
supervisorctl tail -f vllm
curl -H "Authorization: Bearer $VLLM_API_KEY" http://localhost:18000/v1/models
```

## 8. External API

Fetch mapped external port for container port `8000`, then call:

```bash
curl -H "Authorization: Bearer $VLLM_API_KEY" \
  http://<host>:<mapped_8000>/v1/models
```
