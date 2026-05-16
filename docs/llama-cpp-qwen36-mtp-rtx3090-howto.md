# Qwen3.6 27B MTP GGUF on Vast RTX 3090 with llama.cpp

This is a reproducible handoff/how-to for running `unsloth/Qwen3.6-27B-MTP-GGUF` on a single RTX 3090 using the llama.cpp MTP PR branch.

The working setup used:

```text
GPU: RTX 3090 24GB
Runtime image: nvidia/cuda:12.0.1-devel-ubuntu20.04
llama.cpp branch: am17an/mtp-clean
llama.cpp build observed: b9172-08b147428
Model tested: Qwen3.6-27B-Q4_K_M.gguf
Working long-context config: 160K ctx, q4_0/q4_0 KV, MTP draft-mtp n=2, parallel=1
```

Do not assume mainline llama.cpp has this support yet. At the time of testing, MTP support came from PR `ggml-org/llama.cpp#22673` / branch `am17an:mtp-clean`.

## Quickstart

SSH to the Vast instance:

```bash
ssh -i ~/.ssh/<your-private-key> -p <ssh_port> root@<ssh_host>
```

Build llama.cpp MTP branch with CUDA:

```bash
apt-get update
apt-get install -y --no-install-recommends \
  pciutils build-essential cmake curl libcurl4-openssl-dev \
  git ca-certificates python3-pip python3-setuptools python3-wheel ninja-build ccache

# Ubuntu 20.04 apt cmake is too old for current llama.cpp CUDA builds.
python3 -m pip install --upgrade pip cmake

mkdir -p /workspace/src
cd /workspace/src

git clone -b mtp-clean https://github.com/am17an/llama.cpp.git
cd llama.cpp

/usr/local/bin/cmake -S . -B build-mtp-cuda -G Ninja \
  -DCMAKE_BUILD_TYPE=Release \
  -DGGML_CUDA=ON \
  -DCMAKE_CUDA_ARCHITECTURES=86 \
  -DGGML_CCACHE=ON

/usr/local/bin/cmake --build build-mtp-cuda --target llama-cli llama-server llama-speculative -j "$(nproc)"
```

Download model files:

```bash
mkdir -p /workspace/models/unsloth/Qwen3.6-27B-MTP-GGUF
cd /workspace/models/unsloth/Qwen3.6-27B-MTP-GGUF

wget -c --progress=dot:giga \
  https://huggingface.co/unsloth/Qwen3.6-27B-MTP-GGUF/resolve/main/Qwen3.6-27B-Q4_K_M.gguf

wget -c --progress=dot:giga \
  https://huggingface.co/unsloth/Qwen3.6-27B-MTP-GGUF/resolve/main/Qwen3.6-27B-Q3_K_M.gguf
```

Run a 160K server with MTP and q4 KV:

```bash
/workspace/src/llama.cpp/build-mtp-cuda/bin/llama-server \
  --host 0.0.0.0 --port 8000 \
  --no-mmproj --reasoning off \
  -m /workspace/models/unsloth/Qwen3.6-27B-MTP-GGUF/Qwen3.6-27B-Q4_K_M.gguf \
  -ngl 99 -fa on -np 1 -c 160000 \
  --cache-type-k q4_0 --cache-type-v q4_0 \
  --jinja \
  --spec-type draft-mtp --spec-draft-n-max 2
```

Call OpenAI-compatible chat completions:

```bash
curl http://<host>:<mapped_8000>/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{
    "model": "qwen",
    "messages": [{"role": "user", "content": "hello"}],
    "max_tokens": 128,
    "temperature": 0.6
  }'
```

For local-only testing on the instance, bind to `127.0.0.1` and use `/completion` or `/v1/chat/completions` directly.

## 1. Vast instance setup

### Recommended instance type

Use a **single RTX 3090 24GB** if you want a cheap interactive SSH box. Prefer **on-demand** for longer interactive sessions so the instance is not reclaimed.

The tested host was a verified on-demand RTX 3090 with fast local NVMe. Use your own availability check; do not rely on old offer IDs.

### Launch mode

Use an SSH-capable CUDA development image. The tested template/image was:

