#!/usr/bin/env bash
set -euo pipefail

suite="${1:-all}"
case "$suite" in
  all|unit|integration) ;;
  *) echo "usage: $0 [all|unit|integration]" >&2; exit 2 ;;
esac

export PYTHONPATH="${PWD}:${PYTHONPATH:-}"

run_unit() {
  echo "== unit tests =="
  .venv/bin/python -m unittest discover -s tests/unit -p 'test_*.py'
}

run_integration() {
  echo "== integration tests =="
  .venv/bin/python -m unittest discover -s tests/integration -p 'test_*.py'
}

if [ "$suite" = "unit" ] || [ "$suite" = "all" ]; then
  run_unit
fi
if [ "$suite" = "integration" ] || [ "$suite" = "all" ]; then
  run_integration
fi
