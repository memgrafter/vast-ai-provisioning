# Qwen3.6 27B H200 / RTX PRO 6000 WS Generation TPS Report

Date: 2026-05-10 / 2026-05-11 UTC

## Summary

We benchmarked Qwen3.6 27B variants on Vast.ai H200 and RTX PRO 6000 WS instances using a coding-shaped workload with nonce-prefixed prompts, ~6.3k prompt tokens/request, 2048 generated tokens/request, and no prefix-cache hits.

Best H200 result was the official Qwen FP8 model with MTP/speculative decoding enabled:

```text
model: Qwen/Qwen3.6-27B-FP8
GPU: H200
concurrency: 5
generation_tps_total: 693.52 tok/s
wall-clock generation_tps_per_stream: 138.70 tok/s/stream
active-inference generation_tps_per_stream: 146.20 tok/s/stream
```

Best RTX PRO 6000 WS results so far:

```text
Carnice NVFP4 + MTP n=3:       169.96 tok/s total, ~84.98 tok/s/stream wall-clock
Official Qwen FP8 + MTP n=2:   172.90 tok/s total, ~86.45 tok/s/stream wall-clock
QuantTrio AWQ + MTP n=1:       131.64 tok/s total, ~65.82 tok/s/stream wall-clock
QuantTrio AWQ + MTP n=2:        37.41 tok/s total, ~18.70 tok/s/stream wall-clock
```

Key conclusion: MTP is highly model/kernel dependent. It was the major speedup for official FP8 on H200, gave useful but more modest speed on PRO 6000 WS FP8/NVFP4, and was not useful for the QuantTrio AWQ path on PRO 6000 WS.

## Test shape

Common workload shape:

```text
bench_input_tokens argument: 4500
actual prompt tokens/request: ~6,293-6,295
bench_output_tokens: 2048
prefix cache: no hits / disabled for benchmark
finish reason: length for fixed-output comparisons
```

Run durations/concurrency:

```text
H200 comparison runs:       concurrency 5, target 60s
PRO 6000 WS low-latency runs: concurrency 2, target 60-90s
Current smoke default:      --bench-seconds without a value means 90s
```

Command shape:

