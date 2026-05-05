#!/usr/bin/env python3
"""Select and optionally launch a Vast instance with explicit cost gates.

Note: verified=true is enforced in the Vast search query only; returned offers may
report verified as null, so we do not post-filter it client-side.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vastai import VastAI

from scripts.monitor_instance_readiness import port_url

COSTING_STATUSES = {"running", "loading", "starting", "stopped", "exited", "unknown", "offline"}
BAD_STATUSES = {"exited", "unknown", "offline"}
DEFAULT_LAUNCH_PROFILE = Path("config/launch-profiles/qwen3.5-9b-awq.interruptible.json")


def money(value: Any) -> str:
    try:
        if value is None:
            return "n/a"
        return f"${float(value):.4f}"
    except Exception:
        return "n/a"


def number(value: Any, digits: int = 2) -> str:
    try:
        if value is None:
            return "n/a"
        return f"{float(value):.{digits}f}"
    except Exception:
        return "n/a"


def ask(prompt: str) -> bool:
    return input(f"{prompt} [y/N] ").strip().lower() == "y"


def save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True, default=str) + "\n")


def get_instances(vast: VastAI) -> list[dict[str, Any]]:
    try:
        return vast.show_instances()
    except Exception as e:
        print(f"WARN: show_instances failed: {e}", file=sys.stderr)
        return []


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def load_launch_context(path: Path) -> dict[str, Any]:
    launch = load_json(path)
    model_path = Path(launch["model_profile"])
    gpu_path = Path(launch["gpu_profile"])
    model = load_json(model_path)
    gpu = load_json(gpu_path)
    return {
        "launch_profile_path": str(path),
        "launch": launch,
        "model_profile_path": str(model_path),
        "model": model,
        "gpu_profile_path": str(gpu_path),
        "gpu": gpu,
    }


def get_volumes(vast: VastAI) -> dict[str, Any]:
    # VastAI.search_volumes/search_network_volumes return marketplace offers,
    # not owned/costing volumes. Until we wire an owned-volume endpoint, do not
    # include them in current burn calculations.
    return {
        "volumes": [],
        "network_volumes": [],
        "note": "owned volumes not checked; marketplace volume offers skipped",
    }


def instance_hourly_cost(inst: dict[str, Any]) -> float:
    for key in ["dph_total", "actual_dph", "cur_state_dph", "dph_base"]:
        val = inst.get(key)
        if isinstance(val, (int, float)):
            return float(val)
    gpu_cost = inst.get("gpu_cost")
    storage_cost = inst.get("storage_cost") or inst.get("storage_total_cost")
    total = 0.0
    found = False
    for val in [gpu_cost, storage_cost]:
        if isinstance(val, (int, float)):
            total += float(val)
            found = True
    return total if found else 0.0


def print_current_infra(instances: list[dict[str, Any]], volumes: dict[str, Any]) -> float:
    print("Current Vast infra")
    print("==================")
    total_known = 0.0
    if not instances:
        print("Instances: none found")
    else:
        print("Instances:")
        for inst in instances:
            status = inst.get("actual_status") or inst.get("status") or "unknown"
            if str(status).lower() not in COSTING_STATUSES:
                continue
            cost = instance_hourly_cost(inst)
            total_known += cost
            print(
                "  "
                f"id={inst.get('id') or inst.get('contract_id')} "
                f"status={status} "
                f"label={inst.get('label')!r} "
                f"gpu={inst.get('gpu_name') or inst.get('gpu_names')} "
                f"machine={inst.get('machine_id')} "
                f"disk={inst.get('disk_space') or inst.get('disk')}GB "
                f"known_cost={money(cost)}/hr"
            )
    print("Volumes:")
    any_vol = False
    for group in ["volumes", "network_volumes"]:
        vals = volumes.get(group) or []
        if vals:
            any_vol = True
            print(f"  {group}:")
            for vol in vals:
                cost = 0.0
                for k in ["dph_total", "cost_per_hour", "storage_cost", "price_per_hour"]:
                    if isinstance(vol.get(k), (int, float)):
                        cost = float(vol[k])
                        break
                total_known += cost
                print(
                    "    "
                    f"id={vol.get('id')} name={vol.get('name')!r} "
                    f"status={vol.get('status')} size={vol.get('size') or vol.get('disk_space')} "
                    f"known_cost={money(cost)}/hr"
                )
    if not any_vol:
        print("  none found")
    if volumes.get("note"):
        print(f"  NOTE: {volumes['note']}")
    if volumes.get("volumes_error"):
        print(f"  WARN volumes query: {volumes['volumes_error']}")
    if volumes.get("network_volumes_error"):
        print(f"  WARN network volumes query: {volumes['network_volumes_error']}")
    print(f"Known current hourly burn, excluding unchecked owned volumes: {money(total_known)}/hr")
    print()
    return total_known


def offer_passes_policy(offer: dict[str, Any], context: dict[str, Any]) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    launch = context["launch"]
    gpu = context["gpu"]
    pricing = launch["pricing"]
    storage = launch["storage"]
    network = launch["network"]
    reliability = launch["reliability"]
    require_verified = bool(reliability.get("require_verified", False))

    greylisted_machines = {int(x) for x in launch.get("selection", {}).get("greylisted_machine_ids", [])}
    try:
        machine_id = int(offer.get("machine_id"))
    except Exception:
        machine_id = -1

    checks = [
        (machine_id not in greylisted_machines, "greylisted_machine"),
        (
            (not gpu.get("preferred_gpu_name"))
            or offer.get("gpu_name") == gpu["preferred_gpu_name"],
            "gpu_name",
        ),
        (
            (not gpu.get("allowed_gpu_names"))
            or offer.get("gpu_name") in set(gpu["allowed_gpu_names"]),
            "allowed_gpu_names",
        ),
        (int(offer.get("num_gpus") or 0) == int(gpu["num_gpus"]), "num_gpus"),
        (float(offer.get("gpu_total_ram") or 0) >= float(gpu["min_gpu_total_ram_mb"]), "gpu_total_ram"),
        (float(offer.get("cuda_max_good") or 0) >= float(gpu["min_cuda_max_good"]), "cuda_max_good"),
        (float(offer.get("dph_total") or math.inf) <= float(pricing["max_dph_total"]), "dph_total"),
        (float(offer.get("storage_total_cost") or math.inf) <= float(storage["max_storage_total_cost_per_hour"]), "storage_total_cost"),
        (float(offer.get("disk_bw") or offer.get("disk_io") or 0) >= float(storage.get("min_disk_bw") or 0), "disk_bw"),
        (float(offer.get("internet_down_cost_per_tb") or 0) <= float(network["max_internet_down_cost_per_tb"]), "internet_down_cost_per_tb"),
        (float(offer.get("internet_up_cost_per_tb") or 0) <= float(network["max_internet_up_cost_per_tb"]), "internet_up_cost_per_tb"),
        (float(offer.get("inet_down") or 0) >= float(network["min_inet_down"]), "inet_down"),
        (int(offer.get("direct_port_count") or 0) >= int(network["min_direct_port_count"]), "direct_port_count"),
        (float(offer.get("reliability2") or 0) >= float(reliability["min_reliability2"]), "reliability2"),
        (float(offer.get("disk_space") or 0) >= float(storage["disk_gb"]), "disk_space"),
    ]
    for passed, name in checks:
        if not passed:
            reasons.append(name)
    return not reasons, reasons


def effective_cost(offer: dict[str, Any], context: dict[str, Any]) -> float:
    launch = context["launch"]
    tb = float(launch.get("selection", {}).get("expected_model_download_tb", context["model"].get("expected_model_download_tb", 0)))
    return float(offer.get("dph_total") or math.inf) + tb * float(offer.get("internet_down_cost_per_tb") or 0)


def is_preferred_machine(offer: dict[str, Any], context: dict[str, Any]) -> bool:
    preferred = {int(x) for x in context["launch"].get("selection", {}).get("preferred_machine_ids", [])}
    try:
        return int(offer.get("machine_id")) in preferred
    except Exception:
        return False


def is_greylisted_machine(offer: dict[str, Any], context: dict[str, Any]) -> bool:
    greylisted = {int(x) for x in context["launch"].get("selection", {}).get("greylisted_machine_ids", [])}
    try:
        return int(offer.get("machine_id")) in greylisted
    except Exception:
        return False


def selection_sort_key(offer: dict[str, Any], context: dict[str, Any]) -> tuple[bool, float, float]:
    return (
        not is_preferred_machine(offer, context),
        effective_cost(offer, context),
        -float(offer.get("reliability2") or 0),
    )


def search_policy_offers(vast: VastAI, context: dict[str, Any]) -> list[dict[str, Any]]:
    launch = context["launch"]
    gpu = context["gpu"]
    storage_gb = float(launch["storage"]["disk_gb"])
    require_verified = bool(launch["reliability"].get("require_verified", False))
    verified_filter = "verified=true " if require_verified else ""
    filters = [
        f"num_gpus={gpu['num_gpus']}",
        "rentable=true",
    ]
    if gpu.get("preferred_gpu_name"):
        filters.append(f"gpu_name={gpu['preferred_gpu_name']}")
    if require_verified:
        filters.append("verified=true")
    # Vast search query expects GPU RAM in GB-ish units; offer field is returned in MB.
    min_gpu_ram_gb = float(gpu["min_gpu_total_ram_mb"]) / 1000.0
    filters.append(f"gpu_total_ram>={min_gpu_ram_gb}")
    if float(gpu.get("min_cuda_max_good") or 0) > 0:
        filters.append(f"cuda_max_good>={gpu['min_cuda_max_good']}")
    query = " ".join(filters)
    market = "interruptible" if launch.get("market") in {"interruptible", "bid", "spot"} else "on-demand"
    raw = vast.search_offers(query=query, type=market, order="dph_total", limit=50, storage=storage_gb)
    passing = []
    print("Offer policy check")
    print("==================")
    print(f"market: {market}")
    print(f"query: {query}")
    for offer in raw:
        ok, reasons = offer_passes_policy(offer, context)
        status = "PASS" if ok else "FAIL " + ",".join(reasons)
        preferred = "*" if is_preferred_machine(offer, context) else " "
        greylisted = "!" if is_greylisted_machine(offer, context) else " "
        print(
            f"{status:22} "
            f"pref={preferred} grey={greylisted} "
            f"id={offer.get('id')} gpu={offer.get('gpu_name')} "
            f"cuda={offer.get('cuda_max_good')} "
            f"dph={money(offer.get('dph_total'))}/hr "
            f"storage={money(offer.get('storage_total_cost'))}/hr "
            f"disk_bw={number(offer.get('disk_bw') or offer.get('disk_io'), 1)} "
            f"downTB={money(offer.get('internet_down_cost_per_tb'))} "
            f"upTB={money(offer.get('internet_up_cost_per_tb'))} "
            f"inet_down={number(offer.get('inet_down'), 1)}Mbps "
            f"inet_down_MBps={number((float(offer.get('inet_down') or 0) / 8.0), 1)} "
            f"rel={number(offer.get('reliability2'), 4)} "
            f"eff={money(effective_cost(offer, context))}"
        )
        if ok:
            passing.append(offer)
    passing.sort(key=lambda o: selection_sort_key(o, context))
    print()
    return passing


def print_selected_offer(offer: dict[str, Any], context: dict[str, Any]) -> None:
    launch = context["launch"]
    model = context["model"]
    smoke_minutes = float(launch["pricing"].get("target_first_test_minutes", 10))
    dph = float(offer.get("dph_total") or 0)
    storage_hour = float(offer.get("storage_total_cost") or 0)
    down_tb = float(offer.get("internet_down_cost_per_tb") or 0)
    up_tb = float(offer.get("internet_up_cost_per_tb") or 0)
    expected_tb = float(launch.get("selection", {}).get("expected_model_download_tb", model.get("expected_model_download_tb", 0)))
    smoke_compute = dph * smoke_minutes / 60.0
    pull_cost = expected_tb * down_tb
    print("Selected offer")
    print("==============")
    print(f"offer_id:       {offer.get('id')}")
    print(f"machine_id:     {offer.get('machine_id')}{' (preferred)' if is_preferred_machine(offer, context) else ''}")
    print(f"gpu:            {offer.get('gpu_name')} {offer.get('gpu_total_ram')}MB")
    print(f"cuda/driver:    {offer.get('cuda_max_good')} / {offer.get('driver_version')}")
    print(f"reliability2:   {number(offer.get('reliability2'), 4)}")
    print(f"direct ports:   {offer.get('direct_port_count')}")
    print(f"disk available: {number(offer.get('disk_space'), 1)}GB")
    print(f"disk bw:        {number(offer.get('disk_bw') or offer.get('disk_io'), 1)} MB/s")
    inet_down_mbps = float(offer.get('inet_down') or 0)
    print(f"inet down/up:   {number(offer.get('inet_down'), 1)} / {number(offer.get('inet_up'), 1)} Mbps")
    print(f"inet down:      {number(inet_down_mbps / 8.0, 1)} MB/s theoretical")
    print()
    print("Costs")
    print("=====")
    print(f"base hourly:        {money(offer.get('dph_base'))}/hr")
    print(f"storage hourly:     {money(storage_hour)}/hr for {launch['storage']['disk_gb']}GB")
    print(f"total hourly:       {money(dph)}/hr")
    print(f"per minute:         {money(dph / 60.0)}/min")
    print(f"per second:         {money(dph / 3600.0)}/sec")
    print(f"download cost/TB:   {money(down_tb)}/TB")
    print(f"upload cost/TB:     {money(up_tb)}/TB")
    print(f"expected pull TB:   {expected_tb}")
    print(f"expected pull cost: {money(pull_cost)}")
    print(f"{smoke_minutes:.0f}m smoke compute/storage: {money(smoke_compute)}")
    print(f"{smoke_minutes:.0f}m smoke total estimate:  {money(smoke_compute + pull_cost)}")
    print()


def api_get_json(url: str, api_key: str, timeout: int = 10) -> tuple[int, Any]:
    req = Request(url, headers={"Authorization": f"Bearer {api_key}"})
    try:
        with urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode() or "{}")
    except HTTPError as exc:
        return exc.code, exc.read().decode(errors="replace")
    except URLError as exc:
        return 0, str(exc)


def api_post_json(url: str, api_key: str, payload: dict[str, Any], timeout: int = 120) -> tuple[int, Any]:
    body = json.dumps(payload).encode()
    req = Request(
        url,
        data=body,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode() or "{}")
    except HTTPError as exc:
        return exc.code, exc.read().decode(errors="replace")
    except URLError as exc:
        return 0, str(exc)


def print_api_config_and_smoke(vast: VastAI, instance_id: int, model_name: str, message: str) -> int:
    api_key = os.environ.get("VLLM_API_KEY")
    if not api_key:
        print("WARN: local VLLM_API_KEY is missing; cannot smoke chat request.", file=sys.stderr)
        return 1
    info = vast.show_instance(id=instance_id)
    url = port_url(info)
    if not url:
        print("WARN: no external URL found for container port 8000; cannot print chat endpoint.", file=sys.stderr)
        return 1
    base_url = f"{url}/v1"
    chat_completions_url = f"{base_url}/chat/completions"
    print("OpenAI-compatible API")
    print("=====================")
    print(f"base_url={base_url}")
    print(f"chat_completions_url={chat_completions_url}")
    print(f"model={model_name}")
    print("auth_header=Authorization: Bearer $VLLM_API_KEY")
    code, models = api_get_json(f"{base_url}/models", api_key)
    print(f"models_http={code}")
    if code == 200:
        print("models:", json.dumps(models, default=str)[:500])
    code, chat = api_post_json(
        chat_completions_url,
        api_key,
        {
            "model": model_name,
            "messages": [{"role": "user", "content": message}],
            "max_tokens": 64,
            "temperature": 0,
        },
    )
    print(f"chat_http={code}")
    print(json.dumps(chat, indent=2, default=str)[:2000])
    return 0 if code == 200 else 1


def poll_instance(vast: VastAI, instance_id: int, timeout_s: int) -> dict[str, Any]:
    start = time.time()
    last: dict[str, Any] = {}
    while time.time() - start < timeout_s:
        last = vast.show_instance(id=instance_id)
        status = str(last.get("actual_status") or last.get("status") or "unknown")
        print(f"instance {instance_id} status={status}")
        if status == "running":
            return last
        if status in BAD_STATUSES:
            return last
        time.sleep(10)
    return last


def main() -> None:
    parser = argparse.ArgumentParser(description="Select and launch Vast instance with approval gates")
    parser.add_argument("--launch-profile", type=Path, default=DEFAULT_LAUNCH_PROFILE)
    parser.add_argument("--dry-run", action="store_true", help="show selected offer, then exit before launch")
    parser.add_argument("--check-only", action="store_true", help="read-only check: no approval prompts and no launch")
    parser.add_argument("--skip-current-infra", action="store_true", help="with --check-only, skip current infra query")
    parser.add_argument("--top", type=int, default=1, help="with --check-only, number of passing offers to summarize")
    parser.add_argument("--yes-current-infra", action="store_true")
    parser.add_argument("--yes-launch", action="store_true")
    parser.add_argument("--poll-timeout", type=int, default=900)
    parser.add_argument("--no-monitor", action="store_true", help="do not monitor readiness after launch")
    parser.add_argument("--no-destroy-on-monitor-fail", action="store_true", help="leave failed monitored launches running")
    parser.add_argument("--monitor-timeout", type=int, default=1800, help="readiness monitor timeout seconds")
    parser.add_argument("--monitor-interval", type=int, default=15, help="readiness monitor poll interval seconds")
    parser.add_argument("--no-smoke-chat", action="store_true", help="do not print endpoint and run one chat completion after readiness")
    parser.add_argument("--smoke-message", default="Say hello in one short sentence.", help="message for post-launch chat smoke")
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

    if not (args.check_only and args.skip_current_infra):
        instances = get_instances(vast)
        volumes = get_volumes(vast)
        save_json(Path("state/current-infra.json"), {"instances": instances, "volumes": volumes})
        print_current_infra(instances, volumes)
    if not args.check_only and not args.yes_current_infra and not ask("Continue to search/select a new instance?"):
        print("Aborted before search.")
        return

    offers = search_policy_offers(vast, context)
    if not offers:
        raise SystemExit("No offers passed policy.")
    selected = offers[0]
    top = max(1, args.top if args.check_only else 1)
    for idx, offer in enumerate(offers[:top], start=1):
        if top > 1:
            print(f"Passing offer #{idx}")
            print("================")
        save_json(Path(f"offers/{offer['id']}.selected.json"), offer)
        print_selected_offer(offer, context)

    if args.check_only:
        print("Check only: not launching.")
        return
    if args.dry_run:
        print("Dry run: not launching.")
        return
    if not args.yes_launch and not ask("Launch this instance?"):
        print("Aborted before launch.")
        return

    create_kwargs = {
        "id": int(selected["id"]),
        "disk": float(launch["storage"]["disk_gb"]),
        "template_hash": launch["template"]["hash_id"],
        "label": f"{launch['name']}-{model['served_model_name']}",
    }
    if launch.get("market") in {"interruptible", "bid", "spot"}:
        create_kwargs["price"] = float(launch["spot"]["max_bid_dph"])
    result = vast.create_instance(**create_kwargs)
    print("Create result:")
    print(json.dumps(result, indent=2, sort_keys=True, default=str))
    save_json(Path("state/last-create-result.json"), result)
    instance_id = result.get("new_contract") or result.get("id")
    if not instance_id:
        print("No instance id in create result; stop here.")
        return
    info = poll_instance(vast, int(instance_id), args.poll_timeout)
    save_json(Path(f"instances/{instance_id}.json"), info)
    print(f"Saved instance details to instances/{instance_id}.json")

    if not args.no_monitor:
        monitor_cmd = [
            sys.executable,
            "scripts/monitor_instance_readiness.py",
            str(instance_id),
            "--timeout",
            str(args.monitor_timeout),
            "--interval",
            str(args.monitor_interval),
        ]
        if not args.no_destroy_on_monitor_fail:
            monitor_cmd += ["--destroy-on-fail", "--yes-destroy"]
        print("Starting readiness monitor:")
        print("  " + " ".join(monitor_cmd))
        result = subprocess.run(monitor_cmd, check=False)
        if result.returncode not in {0, 4}:
            raise SystemExit(result.returncode)

    if not args.no_smoke_chat:
        smoke_code = print_api_config_and_smoke(vast, int(instance_id), model["served_model_name"], args.smoke_message)
        if smoke_code != 0:
            raise SystemExit(smoke_code)


if __name__ == "__main__":
    main()
