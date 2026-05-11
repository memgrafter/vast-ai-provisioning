# Handoff: 2x Consumer GPU Long-Context Vast.ai Follow-up

Date: 2026-05-11 UTC

## Current state

No active Vast instances remain.

```json
[]
```

Main report is up to date:

```text
docs/qwen3.6-27b-h200-generation-tps-report.md
```

Most relevant recent commits:

```text
1134ec9 feat(provision): emit r2 sync progress lines
26c111d docs(bench): add rtx5070ti two-gpu fp8kv smoke
81d9b42 docs(bench): add rtx5070ti mtp acceptance metrics
61b8b83 feat(vast): add carnice rtx5070ti 2gpu fp8kv profile
f3255f9 feat(vast): add rtx5070ti fp8kv no-mtp profile
532e6b7 docs(bench): add rtx5070ti no-mtp comparison
aebc2be feat(vast): add qwen awq rtx3090 2gpu fp8kv profile
563b875 chore(vast): record rtx3090 awq template hash
```

## Important findings from this session

### 1) TurboQuant is not usable for this Qwen3 hybrid family

Carnice/Qwen3 hybrid attention+Mamba models failed with:

```text
NotImplementedError: TurboQuant KV cache is not supported for hybrid (attention + Mamba) models.
```

Interpretation:

```text
Do not use --kv-cache-dtype turboquant_* for Carnice/Qwen3 hybrid attention+Mamba paths.
Use fp8 KV or no KV compression instead.
```

### 2) R2 speed-test warn-only mode now exists

Provisioner now supports running the speed test without aborting the instance when below threshold:

```text
R2_SPEED_TEST_WARN_ONLY=true
```

This still logs measured throughput and continues provisioning.

### 3) Provisioning now emits visible R2 sync progress lines

New log lines look like:

```text
R2 sync progress: <bytes> bytes across <files> files at <MODEL_DIR>; largest=<size file>
```

This was added because `rclone --stats-one-line` was too opaque in Vast log tails.

## 2x RTX 5060 Ti result

Prepared profile/template:

```text
gpu profile: config/gpu-profiles/carnice-v2-27b-nvfp4-mtp-rtx5060ti-2gpu.json
model profile: config/models/carnice-v2-27b-nvfp4-text-mtp.rtx5060ti-2gpu-agentic-64k-turboquant-k8v4.json
launch profile: config/launch-profiles/carnice-v2-27b-nvfp4-text-mtp.rtx5060ti-2gpu.agentic-64k-turboquant-k8v4.on-demand.json
template hash: 4ccabdd8a6e876fd2238127bf1cfd31e
```

Observed behavior:

```text
- initial TurboQuant launch failed due to hybrid-model unsupported path
- live instance was manually patched to remove TurboQuant and reduce context to 32K
- tensor_parallel_size=2 worked
- MTP stayed on
```

Warm small-bench result after manual patch:

```text
generation_tps: 22.40 tok/s
TTFT_avg: 2.69s
latency_avg: 5.71s
```

Limitation:

```text
Acceptance metrics for the patched 5060 Ti run were not preserved before destroy.
```

## 2x RTX 5070 Ti fp8-KV result

Prepared MTP profile/template:

```text
gpu profile: config/gpu-profiles/carnice-v2-27b-nvfp4-mtp-rtx5070ti-2gpu.json
model profile: config/models/carnice-v2-27b-nvfp4-text-mtp.rtx5070ti-2gpu-agentic-64k-fp8kv.json
launch profile: config/launch-profiles/carnice-v2-27b-nvfp4-text-mtp.rtx5070ti-2gpu.agentic-64k-fp8kv.on-demand.json
template hash: 3352812354abb822f6fbcd6b9d6547ee
preferred machine_id: 28069
```

MTP-on small-bench result:

```text
generation_tps: 32.06 tok/s
TTFT_avg: 1.02s
latency_avg: 3.99s
```

MTP acceptance metrics were preserved:

```text
Mean acceptance length: 3.52 / 4.0
Per-position acceptance: 0.920, 0.840, 0.760
Avg draft acceptance: 84.0%

Mean acceptance length: 3.28 / 4.0
Per-position acceptance: 0.915, 0.746, 0.623
Avg draft acceptance: 76.2%
```

