#!/usr/bin/env bash
set -euo pipefail

: "${R2_BUCKET:?missing R2_BUCKET}"
: "${R2_PREFIX:?missing R2_PREFIX}"
: "${R2_ENDPOINT:?missing R2_ENDPOINT}"
: "${AWS_ACCESS_KEY_ID:?missing AWS_ACCESS_KEY_ID}"
: "${AWS_SECRET_ACCESS_KEY:?missing AWS_SECRET_ACCESS_KEY}"
: "${MODEL_DIR:?missing MODEL_DIR}"

export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-auto}"

MODEL_MIN_FREE_GB="${MODEL_MIN_FREE_GB:-5}"
# Built-in smoke gate for R2 path quality. Override with env if needed.
# Set R2_SPEED_TEST_MIN_MBPS=0 to disable.
# Set R2_SPEED_TEST_WARN_ONLY=true to run/log the test but continue below threshold.
R2_SPEED_TEST_MIN_MBPS="${R2_SPEED_TEST_MIN_MBPS:-100}"
R2_SPEED_TEST_WARN_ONLY="${R2_SPEED_TEST_WARN_ONLY:-false}"
R2_SPEED_TEST_MAX_MB="${R2_SPEED_TEST_MAX_MB:-512}"
# Optional stable bucket-level object for speed tests. If unset, try this key
# first and fall back to the largest object under the model prefix.
R2_SPEED_TEST_KEY="${R2_SPEED_TEST_KEY:-_vast/r2-speed-test.bin}"
R2_TRANSFER_TOOL="${R2_TRANSFER_TOOL:-rclone}"
RCLONE_TRANSFERS="${RCLONE_TRANSFERS:-16}"
RCLONE_CHECKERS="${RCLONE_CHECKERS:-32}"
RCLONE_MULTI_THREAD_STREAMS="${RCLONE_MULTI_THREAD_STREAMS:-8}"
RCLONE_STATS_INTERVAL="${RCLONE_STATS_INTERVAL:-10s}"

mkdir -p "$MODEL_DIR" ~/.aws

emit_nvlink_status() {
  python3 - <<'PY' || true
import csv
import datetime as _dt
import json
import shutil
import subprocess
import uuid

PREFIX = "VAST_GPU_NVLINK_JSON "
SAMPLE_ID = str(uuid.uuid4())

def now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat()


def run_cmd(args):
    try:
        proc = subprocess.run(args, text=True, capture_output=True, timeout=20, check=False)
        return {
            "returncode": proc.returncode,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
        }
    except Exception as exc:  # pragma: no cover - runs on remote host
        return {
            "returncode": None,
            "stdout": "",
            "stderr": f"{type(exc).__name__}: {exc}",
        }


def emit(payload):
    payload.setdefault("schema_version", 2)
    payload.setdefault("sample_id", SAMPLE_ID)
    payload.setdefault("ts", now())
    # Keep each record short so Vast log transport does not truncate it.
    print(PREFIX + json.dumps(payload, sort_keys=True, separators=(",", ":")), flush=True)


nvidia_smi = shutil.which("nvidia-smi")
if not nvidia_smi:
    emit({
        "event": "gpu_nvlink_summary",
        "nvidia_smi_present": False,
        "gpu_count": 0,
        "has_nvlink": False,
        "topology_codes": [],
        "note": "nvidia-smi not found",
    })
    raise SystemExit(0)

gpu_query = run_cmd([
    nvidia_smi,
    "--query-gpu=index,name,uuid,pci.bus_id",
    "--format=csv,noheader,nounits",
])
topo = run_cmd([nvidia_smi, "topo", "-m"])
nvlink = run_cmd([nvidia_smi, "nvlink", "-s"])

gpus = []
if gpu_query["returncode"] == 0:
    for row in csv.reader(gpu_query["stdout"].splitlines()):
        if len(row) < 4:
            continue
        try:
            index = int(row[0].strip())
        except ValueError:
            continue
        gpus.append({
            "index": index,
            "name": row[1].strip(),
            "uuid": row[2].strip(),
            "pci_bus_id": row[3].strip(),
        })

links = []
if topo["returncode"] == 0:
    lines = [line.rstrip() for line in topo["stdout"].splitlines() if line.strip()]
    header = []
    for line in lines:
        parts = line.split()
        if not parts:
            continue
        if parts[0].startswith("GPU") and not header:
            header = [p for p in parts if p.startswith("GPU")]
            continue
        row_label = parts[0]
        if not row_label.startswith("GPU") or not header:
            continue
        try:
            src = int(row_label[3:])
        except ValueError:
            continue
        for pos, dst_label in enumerate(header):
            if pos + 1 >= len(parts):
                continue
            try:
                dst = int(dst_label[3:])
            except ValueError:
                continue
            if src == dst:
                continue
            code = parts[pos + 1]
            links.append({
                "source": src,
                "target": dst,
                "topology": code,
                "nvlink": code.startswith("NV"),
            })

has_nvlink = any(link["nvlink"] for link in links)
topology_codes = sorted({link["topology"] for link in links})
emit({
    "event": "gpu_nvlink_summary",
    "nvidia_smi_present": True,
    "gpu_count": len(gpus),
    "link_count": len(links),
    "has_nvlink": has_nvlink,
    "topology_codes": topology_codes,
    "gpu_query_rc": gpu_query["returncode"],
    "topo_rc": topo["returncode"],
    "nvlink_rc": nvlink["returncode"],
})

for gpu in gpus:
    emit({
        "event": "gpu_nvlink_gpu",
        "gpu_index": gpu["index"],
        "gpu_name": gpu["name"],
        "gpu_uuid": gpu["uuid"],
        "pci_bus_id": gpu["pci_bus_id"],
    })

for link in links:
    emit({
        "event": "gpu_nvlink_link",
        "source": link["source"],
        "target": link["target"],
        "topology": link["topology"],
        "nvlink": link["nvlink"],
    })
PY
}

