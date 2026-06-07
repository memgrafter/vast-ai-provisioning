#!/usr/bin/env python3
"""Refresh the market-scan report with fresh data from market_offers table.

Replaces the inline JSON data in the report HTML with the latest SQLite query.
Safe to re-run — idempotent, only touches the const D = [...] block.

Usage:
  ./run.sh scripts/refresh_market_report.py

Output:
  Updates ~/.agents/skills/quick-report/reports/market-scan/market-scan.html
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

REPORT = Path("reports/market-scan/market-scan.html")
DB = Path("state/launches.sqlite3")

QUERY = """
SELECT scanned_at, profile_name, gpu_name, num_gpus,
       dph_total, dph_per_gbhr, market, reliability2,
       verification, geolocation, inet_down_mbps, disk_bw,
       machine_id, offer_vast_id
FROM market_offers
ORDER BY scanned_at, profile_name
"""


def main() -> int:
    if not REPORT.exists():
        print(f"ERROR: report not found at {REPORT}", file=sys.stderr)
        return 1
    if not DB.exists():
        print(f"ERROR: database not found at {DB}", file=sys.stderr)
        return 1

    con = sqlite3.connect(str(DB))
    con.row_factory = sqlite3.Row
    rows = [dict(r) for r in con.execute(QUERY).fetchall()]
    con.close()

    if not rows:
        print("ERROR: no rows in market_offers table", file=sys.stderr)
        return 1

    fresh_json = json.dumps(rows)
    html = REPORT.read_text()

    # Find and replace const D = [...] block
    marker = "const D = "
    start = html.index(marker) + len(marker)
    end = html.index("];", start) + 1

    new_html = html[:start] + fresh_json + html[end:]
    REPORT.write_text(new_html)

    print(f"OK: refreshed {len(rows)} records in {REPORT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())