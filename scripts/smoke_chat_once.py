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
import uuid
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vastai import VastAI

from scripts.monitor_instance_readiness import analyze_logs, port_url
from scripts.select_and_launch import load_launch_context, search_policy_offers
from scripts.summarize_vllm_metrics import Metrics, fetch_metrics, parse_metrics, print_gauge, print_summary


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


def coding_bench_prompt(approx_input_tokens: int) -> str:
    """Build a coding-shaped prompt with a nonce at the first token to avoid prefix-cache hits."""
    nonce = uuid.uuid4().hex
    task = f"""nonce-{nonce}
You are benchmarking a coding assistant. Do not mention the nonce.

Task: Review the Python module below and return a concise patch plan plus the final corrected implementation.
Focus on correctness, edge cases, and runtime complexity. The code is intentionally small but realistic.

```python
from collections import OrderedDict
import time

class TTLCache:
    def __init__(self, max_size=128, ttl_seconds=60):
        self.max_size = max_size
        self.ttl_seconds = ttl_seconds
        self.items = OrderedDict()

    def get(self, key):
        value, expires_at = self.items[key]
        if expires_at < time.time():
            del self.items[key]
            return None
        self.items.move_to_end(key)
        return value

    def set(self, key, value):
        expires_at = time.time() + self.ttl_seconds
        self.items[key] = (value, expires_at)
        self.items.move_to_end(key)
        if len(self.items) > self.max_size:
            self.items.popitem(last=False)

    def delete(self, key):
        del self.items[key]
```

Requirements:
- Missing keys should return None, not raise.
- Expired keys should be removed lazily.
- max_size <= 0 should reject construction.
- ttl_seconds <= 0 should reject construction.
- set() should update existing keys without double-counting capacity.
- delete() should be idempotent.
- Include a minimal unittest suite.
- Keep the implementation dependency-free.
"""
    filler = """
Additional context: The cache is used by a coding-agent service that stores parsed file snippets, AST summaries, and recent benchmark observations. The service has many short-lived requests, and predictable behavior matters more than cleverness. Avoid global mutable state, avoid background threads, and keep operations amortized O(1). Explain any tradeoffs briefly.
""".strip()
    # Roughly size by whitespace tokens. This is intentionally approximate; the
    # tokenizer-specific prompt count is captured from vLLM metrics after the run.
    while len(task.split()) < approx_input_tokens:
        task += "\n\n" + filler
    return task


def metrics_delta(before: Metrics, after: Metrics, elapsed_s: float) -> dict[str, float]:
    prompt_delta = after.get("vllm:prompt_tokens_total") - before.get("vllm:prompt_tokens_total")
    generation_delta = after.get("vllm:generation_tokens_total") - before.get("vllm:generation_tokens_total")
    total_delta = prompt_delta + generation_delta
    completed = sum(
        after.label_value("vllm:request_success_total", finished_reason=reason)
        - before.label_value("vllm:request_success_total", finished_reason=reason)
        for reason in ("stop", "length", "error", "abort", "repetition")
    )
    ttft_count = after.get("vllm:time_to_first_token_seconds_count") - before.get("vllm:time_to_first_token_seconds_count")
    ttft_sum = after.get("vllm:time_to_first_token_seconds_sum") - before.get("vllm:time_to_first_token_seconds_sum")
    queue_count = after.get("vllm:request_queue_time_seconds_count") - before.get("vllm:request_queue_time_seconds_count")
    queue_sum = after.get("vllm:request_queue_time_seconds_sum") - before.get("vllm:request_queue_time_seconds_sum")
    infer_count = after.get("vllm:request_inference_time_seconds_count") - before.get("vllm:request_inference_time_seconds_count")
    infer_sum = after.get("vllm:request_inference_time_seconds_sum") - before.get("vllm:request_inference_time_seconds_sum")
    return {
        "elapsed_s": elapsed_s,
        "vllm_completed_requests": completed,
        "vllm_prompt_tokens": prompt_delta,
        "vllm_generation_tokens": generation_delta,
        "vllm_total_tokens": total_delta,
        "vllm_prompt_tps": prompt_delta / elapsed_s if elapsed_s > 0 else 0.0,
        "vllm_generation_tps": generation_delta / elapsed_s if elapsed_s > 0 else 0.0,
        "vllm_total_tps": total_delta / elapsed_s if elapsed_s > 0 else 0.0,
        "vllm_avg_ttft_s": ttft_sum / ttft_count if ttft_count > 0 else 0.0,
        "vllm_avg_queue_s": queue_sum / queue_count if queue_count > 0 else 0.0,
        "vllm_avg_inference_s": infer_sum / infer_count if infer_count > 0 else 0.0,
        "vllm_kv_cache_usage": after.get("vllm:kv_cache_usage_perc"),
    }


