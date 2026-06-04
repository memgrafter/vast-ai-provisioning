#!/usr/bin/env bash
# Launch/check the 0xSero DeepSeek V4 Flash 162B GGUF llama.cpp profile on Vast RTX PRO 6000 WS.
#
# Common usage:
#   scripts/launch_deepseek_v4_flash_162b_gguf_llamacpp_pro6000ws.sh --check-only --top 5
#   scripts/launch_deepseek_v4_flash_162b_gguf_llamacpp_pro6000ws.sh
#   scripts/launch_deepseek_v4_flash_162b_gguf_llamacpp_pro6000ws.sh --yes

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

PROFILE="config/launch-profiles/deepseek-v4-flash-162b-gguf.pro6000ws-llamacpp.on-demand.json"

usage() {
  cat <<'EOF'
Usage: scripts/launch_deepseek_v4_flash_162b_gguf_llamacpp_pro6000ws.sh [wrapper-options] [-- select_launch_llamacpp.py options]

Wrapper options:
  --check-only                  Read-only offer/cost check; do not launch.
  --skip-current-infra          With --check-only, skip current infra query.
  --top N                       With --check-only, show top N passing offers.
  --instance-id N               Bootstrap or inspect an already-created Vast instance.
  --no-bootstrap                Launch/inspect without bootstrapping llama.cpp.
  --yes                         Skip current-infra, launch, and bootstrap approval prompts.
  --help                        Show this help.

Profile:
  config/launch-profiles/deepseek-v4-flash-162b-gguf.pro6000ws-llamacpp.on-demand.json

Profile summary:
  Runtime: llama.cpp
  Model:   0xSero/DeepSeek-V4-Flash-162B-GGUF
  GGUF:    DeepSeek-V4-Flash-Spark-Mini-Q2-REAP-ds4.gguf
  GPU:     1x RTX PRO 6000 WS, min 90GB VRAM
  Served:  DeepSeek-V4-Flash-Spark-Mini
  Context: 200K / 200000
  Batch:   8192 tokens; parallel/max seqs = 1
  KV:      cache_ram=14G; K/V cache types q8_0 as llama.cpp fp8 approximation
  Spec:    disabled (SPECULATIVE_CONFIG empty)

Examples:
  scripts/launch_deepseek_v4_flash_162b_gguf_llamacpp_pro6000ws.sh --check-only --top 5
  scripts/launch_deepseek_v4_flash_162b_gguf_llamacpp_pro6000ws.sh
  scripts/launch_deepseek_v4_flash_162b_gguf_llamacpp_pro6000ws.sh --yes
EOF
}

SELECT_ARGS=(--launch-profile "$PROFILE")
PASSTHROUGH=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --help|-h)
      usage
      exit 0
      ;;
    --check-only|--skip-current-infra|--no-bootstrap)
      SELECT_ARGS+=("$1")
      shift
      ;;
    --top|--poll-timeout|--ssh-timeout|--bootstrap-timeout|--startup-timeout|--service-timeout|--rsync-timeout|--instance-id)
      if [[ $# -lt 2 ]]; then
        echo "ERROR: $1 requires a value" >&2
        exit 2
      fi
      SELECT_ARGS+=("$1" "$2")
      shift 2
      ;;
    --yes)
      SELECT_ARGS+=(--yes-current-infra --yes-launch --yes-bootstrap)
      shift
      ;;
    --)
      shift
      PASSTHROUGH+=("$@")
      break
      ;;
    *)
      PASSTHROUGH+=("$1")
      shift
      ;;
  esac
done

if [[ -f env.vast-management ]]; then
  # shellcheck disable=SC1091
  source env.vast-management
fi

if [[ -z "${VAST_API_KEY:-}" ]]; then
  echo "ERROR: VAST_API_KEY is not set. Source env.vast-management or create it locally." >&2
  exit 2
fi

if [[ ! -f "$PROFILE" ]]; then
  echo "ERROR: launch profile not found: $PROFILE" >&2
  exit 2
fi

echo "Launching/checking profile: $PROFILE"
echo "Command: ./run.sh scripts/select_launch_llamacpp.py ${SELECT_ARGS[*]} ${PASSTHROUGH[*]}"
exec ./run.sh scripts/select_launch_llamacpp.py "${SELECT_ARGS[@]}" "${PASSTHROUGH[@]}"
