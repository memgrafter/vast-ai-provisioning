#!/usr/bin/env python3
"""Check current Vast infra and launch-profile offer availability without launching."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vastai import VastAI

from scripts.select_and_launch import (
    DEFAULT_LAUNCH_PROFILE,
    get_instances,
    get_volumes,
    load_launch_context,
    print_current_infra,
    print_selected_offer,
    save_json,
    search_policy_offers,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Check Vast infra and launch-profile offers without launching")
    parser.add_argument("--launch-profile", type=Path, default=DEFAULT_LAUNCH_PROFILE)
    parser.add_argument("--skip-current-infra", action="store_true", help="do not query/show existing instances")
    parser.add_argument("--top", type=int, default=1, help="number of passing offers to summarize")
    args = parser.parse_args()

    context = load_launch_context(args.launch_profile)
    launch = context["launch"]
    model = context["model"]

    print("Launch profile")
    print("==============")
    print(f"profile:       {context['launch_profile_path']}")
    print(f"model profile: {context['model_profile_path']}")
    print(f"gpu profile:   {context['gpu_profile_path']}")
    print(f"model:         {model.get('hf_model_id')}")
    print(f"served name:   {model.get('served_model_name')}")
    print(f"r2 prefix:     {model.get('r2_prefix')}")
    print(f"market:        {launch.get('market')}")
    print()

    vast = VastAI()
    if not args.skip_current_infra:
        instances = get_instances(vast)
        volumes = get_volumes(vast)
        save_json(Path("state/current-infra.json"), {"instances": instances, "volumes": volumes})
        print_current_infra(instances, volumes)

    offers = search_policy_offers(vast, context)
    if not offers:
        print("No offers passed policy.")
        return 2

    top = max(1, args.top)
    for idx, offer in enumerate(offers[:top], start=1):
        if top > 1:
            print(f"Passing offer #{idx}")
            print("================")
        save_json(Path(f"offers/{offer['id']}.selected.json"), offer)
        print_selected_offer(offer, context)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
