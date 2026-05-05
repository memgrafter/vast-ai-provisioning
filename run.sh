#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"

if ! command -v uv >/dev/null 2>&1; then
  echo "uv is required. Install from https://docs.astral.sh/uv/" >&2
  exit 1
fi

uv venv --python 3 .venv
uv pip install --python .venv/bin/python -e .

if [ "$#" -gt 0 ]; then
  exec .venv/bin/python "$@"
fi

cat <<'EOF'
Environment ready.

Activate with:
  source .venv/bin/activate

Or run a Python script with:
  ./run.sh path/to/script.py
EOF
