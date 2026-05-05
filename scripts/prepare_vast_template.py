#!/usr/bin/env python3
"""Render and create/update a Vast template from a launch profile."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vastai import VastAI

from scripts.apply_vast_template import apply_template, result_hash_id, validate_launch_profile_match, write_launch_profile_hash
from scripts.build_vast_template import build_from_launch_profile, update_manifest

DEFAULT_TEMPLATE_SPEC = Path("config/templates/vllm-r2-base.public.json")
DEFAULT_PRIVATE_OVERLAY = Path("config/private/vllm-r2.local.json")


def default_out_path(launch_profile: Path) -> Path:
    return Path("state/templates") / f"{launch_profile.stem}.rendered.json"


def main() -> int:
    parser = argparse.ArgumentParser(description="Build and apply a Vast template from a launch profile")
    parser.add_argument("--launch-profile", type=Path, required=True)
    parser.add_argument("--template-spec", type=Path, default=DEFAULT_TEMPLATE_SPEC)
    parser.add_argument("--private-overlay", type=Path, default=DEFAULT_PRIVATE_OVERLAY)
    parser.add_argument("--out", type=Path, default=None)
    privacy = parser.add_mutually_exclusive_group()
    privacy.add_argument("--private", dest="private", action="store_true", default=True, help="render remote template as private (default)")
    privacy.add_argument("--public", dest="private", action="store_false", help="render remote template as public; only use with public-safe overlays")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--create", action="store_true")
    mode.add_argument("--hash-id", help="remote Vast template hash_id to update")
    parser.add_argument("--yes", action="store_true")
    args = parser.parse_args()

    out = args.out or default_out_path(args.launch_profile)
    payload, metadata = build_from_launch_profile(
        launch_profile_path=args.launch_profile,
        template_spec_path=args.template_spec,
        private_overlay_path=args.private_overlay,
        private=args.private,
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    update_manifest(out, argparse.Namespace(**metadata), payload)
    validate_launch_profile_match(out, payload, args.launch_profile)

    action = "create" if args.create else "update"
    print(f"Action:              {action}")
    if args.hash_id:
        print(f"Remote template hash: {args.hash_id}")
    print(f"Launch profile:       {args.launch_profile}")
    print(f"Rendered template:    {out}")
    print(f"Template name:        {payload.get('name')}")
    print(f"Model profile:        {payload.get('model_profile')}")
    print(f"Private:              {payload.get('private')}")
    if not args.yes:
        answer = input(f"{action.capitalize()} this remote Vast template from launch-profile-rendered payload? [y/N] ").strip().lower()
        if answer != "y":
            print("Aborted.")
            return 0

    vast = VastAI()
    result = apply_template(vast, payload, create=args.create, hash_id=args.hash_id)
    print(json.dumps(result, indent=2, sort_keys=True, default=str))
    new_hash = result_hash_id(result)
    if not new_hash:
        raise SystemExit("Could not find hash_id in Vast result; launch profile not updated.")
    write_launch_profile_hash(args.launch_profile, new_hash)
    print(f"Updated {args.launch_profile} template.hash_id = {new_hash}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
