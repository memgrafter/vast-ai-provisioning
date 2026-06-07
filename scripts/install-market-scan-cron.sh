#!/usr/bin/env bash
# Idempotent cron installer for scan_best_value_per_profile.py.
# Safe to re-run — it replaces any existing entry for this script.
# Uses mkdir-based lock to prevent overlapping scans (portable flock alternative).
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

SCRIPT="scripts/scan_best_value_per_profile.py"
LABEL="market-scan"
CRON_LOG="state/price-history/scan.log"
CRON_ENV_FILE="env.vast-management"
LOCK_DIR="state/price-history/.market-scan.lock"

REPO_DIR="$(pwd)"

# mkdir is atomic on macOS + Linux. If LOCK_DIR exists, prev scan is still running.
# || true prevents the whole cron command from failing on "skipped".
CRON_CMD='cd '"${REPO_DIR}"' && PATH=$HOME/.local/bin:$PATH . '"${REPO_DIR}/${CRON_ENV_FILE}"' && mkdir '"${REPO_DIR}/${LOCK_DIR}"' 2>/dev/null && ./run.sh '"${REPO_DIR}/${SCRIPT}"' --skip-interruptible >>'"${REPO_DIR}/${CRON_LOG}"' 2>&1; rmdir '"${REPO_DIR}/${LOCK_DIR}"' 2>/dev/null; true'

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