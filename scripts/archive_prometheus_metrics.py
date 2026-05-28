#!/usr/bin/env python3
"""Append raw Prometheus metrics snapshots to a JSONL log.

The log is append-only: every scrape writes one complete JSON object containing
metadata plus the full Prometheus text payload. JSONL keeps the structured scrape
metadata easy to parse while preserving the raw metrics for later analysis.
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def resolve_metrics_url(*, metrics_url: str | None, base_url: str | None, instance_id: int | None, container_port: str) -> str:
    if metrics_url:
        return metrics_url
    if base_url:
        return base_url.rstrip("/").removesuffix("/v1") + "/metrics"
    if instance_id is None:
        raise SystemExit("One of --metrics-url, --base-url, or --instance-id is required.")

    from vastai import VastAI

    info = VastAI().show_instance(id=instance_id)
    ports = info.get("ports") or {}
    entries = ports.get(container_port) or []
    host_port = (entries[0] or {}).get("HostPort") if entries else None
    host = info.get("public_ipaddr")
    if not host or not host_port:
        raise SystemExit(f"Could not resolve {container_port} for instance {instance_id}.")
    return f"http://{host}:{host_port}/metrics"


def scrape(metrics_url: str, headers: dict[str, str], timeout: float) -> dict[str, Any]:
    started = time.monotonic()
    timestamp = now_utc()
    request = Request(metrics_url, headers=headers)
    try:
        with urlopen(request, timeout=timeout) as response:
            body = response.read().decode(errors="replace")
            status = int(response.status)
            response_headers = dict(response.headers.items())
        error = None
    except HTTPError as exc:
        body = exc.read().decode(errors="replace")
        status = int(exc.code)
        response_headers = dict(exc.headers.items()) if exc.headers else {}
        error = f"HTTPError: {exc.code}"
    except (TimeoutError, URLError, OSError) as exc:
        body = ""
        status = 0
        response_headers = {}
        error = f"{type(exc).__name__}: {exc}"

    return {
        "timestamp": timestamp,
        "unix_time": time.time(),
        "metrics_url": metrics_url,
        "status": status,
        "ok": status == 200,
        "elapsed_s": round(time.monotonic() - started, 6),
        "bytes": len(body.encode("utf-8")),
        "error": error,
        "response_headers": response_headers,
        "prometheus_text": body,
    }


def append_record(path: Path, record: dict[str, Any], *, fsync: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")
        fh.flush()
        if fsync:
            os.fsync(fh.fileno())


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Append full raw Prometheus metrics snapshots to JSONL")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--metrics-url", help="Full Prometheus metrics URL, e.g. http://host:port/metrics")
    source.add_argument("--base-url", help="OpenAI base URL; /v1 is stripped and /metrics is appended")
    source.add_argument("--instance-id", type=int, help="Resolve Vast public host port for --container-port")
    parser.add_argument("--container-port", default="8000/tcp", help="Vast container port mapping for --instance-id")
    parser.add_argument("--out", type=Path, required=True, help="Append-only JSONL output path")
    parser.add_argument("--interval", type=float, default=10.0, help="Seconds between scrapes when --repeat is set")
    parser.add_argument("--timeout", type=float, default=10.0, help="HTTP timeout per scrape")
    parser.add_argument("--repeat", action="store_true", help="Scrape until interrupted")
    parser.add_argument("--count", type=int, default=0, help="Number of scrapes; 0 means unlimited with --repeat, one without --repeat")
    parser.add_argument("--api-key-env", default="VLLM_API_KEY", help="Bearer token env var; ignored with --no-auth")
    parser.add_argument("--no-auth", action="store_true", help="Do not send Authorization header")
    parser.add_argument("--fsync", action="store_true", help="fsync after each append")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    metrics_url = resolve_metrics_url(
        metrics_url=args.metrics_url,
        base_url=args.base_url,
        instance_id=args.instance_id,
        container_port=args.container_port,
    )
    api_key = None if args.no_auth else os.environ.get(args.api_key_env)
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    stop_requested = False

    def stop(_signum: int, _frame: Any) -> None:
        nonlocal stop_requested
        stop_requested = True

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)

    target_count = args.count if args.count > 0 else (0 if args.repeat else 1)
    written = 0
    while not stop_requested:
        loop_started = time.monotonic()
        record = scrape(metrics_url, headers, args.timeout)
        record["sequence"] = written + 1
        append_record(args.out, record, fsync=args.fsync)
        written += 1
        print(
            f"{record['timestamp']} status={record['status']} bytes={record['bytes']} "
            f"elapsed_s={record['elapsed_s']} out={args.out}",
            flush=True,
        )
        if target_count and written >= target_count:
            break
        if not args.repeat and not target_count:
            break
        sleep_s = max(0.0, args.interval - (time.monotonic() - loop_started))
        time.sleep(sleep_s)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
