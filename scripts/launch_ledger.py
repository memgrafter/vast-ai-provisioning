#!/usr/bin/env python3
"""SQLite launch ledger helpers.

The launch ledger is analytics/audit state only. It must not drive launch
selection or runtime behavior.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_DB_PATH = Path(os.environ.get("LAUNCH_LEDGER_DB", "state/launches.sqlite3"))
SCHEMA_PATH = Path("docs/launch-ledger-schema.sql")
BUSY_TIMEOUT_MS = int(os.environ.get("LAUNCH_LEDGER_BUSY_TIMEOUT_MS", "30000"))
SQLITE_TIMEOUT_SECONDS = BUSY_TIMEOUT_MS / 1000.0


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def launch_key(instance_id: int | str, provider: str = "vast") -> str:
    return f"{provider}:instance:{int(instance_id)}"


def file_sha256(path: str | Path | None) -> str | None:
    if not path:
        return None
    p = Path(path)
    if not p.exists():
        return None
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def configure_connection(con: sqlite3.Connection, *, writable: bool) -> sqlite3.Connection:
    con.row_factory = sqlite3.Row
    con.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
    con.execute("PRAGMA foreign_keys = ON")
    if writable:
        # Every writer opts into the same journal mode so concurrent CLI tools
        # serialize safely and readers can continue while short writes commit.
        con.execute("PRAGMA journal_mode = WAL")
        con.execute("PRAGMA synchronous = NORMAL")
    else:
        con.execute("PRAGMA query_only = ON")
    return con


def init_db(db_path: Path = DEFAULT_DB_PATH, schema_path: Path = SCHEMA_PATH) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db_path, timeout=SQLITE_TIMEOUT_SECONDS)
    configure_connection(con, writable=True)
    con.executescript(schema_path.read_text())
    return con


def open_readonly_db(db_path: Path = DEFAULT_DB_PATH) -> sqlite3.Connection:
    # Open a normal connection, then force query_only. SQLite WAL databases may
    # need to create/read shared-memory sidecar state; URI mode=ro can fail for
    # that case even though the caller only intends reads.
    con = sqlite3.connect(db_path, timeout=SQLITE_TIMEOUT_SECONDS)
    return configure_connection(con, writable=False)


def bool_int(value: Any) -> int | None:
    if value is None:
        return None
    return int(bool(value))


def finite_or_none(value: Any) -> float | None:
    try:
        out = float(value)
    except Exception:
        return None
    return out if math.isfinite(out) else None


def storage_metrics(offer: dict[str, Any], launch: dict[str, Any]) -> dict[str, float | None]:
    storage = launch["storage"]
    requested_gb = finite_or_none(storage.get("disk_gb"))
    storage_hour = finite_or_none(offer.get("storage_total_cost"))
    total_hour = finite_or_none(offer.get("dph_total"))
    storage_per_gb = None
    storage_fraction = None
    compute_hour = None
    if requested_gb and requested_gb > 0 and storage_hour is not None:
        storage_per_gb = storage_hour / requested_gb
    if total_hour and total_hour > 0 and storage_hour is not None:
        storage_fraction = storage_hour / total_hour
        compute_hour = max(0.0, total_hour - storage_hour)
    return {
        "requested_gb": requested_gb,
        "storage_hour": storage_hour,
        "storage_per_gb_hour": storage_per_gb,
        "storage_fraction": storage_fraction,
        "compute_hour": compute_hour,
    }


def instance_status(info: dict[str, Any]) -> str:
    return str(info.get("actual_status") or info.get("status") or "unknown")


def profile_name(profile: dict[str, Any], fallback_path: str | None) -> str | None:
    return profile.get("name") or (Path(fallback_path).stem if fallback_path else None)


def _insert_or_update(con: sqlite3.Connection, row: dict[str, Any]) -> None:
    columns = list(row)
    placeholders = ", ".join([":" + c for c in columns])
    assignments = ", ".join([f"{c}=excluded.{c}" for c in columns if c != "launch_key"])
    sql = f"""
        INSERT INTO launches ({', '.join(columns)})
        VALUES ({placeholders})
        ON CONFLICT(launch_key) DO UPDATE SET {assignments}
    """
    con.execute(sql, row)
    con.commit()


def record_event(
    *,
    instance_id: int | str,
    event_name: str,
    event_at: str | None = None,
    source: str,
    details: dict[str, Any] | None = None,
    db_path: Path = DEFAULT_DB_PATH,
) -> None:
    con = init_db(db_path)
    try:
        con.execute(
            """
            INSERT OR IGNORE INTO launch_events (launch_key, event_name, event_at, source, details_json)
            VALUES (:launch_key, :event_name, :event_at, :source, :details_json)
            """,
            {
                "launch_key": launch_key(instance_id),
                "event_name": event_name,
                "event_at": event_at or now_utc(),
                "source": source,
                "details_json": json.dumps(details, sort_keys=True, default=str) if details else None,
            },
        )
        con.commit()
    finally:
        con.close()


def record_metric_samples(
    *,
    instance_id: int | str,
    source: str,
    metrics: dict[str, float | int | None],
    sampled_at: str | None = None,
    labels: dict[str, Any] | None = None,
    details: dict[str, Any] | None = None,
    db_path: Path = DEFAULT_DB_PATH,
) -> None:
    t = sampled_at or now_utc()
    labels_json = json.dumps(labels, sort_keys=True, default=str) if labels else None
    details_json = json.dumps(details, sort_keys=True, default=str) if details else None
    rows = []
    for name, value in metrics.items():
        rows.append(
            {
                "launch_key": launch_key(instance_id),
                "sampled_at": t,
                "source": source,
                "metric_name": name,
                "metric_value": finite_or_none(value),
                "labels_json": labels_json,
                "details_json": details_json,
            }
        )
    if not rows:
        return
    con = init_db(db_path)
    try:
        con.executemany(
            """
            INSERT INTO launch_metric_samples
              (launch_key, sampled_at, source, metric_name, metric_value, labels_json, details_json)
            VALUES
              (:launch_key, :sampled_at, :source, :metric_name, :metric_value, :labels_json, :details_json)
            """,
            rows,
        )
        con.commit()
    finally:
        con.close()


def record_created_launch(
    *,
    context: dict[str, Any],
    offer: dict[str, Any],
    create_result: dict[str, Any],
    instance_id: int | str,
    selected_offer_json_path: str | Path | None = None,
    create_started_at: str | None = None,
    create_returned_at: str | None = None,
    db_path: Path = DEFAULT_DB_PATH,
) -> None:
    """Insert/update the golden row immediately after Vast create_instance."""
    launch = context["launch"]
    model = context["model"]
    gpu = context["gpu"]
    storage = launch["storage"]
    pricing = launch.get("pricing", {})
    spot = launch.get("spot", {})
    vllm = model.get("vllm", {})
    sm = storage_metrics(offer, launch)
    expected_tb = finite_or_none(launch.get("selection", {}).get("expected_model_download_tb", model.get("expected_model_download_tb", 0))) or 0.0
    down_cost = finite_or_none(offer.get("internet_down_cost_per_tb")) or 0.0
    dph_total = finite_or_none(offer.get("dph_total"))
    smoke_minutes = finite_or_none(pricing.get("target_first_test_minutes", 10)) or 0.0
    est_runtime = (dph_total or 0.0) * smoke_minutes / 60.0
    est_pull = expected_tb * down_cost
    iid = int(instance_id)
    t = now_utc()
    row: dict[str, Any] = {
        "launch_key": launch_key(iid),
        "provider": "vast",
        "instance_id": iid,
        "offer_id": offer.get("id"),
        "machine_id": offer.get("machine_id"),
        "created_at": t,
        "last_seen_at": t,
        "lifecycle_status": "created",
        "destroyed_by_script": 0,
        "launch_profile_name": launch.get("name") or profile_name(launch, context.get("launch_profile_path")),
        "launch_profile_path": context.get("launch_profile_path"),
        "launch_profile_sha256": file_sha256(context.get("launch_profile_path")),
        "model_profile_name": profile_name(model, context.get("model_profile_path")),
        "model_profile_path": context.get("model_profile_path"),
        "model_profile_sha256": file_sha256(context.get("model_profile_path")),
        "gpu_profile_name": profile_name(gpu, context.get("gpu_profile_path")),
        "gpu_profile_path": context.get("gpu_profile_path"),
        "gpu_profile_sha256": file_sha256(context.get("gpu_profile_path")),
        "template_name": launch.get("template", {}).get("name"),
        "template_hash_id": launch.get("template", {}).get("hash_id"),
        "hf_model_id": model.get("hf_model_id"),
        "served_model_name": model.get("served_model_name"),
        "quantization": model.get("quantization"),
        "dtype": vllm.get("dtype"),
        "max_model_len": vllm.get("max_model_len"),
        "gpu_memory_utilization": vllm.get("gpu_memory_utilization"),
        "expected_model_download_tb": expected_tb,
        "market": launch.get("market"),
        "gpu_name": offer.get("gpu_name"),
        "num_gpus": offer.get("num_gpus"),
        "gpu_total_ram_mb": offer.get("gpu_total_ram"),
        "cuda_max_good": offer.get("cuda_max_good"),
        "driver_version": offer.get("driver_version"),
        "verification": offer.get("verification"),
        "reliability2": offer.get("reliability2"),
        "disk_available_gb": offer.get("disk_space"),
        "disk_bw": offer.get("disk_bw") or offer.get("disk_io"),
        "inet_down_mbps": offer.get("inet_down"),
        "inet_up_mbps": offer.get("inet_up"),
        "direct_port_count": offer.get("direct_port_count"),
        "requested_disk_gb": sm["requested_gb"],
        "storage_total_cost_per_hour": sm["storage_hour"],
        "storage_cost_per_requested_gb_hour": sm["storage_per_gb_hour"],
        "storage_fraction_of_total": sm["storage_fraction"],
        "policy_max_storage_total_cost_per_hour": storage.get("max_storage_total_cost_per_hour"),
        "policy_max_storage_cost_per_gb_hour": storage.get("max_storage_cost_per_gb_hour"),
        "policy_max_storage_fraction_of_total": storage.get("max_storage_fraction_of_total"),
        "policy_warn_storage_fraction_of_total": storage.get("warn_storage_fraction_of_total"),
        "dph_base": offer.get("dph_base"),
        "dph_total": dph_total,
        "compute_cost_per_hour": sm["compute_hour"],
        "internet_down_cost_per_tb": offer.get("internet_down_cost_per_tb"),
        "internet_up_cost_per_tb": offer.get("internet_up_cost_per_tb"),
        "spot_bid_dph": spot.get("max_bid_dph") if launch.get("market") in {"interruptible", "bid", "spot"} else None,
        "estimated_pull_cost_usd": est_pull,
        "estimated_runtime_cost_usd": est_runtime,
        "estimated_total_cost_usd": est_pull + est_runtime,
        "selected_offer_json_path": str(selected_offer_json_path) if selected_offer_json_path else None,
        "updated_at": t,
    }
    # Keep a small non-secret pointer to the create result for debugging if the
    # SDK returned an unexpected instance id; do not store raw create_result.
    if create_result.get("success") is False:
        row["error_summary"] = str(create_result)[:1000]
    con = init_db(db_path)
    try:
        _insert_or_update(con, row)
    finally:
        con.close()
    if create_started_at:
        record_event(
            instance_id=iid,
            event_name="launch_requested",
            event_at=create_started_at,
            source="select_and_launch",
            details={"offer_id": offer.get("id"), "machine_id": offer.get("machine_id")},
            db_path=db_path,
        )
    record_event(
        instance_id=iid,
        event_name="sdk_create_returned",
        event_at=create_returned_at or t,
        source="select_and_launch",
        details={"create_success": create_result.get("success"), "offer_id": offer.get("id")},
        db_path=db_path,
    )


def update_instance_snapshot(
    *,
    instance_id: int | str,
    info: dict[str, Any],
    instance_json_path: str | Path | None = None,
    db_path: Path = DEFAULT_DB_PATH,
) -> None:
    iid = int(instance_id)
    status = instance_status(info)
    t = now_utc()
    lifecycle = "running" if status == "running" else status
    con = init_db(db_path)
    try:
        con.execute(
            """
            UPDATE launches
            SET last_seen_at = :now,
                running_at = CASE WHEN :status = 'running' AND running_at IS NULL THEN :now ELSE running_at END,
                lifecycle_status = :lifecycle_status,
                machine_id = COALESCE(:machine_id, machine_id),
                gpu_name = COALESCE(:gpu_name, gpu_name),
                instance_json_path = COALESCE(:instance_json_path, instance_json_path),
                updated_at = :now
            WHERE launch_key = :launch_key
            """,
            {
                "now": t,
                "status": status,
                "lifecycle_status": lifecycle,
                "machine_id": info.get("machine_id"),
                "gpu_name": info.get("gpu_name"),
                "instance_json_path": str(instance_json_path) if instance_json_path else None,
                "launch_key": launch_key(iid),
            },
        )
        con.commit()
    finally:
        con.close()
    if status == "running":
        record_event(instance_id=iid, event_name="instance_running", event_at=t, source="poll_instance", db_path=db_path)


def update_monitor_result(
    *,
    instance_id: int | str,
    monitor_exit_code: int | None = None,
    signals: dict[str, Any] | None = None,
    monitor_json_path: str | Path | None = None,
    logs_path: str | Path | None = None,
    lifecycle_status: str | None = None,
    error_summary: str | None = None,
    db_path: Path = DEFAULT_DB_PATH,
) -> None:
    iid = int(instance_id)
    signals = signals or {}
    t = now_utc()
    api_ready = bool(signals.get("api_ready"))
    vllm_started = bool(signals.get("vllm_started"))
    ready = api_ready or vllm_started
    lifecycle = lifecycle_status or ("ready" if ready else None)
    con = init_db(db_path)
    try:
        con.execute(
            """
            UPDATE launches
            SET last_seen_at = :now,
                ready_at = CASE WHEN :ready = 1 AND ready_at IS NULL THEN :now ELSE ready_at END,
                lifecycle_status = COALESCE(:lifecycle_status, lifecycle_status),
                image_cached = COALESCE(:image_cached, image_cached),
                provisioning_started = COALESCE(:provisioning_started, provisioning_started),
                r2_sync_started = COALESCE(:r2_sync_started, r2_sync_started),
                r2_sync_finished = COALESCE(:r2_sync_finished, r2_sync_finished),
                provisioning_complete = COALESCE(:provisioning_complete, provisioning_complete),
                vllm_started = COALESCE(:vllm_started, vllm_started),
                api_ready = COALESCE(:api_ready, api_ready),
                speed_test_failed = COALESCE(:speed_test_failed, speed_test_failed),
                provisioning_failed = COALESCE(:provisioning_failed, provisioning_failed),
                monitor_exit_code = COALESCE(:monitor_exit_code, monitor_exit_code),
                monitor_json_path = COALESCE(:monitor_json_path, monitor_json_path),
                logs_path = COALESCE(:logs_path, logs_path),
                error_summary = COALESCE(:error_summary, error_summary),
                updated_at = :now
            WHERE launch_key = :launch_key
            """,
            {
                "now": t,
                "ready": int(ready),
                "lifecycle_status": lifecycle,
                "image_cached": bool_int(signals.get("image_cached")),
                "provisioning_started": bool_int(signals.get("provisioning_started")),
                "r2_sync_started": bool_int(signals.get("r2_sync_started")),
                "r2_sync_finished": bool_int(signals.get("r2_sync_finished")),
                "provisioning_complete": bool_int(signals.get("provisioning_complete")),
                "vllm_started": bool_int(signals.get("vllm_started")),
                "api_ready": bool_int(signals.get("api_ready")),
                "speed_test_failed": bool_int(signals.get("speed_test_failed")),
                "provisioning_failed": bool_int(signals.get("provisioning_failed")),
                "monitor_exit_code": monitor_exit_code,
                "monitor_json_path": str(monitor_json_path) if monitor_json_path else None,
                "logs_path": str(logs_path) if logs_path else None,
                "error_summary": error_summary,
                "launch_key": launch_key(iid),
            },
        )
        con.commit()
    finally:
        con.close()
    event_names = [
        "image_pull_seen",
        "image_cached",
        "provisioning_started",
        "r2_sync_started",
        "r2_transfer_active",
        "r2_sync_finished",
        "provisioning_complete",
        "vllm_started",
        "api_ready",
        "speed_test_failed",
        "provisioning_failed",
    ]
    for name in event_names:
        if signals.get(name):
            record_event(instance_id=iid, event_name=name, event_at=t, source="monitor", db_path=db_path)


def update_smoke_result(
    *,
    instance_id: int | str,
    smoke_exit_code: int,
    db_path: Path = DEFAULT_DB_PATH,
) -> None:
    t = now_utc()
    con = init_db(db_path)
    try:
        con.execute(
            """
            UPDATE launches
            SET smoke_exit_code = :smoke_exit_code,
                ready_at = CASE WHEN :smoke_exit_code = 0 AND ready_at IS NULL THEN :now ELSE ready_at END,
                lifecycle_status = CASE WHEN :smoke_exit_code = 0 THEN 'ready' ELSE lifecycle_status END,
                last_seen_at = :now,
                updated_at = :now
            WHERE launch_key = :launch_key
            """,
            {
                "smoke_exit_code": smoke_exit_code,
                "now": t,
                "launch_key": launch_key(instance_id),
            },
        )
        con.commit()
    finally:
        con.close()
    record_event(
        instance_id=instance_id,
        event_name="smoke_passed" if smoke_exit_code == 0 else "smoke_failed",
        event_at=t,
        source="smoke_chat",
        details={"smoke_exit_code": smoke_exit_code},
        db_path=db_path,
    )


def mark_destroyed(
    *,
    instance_id: int | str,
    reason: str,
    destroyed_by_script: bool = False,
    db_path: Path = DEFAULT_DB_PATH,
) -> None:
    t = now_utc()
    con = init_db(db_path)
    try:
        con.execute(
            """
            UPDATE launches
            SET terminated_at = COALESCE(terminated_at, :now),
                last_seen_at = :now,
                lifecycle_status = 'destroyed',
                termination_reason = :reason,
                destroyed_by_script = :destroyed_by_script,
                updated_at = :now
            WHERE launch_key = :launch_key
            """,
            {
                "now": t,
                "reason": reason,
                "destroyed_by_script": int(destroyed_by_script),
                "launch_key": launch_key(instance_id),
            },
        )
        con.commit()
    finally:
        con.close()
    record_event(
        instance_id=instance_id,
        event_name="instance_destroyed",
        event_at=t,
        source="monitor" if destroyed_by_script else "manual_or_reconcile",
        details={"reason": reason, "destroyed_by_script": destroyed_by_script},
        db_path=db_path,
    )
