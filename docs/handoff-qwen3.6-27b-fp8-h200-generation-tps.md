# Handoff: Qwen3.6 27B FP8 H200 generation TPS test

Goal: benchmark generation TPS for official dense FP8/MTP model on H200, comparable to the prior AWQ H200 5-stream test.

## Current transfer

Streaming upload is running from Hugging Face to R2 without local model staging.

```text
HF repo: Qwen/Qwen3.6-27B-FP8
R2 prefix: Qwen/Qwen3.6-27B-FP8
profile: config/models/qwen3.6-27b-fp8.json
pid file: state/stream-qwen3.6-27b-fp8.pid
log file: state/stream-qwen3.6-27b-fp8.log
```

Check progress:

```bash
pid=$(cat state/stream-qwen3.6-27b-fp8.pid)
ps -p "$pid" -o pid,stat,etime,command

tail -30 state/stream-qwen3.6-27b-fp8.log

source env.modeltransfer
.venv/bin/aws s3 ls "s3://$R2_BUCKET/Qwen/Qwen3.6-27B-FP8/" \
  --endpoint-url "$R2_ENDPOINT" \
  --recursive --summarize | tail -30
```

Expected total repo size from HF metadata: about `30.89 GB`.

A static R2 speed-test object exists and the provisioner now prefers it:

```text
_vast/r2-speed-test.bin
```

## Model profile

New profile added:

```text
config/models/qwen3.6-27b-fp8.json
```

Key fields:

```json
{
  "hf_model_id": "Qwen/Qwen3.6-27B-FP8",
  "r2_prefix": "Qwen/Qwen3.6-27B-FP8",
  "model_dir": "/workspace/models/Qwen/Qwen3.6-27B-FP8",
  "served_model_name": "qwen3.6-27b-fp8",
  "quantization": "fp8",
  "vllm": {
    "dtype": "auto",
    "max_model_len": 160000,
    "gpu_memory_utilization": 0.9,
    "max_num_seqs": 64
  }
}
```

## Prior comparable AWQ H200 result

Prior run used H200 on-demand, 5 concurrent coding-shaped streams, no prefix-cache hits:

```text
instance_id: 36497799
machine_id: 74712
gpu: H200
model: qwen3.6-27b-awq
max_model_len: 160000
concurrency: 5
prompt_words_goal: 4500
avg prompt/request: ~6,294.6 tokens
output cap: 2048
requests_ok: 15
requests_error: 0
```

Throughput:

```text
prompt_tps:     1,140.23 tok/s
generation_tps:   370.98 tok/s
total_tps:      1,511.22 tok/s
```

Per-stream generation:

```text
wall-clock:       370.98 / 5 = 74.20 tok/s/stream
active inference: 2048 / 26.46 = 77.40 tok/s/stream
```

Latency:

```text
avg latency:    27.58s
p50 latency:    27.21s
p95 latency:    29.06s
avg TTFT:        2.58s
avg queue:       0.36s
avg inference:  26.46s
```

## Need before launch

1. Confirm stream upload finished and `.stream-manifest.json` exists in R2:

```bash
source env.modeltransfer
.venv/bin/aws s3 ls "s3://$R2_BUCKET/Qwen/Qwen3.6-27B-FP8/.stream-manifest.json" \
  --endpoint-url "$R2_ENDPOINT"
```

2. Create/copy an H200 on-demand launch profile for FP8. Use copy + edit from:

```text
config/launch-profiles/qwen3.6-27b-awq.h200.ondemand.json
```

Suggested new file:

```text
config/launch-profiles/qwen3.6-27b-fp8.h200.ondemand.json
```

Change only:

```json
"model_profile": "config/models/qwen3.6-27b-fp8.json",
"name": "qwen3.6-27b-fp8.h200.ondemand"
```

Keep H200 GPU profile/gates initially. Reuse greylist and price gates unless current offers require review.

3. Build/apply the remote template for this FP8 profile using the launch-profile-driven prepare flow:

```bash
. env.vast-management
./run.sh scripts/prepare_vast_template.py \
  --launch-profile config/launch-profiles/qwen3.6-27b-fp8.h200.ondemand.json \
  --hash-id <existing-or-new-template-hash> \
  --yes
```

If unsure whether to reuse an existing template, render first for review under `state/templates/`, or create a new private template. Do not put secrets in committed files.

## Run benchmark

Use same benchmark shape as AWQ comparable run:

```bash
. env.vast-management
./run.sh scripts/smoke_chat_once.py \
  --launch-profile config/launch-profiles/qwen3.6-27b-fp8.h200.ondemand.json \
  --launch-attempts 1 \
  --ready-timeout 3000 \
  --bench-seconds 60 \
  --bench-concurrency 5 \
  --bench-input-tokens 4500 \
  --bench-output-tokens 2048 \
  --no-destroy-on-error
```

`--no-destroy-on-error` leaves the instance running if the bench fails, so inspect/debug before manually destroying. On success the script still destroys by default only if the bench returns success; verify behavior before walking away.

The script saves final debug before closeout:

```text
instances/<instance_id>.final.json
instances/<instance_id>.final.logs.tail5000.txt
```

## Metrics to report

Primary comparison:

```text
generation_tps total
generation_tps per stream = generation_tps / 5
active per-stream gen TPS = avg_generation_tokens_per_request / avg_inference_s
```

Also report:

```text
prompt_tps
total_tps
requests_ok / requests_error
avg prompt tokens/request
avg generation tokens/request
TTFT avg
queue avg
inference avg
latency p50/p95
prefix cache hit tokens (should be 0 for this no-cache test)
```

## Cleanup

Always confirm no expensive instance remains after the run unless intentionally left for debugging:

```bash
. env.vast-management
.venv/bin/python - <<'PY'
from vastai import VastAI
import json
vast = VastAI()
print(json.dumps([
  {k: i.get(k) for k in ['id', 'label', 'actual_status', 'gpu_name', 'dph_total', 'machine_id']}
  for i in vast.show_instances()
  if 'qwen3.6-27b' in str(i.get('label', '')) or 'smoke-' in str(i.get('label', ''))
], indent=2, sort_keys=True, default=str))
PY
```

Destroy manually if needed:

```bash
. env.vast-management
.venv/bin/python - <<'PY'
from vastai import VastAI
vast = VastAI()
print(vast.destroy_instance(id=<INSTANCE_ID>))
PY
```
