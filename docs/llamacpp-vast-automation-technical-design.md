# Vast llama.cpp automation — technical design

## Script

```text
scripts/select_launch_llamacpp.py
```

Modes:

| Mode | Behavior |
|---|---|
| `--check-only` | Show current offers; never launch. |
| launch | Prompt, create instance, poll SSH, bootstrap, smoke-test. |
| `--no-bootstrap` | Launch only; print SSH/tunnel details. |
| `--build-from-source` | Build `llama-server` remotely if the artifact did not provide it. |

## Inputs

Required for launch/bootstrap:

```bash
VAST_API_KEY
R2_BUCKET
R2_ENDPOINT
AWS_ACCESS_KEY_ID
AWS_SECRET_ACCESS_KEY
```

Core arguments:

```text
--model-r2-key        R2 object key for the GGUF model
--artifact-r2-key     optional R2 tarball with /workspace-relative runtime files
--gpu-name            default RTX 5060 Ti
--ctx                 default 35000
--n-predict           default 4096
--container-port      default 8081
--backend-port        default 8082
```

The model filename defaults to the basename of `--model-r2-key`. Bootstrap requires code from either `--artifact-r2-key` or `--sync-local-code`, and `llama-server` from either `--artifact-r2-key` or `--build-from-source`.

## Offer policy

Search on verified, rentable, on-demand single-GPU offers. Client-side filters reject offers that miss:

- requested GPU name/count,
- minimum VRAM/CUDA/reliability,
- requested disk size,
- at least one direct port,
- configured hourly/storage/network caps.

Ranking is intentionally simple: lower hourly cost first, then higher reliability and better disk/network traits.

## Instance create

Use `VastAI.create_instance()` with:

```python
runtype = "ssh_direc ssh_proxy"
env = {"-p 8081:8081": "1"}
image = "nvidia/cuda:12.8.1-devel-ubuntu24.04"
```

The exposed container port is mapped by Vast to a random public host port. If no mapping is found after launch, the script prints an SSH tunnel fallback.

## Bootstrap

After SSH is ready:

1. install minimal OS packages and an isolated awscli venv,
2. write `/root/.llamacpp-r2.env` with R2 credentials and runtime options,
3. download the model to `/workspace/models/<filename>` with size verification,
4. download/extract the optional artifact tarball to `/workspace`,
5. optionally clone/build TurboQuant llama.cpp,
6. write `/workspace/code/llm-cache-llama.cpp/run-vast-llamacpp-stack.sh`,
7. start the stack in background and poll `/health`.

Expected artifact contents:

```text
code/llm-cache-llama.cpp/...
clones/llama-cpp-turboquant/build-cuda/bin/llama-server
```

## Auth

If `--llamacpp-api-key-env NAME` is provided, the key is copied to the remote root-only env file.

Startup behavior:

1. prefer `--api-key-file` when `llama-server --help` advertises it,
2. only use argv `--api-key` when `--allow-api-key-argv` is explicitly set,
3. otherwise start without public auth and print the tunnel fallback.

## Local state

The script writes only ignored operational state:

```text
state/current-infra.json
offers/<offer_id>.selected-llamacpp.json
state/last-create-llamacpp.json
instances/<instance_id>.llamacpp.json
```

Do not commit those files.

## Follow-up work

- Add a small artifact build/upload helper.
- Move stable defaults into JSON profiles if this flow becomes routine.
- Split benchmark-only context sweeps and metrics parsing into separate scripts.
