#!/usr/bin/env python3
"""Capture final metrics/logs, then destroy a Vast instance and update ledger state.

This is the preferred closeout path for benchmark/serving rentals:

    . env.vast-management
    ./run.sh scripts/clean_terminate_instance.py --instance-id <id> --yes

It saves local artifacts under ignored state/terminate/, records final vLLM metrics
when available, stores a log tail, destroys the instance, and marks the launch
ledger row destroyed after the Vast destroy call returns.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import launch_ledger
from scripts import summarize_vllm_metrics
from vastai import VastAI


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True, default=str) + "\n")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text + ("" if text.endswith("\n") else "\n"))


def record_current_metrics(args: argparse.Namespace, api_key: str | None, out_dir: Path) -> None:
    endpoint = summarize_vllm_metrics.MetricsEndpoint(
        metrics_url=None,
        base_url=None,
        instance_id=args.instance_id,
        container_port=args.container_port,
    )

    def fetch_parsed() -> summarize_vllm_metrics.Metrics:
        text = summarize_vllm_metrics.fetch_metrics(endpoint, api_key, args.timeout)
        write_text(out_dir / "vllm.metrics.prom", text)
        return summarize_vllm_metrics.parse_metrics(text)

    if args.metrics_interval is not None:
        before = fetch_parsed()
        start = time.monotonic()
        time.sleep(args.metrics_interval)
        after = fetch_parsed()
        elapsed = time.monotonic() - start
        payload = summarize_vllm_metrics.interval_metrics_payload(before, after, elapsed)
        launch_ledger.record_metric_samples(
            instance_id=args.instance_id,
            source="vllm_metrics_interval",
            metrics=payload,
            details={
                "endpoint_source": "instance_id",
                "container_port": args.container_port,
                "interval": args.metrics_interval,
                "endpoint_changes": endpoint.endpoint_changes,
                "closeout": True,
            },
            db_path=args.db,
        )
        print("Final interval gauge:")
        summarize_vllm_metrics.print_gauge(before, after, elapsed)
        metrics = after
    else:
        metrics = fetch_parsed()

    current_payload = summarize_vllm_metrics.current_metrics_payload(metrics)
    write_json(out_dir / "vllm.metrics.current.json", current_payload)
    launch_ledger.record_metric_samples(
        instance_id=args.instance_id,
        source="vllm_metrics",
        metrics=current_payload,
        details={
            "endpoint_source": "instance_id",
            "container_port": args.container_port,
            "endpoint_changes": endpoint.endpoint_changes,
            "closeout": True,
        },
        db_path=args.db,
    )
    print("Final cumulative metrics:")
    summarize_vllm_metrics.print_summary(metrics)


def main() -> int:
    parser = argparse.ArgumentParser(description="Capture metrics/logs, destroy a Vast instance, and update launch ledger")
    parser.add_argument("--instance-id", type=int, required=True)
    parser.add_argument("--container-port", default="8000/tcp", help="Container port exposing vLLM metrics")
    parser.add_argument("--tail", type=int, default=5000, help="Vast log tail lines to save before destroy")
    parser.add_argument("--timeout", type=int, default=30, help="HTTP metrics timeout seconds")
    parser.add_argument("--api-key-env", default="VLLM_API_KEY", help="Env var containing bearer token")
    parser.add_argument("--no-auth", action="store_true", help="Do not send Authorization header to /metrics")
    parser.add_argument("--skip-metrics", action="store_true", help="Skip final vLLM metrics capture")
    parser.add_argument("--require-metrics", action="store_true", help="Abort before destroy if metrics capture fails")
    parser.add_argument("--metrics-interval", type=float, help="Also capture a final recent TPS window before destroy")
    parser.add_argument("--post-destroy-wait", type=float, default=5.0, help="Seconds to wait before attempting post-destroy snapshot")
    parser.add_argument("--reason", default="clean_terminate", help="Ledger termination reason")
    parser.add_argument("--out-dir", type=Path, help="Artifact directory; default state/terminate/<id>-<timestamp>")
    parser.add_argument("--db", type=Path, default=launch_ledger.DEFAULT_DB_PATH, help="Launch ledger sqlite path")
    parser.add_argument("--dry-run", action="store_true", help="Capture metrics/logs but do not destroy")
    parser.add_argument("--yes", action="store_true", help="Required to actually destroy unless --dry-run is set")
    args = parser.parse_args()

    if args.metrics_interval is not None and args.metrics_interval <= 0:
        parser.error("--metrics-interval must be > 0")
    if not args.dry_run and not args.yes:
        parser.error("refusing to destroy without --yes; use --dry-run to capture only")

    out_dir = args.out_dir or Path("state/terminate") / f"{args.instance_id}-{stamp()}"
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"artifact_dir={out_dir}")

    vast = VastAI()
    launch_ledger.record_event(
        instance_id=args.instance_id,
        event_name="clean_terminate_started" if not args.dry_run else "clean_terminate_dry_run_started",
        source="clean_terminate",
        details={"artifact_dir": str(out_dir), "tail": args.tail, "skip_metrics": args.skip_metrics},
        db_path=args.db,
    )

    info = vast.show_instance(id=args.instance_id)
    pre_instance_path = out_dir / "pre_destroy.instance.json"
    write_json(pre_instance_path, info)
    launch_ledger.update_instance_snapshot(
        instance_id=args.instance_id,
        info=info,
        instance_json_path=pre_instance_path,
        db_path=args.db,
    )

    try:
        logs = str(vast.logs(instance_id=args.instance_id, tail=str(args.tail)))
        logs_path = out_dir / "pre_destroy.logs.txt"
        write_text(logs_path, logs)
        launch_ledger.update_monitor_result(
            instance_id=args.instance_id,
            logs_path=logs_path,
            monitor_json_path=pre_instance_path,
            db_path=args.db,
        )
        print(f"logs={logs_path}")
    except Exception as exc:
        print(f"WARN: log capture failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        launch_ledger.record_event(
            instance_id=args.instance_id,
            event_name="clean_terminate_logs_failed",
            source="clean_terminate",
            details={"error": f"{type(exc).__name__}: {exc}"},
            db_path=args.db,
        )

    if not args.skip_metrics:
        api_key = None if args.no_auth else os.environ.get(args.api_key_env)
        if not args.no_auth and not api_key:
            msg = f"{args.api_key_env} is not set"
            if args.require_metrics:
                raise SystemExit(msg)
            print(f"WARN: skipping metrics: {msg}", file=sys.stderr)
        else:
            try:
                record_current_metrics(args, api_key, out_dir)
            except Exception as exc:
                print(f"WARN: metrics capture failed: {type(exc).__name__}: {exc}", file=sys.stderr)
                launch_ledger.record_event(
                    instance_id=args.instance_id,
                    event_name="clean_terminate_metrics_failed",
                    source="clean_terminate",
                    details={"error": f"{type(exc).__name__}: {exc}"},
                    db_path=args.db,
                )
                if args.require_metrics:
                    return 3

    if args.dry_run:
        launch_ledger.record_event(
            instance_id=args.instance_id,
            event_name="clean_terminate_dry_run_finished",
            source="clean_terminate",
            details={"artifact_dir": str(out_dir)},
            db_path=args.db,
        )
        print("dry_run=true; instance left running")
        return 0

    print(f"destroying instance {args.instance_id}", file=sys.stderr)
    destroy_result = vast.destroy_instance(id=args.instance_id)
    destroy_result_path = out_dir / "destroy.result.json"
    write_json(destroy_result_path, destroy_result)
    launch_ledger.record_event(
        instance_id=args.instance_id,
        event_name="clean_terminate_destroy_returned",
        source="clean_terminate",
        details={"artifact_dir": str(out_dir), "destroy_result_path": str(destroy_result_path)},
        db_path=args.db,
    )

    if args.post_destroy_wait > 0:
        time.sleep(args.post_destroy_wait)
    try:
        post_info = vast.show_instance(id=args.instance_id)
        write_json(out_dir / "post_destroy.instance.json", post_info)
    except Exception as exc:
        write_text(out_dir / "post_destroy.show_instance.error.txt", f"{type(exc).__name__}: {exc}")

    launch_ledger.mark_destroyed(
        instance_id=args.instance_id,
        reason=args.reason,
        destroyed_by_script=True,
        db_path=args.db,
    )
    print(f"destroy_result={destroy_result_path}")
    print("ledger_status=destroyed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
