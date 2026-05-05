#!/usr/bin/env bash
set -euo pipefail

model_profile=""
while [ "$#" -gt 0 ]; do
  case "$1" in
    --model-profile)
      model_profile="${2:?missing value for --model-profile}"
      shift 2
      ;;
    *)
      echo "ERROR: unknown argument: $1" >&2
      exit 2
      ;;
  esac
done

if [ -z "$model_profile" ]; then
  echo "ERROR: --model-profile is required" >&2
  exit 2
fi

source env.modeltransfer
pip install -U huggingface_hub hf_transfer awscli

profile_values="$(python3 - "$model_profile" <<'PY'
import json
import sys
from pathlib import Path
profile = json.loads(Path(sys.argv[1]).read_text())
print(profile["hf_model_id"])
print(profile["r2_prefix"])
PY
)"
HF_REPO_ID="$(printf '%s\n' "$profile_values" | sed -n '1p')"
R2_PREFIX="$(printf '%s\n' "$profile_values" | sed -n '2p')"

MODEL_DIR="./models/$HF_REPO_ID"
mkdir -p "$MODEL_DIR"

hf download "$HF_REPO_ID" \
  --local-dir "$MODEL_DIR" \
  ${HF_TOKEN:+--token "$HF_TOKEN"}

aws s3 sync "$MODEL_DIR" "s3://$R2_BUCKET/$R2_PREFIX" \
  --endpoint-url "$R2_ENDPOINT"
