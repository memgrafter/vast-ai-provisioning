#!/usr/bin/env bash
set -euo pipefail

# Vast SSH/Jupyter launch modes override the Docker image entrypoint.
# This restores the official vastai/vllm startup path after Vast sets up SSH/Jupyter.
exec /opt/instance-tools/bin/entrypoint.sh