```bash
. env.vast-management
./run.sh scripts/smoke_chat_once.py \
  --launch-profile <launch-profile> \
  --launch-attempts 1 \
  --ready-timeout 3000 \
  --bench-seconds <60-or-90> \
  --bench-concurrency <2-or-5> \
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

## RTX PRO 6000 WS comparison

### Carnice-V2-27b-NVFP4-TEXT-MTP, MTP n=3

```text
model: carnice-v2-27b-nvfp4-text-mtp
source: sakamakismile/Carnice-V2-27b-NVFP4-TEXT-MTP
instance_id: 36509448
machine_id: 45824
gpu: RTX PRO 6000 WS
market: on-demand
max_model_len: 262144
max_num_seqs: 2
kv_cache_dtype: fp8
speculative_config: {"method":"qwen3_5_mtp","num_speculative_tokens":3}
requests_ok: 7
requests_error: 0
avg prompt/request: ~6,294.43 tokens
avg generation/request: ~1,533 tokens
```

Throughput:

```text
prompt_tps:       697.86 tok/s
generation_tps:   169.96 tok/s
total_tps:        867.83 tok/s
```

Per-stream generation at concurrency 2:

```text
wall-clock:       169.96 / 2 = 84.98 tok/s/stream
active inference: 1533 / 16.54 = ~92.68 tok/s/stream
```

Latency:

```text
avg TTFT:        2.50s
avg queue:       ~0.00s
avg inference:  16.54s
latency_avg:    17.76s
latency_p50:    19.86s
latency_p95:    29.29s
```

MTP was active:

```text
speculative_config=SpeculativeConfig(method='mtp', model='/workspace/models/sakamakismile/Carnice-V2-27b-NVFP4-TEXT-MTP', num_spec_tokens=3)
Resolved architecture: Qwen3_5MTP
Loading drafter model...
```

Speculative acceptance was strong for 3 predicted tokens:

```text
Mean acceptance length: ~3.29-3.46 / 4.0
Per-position acceptance: roughly 0.865-0.925, 0.759-0.818, 0.656-0.725
Avg draft acceptance: ~76.5-82.1%
```

This broadly matched the model card's expectation that `num_speculative_tokens=3` is useful on RTX PRO 6000 Blackwell.

### Official Qwen3.6-27B-FP8, MTP n=2 on RTX PRO 6000 WS

This was the missing data point from earlier notes. A prior official FP8 run at ~81 tok/s/stream was on H200 and did **not** have MTP enabled. The completed PRO 6000 WS FP8+MTP run is:

```text
model: qwen3.6-27b-fp8-pro6000ws
source: Qwen/Qwen3.6-27B-FP8
instance_id: 36510679
machine_id: 68497
gpu: RTX PRO 6000 WS
market: on-demand
max_model_len: 160000
max_num_seqs: 2
kv_cache_dtype: fp8
language_model_only: true
speculative_config: {"method":"qwen3_next_mtp","num_speculative_tokens":2}
bench_seconds: 90
concurrency: 2
requests_ok: 8
requests_error: 0
avg prompt/request: ~6,294.62 tokens
avg generation/request: 2048 tokens
```

Throughput:

```text
prompt_tps:       531.42 tok/s
generation_tps:   172.90 tok/s
total_tps:        704.32 tok/s
```

Per-stream generation at concurrency 2:

```text
wall-clock:       172.90 / 2 = 86.45 tok/s/stream
active inference: 2048 / 22.68 = ~90.30 tok/s/stream
```

Latency:

```text
avg TTFT:        2.44s
avg queue:       ~0.00s
avg inference:  22.68s
latency_avg:    23.67s
latency_p50:    23.00s
latency_p95:    26.66s
```

MTP was active:

```text
method `qwen3_next_mtp` is deprecated and replaced with mtp.
Resolved architecture: Qwen3_5MTP
speculative_config=SpeculativeConfig(method='mtp', model='/workspace/models/Qwen/Qwen3.6-27B-FP8', num_spec_tokens=2)
Loading drafter model...
```

Speculative acceptance:

```text
Mean acceptance length: ~2.58-2.70 / 3.0
Per-position acceptance: roughly 0.862-0.922, 0.710-0.783
Avg draft acceptance: ~79.1-85.1%
```

The first PRO 6000 WS FP8 launch attempt (`36510419`) was aborted/terminated before benchmark completion and should not be treated as a metric. The completed metric is `36510679` above.

### PRO 6000 WS takeaways

```text
AWQ old/no-MTP slices:       ~69-71 tok/s single-stream observed
AWQ MTP n=1:                ~65.82 tok/s/stream wall-clock at concurrency 2
AWQ MTP n=2:                ~18.70 tok/s/stream wall-clock at concurrency 2
Carnice NVFP4 MTP n=3:      ~84.98 tok/s/stream wall-clock at concurrency 2
Official FP8 MTP n=2:       ~86.45 tok/s/stream wall-clock at concurrency 2
```

For the PRO 6000 WS, official FP8+MTP n=2 and Carnice NVFP4+MTP n=3 landed close together on this coding-shaped benchmark. Both beat AWQ low-concurrency behavior; AWQ n=2 was a clear regression.

## RTX 5090 Carnice NVFP4 smoke

Prepared a 32GB RTX 5090-specific Carnice profile from the tested PRO 6000 WS NVFP4+MTP profile using copy-then-edit. The 5090 variant follows the model card's smaller-context recommendation rather than the full 256K PRO 6000 WS profile:

```text
model: carnice-v2-27b-nvfp4-text-mtp-rtx5090-16k
source: sakamakismile/Carnice-V2-27b-NVFP4-TEXT-MTP
gpu profile: config/gpu-profiles/carnice-v2-27b-nvfp4-mtp-rtx5090-1gpu.json
launch profile: config/launch-profiles/carnice-v2-27b-nvfp4-text-mtp.rtx5090.on-demand.json
template: vLLM_R2_Carnice_V2_27B_NVFP4_TEXT_MTP_RTX5090_16K
template_hash_id: 9c9da26e008eb4069ee25fc5f82751e3
max_model_len: 16384
gpu_memory_utilization: 0.85
kv_cache_dtype: unset
max_num_seqs: 2
force_quantization: modelopt
language_model_only: true
tool_call_parser: qwen3_xml
reasoning_parser: qwen3
speculative_config: {"method":"qwen3_5_mtp","num_speculative_tokens":3}
```

Vast search notes:

```text
require_verified: false
search_no_default: true
preferred_machine_ids includes 58434
greylisted_machine_ids includes 51352, 57883, 58555, 51471
min_inet_down: 1000 Mbps
provisioner R2 speed test: kept enabled at 100 MB/s minimum
```

The first unverified RTX 5090 host (`machine_id: 51352`) failed before provisioning because Docker/NVIDIA CDI could not inject the requested GPU device:

```text
failed to inject CDI devices: unresolvable CDI devices .../gpu=2
```

That was treated as a host/runtime issue and the machine was greylisted.

Geo-restricted search was then tried manually:

```text
US only: no passing offer
NA [CA,US]: no passing offer
Western Europe + JP: passing offer found
```

Completed 5090 smoke:

```text
instance_id: 36514355
machine_id: 58434
gpu: RTX 5090
geolocation: France, FR
market: on-demand
dph_total: $0.5211/hr
bench_seconds: 90
concurrency: 1
requests_ok: 4
requests_error: 0
avg prompt/request: ~6,295 tokens
avg generation/request: ~1,449 tokens
```

R2 speed test passed before model sync:

```text
minimum: 100 MB/s
object: _vast/r2-speed-test.bin, 536,870,912 bytes
range: first 512,000,000 bytes across 8 parallel ranged GETs
result: 512,000,000 bytes in 2s = 256.00 MB/s
```

Throughput:

```text
prompt_tps:      268.83 tok/s
generation_tps:   61.89 tok/s
total_tps:       330.72 tok/s
```

Per-stream generation at concurrency 1:

```text
wall-clock:       61.89 tok/s/stream
active inference: ~1,449.25 / 22.88 = ~63.34 tok/s/stream
```

Latency:

```text
avg TTFT:        9.34s
avg queue:       ~0.00s
avg inference:  22.88s
latency_avg:    23.41s
latency_p50:    20.43s
latency_p95:    49.62s
```

MTP was active:

```text
speculative_config=SpeculativeConfig(method='mtp', model='/workspace/models/sakamakismile/Carnice-V2-27b-NVFP4-TEXT-MTP', num_spec_tokens=3)
Resolved architecture: Qwen3_5MTP
Loading drafter model...
```

Speculative acceptance was good after warmup:

```text
Mean acceptance length: ~3.26-3.61 / 4.0
Per-position acceptance: roughly 0.894-0.936, 0.739-0.857, 0.626-0.814
Avg draft acceptance: ~75.3-86.9%
```

Interpretation: the 5090 can run the 16K Carnice NVFP4+MTP profile, but this first unverified/deverified host was materially slower than RTX PRO 6000 WS for the same family of workload. The high average TTFT was driven by one outlier; three of four requests had TTFT <= 2.5s.


## RTX 5060 Ti 2-GPU Carnice NVFP4 smoke

Prepared an experimental 2x RTX 5060 Ti profile for the same Carnice NVFP4 MTP path, using vLLM tensor parallelism across two 16GB GPUs:

```text
gpu profile: config/gpu-profiles/carnice-v2-27b-nvfp4-mtp-rtx5060ti-2gpu.json
model profile: config/models/carnice-v2-27b-nvfp4-text-mtp.rtx5060ti-2gpu-agentic-64k-turboquant-k8v4.json
launch profile: config/launch-profiles/carnice-v2-27b-nvfp4-text-mtp.rtx5060ti-2gpu.agentic-64k-turboquant-k8v4.on-demand.json
template: vLLM_R2_Carnice_V2_27B_NVFP4_TEXT_MTP_RTX5060TI_2GPU_AGENTIC_64K_TQ_K8V4
template_hash_id: 4ccabdd8a6e876fd2238127bf1cfd31e
initial requested max_model_len: 65536
initial requested kv_cache_dtype: turboquant_k8v4
tensor_parallel_size: 2
speculative_config: {"method":"qwen3_5_mtp","num_speculative_tokens":3}
```

Launched offer:

```text
instance_id: 36556709
machine_id: 102239
gpu: 2x RTX 5060 Ti 16GB
geolocation: Thailand, TH
market: on-demand
dph_total: $0.2811/hr
disk_bw: 5319 MB/s
inet_down/up: 766.8 / 519.6 Mbps
reliability2: 0.9518
```

Provisioning notes:

```text
R2 speed test: 512,000,000 bytes in 6s = 85.33 MB/s
R2_SPEED_TEST_WARN_ONLY=true allowed provisioning to continue below the 100 MB/s guard
model bytes present locally: 19,657,808,063 bytes across 11 files
```

The first vLLM startup failed because TurboQuant KV-cache compression is not supported for Qwen3 hybrid attention+Mamba models:

```text
NotImplementedError: TurboQuant KV cache is not supported for hybrid (attention + Mamba) models. Boundary layer protection requires uniform attention layers.
```

The live instance was manually patched for a fallback smoke by removing `--kv-cache-dtype turboquant_k8v4` and lowering context to 32K:

```text
max_model_len: 32768
kv_cache_dtype: unset
tensor_parallel_size: 2
force_quantization: modelopt
speculative_config: qwen3_5_mtp, num_speculative_tokens=3
```

The patched server started successfully with tensor parallelism and MTP:

```text
world_size=2 rank=0/1 backend=nccl
Custom allreduce disabled because GPU P2P capability or P2P test failed
Resolved architecture: Qwen3_5MTP
Loading drafter model...
GPU KV cache size: 26,400 tokens
Maximum concurrency for 32,768 tokens per request: 2.55x
Starting vLLM server on http://127.0.0.1:18000
```

Small benchmark, long-ish prompt, likely including remaining warmup overhead:

```text
input goal: 2000 words
max_output_tokens: 512
requests_ok: 1
latency: 65.37s
TTFT: 55.04s
prompt_tokens: 2,891
generation_tokens: 512
prompt_tps: 44.22 tok/s
generation_tps: 7.83 tok/s
total_tps: 52.06 tok/s
```

Warmer small benchmark:

```text
input goal: 500 words
max_output_tokens: 128
requests_ok: 3
latency_avg: 5.71s
TTFT_avg: 2.69s
prompt_tokens: 2,566
generation_tokens: 384
prompt_tps: 149.66 tok/s
generation_tps: 22.40 tok/s
total_tps: 172.06 tok/s
```

Interpretation: 2x RTX 5060 Ti can run Carnice NVFP4+MTP with tensor parallel at 32K after removing TurboQuant, but throughput is modest and GPU P2P/custom allreduce is unavailable on this host. TurboQuant should not be used for this Qwen3 hybrid family unless vLLM adds hybrid support. The instance was destroyed after the smoke/bench.

### Unsloth Qwen3.6-27B-NVFP4 on RTX 5090

The Unsloth NVFP4 checkpoint was also tested on RTX 5090 using the same R2/provisioning path. The baseline profile intentionally keeps the model-card vLLM guidance conservative (`dtype=bfloat16`, 16K context, no forced quantization). For speculative tests, temporary MTP variants used `qwen3_next_mtp` with `num_speculative_tokens` set to 2 and then 1.

A first 16K MTP2 attempt at `gpu_memory_utilization=0.85` failed during vLLM startup because the KV cache was too small:

```text
max seq len 16384 needs 1.56 GiB KV cache
available KV cache memory: 0.37 GiB
```

Raising `gpu_memory_utilization` to `0.95` allowed the 16K profile to start on RTX 5090:

```text
Available KV cache memory: ~3.49-3.50 GiB
GPU KV cache size: 12,800 tokens
```

#### Unsloth NVFP4, MTP n=2

```text
instance_id: 36519682
machine_id: 58434
gpu: RTX 5090
geolocation: France, FR
max_model_len: 16384
gpu_memory_utilization: 0.95
speculative_config: {"method":"qwen3_next_mtp","num_speculative_tokens":2}
bench_seconds: 90
concurrency: 1
requests_ok: 1
requests_error: 0
avg prompt/request: ~6,292 tokens
avg generation/request: 2,048 tokens
R2 speed test: 512 MB/s
```

Throughput:

```text
prompt_tps:       59.94 tok/s
generation_tps:  19.51 tok/s
total_tps:       79.45 tok/s
```

Latency:

```text
avg TTFT:        36.28s
avg queue:       ~0.00s
avg inference:  104.41s
latency_avg:    104.96s
```

MTP was active, but no draft tokens were accepted:

```text
speculative_config=SpeculativeConfig(method='mtp', model='/workspace/models/unsloth/Qwen3.6-27B-NVFP4', num_spec_tokens=2)
Resolved architecture: Qwen3_5MTP
Loading drafter model...
Mean acceptance length: 1.00
Per-position acceptance: 0.000, 0.000
Avg Draft acceptance rate: 0.0%
```

#### Unsloth NVFP4, MTP n=1

```text
instance_id: 36520226
machine_id: 58434
gpu: RTX 5090
geolocation: France, FR
max_model_len: 16384
gpu_memory_utilization: 0.95
speculative_config: {"method":"qwen3_next_mtp","num_speculative_tokens":1}
bench_seconds: 90
concurrency: 1
requests_ok: 2
requests_error: 0
avg prompt/request: ~6,293.5 tokens
avg generation/request: 2,048 tokens
R2 speed test: 256 MB/s
```

Throughput:

```text
prompt_tps:       96.63 tok/s
generation_tps:  31.44 tok/s
total_tps:       128.07 tok/s
```

Latency:

```text
avg TTFT:        1.33s
avg queue:       ~0.00s
avg inference:  64.62s
latency_avg:    65.12s
latency_p50:    64.39s
latency_p95:    65.86s
```

MTP was active, but again no draft tokens were accepted:

```text
speculative_config=SpeculativeConfig(method='mtp', model='/workspace/models/unsloth/Qwen3.6-27B-NVFP4', num_spec_tokens=1)
Resolved architecture: Qwen3_5MTP
Loading drafter model...
Mean acceptance length: 1.00
Per-position acceptance: 0.000
Avg Draft acceptance rate: 0.0%
```

#### RTX 5090 quant/speculative comparison

```text
Carnice NVFP4 MTP n=3:  generation_tps 61.89, active ~63.34 tok/s/stream, acceptance ~75.3-86.9%
Unsloth NVFP4 MTP n=1: generation_tps 31.44, active ~31.70 tok/s/stream, acceptance 0.0%
Unsloth NVFP4 MTP n=2: generation_tps 19.51, active ~19.62 tok/s/stream, acceptance 0.0%
```

Answer: yes, the RTX 5090 worked well enough with the other quantized speculative path: Carnice NVFP4 + MTP n=3. It was roughly `2.0x` the Unsloth MTP n=1 generation throughput and `3.2x` the Unsloth MTP n=2 throughput in these single-stream smoke runs, with strong draft-token acceptance instead of zero acceptance. The Unsloth MTP variants start at 16K only with high GPU memory utilization and do not appear useful with `qwen3_next_mtp` on this setup.

Bad/unstable RTX 5090 hosts encountered while reaching these results:

```text
51352: Docker/NVIDIA CDI injection failure
57883: Docker/NVIDIA CDI injection failure
58555: stuck/failed before usable startup, CN geolocation
51471: deverified host failure
```

Machine `58434` is the known-good RTX 5090 host for both Carnice and Unsloth smoke tests and is now preferred in the RTX 5090 launch profiles when rentable.

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

Added PRO 6000 WS FP8 profile/launch profile for lower-concurrency testing:

```text
config/models/qwen3.6-27b-fp8.pro6000ws.json
config/launch-profiles/qwen3.6-27b-fp8.pro6000ws.on-demand.json
```

Key PRO 6000 WS differences:

```json
{
  "max_num_seqs": 2,
  "kv_cache_dtype": "fp8",
  "language_model_only": true,
  "speculative_config": {
    "method": "qwen3_next_mtp",
    "num_speculative_tokens": 2
  }
}
```

Current H200 remote template:

```text
template_name: vLLM_R2_Qwen3_6_27B_FP8
template_hash_id: 04078a21dd50fc1ab56b46d453383f20
```

Current PRO 6000 WS FP8 remote template:

```text
template_name: vLLM_R2_Qwen3_6_27B_FP8_PRO6000WS
template_hash_id: 910465ed31fbab3ab1d72d828cde7ec4
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

