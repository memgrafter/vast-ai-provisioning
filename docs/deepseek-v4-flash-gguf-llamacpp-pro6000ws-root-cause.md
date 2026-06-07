# DeepSeek V4 Flash GGUF llama.cpp PRO6000WS root-cause notes

Date: 2026-06-04

## Scope

Target setup:

- Vast GPU: `RTX PRO 6000 WS` / Blackwell, compute capability 12.0
- Model repo mirrored to R2: `0xSero/DeepSeek-V4-Flash-162B-GGUF`
- GGUF file: `DeepSeek-V4-Flash-Spark-Mini-Q2-REAP-ds4.gguf`
- Served alias: `DeepSeek-V4-Flash-Spark-Mini`
- Local copied logs: `logs/ds4/`

The instance and the separate Qwen Vast instance were terminated after investigation.

## Timeline of failures

### 1. Existing `llama-cpp-turboquant` build cannot load DS4

Initial bootstrap used the existing `TheTom/llama-cpp-turboquant` build path from the repo automation.

Failure:

```text
llama_model_load: error loading model: unknown model architecture: 'deepseek4'
```

Root cause: that fork/build does not know the `deepseek4` GGUF architecture. This is independent of KV-cache compression settings.

### 2. Antirez DS4 fork recognizes architecture

Switched manually to:

```text
https://github.com/antirez/llama.cpp-deepseek-v4-flash
```

Observed commit on host:

```text
2f2d440 Speed up DeepSeek V4 prompt replay
```

This fork successfully parsed the GGUF metadata and loaded the model architecture.

### 3. Quantized KV cache config fails before serving

With the previous profile’s KV cache setting:

```text
CACHE_K=q8_0
CACHE_V=q8_0
FLASH_ATTN=auto/off path
```

Failure:

```text
quantized V cache was requested, but this requires Flash Attention
Flash Attention was auto, set to disabled
failed to create context
```

Root cause: llama.cpp requires Flash Attention for quantized V cache, but this DS4 CUDA graph/path disabled Flash Attention. Switching to f16 KV avoided this initialization failure.

### 4. f16 KV loads but crashes during CUDA execution

Runtime used:

```text
SERVER_BIN=/workspace/clones/llama-cpp-deepseek-v4-flash/build-cuda/bin/llama-server
CACHE_K=f16
CACHE_V=f16
FLASH_ATTN=off
TURBOQUANT=0
CTX=200000
BATCH=8192
UBATCH=512
PARALLEL=1
```

The server loaded and listened successfully:

```text
main: model loaded
main: server is listening on http://127.0.0.1:8082
```

GPU memory after load was about:

```text
52291 MiB / 97887 MiB
```

Then requests crashed the backend.

#### Long-context request

A ~180k-character prompt was tokenized by llama.cpp as:

```text
task.n_tokens = 60035
```

Crash:

```text
CUDA error: an illegal memory access was encountered
current device: 0, in function launch_mul_mat_q at .../ggml-cuda/template-instances/../mmq.cuh:3912
.../ggml-cuda/ggml-cuda.cu:97: CUDA error
```

#### Tiny smoke request

A tiny smoke prompt was tokenized as:

```text
task.n_tokens = 9
```

Crash:

```text
/workspace/clones/llama-cpp-deepseek-v4-flash/ggml/src/ggml-cuda/concat.cu:165: GGML_ASSERT(src0->type == GGML_TYPE_F32) failed
```

This proves the crash is not caused by long context length; even a 9-token request aborts in CUDA execution.

## Why the proxy is not the primary root cause

The LMCache proxy logs show:

```text
GET /v1/models HTTP/1.1" 200
WARNING llama API call failed: POST /apply-template — HTTP Error 401: Unauthorized
WARNING unexpected /apply-template response: None
WARNING llama server error: Remote end closed connection without response
POST /v1/chat/completions HTTP/1.1" 502
```

The `/apply-template` 401 is a real proxy/backend auth mismatch and should be fixed separately. However, it is not the backend crash root cause because the backend proceeds to parse/process the chat request and logs token processing before aborting in CUDA:

