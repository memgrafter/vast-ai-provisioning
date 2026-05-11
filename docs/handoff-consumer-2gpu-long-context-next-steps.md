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

## 2x RTX 3090 160K exploration

Prepared AWQ + fp8-KV + no-MTP 160K single-user profile:

```text
gpu profile: config/gpu-profiles/qwen-27b-awq-rtx3090-2gpu.json
model profile: config/models/qwen3.6-27b-awq.rtx3090-2gpu-160k-fp8kv-no-mtp.json
launch profile: config/launch-profiles/qwen3.6-27b-awq.rtx3090-2gpu-160k-fp8kv-no-mtp.on-demand.json
template hash: 7ef02c850d306d43ccdad8a38918889f
```

Target idea:

```text
Qwen3.6-27B-AWQ
max_model_len: 160000
kv_cache_dtype: fp8
tensor_parallel_size: 2
max_num_seqs: 1
speculative_config: None
```

Best candidate seen:

```text
offer_id: 36379411
machine_id: 42967
geo: British Columbia, CA
gpu: 2x RTX 3090
reliability2: 0.9863
inet_down: 1986 Mbps
disk_bw: 5995 MB/s
dph_total: $0.2815/hr
```

But by launch time, the market moved and no passing 2x3090 offer remained.

A temporary relaxed state profile was also checked:

```text
state/launch-profiles/qwen3.6-27b-awq.rtx3090-2gpu-160k-fp8kv-no-mtp.rel094.on-demand.json
```

but still ended with no passing offer in the subsequent check.

## Practical takeaways

### Best currently validated 2x budget path

```text
2x RTX 5070 Ti
Carnice NVFP4
fp8 KV
64K context
no MTP for small concurrency-1 request pattern
```

### Best currently prepared but not yet validated long-context 160K path

```text
2x RTX 3090
Qwen3.6-27B-AWQ
fp8 KV
no MTP
160K target
single-user
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

1. Retry the 2x RTX 3090 profile first:

```bash
. env.vast-management
./run.sh scripts/select_and_launch.py \
  --launch-profile config/launch-profiles/qwen3.6-27b-awq.rtx3090-2gpu-160k-fp8kv-no-mtp.on-demand.json \
  --check-only \
  --skip-current-infra \
  --top 5
```

2. If `machine_id: 42967` or another clean 2x3090 reappears, launch immediately.

3. On successful 2x3090 startup, inspect for:

```text
speculative_config=None
max_seq_len=160000
GPU KV cache size
Maximum concurrency for 160,000 tokens per request
```

4. If 160K fails on 2x3090, step down in this order:

```text
160K -> 128K -> 96K
```

5. If 160K succeeds, run a tiny smoke first, then a slightly larger single-user check.

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