emit_nvlink_status

SERVED_MODEL_NAME="${SERVED_MODEL_NAME:-$(basename "$MODEL_DIR" | tr '[:upper:]_' '[:lower:]-')}"
VLLM_DTYPE="${VLLM_DTYPE:-half}"
VLLM_MAX_MODEL_LEN="${VLLM_MAX_MODEL_LEN:-8192}"
VLLM_HOST="${VLLM_HOST:-127.0.0.1}"
VLLM_PORT="${VLLM_PORT:-18000}"
VLLM_DOWNLOAD_DIR="${VLLM_DOWNLOAD_DIR:-/workspace/models}"
VLLM_GPU_MEMORY_UTILIZATION="${VLLM_GPU_MEMORY_UTILIZATION:-0.90}"
VLLM_TENSOR_PARALLEL_SIZE="${VLLM_TENSOR_PARALLEL_SIZE:-}"
VLLM_KV_CACHE_DTYPE="${VLLM_KV_CACHE_DTYPE:-}"
VLLM_TRUST_REMOTE_CODE="${VLLM_TRUST_REMOTE_CODE:-true}"
VLLM_FORCE_QUANTIZATION="${VLLM_FORCE_QUANTIZATION:-}"
VLLM_MAX_NUM_SEQS="${VLLM_MAX_NUM_SEQS:-}"
VLLM_MAX_NUM_BATCHED_TOKENS="${VLLM_MAX_NUM_BATCHED_TOKENS:-}"
VLLM_MAX_NEW_TOKENS="${VLLM_MAX_NEW_TOKENS:-}"
VLLM_ENABLE_AUTO_TOOL_CHOICE="${VLLM_ENABLE_AUTO_TOOL_CHOICE:-false}"
VLLM_TOOL_CALL_PARSER="${VLLM_TOOL_CALL_PARSER:-}"
VLLM_REASONING_PARSER="${VLLM_REASONING_PARSER:-}"
VLLM_ENABLE_PREFIX_CACHING="${VLLM_ENABLE_PREFIX_CACHING:-false}"
VLLM_LANGUAGE_MODEL_ONLY="${VLLM_LANGUAGE_MODEL_ONLY:-false}"
VLLM_SPECULATIVE_CONFIG_B64="${VLLM_SPECULATIVE_CONFIG_B64:-}"
VLLM_EXTRA_ARGS="${VLLM_EXTRA_ARGS:-}"
VLLM_USE_FASTOKENS="${VLLM_USE_FASTOKENS:-0}"
# Optional DFlash2 speculative-decoding drafter (block-diffusion, external drafter).
# When set, the drafter repo is synced from R2 to DRAFTER_DIR and the vLLM install
# is patched in place with the DFlash2 backport (vLLM PR #52816) before serve.
# The template must also pass --speculative-config '{"method":"dflash",...}' via
# VLLM_SPECULATIVE_CONFIG_B64 and --attention-backend FLASH_ATTN via VLLM_EXTRA_ARGS.
# DFlash2 requires a bf16 target lm_head and bfloat16 KV cache.
PATCH_DFLASH2="${PATCH_DFLASH2:-0}"
DRAFTER_DIR="${DRAFTER_DIR:-}"
DRAFTER_PREFIX="${DRAFTER_PREFIX:-}"

