#!/usr/bin/env python3
"""Apply a locally rendered Vast template payload to a remote Vast template."""
from __future__ import annotations

import argparse
import json
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


def load_payload(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def update_kwargs(payload: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in payload.items() if k not in REMOTE_IGNORED_KEYS and v is not None}


def main() -> None:
    parser = argparse.ArgumentParser(description="Apply a rendered Vast template payload")
    parser.add_argument("--template", type=Path, required=True, help="rendered local template JSON")
    parser.add_argument("--hash-id", required=True, help="remote Vast template hash_id to update")
    parser.add_argument("--yes", action="store_true", help="apply without interactive confirmation")
    args = parser.parse_args()

    payload = load_payload(args.template)
    kwargs = update_kwargs(payload)
    print(f"Remote template hash: {args.hash_id}")
    print(f"Local template file:  {args.template}")
    print(f"Template name:        {kwargs.get('name')}")
    print(f"Image/tag:            {kwargs.get('image')}:{kwargs.get('tag') or kwargs.get('image_tag')}")
    print(f"Env bytes:            {len(kwargs.get('env') or '')}")
    if not args.yes:
        answer = input("Apply this local rendered template to remote Vast template? [y/N] ").strip().lower()
        if answer != "y":
            print("Aborted.")
            return

    vast = VastAI()
    result = vast.update_template(args.hash_id, **kwargs)
    print(json.dumps(result, indent=2, sort_keys=True, default=str))


if __name__ == "__main__":
    main()
