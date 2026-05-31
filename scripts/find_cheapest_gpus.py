#!/usr/bin/env python3
"""Find the cheapest on-demand GPU offers with >= 24GB per GPU.

Supports any GPU count. Shows cheapest passing offer per GPU type
(pinned to 1x, 2x, etc.), split by verification status.
Use --verified-only to show only verified (hide unverified and deverified).
Use --sort-cost to sort all passing offers by cost (per GPU table is always sorted).
"""
from __future__ import annotations

import argparse
import math
from typing import Any

from vastai import VastAI


POLICY = {
    "min_cuda": 12.8,
    "min_reliability": 0.96,
    "min_inet_down": 128,
    "max_dph_total": 1.5,
    "max_storage_total_cost_per_hour": 0.03,
    "min_disk_bw": 200,
    "max_internet_down_cost_per_tb": 10.0,
    "max_internet_up_cost_per_tb": 10.0,
    "geo_exclude": ("CN",),
}


def money(value: Any) -> str:
    if not isinstance(value, (int, float)):
        return "n/a"
    return f"${float(value):.4f}"


def offer_passes(offer: dict[str, Any], verified_only: bool) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    ver = str(offer.get("verification") or "")
    if ver == "deverified":
        reasons.append("deverified")
    if verified_only and ver != "verified":
        reasons.append("unverified")

    checks = [
        (str(offer.get("rentable", "")) == "True" or offer.get("rentable") is True, "rentable"),
        (float(offer.get("cuda_max_good") or 0) >= POLICY["min_cuda"], "cuda"),
        (float(offer.get("reliability2") or 0) >= POLICY["min_reliability"], "rel"),
        (float(offer.get("dph_total") or math.inf) <= POLICY["max_dph_total"], "dph"),
        (float(offer.get("storage_total_cost") or math.inf) <= POLICY["max_storage_total_cost_per_hour"], "storage"),
        (float(offer.get("disk_bw") or offer.get("disk_io") or 0) >= POLICY["min_disk_bw"], "disk"),
        (float(offer.get("inet_down") or 0) >= POLICY["min_inet_down"], "inet"),
        (float(offer.get("internet_down_cost_per_tb") or 0) <= POLICY["max_internet_down_cost_per_tb"], "down_cost"),
        (float(offer.get("internet_up_cost_per_tb") or 0) <= POLICY["max_internet_up_cost_per_tb"], "up_cost"),
    ]
    loc = str(offer.get("geolocation") or "")
    geo_ok = not any(excl in loc for excl in POLICY["geo_exclude"])
    checks.append((geo_ok, "geo"))

    for ok, name in checks:
        if not ok:
            reasons.append(name)
    return not bool(reasons), reasons


def gpu_key(o: dict[str, Any]) -> str:
    """Unique key per GPU type + count, e.g. 'RTX 3090-2x'."""
    return f"{o.get('gpu_name', 'unknown')}-{int(o.get('num_gpus', 1))}x"


def total_vram(o: dict[str, Any]) -> float:
    return float(o.get("gpu_total_ram", 0)) * int(o.get("num_gpus", 1))


