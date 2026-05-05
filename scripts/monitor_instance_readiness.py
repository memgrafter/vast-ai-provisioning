#!/usr/bin/env python3
"""Monitor Vast instance logs/status for provisioning and vLLM readiness.

This script is read-only by default. It does not destroy, reboot, or modify an
instance. Use it after launch to see whether the instance reached key milestones:

- Docker image cached / pull path
- provisioning started
- R2 sync started / active / finished
- vLLM started / API ready
- optional fast-start kill recommendation if Docker/provisioning is too slow
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from vastai import VastAI


DEFAULT_MODEL = "vastai/vllm:v0.20.0-cuda-13.0"


@dataclass(frozen=True)
class Signals:
    image_cached: bool
    image_pull_seen: bool
    provisioning_started: bool
    r2_sync_started: bool
    r2_transfer_active: bool
    r2_sync_finished: bool
    provisioning_complete: bool
    vllm_waiting_for_provisioning: bool
    vllm_started: bool
    api_ready: bool
    speed_test_failed: bool
    errors: list[str]


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def get_instance(vast: VastAI, instance_id: int) -> dict[str, Any]:
    return vast.show_instance(id=instance_id)


def get_logs(vast: VastAI, instance_id: int, tail: int) -> str:
    return str(vast.logs(instance_id=instance_id, tail=str(tail)))


def save_snapshot(instance_id: int, info: dict[str, Any], logs: str) -> None:
    out = Path("instances")
    out.mkdir(exist_ok=True)
    out.joinpath(f"{instance_id}.monitor.current.json").write_text(
        json.dumps(info, indent=2, sort_keys=True, default=str) + "\n"
    )
    out.joinpath(f"{instance_id}.monitor.logs.txt").write_text(logs + "\n")


def analyze_logs(logs: str, image: str) -> Signals:
    lines = logs.splitlines()
    lower = logs.lower()
    error_lines = [
        line
        for line in lines
        if re.search(r"\b(error|traceback|exception|failed|missing)\b", line, re.I)
        and "trycloudflare" not in line.lower()
        and "quicktunnel" not in line.lower()
    ][-20:]
    return Signals(
        image_cached=(f"Status: Image is up to date for {image}" in logs),
        image_pull_seen=("Pulling from vastai/vllm" in logs or image in logs or "Verifying Checksum" in logs),
        provisioning_started=(
            "Provisioning instance with manifest" in logs
            or "Provisioning model from R2" in logs
            or "R2 speed test enabled" in logs
        ),
        r2_sync_started=("Sync started at:" in logs or "Syncing s3://" in logs),
        r2_transfer_active=("download:" in lower or "copy:" in lower),
        r2_sync_finished=("Sync finished at:" in logs or "Synced bytes:" in logs),
        provisioning_complete=(
            "Provisioning complete" in logs
            or "Provisioner complete" in logs
            or "Removed /.provisioning" in logs
        ),
        vllm_waiting_for_provisioning=("vllm startup paused until instance provisioning has completed" in logs),
        vllm_started=(
            "vllm serve" in logs
            or "Started server process" in logs and "vllm" in lower and "18000" in logs
            or "Uvicorn running on http://127.0.0.1:18000" in logs
            or "Uvicorn running on http://0.0.0.0:18000" in logs
        ),
        api_ready=(
            "Uvicorn running on http://127.0.0.1:18000" in logs
            or "Uvicorn running on http://0.0.0.0:18000" in logs
            or "vLLM API server" in logs and "ready" in lower
        ),
        speed_test_failed=(
            "R2 speed test below threshold" in logs
            or "Provisioning script failed (exit 42)" in logs
        ),
        errors=error_lines,
    )


def port_url(info: dict[str, Any], container_port: str = "8000/tcp") -> str | None:
    ports = info.get("ports") or {}
    host_port = ((ports.get(container_port) or [{}])[0] or {}).get("HostPort")
    host = info.get("public_ipaddr")
    if host and host_port:
        return f"http://{host}:{host_port}"
    return None


def print_status(instance_id: int, info: dict[str, Any], signals: Signals, elapsed: float, image_deadline: int, provisioning_deadline: int) -> str:
    status = str(info.get("actual_status") or info.get("status") or "unknown")
    url = port_url(info)
    print(f"[{now_utc()}] instance={instance_id} status={status} elapsed={elapsed:.0f}s machine={info.get('machine_id')} gpu={info.get('gpu_name')}")
    if url:
        print(f"  vllm_api: {url}")
    print(
        "  signals: "
        f"image_cached={signals.image_cached} "
        f"image_pull_seen={signals.image_pull_seen} "
        f"provisioning_started={signals.provisioning_started} "
        f"r2_sync_started={signals.r2_sync_started} "
        f"r2_transfer_active={signals.r2_transfer_active} "
        f"r2_sync_finished={signals.r2_sync_finished} "
        f"speed_test_failed={signals.speed_test_failed} "
        f"vllm_waiting={signals.vllm_waiting_for_provisioning} "
        f"vllm_started={signals.vllm_started} "
        f"api_ready={signals.api_ready}"
    )
    recommendation = "WAIT"
    if signals.speed_test_failed:
        recommendation = "TERMINATE_R2_SPEED_TEST_FAILED"
    elif signals.api_ready or signals.vllm_started:
        recommendation = "READY_OR_STARTING_VLLM"
    elif signals.r2_sync_finished:
        recommendation = "WAIT_VLLM_LOADING"
    elif signals.r2_sync_started or signals.provisioning_started:
        recommendation = "WAIT_R2_OR_PROVISIONING"
    elif elapsed >= provisioning_deadline and not signals.provisioning_started:
        recommendation = "CONSIDER_TERMINATE_NO_PROVISIONING"
    elif elapsed >= image_deadline and signals.image_pull_seen and not signals.image_cached:
        recommendation = "CONSIDER_TERMINATE_SLOW_IMAGE_PULL"
    print(f"  recommendation: {recommendation}")
    if signals.errors:
        print("  recent non-tunnel errors:")
        for line in signals.errors[-5:]:
            print(f"    {line[:240]}")
    print(flush=True)
    return recommendation


def main() -> int:
    parser = argparse.ArgumentParser(description="Monitor Vast instance readiness from SDK logs")
    parser.add_argument("instance_id", type=int)
    parser.add_argument("--interval", type=int, default=15, help="poll interval seconds")
    parser.add_argument("--tail", type=int, default=1000, help="log tail lines")
    parser.add_argument("--timeout", type=int, default=1800, help="overall monitor timeout seconds")
    parser.add_argument("--image", default=DEFAULT_MODEL, help="image tag to detect cached-image line")
    parser.add_argument("--image-deadline", type=int, default=60, help="seconds before warning on slow image pull")
    parser.add_argument("--provisioning-deadline", type=int, default=180, help="seconds before warning if provisioning has not started")
    parser.add_argument("--once", action="store_true", help="single poll then exit")
    parser.add_argument("--destroy-on-fail", action="store_true", help="destroy instance when a terminate recommendation is reached")
    parser.add_argument("--yes-destroy", action="store_true", help="required with --destroy-on-fail to actually destroy without prompting")
    args = parser.parse_args()

    vast = VastAI()
    start = time.time()
    last_recommendation = "WAIT"
    while True:
        elapsed = time.time() - start
        try:
            info = get_instance(vast, args.instance_id)
            logs = get_logs(vast, args.instance_id, args.tail)
            save_snapshot(args.instance_id, info, logs)
            signals = analyze_logs(logs, args.image)
            last_recommendation = print_status(
                args.instance_id,
                info,
                signals,
                elapsed,
                args.image_deadline,
                args.provisioning_deadline,
            )
            should_destroy = last_recommendation.startswith("TERMINATE_") or last_recommendation.startswith("CONSIDER_TERMINATE_")
            if should_destroy and args.destroy_on_fail:
                if not args.yes_destroy:
                    print("Destroy requested by recommendation but --yes-destroy was not set; leaving instance running.", file=sys.stderr)
                    return 3
                print(f"Destroying instance {args.instance_id}: {last_recommendation}", file=sys.stderr)
                result = vast.destroy_instance(id=args.instance_id)
                print(json.dumps(result, indent=2, sort_keys=True, default=str))
                return 4
            if signals.api_ready or signals.vllm_started:
                return 0
            if args.once:
                return 0
            if elapsed >= args.timeout:
                print(f"Timed out after {args.timeout}s; last recommendation={last_recommendation}", file=sys.stderr)
                return 2
        except KeyboardInterrupt:
            print("Interrupted", file=sys.stderr)
            return 130
        except Exception as exc:
            print(f"WARN monitor poll failed: {exc}", file=sys.stderr)
            if args.once:
                return 1
        time.sleep(args.interval)


if __name__ == "__main__":
    raise SystemExit(main())
