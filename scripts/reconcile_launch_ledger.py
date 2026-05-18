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
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import launch_ledger
from vastai import VastAI


def safe_error(exc: Exception) -> str:
    response = getattr(exc, "response", None)
    if response is not None:
        return f"{type(exc).__name__} status={response.status_code} reason={response.reason}"
    text = str(exc).split("api_key=")[0]
    return f"{type(exc).__name__}: {text}"


def iso_from_epoch(value: Any) -> str | None:
    if value is None:
        return None
    try:
        return datetime.fromtimestamp(float(value), timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    except Exception:
        return None


def date_from_iso(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date().isoformat()
    except Exception:
        return None


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


def load_audit_delete_times(vast: VastAI) -> dict[int, dict[str, Any]]:
    """Return instance_id -> delete audit event details.

    Requires a Vast API key with audit-log permissions. The caller handles auth
    failures; do not include raw SDK URLs in error output because they contain
    query-string API keys.
    """
    events = vast.show_audit_logs()
    out: dict[int, dict[str, Any]] = {}
    for event in events or []:
        route = str(event.get("api_route") or "")
        if route != "api.instance_DELETE":
            continue
        args = event.get("args") or {}
        iid = args.get("instance_id") or args.get("contract_id")
        if iid is None:
            continue
        try:
            iid_int = int(iid)
        except Exception:
            continue
        deleted_at = iso_from_epoch(event.get("created_at"))
        if not deleted_at:
            continue
        prior = out.get(iid_int)
        if prior is None or deleted_at < str(prior.get("deleted_at")):
            out[iid_int] = {
                "deleted_at": deleted_at,
                "audit_id": event.get("id"),
                "api_route": route,
                "api_key_id": event.get("api_key_id"),
            }
    return out


def load_instance_charges(vast: VastAI, rows: list[sqlite3.Row]) -> dict[int, dict[str, Any]]:
    """Return instance_id -> Vast charge row for ledger rows.

    Uses the charges endpoint, not local estimates. This is billing history and
    may require elevated API permissions.
    """
    dates = [date_from_iso(row["created_at"]) for row in rows]
    dates = [d for d in dates if d]
    if not dates:
        return {}
    start_date = min(dates)
    end_date = datetime.now(timezone.utc).date().isoformat()
    params: dict[str, Any] = {
        "charges": True,
        "start_date": start_date,
        "end_date": end_date,
        "limit": 100,
        "charge_type": ["instance"],
    }
    charges: list[dict[str, Any]] = []
    while True:
        page = vast.show_invoices_v1(**params)
        charges.extend(page.get("results") or [])
        token = page.get("next_token")
        if not token:
            break
        params["next_token"] = token
    wanted = {int(row["instance_id"]) for row in rows}
    out: dict[int, dict[str, Any]] = {}
    for charge in charges:
        source = str(charge.get("source") or "")
        if not source.startswith("instance-"):
            continue
        try:
            iid = int(source.split("-", 1)[1])
        except Exception:
            continue
        if iid in wanted:
            out[iid] = charge
    return out


def charge_metric_payload(charge: dict[str, Any]) -> dict[str, float | int | None]:
    metrics: dict[str, float | int | None] = {
        "vast.billing.total_charge_usd": charge.get("amount"),
    }
    for item in charge.get("items") or []:
        typ = item.get("type")
        amount = item.get("amount")
        if typ:
            metrics[f"vast.billing.{typ}_charge_usd"] = amount
    return metrics


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
        help="with --write, mark active ledger rows absent from current Vast instances as destroyed only when Vast audit history confirms deletion",
    )
    parser.add_argument("--skip-history", action="store_true", help="do not query Vast audit/charge history")
    args = parser.parse_args()

    rows = active_ledger_rows(args.db)
    if not rows:
        print(f"No active ledger rows found in {args.db}")
        return 0

    vast = VastAI()
    current = vast.show_instances()
    by_id = {int(inst["id"]): inst for inst in current if inst.get("id") is not None}

    audit_deletes: dict[int, dict[str, Any]] = {}
    charges: dict[int, dict[str, Any]] = {}
    if not args.skip_history:
        try:
            audit_deletes = load_audit_delete_times(vast)
        except Exception as exc:
            print(f"WARN audit history unavailable: {safe_error(exc)}", file=sys.stderr)
        try:
            charges = load_instance_charges(vast, rows)
        except Exception as exc:
            print(f"WARN billing history unavailable: {safe_error(exc)}", file=sys.stderr)

    print(
        f"ledger_active_rows={len(rows)} vast_current_instances={len(current)} write={args.write} "
        f"history={'off' if args.skip_history else 'on'} audit_deletes={len(audit_deletes)} charge_rows={len(charges)}"
    )
    for row in rows:
        iid = int(row["instance_id"])
        info = by_id.get(iid)
        if info is None:
            delete_event = audit_deletes.get(iid)
            charge = charges.get(iid)
            history_bits = []
            if delete_event:
                history_bits.append(f"deleted_at={delete_event['deleted_at']}")
            if charge:
                history_bits.append(f"billed=${float(charge.get('amount') or 0):.4f}")
            history_text = " " + " ".join(history_bits) if history_bits else ""
            print(f"MISSING instance={iid} launch_key={row['launch_key']} ledger_status={row['lifecycle_status']}{history_text}")
            if args.write:
                launch_ledger.record_event(
                    instance_id=iid,
                    event_name="reconcile_not_seen",
                    source="reconcile",
                    details={
                        "previous_lifecycle_status": row["lifecycle_status"],
                        "history_delete_found": bool(delete_event),
                        "history_charge_found": bool(charge),
                    },
                    db_path=args.db,
                )
                if charge:
                    launch_ledger.record_metric_samples(
                        instance_id=iid,
                        source="vast_billing_history",
                        metrics=charge_metric_payload(charge),
                        details={
                            "source": charge.get("source"),
                            "description": charge.get("description"),
                            "start": charge.get("start"),
                            "end": charge.get("end"),
                        },
                        db_path=args.db,
                    )
                if args.mark_not_seen:
                    if delete_event:
                        launch_ledger.mark_destroyed(
                            instance_id=iid,
                            reason="vast_audit_instance_delete",
                            destroyed_by_script=False,
                            terminated_at=str(delete_event["deleted_at"]),
                            db_path=args.db,
                        )
                    else:
                        print(
                            f"WARN not marking instance={iid} destroyed: no Vast audit delete event found",
                            file=sys.stderr,
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
