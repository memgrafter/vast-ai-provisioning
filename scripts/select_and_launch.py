#!/usr/bin/env python3
"""Select and optionally launch a Vast instance with explicit cost gates.

Note: verified=true is enforced in the Vast search query when required. The
search query also excludes explicitly deverified offers as a best effort. Vast
can still return some of them, so the consumer script drops explicitly
deverified offers client-side before policy logging/selection.
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

from scripts import launch_ledger
from scripts.monitor_instance_readiness import port_url

COSTING_STATUSES = {"running", "loading", "starting", "stopped", "exited", "unknown", "offline"}
BAD_STATUSES = {"exited", "offline"}
EXCLUDED_VERIFICATION_STATES = {"deverified"}
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


POLICY_PATCH_TOP_LEVEL_KEYS = {"network", "pricing", "reliability", "selection", "spot", "storage"}


def merge_policy_patch(target: dict[str, Any], patch: dict[str, Any]) -> None:
    for key, value in patch.items():
        if key not in POLICY_PATCH_TOP_LEVEL_KEYS:
            allowed = ", ".join(sorted(POLICY_PATCH_TOP_LEVEL_KEYS))
            raise ValueError(f"--relax-policy may only patch policy keys: {allowed}; got {key!r}")
        current = target.get(key)
        if isinstance(current, dict) and isinstance(value, dict):
            merge_nested_policy(current, value)
        else:
            target[key] = value


def merge_nested_policy(target: dict[str, Any], patch: dict[str, Any]) -> None:
    for key, value in patch.items():
        current = target.get(key)
        if isinstance(current, dict) and isinstance(value, dict):
            merge_nested_policy(current, value)
        else:
            target[key] = value


def apply_relax_policy(context: dict[str, Any], patches: list[str]) -> list[dict[str, Any]]:
    applied: list[dict[str, Any]] = []
    for raw_patch in patches:
        try:
            patch = json.loads(raw_patch)
        except json.JSONDecodeError as exc:
            raise SystemExit(f"Invalid --relax-policy JSON: {exc}") from None
        if not isinstance(patch, dict):
            raise SystemExit("--relax-policy must be a JSON object")
        try:
            merge_policy_patch(context["launch"], patch)
        except ValueError as exc:
            raise SystemExit(str(exc)) from None
        applied.append(patch)
    if applied:
        context["relax_policy_patches"] = applied
    return applied


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
            api_url = port_url(inst)
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
            if api_url:
                print(f"    base_url={api_url}/v1")
                print(f"    chat_completions_url={api_url}/v1/chat/completions")
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


def storage_metrics(offer: dict[str, Any], context: dict[str, Any]) -> dict[str, float]:
    storage = context["launch"]["storage"]
    requested_gb = float(storage["disk_gb"])
    storage_raw = offer.get("storage_total_cost")
    total_raw = offer.get("dph_total")
    storage_hour = float(storage_raw) if storage_raw is not None else math.inf
    total_hour = float(total_raw) if total_raw is not None else math.inf
    storage_per_gb_hour = storage_hour / requested_gb if requested_gb > 0 else math.inf
    storage_fraction = storage_hour / total_hour if total_hour > 0 and math.isfinite(total_hour) else math.inf
    compute_hour = max(0.0, total_hour - storage_hour) if math.isfinite(total_hour) else math.inf
    return {
        "requested_gb": requested_gb,
        "storage_hour": storage_hour,
        "storage_per_gb_hour": storage_per_gb_hour,
        "storage_fraction": storage_fraction,
        "compute_hour": compute_hour,
    }


def quote_gpu_name(gpu_name: str) -> str:
    if any(ch.isspace() for ch in gpu_name):
        return json.dumps(gpu_name)
    return gpu_name


def gpu_policy_configs(gpu: dict[str, Any]) -> list[dict[str, Any]]:
    explicit_configs = gpu.get("allowed_gpu_configs") or []
    if explicit_configs:
        configs: list[dict[str, Any]] = []
        for raw in explicit_configs:
            names = raw.get("gpu_names") or [raw.get("gpu_name")]
            for name in names:
                if not name:
                    raise ValueError("allowed_gpu_configs entries must include gpu_name or gpu_names")
                configs.append(
                    {
                        "gpu_name": str(name),
                        "num_gpus": int(raw["num_gpus"]),
                        "min_gpu_total_ram_mb": float(raw.get("min_gpu_total_ram_mb", gpu.get("min_gpu_total_ram_mb", 0))),
                    }
                )
        return configs

    config: dict[str, Any] = {
        "gpu_name": gpu.get("preferred_gpu_name"),
        "allowed_gpu_names": gpu.get("allowed_gpu_names") or [],
        "num_gpus": int(gpu["num_gpus"]),
        "min_gpu_total_ram_mb": float(gpu["min_gpu_total_ram_mb"]),
    }
    return [config]


def offer_gpu_policy_failures(offer: dict[str, Any], gpu: dict[str, Any]) -> list[str]:
    configs = gpu_policy_configs(gpu)
    if gpu.get("allowed_gpu_configs"):
        offer_gpu_name = offer.get("gpu_name")
        same_name = [cfg for cfg in configs if offer_gpu_name == cfg["gpu_name"]]
        if not same_name:
            return ["allowed_gpu_names"]
        try:
            offer_num_gpus = int(offer.get("num_gpus") or 0)
        except Exception:
            offer_num_gpus = 0
        same_count = [cfg for cfg in same_name if offer_num_gpus == cfg["num_gpus"]]
        if not same_count:
            return ["num_gpus"]
        offer_ram_mb = float(offer.get("gpu_total_ram") or 0)
        if not any(offer_ram_mb >= cfg["min_gpu_total_ram_mb"] for cfg in same_count):
            return ["gpu_total_ram"]
        return []

    failures: list[str] = []
    config = configs[0]
    if config.get("gpu_name") and offer.get("gpu_name") != config["gpu_name"]:
        failures.append("gpu_name")
    if config.get("allowed_gpu_names") and offer.get("gpu_name") not in set(config["allowed_gpu_names"]):
        failures.append("allowed_gpu_names")
    if int(offer.get("num_gpus") or 0) != int(config["num_gpus"]):
        failures.append("num_gpus")
    if float(offer.get("gpu_total_ram") or 0) < float(config["min_gpu_total_ram_mb"]):
        failures.append("gpu_total_ram")
    return failures


def offer_passes_policy(offer: dict[str, Any], context: dict[str, Any]) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    launch = context["launch"]
    gpu = context["gpu"]
    pricing = launch["pricing"]
    storage = launch["storage"]
    sm = storage_metrics(offer, context)
    network = launch["network"]
    reliability = launch["reliability"]

    greylisted_machines = {int(x) for x in launch.get("selection", {}).get("greylisted_machine_ids", [])}
    try:
        machine_id = int(offer.get("machine_id"))
    except Exception:
        machine_id = -1

    reasons.extend(offer_gpu_policy_failures(offer, gpu))
    checks = [
        (machine_id not in greylisted_machines, "greylisted_machine"),
        (offer.get("verification") != "deverified", "deverified"),
        (float(offer.get("cuda_max_good") or 0) >= float(gpu["min_cuda_max_good"]), "cuda_max_good"),
        (float(offer.get("dph_total") or math.inf) <= float(pricing["max_dph_total"]), "dph_total"),
        (sm["storage_hour"] <= float(storage["max_storage_total_cost_per_hour"]), "storage_total_cost"),
        (sm["storage_per_gb_hour"] <= float(storage["max_storage_cost_per_gb_hour"]), "storage_cost_per_gb_hour"),
        (
            "max_storage_fraction_of_total" not in storage
            or sm["storage_fraction"] <= float(storage["max_storage_fraction_of_total"]),
            "storage_fraction_of_total",
        ),
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


def has_excluded_verification(offer: dict[str, Any]) -> bool:
    return offer.get("verification") in EXCLUDED_VERIFICATION_STATES


def selection_sort_key(offer: dict[str, Any], context: dict[str, Any]) -> tuple[bool, float, float]:
    return (
        not is_preferred_machine(offer, context),
        effective_cost(offer, context),
        -float(offer.get("reliability2") or 0),
    )


def search_query_for_gpu_config(gpu: dict[str, Any], config: dict[str, Any], require_verified: bool, geo_query: str) -> str:
    filters = [
        f"num_gpus={config['num_gpus']}",
        "rentable=true",
    ]
    gpu_name = config.get("gpu_name") or gpu.get("preferred_gpu_name")
    if gpu_name:
        filters.append(f"gpu_name={quote_gpu_name(str(gpu_name))}")
    if require_verified:
        filters.append("verified=true")
    filters.append("verification!=deverified")
    # Vast search query expects GPU RAM in GB-ish units; offer field is returned in MB.
    min_gpu_ram_gb = float(config["min_gpu_total_ram_mb"]) / 1000.0
    filters.append(f"gpu_total_ram>={min_gpu_ram_gb}")
    if float(gpu.get("min_cuda_max_good") or 0) > 0:
        filters.append(f"cuda_max_good>={gpu['min_cuda_max_good']}")
    if geo_query:
        filters.append(geo_query)
    return " ".join(filters)


def search_policy_offers(vast: VastAI, context: dict[str, Any]) -> list[dict[str, Any]]:
    launch = context["launch"]
    gpu = context["gpu"]
    storage_gb = float(launch["storage"]["disk_gb"])
    require_verified = bool(launch["reliability"].get("require_verified", False))
    selection = launch.get("selection", {})
    geo_query = str(selection.get("geo_query", "")).strip()
    market = "interruptible" if launch.get("market") in {"interruptible", "bid", "spot"} else "on-demand"
    no_default = bool(selection.get("search_no_default", False))
    search_limit = int(selection.get("search_limit", 50))
    queries = [search_query_for_gpu_config(gpu, config, require_verified, geo_query) for config in gpu_policy_configs(gpu)]
    raw_by_id: dict[Any, dict[str, Any]] = {}
    for query in queries:
        for offer in vast.search_offers(query=query, type=market, order="dph_total", limit=search_limit, storage=storage_gb, no_default=no_default):
            raw_by_id[offer.get("id", id(offer))] = offer
    raw_values = list(raw_by_id.values())
    raw = [offer for offer in raw_values if not has_excluded_verification(offer)]
    excluded_deverified_count = len(raw_values) - len(raw)
    passing = []
    print("Offer policy check")
    print("==================")
    print(f"market: {market}")
    for query in queries:
        print(f"query: {query}")
    print(f"search_limit: {search_limit}")
    if no_default:
        print("search_no_default: true")
    if excluded_deverified_count:
        print(f"excluded_deverified: {excluded_deverified_count}")
    for offer in raw:
        ok, reasons = offer_passes_policy(offer, context)
        status = "PASS" if ok else "FAIL " + ",".join(reasons)
        preferred = "*" if is_preferred_machine(offer, context) else " "
        greylisted = "!" if is_greylisted_machine(offer, context) else " "
        sm = storage_metrics(offer, context)
        print(
            f"{status:22} "
            f"pref={preferred} grey={greylisted} "
            f"id={offer.get('id')} gpu={offer.get('gpu_name')} "
            f"cuda={offer.get('cuda_max_good')} "
            f"dph={money(offer.get('dph_total'))}/hr "
            f"storage={money(sm['storage_hour'])}/hr "
            f"storageGB={money(sm['storage_per_gb_hour'])}/GBhr "
            f"storagePct={number(sm['storage_fraction'] * 100, 1)}% "
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
    sm = storage_metrics(offer, context)
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
    print(f"compute hourly:     {money(sm['compute_hour'])}/hr")
    print(f"storage hourly:     {money(storage_hour)}/hr for {sm['requested_gb']:.0f}GB")
    print(f"storage per GB-hr:  {money(sm['storage_per_gb_hour'])}/GB-hr")
    print(f"storage share:      {number(sm['storage_fraction'] * 100, 1)}%")
    print(f"total hourly:       {money(dph)}/hr")
    warn_storage_fraction = float(launch["storage"].get("warn_storage_fraction_of_total", 0.25))
    if sm["storage_fraction"] > warn_storage_fraction:
        print(f"WARN: storage is {number(sm['storage_fraction'] * 100, 1)}% of total hourly cost")
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


def print_api_config_and_smoke(
    vast: VastAI,
    instance_id: int,
    model_name: str,
    message: str,
    *,
    smoke_timeout: int,
    smoke_interval: float,
    smoke_chat_timeout: int,
    smoke_max_tokens: int,
) -> int:
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

    deadline = time.time() + smoke_timeout
    attempt = 0
    last_models: Any = None
    last_chat: Any = None
    payload: dict[str, Any] = {
        "model": model_name,
        "messages": [{"role": "user", "content": message}],
        "temperature": 0,
    }
    if smoke_max_tokens > 0:
        payload["max_tokens"] = smoke_max_tokens

    while True:
        attempt += 1
        remaining = max(1, int(deadline - time.time()))
        code, models = api_get_json(f"{base_url}/models", api_key, timeout=min(10, remaining))
        last_models = models
        print(f"models_http={code} attempt={attempt}", flush=True)
        if code == 200:
            print("models:", json.dumps(models, default=str)[:500], flush=True)
            chat_timeout = max(1, min(smoke_chat_timeout, int(deadline - time.time())))
            code, chat = api_post_json(chat_completions_url, api_key, payload, timeout=chat_timeout)
            last_chat = chat
            print(f"chat_http={code} attempt={attempt}", flush=True)
            print(json.dumps(chat, indent=2, default=str)[:2000], flush=True)
            if code == 200:
                return 0
        if time.time() >= deadline:
            print(
                "WARN: smoke test timed out; "
                f"last_models={str(last_models)[:500]} last_chat={str(last_chat)[:500]}",
                file=sys.stderr,
                flush=True,
            )
            return 1
        time.sleep(min(smoke_interval, max(0.0, deadline - time.time())))


def poll_instance(vast: VastAI, instance_id: int, timeout_s: int) -> dict[str, Any]:
    start = time.time()
    last: dict[str, Any] = {}
    while time.time() - start < timeout_s:
        last = vast.show_instance(id=instance_id)
        actual_status = last.get("actual_status")
        status = str(actual_status or last.get("status") or last.get("cur_state") or "unknown")
        print(f"instance {instance_id} status={status}")
        if status == "running":
            return last
        if status in BAD_STATUSES:
            return last
        # Vast can briefly report actual_status/status as unknown immediately
        # after create_instance even when cur_state will settle to running.
        # Keep polling unknown instead of treating it as terminal.
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
    parser.add_argument("--smoke-timeout", type=int, default=60, help="max seconds for post-launch models/chat smoke polling")
    parser.add_argument("--smoke-interval", type=float, default=2.0, help="seconds between failed smoke attempts")
    parser.add_argument("--smoke-chat-timeout", type=int, default=30, help="max seconds for each smoke chat request")
    parser.add_argument("--smoke-max-tokens", type=int, default=8, help="max generated tokens for smoke chat; <=0 omits max_tokens")
    parser.add_argument(
        "--relax-policy",
        action="append",
        default=[],
        metavar="JSON",
        help="deep-merge a JSON object into launch policy keys (pricing/storage/network/reliability/selection/spot)",
    )
    args = parser.parse_args()

    context = load_launch_context(args.launch_profile)
    applied_policy_patches = apply_relax_policy(context, args.relax_policy)
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
    if applied_policy_patches:
        print("relax policy:")
        for patch in applied_policy_patches:
            print(json.dumps(patch, sort_keys=True))
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
        selected_offer_path = Path(f"offers/{offer['id']}.selected.json")
        save_json(selected_offer_path, offer)
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
    create_started_at = launch_ledger.now_utc()
    result = vast.create_instance(**create_kwargs)
    create_returned_at = launch_ledger.now_utc()
    print("Create result:")
    print(json.dumps(result, indent=2, sort_keys=True, default=str))
    save_json(Path("state/last-create-result.json"), result)
    instance_id = result.get("new_contract") or result.get("id")
    if not instance_id:
        print("No instance id in create result; stop here.")
        return
    selected_offer_path = Path(f"offers/{selected['id']}.selected.json")
    try:
        launch_ledger.record_created_launch(
            context=context,
            offer=selected,
            create_result=result,
            instance_id=int(instance_id),
            selected_offer_json_path=selected_offer_path,
            create_started_at=create_started_at,
            create_returned_at=create_returned_at,
        )
        print(f"Recorded launch ledger row for vast:instance:{int(instance_id)}")
    except Exception as exc:
        print(f"WARN: launch ledger insert failed: {exc}", file=sys.stderr)
    info = poll_instance(vast, int(instance_id), args.poll_timeout)
    instance_json_path = Path(f"instances/{instance_id}.json")
    save_json(instance_json_path, info)
    try:
        launch_ledger.update_instance_snapshot(instance_id=int(instance_id), info=info, instance_json_path=instance_json_path)
    except Exception as exc:
        print(f"WARN: launch ledger instance update failed: {exc}", file=sys.stderr)
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
        try:
            launch_ledger.update_monitor_result(instance_id=int(instance_id), monitor_exit_code=result.returncode)
            if result.returncode == 4:
                launch_ledger.mark_destroyed(
                    instance_id=int(instance_id),
                    reason="monitor_destroyed_failed_launch",
                    destroyed_by_script=True,
                )
        except Exception as exc:
            print(f"WARN: launch ledger monitor update failed: {exc}", file=sys.stderr)
        if result.returncode == 4:
            print("Monitor destroyed the instance; skipping post-launch smoke.")
            return
        if result.returncode != 0:
            raise SystemExit(result.returncode)

    if not args.no_smoke_chat:
        smoke_code = print_api_config_and_smoke(
            vast,
            int(instance_id),
            model["served_model_name"],
            args.smoke_message,
            smoke_timeout=args.smoke_timeout,
            smoke_interval=args.smoke_interval,
            smoke_chat_timeout=args.smoke_chat_timeout,
            smoke_max_tokens=args.smoke_max_tokens,
        )
        try:
            launch_ledger.update_smoke_result(instance_id=int(instance_id), smoke_exit_code=smoke_code)
        except Exception as exc:
            print(f"WARN: launch ledger smoke update failed: {exc}", file=sys.stderr)
        if smoke_code != 0:
            raise SystemExit(smoke_code)


if __name__ == "__main__":
    main()