if [ "$VLLM_TENSOR_PARALLEL_SIZE" = "auto" ]; then
  detected_gpu_count="$(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | awk 'NF {count++} END {print count+0}')"
  if [ "${detected_gpu_count:-0}" -gt 1 ]; then
    VLLM_TENSOR_PARALLEL_SIZE="$detected_gpu_count"
  else
    VLLM_TENSOR_PARALLEL_SIZE=""
  fi
  echo "Resolved VLLM_TENSOR_PARALLEL_SIZE=auto to ${VLLM_TENSOR_PARALLEL_SIZE:-single-gpu default}"
fi

# Use a file for complex vLLM args. This avoids Docker/template/env quoting
# issues and is read by /opt/supervisor-scripts/vllm.sh after provisioning.
{
  printf -- '--served-model-name %q ' "$SERVED_MODEL_NAME"
  printf -- '--dtype %q ' "$VLLM_DTYPE"
  printf -- '--max-model-len %q ' "$VLLM_MAX_MODEL_LEN"
  printf -- '--host %q ' "$VLLM_HOST"
  printf -- '--port %q ' "$VLLM_PORT"
  printf -- '--download-dir %q ' "$VLLM_DOWNLOAD_DIR"
  printf -- '--gpu-memory-utilization %q ' "$VLLM_GPU_MEMORY_UTILIZATION"
  if [ -n "$VLLM_TENSOR_PARALLEL_SIZE" ]; then
    printf -- '--tensor-parallel-size %q ' "$VLLM_TENSOR_PARALLEL_SIZE"
  fi
  if [ -n "$VLLM_KV_CACHE_DTYPE" ]; then
    printf -- '--kv-cache-dtype %q ' "$VLLM_KV_CACHE_DTYPE"
  fi
  if [ "$VLLM_TRUST_REMOTE_CODE" = "true" ]; then
    printf -- '--trust-remote-code '
  fi
  if [ -n "$VLLM_FORCE_QUANTIZATION" ]; then
    printf -- '--quantization %q ' "$VLLM_FORCE_QUANTIZATION"
  fi
  if [ -n "$VLLM_MAX_NUM_SEQS" ]; then
    printf -- '--max-num-seqs %q ' "$VLLM_MAX_NUM_SEQS"
  fi
  if [ -n "$VLLM_MAX_NUM_BATCHED_TOKENS" ]; then
    printf -- '--max-num-batched-tokens %q ' "$VLLM_MAX_NUM_BATCHED_TOKENS"
  fi
  if [ -n "$VLLM_MAX_NEW_TOKENS" ]; then
    printf -- '--override-generation-config %q ' "{\"max_new_tokens\":${VLLM_MAX_NEW_TOKENS}}"
  fi
  if [ "$VLLM_ENABLE_AUTO_TOOL_CHOICE" = "true" ]; then
    printf -- '--enable-auto-tool-choice '
  fi
  if [ -n "$VLLM_TOOL_CALL_PARSER" ]; then
    printf -- '--tool-call-parser %q ' "$VLLM_TOOL_CALL_PARSER"
  fi
  if [ -n "$VLLM_REASONING_PARSER" ]; then
    printf -- '--reasoning-parser %q ' "$VLLM_REASONING_PARSER"
  fi
  if [ "$VLLM_ENABLE_PREFIX_CACHING" = "true" ]; then
    printf -- '--enable-prefix-caching '
  fi
  if [ "$VLLM_LANGUAGE_MODEL_ONLY" = "true" ]; then
    printf -- '--language-model-only '
  fi
  if [ -n "$VLLM_SPECULATIVE_CONFIG_B64" ]; then
    speculative_config="$(printf '%s' "$VLLM_SPECULATIVE_CONFIG_B64" | base64 -d)"
    printf -- '--speculative-config %q ' "$speculative_config"
  fi
  if [ -n "$VLLM_EXTRA_ARGS" ]; then
    printf -- '%s ' "$VLLM_EXTRA_ARGS"
  fi
  printf -- '--api-key ${VLLM_API_KEY}\n'
} > /etc/vllm-args.conf

