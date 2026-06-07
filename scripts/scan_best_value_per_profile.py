#!/usr/bin/env python3
"""Scan every launch profile, record best passing Vast offer to market_offers table.

Intended to run every ~60s (cron or similar).  Builds a time-series of what the
market looks like for each profile — eventually helps establish acceptable price
thresholds and spot opportunities for larger GPUs (H200, etc.).

Usage:
  . env.vast-management
  ./run.sh scripts/scan_best_value_per_profile.py [--skip-interruptible]

Output:
  One row per (profile, scan) in the market_offers table in state/launches.sqlite3.
  Only the cheapest passing offer per profile is recorded each run.

API calls use encapsulated backoff with jitter (1s, 2s, 8s, then give up).
Failed calls are logged to logs/api-errors.log alongside the profile name.
"""
from __future__ import annotations

import argparse
import json
import math
import random
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vastai import VastAI

from scripts import launch_ledger


LOG_DIR = Path("logs")
API_ERROR_LOG = LOG_DIR / "api-errors.log"


# ---------------------------------------------------------------------------
# Backoff helper
# ---------------------------------------------------------------------------

BACKOFF_DELAYS = [1, 2, 8]
_verbose_global: bool = False


def _log_api_error(profile_label: str, attempt: int, total_attempts: int, exc: Exception) -> None:
    """Write a structured one-liner to logs/api-errors.log."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    msg = f"{ts} profile={profile_label} attempt={attempt}/{total_attempts} error={exc}\n"
    with API_ERROR_LOG.open("a") as f:
        f.write(msg)


def search_with_backoff(vast: VastAI, context: dict[str, Any], *, search_limit: int, profile_label: str) -> list[dict[str, Any]]:
    """Call search_policy_offers with exponential backoff + jitter.

    Logs every failure to logs/api-errors.log.  On final failure, prints to
    stderr and returns [] so the profile is skipped for this scan cycle.
    """
    for attempt, delay in enumerate(BACKOFF_DELAYS, start=1):
        try:
            offers = search_policy_offers(vast, context, search_limit=search_limit)
            return offers
        except Exception as exc:
            jittered = delay + random.uniform(-0.3, 0.3)
            _log_api_error(profile_label, attempt, len(BACKOFF_DELAYS), exc)
            if attempt < len(BACKOFF_DELAYS):
                if _verbose_global:
                    print(f" retry in {jittered:.1f}s (attempt {attempt}/{len(BACKOFF_DELAYS)})", end="", flush=True)
                time.sleep(jittered)
            else:
                print(f"  ERROR {profile_label}: gave up after {len(BACKOFF_DELAYS)} attempts ({exc})", file=sys.stderr)
    return []

# ---------------------------------------------------------------------------
# Shared helpers — inlined from select_and_launch.py to avoid a refactor up-front.
# If this file and select_and_launch.py diverge meaningfully, extract these
# into scripts/_shared_launch.py.
# ---------------------------------------------------------------------------

POLICY_PATCH_TOP_LEVEL_KEYS = {"network", "pricing", "reliability", "selection", "spot", "storage"}
EXCLUDED_VERIFICATION_STATES = {"deverified"}


def money(value: Any) -> str:
    try:
        if value is None:
            return "n/a"
        return f"${float(value):.4f}"
    except Exception:
        return "n/a"


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
    model = context["model"]
    tb = float(launch.get("selection", {}).get("expected_model_download_tb", model.get("expected_model_download_tb", 0)))
    return float(offer.get("dph_total") or math.inf) + tb * float(offer.get("internet_down_cost_per_tb") or 0)


def has_excluded_verification(offer: dict[str, Any]) -> bool:
    return offer.get("verification") in EXCLUDED_VERIFICATION_STATES


def selection_sort_key(offer: dict[str, Any], context: dict[str, Any]) -> tuple[bool, float, float]:
    return (
        False,  # no preferred-machine boost in scan mode
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
    min_gpu_ram_gb = float(config["min_gpu_total_ram_mb"]) / 1000.0
    filters.append(f"gpu_total_ram>={min_gpu_ram_gb}")
    if float(gpu.get("min_cuda_max_good") or 0) > 0:
        filters.append(f"cuda_max_good>={gpu['min_cuda_max_good']}")
    if geo_query:
        filters.append(geo_query)
    return " ".join(filters)


def search_policy_offers(vast: VastAI, context: dict[str, Any], search_limit: int = 5) -> list[dict[str, Any]]:
    """Return offers matching the profile's policy, sorted cheapest-first.

    This is the same logic as select_and_launch.py's search_policy_offers but
    with no side-effects (no print, no file saves, no preferred-machine boost).
    """
    launch = context["launch"]
    gpu = context["gpu"]
    storage_gb = float(launch["storage"]["disk_gb"])
    require_verified = bool(launch["reliability"].get("require_verified", False))
    selection = launch.get("selection", {})
    geo_query = str(selection.get("geo_query", "")).strip()
    market = "interruptible" if launch.get("market") in {"interruptible", "bid", "spot"} else "on-demand"
    no_default = bool(selection.get("search_no_default", False))
    queries = [search_query_for_gpu_config(gpu, config, require_verified, geo_query) for config in gpu_policy_configs(gpu)]

    raw_by_id: dict[Any, dict[str, Any]] = {}
    for query in queries:
        for offer in vast.search_offers(query=query, type=market, order="dph_total", limit=search_limit, storage=storage_gb, no_default=no_default):
            raw_by_id[offer.get("id", id(offer))] = offer

    raw = [o for o in raw_by_id.values() if not has_excluded_verification(o)]
    passing = [o for o in raw if offer_passes_policy(o, context)[0]]
    passing.sort(key=lambda o: selection_sort_key(o, context))
    return passing


# ---------------------------------------------------------------------------
# Scan script
# ---------------------------------------------------------------------------

def ensure_market_offers_table() -> None:
    """Idempotent table creation — safe even if the migration already ran."""
    con = launch_ledger.init_db()
    try:
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS market_offers (
              offer_id      INTEGER PRIMARY KEY AUTOINCREMENT,
              scanned_at    TEXT NOT NULL,
              source        TEXT NOT NULL DEFAULT 'market_scan',
              profile_name  TEXT NOT NULL,
              profile_path  TEXT NOT NULL,
              market        TEXT NOT NULL,
              gpu_name             TEXT,
              num_gpus             INTEGER,
              gpu_total_ram_mb     REAL,
              dph_total            REAL,
              dph_base             REAL,
              storage_hour         REAL,
              compute_hour         REAL,
              reliability2         REAL,
              verification         TEXT,
              inet_down_mbps       REAL,
              disk_bw              REAL,
              geolocation          TEXT,
              machine_id           INTEGER,
              offer_vast_id        INTEGER,
              cuda_max_good        REAL,
              inet_down_cost_per_tb REAL,
              policy_max_dph_total          REAL,
              policy_min_reliability2       REAL,
              is_best INTEGER NOT NULL DEFAULT 1
            )
            """
        )
        for idx_name, cols in [
            ("idx_market_offers_time", "scanned_at"),
            ("idx_market_offers_profile_time", "profile_name, scanned_at"),
            ("idx_market_offers_gpu_time", "gpu_name, num_gpus, scanned_at"),
        ]:
            con.execute(f"CREATE INDEX IF NOT EXISTS {idx_name} ON market_offers({cols})")
        con.commit()
    finally:
        con.close()


