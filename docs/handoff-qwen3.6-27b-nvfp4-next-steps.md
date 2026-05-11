# Handoff: Qwen3.6 27B NVFP4 / FP8 Vast.ai Benchmarks

Date: 2026-05-10 / 2026-05-11 UTC

## Current state

No active Vast instances were present after the latest runs.

Latest pushed commits of interest:

```text
46b56b0 feat(vast): add carnice nvfp4 rtx5090 profile
fe0d77a chore(vast): allow geo-aware unverified 5090 search
86f9b08 docs(bench): add rtx5090 carnice smoke
```

Main report is up to date:

```text
docs/qwen3.6-27b-h200-generation-tps-report.md
```

## Completed uploads

### Carnice NVFP4 MTP

```text
HF repo: sakamakismile/Carnice-V2-27b-NVFP4-TEXT-MTP
R2 prefix: sakamakismile/Carnice-V2-27b-NVFP4-TEXT-MTP
R2 model files: 10
R2 model size: 19,657,807,165 bytes
manifest: sakamakismile/Carnice-V2-27b-NVFP4-TEXT-MTP/.stream-manifest.json
```

### Official Qwen FP8

```text
HF repo: Qwen/Qwen3.6-27B-FP8
R2 prefix: Qwen/Qwen3.6-27B-FP8
R2 objects: 81 including manifest
R2 size: ~30.89 GB
manifest: Qwen/Qwen3.6-27B-FP8/.stream-manifest.json
```

### Unsloth NVFP4

Upload completed and was verified by exact file count + byte size.

```text
HF repo: unsloth/Qwen3.6-27B-NVFP4
revision: 6db17837b1c03a197fb45cef806e0c2a612c3aa7
R2 prefix: unsloth/Qwen3.6-27B-NVFP4
HF files: 11
R2 model files: 11
HF size: 25,551,963,180 bytes
R2 model size: 25,551,963,180 bytes
manifest: unsloth/Qwen3.6-27B-NVFP4/.stream-manifest.json
missing/extra/mismatch: []
```

## Profiles and templates

### Carnice PRO 6000 WS full-context profile

```text
model profile: config/models/carnice-v2-27b-nvfp4-text-mtp.json
launch profiles:
  config/launch-profiles/carnice-v2-27b-nvfp4-text-mtp.pro6000ws.on-demand.json
  config/launch-profiles/carnice-v2-27b-nvfp4-text-mtp.pro6000ws.interruptible.json
template_name: vLLM_R2_Carnice_V2_27B_NVFP4_TEXT_MTP
template_hash_id: fa7b676dcc8b410adca262efec8c86d4
```

Key settings:

```text
max_model_len: 262144
max_num_seqs: 2
kv_cache_dtype: fp8
gpu_memory_utilization: 0.9
language_model_only: true
quantization/modelopt: enabled
speculative_config: {"method":"qwen3_5_mtp","num_speculative_tokens":3}
tool_call_parser: qwen3_xml
reasoning_parser: qwen3
```

### Carnice RTX 5090 16K profile

Created by copy-then-edit from the tested Carnice profile.

```text
gpu profile: config/gpu-profiles/carnice-v2-27b-nvfp4-mtp-rtx5090-1gpu.json
model profile: config/models/carnice-v2-27b-nvfp4-text-mtp.rtx5090-16k.json
launch profile: config/launch-profiles/carnice-v2-27b-nvfp4-text-mtp.rtx5090.on-demand.json
template_name: vLLM_R2_Carnice_V2_27B_NVFP4_TEXT_MTP_RTX5090_16K
template_hash_id: 9c9da26e008eb4069ee25fc5f82751e3
```

Key settings:

```text
gpu: RTX 5090
min_gpu_total_ram_mb: 30000
max_model_len: 16384
gpu_memory_utilization: 0.85
kv_cache_dtype: unset
max_num_seqs: 2
language_model_only: true
quantization/modelopt: enabled
speculative_config: {"method":"qwen3_5_mtp","num_speculative_tokens":3}
tool_call_parser: qwen3_xml
reasoning_parser: qwen3
```

RTX 5090 profile search settings:

```text
require_verified: false
search_no_default: true
greylisted_machine_ids: [8357, 51352]
min_inet_down: 1000 Mbps
provisioner R2 speed test: still enabled, default minimum 100 MB/s
```

Reason for greylisting `51352`: Docker/NVIDIA CDI host failure before provisioning:

```text
failed to inject CDI devices: unresolvable CDI devices .../gpu=2
```

### Official Qwen FP8 PRO 6000 WS profile

