#!/usr/bin/env python3
"""Reconcile local launch ledger rows with current Vast instance state.

This is intentionally conservative:
- It only uses read-only Vast SDK calls.
- It never destroys or mutates Vast instances.
- By default it prints a plan. Use --write to update the local sqlite ledger.
- Missing instances are not marked destroyed unless --mark-not-seen is provided,
  because Vast/API visibility can be intermittent.
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import launch_ledger
from vastai import VastAI


def active_ledger_rows(db_path: Path) -> list[sqlite3.Row]:
    if not db_path.exists():
        return []
    con = launch_ledger.open_readonly_db(db_path)
    try:
        return list(
            con.execute(
                """
                SELECT launch_key, instance_id, lifecycle_status, created_at,
                       launch_profile_name, model_profile_name, gpu_profile_name
                FROM launches
                WHERE terminated_at IS NULL
                  AND COALESCE(lifecycle_status, '') != 'destroyed'
                ORDER BY created_at DESC
                """
            )
        )
    finally:
        con.close()


def instance_status(info: dict[str, Any]) -> str:
    return str(info.get("actual_status") or info.get("status") or info.get("cur_state") or "unknown")


def metric_payload(info: dict[str, Any]) -> dict[str, float | int | None]:
    duration = info.get("duration")
    if duration is None and info.get("start_date"):
        # Vast commonly returns duration directly. Avoid wall-clock inference if absent.
        duration = None
    return {
        "vast.dph_total": info.get("dph_total"),
        "vast.cur_state_dph": info.get("cur_state_dph"),
        "vast.storage_total_cost_per_hour": info.get("storage_total_cost"),
        "vast.duration_seconds": duration,
        "vast.gpu_utilization_percent": info.get("gpu_util"),
        "vast.gpu_memory_used_mb": info.get("gpu_mem_usage"),
        "vast.disk_usage_gb": info.get("disk_usage"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Reconcile launch ledger with current Vast instance status")
    parser.add_argument("--db", type=Path, default=launch_ledger.DEFAULT_DB_PATH)
    parser.add_argument("--write", action="store_true", help="write local ledger updates; default only prints")
    parser.add_argument(
        "--mark-not-seen",
        action="store_true",
        help="with --write, record reconcile_not_seen event for ledger rows absent from current Vast instances",
    )
    args = parser.parse_args()

    rows = active_ledger_rows(args.db)
    if not rows:
        print(f"No active ledger rows found in {args.db}")
        return 0

    vast = VastAI()
    current = vast.show_instances()
    by_id = {int(inst["id"]): inst for inst in current if inst.get("id") is not None}

    print(f"ledger_active_rows={len(rows)} vast_current_instances={len(current)} write={args.write}")
    for row in rows:
        iid = int(row["instance_id"])
        info = by_id.get(iid)
        if info is None:
            print(f"MISSING instance={iid} launch_key={row['launch_key']} ledger_status={row['lifecycle_status']}")
            if args.write and args.mark_not_seen:
                launch_ledger.record_event(
                    instance_id=iid,
                    event_name="reconcile_not_seen",
                    source="reconcile",
                    details={"previous_lifecycle_status": row["lifecycle_status"]},
                    db_path=args.db,
                )
            continue

        status = instance_status(info)
        print(
            f"FOUND instance={iid} status={status} gpu={info.get('gpu_name')} "
            f"dph={info.get('dph_total')} storage={info.get('storage_total_cost')} "
            f"duration={info.get('duration')}"
        )
        if args.write:
            launch_ledger.update_instance_snapshot(
                instance_id=iid,
                info=info,
                instance_json_path=Path("instances") / f"{iid}.json",
                db_path=args.db,
            )
            launch_ledger.record_metric_samples(
                instance_id=iid,
                source="vast_reconcile",
                metrics=metric_payload(info),
                details={"status": status, "machine_id": info.get("machine_id"), "gpu_name": info.get("gpu_name")},
                db_path=args.db,
            )
            launch_ledger.record_event(
                instance_id=iid,
                event_name="reconcile_seen",
                source="reconcile",
                details={"status": status},
                db_path=args.db,
            )

    if not args.write:
        print("Dry run only. Re-run with --write to update local ledger metrics/events.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