`smoke_chat_once.py` now accepts `--bench-seconds` without a value; that uses a 90s bench default for a little more statistical signal while keeping rental time modest.

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

## Additional R2 transfers

Carnice NVFP4 transfer completed:

```text
HF repo: sakamakismile/Carnice-V2-27b-NVFP4-TEXT-MTP
R2 prefix: sakamakismile/Carnice-V2-27b-NVFP4-TEXT-MTP
objects: 11
size: 19,657,808,063 bytes including .stream-manifest.json
model file: model.safetensors, 19,637,775,848 bytes
manifest: present
```

Unsloth NVFP4 transfer is in progress:

```text
HF repo: unsloth/Qwen3.6-27B-NVFP4
R2 prefix: unsloth/Qwen3.6-27B-NVFP4
HF revision: 6db17837b1c03a197fb45cef806e0c2a612c3aa7
HF repo size: ~25.55 GB
current state: streaming single 25.53 GB model.safetensors object
manifest: not present yet
visible R2 objects: small metadata files only until model.safetensors commits
```

Check command:

```bash
pid=$(cat state/stream-unsloth-qwen3.6-27b-nvfp4.pid)
ps -p "$pid" -o pid,stat,etime,command
source env.modeltransfer
.venv/bin/aws s3 ls "s3://$R2_BUCKET/unsloth/Qwen3.6-27B-NVFP4/.stream-manifest.json" --endpoint-url "$R2_ENDPOINT"
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
instances/36508333.final.json
instances/36508333.final.logs.tail5000.txt
instances/36509448.final.json
instances/36509448.final.logs.tail5000.txt
instances/36510679.final.json
instances/36510679.final.logs.tail5000.txt
```

