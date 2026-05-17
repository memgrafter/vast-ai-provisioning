#!/usr/bin/env python3
"""Audit model profiles for required vLLM tool-call parser settings."""
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
    parser = argparse.ArgumentParser(description="Audit Qwen/Carnice vLLM tool-call parser consistency")
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
        ok = auto is True and actual == expected and reasoning == "qwen3"
        status = "OK" if ok else "BAD"
        print(f"{status:3} {path} auto={auto!r} tool_call_parser={actual!r} expected={expected!r} reasoning_parser={reasoning!r}")
        if not ok:
            problems.append(str(path))

    if problems:
        print("\nProfiles with inconsistent tool parser settings:")
        for path in problems:
            print(f"- {path}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