```text
image: nvidia/cuda:12.0.1-devel-ubuntu20.04
runtype: ssh
ssh_direct: true
```

Attach your public key:

```text
~/.ssh/<your-public-key>.pub
```

If launching via Vast SDK, create the instance from the selected offer with a CUDA image/template and then attach SSH:

```python
from pathlib import Path
from vastai import VastAI

vast = VastAI()

result = vast.create_instance(
    id=<offer_id>,
    disk=800,
    template_hash="<ssh_cuda_template_hash>",
    label="ssh-rtx3090-llamacpp-models",
    cancel_unavail=True,
)

instance_id = result["new_contract"]
ssh_key = Path.home().joinpath(".ssh/<your-public-key>.pub").read_text().strip()
vast.attach_ssh(int(instance_id), ssh_key)
```

Verify SSH and GPU:

```bash
ssh -i ~/.ssh/<your-private-key> -p <ssh_port> root@<ssh_host> \
  'echo SSH_OK; nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader'
```

Expected shape:

```text
NVIDIA GeForce RTX 3090, 24576 MiB, <driver>
```

## 2. Model downloads

The tested local model directory was:

```text
/workspace/models/unsloth/Qwen3.6-27B-MTP-GGUF
```

Download Q4_K_M first, then Q3_K_M:

```bash
cat > /workspace/download_qwen36_gguf.sh <<'SH'
#!/usr/bin/env bash
set -euo pipefail
MODEL_DIR=/workspace/models/unsloth/Qwen3.6-27B-MTP-GGUF
LOG=/workspace/qwen36-gguf-download.log
mkdir -p "$MODEL_DIR"
cd "$MODEL_DIR"
{
  echo "==== $(date -Is) starting Qwen3.6-27B-MTP-GGUF downloads ===="
  df -h /workspace / 2>/dev/null || df -h /
  for f in Qwen3.6-27B-Q4_K_M.gguf Qwen3.6-27B-Q3_K_M.gguf; do
    url="https://huggingface.co/unsloth/Qwen3.6-27B-MTP-GGUF/resolve/main/$f"
    echo "==== $(date -Is) downloading $f ===="
    wget -c --progress=dot:giga --retry-connrefused --waitretry=5 --read-timeout=30 --timeout=30 -t 0 -O "$f" "$url"
    echo "==== $(date -Is) finished $f ===="
    ls -lh "$f"
    sha256sum "$f" > "$f.sha256"
  done
  echo "==== $(date -Is) all downloads complete ===="
  df -h /workspace / 2>/dev/null || df -h /
} >> "$LOG" 2>&1
SH

chmod +x /workspace/download_qwen36_gguf.sh
nohup /workspace/download_qwen36_gguf.sh >/workspace/qwen36-gguf-nohup.out 2>&1 &
echo $! > /workspace/qwen36-gguf-download.pid
```

Monitor:

```bash
tail -f /workspace/qwen36-gguf-download.log
ls -lh /workspace/models/unsloth/Qwen3.6-27B-MTP-GGUF
```

Observed sizes:

```text
Qwen3.6-27B-Q4_K_M.gguf  ~16G
Qwen3.6-27B-Q3_K_M.gguf  ~13G
```

### About UD-Q4_K_XL

Unsloth's published fast-path command uses:

```bash
-hf unsloth/Qwen3.6-27B-MTP-GGUF:UD-Q4_K_XL
```

The initial local tests used `Qwen3.6-27B-Q4_K_M.gguf`, not `UD-Q4_K_XL`. To reproduce Unsloth's faster path exactly, test `UD-Q4_K_XL` as a follow-up.

## 3. Build llama.cpp MTP branch

### Why this branch

Mainline llama.cpp may not yet include Qwen3.6 MTP support. The needed PR was:

```text
https://github.com/ggml-org/llama.cpp/pull/22673
branch: am17an/mtp-clean
```

The branch adds support for:

```text
--spec-type draft-mtp
--spec-draft-n-max <N>
```

At the tested commit, `--spec-type mtp` was stale documentation/old spelling. The binary help showed the current spelling:

```text
--spec-type none,draft-simple,draft-eagle3,draft-mtp,ngram-simple,...
```