Main commits containing FP8/MTP/profile/report work:

```text
69aa453 feat(vast): add qwen fp8 mtp h200 profile
65ca529 feat(vast): add carnice nvfp4 mtp profile
80fe157 chore(bench): test awq mtp two-token draft
985d25b docs(bench): record awq mtp two-token smoke
db12948 feat(bench): add fp8 pro6000ws smoke profile
```

## Cleanup status

After the latest completed PRO 6000 WS FP8+MTP run, the instance was destroyed successfully and Vast returned no active instances:

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

A follow-up on-demand smoke tried the official Qwen3.6-27B-card setting `num_speculative_tokens=2` for the same AWQ profile:

```text
instance_id: 36508333
market: on-demand
machine_id: 44351
gpu: RTX PRO 6000 WS
concurrency: 2
avg prompt/request: ~6,294 tokens
avg generation/request: ~2,048 tokens
requests_ok: 2
requests_error: 0
vllm_generation_tps: 37.41 tok/s total
wall-clock per stream: 18.70 tok/s/stream
active inference per stream: ~25.11 tok/s/stream
avg TTFT: 61.92s
avg queue: ~0.00s
avg inference: 81.57s
```

MTP was active:

```text
speculative_config=SpeculativeConfig(method='mtp', model='/workspace/models/QuantTrio/Qwen3.6-27B-AWQ', num_spec_tokens=2)
Resolved architecture: Qwen3_5MTP
```

