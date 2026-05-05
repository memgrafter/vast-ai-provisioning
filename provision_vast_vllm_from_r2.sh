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

mkdir -p "$MODEL_DIR" ~/.aws

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

R2_SPEED_TEST_MIN_MBPS="${R2_SPEED_TEST_MIN_MBPS:-0}"
R2_SPEED_TEST_MAX_MB="${R2_SPEED_TEST_MAX_MB:-512}"
if [ "$R2_SPEED_TEST_MIN_MBPS" != "0" ]; then
  echo "R2 speed test enabled: minimum ${R2_SPEED_TEST_MIN_MBPS} MB/s, max ${R2_SPEED_TEST_MAX_MB} MB"
  speed_key="$(aws s3 ls "s3://$R2_BUCKET/$R2_PREFIX/" --recursive --endpoint-url "$R2_ENDPOINT" \
    | awk '$3 > 0 {print $3 " " $4}' \
    | sort -nr \
    | head -1 \
    | cut -d' ' -f2-)"
  if [ -z "$speed_key" ]; then
    echo "ERROR: R2 speed test could not find any non-empty object under s3://$R2_BUCKET/$R2_PREFIX" >&2
    exit 1
  fi
  speed_out="/tmp/r2-speed-test.bin"
  rm -f "$speed_out"
  range_end="$(( R2_SPEED_TEST_MAX_MB * 1000 * 1000 - 1 ))"
  echo "R2 speed test object: s3://$R2_BUCKET/$speed_key"
  echo "R2 speed test range: bytes=0-${range_end}"
  start_ts="$(date +%s)"
  aws s3api get-object \
    --bucket "$R2_BUCKET" \
    --key "$speed_key" \
    --range "bytes=0-${range_end}" \
    --endpoint-url "$R2_ENDPOINT" \
    "$speed_out" >/dev/null
  end_ts="$(date +%s)"
  elapsed_s="$(( end_ts - start_ts ))"
  [ "$elapsed_s" -lt 1 ] && elapsed_s=1
  bytes="$(wc -c < "$speed_out")"
  mbps="$(awk -v b="$bytes" -v s="$elapsed_s" 'BEGIN {printf "%.2f", b / 1000000 / s}')"
  echo "R2 speed test result: ${bytes} bytes in ${elapsed_s}s = ${mbps} MB/s"
  rm -f "$speed_out"
  if awk -v got="$mbps" -v min="$R2_SPEED_TEST_MIN_MBPS" 'BEGIN {exit !(got < min)}'; then
    echo "ERROR: R2 speed test below threshold: ${mbps} MB/s < ${R2_SPEED_TEST_MIN_MBPS} MB/s" >&2
    exit 42
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
  aws s3 sync "s3://$R2_BUCKET/$R2_PREFIX" "$MODEL_DIR" \
    --endpoint-url "$R2_ENDPOINT"
  echo "Sync finished at: $(date -Is)"
  echo "Synced bytes: $(du -sh "$MODEL_DIR" | awk '{print $1}')"
fi

# Ensure vLLM will use the local model path even if the template forgot to set it.
# Note: template env VLLM_MODEL is still preferred because supervisor reads env at process start.
echo "VLLM_MODEL=${VLLM_MODEL:-$MODEL_DIR}"
echo "Model files:"
find "$MODEL_DIR" -maxdepth 1 -type f | sed 's#^#  #' | sort | tail -50
