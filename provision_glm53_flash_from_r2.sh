#!/usr/bin/env bash
#
# Self-contained provisioning for GLM-5.3-Flash on the vllm/vllm-openai:glm53-flash
# image. That image has ENTRYPOINT ["vllm","serve"] and NO vastai/vllm supervisor, so
# this script (run from the template onstart) must:
#   1. install the AWS CLI if missing,
#   2. sync the model from R2 to $MODEL_DIR,
#   3. assemble vllm serve args from the VLLM_* env vars (emitted by
#      scripts/build_vast_template.py), and
#   4. exec vllm serve (foreground, keeps the container alive).
#
# Public-safe: contains no secrets. AWS creds + VLLM_API_KEY come from Vast
# account-level env vars (see AGENTS.md).
set -euo pipefail

: "${R2_BUCKET:?missing R2_BUCKET}"
: "${R2_PREFIX:?missing R2_PREFIX}"
: "${R2_ENDPOINT:?missing R2_ENDPOINT}"
: "${AWS_ACCESS_KEY_ID:?missing AWS_ACCESS_KEY_ID}"
: "${AWS_SECRET_ACCESS_KEY:?missing AWS_SECRET_ACCESS_KEY}"
: "${MODEL_DIR:?missing MODEL_DIR}"

export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-auto}"
MODEL_MIN_FREE_GB="${MODEL_MIN_FREE_GB:-5}"

# --- AWS CLI ---------------------------------------------------------------
if ! command -v aws >/dev/null 2>&1; then
  echo "Installing AWS CLI"
  if command -v uv >/dev/null 2>&1; then
    uv pip install --system awscli
  elif command -v pip >/dev/null 2>&1; then
    pip install --no-cache-dir awscli
  else
    python3 -m pip install --no-cache-dir awscli
  fi
fi

# Multipart tuning for large shard repos.
cat > ~/.aws/config <<EOF
[default]
region = ${AWS_DEFAULT_REGION}
s3 =
    max_concurrent_requests = 32
    multipart_threshold = 64MB
    multipart_chunksize = 64MB
EOF

# --- Disk check ------------------------------------------------------------
mkdir -p "$MODEL_DIR"
available_gb="$(df -BG "$MODEL_DIR" | awk 'NR==2 {gsub(/G/, "", $4); print $4}')"
if [ "${available_gb:-0}" -lt "$MODEL_MIN_FREE_GB" ]; then
  echo "ERROR: only ${available_gb:-0}GB free at $MODEL_DIR; need at least $MODEL_MIN_FREE_GB" >&2
  exit 1
fi

# --- R2 sync ---------------------------------------------------------------
if [ -f "$MODEL_DIR/config.json" ] && find "$MODEL_DIR" -maxdepth 1 -name '*.safetensors' | grep -q .; then
  echo "Model appears present at $MODEL_DIR; skipping R2 sync"
else
  echo "Provisioning model from R2"
  echo "  R2 source: s3://$R2_BUCKET/$R2_PREFIX"
  echo "  Target:    $MODEL_DIR"
  echo "  Free GB:   $available_gb"
  echo "Syncing s3://$R2_BUCKET/$R2_PREFIX -> $MODEL_DIR"
  echo "Sync started at: $(date -Is)"
  aws s3 sync "s3://$R2_BUCKET/$R2_PREFIX" "$MODEL_DIR" --endpoint-url "$R2_ENDPOINT"
  echo "Sync finished at: $(date -Is)"
  echo "Synced bytes: $(du -sh "$MODEL_DIR" | awk '{print $1}')"
fi

# --- Assemble vllm serve args ---------------------------------------------
SERVED_MODEL_NAME="${SERVED_MODEL_NAME:-$(basename "$MODEL_DIR" | tr '[:upper:]_' '[:lower:]-')}"
VLLM_DTYPE="${VLLM_DTYPE:-auto}"
VLLM_MAX_MODEL_LEN="${VLLM_MAX_MODEL_LEN:?VLLM_MAX_MODEL_LEN is required}"
VLLM_HOST="${VLLM_HOST:-127.0.0.1}"
VLLM_PORT="${VLLM_PORT:-18000}"
VLLM_DOWNLOAD_DIR="${VLLM_DOWNLOAD_DIR:-/workspace/models}"
VLLM_GPU_MEMORY_UTILIZATION="${VLLM_GPU_MEMORY_UTILIZATION:-0.95}"
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

