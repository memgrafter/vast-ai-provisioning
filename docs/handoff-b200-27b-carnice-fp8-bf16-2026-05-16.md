# Handoff: B200 27B Dense Testing — Carnice NVFP4, Qwen FP8, BF16 Stream

Date: 2026-05-16T06:25:45Z

## Do not release host

During this chat we intentionally retained the B200 rental. Do **not** destroy/release it unless explicitly asked. Use only in-place updates/recycles/reboots.

Current live instance at handoff time:

```text
instance_id: <terminated during session; do not reuse>
machine_id: <redacted>
gpu: B200 183GB
price: ~$3.9635/hr
public_ip: <redacted>
current label: carnice-v2-27b-nvfp4-b200-maxctx-mtp3
current external vLLM port seen most recently: <redacted>
```

Always re-read `show_instance(id=<instance_id>)` before using an endpoint because Vast port mappings change after recycle.

## Current live profile

Live profile after latest recycle:

```text
model: sakamakismile/Carnice-V2-27b-NVFP4-TEXT-MTP
served_model_name: carnice-v2-27b-nvfp4-text-mtp-b200-maxctx-mtp3
launch profile: config/launch-profiles/carnice-v2-27b-nvfp4-text-mtp.b200-maxctx-mtp3.on-demand.json
model profile: config/models/carnice-v2-27b-nvfp4-text-mtp.b200-maxctx-mtp3.json
template hash: 3569f66136dfc310494f47c733d164ad
```

Important settings:

```text
quantization: modelopt / NVFP4
speculative decoding: MTP n=3
max_model_len: 262144
kv_cache_dtype: fp8
enable_prefix_caching: true
max_num_seqs: 512
max_num_batched_tokens: 16384
max_new_tokens: 30000
gpu_memory_utilization: 0.9
language_model_only: true
tool_call_parser: qwen3_xml
reasoning_parser: qwen3
```

Why `max_num_batched_tokens=16384`: Qwen FP8 B200 crashed at 65536 during torch.compile/Triton autotune with CUDA illegal memory access. Carnice was set to 16384 preemptively.

Why `max_num_seqs=512`: this keeps server-side scheduler caps out of peak TPS sweeps. KV/store saturation should be handled separately by the service/control plane.

## Startup / readiness notes

Carnice with `max_num_seqs=512` started cleanly.

Log proof from latest startup:

```text
Using FlashInferCutlassNvFp4LinearKernel for NVFP4 GEMM
DeepGEMM E8M0 enabled
SpeculativeConfig(method='mtp', ..., num_spec_tokens=3)
Chunked prefill is enabled with max_num_batched_tokens=16384
max model len 262144
fp8 KV cache active
```

Startup overhead increased with `max_num_seqs=512`:

```text
torch.compile: ~62s
init engine / graph capture: ~180s
graph pool actual: ~1.16 GiB
```

No actionable exception after the final recycle. Cloudflare quick tunnel logs show HTTP 429s; ignore these for direct-port API tests.

## Qwen FP8 B200 result and crash note

Initial B200 quick reserve used Qwen/Qwen3.6-27B-FP8. Later updated in-place to max-context FP8/MTP2:

```text
model: Qwen/Qwen3.6-27B-FP8
profile: config/models/qwen3.6-27b-fp8.b200-maxctx-mtp2.json
launch: config/launch-profiles/qwen3.6-27b-fp8.b200-maxctx-mtp2.on-demand.json
MTP: n=2
max_model_len: 262144
fp8 KV
prefix caching enabled
```

At `max_num_batched_tokens=65536`, startup crashed:

```text
torch.AcceleratorError: CUDA error: an illegal memory access was encountered
RuntimeError: Engine core initialization failed
```

At `max_num_batched_tokens=16384`, startup succeeded.

Qwen FP8 warmed-prefix quick results:

```text
c=2:  generation_tps ~180 tok/s total
c=4:  generation_tps ~382 tok/s total
c=8:  generation_tps ~545 tok/s total
c=12: generation_tps ~798 tok/s total
```

This looked weak versus expectations and we pivoted to Carnice NVFP4.

## Benchmark harness changes

Modified `scripts/coding_agent_saturation_ramp.py` during session:

1. Added warmup phase before measured turns:

```text
--warmup-turns
--warmup-max-tokens
--post-warmup-gap
```

Default warmup avoids the previous thundering-herd cold-prefix bug.

2. Added measured output cap:

```text
--max-tokens
```

3. Replaced terse/concise prompt with a coding-heavy detailed implementation prompt to improve MTP acceptance and avoid very short stop completions.

4. Added TPS-only shared-prefix mode:

```text
--shared-prefix
--fixed-prefix-tokens <N>
```

Use shared-prefix mode only for **peak TPS**, not for KV-store residency tests. For KV-store tests, keep unique per-user prefixes.

## Apples-to-apples caution

Variables changed across the session:

```text
model: Qwen FP8 -> Carnice NVFP4
MTP: n=2 -> n=3
max_num_batched_tokens: 65536 -> 16384
max_num_seqs: 8 -> 36 -> 512
max_new_tokens: 20000 -> 30000 for future templates
prompt: concise -> coding-heavy detailed
prefix mode: unique -> shared-prefix TPS mode
output cap: 512 / 1024 / 2048 across runs
```

For future clean peak-TPS curve, freeze:

```text
model/profile: Carnice B200 current
max_num_seqs: 512
max_num_batched_tokens: 16384
shared_prefix: true
fixed_prefix_tokens: 60000
warmup_turns: 1
warmup_max_tokens: 1
requests_per_concurrency: 2
prompt: current coding-heavy prompt
```

Then vary only:

```text
concurrency
max_tokens if intentionally switching between peak probe and agentic test
```