### Build script

```bash
cat > /workspace/build_llama_cpp_mtp_branch.sh <<'SH'
#!/usr/bin/env bash
set -euo pipefail
LOG=/workspace/llama-cpp-mtp-build.log
{
  echo "==== $(date -Is) MTP branch build start ===="
  export DEBIAN_FRONTEND=noninteractive
  apt-get update
  apt-get install -y --no-install-recommends \
    git build-essential python3-pip python3-setuptools python3-wheel \
    ninja-build pkg-config libcurl4-openssl-dev ca-certificates ccache

  # Ubuntu 20.04 apt cmake is too old for current CUDA build files.
  if ! command -v /usr/local/bin/cmake >/dev/null 2>&1; then
    python3 -m pip install --upgrade pip cmake
  fi
  /usr/local/bin/cmake --version

  mkdir -p /workspace/src
  if [ ! -d /workspace/src/llama.cpp/.git ]; then
    git clone https://github.com/ggml-org/llama.cpp.git /workspace/src/llama.cpp
  fi

  cd /workspace/src/llama.cpp
  git remote remove am17an 2>/dev/null || true
  git remote add am17an https://github.com/am17an/llama.cpp.git
  git fetch am17an mtp-clean
  git checkout -B mtp-clean am17an/mtp-clean
  git rev-parse --short HEAD
  git log -1 --oneline

  echo "==== $(date -Is) MTP markers ===="
  grep -RIn --exclude-dir=.git --exclude-dir=build-cuda --exclude-dir=build-mtp-cuda \
    -E 'mtp|MTP|nextn|spec' src include common tools 2>/dev/null | head -160 || true

  echo "==== $(date -Is) configure CUDA MTP branch ===="
  rm -rf build-mtp-cuda
  /usr/local/bin/cmake -S . -B build-mtp-cuda -G Ninja \
    -DCMAKE_BUILD_TYPE=Release \
    -DGGML_CUDA=ON \
    -DCMAKE_CUDA_ARCHITECTURES=86 \
    -DGGML_CCACHE=ON

  echo "==== $(date -Is) build selected targets ===="
  /usr/local/bin/cmake --build build-mtp-cuda --target llama-cli llama-server llama-speculative -j "$(nproc)"

  echo "==== $(date -Is) binaries/version/help ===="
  ls -lh build-mtp-cuda/bin/llama-cli build-mtp-cuda/bin/llama-server build-mtp-cuda/bin/llama-speculative
  build-mtp-cuda/bin/llama-cli --version || true
  build-mtp-cuda/bin/llama-cli --help 2>&1 | grep -Ei 'spec-type|draft-mtp|mtp|draft|spec' | head -160 || true
  echo "==== $(date -Is) done ===="
} >> "$LOG" 2>&1
SH

chmod +x /workspace/build_llama_cpp_mtp_branch.sh
nohup /workspace/build_llama_cpp_mtp_branch.sh >/workspace/llama-cpp-mtp-build-nohup.out 2>&1 &
echo $! > /workspace/llama-cpp-mtp-build.pid
```

Monitor:

```bash
ps -p "$(cat /workspace/llama-cpp-mtp-build.pid)" -o pid,stat,etime,cmd
tail -f /workspace/llama-cpp-mtp-build.log
```

On the tested RTX 3090 host, build was CPU-limited by a 6-core / 12-thread Ryzen 5 5600X and took a while because CUDA template instantiations are expensive. This is normal.

Verify branch/build:

```bash
cd /workspace/src/llama.cpp
git remote -v
git branch --show-current
git rev-parse HEAD
git log -1 --oneline
/workspace/src/llama.cpp/build-mtp-cuda/bin/llama-cli --version
/workspace/src/llama.cpp/build-mtp-cuda/bin/llama-cli --help | grep spec-type
```

Observed:

```text
branch: mtp-clean
commit: 08b147428e7db0760acda2b4e0bd49f5b2ffe945
version: 9172 (08b147428)
```

## 4. Smoke test with llama-cli

Use `-st` / `--single-turn` so `llama-cli` exits after the first response instead of staying interactive.

