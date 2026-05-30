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
import os
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import launch_ledger
from vastai import VastAI


DEFAULT_MODEL = "vastai/vllm:v0.22.0-cuda-13.0"


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
    provisioning_failed: bool
    errors: list[str]


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def get_instance(vast: VastAI, instance_id: int) -> dict[str, Any]:
    return vast.show_instance(id=instance_id)


def get_logs(vast: VastAI, instance_id: int, tail: int) -> str:
    return str(vast.logs(instance_id=instance_id, tail=str(tail)))


def save_snapshot(instance_id: int, info: dict[str, Any], logs: str) -> tuple[Path, Path]:
    out = Path("instances")
    out.mkdir(exist_ok=True)
    monitor_json_path = out / f"{instance_id}.monitor.current.json"
    logs_path = out / f"{instance_id}.monitor.logs.txt"
    monitor_json_path.write_text(json.dumps(info, indent=2, sort_keys=True, default=str) + "\n")
    logs_path.write_text(logs + "\n")
    return monitor_json_path, logs_path


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
        r2_transfer_active=("download:" in lower or "copy:" in lower or "R2 sync progress:" in logs),
        r2_sync_finished=("Sync finished at:" in logs or "Synced bytes:" in logs),
        provisioning_complete=(
            "Provisioning complete" in logs
            or "Provisioner complete" in logs
            or "Removed /.provisioning" in logs
        ),
        vllm_waiting_for_provisioning=("vllm startup paused until instance provisioning has completed" in logs),
        vllm_started=(
            "vllm serve" in logs
            or "Uvicorn running on http://127.0.0.1:18000" in logs
            or "Uvicorn running on http://0.0.0.0:18000" in logs
            or "Starting vLLM server on http://127.0.0.1:18000" in logs
            or "Starting vLLM server on http://0.0.0.0:18000" in logs
        ),
        api_ready=(
            "Uvicorn running on http://127.0.0.1:18000" in logs
            or "Uvicorn running on http://0.0.0.0:18000" in logs
            or "Starting vLLM server on http://127.0.0.1:18000" in logs and "Application startup complete" in logs
            or "Starting vLLM server on http://0.0.0.0:18000" in logs and "Application startup complete" in logs
            or "vLLM API server" in logs and "ready" in lower
        ),
        speed_test_failed=(
            "ERROR: R2 speed test below threshold" in logs
            or "Provisioning script failed (exit 42)" in logs
        ),
        provisioning_failed=(
            "All 3 attempts exhausted" in logs
            or "missing AWS_ACCESS_KEY_ID" in logs
            or "missing AWS_SECRET_ACCESS_KEY" in logs
            or "Provisioning script failed (exit 1)" in logs
            or "Quantization method specified in the model config" in logs
            or "ValidationError: 1 validation error for ModelConfig" in logs
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


def api_status(url: str, api_key: str | None, timeout: int) -> tuple[int, str]:
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    request = Request(url, headers=headers)
    try:
        with urlopen(request, timeout=timeout) as response:
            body = response.read(200).decode(errors="replace")
            return response.status, body
    except HTTPError as exc:
        body = exc.read(200).decode(errors="replace")
        return exc.code, body
    except TimeoutError:
        return 0, "timeout"
    except URLError as exc:
        return 0, str(exc.reason)
    except Exception as exc:
        return 0, f"{type(exc).__name__}: {exc}"


def external_api_probe(info: dict[str, Any], api_key: str | None, container_port: str, timeout: int) -> dict[str, Any]:
    base_url = port_url(info, container_port)
    if not base_url:
        return {"base_url": None, "reachable": False, "models_ok": False, "health_status": None, "models_status": None, "error": "no public port mapping"}
    health_status, health_body = api_status(f"{base_url}/health", api_key, timeout)
    models_status, models_body = api_status(f"{base_url}/v1/models", api_key, timeout)
    if api_key:
        models_ok = models_status == 200
        reachable = health_status in {200, 401, 403} or models_status in {200, 401, 403}
    else:
        models_ok = models_status in {200, 401, 403}
        reachable = health_status in {200, 401, 403} or models_ok
    return {
        "base_url": base_url,
        "reachable": reachable,
        "models_ok": models_ok,
        "health_status": health_status,
        "models_status": models_status,
        "health_body": health_body[:200],
        "models_body": models_body[:200],
    }


def print_status(instance_id: int, info: dict[str, Any], signals: Signals, elapsed: float, image_deadline: int, provisioning_deadline: int) -> str:
    status = str(info.get("actual_status") or info.get("status") or "unknown")
    url = port_url(info)
    print(f"[{now_utc()}] instance={instance_id} status={status} elapsed={elapsed:.0f}s machine={info.get('machine_id')} gpu={info.get('gpu_name')}")
    status_msg = str(info.get("status_msg") or "").strip()
    status_msg_image_pull_seen = any(token in status_msg for token in ["Pulling", "Pull complete", "Download complete", "Verifying Checksum"])
    effective_image_pull_seen = signals.image_pull_seen or status_msg_image_pull_seen
    if url:
        print(f"  vllm_api: {url}")
    if status_msg:
        print(f"  status_msg: {status_msg[:240]}")
    print(
        "  signals: "
        f"image_cached={signals.image_cached} "
        f"image_pull_seen={effective_image_pull_seen} "
        f"provisioning_started={signals.provisioning_started} "
        f"r2_sync_started={signals.r2_sync_started} "
        f"r2_transfer_active={signals.r2_transfer_active} "
        f"r2_sync_finished={signals.r2_sync_finished} "
        f"speed_test_failed={signals.speed_test_failed} "
        f"provisioning_failed={signals.provisioning_failed} "
        f"vllm_waiting={signals.vllm_waiting_for_provisioning} "
        f"vllm_started={signals.vllm_started} "
        f"api_ready={signals.api_ready}"
    )
    recommendation = "WAIT"
    if signals.speed_test_failed:
        recommendation = "TERMINATE_R2_SPEED_TEST_FAILED"
    elif signals.provisioning_failed:
        recommendation = "TERMINATE_PROVISIONING_FAILED"
    elif signals.api_ready or signals.vllm_started:
        recommendation = "READY_OR_STARTING_VLLM"
    elif signals.r2_sync_finished:
        recommendation = "WAIT_VLLM_LOADING"
    elif signals.r2_sync_started or signals.provisioning_started:
        recommendation = "WAIT_R2_OR_PROVISIONING"
    elif elapsed >= provisioning_deadline and not signals.provisioning_started:
        recommendation = "CONSIDER_TERMINATE_NO_PROVISIONING"
    elif elapsed >= image_deadline and effective_image_pull_seen and not signals.image_cached:
        recommendation = "CONSIDER_TERMINATE_SLOW_IMAGE_PULL"
    print(f"  recommendation: {recommendation}")
    if signals.errors:
        print("  recent non-tunnel errors:")
        for line in signals.errors[-5:]:
            print(f"    {line[:240]}")
    print(flush=True)
    return recommendation


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Monitor Vast instance readiness from SDK logs")
    parser.add_argument("instance_id", type=int)
    parser.add_argument("--interval", type=int, default=15, help="poll interval seconds")
    parser.add_argument("--tail", type=int, default=1000, help="log tail lines")
    parser.add_argument("--timeout", type=int, default=1800, help="overall monitor timeout seconds")
    parser.add_argument("--image", default=DEFAULT_MODEL, help="image tag to detect cached-image line")
    parser.add_argument("--image-deadline", type=int, default=180, help="seconds before warning on slow image pull")
    parser.add_argument("--provisioning-deadline", type=int, default=300, help="seconds before warning if provisioning has not started")
    parser.add_argument("--once", action="store_true", help="single poll then exit")
    parser.add_argument("--destroy-on-fail", action="store_true", help="destroy instance when a terminate recommendation is reached")
    parser.add_argument("--yes-destroy", action="store_true", help="required with --destroy-on-fail to actually destroy without prompting")
    parser.add_argument("--api-key-env", default="VLLM_API_KEY", help="Env var containing bearer token for external API readiness probes")
    parser.add_argument("--no-auth", action="store_true", help="Do not send Authorization header to external API readiness probes")
    parser.add_argument("--external-api-timeout", type=int, default=5, help="seconds for each external API probe request")
    parser.add_argument("--external-api-deadline", type=int, default=240, help="seconds to allow public API to respond after local vLLM readiness")
    parser.add_argument("--container-port", default="8000/tcp", help="container port mapping to probe for the public vLLM API")
    parser.add_argument("--skip-external-api-check", action="store_true", help="old behavior: exit once logs indicate local vLLM readiness")
    return parser


def main() -> int:
    args = build_arg_parser().parse_args()

    vast = VastAI()
    api_key = None if args.no_auth else os.environ.get(args.api_key_env)
    start = time.time()
    local_api_ready_since: float | None = None
    last_external_probe: dict[str, Any] | None = None
    last_recommendation = "WAIT"
    cumulative = Signals(
        image_cached=False,
        image_pull_seen=False,
        provisioning_started=False,
        r2_sync_started=False,
        r2_transfer_active=False,
        r2_sync_finished=False,
        provisioning_complete=False,
        vllm_waiting_for_provisioning=False,
        vllm_started=False,
        api_ready=False,
        speed_test_failed=False,
        provisioning_failed=False,
        errors=[],
    )
    while True:
        elapsed = time.time() - start
        try:
            info = get_instance(vast, args.instance_id)
            logs = get_logs(vast, args.instance_id, args.tail)
            monitor_json_path, logs_path = save_snapshot(args.instance_id, info, logs)
            current_signals = analyze_logs(logs, args.image)
            signals = Signals(**{
                field: (cumulative.errors + current_signals.errors if field == "errors" else bool(getattr(cumulative, field) or getattr(current_signals, field)))
                for field in cumulative.__dataclass_fields__
            })
            cumulative = signals
            last_recommendation = print_status(
                args.instance_id,
                info,
                signals,
                elapsed,
                args.image_deadline,
                args.provisioning_deadline,
            )
            if signals.api_ready:
                if local_api_ready_since is None:
                    local_api_ready_since = time.time()
                if not args.skip_external_api_check:
                    last_external_probe = external_api_probe(info, api_key, args.container_port, args.external_api_timeout)
                    age = time.time() - local_api_ready_since
                    print(
                        "  external_api: "
                        f"base_url={last_external_probe.get('base_url') or 'n/a'} "
                        f"health_http={last_external_probe.get('health_status')} "
                        f"models_http={last_external_probe.get('models_status')} "
                        f"reachable={str(bool(last_external_probe.get('reachable'))).lower()} "
                        f"models_ok={str(bool(last_external_probe.get('models_ok'))).lower()} "
                        f"local_ready_age={age:.0f}s",
                        flush=True,
                    )
                    if last_external_probe.get("models_ok"):
                        last_recommendation = "READY_EXTERNAL_API"
                    elif age >= args.external_api_deadline:
                        last_recommendation = "TERMINATE_EXTERNAL_API_UNREACHABLE"
            try:
                details = {"signals": signals.__dict__}
                if last_external_probe is not None:
                    details["external_api_probe"] = last_external_probe
                launch_ledger.update_instance_snapshot(
                    instance_id=args.instance_id,
                    info=info,
                    instance_json_path=monitor_json_path,
                )
                launch_ledger.update_monitor_result(
                    instance_id=args.instance_id,
                    signals=details,
                    monitor_json_path=monitor_json_path,
                    logs_path=logs_path,
                    error_summary="\n".join(signals.errors[-20:])[:4000] if signals.errors else None,
                )
            except Exception as exc:
                print(f"WARN launch ledger monitor update failed: {exc}", file=sys.stderr)
            should_destroy = last_recommendation.startswith("TERMINATE_") or last_recommendation.startswith("CONSIDER_TERMINATE_")
            if should_destroy and args.destroy_on_fail:
                if not args.yes_destroy:
                    print("Destroy requested by recommendation but --yes-destroy was not set; leaving instance running.", file=sys.stderr)
                    return 3
                print(f"Destroying instance {args.instance_id}: {last_recommendation}", file=sys.stderr)
                result = vast.destroy_instance(id=args.instance_id)
                try:
                    launch_ledger.mark_destroyed(
                        instance_id=args.instance_id,
                        reason=last_recommendation,
                        destroyed_by_script=True,
                    )
                except Exception as exc:
                    print(f"WARN launch ledger destroy update failed: {exc}", file=sys.stderr)
                print(json.dumps(result, indent=2, sort_keys=True, default=str))
                return 4
            if args.skip_external_api_check and (signals.api_ready or signals.vllm_started):
                return 0
            if signals.api_ready and (args.skip_external_api_check or last_recommendation == "READY_EXTERNAL_API"):
                return 0
            if args.once:
                return 0
            if elapsed >= args.timeout:
                print(f"Timed out after {args.timeout}s; last recommendation={last_recommendation}", file=sys.stderr)
                return 2
        except KeyboardInterrupt:
            print("Interrupted", file=sys.stderr)
            return 130
        except (AttributeError, NameError) as exc:
            print(f"ERROR monitor implementation bug: {exc}", file=sys.stderr)
            return 1
        except Exception as exc:
            print(f"WARN monitor poll failed: {exc}", file=sys.stderr)
            if args.once:
                return 1
        time.sleep(args.interval)


if __name__ == "__main__":
    raise SystemExit(main())
