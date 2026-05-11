# Qwen3.6 27B H200 Generation TPS Report

Date: 2026-05-10 / 2026-05-11 UTC

## Summary

We benchmarked Qwen3.6 27B variants on a Vast.ai H200 instance using a coding-shaped workload with 5 concurrent streams, ~6.3k prompt tokens/request, and 2048 generated tokens/request.

Best result was the official Qwen FP8 model with MTP/speculative decoding enabled:

```text
model: Qwen/Qwen3.6-27B-FP8
GPU: H200
concurrency: 5
generation_tps_total: 693.52 tok/s
wall-clock generation_tps_per_stream: 138.70 tok/s/stream
active-inference generation_tps_per_stream: 146.20 tok/s/stream
```

Compared with the earlier AWQ run:

```text
AWQ:     ~74.20 tok/s/stream wall-clock
FP8:     ~81.33 tok/s/stream wall-clock
FP8+MTP: ~138.70 tok/s/stream wall-clock
```

MTP was the major speedup.

## Test shape

Common workload shape:

```text
bench_concurrency: 5
bench_seconds: 60
bench_input_tokens argument: 4500
actual prompt tokens/request: ~6,293-6,295
bench_output_tokens: 2048
prefix cache: no hits / disabled for benchmark
finish reason: length
```

Command shape:

```bash
. env.vast-management
./run.sh scripts/smoke_chat_once.py \
  --launch-profile <launch-profile> \
  --launch-attempts 1 \
  --ready-timeout 3000 \
  --bench-seconds 60 \
  --bench-concurrency 5 \
  --bench-input-tokens 4500 \
  --bench-output-tokens 2048 \
  --no-destroy-on-error
```

## Results

### 1. Qwen3.6 27B AWQ baseline

```text
model: qwen3.6-27b-awq
instance_id: 36497799
machine_id: 74712
gpu: H200
max_model_len: 160000
requests_ok: 15
requests_error: 0
avg prompt/request: ~6,294.6 tokens
avg generation/request: 2048 tokens
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

### 2. Qwen3.6 27B FP8, MTP weights present but not enabled

```text
model: qwen3.6-27b-fp8
instance_id: 36501118
machine_id: 74712
gpu: H200
max_model_len: 160000
requests_ok: 15
requests_error: 0
avg prompt/request: ~6,294 tokens
avg generation/request: 2048 tokens
```

Throughput:

```text
prompt_tps:     1,249.77 tok/s
generation_tps:   406.64 tok/s
total_tps:      1,656.40 tok/s
```

Per-stream generation:

```text
wall-clock:       406.64 / 5 = 81.33 tok/s/stream
active inference: 2048 / 24.21 = 84.59 tok/s/stream
```

Startup log showed MTP was **not** active:

```text
speculative_config=None
```

The repo did contain:

```text
mtp.safetensors
```

but vLLM did not use it automatically.

### 3. Qwen3.6 27B FP8 with MTP/speculative decoding enabled

```text
model: qwen3.6-27b-fp8
instance_id: 36502498
machine_id: 74712
gpu: H200
max_model_len: 160000
requests_ok: 25
requests_error: 0
avg prompt/request: ~6,294.12 tokens
avg generation/request: 2048 tokens
```

Throughput:

```text
prompt_tps:     2,131.38 tok/s
generation_tps:   693.52 tok/s
total_tps:      2,824.90 tok/s
```

Per-stream generation:

```text
wall-clock:       693.52 / 5 = 138.70 tok/s/stream
active inference: 2048 / 14.01 = 146.20 tok/s/stream
```

Latency:

```text
avg latency:    14.70s
p50 latency:    14.24s
p95 latency:    17.05s
avg TTFT:        1.60s
avg queue:       0.20s
avg inference:  14.01s
```

Log proof MTP was enabled:

```text
speculative_config=SpeculativeConfig(method='mtp', model='/workspace/models/Qwen/Qwen3.6-27B-FP8', num_spec_tokens=2)
Resolved architecture: Qwen3_5MTP
Loading drafter model...
Detected MTP model. Sharing target model embedding weights with the draft model.
Detected MTP model. Sharing target model lm_head weights with the draft model.
```

Speculative decoding runtime metrics showed acceptance rates around 80-84%:

```text
Mean acceptance length: ~2.60-2.68
Per-position acceptance rate: ~0.88-0.91, ~0.72-0.77
Avg Draft acceptance rate: ~79.8%-83.8%
```

## Relative comparisons

### FP8 non-MTP vs AWQ

```text
AWQ generation_tps_total:      370.98
FP8 generation_tps_total:      406.64
improvement:                  +9.6%
```

Wall-clock per stream:

```text
AWQ: 74.20 tok/s/stream
FP8: 81.33 tok/s/stream
```

### FP8+MTP vs FP8 non-MTP

```text
FP8 non-MTP generation_tps_total: 406.64
FP8+MTP generation_tps_total:     693.52
improvement:                     +70.6%
```

Wall-clock per stream:

```text
FP8 non-MTP: 81.33 tok/s/stream
FP8+MTP:    138.70 tok/s/stream
```

### FP8+MTP vs AWQ

```text
AWQ generation_tps_total:      370.98
FP8+MTP generation_tps_total:  693.52
improvement:                  +86.9%
```

Wall-clock per stream:

```text
AWQ:      74.20 tok/s/stream
FP8+MTP: 138.70 tok/s/stream
```

## HF model-card guidance used

The Qwen model card recommends vLLM MTP with:

```bash
--reasoning-parser qwen3 \
--speculative-config '{"method":"qwen3_next_mtp","num_speculative_tokens":2}'
```

During startup, vLLM warned:

```text
method `qwen3_next_mtp` is deprecated and replaced with mtp.
```

vLLM still resolved and enabled MTP correctly.

## Implementation details

Added official FP8 model profile:

```text
config/models/qwen3.6-27b-fp8.json
```

Important vLLM fields:

```json
{
  "dtype": "auto",
  "max_model_len": 160000,
  "gpu_memory_utilization": 0.9,
  "max_num_seqs": 64,
  "reasoning_parser": "qwen3",
  "speculative_config": {
    "method": "qwen3_next_mtp",
    "num_speculative_tokens": 2
  }
}
```

Added H200 launch profiles:

```text
config/launch-profiles/qwen3.6-27b-fp8.h200.ondemand.json
config/launch-profiles/qwen3.6-27b-fp8.h200.interruptible.json
```

Current remote template:

```text
template_name: vLLM_R2_Qwen3_6_27B_FP8
template_hash_id: 04078a21dd50fc1ab56b46d453383f20
```

Speculative config is passed via base64 env to avoid Vast/Docker env quoting issues:

```text
VLLM_SPECULATIVE_CONFIG_B64=eyJtZXRob2QiOiJxd2VuM19uZXh0X210cCIsIm51bV9zcGVjdWxhdGl2ZV90b2tlbnMiOjJ9
```

The provisioner decodes it into:

```bash
--speculative-config '{"method":"qwen3_next_mtp","num_speculative_tokens":2}'
```

This was necessary because passing JSON through `VLLM_EXTRA_ARGS` did not survive as intended on Vast; the first post-change run still showed:

```text
speculative_config=None
```

## R2 transfer

Official model was streamed from Hugging Face to R2 without staging full model files locally.

```text
HF repo: Qwen/Qwen3.6-27B-FP8
R2 prefix: Qwen/Qwen3.6-27B-FP8
objects: 81
size: ~30.89 GB
manifest: Qwen/Qwen3.6-27B-FP8/.stream-manifest.json
```

Uploader command:

```bash
source env.modeltransfer
./transfer_model_to_R2.sh \
  --model-profile config/models/qwen3.6-27b-fp8.json \
  --stream