```bash
/workspace/src/llama.cpp/build-mtp-cuda/bin/llama-cli \
  --no-mmproj --reasoning off \
  -m /workspace/models/unsloth/Qwen3.6-27B-MTP-GGUF/Qwen3.6-27B-Q4_K_M.gguf \
  -ngl 99 -fa on -np 1 -c 4096 \
  --cache-type-k f32 --cache-type-v f32 \
  --jinja \
  --spec-type draft-mtp --spec-draft-n-max 2 \
  -n 128 -st \
  --temp 0.6 --top-p 0.95 --top-k 20 --min-p 0.0 --repeat-penalty 1.0 \
  -p "Write a tiny C function that returns the larger of two ints, then explain it in one sentence."
```

Observed smoke:

```text
Prompt:     ~198 tok/s
Generation: ~72 tok/s
exit: 0
```

Example output:

```c
int max(int a, int b) { return a > b ? a : b; }
```

## 5. Run llama-server with OpenAI-compatible chat completions

`llama-server` exposes OpenAI-compatible endpoints, including:

```text
/v1/chat/completions
/v1/completions
/completion
/tokenize
```

### Local-only server for testing

```bash
/workspace/src/llama.cpp/build-mtp-cuda/bin/llama-server \
  --host 127.0.0.1 --port 18082 \
  --no-mmproj --reasoning off \
  -m /workspace/models/unsloth/Qwen3.6-27B-MTP-GGUF/Qwen3.6-27B-Q4_K_M.gguf \
  -ngl 99 -fa on -np 1 -c 160000 \
  --cache-type-k q4_0 --cache-type-v q4_0 \
  --jinja \
  --spec-type draft-mtp --spec-draft-n-max 2
```

### Externally reachable server on Vast

If the Vast template/container maps container port `8000`, bind server to `0.0.0.0:8000`:

```bash
/workspace/src/llama.cpp/build-mtp-cuda/bin/llama-server \
  --host 0.0.0.0 --port 8000 \
  --no-mmproj --reasoning off \
  -m /workspace/models/unsloth/Qwen3.6-27B-MTP-GGUF/Qwen3.6-27B-Q4_K_M.gguf \
  -ngl 99 -fa on -np 1 -c 160000 \
  --cache-type-k q4_0 --cache-type-v q4_0 \
  --jinja \
  --spec-type draft-mtp --spec-draft-n-max 2
```

Call it:

```bash
curl http://<host>:<mapped_8000>/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{
    "model": "qwen",
    "messages": [{"role": "user", "content": "hello"}],
    "max_tokens": 128,
    "temperature": 0.6
  }'
```

### Server log proof for MTP

Expected log lines:

```text
creating MTP draft context against the target model '...Qwen3.6-27B-Q4_K_M.gguf'
common_context_can_seq_rm: the context supports bounded partial sequence removal
common_speculative_init: adding speculative implementation 'draft-mtp'
speculative decoding context initialized
new slot, n_ctx = 160000
```

## 6. Context and KV cache findings

### KV types available

This build supports:

```text
f32, f16, bf16, q8_0, q4_0, q4_1, iq4_nl, q5_0, q5_1
```

There is no `q3_0` KV option in this build.

### 262K q4 KV loads

A 262K server with q4 KV loaded and handled a tiny request:

```bash
llama-server \
  -m Qwen3.6-27B-Q4_K_M.gguf \
  -ngl 99 -fa on -np 1 -c 262144 \
  --cache-type-k q4_0 --cache-type-v q4_0 \
  --jinja --spec-type draft-mtp --spec-draft-n-max 2
```

Observed:

```text
n_ctx = 262144
VRAM: ~23169 MiB / 24576 MiB
eval: ~60 tok/s on a tiny request
draft acceptance: ~69% on tiny sample
```

This is very tight and was not full-context churn-tested at 262K.

### 160K q8 KV loads but fails full churn

160K with q8 KV loaded and handled tiny requests:

```bash
-c 160000 --cache-type-k q8_0 --cache-type-v q8_0
```

Observed at load:

```text
VRAM: ~23319 MiB / 24576 MiB
```

But a 150K prompt churn failed around 98K processed prompt tokens with CUDA OOM:

