# Handoff: B200 27B Dense Benchmark Resume — BF16 Next

Date: 2026-05-16T08:02:53Z

## Current state

Credits ran out and the B200 used for this session was terminated by the user. There is no live B200 to preserve at this handoff.

Do **not** assume the old instance exists. Launch a fresh B200 when credits are available.

## What was completed

### Carnice NVFP4/modelopt B200 benchmarked

Model/profile:

```text
model: sakamakismile/Carnice-V2-27b-NVFP4-TEXT-MTP
served_model_name: carnice-v2-27b-nvfp4-text-mtp-b200-maxctx-mtp3
profile: config/models/carnice-v2-27b-nvfp4-text-mtp.b200-maxctx-mtp3.json
launch profile: config/launch-profiles/carnice-v2-27b-nvfp4-text-mtp.b200-maxctx-mtp3.on-demand.json
MTP: n=3
max_model_len: 262144
max_num_seqs: 512
max_num_batched_tokens: 16384
max_new_tokens: 30000
kv_cache_dtype: fp8
```

Main result:

```text
Current agentic sweet spot: c=96
shape: shared 30K prefix, max_tokens=20000, 4 sequential measured requests/user after warmup
throughput: ~5575 tok/s total
per-user: ~58.1 tok/s/user
max_kv: ~75.3%
queue_avg: ~0.11s
TTFT_avg: ~1.34s
```

Comparison points under the same agentic shape:

```text
c=24:  2845 tok/s total, 118.5 tok/s/user, max_kv 19.8%, queue_avg 0.03s
c=64:  4942 tok/s total,  77.2 tok/s/user, max_kv 50.3%, queue_avg 0.11s
c=96:  5575 tok/s total,  58.1 tok/s/user, max_kv 75.3%, queue_avg 0.11s
c=128: 5450 tok/s total,  42.6 tok/s/user, max_kv 100%,  queue_avg 13.02s
```

Interpretation:

```text
c=96 is the best current service-shaped target.
c=128 is saturated: lower aggregate than c=96, worse per-user TPS, much higher queue/TTFT, KV reached 100%.
```

Full report:

```text
docs/b200-carnice-v2-27b-nvfp4-mtp3-throughput-report-2026-05-16.md
```

Earlier handoff:

```text
docs/handoff-b200-27b-carnice-fp8-bf16-2026-05-16.md
```

### BF16 upload completed

The streamed HF-to-R2 upload of full BF16 Qwen completed.

```text
HF repo: Qwen/Qwen3.6-27B
R2 prefix: Qwen/Qwen3.6-27B
manifest: Qwen/Qwen3.6-27B/.stream-manifest.json
uploaded files: 29
model shards: model-00001-of-00015.safetensors through model-00015-of-00015.safetensors
```

The local stream process is no longer running; the log showed successful completion.

Log path if still present locally:

```text
state/stream-qwen3.6-27b-bf16.log
```

### BF16 B200 profile/template prepared

BF16 profile:

```text
config/models/qwen3.6-27b-bf16.b200-maxctx-mtp2.json
```

Key BF16 settings:

```text
model: Qwen/Qwen3.6-27B
dtype: bfloat16
served_model_name: qwen3.6-27b-bf16-b200-maxctx-mtp2
MTP method: qwen3_next_mtp
num_speculative_tokens: 2
max_model_len: 262144
max_num_seqs: 512
max_num_batched_tokens: 16384
max_new_tokens: 30000
kv_cache_dtype: fp8
enable_prefix_caching: true
```

BF16 launch profile:

```text
config/launch-profiles/qwen3.6-27b-bf16.b200-maxctx-mtp2.on-demand.json
```

Remote Vast template created successfully:

```text
template name: vLLM_R2_Qwen3_6_27B_BF16_B200_MAXCTX_MTP2
template hash_id: bf09e015803afc4a955f352a915f621c
```

The launch profile has been updated with that hash.

## Commits created at end of session

The code/config/report changes from the benchmarking session were committed cleanly before this handoff file was added.

Recent relevant commits:

```text
e9201ab docs(bench): record B200 Carnice throughput results
a1be4cb chore(config): raise AWQ agentic output cap
dcf2657 feat(config): add B200 27B launch profiles
6ebf6b7 docs(metrics): add B200 burn-in reports
a07169b docs(vast): document storage policy and llama MTP workflows
451decc feat(bench): make saturation ramp self-reporting
9e420c0 feat(launch): add launch ledger and storage cost tracking
8ec2448 feat(metrics): add launch ledger and report generator
```

## Important constraints / safety

- This repo is public. Do not commit secrets, live instance JSON, private R2 overlay files, auth tokens, API keys, or PII.
- Use ignored env files only:

