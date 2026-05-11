#!/usr/bin/env bash
set -euo pipefail

model_profile=""
stream="false"
while [ "$#" -gt 0 ]; do
  case "$1" in
    --model-profile)
      model_profile="${2:?missing value for --model-profile}"
      shift 2
      ;;
    --stream)
      stream="true"
      shift
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

cd "$(dirname "${BASH_SOURCE[0]}")"

if ! command -v uv >/dev/null 2>&1; then
  echo "ERROR: uv is required. Install from https://docs.astral.sh/uv/" >&2
  exit 1
fi

if [ ! -x .venv/bin/python ]; then
  uv venv --python 3 .venv
fi
uv pip install --python .venv/bin/python -U huggingface_hub hf_transfer awscli

source env.modeltransfer

if [ "$stream" = "true" ]; then
  exec .venv/bin/python scripts/stream_hf_model_to_r2.py --model-profile "$model_profile"
fi

profile_values="$(.venv/bin/python - "$model_profile" <<'PY'
import json
import sys
from pathlib import Path
profile = json.loads(Path(sys.argv[1]).read_text())
print(profile["hf_model_id"])
print(profile["r2_prefix"])
PY
)"
profile_hf_model_id="$(printf '%s\n' "$profile_values" | sed -n '1p')"
profile_r2_prefix="$(printf '%s\n' "$profile_values" | sed -n '2p')"

MODEL_DIR="./models/$profile_hf_model_id"
mkdir -p "$MODEL_DIR"

# Do not pass HF_TOKEN as a CLI argument; process listings can expose argv.
# The Hugging Face CLI reads HF_TOKEN from the environment after env.modeltransfer is sourced.
.venv/bin/hf download "$profile_hf_model_id" \
  --local-dir "$MODEL_DIR"

.venv/bin/aws s3 sync "$MODEL_DIR" "s3://$R2_BUCKET/$profile_r2_prefix" \
  --endpoint-url "$R2_ENDPOINT"
