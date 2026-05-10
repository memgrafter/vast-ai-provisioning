#!/usr/bin/env python3
"""Launch one profiled Vast vLLM instance, test chat once, then destroy it."""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import statistics
import subprocess
import sys
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vastai import VastAI

from scripts.monitor_instance_readiness import analyze_logs, port_url
from scripts.select_and_launch import load_launch_context, search_policy_offers
from scripts.summarize_vllm_metrics import fetch_metrics, parse_metrics, print_gauge


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


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    vals = sorted(values)
    idx = min(len(vals) - 1, max(0, round((pct / 100.0) * (len(vals) - 1))))
    return vals[idx]


def run_quick_bench(base_url: str, api_key: str, model: str, seconds: float, concurrency: int, input_tokens: int, output_tokens: int) -> int:
    """Run a short external chat load test and print vLLM metrics delta."""
    chat_url = f"{base_url}/v1/chat/completions"
    metrics_url = f"{base_url}/metrics"
    prompt = " ".join(["benchmark"] * max(1, input_tokens))
    deadline = time.monotonic() + seconds
    latencies: list[float] = []
    statuses: list[int] = []
    errors = 0

    before = parse_metrics(fetch_metrics(metrics_url, api_key, 30))
    start = time.monotonic()

    def one_request() -> tuple[int, float]:
        t0 = time.monotonic()
        code, _ = api_post_json(
            chat_url,
            api_key,
            {
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": output_tokens,
                "temperature": 0,
            },
            timeout=max(30, int(seconds) + 30),
        )
        return code, time.monotonic() - t0

    with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures: set[concurrent.futures.Future[tuple[int, float]]] = set()
        while time.monotonic() < deadline or futures:
            while time.monotonic() < deadline and len(futures) < concurrency:
                futures.add(pool.submit(one_request))
            if not futures:
                break
            done, futures = concurrent.futures.wait(futures, timeout=0.2, return_when=concurrent.futures.FIRST_COMPLETED)
            for fut in done:
                try:
                    code, latency = fut.result()
                    statuses.append(code)
                    latencies.append(latency)
                    if code != 200:
                        errors += 1
                except Exception:
                    errors += 1

    elapsed = time.monotonic() - start
    after = parse_metrics(fetch_metrics(metrics_url, api_key, 30))
    ok = sum(1 for code in statuses if code == 200)
    print("Quick bench summary")
    print("===================")
    print(f"duration_s:      {elapsed:.2f}")
    print(f"concurrency:     {concurrency}")
    print(f"input_words:     {input_tokens}")
    print(f"max_output_tokens:{output_tokens}")
    print(f"requests_ok:     {ok}")
    print(f"requests_error:  {errors}")
    print(f"request_rps:     {ok / elapsed if elapsed > 0 else 0:.2f}")
    if latencies:
        print(f"latency_avg_s:   {statistics.mean(latencies):.2f}")
        print(f"latency_p50_s:   {percentile(latencies, 50):.2f}")
        print(f"latency_p95_s:   {percentile(latencies, 95):.2f}")
    print()
    print_gauge(before, after, elapsed)
    return 0 if ok > 0 and errors == 0 else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Launch, wait for chat readiness, send one chat, destroy")
    parser.add_argument("--launch-profile", type=Path, default=Path("config/launch-profiles/qwen3.5-9b-awq.interruptible.json"))
    parser.add_argument("--launch-attempts", type=int, default=3)
    parser.add_argument("--ready-timeout", type=int, default=1200)
    parser.add_argument("--interval", type=int, default=15)
    parser.add_argument("--tail", type=int, default=2500)
    parser.add_argument("--message", default="Say hello in one short sentence.")
    parser.add_argument("--bench-seconds", type=float, default=0, help="after readiness, run a quick load bench for this many seconds instead of one smoke chat")
    parser.add_argument("--bench-concurrency", type=int, default=4)
    parser.add_argument("--bench-input-tokens", type=int, default=512, help="approximate prompt words for quick bench")
    parser.add_argument("--bench-output-tokens", type=int, default=128)
    args = parser.parse_args()

    api_key = os.environ.get("VLLM_API_KEY")
    if not api_key:
        raise SystemExit("missing local VLLM_API_KEY for smoke chat request")

    context = load_launch_context(args.launch_profile)
    launch = context["launch"]
    model = context["model"]
    vast = VastAI()

    for attempt in range(1, args.launch_attempts + 1):
        print(f"=== launch attempt {attempt}/{args.launch_attempts}: {launch['name']} ===", flush=True)
        offers = search_policy_offers(vast, context)
        if not offers:
            print("no offers passed policy; retrying", flush=True)
            time.sleep(args.interval)
            continue
        offer = offers[0]
        print(f"launching offer={offer.get('id')} machine={offer.get('machine_id')} gpu={offer.get('gpu_name')}", flush=True)
        create_kwargs = {
            "id": int(offer["id"]),
            "disk": float(launch["storage"]["disk_gb"]),
            "template_hash": launch["template"]["hash_id"],
            "label": f"smoke-{launch['name']}-{model['served_model_name']}",
        }
        if launch.get("market") in {"interruptible", "bid", "spot"}:
            create_kwargs["price"] = float(launch["spot"]["max_bid_dph"])
        result = vast.create_instance(**create_kwargs)
        instance_id = result.get("new_contract") or result.get("id")
        print("create:", json.dumps(result, sort_keys=True, default=str), flush=True)
        if not instance_id:
            continue
        instance_id = int(instance_id)
        try:
            start = time.time()
            while time.time() - start < args.ready_timeout:
                info = vast.show_instance(id=instance_id)
                try:
                    logs = str(vast.logs(instance_id=instance_id, tail=str(args.tail)))
                    signals = analyze_logs(logs, launch.get("image", "vastai/vllm:v0.20.0-cuda-13.0"))
                except Exception as exc:
                    print(f"WARN log fetch failed; continuing readiness probes: {type(exc).__name__}: {exc}", flush=True)
                    logs = ""
                    signals = analyze_logs(logs, launch.get("image", "vastai/vllm:v0.20.0-cuda-13.0"))
                url = port_url(info)
                status = info.get("actual_status") or info.get("status")
                print(
                    f"probe instance={instance_id} status={status} url={url or '-'} "
                    f"sync={signals.r2_sync_finished} fail={signals.speed_test_failed or signals.provisioning_failed} "
                    f"vllm={signals.vllm_started or signals.api_ready}",
                    flush=True,
                )
                fatal_provisioning_failure = (
                    signals.speed_test_failed
                    or "All 3 attempts exhausted" in logs
                    or "missing AWS_ACCESS_KEY_ID" in logs
                    or "missing AWS_SECRET_ACCESS_KEY" in logs
                    or "ValidationError: 1 validation error for ModelConfig" in logs
                    or "Quantization method specified in the model config" in logs
                )
                if fatal_provisioning_failure:
                    print("fatal provisioning failure; destroying and retrying", flush=True)
                    break
                if signals.provisioning_failed:
                    print("provisioning attempt failed but provisioner may retry; continuing", flush=True)
                if url:
                    code, models = api_get_json(f"{url}/v1/models", api_key)
                    if code == 200:
                        chat_completions_url = f"{url}/v1/chat/completions"
                        print("models ok:", json.dumps(models, default=str)[:500], flush=True)
                        print(f"chat_completions_url={chat_completions_url}", flush=True)
                        print(f"model={model['served_model_name']}", flush=True)
                        if args.bench_seconds > 0:
                            return run_quick_bench(
                                url,
                                api_key,
                                model["served_model_name"],
                                args.bench_seconds,
                                args.bench_concurrency,
                                args.bench_input_tokens,
                                args.bench_output_tokens,
                            )
                        code, chat = api_post_json(
                            chat_completions_url,
                            api_key,
                            {
                                "model": model["served_model_name"],
                                "messages": [{"role": "user", "content": args.message}],
                                "max_tokens": 64,
                                "temperature": 0,
                            },
                        )
                        print(f"chat_http={code}")
                        print(json.dumps(chat, indent=2, default=str)[:2000])
                        return 0 if code == 200 else 1
                time.sleep(args.interval)
            print("ready timeout/failure; retrying", flush=True)
        finally:
            print(f"destroying instance {instance_id}", flush=True)
            try:
                print(json.dumps(vast.destroy_instance(id=instance_id), sort_keys=True, default=str), flush=True)
            except Exception as exc:
                print(f"WARN destroy failed: {exc}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
