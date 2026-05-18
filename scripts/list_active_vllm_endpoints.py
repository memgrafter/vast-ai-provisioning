#!/usr/bin/env python3
"""Print vLLM endpoint connection data for active Vast instances.

This intentionally prints no secrets. Use the local/account VLLM_API_KEY when
calling the returned base_url values.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vastai import VastAI

ACTIVE_STATUSES = {"running", "loading", "starting"}


def sanitize_error(exc: BaseException) -> str:
    text = f"{type(exc).__name__}: {exc}"
    text = re.sub(r"([?&]api_key=)[^&\s]+", r"\1<redacted>", text)
    text = re.sub(r"(Bearer\s+)[A-Za-z0-9._~+/-]+", r"\1<redacted>", text)
    return text


def env_dict(raw: Any) -> dict[str, str]:
    if isinstance(raw, dict):
        return {str(k): str(v) for k, v in raw.items()}
    if isinstance(raw, list):
        out: dict[str, str] = {}
        for item in raw:
            if isinstance(item, (list, tuple)) and len(item) >= 2:
                out[str(item[0])] = str(item[1])
        return out
    return {}


def host_port(info: dict[str, Any], container_port: str) -> tuple[str | None, str | None]:
    host = info.get("public_ipaddr") or info.get("ssh_host")
    ports = info.get("ports") or {}
    entries = ports.get(container_port) or []
    host_port_value = None
    if entries:
        host_port_value = (entries[0] or {}).get("HostPort")
    return (str(host) if host else None, str(host_port_value) if host_port_value else None)


def model_name(info: dict[str, Any]) -> str | None:
    env = env_dict(info.get("extra_env"))
    for key in ("SERVED_MODEL_NAME", "served_model_name", "VLLM_SERVED_MODEL_NAME"):
        if env.get(key):
            return env[key]
    label = info.get("label")
    if isinstance(label, str) and label:
        # select_and_launch labels are "<launch-name>-<served-model-name>".
        marker = "-qwen"
        idx = label.find(marker)
        if idx >= 0:
            return label[idx + 1 :]
    for key in ("VLLM_MODEL", "MODEL_DIR"):
        value = env.get(key)
        if value:
            return value.rstrip("/").rsplit("/", 1)[-1]
    return None


def get_instances(vast: VastAI) -> list[dict[str, Any]]:
    instances: list[dict[str, Any]] = []
    params: dict[str, Any] = {}
    while True:
        result = vast.show_instances_v1(params)
        batch = result.get("instances") or []
        if not isinstance(batch, list):
            raise RuntimeError("unexpected show_instances_v1 response: instances is not a list")
        instances.extend(batch)
        token = result.get("next_token")
        if not token:
            break
        params = {"next_token": token}
    return instances


def endpoint_row(info: dict[str, Any], container_port: str) -> dict[str, Any]:
    host, port = host_port(info, container_port)
    base_url = f"http://{host}:{port}/v1" if host and port else None
    status = info.get("actual_status") or info.get("cur_state") or info.get("status")
    return {
        "instance_id": info.get("id") or info.get("instance_id"),
        "machine_id": info.get("machine_id"),
        "status": status,
        "gpu": info.get("gpu_name"),
        "host": host,
        "port": port,
        "container_port": container_port,
        "model": model_name(info),
        "base_url": base_url,
        "label": info.get("label"),
    }


def print_table(rows: list[dict[str, Any]]) -> None:
    if not rows:
        print("No active Vast instances found.")
        return
    cols = ["instance_id", "machine_id", "status", "gpu", "host", "port", "model", "base_url"]
    widths = {col: max(len(col), *(len(str(row.get(col) or "")) for row in rows)) for col in cols}
    print("  ".join(col.ljust(widths[col]) for col in cols))
    print("  ".join("-" * widths[col] for col in cols))
    for row in rows:
        print("  ".join(str(row.get(col) or "").ljust(widths[col]) for col in cols))


def print_env(rows: list[dict[str, Any]]) -> None:
    for i, row in enumerate(rows, start=1):
        prefix = f"VLLM_{i}"
        print(f"{prefix}_INSTANCE_ID={row.get('instance_id') or ''}")
        print(f"{prefix}_HOST={row.get('host') or ''}")
        print(f"{prefix}_PORT={row.get('port') or ''}")
        print(f"{prefix}_MODEL={row.get('model') or ''}")
        print(f"{prefix}_BASE_URL={row.get('base_url') or ''}")


def main() -> int:
    parser = argparse.ArgumentParser(description="List host/port/model/base_url for active Vast vLLM hosts")
    parser.add_argument("--container-port", default="8000/tcp", help="container port to report; default: 8000/tcp")
    parser.add_argument("--include-non-active", action="store_true", help="include all current instances, not only running/loading/starting")
    parser.add_argument("--format", choices=("table", "json", "env"), default="table")
    args = parser.parse_args()

    try:
        vast = VastAI()
        instances = get_instances(vast)
    except Exception as exc:
        print("ERROR: " + sanitize_error(exc), file=sys.stderr)
        return 2

    rows = []
    for info in instances:
        status = str(info.get("actual_status") or info.get("cur_state") or info.get("status") or "").lower()
        if not args.include_non_active and status not in ACTIVE_STATUSES:
            continue
        rows.append(endpoint_row(info, args.container_port))

    rows.sort(key=lambda row: (str(row.get("status") or ""), str(row.get("instance_id") or "")))

    if args.format == "json":
        print(json.dumps(rows, indent=2, sort_keys=True, default=str))
    elif args.format == "env":
        print_env(rows)
    else:
        print_table(rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
