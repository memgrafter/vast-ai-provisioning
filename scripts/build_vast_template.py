#!/usr/bin/env python3
"""Build a public-safe Vast template payload from local template/model specs.

This script does not call Vast. It makes the local template spec the source of
truth and writes a complete rendered payload that can be reviewed before any
remote apply step.
"""
from __future__ import annotations

import argparse
import json
import shlex
from pathlib import Path
from typing import Any

SECRET_ENV_NAMES = {
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "VLLM_API_KEY",
    "HF_TOKEN",
    "HUGGING_FACE_HUB_TOKEN",
}


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def docker_options(env: dict[str, str], ports: dict[str, str]) -> str:
    parts: list[str] = []
    for external, internal in ports.items():
        parts += ["-p", f"{external}:{internal}"]
    for key, value in env.items():
        parts += ["-e", f"{key}={value}"]
    return " ".join(shlex.quote(part) for part in parts)


def env_from_specs(template: dict[str, Any], model: dict[str, Any]) -> dict[str, str]:
    env = {str(k): str(v) for k, v in (template.get("env_map") or {}).items()}
    vllm = model.get("vllm") or {}

    env.update(
        {
            "R2_PREFIX": str(model["r2_prefix"]),
            "MODEL_DIR": str(model["model_dir"]),
            "VLLM_MODEL": str(model["model_dir"]),
            "SERVED_MODEL_NAME": str(model["served_model_name"]),
            "VLLM_DTYPE": str(vllm.get("dtype", "half")),
            "VLLM_MAX_MODEL_LEN": str(vllm.get("max_model_len", 8192)),
            "VLLM_HOST": str(vllm.get("host", "127.0.0.1")),
            "VLLM_PORT": str(vllm.get("port", 18000)),
            "VLLM_DOWNLOAD_DIR": str(vllm.get("download_dir", "/workspace/models")),
            "VLLM_GPU_MEMORY_UTILIZATION": str(vllm.get("gpu_memory_utilization", 0.9)),
            "VLLM_TRUST_REMOTE_CODE": str(vllm.get("trust_remote_code", True)).lower(),
            "VLLM_FORCE_QUANTIZATION": "" if vllm.get("force_quantization") is None else str(vllm.get("force_quantization")),
            "VLLM_EXTRA_ARGS": " ".join(str(x) for x in vllm.get("extra_args", [])),
        }
    )
    env.setdefault("VLLM_ARGS", "")
    return env


def assert_public_safe(env: dict[str, str]) -> None:
    forbidden_present = sorted(SECRET_ENV_NAMES & set(env))
    if forbidden_present:
        raise ValueError(f"template env must not contain secret env names: {', '.join(forbidden_present)}")


def build_template(template: dict[str, Any], model: dict[str, Any]) -> dict[str, Any]:
    env = env_from_specs(template, model)
    assert_public_safe(env)
    ports = {str(k): str(v) for k, v in (template.get("ports") or {}).items()}
    payload = {k: v for k, v in template.items() if k not in {"env_map", "ports"}}
    payload["env"] = docker_options(env, ports)
    payload["model_profile"] = model.get("name")
    payload["desc"] = template.get("desc", "")
    payload["extra_filters"] = json.dumps(template.get("extra_filters", {}), sort_keys=True)
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a Vast template payload from local specs")
    parser.add_argument("--template-spec", type=Path, required=True)
    parser.add_argument("--model-profile", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()

    payload = build_template(load_json(args.template_spec), load_json(args.model_profile))
    text = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text)
    else:
        print(text, end="")


if __name__ == "__main__":
    main()
