#!/usr/bin/env python3
"""Simple coding-agent-shaped saturation ramp for an OpenAI-compatible vLLM server.

Usage:
    . env.vast-management
    scripts/coding_agent_saturation_ramp.py \
      --base-url http://194.26.196.169:15377 \
      --model qwen3.6-35b-a3b-awq-coding-budget-160k

Watch server-side metrics separately, e.g.:
    ./run.sh scripts/summarize_vllm_metrics.py --base-url http://194.26.196.169:15377/v1 --interval 10
"""

from __future__ import annotations

import argparse
import concurrent.futures as futures
import json
import os
import random
import statistics
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Bucket:
    name: str
    weight: int
    input_tokens: int
    max_tokens: int | None


# Rough coding-agent-ish mix: many normal turns, some long-context turns.
# Prompt bodies are ~90% shared prefix and ~10% unique suffix to exercise
# prefix-cache-heavy coding sessions. Output is not capped per request; the
# server/model profile generation config owns the default limit.
BUCKETS = [
    Bucket("small_edit", 45, 2_000, None),
    Bucket("medium_task", 30, 8_000, None),
    Bucket("large_context", 20, 32_000, None),
    Bucket("huge_context", 5, 80_000, None),
]

CACHEABLE_PREFIX_RATIO = 0.90


def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    values = sorted(values)
    idx = min(len(values) - 1, max(0, int(round((p / 100) * (len(values) - 1)))))
    return values[idx]


def make_prompt(bucket: Bucket, request_id: int) -> str:
    # Repeated "tok " is approximately one token per repeat for this Qwen tokenizer path.
    # Shared prefix comes first so vLLM prefix caching can reuse it across requests.
    overhead_budget = 96
    filler_count = max(1, bucket.input_tokens - overhead_budget)
    shared_count = int(filler_count * CACHEABLE_PREFIX_RATIO)
    unique_count = max(1, filler_count - shared_count)
    return (
        "You are acting as a coding agent. Inspect the synthetic repository context, then provide a concise implementation plan.\n"
        f"Shared cacheable context bucket: {bucket.name}\n\n"
        + ("tok " * shared_count)
        + "\n\nUnique request tail:\n"
        f"Request id: {request_id}\n"
        + ("uniq " * unique_count)
        + "\n\nReturn a concise answer."
    )


def metric_value(text: str, name: str, labels: str = "") -> float:
    prefix = name + ("{" if labels else "")
    for line in text.splitlines():
        if not line.startswith(prefix):
            continue
        if labels and labels not in line:
            continue
        try:
            return float(line.rsplit(None, 1)[1])
        except (IndexError, ValueError):
            return 0.0
    return 0.0


