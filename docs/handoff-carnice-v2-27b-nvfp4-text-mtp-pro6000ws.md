# Handoff: Carnice-V2-27b-NVFP4-TEXT-MTP on RTX PRO 6000 WS

Goal: finish streaming `sakamakismile/Carnice-V2-27b-NVFP4-TEXT-MTP` to R2, then use the prepared PRO 6000 WS templates/profiles for smoke and generation-TPS benchmarking.

## Current stream status

Stream completed and wrote the manifest.

```text
HF repo: sakamakismile/Carnice-V2-27b-NVFP4-TEXT-MTP
R2 prefix: sakamakismile/Carnice-V2-27b-NVFP4-TEXT-MTP
profile: config/models/carnice-v2-27b-nvfp4-text-mtp.json
pid file: state/stream-carnice-v2-27b-nvfp4-text-mtp.pid
log file: state/stream-carnice-v2-27b-nvfp4-text-mtp.log
```

Important: this repo has one huge weight file:

```text
model.safetensors ~19.64 GB
```

The upload initially appeared stuck because `aws s3 ls --summarize` does not show partial progress for a single in-flight object. It completed with:

```text
Total Objects: 11
Total Size: 19,657,808,063 bytes
.stream-manifest.json present
```

Check stream:

```bash
pid=$(cat state/stream-carnice-v2-27b-nvfp4-text-mtp.pid)
ps -p "$pid" -o pid,stat,etime,command

pgrep -P "$pid" | while read c; do
  ps -p "$c" -o pid,ppid,stat,etime,command
done

tail -20 state/stream-carnice-v2-27b-nvfp4-text-mtp.log

source env.modeltransfer
.venv/bin/aws s3 ls "s3://$R2_BUCKET/sakamakismile/Carnice-V2-27b-NVFP4-TEXT-MTP/" \
  --endpoint-url "$R2_ENDPOINT" \
  --recursive --summarize | tail -20
```

Completion check:

```bash
source env.modeltransfer
.venv/bin/aws s3 ls "s3://$R2_BUCKET/sakamakismile/Carnice-V2-27b-NVFP4-TEXT-MTP/.stream-manifest.json" \
  --endpoint-url "$R2_ENDPOINT"
```

Expected total repo size from HF metadata:

```text
~19.66 GB
```

## What was prepared already

### Model profile

```text
config/models/carnice-v2-27b-nvfp4-text-mtp.json
```

Current key settings:

```json
{
  "hf_model_id": "sakamakismile/Carnice-V2-27b-NVFP4-TEXT-MTP",
  "r2_prefix": "sakamakismile/Carnice-V2-27b-NVFP4-TEXT-MTP",
  "model_dir": "/workspace/models/sakamakismile/Carnice-V2-27b-NVFP4-TEXT-MTP",
  "served_model_name": "carnice-v2-27b-nvfp4-text-mtp",
  "quantization": "modelopt",
  "vllm": {
    "dtype": "auto",
    "max_model_len": 262144,
    "gpu_memory_utilization": 0.9,
    "kv_cache_dtype": "fp8",
    "max_num_seqs": 2,
    "enable_auto_tool_choice": true,
    "tool_call_parser": "qwen3_xml",
    "reasoning_parser": "qwen3",
    "language_model_only": true,
    "speculative_config": {
      "method": "qwen3_5_mtp",
      "num_speculative_tokens": 3
    },
    "force_quantization": "modelopt"
  }
}
```

These settings came from the HF model card recommendations for Blackwell / RTX PRO 6000.

### Launch profiles

Prepared PRO 6000 WS launch profiles:

```text
config/launch-profiles/carnice-v2-27b-nvfp4-text-mtp.pro6000ws.on-demand.json
config/launch-profiles/carnice-v2-27b-nvfp4-text-mtp.pro6000ws.interruptible.json
```

They both target:

```text
config/gpu-profiles/qwen-27b-awq-96gb-rtx-pro-6000-ws.json
```

### Remote Vast template

Already created and written into both launch profiles:

