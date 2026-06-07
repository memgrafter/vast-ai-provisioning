#!/usr/bin/env bash
# Idempotent cron installer for scan_best_value_per_profile.py.
# Safe to re-run — it replaces any existing entry for this script.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

SCRIPT="scripts/scan_best_value_per_profile.py"
LABEL="market-scan"
CRON_LOG="state/price-history/scan.log"
CRON_ENV_FILE="env.vast-management"

REPO_DIR="$(pwd)"

# Use single-quoted PATH so $HOME resolves at cron runtime, not script-write time.
CRON_CMD='cd '"${REPO_DIR}"' && PATH=$HOME/.local/bin:$PATH . '"${REPO_DIR}/${CRON_ENV_FILE}"' && ./run.sh '"${REPO_DIR}/${SCRIPT}"' --skip-interruptible >>'"${REPO_DIR}/${CRON_LOG}"' 2>&1'

# Default to every 1 minute. To change, pass CRON_SCHED as an env var:
#   CRON_SCHED="*/5 * * * *" ./install-cron.sh
CRON_SCHED="${CRON_SCHED:-* * * * *}"

CRON_LINE="${CRON_SCHED} ${CRON_CMD} # ${LABEL}"

mkdir -p "$(dirname "${REPO_DIR}/${CRON_LOG}")"

if crontab -l 2>/dev/null | grep -q "# ${LABEL}$"; then
  echo "Updating existing cron entry for ${LABEL}..."
  (crontab -l 2>/dev/null | grep -v "# ${LABEL}$"; echo "${CRON_LINE}") | crontab -
else
  echo "Installing new cron entry for ${LABEL}..."
  (crontab -l 2>/dev/null || true; echo "${CRON_LINE}") | crontab -
fi

echo "Cron installed:"
echo "  ${CRON_LINE}"
echo
echo "Logs go to: ${CRON_LOG}"
echo
echo "To change the schedule, re-run with:"
echo "  CRON_SCHED='*/5 * * * *' ./scripts/install-market-scan-cron.sh"