### 2x RTX 5070 Ti no-MTP A/B

Prepared no-MTP comparator:

```text
model profile: config/models/carnice-v2-27b-nvfp4-text-mtp.rtx5070ti-2gpu-agentic-64k-fp8kv-no-mtp.json
launch profile: config/launch-profiles/carnice-v2-27b-nvfp4-text-mtp.rtx5070ti-2gpu.agentic-64k-fp8kv-no-mtp.on-demand.json
template hash: e6235ab0b6f42ff02426b35ec94901a3
```

No-MTP result on the same preferred machine:

```text
generation_tps: 36.93 tok/s
TTFT_avg: 0.80s
latency_avg: 3.47s
```

A/B conclusion for this small concurrency-1 workload:

```text
No-MTP beat MTP on 2x RTX 5070 Ti despite decent draft acceptance.
Approx lift: ~15.2% generation TPS.
```

Interpretation:

```text
For this budget 2x 5070 Ti path, default to no MTP unless a different workload
(longer outputs / higher concurrency) reverses the result.
```

## 2x RTX 3090 160K result

Prepared AWQ + fp8-KV + no-MTP 160K single-user profile:

```text
gpu profile: config/gpu-profiles/qwen-27b-awq-rtx3090-2gpu.json
model profile: config/models/qwen3.6-27b-awq.rtx3090-2gpu-160k-fp8kv-no-mtp.json
launch profile: config/launch-profiles/qwen3.6-27b-awq.rtx3090-2gpu-160k-fp8kv-no-mtp.on-demand.json
template hash: 7ef02c850d306d43ccdad8a38918889f
```

Target settings:

```text
Qwen3.6-27B-AWQ
max_model_len: 160000
kv_cache_dtype: fp8
tensor_parallel_size: 2
max_num_seqs: 1
speculative_config: None
```

Strict profile (`reliability2 >= 0.98`) found no passing 2x3090 offers. A temporary relaxed state profile (`reliability2 >= 0.94`) was used:

```text
state/launch-profiles/qwen3.6-27b-awq.rtx3090-2gpu-160k-fp8kv-no-mtp.rel094.on-demand.json
```

Launched and tested:

```text
instance_id: 36564163
offer_id: 36354557
machine_id: 104433
geo: Quebec, CA
gpu: 2x RTX 3090
reliability2: 0.9488
inet_down: 827 Mbps
disk_bw: 1660 MB/s
dph_total: $0.2643/hr
```

Provisioning/startup details:

```text
R2 speed test: 85.33 MB/s, below 100 MB/s threshold but warn-only continued
speculative_config=None
max_seq_len=160000
tensor_parallel_size=2
Using fp8 data type to store kv cache
Available KV cache memory: 10.65 GiB
GPU KV cache size: 174,048 tokens
Maximum concurrency for 160,000 tokens per request: 4.08x
```

Small smoke result:

```text
requests_ok: 2
requests_error: 0
latency_avg: 16.28s
TTFT_avg: 1.61s
prompt_tokens: 1,707
generation_tokens: 256
prompt_tps: 52.41 tok/s
generation_tps: 7.86 tok/s
total_tps: 60.27 tok/s
```

Instance was destroyed after the bench.

### 2x RTX 3090 MTP1 follow-up

Prepared and tested AWQ + fp8-KV + MTP n=1 at the same 160K target:

```text
model profile: config/models/qwen3.6-27b-awq.rtx3090-2gpu-160k-fp8kv-mtp1.json
launch profile: config/launch-profiles/qwen3.6-27b-awq.rtx3090-2gpu-160k-fp8kv-mtp1.on-demand.json
template hash: 24aa18d263b9754cbdf114107761f78e
speculative_config: {"method":"qwen3_next_mtp","num_speculative_tokens":1}
```

Launched and tested on the same relaxed-policy host:

```text
instance_id: 36565384
offer_id: 36354557
machine_id: 104433
gpu: 2x RTX 3090
reliability2: 0.9493
dph_total: $0.2643/hr
```