available_gb="$(df -BG "$MODEL_DIR" | awk 'NR==2 {gsub(/G/, "", $4); print $4}')"
if [ "${available_gb:-0}" -lt "$MODEL_MIN_FREE_GB" ]; then
  echo "ERROR: only ${available_gb:-0}GB free at $MODEL_DIR; need at least ${MODEL_MIN_FREE_GB}GB" >&2
  exit 1
fi

echo "Provisioning model from R2"
echo "  R2 source: s3://$R2_BUCKET/$R2_PREFIX"
echo "  Target:    $MODEL_DIR"
echo "  Free GB:   $available_gb"

# Tune S3/R2 transfer concurrency for model repos with multiple safetensor shards.
cat > ~/.aws/config <<'EOF'
[default]
region = auto
s3 =
    max_concurrent_requests = 32
    multipart_threshold = 64MB
    multipart_chunksize = 64MB
EOF

if ! command -v aws >/dev/null 2>&1; then
  if command -v uv >/dev/null 2>&1; then
    uv pip install --system awscli
  else
    python3 -m pip install --no-cache-dir awscli
  fi
fi

case "${VLLM_USE_FASTOKENS,,}" in
  1|true|yes|on)
    echo "VLLM_USE_FASTOKENS enabled; installing fastokens>=0.2.0"
    if command -v uv >/dev/null 2>&1; then
      uv pip install --system --upgrade 'fastokens>=0.2.0'
    fi
    if command -v pip >/dev/null 2>&1; then
      pip install --no-cache-dir --upgrade 'fastokens>=0.2.0'
    fi
    python3 -m pip install --no-cache-dir --upgrade 'fastokens>=0.2.0'
    for python_bin in python3 /usr/local/bin/python3 /usr/bin/python3; do
      if command -v "$python_bin" >/dev/null 2>&1; then
        "$python_bin" - <<'PY'
import fastokens
print("fastokens import ok")
PY
      fi
    done
    ;;
esac

if [ "$R2_TRANSFER_TOOL" = "rclone" ] && ! command -v rclone >/dev/null 2>&1; then
  echo "Installing rclone for parallel R2 downloads"
  curl -fsSL https://rclone.org/install.sh | bash
fi

rclone_config="/tmp/rclone-r2.conf"
if [ "$R2_TRANSFER_TOOL" = "rclone" ]; then
  cat > "$rclone_config" <<EOF
[r2]
type = s3
provider = Cloudflare
access_key_id = $AWS_ACCESS_KEY_ID
secret_access_key = $AWS_SECRET_ACCESS_KEY
endpoint = $R2_ENDPOINT
acl = private
EOF
fi

