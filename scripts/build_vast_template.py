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


def deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


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

    if "max_model_len" not in vllm:
        raise ValueError("model vllm.max_model_len is required; do not rely on an implicit context-length default")

    env.update(
        {
            "R2_PREFIX": str(model["r2_prefix"]),
            "MODEL_DIR": str(model["model_dir"]),
            "VLLM_MODEL": str(model["model_dir"]),
            "SERVED_MODEL_NAME": str(model["served_model_name"]),
            "VLLM_DTYPE": str(vllm.get("dtype", "half")),
            "VLLM_MAX_MODEL_LEN": str(vllm["max_model_len"]),
            "VLLM_HOST": str(vllm.get("host", "127.0.0.1")),
            "VLLM_PORT": str(vllm.get("port", 18000)),
            "VLLM_DOWNLOAD_DIR": str(vllm.get("download_dir", "/workspace/models")),
            "VLLM_GPU_MEMORY_UTILIZATION": str(vllm.get("gpu_memory_utilization", 0.9)),
            "VLLM_TRUST_REMOTE_CODE": str(vllm.get("trust_remote_code", True)).lower(),
            "VLLM_FORCE_QUANTIZATION": "" if vllm.get("force_quantization") is None else str(vllm.get("force_quantization")),
            "VLLM_MAX_NUM_SEQS": "" if vllm.get("max_num_seqs") is None else str(vllm.get("max_num_seqs")),
            "VLLM_MAX_NEW_TOKENS": "" if vllm.get("max_new_tokens") is None else str(vllm.get("max_new_tokens")),
            "VLLM_ENABLE_AUTO_TOOL_CHOICE": str(vllm.get("enable_auto_tool_choice", False)).lower(),
            "VLLM_TOOL_CALL_PARSER": "" if vllm.get("tool_call_parser") is None else str(vllm.get("tool_call_parser")),
            "VLLM_REASONING_PARSER": "" if vllm.get("reasoning_parser") is None else str(vllm.get("reasoning_parser")),
            "VLLM_ENABLE_PREFIX_CACHING": str(vllm.get("enable_prefix_caching", False)).lower(),
            "VLLM_LANGUAGE_MODEL_ONLY": str(vllm.get("language_model_only", False)).lower(),
            "VLLM_EXTRA_ARGS": " ".join(str(x) for x in vllm.get("extra_args", [])),
        }
    )
    env.setdefault("VLLM_ARGS", "")
    return env


def assert_public_safe(env: dict[str, str]) -> None:
    forbidden_present = sorted(SECRET_ENV_NAMES & set(env))
    if forbidden_present:
        raise ValueError(f"template env must not contain secret env names: {', '.join(forbidden_present)}")


def build_template(template: dict[str, Any], model: dict[str, Any], *, private: bool | None = None) -> dict[str, Any]:
    env = env_from_specs(template, model)
    assert_public_safe(env)
    ports = {str(k): str(v) for k, v in (template.get("ports") or {}).items()}
    payload = {k: v for k, v in template.items() if k not in {"env_map", "ports"}}
    if private is not None:
        payload["private"] = private
    else:
        payload.setdefault("private", True)
    payload["env"] = docker_options(env, ports)
    payload["model_profile"] = model.get("name")
    payload["desc"] = template.get("desc", "")
    payload["extra_filters"] = json.dumps(template.get("extra_filters", {}), sort_keys=True)
    return payload


def build_from_launch_profile(
    *,
    launch_profile_path: Path,
    template_spec_path: Path,
    private_overlay_path: Path | None,
    private: bool = True,
) -> tuple[dict[str, Any], dict[str, Any]]:
    launch = load_json(launch_profile_path)
    model_profile_path = Path(launch["model_profile"])
    template = load_json(template_spec_path)
    if private_overlay_path:
        template = deep_merge(template, load_json(private_overlay_path))
    template["name"] = launch["template"]["name"]
    payload = build_template(template, load_json(model_profile_path), private=private)
    metadata = {
        "template_spec": template_spec_path,
        "model_profile": model_profile_path,
        "private_overlay": private_overlay_path,
        "launch_profile": launch_profile_path,
    }
    return payload, metadata


def update_manifest(out: Path, args: argparse.Namespace, payload: dict[str, Any]) -> None:
    manifest_path = out.parent / "manifest.json"
    if manifest_path.exists():
        manifest = load_json(manifest_path)
    else:
        manifest = {"templates": {}}
    manifest.setdefault("templates", {})[out.name] = {
        "file": out.name,
        "template_spec": str(args.template_spec),
        "model_profile": str(args.model_profile),
        "private_overlay": str(args.private_overlay) if getattr(args, "private_overlay", None) else None,
        "launch_profile": str(args.launch_profile) if getattr(args, "launch_profile", None) else None,
        "model_profile_name": payload.get("model_profile"),
        "template_name": payload.get("name"),
        "private": payload.get("private"),
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a Vast template payload from local specs")
    parser.add_argument("--template-spec", type=Path, required=True)
    parser.add_argument("--model-profile", type=Path, default=None)
    parser.add_argument("--launch-profile", type=Path, default=None, help="derive model profile and template name from launch profile")
    parser.add_argument("--private-overlay", type=Path, default=None, help="ignored local JSON overlay for private non-secret values")
    parser.add_argument("--out", type=Path, default=None)
    privacy = parser.add_mutually_exclusive_group()
    privacy.add_argument("--private", dest="private", action="store_true", default=True, help="render remote template as private (default)")
    privacy.add_argument("--public", dest="private", action="store_false", help="render remote template as public; only use with public-safe overlays")
    args = parser.parse_args()

    out = args.out
    if args.launch_profile:
        payload, metadata = build_from_launch_profile(
            launch_profile_path=args.launch_profile,
            template_spec_path=args.template_spec,
            private_overlay_path=args.private_overlay,
            private=args.private,
        )
        manifest_args = argparse.Namespace(**metadata)
    else:
        if not args.model_profile:
            raise SystemExit("--model-profile is required unless --launch-profile is used")
        template = load_json(args.template_spec)
        if args.private_overlay:
            template = deep_merge(template, load_json(args.private_overlay))
        payload = build_template(template, load_json(args.model_profile), private=args.private)
        manifest_args = args
    text = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if out:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text)
        update_manifest(out, manifest_args, payload)
    else:
        print(text, end="")


if __name__ == "__main__":
    main()