```text
CUDA error: out of memory
cuMemCreate(...)
flash_attn_ext_mma_f16
```

Conclusion: **160K q8 KV is too tight for full-context churn with MTP + flash attention on 24GB RTX 3090**.

### 160K q4 KV survives full churn

160K with q4 KV survived a 150K prompt churn:

```bash
-c 160000 --cache-type-k q4_0 --cache-type-v q4_0
```

Observed full-context churn:

```text
prompt tokens: 150,032
prompt eval: 245.24s = 611.77 tok/s
generation: 65 tokens in 1.61s = 40.40 tok/s
draft acceptance: 95.45% (42 accepted / 44 generated)
VRAM after: ~21.86 GiB / 24 GiB class
```

Conclusion: **160K q4_0/q4_0 KV is the working long-context configuration on this 3090**.

## 7. Prompt prefix cache behavior

llama.cpp server prompt cache is enabled by default. This is a **host RAM** cache, not a VRAM cache.

Log line:

```text
prompt cache is enabled, size limit: 8192 MiB
```

That means ~8 GiB system RAM budget.

The server can select a prior slot/prompt by longest common prefix similarity and restore a checkpoint:

```text
selected slot by LCP similarity, sim_best = 1.000 (> 0.100 thold), f_keep = 0.999
restored context checkpoint (pos_min = 149515, pos_max = 149515, n_tokens = 149516, ...)
```

### Prefix-cache decode test

After a 150K q4-KV churn, a second request with the same long prefix and changed tail reused the cache and generated a long continuation.

Result:

```text
prompt eval: 503 tokens in 1.56s = 323.12 tok/s
generation: 3704 tokens in 95.48s = 38.79 tok/s
total wall: 97.03s
draft acceptance: 91.23% (2392 accepted / 2622 generated)
```

It stopped before 4000 tokens because the model naturally completed / hit stop behavior.

## 8. Churn scripts

### Small/large context churn client

Create `/workspace/churn_context.py`:

```python
#!/usr/bin/env python3
from __future__ import annotations

import json
import time
import uuid
import urllib.request

BASE_URL = "http://127.0.0.1:18082"
TARGET_PROMPT_TOKENS = 150000
MAX_PREDICT_TOKENS = 128
TEMPERATURE = 0.0


def post_json(path: str, payload: dict, timeout: int = 3600) -> dict:
    req = urllib.request.Request(
        BASE_URL + path,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def count_tokens(text: str) -> int:
    return len(post_json("/tokenize", {"content": text}, timeout=300).get("tokens", []))


def build_prompt(target_tokens: int) -> tuple[str, int]:
    nonce = uuid.uuid4().hex
    header = f"""nonce-{nonce}
You are testing long-context recall and decode. The context below contains many numbered records.
Read all records. At the end, answer with: (1) the nonce, (2) the highest record id seen, (3) a tiny C max(a,b) function.
Do not skip the final instruction.

BEGIN RECORDS
"""
    chunk = (
        "record {i:06d}: alpha beta gamma delta epsilon zeta eta theta. "
        "This record is unique enough to force prompt processing and contains a checksum marker {j:06d}.\n"
    )
    footer = """
END RECORDS

Final instruction: report the nonce, the highest record id, and a tiny C function max_int(int a, int b).
"""
    base_tokens = count_tokens(header + footer)
    chunk_tokens = count_tokens(chunk.format(i=0, j=0))
    n_chunks = max(1, (target_tokens - base_tokens) // max(1, chunk_tokens))
    prompt = header + "".join(chunk.format(i=i, j=(i * 17) % 1000000) for i in range(n_chunks)) + footer
    tokens = count_tokens(prompt)
    while tokens < target_tokens:
        i = n_chunks
        prompt = prompt[:-len(footer)] + chunk.format(i=i, j=(i * 17) % 1000000) + footer
        n_chunks += 1
        tokens = count_tokens(prompt)
    return prompt, tokens


def main() -> None:
    print(f"target_prompt_tokens={TARGET_PROMPT_TOKENS}", flush=True)
    print(f"max_predict_tokens={MAX_PREDICT_TOKENS}", flush=True)
    t0 = time.monotonic()
    prompt, prompt_tokens = build_prompt(TARGET_PROMPT_TOKENS)
    print(f"actual_prompt_tokens={prompt_tokens}", flush=True)
    print(f"prompt_build_and_tokenize_s={time.monotonic() - t0:.2f}", flush=True)
    payload = {
        "prompt": prompt,
        "n_predict": MAX_PREDICT_TOKENS,
        "temperature": TEMPERATURE,
        "top_k": 20,
        "top_p": 0.95,
        "min_p": 0.0,
        "repeat_penalty": 1.0,
        "cache_prompt": False,
    }
    t1 = time.monotonic()
    result = post_json("/completion", payload, timeout=3600)
    print(f"request_wall_s={time.monotonic() - t1:.2f}")
    print(f"tokens_evaluated={result.get('tokens_evaluated')}")
    print(f"tokens_predicted={result.get('tokens_predicted')}")
    print("content_preview=")
    print((result.get("content") or "")[:2000])


if __name__ == "__main__":
    main()
```