if [ "$R2_SPEED_TEST_MIN_MBPS" != "0" ]; then
  echo "R2 speed test enabled: minimum ${R2_SPEED_TEST_MIN_MBPS} MB/s, max ${R2_SPEED_TEST_MAX_MB} MB"
  speed_key=""
  speed_size=""
  if [ -n "$R2_SPEED_TEST_KEY" ]; then
    if speed_size="$(aws s3api head-object \
      --bucket "$R2_BUCKET" \
      --key "$R2_SPEED_TEST_KEY" \
      --endpoint-url "$R2_ENDPOINT" \
      --query ContentLength \
      --output text 2>/dev/null)"; then
      speed_key="$R2_SPEED_TEST_KEY"
      echo "R2 speed test using static object key from R2_SPEED_TEST_KEY"
    else
      echo "WARN: R2 speed test static object not found: s3://$R2_BUCKET/$R2_SPEED_TEST_KEY; falling back to model prefix"
    fi
  fi
  if [ -z "$speed_key" ]; then
    speed_row="$(aws s3 ls "s3://$R2_BUCKET/$R2_PREFIX/" --recursive --endpoint-url "$R2_ENDPOINT" \
      | awk '$3 > 0 {print $3 " " $4}' \
      | sort -nr \
      | head -1)"
    speed_size="${speed_row%% *}"
    speed_key="${speed_row#* }"
  fi
  if [ -z "$speed_key" ] || [ -z "$speed_size" ] || [ "$speed_key" = "$speed_size" ]; then
    echo "ERROR: R2 speed test could not find any non-empty object under s3://$R2_BUCKET/$R2_PREFIX" >&2
    exit 1
  fi
  case "$speed_size" in
    ''|*[!0-9]*)
      echo "ERROR: R2 speed test object size is not numeric for s3://$R2_BUCKET/$speed_key: $speed_size" >&2
      exit 1
      ;;
  esac
  speed_dir="/tmp/r2-speed-test"
  rm -rf "$speed_dir"
  mkdir -p "$speed_dir"
  test_bytes="$(( R2_SPEED_TEST_MAX_MB * 1000 * 1000 ))"
  if [ "$speed_size" -lt "$test_bytes" ]; then
    test_bytes="$speed_size"
  fi
  if [ "$test_bytes" -lt 1 ]; then
    echo "ERROR: R2 speed test object is empty: s3://$R2_BUCKET/$speed_key" >&2
    exit 1
  fi
  chunk_count="$RCLONE_MULTI_THREAD_STREAMS"
  [ "$chunk_count" -lt 1 ] && chunk_count=1
  [ "$chunk_count" -gt "$test_bytes" ] && chunk_count="$test_bytes"
  chunk_bytes="$(( (test_bytes + chunk_count - 1) / chunk_count ))"
  echo "R2 speed test object: s3://$R2_BUCKET/$speed_key (${speed_size} bytes)"
  echo "R2 speed test range: first ${test_bytes} bytes across ${chunk_count} parallel ranged GETs"
  start_ts="$(date +%s)"
  pids=""
  i=0
  while [ "$i" -lt "$chunk_count" ]; do
    range_start="$(( i * chunk_bytes ))"
    range_end="$(( range_start + chunk_bytes - 1 ))"
    [ "$range_end" -ge "$test_bytes" ] && range_end="$(( test_bytes - 1 ))"
    aws s3api get-object \
      --bucket "$R2_BUCKET" \
      --key "$speed_key" \
      --range "bytes=${range_start}-${range_end}" \
      --endpoint-url "$R2_ENDPOINT" \
      "$speed_dir/part-$i" >"$speed_dir/part-$i.log" 2>&1 &
    pids="$pids $!"
    i="$(( i + 1 ))"
  done
  failed=0
  for pid in $pids; do
    if ! wait "$pid"; then
      failed=1
    fi
  done
  if [ "$failed" -ne 0 ]; then
    echo "ERROR: R2 speed test ranged GET failed for s3://$R2_BUCKET/$speed_key" >&2
    for log in "$speed_dir"/*.log; do
      [ -f "$log" ] || continue
      echo "--- $log ---" >&2
      tail -20 "$log" >&2 || true
    done
    rm -rf "$speed_dir"
    exit 1
  fi
  end_ts="$(date +%s)"
  elapsed_s="$(( end_ts - start_ts ))"
  [ "$elapsed_s" -lt 1 ] && elapsed_s=1
  bytes="$(find "$speed_dir" -type f -name 'part-[0-9]*' ! -name '*.log' -printf '%s\n' | awk '{s += $1} END {print s + 0}')"
  mbps="$(awk -v b="$bytes" -v s="$elapsed_s" 'BEGIN {printf "%.2f", b / 1000000 / s}')"
  echo "R2 speed test result: ${bytes} bytes in ${elapsed_s}s = ${mbps} MB/s"
  rm -rf "$speed_dir"
  if awk -v got="$mbps" -v min="$R2_SPEED_TEST_MIN_MBPS" 'BEGIN {exit !(got < min)}'; then
    if [ "$R2_SPEED_TEST_WARN_ONLY" = "true" ]; then
      echo "WARN: R2 speed test below threshold; continuing because R2_SPEED_TEST_WARN_ONLY=true: ${mbps} MB/s < ${R2_SPEED_TEST_MIN_MBPS} MB/s" >&2
    else
      echo "ERROR: R2 speed test below threshold: ${mbps} MB/s < ${R2_SPEED_TEST_MIN_MBPS} MB/s" >&2
      exit 42
    fi
  fi
fi

# Cheap readiness check. If config exists and at least one safetensors file exists, skip.
if [ -f "$MODEL_DIR/config.json" ] && find "$MODEL_DIR" -maxdepth 1 -name '*.safetensors' | grep -q .; then
  echo "Model appears present at $MODEL_DIR; skipping R2 sync"
else
  echo "Syncing s3://$R2_BUCKET/$R2_PREFIX -> $MODEL_DIR"
  echo "Sync started at: $(date -Is)"
  # Intentionally do not use --only-show-errors here. Vast UI logs need transfer
  # activity so we can tell R2 sync is progressing before vLLM starts. Emit both
  # rclone's own transfer counters and our completed-file fallback; the fallback
  # can appear flat while rclone is still downloading a large temporary shard.
  if [ "$R2_TRANSFER_TOOL" = "rclone" ]; then
    echo "R2 rclone stats interval: $RCLONE_STATS_INTERVAL"
    rclone copy "r2:$R2_BUCKET/$R2_PREFIX" "$MODEL_DIR" \
      --config "$rclone_config" \
      --transfers "$RCLONE_TRANSFERS" \
      --checkers "$RCLONE_CHECKERS" \
      --multi-thread-cutoff 1M \
      --multi-thread-streams "$RCLONE_MULTI_THREAD_STREAMS" \
      --stats "$RCLONE_STATS_INTERVAL" \
      --stats-one-line \
      --stats-log-level NOTICE &
    rclone_pid="$!"
    (
      while kill -0 "$rclone_pid" 2>/dev/null; do
        bytes="$(find "$MODEL_DIR" -type f -printf '%s\n' 2>/dev/null | awk '{s += $1} END {print s + 0}')"
        files="$(find "$MODEL_DIR" -type f 2>/dev/null | wc -l | awk '{print $1}')"
        largest="$(find "$MODEL_DIR" -type f -printf '%s %f\n' 2>/dev/null | sort -nr | head -1 || true)"
        echo "R2 sync progress: ${bytes} bytes across ${files} files at $MODEL_DIR; largest=${largest:-none}"
        sleep 30
      done
    ) &
    progress_pid="$!"
    rclone_rc=0
    wait "$rclone_pid" || rclone_rc="$?"
    kill "$progress_pid" 2>/dev/null || true
    wait "$progress_pid" 2>/dev/null || true
    if [ "$rclone_rc" -ne 0 ]; then
      exit "$rclone_rc"
    fi
  else
    aws s3 sync "s3://$R2_BUCKET/$R2_PREFIX" "$MODEL_DIR" \
      --endpoint-url "$R2_ENDPOINT"
  fi
  echo "Sync finished at: $(date -Is)"
  echo "Synced bytes: $(du -sh "$MODEL_DIR" | awk '{print $1}')"
fi

# Optional DFlash2 drafter sync (only when PATCH_DFLASH2=1). Mirrors the main model
# sync: rclone when available, aws s3 sync fallback, cheap readiness check first.
if [ "$PATCH_DFLASH2" = "1" ]; then
  if [ -z "$DRAFTER_DIR" ] || [ -z "$DRAFTER_PREFIX" ]; then
    echo "ERROR: PATCH_DFLASH2=1 requires DRAFTER_DIR and DRAFTER_PREFIX" >&2
    exit 1
  fi
  mkdir -p "$DRAFTER_DIR"
  if [ -f "$DRAFTER_DIR/config.json" ] && find "$DRAFTER_DIR" -maxdepth 1 -name '*.safetensors' | grep -q .; then
    echo "Drafter appears present at $DRAFTER_DIR; skipping R2 sync"
  else
    echo "Syncing drafter s3://$R2_BUCKET/$DRAFTER_PREFIX -> $DRAFTER_DIR"
    if [ "$R2_TRANSFER_TOOL" = "rclone" ] && command -v rclone >/dev/null 2>&1; then
      rclone copy "r2:$R2_BUCKET/$DRAFTER_PREFIX" "$DRAFTER_DIR" \
        --config "$rclone_config" \
        --transfers "$RCLONE_TRANSFERS" \
        --checkers "$RCLONE_CHECKERS" \
        --multi-thread-cutoff 1M \
        --multi-thread-streams "$RCLONE_MULTI_THREAD_STREAMS" \
        --stats "$RCLONE_STATS_INTERVAL" \
        --stats-one-line
    else
      aws s3 sync "s3://$R2_BUCKET/$DRAFTER_PREFIX" "$DRAFTER_DIR" \
        --endpoint-url "$R2_ENDPOINT"
    fi
    echo "Drafter synced: $(du -sh "$DRAFTER_DIR" | awk '{print $1}')"
  fi

  # Apply the DFlash2 backport to the installed vLLM in place. Idempotent: skips
  # when the new model file already exists (cached-container restarts). Refuses to
  # boot on patch failure so a drifted image cannot silently serve unpatched.
  # Patch provenance: vLLM PR #52816 (merged 2026-08-21), backported to v0.27.1 by
  # syv-ai, vendored by noonghunna/club-3090 (models/qwen3.8-27b/vllm/patches/
  # vllm-dflash2-backport). Verified clean against vllm/vllm-openai:v0.27.1.
  # Resolve the installed vllm package dir. The vastai image's default python3
  # may not be the interpreter carrying vllm (conda/venv layouts), so probe a
  # list of candidate interpreters first, then fall back to a filesystem search.
  # Any python3 works for the shim/content-check (pure file ops); only the
  # package location matters for the patch.
  vllm_pkg=""
  for cand in python3 python /usr/local/bin/python3 /usr/local/bin/python /usr/bin/python3 /opt/conda/bin/python /opt/venv/bin/python /venv/main/bin/python python3.12 python3.11 python3.10; do
    if command -v "$cand" >/dev/null 2>&1; then
      candidate_pkg="$("$cand" -c 'import vllm, os; print(os.path.dirname(vllm.__file__))' 2>/dev/null)" || candidate_pkg=""
      if [ -n "$candidate_pkg" ]; then
        vllm_pkg="$candidate_pkg"
        echo "Resolved vllm package via $cand: $vllm_pkg"
        break
      fi
    fi
  done
  if [ -z "$vllm_pkg" ]; then
    echo "No candidate interpreter imports vllm; searching filesystem"
    vllm_pkg="$(find / -maxdepth 8 -type d -name vllm \
      \( -path "*site-packages*" -o -path "*dist-packages*" \) 2>/dev/null | head -1)"
  fi
  if [ -z "$vllm_pkg" ] || [ ! -d "$vllm_pkg" ]; then
    echo "ERROR: could not locate an installed vllm package to patch" >&2
    exit 1
  fi
  if ! command -v patch >/dev/null 2>&1; then
    echo "patch not found; installing via apt-get"
    if ! (apt-get update -qq && apt-get install -y -qq patch); then
      echo "ERROR: patch is not installed and apt-get install failed" >&2
      exit 1
    fi
  fi
  if [ -f "$vllm_pkg/model_executor/models/qwen3_dflash2.py" ]; then
    echo "DFlash2 backport already present in $vllm_pkg; skipping"
  else
    echo "Applying DFlash2 backport (vLLM PR #52816) to $vllm_pkg"
    # This script is fetched standalone from the public repo, so the patch files
    # live in the repo, not next to the script. Derive the base URL from
    # PROVISIONING_SCRIPT (same branch the script came from); fall back to main.
    patch_base="${PROVISIONING_SCRIPT%/provision_vast_vllm_from_r2.sh}scripts/patches"
    patch_base="${patch_base:-https://raw.githubusercontent.com/memgrafter/vast-ai-provisioning/main/scripts/patches}"
    patch_dir="/tmp/dflash2-patches"
    mkdir -p "$patch_dir"
    for f in dflash2-backport.patch dflash2_topk_compat.py _check_applied.py; do
      curl -fsSL "$patch_base/$f" -o "$patch_dir/$f" || {
        echo "ERROR: failed to fetch DFlash2 patch file $f from $patch_base" >&2
        exit 1
      }
    done
    python3 "$patch_dir/dflash2_topk_compat.py" "$vllm_pkg" || exit 1
    if ! ( cd "$vllm_pkg" && patch -p1 --forward --batch < "$patch_dir/dflash2-backport.patch" ); then
      echo "ERROR: DFlash2 backport failed to apply to $vllm_pkg — refusing to boot" >&2
      exit 1
    fi
    if ! python3 "$patch_dir/_check_applied.py" "$patch_dir/dflash2-backport.patch" "$vllm_pkg"; then
      echo "ERROR: DFlash2 backport content check failed in $vllm_pkg — refusing to boot" >&2
      exit 1
    fi
    echo "DFlash2 backport applied and verified"
  fi
fi

# Ensure vLLM will use the local model path even if the template forgot to set it.
# Note: template env VLLM_MODEL is still preferred because supervisor reads env at process start.
echo "VLLM_MODEL=${VLLM_MODEL:-$MODEL_DIR}"
echo "Model files:"
find "$MODEL_DIR" -maxdepth 1 -type f | sed 's#^#  #' | sort | tail -50