## Carnice B200 results so far

### Early non-apples-to-apples / diagnostic results

With old profile `max_num_seqs=8`, c=12 queued and looked bad:

```text
c=12: ~396 tok/s total, max_running=8, max_waiting=4
```

This was not a fair peak test.

With `max_num_seqs=36`, unique prefixes, c=36:

```text
c=36: ~2022 tok/s total, ~56.2 tok/s/user, max_kv ~64.6%
```

Good enough to show B200 was not inherently weak, but not clean shared-prefix peak mode.

### Shared-prefix TPS mode results

Shared-prefix mode uses:

```text
--shared-prefix
--fixed-prefix-tokens 60000
--warmup-turns 1
--warmup-max-tokens 1
```

Results logged in `todo.txt` and session:

```text
c=2, max_tokens=2048:
  ~397 tok/s total
  ~198 tok/s/user
  no queueing
  ~2.6% KV
  MTP acceptance windows ~77-82%

c=24, max_tokens=2048:
  ~2528 tok/s total
  ~105 tok/s/user
  no meaningful queueing
  ~15% KV
  server best window ~3234 tok/s @ 24 running
  MTP acceptance best windows ~80-82%

c=128, max_tokens=1024:
  ~3782 tok/s total
  ~29.6 tok/s/user
  max_running=128
  max_waiting=12
  max_kv ~75.7%
  server windows: ~3899, ~3479, best ~5328 tok/s
  MTP acceptance main windows ~64-72%, tail ~77.7%

c=192, max_tokens=1024:
  ~3071 tok/s total
  ~16.0 tok/s/user
  max_running=178
  max_waiting=33
  max_kv ~99.9%
  queue_avg ~5.26s
  KV/scheduler saturated; worse than c=128
```

Interpretation:

```text
c=192 is past useful peak; KV hit 99.9% and aggregate dropped.
c=128 is current best measured aggregate under shared-prefix c=1024 test.
c=24 and c=2 show strong per-user TPS.
```

## Agentic test recommendation

User noted agentic max tokens should be more like 8000. That is a different lane than quick peak probes.

Recommended next agentic run:

```bash
. env.vast-management
OPENAI_API_KEY="$VLLM_API_KEY" ./run.sh scripts/coding_agent_saturation_ramp.py \
  --base-url http://<host>:<current_8000_port> \
  --model carnice-v2-27b-nvfp4-text-mtp-b200-maxctx-mtp3 \
  --concurrency 24 \
  --requests-per-concurrency 1 \
  --warmup-turns 1 \
  --warmup-max-tokens 1 \
  --max-tokens 8000 \
  --shared-prefix \
  --fixed-prefix-tokens 60000 \
  --post-warmup-gap 2 \
  --max-model-len 262144 \
  --timeout 3600 \
  --step-gap 0
```

Why c=24 first: c=128 with 8000 max output could request ~1M generated tokens and run much longer. c=24 requests up to ~192k generated tokens for one measured turn each, which is a reasonable sustained agentic probe.

## BF16 full-weight upload in progress

Started a background stream upload from HF to R2 with no local staging:

```text
HF repo: Qwen/Qwen3.6-27B
R2 prefix: Qwen/Qwen3.6-27B
profile: config/models/qwen3.6-27b-bf16.b200-maxctx-mtp2.json
launch profile: config/launch-profiles/qwen3.6-27b-bf16.b200-maxctx-mtp2.on-demand.json
repo size: ~55.6 GB
pidfile: state/stream-qwen3.6-27b-bf16.pid
log: state/stream-qwen3.6-27b-bf16.log
```

Check:

```bash
ps -p $(cat state/stream-qwen3.6-27b-bf16.pid) -o pid,stat,etime,command
tail -50 state/stream-qwen3.6-27b-bf16.log
```

At last check, upload was around `model-00007-of-00015.safetensors`.

The full Qwen repo contains `mtp.*` tensors in `model.safetensors.index.json`, so BF16 profile enables MTP n=2.

BF16 profile settings:

```text
model: Qwen/Qwen3.6-27B
dtype: bfloat16
MTP: n=2
max_model_len: 262144
kv_cache_dtype: fp8
prefix caching: true
max_num_batched_tokens: 16384
max_num_seqs: 32 initially
max_new_tokens: 30000
```

Do not launch BF16 until `.stream-manifest.json` exists in R2.

## Useful commands

Show live instance and current port:

```bash
. env.vast-management
.venv/bin/python - <<'PY'
from vastai import VastAI
import json
vast = VastAI()
INSTANCE_ID = 12345678  # replace with current instance id
inst = vast.show_instance(id=INSTANCE_ID)
print(json.dumps({k: inst.get(k) for k in ['id','actual_status','cur_state','label','template_hash_id','public_ipaddr','ports']}, indent=2, sort_keys=True, default=str))
PY
```

Models endpoint after extracting current 8000 HostPort:

```bash
curl -H "Authorization: Bearer $VLLM_API_KEY" http://<host>:<port>/v1/models
```

Summarize metrics:

```bash
./run.sh scripts/summarize_vllm_metrics.py --base-url http://<host>:<port>/v1
```

Fetch logs safely without smoke/destroy:

```bash
.venv/bin/python - <<'PY'
from vastai import VastAI
vast = VastAI()
INSTANCE_ID = 12345678  # replace with current instance id
print(vast.logs(instance_id=INSTANCE_ID, tail='200'))
PY
```

## Safety notes

- Do not use `smoke_chat_once.py` without checking destroy behavior/flags.
- Do not destroy/release current B200 unless user explicitly asks.
- Use `update_instance(... template_hash_id=...)` + `recycle_instance(...)` for in-place template changes.
- Cloudflare quick tunnel failures are not fatal for direct mapped port usage.