Acceptance was still decent, but vLLM warned that recursive use of one MTP layer can reduce acceptance, and total throughput collapsed:

```text
Enabling num_speculative_tokens > 1 will run multiple times of forward on same MTP layer, which may result in lower acceptance rate
Mean acceptance length: ~2.49-2.86 / 3.0
Per-position acceptance rate: roughly 0.83-0.95, 0.65-0.90
Avg draft acceptance rate: ~74-93%
```

Interpretation: on RTX PRO 6000 WS with this AWQ/modelopt path, the extra drafter work appears to offset or exceed the benefit. For this AWQ model on PRO 6000 WS, MTP is probably not worth enabling; `num_speculative_tokens=2` is clearly worse than the prior `num_speculative_tokens=1` smoke. This contrasts with official FP8 on H200, where MTP gave a large gain.

Likely reason: for speculative decoding to help, the saved target-model forward passes must exceed the extra drafter/speculation overhead. On this AWQ + PRO 6000 WS path, that trade appears to lose. The target AWQ decode may already be efficient enough, or bottlenecked differently enough, that recursive MTP does not save much wall-clock time. Meanwhile `num_speculative_tokens=2` makes vLLM run multiple recursive forwards through the single MTP layer, adding overhead and reducing second-position acceptance. The logged accepted/drafted throughput looked reasonable in isolation, but final user-visible generation throughput fell to only `37.41 tok/s` total at concurrency 2.