```text
env.vast-management
env.modeltransfer
```

- Prefer profile launcher and `--check-only` before launching.
- Avoid smoke scripts unless confirmed safe; some smoke paths can destroy failed instances.
- For live testing, use direct Vast mapped port and `/v1/models`, `/metrics`, and `vast.logs`.
- The previous B200 is gone; do not try to recycle/reboot it.

## Next session: launch BF16 on a fresh B200

First source Vast credentials:

```bash
. env.vast-management
```

Read-only offer check:

```bash
./run.sh scripts/select_and_launch.py \
  --launch-profile config/launch-profiles/qwen3.6-27b-bf16.b200-maxctx-mtp2.on-demand.json \
  --check-only \
  --top 3
```

If a suitable B200 appears, launch with guarded prompts:

```bash
./run.sh scripts/select_and_launch.py \
  --launch-profile config/launch-profiles/qwen3.6-27b-bf16.b200-maxctx-mtp2.on-demand.json
```

After launch, get the new instance id and current mapped `8000/tcp` port. Do not reuse old runtime endpoints.

## Readiness polling loop to use

User asked for a 30-second poll/react cadence. After launching a fresh instance, do this manually in separate tool calls with real 30s sleeps between calls, so exceptions can be acted on.

Preferred command per poll, because it already summarizes logs/readiness and does not destroy unless explicit destroy flags are added:

```bash
. env.vast-management
./run.sh scripts/monitor_instance_readiness.py <NEW_INSTANCE_ID> \
  --once \
  --tail 120 \
  --timeout 60
```

Optional direct `/v1/models` probe after the monitor command shows a mapped `vllm_api` URL:

```bash
curl -H "Authorization: Bearer $VLLM_API_KEY" http://<host>:<mapped_8000>/v1/models
```

Then wait 30 seconds between polls:

```bash
sleep 30
```

React to actionable exceptions before continuing.

Watch for expected BF16 startup markers:

```text
Provisioning model from R2
R2 source: s3://.../Qwen/Qwen3.6-27B
Target: /workspace/models/Qwen/Qwen3.6-27B
Syncing s3://...
served_model_name qwen3.6-27b-bf16-b200-maxctx-mtp2
SpeculativeConfig with qwen3_next_mtp / num_speculative_tokens=2
max_num_seqs=512
max_num_batched_tokens=16384
max_model_len=262144
kv_cache_dtype=fp8
```

Actionable failure patterns:

```text
missing .stream-manifest.json -> R2 upload/manifests issue; should not happen, upload completed
CUDA illegal memory access during graph capture -> consider lowering max_num_batched_tokens below 16384 or disabling graph capture if necessary
OOM / KV allocation failure -> reduce max_num_seqs from 512 or lower gpu_memory_utilization / max_model_len if needed
unsupported MTP method -> check vLLM version and Qwen MTP config; BF16 profile uses qwen3_next_mtp n=2
```

Do not destroy on errors without explicit approval.

## BF16 benchmark plan once ready

Use the same agentic shape that found Carnice's sweet spot, so comparisons are meaningful:

```text
shared_prefix=true
fixed_prefix_tokens=30000
warmup_turns=1
warmup_max_tokens=1
requests_per_concurrency=4
max_tokens=20000
max_model_len=262144
```

Start with lower concurrency because BF16 weights may reduce headroom versus NVFP4:

```text
c=24 first
then c=64 if clean
then c=96 only if c=64 has good KV/queue headroom
```

Example command after replacing instance id:

```bash
. env.vast-management
OPENAI_API_KEY="$VLLM_API_KEY" ./run.sh scripts/coding_agent_saturation_ramp.py \
  --instance-id <NEW_INSTANCE_ID> \
  --model qwen3.6-27b-bf16-b200-maxctx-mtp2 \
  --concurrency 24 \
  --requests-per-concurrency 4 \
  --warmup-turns 1 \
  --warmup-max-tokens 1 \
  --max-tokens 20000 \
  --shared-prefix \
  --fixed-prefix-tokens 30000 \
  --post-warmup-gap 2 \
  --max-model-len 262144 \
  --timeout 7200 \
  --step-gap 0
```

The benchmark script now rejects fixed `--base-url`; use `--instance-id` so Vast port remaps are handled.

## Known gotcha from this session

Attempting to update the already-stopped previous B200 to BF16 succeeded at the template field level, but recycle/reboot failed because the container was stopped/exited:

```text
update_instance(template_hash_id=bf09e015803afc4a955f352a915f621c) => success
recycle_instance => invalid_id, Is the container started?
reboot_instance => invalid_id, Is the container started?
```

This is not a BF16 template failure; it was a credit/stopped-instance issue.
