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

mkdir -p "$MODEL_DIR" ~/.aws

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
VLLM_MAX_NEW_TOKENS="${VLLM_MAX_NEW_TOKENS:-}"
VLLM_ENABLE_AUTO_TOOL_CHOICE="${VLLM_ENABLE_AUTO_TOOL_CHOICE:-false}"
VLLM_TOOL_CALL_PARSER="${VLLM_TOOL_CALL_PARSER:-}"
VLLM_REASONING_PARSER="${VLLM_REASONING_PARSER:-}"
VLLM_ENABLE_PREFIX_CACHING="${VLLM_ENABLE_PREFIX_CACHING:-false}"
VLLM_LANGUAGE_MODEL_ONLY="${VLLM_LANGUAGE_MODEL_ONLY:-false}"
VLLM_SPECULATIVE_CONFIG_B64="${VLLM_SPECULATIVE_CONFIG_B64:-}"
VLLM_EXTRA_ARGS="${VLLM_EXTRA_ARGS:-}"

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
  # activity so we can tell R2 sync is progressing before vLLM starts.
  if [ "$R2_TRANSFER_TOOL" = "rclone" ]; then
    rclone copy "r2:$R2_BUCKET/$R2_PREFIX" "$MODEL_DIR" \
      --config "$rclone_config" \
      --transfers "$RCLONE_TRANSFERS" \
      --checkers "$RCLONE_CHECKERS" \
      --multi-thread-cutoff 1M \
      --multi-thread-streams "$RCLONE_MULTI_THREAD_STREAMS" \
      --stats 10s \
      --stats-one-line
  else
    aws s3 sync "s3://$R2_BUCKET/$R2_PREFIX" "$MODEL_DIR" \
      --endpoint-url "$R2_ENDPOINT"
  fi
  echo "Sync finished at: $(date -Is)"
  echo "Synced bytes: $(du -sh "$MODEL_DIR" | awk '{print $1}')"
fi

# Ensure vLLM will use the local model path even if the template forgot to set it.
# Note: template env VLLM_MODEL is still preferred because supervisor reads env at process start.
echo "VLLM_MODEL=${VLLM_MODEL:-$MODEL_DIR}"
echo "Model files:"
find "$MODEL_DIR" -maxdepth 1 -type f | sed 's#^#  #' | sort | tail -50