```text
template_name: vLLM_R2_Carnice_V2_27B_NVFP4_TEXT_MTP
template_hash_id: fa7b676dcc8b410adca262efec8c86d4
```

Rendered env verifies:

```text
R2_PREFIX=sakamakismile/Carnice-V2-27b-NVFP4-TEXT-MTP
SERVED_MODEL_NAME=carnice-v2-27b-nvfp4-text-mtp
VLLM_FORCE_QUANTIZATION=modelopt
VLLM_KV_CACHE_DTYPE=fp8
VLLM_MAX_MODEL_LEN=262144
VLLM_MAX_NUM_SEQS=2
VLLM_TOOL_CALL_PARSER=qwen3_xml
VLLM_REASONING_PARSER=qwen3
VLLM_LANGUAGE_MODEL_ONLY=true
VLLM_SPECULATIVE_CONFIG_B64 -> {"method":"qwen3_5_mtp","num_speculative_tokens":3}
```

## Provisioning support already pushed

Needed because this template uses:

```text
VLLM_KV_CACHE_DTYPE
VLLM_SPECULATIVE_CONFIG_B64
```

Commit on `main`:

```text
65ca529 feat(vast): add carnice nvfp4 mtp profile
```

Remote provisioner URL in templates points at GitHub raw `main`, so this push matters.

## Relevant HF model-card notes

Model card says for vLLM on Blackwell / RTX PRO 6000:

```bash
--trust-remote-code \
--quantization modelopt \
--language-model-only \
--enable-auto-tool-choice --tool-call-parser qwen3_xml \
--reasoning-parser qwen3 \
--max-model-len 262144 \
--max-num-seqs 2 \
--kv-cache-dtype fp8 \
--gpu-memory-utilization 0.9 \
--speculative-config '{"method":"qwen3_5_mtp","num_speculative_tokens":3}'
```

Claimed model-card performance on RTX PRO 6000 Blackwell:

```text
single decode: ~107 / 98 / 102 tok/s (short / medium / long)
2-parallel aggregate: ~193 / 194 tok/s
```

## Next steps

Use the on-demand launch profile. Vast interruptible has been unreliable for this testing path.

1. Confirm `.stream-manifest.json` exists if starting from a fresh shell.
2. Optionally re-run template update if any profile fields changed.
3. Run a PRO 6000 WS smoke/bench.

Suggested first smoke bench:

```bash
. env.vast-management
./run.sh scripts/smoke_chat_once.py \
  --launch-profile config/launch-profiles/carnice-v2-27b-nvfp4-text-mtp.pro6000ws.on-demand.json \
  --launch-attempts 1 \
  --ready-timeout 3000 \
  --bench-seconds 60 \
  --bench-concurrency 2 \
  --bench-input-tokens 4500 \
  --bench-output-tokens 2048 \
  --no-destroy-on-error
```

Why start at `concurrency=2`:

- prior AWQ PRO 6000 WS runs showed queue at higher concurrency
- this gives a cleaner first per-stream number
- then ramp to `5` if stable

## What to verify in logs on the next run

Confirm MTP/spec decode is actually enabled:

```text
speculative_config=SpeculativeConfig(method='mtp' ... num_spec_tokens=3)
Resolved architecture: Qwen3_5MTP
Loading drafter model...
SpecDecoding metrics:
```

Also verify the text-only/tool settings survived:

```text
language_model_only
qwen3_xml
reasoning_parser=qwen3
quantization modelopt
kv-cache-dtype fp8
```

## Metrics to report

At minimum:

```text
generation_tps total
wall-clock generation_tps_per_stream = generation_tps / concurrency
active-inference generation_tps_per_stream = avg_generation_tokens_per_request / avg_inference_s
prompt_tps
total_tps
TTFT avg
queue avg
inference avg
requests_ok / requests_error
avg prompt/request
avg generation/request
```

## Current local-only leftovers

Still untracked locally and intentionally not part of this handoff work:

```text
docs/library-extraction-plan.md
tmp/
uv.lock
vllm_log_for_launch_optimization.md
watch_20260505-222607
```
