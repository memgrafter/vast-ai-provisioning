#!/usr/bin/env bash
# Serve the reports directory so vendor/ paths resolve correctly.
# Usage: ./serve.sh [port]
#   Default port: 8080
#   Kill with Ctrl-C or: kill $(cat /tmp/reports-serve.pid)

set -euo pipefail

PORT="${1:-8080}"
DIR="$(cd "$(dirname "$0")" && pwd)"

echo "Serving reports from: $DIR"
echo "Report URL: http://$(hostname):${PORT}/reports/market-scan/market-scan.html"
echo "PID file:   /tmp/reports-serve.pid"
echo ""

cd "$DIR"
echo $$ > /tmp/reports-serve.pid
exec python3 -m http.server "$PORT"