# Resolve TP=auto to the detected GPU count.
if [ "$VLLM_TENSOR_PARALLEL_SIZE" = "auto" ]; then
  detected="$(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | awk 'NF {c++} END {print c+0}')"
  if [ "${detected:-0}" -gt 1 ]; then
    VLLM_TENSOR_PARALLEL_SIZE="$detected"
  else
    VLLM_TENSOR_PARALLEL_SIZE=""
  fi
  echo "Resolved VLLM_TENSOR_PARALLEL_SIZE=auto to ${VLLM_TENSOR_PARALLEL_SIZE:-single-gpu default}"
fi

ARGS=(
  "--served-model-name" "$SERVED_MODEL_NAME"
  "--dtype" "$VLLM_DTYPE"
  "--max-model-len" "$VLLM_MAX_MODEL_LEN"
  "--host" "$VLLM_HOST"
  "--port" "$VLLM_PORT"
  "--download-dir" "$VLLM_DOWNLOAD_DIR"
  "--gpu-memory-utilization" "$VLLM_GPU_MEMORY_UTILIZATION"
)
[ -n "$VLLM_TENSOR_PARALLEL_SIZE" ] && ARGS+=("--tensor-parallel-size" "$VLLM_TENSOR_PARALLEL_SIZE")
[ -n "$VLLM_KV_CACHE_DTYPE" ] && ARGS+=("--kv-cache-dtype" "$VLLM_KV_CACHE_DTYPE")
[ "$VLLM_TRUST_REMOTE_CODE" = "true" ] && ARGS+=("--trust-remote-code")
[ -n "$VLLM_FORCE_QUANTIZATION" ] && ARGS+=("--quantization" "$VLLM_FORCE_QUANTIZATION")
[ -n "$VLLM_MAX_NUM_SEQS" ] && ARGS+=("--max-num-seqs" "$VLLM_MAX_NUM_SEQS")
[ -n "$VLLM_MAX_NUM_BATCHED_TOKENS" ] && ARGS+=("--max-num-batched-tokens" "$VLLM_MAX_NUM_BATCHED_TOKENS")
[ -n "$VLLM_MAX_NEW_TOKENS" ] && ARGS+=("--override-generation-config" "{\"max_new_tokens\":${VLLM_MAX_NEW_TOKENS}}")
[ "$VLLM_ENABLE_AUTO_TOOL_CHOICE" = "true" ] && ARGS+=("--enable-auto-tool-choice")
[ -n "$VLLM_TOOL_CALL_PARSER" ] && ARGS+=("--tool-call-parser" "$VLLM_TOOL_CALL_PARSER")
[ -n "$VLLM_REASONING_PARSER" ] && ARGS+=("--reasoning-parser" "$VLLM_REASONING_PARSER")
[ "$VLLM_ENABLE_PREFIX_CACHING" = "true" ] && ARGS+=("--enable-prefix-caching")
[ "$VLLM_LANGUAGE_MODEL_ONLY" = "true" ] && ARGS+=("--language-model-only")
if [ -n "$VLLM_SPECULATIVE_CONFIG_B64" ]; then
  speculative_config="$(printf '%s' "$VLLM_SPECULATIVE_CONFIG_B64" | base64 -d)"
  ARGS+=("--speculative-config" "$speculative_config")
fi
# Extra args are a pre-split string of tokens.
if [ -n "$VLLM_EXTRA_ARGS" ]; then
  # shellcheck disable=SC2206
  ARGS+=($VLLM_EXTRA_ARGS)
fi
ARGS+=("--api-key" "${VLLM_API_KEY:?missing VLLM_API_KEY}")

echo "Launching vllm serve:"
printf '  %q' "${ARGS[@]}"; printf '\n'

cd "${VLLM_DOWNLOAD_DIR}"
exec vllm serve "$MODEL_DIR" "${ARGS[@]}"