Startup details:

```text
R2 speed test: 73.14 MB/s, below 100 MB/s threshold but warn-only continued
Resolved architecture: Qwen3_5MTP
speculative_config=SpeculativeConfig(method='mtp', model='/workspace/models/QuantTrio/Qwen3.6-27B-AWQ', num_spec_tokens=1)
max_seq_len=160000
tensor_parallel_size=2
Available KV cache memory: 10.2 GiB
GPU KV cache size: 156,816 tokens
Maximum concurrency for 160,000 tokens per request: 3.58x
```

Small smoke result:

```text
requests_ok: 2
requests_error: 0
latency_avg: 10.87s
TTFT_avg: 1.86s
prompt_tokens: 1,711
generation_tokens: 256
prompt_tps: 78.67 tok/s
generation_tps: 11.77 tok/s
total_tps: 90.44 tok/s
```

Acceptance:

```text
Mean acceptance length: 2.00
Per-position acceptance rate: 1.000
Avg Draft acceptance rate: 100.0%
```

A/B against no-MTP on same machine:

```text
No MTP: generation_tps 7.86, TTFT_avg 1.61s, latency_avg 16.28s
MTP1:   generation_tps 11.77, TTFT_avg 1.86s, latency_avg 10.87s
```

Instance was destroyed after the bench.

### 2x RTX 3090 AWQ Marlin correction and rerun

The 2x3090 AWQ profiles were corrected to force `awq_marlin` instead of `awq`:

```text
commit: 868282e fix(vast): use awq marlin for rtx3090 awq profiles
no-MTP template hash: a999f39227dda433fa51a03cdfd41b62
MTP1 template hash: dc06729e41a32b77a02ce1f9962eae29
```

Reran MTP1 on the same relaxed-policy host:

```text
instance_id: 36567774
machine_id: 104433
gpu: 2x RTX 3090
force_quantization: awq_marlin
max_model_len: 160000
```

Startup proof:

```text
Using MarlinLinearKernel for AWQMarlinLinearMethod
Resolved architecture: Qwen3_5MTP
SpeculativeConfig(method='mtp', num_spec_tokens=1)
world_size=2
TP rank 0 / TP rank 1
GPU KV cache size: 159,984 tokens
Maximum concurrency for 160,000 tokens per request: 3.66x
```

Small smoke result:

```text
requests_ok: 6
requests_error: 0
latency_avg: 3.54s
TTFT_avg: 1.24s
prompt_tps: 241.71 tok/s
generation_tps: 36.19 tok/s
total_tps: 277.90 tok/s
Avg Draft acceptance rate: 100.0%
```

Progression on same host class:

```text
forced awq, no MTP: 7.86 gen tok/s
forced awq, MTP1:   11.77 gen tok/s
awq_marlin, MTP1:   36.19 gen tok/s
```

The host remained PCIe-only:

```text
has_nvlink: false
bw_nvlink: 0.0
pci_gen: 3.0
pcie_bw: 12.7 GB/s
```

Instance was destroyed after the bench.

### 2x RTX 3090 AWQ Marlin MTP2 256K context-fill

Prepared and tested a 256K-context MTP2 variant:

```text
model profile: config/models/qwen3.6-27b-awq.rtx3090-2gpu-256k-fp8kv-mtp2.json
launch profile: config/launch-profiles/qwen3.6-27b-awq.rtx3090-2gpu-256k-fp8kv-mtp2.on-demand.json
template hash: cfd71b81b178c7a9473e127adf390ead
max_model_len: 262144
force_quantization: awq_marlin
kv_cache_dtype: fp8
speculative_config: {"method":"qwen3_next_mtp","num_speculative_tokens":2}
```

Launched host:

```text
instance_id: 36569197
machine_id: 95152
gpu: 2x RTX 3090
geolocation: Estonia, EE
dph_total: $0.5667/hr
has_nvlink: false
topology: NODE
```

Startup proof:

```text
Resolved architecture: Qwen3_5MTP
SpeculativeConfig(method='mtp', num_spec_tokens=2)
Using MarlinLinearKernel for AWQMarlinLinearMethod
max_seq_len=262144
GPU KV cache size: 160,000 tokens
Maximum concurrency for 262,144 tokens per request: 2.28x
```