def scan_profiles(
    profiles_dir: Path,
    *,
    skip_interruptible: bool,
    search_limit: int,
    verbose: bool,
) -> tuple[int, int]:
    """Scan all launch profiles and record best offers.

    Returns (recorded_rows, errors).
    """
    global _verbose_global
    _verbose_global = verbose

    vast = VastAI()
    profile_paths = sorted(profiles_dir.glob("*.json"))
    now = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    to_insert: list[dict[str, Any]] = []
    errors = 0

    for pp in profile_paths:
        if verbose:
            print(f"  {pp.name} ...", end="", flush=True)

        try:
            context = load_launch_context(pp)
        except Exception as exc:
            print(f"  ERROR loading {pp.name}: {exc}", file=sys.stderr)
            errors += 1
            continue

        market = context["launch"].get("market", "on-demand")
        if skip_interruptible and market in {"interruptible", "bid", "spot"}:
            if verbose:
                print(f" skip ({market})")
            continue

        offers = search_with_backoff(vast, context, search_limit=search_limit, profile_label=pp.name)

        if not offers:
            if verbose:
                print(" no passing offers")
            continue

        best = offers[0]
        launch = context["launch"]
        gpu = context["gpu"]
        sm = storage_metrics(best, context)
        dph_total = best.get("dph_total")
        total_vram_gb = (float(best.get("gpu_total_ram") or 0) * int(best.get("num_gpus") or 1)) / 1000.0
        dph_per_gbhr = dph_total / total_vram_gb if dph_total and total_vram_gb > 0 else None

        row = {
            "scanned_at": now,
            "source": "market_scan",
            "profile_name": launch.get("name", pp.stem),
            "profile_path": str(pp),
            "market": launch.get("market", "on-demand"),
            "gpu_name": best.get("gpu_name"),
            "num_gpus": best.get("num_gpus"),
            "gpu_total_ram_mb": best.get("gpu_total_ram"),
            "dph_total": dph_total,
            "dph_base": best.get("dph_base"),
            "dph_per_gbhr": dph_per_gbhr,
            "storage_hour": sm["storage_hour"] if math.isfinite(sm["storage_hour"]) else None,
            "compute_hour": sm["compute_hour"] if math.isfinite(sm["compute_hour"]) else None,
            "reliability2": best.get("reliability2"),
            "verification": best.get("verification"),
            "inet_down_mbps": best.get("inet_down"),
            "disk_bw": best.get("disk_bw") or best.get("disk_io"),
            "geolocation": best.get("geolocation"),
            "machine_id": best.get("machine_id"),
            "offer_vast_id": best.get("id"),
            "cuda_max_good": best.get("cuda_max_good"),
            "inet_down_cost_per_tb": best.get("internet_down_cost_per_tb"),
            "policy_max_dph_total": launch.get("pricing", {}).get("max_dph_total"),
            "policy_min_reliability2": launch.get("reliability", {}).get("min_reliability2"),
            "is_best": 1,
        }
        to_insert.append(row)

        if verbose:
            print(f" {money(dph_total)}/hr {best.get('gpu_name')} {best.get('num_gpus')}x id={best.get('id')}")

    if not to_insert:
        if verbose:
            print("No offers recorded this scan.")
        return (0, errors)

    # Batch insert
    con = launch_ledger.init_db()
    try:
        cols = list(to_insert[0].keys())
        placeholders = ", ".join([f":{c}" for c in cols])
        sql = f"INSERT INTO market_offers ({', '.join(cols)}) VALUES ({placeholders})"
        con.executemany(sql, to_insert)
        con.commit()
        if verbose:
            print(f"  -> recorded {len(to_insert)} rows")
    except Exception as exc:
        print(f"  ERROR inserting to market_offers: {exc}", file=sys.stderr)
        errors += 1
    finally:
        con.close()

    if errors:
        print(f"  ({errors} errors during scan)", file=sys.stderr)
    return (len(to_insert), errors)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Scan every launch profile, record best passing Vast offer to market_offers table."
    )
    parser.add_argument(
        "--profiles-dir",
        type=Path,
        default=Path("config/launch-profiles"),
        help="Directory containing launch profile JSON files (default: config/launch-profiles)",
    )
    parser.add_argument(
        "--skip-interruptible",
        action="store_true",
        help="Skip profiles with 'interruptible' in their filename",
    )
    parser.add_argument(
        "--minutes",
        type=float,
        default=0,
        help="Minutes between scans in self-loop mode (default: 1, 0 = single scan and exit)",
    )
    parser.add_argument(
        "--search-limit",
        type=int,
        default=5,
        help="Number of offers to request per search query (default: 5)",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Print per-profile progress",
    )
    args = parser.parse_args()

    ensure_market_offers_table()

    interval_seconds = args.minutes * 60
    first = True
    while True:
        if not first:
            next_ts = datetime.now(timezone.utc).timestamp() + interval_seconds
            print(f"next_scan_in={args.minutes:.0f}m at={datetime.fromtimestamp(next_ts, tz=timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')}", flush=True)
            time.sleep(interval_seconds)
        first = False

        count, errors = scan_profiles(
            args.profiles_dir,
            skip_interruptible=args.skip_interruptible,
            search_limit=args.search_limit,
            verbose=args.verbose,
        )

        ts = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
        print(f"scan_complete profiles={count} errors={errors} at={ts}", flush=True)

        if interval_seconds <= 0:
            break

    return 0


if __name__ == "__main__":
    raise SystemExit(main())