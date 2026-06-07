#!/usr/bin/env python3
"""Migration 001: Add market_offers table for minutely price-scan time series.

Creates the market_offers table in the existing launch ledger SQLite database.
Safe to re-run (CREATE TABLE IF NOT EXISTS).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts import launch_ledger

MIGRATION_SQL = """
CREATE TABLE IF NOT EXISTS market_offers (
  offer_id      INTEGER PRIMARY KEY AUTOINCREMENT,
  scanned_at    TEXT NOT NULL,              -- UTC ISO-8601, when the scan ran
  source        TEXT NOT NULL DEFAULT 'market_scan',

  -- Profile identity
  profile_name  TEXT NOT NULL,
  profile_path  TEXT NOT NULL,
  market        TEXT NOT NULL,              -- on-demand / interruptible

  -- Offer snapshot (best passing offer for this profile this scan)
  gpu_name             TEXT,
  num_gpus             INTEGER,
  gpu_total_ram_mb     REAL,
  dph_total            REAL,
  dph_base             REAL,
  dph_per_gbhr         REAL,
  storage_hour         REAL,
  compute_hour         REAL,
  reliability2         REAL,
  verification         TEXT,
  inet_down_mbps       REAL,
  disk_bw              REAL,
  geolocation          TEXT,
  machine_id           INTEGER,
  offer_vast_id        INTEGER,
  cuda_max_good        REAL,
  inet_down_cost_per_tb REAL,

  -- Policy gates applied
  policy_max_dph_total          REAL,
  policy_min_reliability2       REAL,

  -- Signal column: 1 = cheapest passing offer for this (profile, scan) pair
  is_best INTEGER NOT NULL DEFAULT 1
);

CREATE INDEX IF NOT EXISTS idx_market_offers_time
  ON market_offers(scanned_at);

CREATE INDEX IF NOT EXISTS idx_market_offers_profile_time
  ON market_offers(profile_name, scanned_at);

CREATE INDEX IF NOT EXISTS idx_market_offers_gpu_time
  ON market_offers(gpu_name, num_gpus, scanned_at);
"""


def main() -> int:
    db_path = launch_ledger.DEFAULT_DB_PATH
    con = launch_ledger.init_db(db_path)
    try:
        con.executescript(MIGRATION_SQL)
        con.commit()
        print(f"OK: market_offers table ready in {db_path}")
    except Exception as exc:
        print(f"ERROR: migration failed: {exc}", file=sys.stderr)
        return 1
    finally:
        con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())