Tokenizer bisection for `max_tokens=64` selected:

```text
prompt_words_goal: 192500
actual bench prompt tokens/request: ~261,974
total with 64 output tokens: ~262,038
```

Three sequential near-256K requests completed:

```text
requests_ok: 3
requests_error: 0
latency_avg: 318.58s
TTFT_avg: 315.03s
prompt_tps wall-clock: 808.38 tok/s
generation_tps wall-clock: 0.20 tok/s
server prefill windows: ~26K tok/s
server post-prefill generation windows: ~4-6 tok/s
MTP2 draft acceptance: 72.2%-100.0%
```

Interpretation: functional 256K smoke passes on 2x3090, but huge prefill dominates latency. Treat this as an ultra-cheap long-context fallback, not an interactive default.

Instance was destroyed after the bench.

## Practical takeaways

### Best currently validated 2x budget path

```text
2x RTX 5070 Ti
Carnice NVFP4
fp8 KV
64K context
no MTP for small concurrency-1 request pattern
```

### Best currently validated ultra-cheap long-context 160K path

```text
2x RTX 3090
Qwen3.6-27B-AWQ
awq_marlin
fp8 KV
MTP n=1 for 160K small smoke; MTP n=2 functional for 256K context-fill
160K/256K targets
single-user
validated startup + smoke, but only under relaxed reliability policy
```

### 5070 Ti headroom note

From the 2x 5070 Ti no-MTP fp8-KV run:

```text
GPU KV cache size: 58,016 tokens
max_model_len configured: 65,536
```

Interpretation:

```text
Practical single-user context is closer to ~56K than a true 64K with output headroom.
```

## Suggested next actions

1. If continuing 2x RTX 3090, prefer strict policy first, then use the relaxed reliability state profile only if cost/availability matters more than host quality.

2. Run a larger 2x3090 MTP1 vs no-MTP single-user benchmark now that both start at 160K:

```text
input_tokens: 4K-16K first, then larger context-fill tests
output_tokens: 512-2048
concurrency: 1
compare no-MTP vs MTP1
```

3. Re-check key startup lines in future runs:

```text
speculative_config=None or SpeculativeConfig(method='mtp', num_spec_tokens=1)
max_seq_len=160000
GPU KV cache size
Maximum concurrency for 160,000 tokens per request
```

4. If 160K regresses on a different 2x3090 host, step down in this order:

```text
160K -> 128K -> 96K
```

5. For a better budget default, keep 2x RTX 5070 Ti no-MTP as the faster path and 2x RTX 3090 as the ultra-cheap long-context fallback.

## Useful commands

Check current offer set:

```bash
. env.vast-management
./run.sh scripts/select_and_launch.py \
  --launch-profile config/launch-profiles/qwen3.6-27b-awq.rtx3090-2gpu-160k-fp8kv-no-mtp.on-demand.json \
  --check-only \
  --skip-current-infra \
  --top 5
```

If a successful run completes, summarize live metrics:

```bash
. env.vast-management
./run.sh scripts/summarize_vllm_metrics.py \
  --base-url http://<host>:<mapped_8000>/v1
```

## Files most likely needed next session

```text
docs/qwen3.6-27b-h200-generation-tps-report.md
docs/handoff-consumer-2gpu-long-context-next-steps.md
config/launch-profiles/qwen3.6-27b-awq.rtx3090-2gpu-160k-fp8kv-no-mtp.on-demand.json
config/models/qwen3.6-27b-awq.rtx3090-2gpu-160k-fp8kv-no-mtp.json
config/gpu-profiles/qwen-27b-awq-rtx3090-2gpu.json
config/launch-profiles/carnice-v2-27b-nvfp4-text-mtp.rtx5070ti-2gpu.agentic-64k-fp8kv.on-demand.json
config/launch-profiles/carnice-v2-27b-nvfp4-text-mtp.rtx5070ti-2gpu.agentic-64k-fp8kv-no-mtp.on-demand.json
```