Run:

```bash
python3 /workspace/churn_context.py | tee /workspace/churn-context-large-q4kv.log
```

For a small pre-test, edit:

```python
TARGET_PROMPT_TOKENS = 2048
MAX_PREDICT_TOKENS = 64
```

Then change back to the larger values.

### Prefix-cache long generation script

Create `/workspace/prefix_cache_4000.py` using the same long prefix but changed final instruction and `cache_prompt=true`. The important bits are:

```python
BASE_URL = "http://127.0.0.1:18082"
TARGET_PROMPT_TOKENS = 150000
MAX_PREDICT_TOKENS = 4000
payload = {
    "prompt": prompt,
    "n_predict": MAX_PREDICT_TOKENS,
    "temperature": 0.6,
    "top_k": 20,
    "top_p": 0.95,
    "min_p": 0.0,
    "repeat_penalty": 1.0,
    "cache_prompt": True,
}
```

Run:

```bash
python3 /workspace/prefix_cache_4000.py | tee /workspace/prefix-cache-4000.log
```

Watch server logs:

```bash
tail -f /workspace/llama-server-160k-q4kv-mtp.log
```

Look for:

```text
selected slot by LCP similarity
restored context checkpoint
n_decoded = ...
draft acceptance rate = ...
statistics draft-mtp: ...
```

## 9. What still needs testing

- `UD-Q4_K_XL` from the Unsloth repo, because that is the advertised faster quant.
- `UD-Q6_K_XL` and any smaller Unsloth MTP quants if needed.
- MTP draft length sweep:
  - `--spec-draft-n-max 1`
  - `--spec-draft-n-max 2` current
  - `--spec-draft-n-max 3`
- No-MTP baseline with same model/context/KV.
- KV cache sweep:
  - `q4_0/q4_0` current working default
  - `q4_1/q4_1`
  - `q5_0/q5_0`
  - `q5_1/q5_1`
  - `iq4_nl/iq4_nl`
- Full-context churn at 262K q4 KV, if you need maximum context.
- `/v1/chat/completions` workload matching your actual client.
- Tool calling / reasoning mode. Current tests used `--reasoning off`.
- Prompt-cache behavior after multiple different prompts and cache pressure.
- Concurrency. MTP PR notes often recommend `-np 1`; verify before using `-np 2+`.

## 10. Known pitfalls

- `--spec-type mtp` may be stale. Use:

```bash
--spec-type draft-mtp
```

- MTP support currently expects `-np 1` in the safest path.
- 160K `q8_0/q8_0` KV can load but OOMs during full prompt churn.
- 262K `q4_0/q4_0` can load but is very tight and needs full churn validation.
- llama.cpp prompt cache log uses `MiB` and refers to **system RAM**, not VRAM.
- `llama-cli` is interactive by default. Add `-st` for one-shot smoke tests.
- Ubuntu 20.04's apt CMake is too old for current llama.cpp CUDA builds; install newer CMake with pip or another package source.
- If a long request crashes the server, check:

```bash
nvidia-smi
tail -200 /workspace/llama-server-*.log
```

and restart the server with lower context or smaller KV type.
