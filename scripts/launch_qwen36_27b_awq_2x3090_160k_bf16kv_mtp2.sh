#!/usr/bin/env bash
# Launch the validated Qwen3.6 27B AWQ vLLM profile on Vast 2x RTX 3090.
#
# Defaults are intentionally prompt-guarded by scripts/select_and_launch.py:
#   - prints current infra/cost first
#   - asks before offer search
#   - asks again before launch
#
# Common usage:
#   scripts/launch_qwen36_27b_awq_2x3090_160k_bf16kv_mtp2.sh --check-only --top 3
#   scripts/launch_qwen36_27b_awq_2x3090_160k_bf16kv_mtp2.sh
#   scripts/launch_qwen36_27b_awq_2x3090_160k_bf16kv_mtp2.sh --yes
#
# Pass any extra scripts/select_and_launch.py flags after these wrapper options.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

PROFILE="config/launch-profiles/qwen3.6-27b-awq.rtx3090-2gpu-160k-bf16kv-mtp2.on-demand.json"

usage() {
  cat <<'EOF'
Usage: scripts/launch_qwen36_27b_awq_2x3090_160k_bf16kv_mtp2.sh [wrapper-options] [-- select_and_launch.py options]

Wrapper options:
  --check-only                  Read-only offer/cost check; do not launch.
  --skip-current-infra          With --check-only, skip current infra query.
  --top N                       With --check-only, show top N passing offers.
  --dry-run                     Select and print one offer, then exit before launch.
  --yes                         Skip both launch approval prompts.
  --no-monitor                  Do not run readiness monitor after launch.
  --no-smoke-chat               Do not run post-readiness chat smoke test.
  --smoke-timeout N             Max seconds for post-launch models/chat smoke polling.
  --smoke-chat-timeout N        Max seconds for each smoke chat request.
  --smoke-max-tokens N          Max generated tokens for smoke chat; default is small/fast.
  --no-destroy-on-monitor-fail  Leave failed monitored launches running.
  --relax-policy JSON           Deep-merge a policy override into this run.
  --help                        Show this help.

Profile:
  config/launch-profiles/qwen3.6-27b-awq.rtx3090-2gpu-160k-bf16kv-mtp2.on-demand.json

Profile summary:
  Runtime: vLLM
  Model:   QuantTrio/Qwen3.6-27B-AWQ
  GPUs:    2x RTX 3090
  Context: 160k
  TP:      2
  Quant:   awq_marlin
  KV:      bfloat16
  MTP:     qwen3_next_mtp, 2 speculative tokens
  Verified: required
  Cost cap from profile: max_dph_total <= 0.60

Examples:
  scripts/launch_qwen36_27b_awq_2x3090_160k_bf16kv_mtp2.sh --check-only --top 3
  scripts/launch_qwen36_27b_awq_2x3090_160k_bf16kv_mtp2.sh --check-only --relax-policy '{"storage":{"min_disk_bw":300}}'
  scripts/launch_qwen36_27b_awq_2x3090_160k_bf16kv_mtp2.sh
  scripts/launch_qwen36_27b_awq_2x3090_160k_bf16kv_mtp2.sh --yes --monitor-timeout 2400
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
    --check-only|--skip-current-infra|--dry-run|--no-monitor|--no-smoke-chat|--no-destroy-on-monitor-fail)
      SELECT_ARGS+=("$1")
      shift
      ;;
    --top|--poll-timeout|--monitor-timeout|--monitor-interval|--smoke-message|--smoke-timeout|--smoke-interval|--smoke-chat-timeout|--smoke-max-tokens|--relax-policy)
      if [[ $# -lt 2 ]]; then
        echo "ERROR: $1 requires a value" >&2
        exit 2
      fi
      SELECT_ARGS+=("$1" "$2")
      shift 2
      ;;
    --yes)
      SELECT_ARGS+=(--yes-current-infra --yes-launch)
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
echo "Command: ./run.sh scripts/select_and_launch.py ${SELECT_ARGS[*]} ${PASSTHROUGH[*]}"
exec ./run.sh scripts/select_and_launch.py "${SELECT_ARGS[@]}" "${PASSTHROUGH[@]}"