def show_table(offers: list[dict[str, Any]], verified_only: bool, label: str, sort_cost: bool = False) -> None:
    passing = [o for o in offers if offer_passes(o, verified_only)[0]]
    if not passing:
        return

    # Best per GPU type + count (cheapest)
    best_by_key: dict[str, dict[str, Any]] = {}
    for o in passing:
        key = gpu_key(o)
        dph = float(o.get("dph_total", 0))
        existing = best_by_key.get(key)
        if existing is None or dph < float(existing.get("dph_total", math.inf)):
            best_by_key[key] = o

    # Sort best per key by cost
    best_sorted = sorted(best_by_key.items(), key=lambda kv: float(kv[1].get("dph_total", 0)))

    print(f"\n=== {label} (cheapest per GPU type x count, sorted by cost) ===\n")
    print(f"{'GPU':30s} {'xNum':>4s} {'TotRAM':>8s} {'DPH':>10s} {'$/GBhr':>7s} {'Rel':>7s} {'Disk':>8s} {'Inet':>8s} {'Verif':>10s} {'Geo':20s}  Offer")
    print("-" * 125)
    for key, o in best_sorted:
        dph = float(o.get("dph_total", 0))
        n = int(o.get("num_gpus", 1))
        per_gpu = float(o.get("gpu_total_ram", 0))
        total = total_vram(o)
        dph_per_gb = dph / (total / 1000) if total > 0 else 0.0
        rel = float(o.get("reliability2", 0))
        disk = float(o.get("disk_bw", 0) or 0)
        inet = float(o.get("inet_down", 0) or 0)
        ver = str(o.get("verification", ""))
        loc = str(o.get("geolocation", ""))
        print(f"{o.get('gpu_name',''):30s} {n:>4d} {total:>8.0f}MB {money(dph):>10s} {dph_per_gb:>7.4f} {rel:>7.4f} {disk:>8.0f} {inet:>8.0f}Mbps {ver:>10s} {loc:20s} id={o.get('id')}")

    if sort_cost:
        passing.sort(key=lambda o: float(o.get("dph_total", 0)))
        print(f"\nAll {len(passing)} passing {label.lower()} ranked by cost (top 20):")
        print("-" * 125)
        for i, o in enumerate(passing[:20]):
            dph = float(o.get("dph_total", 0))
            n = int(o.get("num_gpus", 1))
            total = total_vram(o)
            dph_per_gb = dph / (total / 1000) if total > 0 else 0.0
            gpu = str(o.get("gpu_name", ""))
            rel = float(o.get("reliability2", 0))
            disk = float(o.get("disk_bw", 0) or 0)
            inet = float(o.get("inet_down", 0) or 0)
            ver = str(o.get("verification", ""))
            loc = str(o.get("geolocation", ""))
            print(f"  #{i+1:2d} {money(dph):>10s} {gpu:25s} {n}x {total:>6.0f}MB {dph_per_gb:>7.4f}/GBhr rel={rel:.4f} disk={disk:>6.0f} inet={inet:>5.0f} {ver:>10s} {loc:20s} id={o.get('id')}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Find cheapest on-demand 1x GPU offers >= 24GB VRAM")
    parser.add_argument("--verified-only", action="store_true", help="Show only verified offers; hide unverified and deverified")
    parser.add_argument("--sort-cost", action="store_true", help="Also show all passing offers ranked by cost under each table")
    args = parser.parse_args()

    vast = VastAI()

    # no_default=True to disable SDK's built-in verified filter
    all_offers = vast.search_offers(
        query="gpu_ram>23",
        type="on-demand",
        order="dph_total",
        limit=500,
        no_default=True,
    )

    print(f"Total on-demand >=24GB per-GPU offers found: {len(all_offers)}")
    print(f"Policy: rel>={POLICY['min_reliability']} cuda>={POLICY['min_cuda']} dph<={POLICY['max_dph_total']} disk>={POLICY['min_disk_bw']} inet>={POLICY['min_inet_down']} no-CN")
    print(f"Mode: {'verified only' if args.verified_only else 'all (excluding deverified)'}")

    verified = [o for o in all_offers if str(o.get("verification", "")) == "verified"]
    unverified = [o for o in all_offers if str(o.get("verification", "")) == "unverified"]
    deverified = [o for o in all_offers if str(o.get("verification", "")) == "deverified"]
    other = [o for o in all_offers if str(o.get("verification", "")) not in ("verified", "unverified", "deverified")]

    if args.verified_only:
        show_table(verified, verified_only=True, label="Verified", sort_cost=args.sort_cost)
    else:
        show_table(verified, verified_only=False, label="Verified", sort_cost=args.sort_cost)
        show_table(unverified, verified_only=False, label="Unverified", sort_cost=args.sort_cost)
        if deverified:
            print(f"\n(Skipped {len(deverified)} deverified offers)")
        if other:
            print(f"\n(Skipped {len(other)} offers with unknown verification)")

    # Merged view: verified + unverified (no deverified), sorted by cost
    merged = [o for o in verified + unverified if offer_passes(o, verified_only=args.verified_only)[0]]
    merged.sort(key=lambda o: float(o.get("dph_total", 0)))
    if merged:
        print(f"\n\n=== Merged Verified + Unverified (all {len(merged)} passing, sorted by cost) ===\n")
        print(f"{'GPU':30s} {'xNum':>4s} {'TotRAM':>8s} {'DPH':>10s} {'$/GBhr':>7s} {'Rel':>7s} {'Disk':>8s} {'Inet':>8s} {'Verif':>10s} {'Geo':20s}  Offer")
        print("-" * 125)
        for i, o in enumerate(merged[:30]):
            dph = float(o.get("dph_total", 0))
            n = int(o.get("num_gpus", 1))
            total = total_vram(o)
            dph_per_gb = dph / (total / 1000) if total > 0 else 0.0
            gpu = str(o.get("gpu_name", ""))
            rel = float(o.get("reliability2", 0))
            disk = float(o.get("disk_bw", 0) or 0)
            inet = float(o.get("inet_down", 0) or 0)
            ver = str(o.get("verification", ""))
            loc = str(o.get("geolocation", ""))
            print(f"  #{i+1:2d} {money(dph):>10s} {gpu:25s} {n}x {total:>6.0f}MB {dph_per_gb:>7.4f}/GBhr rel={rel:.4f} disk={disk:>6.0f} inet={inet:>5.0f} {ver:>10s} {loc:20s} id={o.get('id')}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())