```text
slot update_slots ... task.n_tokens = 9
GGML_ASSERT(src0->type == GGML_TYPE_F32) failed
```

The proxy 502 is fallout from the backend process aborting.

## Most likely root cause

The Antirez fork has experimental DS4 support but the CUDA backend path is not stable for this setup/model/quant on Blackwell.

Supporting evidence:

- The fork README explicitly says the code runs with CPU and Metal backends:

  ```text
  The code runs both with CPU and Metal backends. With Metal is faster.
  ```

  It does not claim CUDA support is production-ready.

- The model loads successfully, so this is not a GGUF parser or architecture-recognition issue once using the Antirez fork.
- Tiny 9-token inference crashes in CUDA `concat.cu`, so context size is not the trigger.
- Long-context inference additionally hits CUDA illegal memory access in the quantized matmul path (`mmq.cuh`).
- The GGUF is `IQ2_XXS` / mixed quantized tensors:

  ```text
  type f32: 492 tensors
  type f16: 359 tensors
  type q8_0: 345 tensors
  type q2_K: 43 tensors
  type iq2_xxs: 86 tensors
  file type: IQ2_XXS - 2.0625 bpw
  ```

  The CUDA path appears to encounter unsupported tensor types/shapes in DS4 graph ops.

## Useful log files

Local copies are in:

```text
logs/ds4/
```

Key files:

```text
logs/ds4/llamacpp-backend-20260604-062604.log
logs/ds4/llamacpp-backend-20260604-064733.log
logs/ds4/llamacpp-backend-deepseek-f16kv-20260604-070635.log
logs/ds4/llamacpp-backend-deepseek-f16kv-20260604-071516.log
logs/ds4/llamacpp-backend-deepseek-f16kv-20260604-071645.log
logs/ds4/lmcache-proxy-deepseek-f16kv-20260604-071645.log
logs/ds4/stack-deepseek-f16kv-20260604-071645.log
```

Important grep patterns:

```bash
rg -n "unknown model architecture|quantized V cache|requires Flash Attention|task.n_tokens|CUDA error|illegal memory|GGML_ASSERT|concat.cu|mmq.cuh" logs/ds4
```

## Recommended next experiments

Do not assume this GGUF can serve on CUDA with the current fork. If retrying, isolate variables in this order:

1. **Confirm CPU path works**
   - Run with `--gpu-layers 0` for a tiny prompt.
   - This is slow but proves model + chat path independent of CUDA.

2. **Try partial offload**
   - Reduce `--gpu-layers` to find whether CUDA graph ops can be avoided or limited.

3. **Try disabling operation offload**
   - Candidate flag: `--no-op-offload`.
   - Goal: keep unsupported concat / host tensor ops off CUDA while still offloading model weights if possible.

4. **Try smaller batch/ubatch**
   - The 9-token crash suggests this may not fix it, but it is cheap to test:

   ```text
   BATCH=512
   UBATCH=64
   ```

5. **Try the exact Antirez GGUF**
   - The fork README points at:

   ```text
   https://huggingface.co/antirez/deepseek-v4-gguf
   ```

   The investigated file was from `0xSero/DeepSeek-V4-Flash-162B-GGUF`, not the exact README artifact.

6. **Fix proxy auth separately**
   - The proxy should pass the backend API key for internal `/apply-template` calls or skip that path when backend auth is enabled.
   - This will not fix the CUDA crash, but it removes noise.

7. **Prefer vLLM or another CUDA-supported runtime for NVIDIA serving**
   - The Antirez fork appears oriented toward CPU/Metal experimentation.

## Operational notes from this run

- Vast external ports are random. For this instance, container `8081/tcp` mapped to host port `20218`, but future launches must read the `ports` mapping.
- SSH broke initially because Vast wrote `/root/.ssh/authorized_keys` with bad ownership/mode. The reliable repair was:

  1. stop instance;
  2. wait until fully `exited`/`stopped`;
  3. `vast.execute(..., command="rm -r /root/.ssh")` while stopped;
  4. reattach SSH key;
  5. start instance.

  See `docs/vast-ssh-authorized-keys-repair-runbook.md`.