class MetricsSampler:
    def __init__(self, base_url: str, api_key: str, interval: float = 2.0) -> None:
        self.url = base_url.rstrip("/") + "/metrics"
        self.api_key = api_key
        self.interval = interval
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.samples: list[dict[str, float]] = []
        self.before: dict[str, float] = {}
        self.after: dict[str, float] = {}

    def scrape(self) -> dict[str, float]:
        req = urllib.request.Request(self.url, headers={"Authorization": f"Bearer {self.api_key}"})
        with urllib.request.urlopen(req, timeout=10) as response:
            text = response.read().decode(errors="replace")
        return {
            "running": metric_value(text, "vllm:num_requests_running"),
            "waiting": metric_value(text, "vllm:num_requests_waiting"),
            "kv": metric_value(text, "vllm:kv_cache_usage_perc"),
            "queue_sum": metric_value(text, "vllm:request_queue_time_seconds_sum"),
            "queue_count": metric_value(text, "vllm:request_queue_time_seconds_count"),
            "ttft_sum": metric_value(text, "vllm:time_to_first_token_seconds_sum"),
            "ttft_count": metric_value(text, "vllm:time_to_first_token_seconds_count"),
            "prompt_total": metric_value(text, "vllm:prompt_tokens_total"),
            "prompt_compute": metric_value(text, "vllm:prompt_tokens_by_source_total", 'source="local_compute"'),
            "prompt_cache": metric_value(text, "vllm:prompt_tokens_by_source_total", 'source="local_cache_hit"'),
            "generation": metric_value(text, "vllm:generation_tokens_total"),
        }

    def _run(self) -> None:
        while not self.stop.is_set():
            try:
                self.samples.append(self.scrape())
            except Exception:
                pass
            self.stop.wait(self.interval)

    def __enter__(self) -> "MetricsSampler":
        try:
            self.before = self.scrape()
        except Exception:
            self.before = {}
        self.thread.start()
        return self

    def __exit__(self, *_: object) -> None:
        self.stop.set()
        self.thread.join(timeout=3)
        try:
            self.after = self.scrape()
        except Exception:
            self.after = self.samples[-1] if self.samples else {}

    def report(self, wall: float) -> dict[str, float]:
        samples = self.samples or ([self.after] if self.after else [])
        delta = lambda k: self.after.get(k, 0.0) - self.before.get(k, 0.0)
        queue_count = delta("queue_count")
        ttft_count = delta("ttft_count")
        return {
            "max_running": max((s.get("running", 0.0) for s in samples), default=0.0),
            "max_waiting": max((s.get("waiting", 0.0) for s in samples), default=0.0),
            "max_kv_pct": 100 * max((s.get("kv", 0.0) for s in samples), default=0.0),
            "server_prompt_total_tps": delta("prompt_total") / wall if wall else 0.0,
            "server_prompt_compute_tps": delta("prompt_compute") / wall if wall else 0.0,
            "server_prompt_cache_tps": delta("prompt_cache") / wall if wall else 0.0,
            "server_generation_tps": delta("generation") / wall if wall else 0.0,
            "server_queue_avg_s": delta("queue_sum") / queue_count if queue_count else 0.0,
            "server_queue_count": queue_count,
            "server_ttft_avg_s": delta("ttft_sum") / ttft_count if ttft_count else 0.0,
            "server_ttft_count": ttft_count,
        }


def one_request(base_url: str, model: str, api_key: str, bucket: Bucket, request_id: int, timeout: int) -> dict[str, Any]:
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": make_prompt(bucket, request_id)}],
        "temperature": 0,
    }
    if bucket.max_tokens is not None:
        payload["max_tokens"] = bucket.max_tokens
    req = urllib.request.Request(
        base_url.rstrip("/") + "/v1/chat/completions",
        data=json.dumps(payload).encode(),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
    )
    started = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            body = json.loads(response.read().decode())
        elapsed = time.monotonic() - started
        usage = body.get("usage") or {}
        choice = (body.get("choices") or [{}])[0]
        return {
            "ok": True,
            "bucket": bucket.name,
            "elapsed": elapsed,
            "prompt_tokens": int(usage.get("prompt_tokens") or 0),
            "completion_tokens": int(usage.get("completion_tokens") or 0),
            "finish_reason": choice.get("finish_reason"),
        }
    except urllib.error.HTTPError as exc:
        return {"ok": False, "bucket": bucket.name, "elapsed": time.monotonic() - started, "error": f"HTTP {exc.code}"}
    except Exception as exc:
        return {"ok": False, "bucket": bucket.name, "elapsed": time.monotonic() - started, "error": type(exc).__name__}