def run_quick_bench(base_url: str, api_key: str, model: str, seconds: float, concurrency: int, input_tokens: int, output_tokens: int) -> int:
    """Run a short external coding-shaped chat load test and print vLLM metrics delta."""
    chat_url = f"{base_url}/v1/chat/completions"
    metrics_url = f"{base_url}/metrics"
    deadline = time.monotonic() + seconds
    latencies: list[float] = []
    statuses: list[int] = []
    sample_errors: list[str] = []
    prompt_usage = 0
    completion_usage = 0
    total_usage = 0
    errors = 0

    before = parse_metrics(fetch_metrics(metrics_url, api_key, 30))
    start = time.monotonic()

    def one_request() -> tuple[int, float, int, int, int, str]:
        payload: dict[str, Any] = {
            "model": model,
            "messages": [{"role": "user", "content": coding_bench_prompt(input_tokens)}],
            "temperature": 0,
        }
        if output_tokens > 0:
            payload["max_tokens"] = output_tokens
        t0 = time.monotonic()
        code, body = api_post_json(chat_url, api_key, payload, timeout=max(60, int(seconds) + 120))
        latency = time.monotonic() - t0
        usage = body.get("usage", {}) if isinstance(body, dict) else {}
        error_text = ""
        if code != 200:
            error_text = body if isinstance(body, str) else json.dumps(body, default=str)
        return (
            code,
            latency,
            int(usage.get("prompt_tokens") or 0),
            int(usage.get("completion_tokens") or 0),
            int(usage.get("total_tokens") or 0),
            error_text[:1000],
        )

    with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures: set[concurrent.futures.Future[tuple[int, float, int, int, int, str]]] = set()
        while time.monotonic() < deadline or futures:
            while time.monotonic() < deadline and len(futures) < concurrency:
                futures.add(pool.submit(one_request))
            if not futures:
                break
            done, futures = concurrent.futures.wait(futures, timeout=0.2, return_when=concurrent.futures.FIRST_COMPLETED)
            for fut in done:
                try:
                    code, latency, prompt_tokens, completion_tokens, request_total_tokens, error_text = fut.result()
                    statuses.append(code)
                    latencies.append(latency)
                    prompt_usage += prompt_tokens
                    completion_usage += completion_tokens
                    total_usage += request_total_tokens
                    if code != 200:
                        errors += 1
                        if error_text and len(sample_errors) < 3:
                            sample_errors.append(f"HTTP {code}: {error_text}")
                except Exception:
                    errors += 1

    elapsed = time.monotonic() - start
    after = parse_metrics(fetch_metrics(metrics_url, api_key, 30))
    ok = sum(1 for code in statuses if code == 200)
    print("Quick coding bench summary")
    print("==========================")
    print(f"duration_s:        {elapsed:.2f}")
    print(f"target_seconds:    {seconds:.2f}")
    print(f"concurrency:       {concurrency}")
    print(f"prompt_words_goal: {input_tokens}")
    print(f"max_output_tokens: {'model default' if output_tokens <= 0 else output_tokens}")
    print(f"requests_ok:       {ok}")
    print(f"requests_error:    {errors}")
    print(f"request_rps:       {ok / elapsed if elapsed > 0 else 0:.2f}")
    print(f"client_prompt_tokens:     {prompt_usage}")
    print(f"client_completion_tokens: {completion_usage}")
    print(f"client_total_tokens:      {total_usage}")
    if latencies:
        print(f"latency_avg_s:     {statistics.mean(latencies):.2f}")
        print(f"latency_p50_s:     {percentile(latencies, 50):.2f}")
        print(f"latency_p95_s:     {percentile(latencies, 95):.2f}")
    if sample_errors:
        print("sample_errors:")
        for err in sample_errors:
            print(err)
    print()
    delta = metrics_delta(before, after, elapsed)
    print("Bench metrics JSON")
    print("==================")
    print(json.dumps(delta, indent=2, sort_keys=True))
    print()
    print_gauge(before, after, elapsed)
    print()
    print("Post-bench metrics summary")
    print("==========================")
    print_summary(after)
    return 0 if ok > 0 and errors == 0 else 1


