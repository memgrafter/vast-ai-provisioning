#!/usr/bin/env python3
"""Audit model profiles for required vLLM Qwen/Carnice settings."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def expected_parser(profile: dict[str, Any]) -> str | None:
    blob = f"{profile.get('hf_model_id', '')} {profile.get('name', '')} {profile.get('served_model_name', '')}".lower()
    if "carnice" in blob:
        return "qwen3_xml"
    if "qwen3.6" in blob:
        return "qwen3_coder"
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit Qwen/Carnice vLLM tool-call parser and MTP consistency")
    parser.add_argument("paths", nargs="*", type=Path, default=[Path("config/models")])
    args = parser.parse_args()

    files: list[Path] = []
    for path in args.paths:
        if path.is_dir():
            files.extend(sorted(path.glob("*.json")))
        else:
            files.append(path)

    problems: list[str] = []
    for path in files:
        profile = json.loads(path.read_text())
        vllm = profile.get("vllm") or {}
        if not vllm:
            continue
        expected = expected_parser(profile)
        if expected is None:
            continue
        auto = vllm.get("enable_auto_tool_choice")
        actual = vllm.get("tool_call_parser")
        reasoning = vllm.get("reasoning_parser")
        errors: list[str] = []
        if auto is not True or actual != expected or reasoning != "qwen3":
            errors.append(
                f"tool settings auto={auto!r} tool_call_parser={actual!r} expected={expected!r} reasoning_parser={reasoning!r}"
            )

        dtype = vllm.get("dtype")
        kv_cache_dtype = vllm.get("kv_cache_dtype")
        if kv_cache_dtype == "bfloat16" and dtype not in {"bfloat16", "bf16"}:
            errors.append(
                f"kv_cache_dtype='bfloat16' requires dtype='bfloat16' to avoid FlashAttention query/key dtype mismatch; got dtype={dtype!r}"
            )

        spec = vllm.get("speculative_config")
        if spec is not None:
            expected_method = "qwen3_5_mtp" if expected == "qwen3_xml" else "qwen3_next_mtp"
            method = spec.get("method") if isinstance(spec, dict) else None
            tokens = spec.get("num_speculative_tokens") if isinstance(spec, dict) else None
            if method != expected_method:
                errors.append(f"MTP method={method!r} expected={expected_method!r}")
            if expected_method == "qwen3_next_mtp" and tokens not in {1, 2}:
                errors.append(f"qwen3_next_mtp num_speculative_tokens={tokens!r} expected 1 or 2")
            if expected_method == "qwen3_5_mtp" and tokens != 3:
                errors.append(f"qwen3_5_mtp num_speculative_tokens={tokens!r} expected 3")

        status = "OK" if not errors else "BAD"
        spec_text = f" spec={spec!r}" if spec is not None else ""
        print(f"{status:3} {path} auto={auto!r} tool_call_parser={actual!r} expected={expected!r} reasoning_parser={reasoning!r}{spec_text}")
        for error in errors:
            print(f"    - {error}")
        if errors:
            problems.append(str(path))

    if problems:
        print("\nProfiles with inconsistent Qwen/Carnice settings:")
        for path in problems:
            print(f"- {path}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