Working rule after these runs:

```text
AWQ on PRO 6000 WS: MTP off or n=1 max; n=2 is a bad tradeoff
Official FP8 on H200: n=2 works very well per Qwen card
Official FP8 on PRO 6000 WS: n=2 works, but lands around mid-80s tok/s/stream at concurrency 2
Carnice/modelopt NVFP4 on PRO 6000 WS: n=3 works and lands around mid-80s tok/s/stream at concurrency 2
```

## Takeaways

1. H200 was not suspiciously slow when tested at 5 concurrent streams; the earlier 48-way burst created a thundering-herd effect.
2. FP8 alone improved H200 generation TPS modestly over AWQ.
3. MTP/speculative decoding provided the large win on H200 FP8, lifting per-stream generation from ~81 tok/s to ~139 tok/s wall-clock.
4. On RTX PRO 6000 WS, official FP8+MTP n=2 and Carnice NVFP4+MTP n=3 both landed around mid-80s tok/s/stream on the coding-shaped concurrency-2 workload.
5. AWQ MTP on RTX PRO 6000 WS did not beat older non-MTP PRO 6000 WS observations; AWQ n=2 was much worse. Good acceptance length alone does not guarantee speedup.
6. For future Qwen3.6 MTP runs, verify logs contain `SpeculativeConfig(method='mtp'...)`; the presence of `mtp.*` weights alone is not enough.
7. Keep recording full rental metadata and hardware/runtime telemetry to make future GPU/provider comparisons auditable.
