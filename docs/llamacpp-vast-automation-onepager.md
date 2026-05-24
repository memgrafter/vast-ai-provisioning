# Vast llama.cpp automation — one page

## Goal

Provision an inexpensive Vast.ai GPU host for a llama.cpp-compatible coding-agent endpoint without rebuilding or re-uploading large files on every run.

The launcher should:

1. show current Vast hourly burn and unchecked-volume caveat,
2. find a verified on-demand GPU offer,
3. launch a CUDA container with SSH and the requested service port,
4. download model/runtime artifacts from R2,
5. start the `llm-cache-llama.cpp` proxy stack,
6. print the endpoint, SSH command, tunnel fallback, and smoke-test result.

## Operating model

Large files move through R2. SSH is for orchestration only.

```text
local build/upload -> R2 artifact/model objects -> Vast /workspace
```

Expected remote layout:

```text
/workspace/models/<model>.gguf
/workspace/code/llm-cache-llama.cpp/
/workspace/clones/llama-cpp-turboquant/build-cuda/bin/llama-server
/workspace/logs/
/workspace/cache/llama.cpp-launch-scripts/slot-kv/
```

The artifact tarball should extract relative to `/workspace` and contain the prepared code/binary paths above. If no artifact is available, the launcher can optionally build `llama-server` from source on the host.

## Security

- Do not commit secrets, rendered live templates, instance JSON, or R2 credentials.
- R2/Vast credentials stay in ignored env files and a root-only remote env file.
- If a public service port is mapped, use llama.cpp API-key support when available.
- Without service auth, prefer the SSH tunnel fallback.

## Command shape

Read-only offer check:

```bash
. env.vast-management
./run.sh scripts/select_launch_llamacpp.py --check-only --top 5
```

Launch and bootstrap:

```bash
. env.vast-management
. env.modeltransfer
./run.sh scripts/select_launch_llamacpp.py \
  --model-r2-key llama-cpp/models/my-model.gguf \
  --artifact-r2-key llama-cpp/artifacts/llamacpp-runtime-cuda.tgz \
  --model-alias my-coding-model
```

Useful overrides:

```bash
--gpu-name "RTX 5060 Ti"
--ctx 35000
--n-predict 4096
--llamacpp-api-key-env VLLM_API_KEY
--build-from-source
--sync-local-code
```

## Requirements before routine use

- Upload a reusable runtime artifact to R2.
- Confirm the selected `llama-server` auth flags on the artifact build.
- Decide whether the default flow should publish a public Vast port or require SSH tunnel only for unauthenticated endpoints.
