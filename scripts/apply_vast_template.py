#!/usr/bin/env python3
"""Create or update a remote Vast template from a local rendered payload."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from vastai import VastAI

REMOTE_IGNORED_KEYS = {
    "id",
    "hash_id",
    "created_at",
    "deleted_at",
    "creator_id",
    "model_profile",
}
REMOTE_ALLOWED_KEYS = {
    "name",
    "image",
    "image_tag",
    "href",
    "repo",
    "env",
    "onstart_cmd",
    "jup_direct",
    "ssh_direct",
    "use_jupyter_lab",
    "runtype",
    "use_ssh",
    "jupyter_dir",
    "docker_login_repo",
    "extra_filters",
    "disk_space",
    "readme",
    "readme_visible",
    "desc",
    "private",
}


def load_payload(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def load_manifest_for_template(path: Path) -> dict[str, Any]:
    manifest_path = path.parent / "manifest.json"
    if not manifest_path.exists():
        raise SystemExit(f"Missing required template manifest: {manifest_path}")
    manifest = json.loads(manifest_path.read_text())
    entry = (manifest.get("templates") or {}).get(path.name)
    if not entry:
        raise SystemExit(f"Template {path.name} is not listed in required manifest: {manifest_path}")
    return entry


def update_kwargs(payload: dict[str, Any]) -> dict[str, Any]:
    normalized = {k: v for k, v in payload.items() if k not in REMOTE_IGNORED_KEYS and v is not None}
    if "tag" in normalized and "image_tag" not in normalized:
        normalized["image_tag"] = normalized.pop("tag")
    if "onstart" in normalized and "onstart_cmd" not in normalized:
        normalized["onstart_cmd"] = normalized.pop("onstart")
    if "recommended_disk_space" in normalized and "disk_space" not in normalized:
        normalized["disk_space"] = normalized.pop("recommended_disk_space")
    if isinstance(normalized.get("extra_filters"), str):
        normalized["extra_filters"] = json.loads(normalized["extra_filters"])
    return {k: v for k, v in normalized.items() if k in REMOTE_ALLOWED_KEYS}


def write_launch_profile_hash(path: Path, template_hash: str) -> None:
    data = json.loads(path.read_text())
    data.setdefault("template", {})["hash_id"] = template_hash
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")


def result_hash_id(result: dict[str, Any]) -> str | None:
    if result.get("hash_id"):
        return str(result["hash_id"])
    template = result.get("template") or {}
    if template.get("hash_id"):
        return str(template["hash_id"])
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description="Create or update a Vast template from a rendered local payload")
    parser.add_argument("--template", type=Path, required=True, help="rendered local template JSON")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--create", action="store_true", help="create a new remote Vast template")
    mode.add_argument("--hash-id", help="remote Vast template hash_id to update")
    parser.add_argument("--update-launch-profile", type=Path, default=None, help="write resulting template hash into this launch profile")
    parser.add_argument("--yes", action="store_true", help="apply without interactive confirmation")
    if len(sys.argv) == 1:
        parser.print_help()
        return
    args = parser.parse_args()

    manifest_entry = load_manifest_for_template(args.template)
    payload = load_payload(args.template)
    kwargs = update_kwargs(payload)
    action = "create" if args.create else "update"
    print(f"Action:              {action}")
    if args.hash_id:
        print(f"Remote template hash: {args.hash_id}")
    print(f"Local template file:  {args.template}")
    print(f"Manifest entry:       {manifest_entry.get('file')}")
    print(f"Template name:        {kwargs.get('name')}")
    print(f"Image/tag:            {kwargs.get('image')}:{kwargs.get('image_tag')}")
    print(f"Private:              {kwargs.get('private')}")
    print(f"Env bytes:            {len(kwargs.get('env') or '')}")
    if args.update_launch_profile:
        print(f"Launch profile:       {args.update_launch_profile}")
    if not args.yes:
        answer = input(f"{action.capitalize()} this remote Vast template from local rendered payload? [y/N] ").strip().lower()
        if answer != "y":
            print("Aborted.")
            return

    vast = VastAI()
    if args.create:
        # VastAI.create_template injects jup_direct/ssh_direct/private defaults, which
        # conflict with fully rendered template kwargs. Call the lower-level API.
        from vastai.api import offers

        result = offers.create_template(vast.client, **kwargs)
    else:
        result = vast.update_template(args.hash_id, **kwargs)
    print(json.dumps(result, indent=2, sort_keys=True, default=str))

    new_hash = result_hash_id(result)
    if args.update_launch_profile:
        if not new_hash:
            raise SystemExit("Could not find hash_id in Vast result; launch profile not updated.")
        write_launch_profile_hash(args.update_launch_profile, new_hash)
        print(f"Updated {args.update_launch_profile} template.hash_id = {new_hash}")


if __name__ == "__main__":
    main()