def save_instance_debug(vast: VastAI, instance_id: int, suffix: str = "final", tail: int = 5000) -> None:
    out = Path("instances")
    out.mkdir(exist_ok=True)
    try:
        info = vast.show_instance(id=instance_id)
        out.joinpath(f"{instance_id}.{suffix}.json").write_text(json.dumps(info, indent=2, sort_keys=True, default=str) + "\n")
    except Exception as exc:
        out.joinpath(f"{instance_id}.{suffix}.show_instance.error.txt").write_text(f"{type(exc).__name__}: {exc}\n")
    try:
        logs = str(vast.logs(instance_id=instance_id, tail=str(tail)))
        out.joinpath(f"{instance_id}.{suffix}.logs.tail{tail}.txt").write_text(logs + "\n")
    except Exception as exc:
        out.joinpath(f"{instance_id}.{suffix}.logs.error.txt").write_text(f"{type(exc).__name__}: {exc}\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Launch, wait for chat readiness, send one chat, destroy")
    parser.add_argument("--launch-profile", type=Path, default=Path("config/launch-profiles/qwen3.5-9b-awq.interruptible.json"))
    parser.add_argument("--launch-attempts", type=int, default=3)
    parser.add_argument("--ready-timeout", type=int, default=1200)
    parser.add_argument("--interval", type=int, default=15)
    parser.add_argument("--tail", type=int, default=2500)
    parser.add_argument("--message", default="Say hello in one short sentence.")
    parser.add_argument(
        "--bench-seconds",
        type=float,
        nargs="?",
        const=90.0,
        default=0,
        help="after readiness, run a quick load bench instead of one smoke chat; pass without a value for the 90s default",
    )
    parser.add_argument("--bench-concurrency", type=int, default=48, help="coding bench concurrency; sized to load H100-class GPUs without cache-prefix testing")
    parser.add_argument("--bench-input-tokens", type=int, default=6000, help="approximate prompt words for coding bench")
    parser.add_argument("--bench-output-tokens", type=int, default=0, help="max generated tokens for bench; <=0 omits max_tokens and uses model default")
    parser.add_argument("--no-destroy-on-error", action="store_true", help="leave the instance running when readiness, smoke, or bench fails")
    parser.add_argument("--final-log-tail", type=int, default=5000, help="Vast log lines to save before any destroy/leave-running closeout")
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
        destroy_instance = True
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
                    if args.no_destroy_on_error:
                        destroy_instance = False
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
                            bench_code = run_quick_bench(
                                url,
                                api_key,
                                model["served_model_name"],
                                args.bench_seconds,
                                args.bench_concurrency,
                                args.bench_input_tokens,
                                args.bench_output_tokens,
                            )
                            if bench_code != 0 and args.no_destroy_on_error:
                                destroy_instance = False
                            return bench_code
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
                        smoke_code = 0 if code == 200 else 1
                        if smoke_code != 0 and args.no_destroy_on_error:
                            destroy_instance = False
                        return smoke_code
                time.sleep(args.interval)
            print("ready timeout/failure; retrying", flush=True)
            if args.no_destroy_on_error:
                destroy_instance = False
        except Exception:
            if args.no_destroy_on_error:
                destroy_instance = False
            raise
        finally:
            print(f"saving final instance debug for {instance_id}", flush=True)
            save_instance_debug(vast, instance_id, tail=args.final_log_tail)
            if destroy_instance:
                print(f"destroying instance {instance_id}", flush=True)
                try:
                    print(json.dumps(vast.destroy_instance(id=instance_id), sort_keys=True, default=str), flush=True)
                except Exception as exc:
                    print(f"WARN destroy failed: {exc}", file=sys.stderr)
            else:
                print(f"leaving instance {instance_id} running due to --no-destroy-on-error", flush=True)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