```text
model profile: config/models/qwen3.6-27b-fp8.pro6000ws.json
launch profile: config/launch-profiles/qwen3.6-27b-fp8.pro6000ws.on-demand.json
template_name: vLLM_R2_Qwen3_6_27B_FP8_PRO6000WS
template_hash_id: 910465ed31fbab3ab1d72d828cde7ec4
```

Key settings:

```text
max_model_len: 160000
max_num_seqs: 2
kv_cache_dtype: fp8
language_model_only: true
speculative_config: {"method":"qwen3_next_mtp","num_speculative_tokens":2}
reasoning_parser: qwen3
```

## Benchmark results to preserve

### H200 official Qwen FP8 non-MTP

```text
instance_id: 36501118
gpu: H200
concurrency: 5
generation_tps: 406.64 tok/s total
wall-clock per stream: 81.33 tok/s
speculative_config: None
```

### H200 official Qwen FP8 + MTP n=2

```text
instance_id: 36502498
gpu: H200
concurrency: 5
generation_tps: 693.52 tok/s total
wall-clock per stream: 138.70 tok/s
active per stream: 146.20 tok/s
MTP active: SpeculativeConfig(method='mtp', num_spec_tokens=2)
acceptance: ~80-84%
```

### PRO 6000 WS Carnice NVFP4 + MTP n=3

```text
instance_id: 36509448
gpu: RTX PRO 6000 WS
concurrency: 2
generation_tps: 169.96 tok/s total
wall-clock per stream: 84.98 tok/s
active per stream: ~92.68 tok/s
MTP active: num_spec_tokens=3
acceptance: ~76.5-82.1%
```

### PRO 6000 WS official Qwen FP8 + MTP n=2

```text
instance_id: 36510679
gpu: RTX PRO 6000 WS
concurrency: 2
generation_tps: 172.90 tok/s total
wall-clock per stream: 86.45 tok/s
active per stream: ~90.30 tok/s
MTP active: num_spec_tokens=2
acceptance: ~79.1-85.1%
```

### RTX 5090 Carnice NVFP4 + MTP n=3, 16K

```text
instance_id: 36514355
machine_id: 58434
gpu: RTX 5090
geolocation: France, FR
concurrency: 1
generation_tps: 61.89 tok/s
active per stream: ~63.34 tok/s
avg TTFT: 9.34s, with one outlier; 3/4 requests <= 2.5s
R2 speed test: 256 MB/s, threshold 100 MB/s
MTP active: num_spec_tokens=3
acceptance: ~75.3-86.9%
```

### AWQ PRO 6000 WS MTP caution

```text
AWQ old/no-MTP slices: ~69-71 tok/s single-stream observed
AWQ MTP n=1: ~65.82 tok/s/stream at concurrency 2
AWQ MTP n=2: ~18.70 tok/s/stream at concurrency 2
```

Conclusion: AWQ MTP was not worth it on PRO 6000 WS. `num_speculative_tokens=2` was clearly bad for the AWQ path.

## Geo search notes

Vast SDK supports `geolocation` filters in query strings. The built-in `georegion=true geolocation=NA` helper did not work cleanly through our current launcher path, so temporary profiles used explicit lists.

Useful manual tiers:

```text
US: geolocation=US
NA: geolocation in [CA,US]
Western Europe + JP: geolocation in [GB,IE,FR,DE,NL,BE,CH,AT,DK,SE,NO,FI,ES,PT,IT,JP]
```

Todo already added compactly to `todo.txt`: implement geo-tiered Vast offer search for unverified RTX 5090 tests while keeping `search_no_default`, `min_inet_down`, and R2 MB/s checks.

## Recommended next steps

1. Create a persistent Unsloth NVFP4 model profile and RTX 5090 / PRO 6000 WS launch profiles from the Carnice NVFP4 profile using copy-then-edit.
2. Read the Unsloth model card for exact vLLM flags before building templates.
3. For RTX 5090, keep 16K first:

```text
max_model_len: 16384
gpu_memory_utilization: ~0.85
max_num_seqs: 2
MTP: use model-card recommendation if present
R2 speed test: keep enabled
```

4. If re-running Carnice RTX 5090, prefer geo tiers in this order:

```text
US -> NA -> western Europe + JP -> broader fallback
```

5. If a host fails before provisioning with Docker/CDI/device errors, add the machine ID to `greylisted_machine_ids` and try another offer.

## Current local-only leftovers

These were already local/untracked and not part of the benchmark profile commits:

```text
docs/library-extraction-plan.md
tmp/
uv.lock
vllm_log_for_launch_optimization.md
watch_20260505-222607
```
