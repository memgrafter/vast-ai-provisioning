#!/usr/bin/env bash
set -euo pipefail

# Simple external vLLM/OpenAI-compatible saturation ramp.
#
# Usage:
#   export OPENAI_API_KEY="$VLLM_API_KEY"
#   scripts/vllm_bench_saturation_ramp.sh \
#     http://194.26.196.169:15377 \
#     qwen3.6-35b-a3b-awq-coding-budget-160k
#
# Requires:
#   vllm bench serve --help
#
# Notes:
# - BASE_URL should be the server root, not /v1.
# - Watch server metrics separately while this runs.
# - Stop when queue/TTFT/errors rise too much.

BASE_URL="${1:?usage: $0 <base-url-without-/v1> <model>}"
MODEL="${2:?usage: $0 <base-url-without-/v1> <model>}"

: "${OPENAI_API_KEY:?set OPENAI_API_KEY to the vLLM API key}"

INPUT_LEN="${INPUT_LEN:-4096}"
OUTPUT_LEN="${OUTPUT_LEN:-1024}"
NUM_PROMPTS="${NUM_PROMPTS:-200}"
RATES="${RATES:-2 5 10 15 20 30 40}"
TOKENIZER="${TOKENIZER:-$MODEL}"

printf 'base_url=%s\nmodel=%s\ntokenizer=%s\ninput_len=%s\noutput_len=%s\nnum_prompts=%s\nrates=%s\n\n' \
  "$BASE_URL" "$MODEL" "$TOKENIZER" "$INPUT_LEN" "$OUTPUT_LEN" "$NUM_PROMPTS" "$RATES"

for RATE in $RATES; do
  echo "================================================================"
  echo "vLLM bench: request_rate=${RATE} req/s"
  echo "================================================================"

  vllm bench serve \
    --backend openai-chat \
    --base-url "$BASE_URL" \
    --endpoint /v1/chat/completions \
    --model "$MODEL" \
    --tokenizer "$TOKENIZER" \
    --dataset-name random \
    --random-input-len "$INPUT_LEN" \
    --random-output-len "$OUTPUT_LEN" \
    --num-prompts "$NUM_PROMPTS" \
    --request-rate "$RATE"

  echo
  echo "Completed request_rate=${RATE}. Press Enter for next step, Ctrl-C to stop."
  read -r _
done