```

## Artifacts

Saved final instance debug:

```text
instances/36497799.final.json
instances/36497799.final.logs.tail5000.txt
instances/36501118.final.json
instances/36501118.final.logs.tail5000.txt
instances/36502498.final.json
instances/36502498.final.logs.tail5000.txt
```

Main commit containing FP8/MTP profile and streaming support:

```text
69aa453 feat(vast): add qwen fp8 mtp h200 profile
```

## Cleanup status

After the MTP run, the instance was destroyed successfully and Vast returned no active instances:

```json
[]
```

## PRO 6000 WS AWQ MTP follow-up

We later checked whether the local AWQ model preserved MTP. It did: `models/QuantTrio/Qwen3.6-27B-AWQ/model.safetensors.index.json` maps 15 `mtp.*` tensors into `model-00008-of-00008.safetensors`, and `config.json` includes:

```json
"mtp_num_hidden_layers": 1,
"mtp_use_dedicated_embeddings": false
```

We enabled MTP for the AWQ coding profile on RTX PRO 6000 WS using the repo-card recommendation of `num_speculative_tokens=1` and `max_num_seqs=32`.

MTP was active in logs:

```text
speculative_config=SpeculativeConfig(method='mtp', model='/workspace/models/QuantTrio/Qwen3.6-27B-AWQ', num_spec_tokens=1)
Resolved architecture: Qwen3_5MTP
Detected MTP model. Sharing target model embedding weights with the draft model.
```

But it did **not** show a material speedup versus the older non-MTP PRO 6000 WS observations.

Older non-MTP PRO 6000 WS meter slices from the session history:

```text
requests running: 1
generation_delta: 737 tokens over 10.68s
generation_tps: 69.01 tok/s
```

```text
requests running: 1
generation_delta: 189 tokens over 2.66s
generation_tps: 71.09 tok/s
```

Current AWQ+MTP PRO 6000 WS smoke runs:

```text
concurrency: 2
generation_tps: 131.64 tok/s total
wall-clock per stream: 65.82 tok/s/stream
active inference per stream: 68.42 tok/s/stream
```

```text
concurrency: 5
generation_tps: 286.46 tok/s total
wall-clock per stream: 57.29 tok/s/stream
active inference per stream: 63.35 tok/s/stream
```

Speculative acceptance itself looked good for `num_speculative_tokens=1`:

```text
mean acceptance length: ~1.86-1.99 / 2.0
draft acceptance: ~86-99%
```

Interpretation: on RTX PRO 6000 WS with this AWQ/modelopt path, the extra drafter work appears to offset the benefit. For this AWQ model on PRO 6000 WS, MTP is probably not worth enabling unless a longer, controlled benchmark proves otherwise. This contrasts with official FP8 on H200, where MTP gave a large gain.

## Takeaways

1. H200 was not suspiciously slow when tested at 5 concurrent streams; the earlier 48-way burst created a thundering-herd effect.
2. FP8 alone improved generation TPS modestly over AWQ.
3. MTP/speculative decoding provided the large win on H200 FP8, lifting per-stream generation from ~81 tok/s to ~139 tok/s wall-clock.
4. AWQ MTP on RTX PRO 6000 WS did not beat older non-MTP PRO 6000 WS observations; good acceptance length alone does not guarantee speedup.
5. For future Qwen3.6 MTP runs, verify logs contain `SpeculativeConfig(method='mtp'...)`; the presence of `mtp.*` weights alone is not enough.
6. Keep recording full rental metadata and hardware/runtime telemetry to make future GPU/provider comparisons auditable.