def run_step(base_url: str, model: str, api_key: str, concurrency: int, requests: int, timeout: int) -> None:
    if requests < concurrency:
        raise ValueError(f"requests ({requests}) must be >= concurrency ({concurrency})")
    weighted = [bucket for bucket in BUCKETS for _ in range(bucket.weight)]
    submitted = 0
    results: list[dict[str, Any]] = []
    started = time.monotonic()

    with MetricsSampler(base_url, api_key) as sampler:
        with futures.ThreadPoolExecutor(max_workers=concurrency) as pool:
            pending: set[futures.Future[dict[str, Any]]] = set()
            while submitted < requests or pending:
                while submitted < requests and len(pending) < concurrency:
                    submitted += 1
                    bucket = random.choice(weighted)
                    pending.add(pool.submit(one_request, base_url, model, api_key, bucket, submitted, timeout))
                done, pending = futures.wait(pending, return_when=futures.FIRST_COMPLETED)
                for fut in done:
                    results.append(fut.result())

    wall = time.monotonic() - started
    server = sampler.report(wall)
    ok = [r for r in results if r.get("ok")]
    bad = [r for r in results if not r.get("ok")]
    latencies = [float(r["elapsed"]) for r in ok]
    prompt_tokens = sum(int(r.get("prompt_tokens") or 0) for r in ok)
    completion_tokens = sum(int(r.get("completion_tokens") or 0) for r in ok)

    print(f"concurrency={concurrency} simulated_users={concurrency} requests={requests} wall_s={wall:.1f}")
    print(f"  ok={len(ok)} errors={len(bad)} rps={len(ok) / wall:.2f}")
    print(f"  client_prompt_tps={prompt_tokens / wall:.2f} client_generation_tps={completion_tokens / wall:.2f} client_total_tps={(prompt_tokens + completion_tokens) / wall:.2f}")
    print(f"  latency_s avg={statistics.mean(latencies) if latencies else 0:.2f} p50={percentile(latencies, 50):.2f} p95={percentile(latencies, 95):.2f} max={max(latencies) if latencies else 0:.2f}")
    print(
        "  server "
        f"max_running={server['max_running']:.0f} max_waiting={server['max_waiting']:.0f} max_kv={server['max_kv_pct']:.1f}% "
        f"queue_avg_s={server['server_queue_avg_s']:.2f} ttft_avg_s={server['server_ttft_avg_s']:.2f}"
    )
    print(
        "  server_tps "
        f"prompt_total={server['server_prompt_total_tps']:.2f} "
        f"prompt_compute={server['server_prompt_compute_tps']:.2f} "
        f"prompt_cache={server['server_prompt_cache_tps']:.2f} "
        f"generation={server['server_generation_tps']:.2f}"
    )
    for bucket in BUCKETS:
        count = sum(1 for r in ok if r.get("bucket") == bucket.name)
        if count:
            print(f"  bucket {bucket.name}: {count}")
    if bad:
        errors: dict[str, int] = {}
        for r in bad:
            errors[str(r.get("error"))] = errors.get(str(r.get("error")), 0) + 1
        print(f"  errors_by_type={errors}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Coding-agent-shaped saturation ramp")
    parser.add_argument("--base-url", required=True, help="Server root, e.g. http://host:port, not /v1")
    parser.add_argument("--model", required=True)
    parser.add_argument("--concurrency", default="96,128,160", help="Comma-separated concurrency steps")
    parser.add_argument("--min-requests-per-step", type=int, default=120, help="Minimum requests to run at each concurrency step")
    parser.add_argument("--requests-per-concurrency", type=int, default=3, help="Requests per simulated user; requests per step = max(min requests, concurrency * this value)")
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument("--pause", action="store_true", help="Pause for Enter between concurrency steps")
    args = parser.parse_args()

    api_key = os.environ.get("OPENAI_API_KEY") or os.environ.get("VLLM_API_KEY")
    if not api_key:
        raise SystemExit("set OPENAI_API_KEY or source env.vast-management so VLLM_API_KEY is set")
    if args.base_url.rstrip("/").endswith("/v1"):
        raise SystemExit("--base-url should be the server root, e.g. http://host:port, not .../v1")

    print("Buckets:")
    print(f"  cacheable_prefix_ratio≈{CACHEABLE_PREFIX_RATIO:.0%}; output cap=server default")
    for bucket in BUCKETS:
        max_out = "server_default" if bucket.max_tokens is None else str(bucket.max_tokens)
        print(f"  {bucket.name}: weight={bucket.weight} input≈{bucket.input_tokens} max_out={max_out}")
    print()

    for concurrency in [int(x) for x in args.concurrency.split(",") if x.strip()]:
        requests = max(args.min_requests_per_step, concurrency * args.requests_per_concurrency)
        print("=" * 72)
        run_step(args.base_url, args.model, api_key, concurrency, requests, args.timeout)
        if args.pause:
            print("Press Enter for next step, Ctrl-C to stop.")
            input()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
