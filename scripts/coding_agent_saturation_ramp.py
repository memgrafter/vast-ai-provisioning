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
class PrefixBucket:
    name: str
    weight: int
    user_prefix_tokens: int
    max_tokens: int | None


@dataclass(frozen=True)
class SimUser:
    user_id: int
    bucket: PrefixBucket
    stable_prefix: str


# Simulated-user session buckets. Each user gets a stable prefix and submits
# multiple serial turns against it. This is meant to reveal prefix/KV cache
# behavior as many distinct user prefixes become resident. Output is not capped
# per request; the server/model profile generation config owns the limit.
BUCKETS = [
    PrefixBucket("user_prefix_5k", 10, 5_000, None),
    PrefixBucket("user_prefix_30k", 30, 30_000, None),
    PrefixBucket("user_prefix_60k", 30, 60_000, None),
    PrefixBucket("user_prefix_90k", 30, 90_000, None),
]

GLOBAL_PREFIX_TOKENS = 100
TURN_UNIQUE_TOKENS = 256


def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    values = sorted(values)
    idx = min(len(values) - 1, max(0, int(round((p / 100) * (len(values) - 1)))))
    return values[idx]


def make_user(user_id: int, bucket: PrefixBucket) -> SimUser:
    # Repeated "TOK " is close to one token per repeat for this Qwen tokenizer path.
    # Put user identity before the long body: exact-prefix matching cannot cross the
    # differing header, so users do not share each other's long prefix, while the
    # body stays token-efficient enough to fit 90k-class prompts under 160k.
    stable_prefix = (
        f"Stable synthetic repository/session prefix for unique simulated user {user_id} bucket {bucket.name}.\n"
        + ("TOK " * max(1, bucket.user_prefix_tokens))
    )
    return SimUser(user_id=user_id, bucket=bucket, stable_prefix=stable_prefix)


def make_prompt(user: SimUser, turn: int) -> str:
    # Global prefix first, then user-stable prefix, then turn-unique tail. This
    # lets vLLM reuse a tiny global prefix across everyone and a large stable
    # prefix across serial turns for the same simulated user.
    return (
        "You are acting as a coding agent. Inspect the synthetic repository context, then provide a concise implementation plan.\n"
        + ("TOK " * GLOBAL_PREFIX_TOKENS)
        + "\n\n"
        + user.stable_prefix
        + "\n\nCurrent turn:\n"
        f"user_id={user.user_id} turn={turn}\n"
        + ("TOK " * TURN_UNIQUE_TOKENS)
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


def token_count(base_url: str, model: str, api_key: str, prompt: str, timeout: int) -> int:
    payload = {"model": model, "prompt": prompt}
    req = urllib.request.Request(
        base_url.rstrip("/") + "/tokenize",
        data=json.dumps(payload).encode(),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        body = json.loads(response.read().decode())
    return int(body.get("count") or len(body.get("tokens") or []))


def one_request(base_url: str, model: str, api_key: str, user: SimUser, turn: int, timeout: int) -> dict[str, Any]:
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": make_prompt(user, turn)}],
        "temperature": 0,
    }
    if user.bucket.max_tokens is not None:
        payload["max_tokens"] = user.bucket.max_tokens
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
            "bucket": user.bucket.name,
            "user_id": user.user_id,
            "turn": turn,
            "elapsed": elapsed,
            "prompt_tokens": int(usage.get("prompt_tokens") or 0),
            "completion_tokens": int(usage.get("completion_tokens") or 0),
            "finish_reason": choice.get("finish_reason"),
        }
    except urllib.error.HTTPError as exc:
        return {"ok": False, "bucket": user.bucket.name, "user_id": user.user_id, "turn": turn, "elapsed": time.monotonic() - started, "error": f"HTTP {exc.code}"}
    except Exception as exc:
        return {"ok": False, "bucket": user.bucket.name, "user_id": user.user_id, "turn": turn, "elapsed": time.monotonic() - started, "error": type(exc).__name__}


def run_step(base_url: str, model: str, api_key: str, concurrency: int, turns_per_user: int, timeout: int) -> None:
    weighted = [bucket for bucket in BUCKETS for _ in range(bucket.weight)]
    users = [make_user(user_id, random.choice(weighted)) for user_id in range(1, concurrency + 1)]
    requests = concurrency * turns_per_user
    submitted = 0
    skipped_followup_turns = 0
    results: list[dict[str, Any]] = []
    started = time.monotonic()
    last_progress = started

    def submit_turn(pool: futures.ThreadPoolExecutor, user: SimUser, turn: int) -> futures.Future[dict[str, Any]]:
        nonlocal submitted
        submitted += 1
        return pool.submit(one_request, base_url, model, api_key, user, turn, timeout)

    def print_progress(pending_count: int) -> None:
        ok_count = sum(1 for r in results if r.get("ok"))
        error_count = len(results) - ok_count
        print(
            "  progress "
            f"planned={requests} submitted={submitted} completed={len(results)} "
            f"ok={ok_count} errors={error_count} in_flight={pending_count} "
            f"skipped_followup_turns={skipped_followup_turns}"
        )

    with MetricsSampler(base_url, api_key) as sampler:
        with futures.ThreadPoolExecutor(max_workers=concurrency) as pool:
            pending: set[futures.Future[dict[str, Any]]] = {submit_turn(pool, user, 1) for user in users}
            print_progress(len(pending))
            while pending:
                done, pending = futures.wait(pending, timeout=5, return_when=futures.FIRST_COMPLETED)
                now = time.monotonic()
                if not done:
                    if now - last_progress >= 30:
                        print_progress(len(pending))
                        last_progress = now
                    continue
                for fut in done:
                    result = fut.result()
                    results.append(result)
                    turn = int(result.get("turn") or 0)
                    if result.get("ok") and turn < turns_per_user:
                        user = users[int(result["user_id"]) - 1]
                        pending.add(submit_turn(pool, user, turn + 1))
                    elif not result.get("ok"):
                        skipped_followup_turns += max(0, turns_per_user - turn)
                if now - last_progress >= 30 or len(results) == requests:
                    print_progress(len(pending))
                    last_progress = now

    wall = time.monotonic() - started
    server = sampler.report(wall)
    ok = [r for r in results if r.get("ok")]
    bad = [r for r in results if not r.get("ok")]
    latencies = [float(r["elapsed"]) for r in ok]
    prompt_tokens = sum(int(r.get("prompt_tokens") or 0) for r in ok)
    completion_tokens = sum(int(r.get("completion_tokens") or 0) for r in ok)

    print(f"concurrency={concurrency} simulated_users={concurrency} planned_requests={requests} submitted_requests={submitted} completed_results={len(results)} skipped_followup_turns={skipped_followup_turns} wall_s={wall:.1f}")
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
    parser.add_argument("--concurrency", default="16,32,48,64", help="Comma-separated concurrency steps")
    parser.add_argument("--requests-per-concurrency", type=int, default=3, help="Serial turns per simulated user")
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument("--step-gap", type=float, default=10.0, help="Seconds to sleep between concurrency steps")
    parser.add_argument("--pause", action="store_true", help="Pause for Enter between concurrency steps, after --step-gap")
    args = parser.parse_args()

    api_key = os.environ.get("OPENAI_API_KEY") or os.environ.get("VLLM_API_KEY")
    if not api_key:
        raise SystemExit("set OPENAI_API_KEY or source env.vast-management so VLLM_API_KEY is set")
    if args.base_url.rstrip("/").endswith("/v1"):
        raise SystemExit("--base-url should be the server root, e.g. http://host:port, not .../v1")

    avg_user_prefix = sum(bucket.weight * bucket.user_prefix_tokens for bucket in BUCKETS) / sum(bucket.weight for bucket in BUCKETS)
    theoretical_cache_share = max(0, args.requests_per_concurrency - 1) / args.requests_per_concurrency
    print("Buckets:")
    print(f"  global_prefix≈{GLOBAL_PREFIX_TOKENS} tokens; turn_unique_tail≈{TURN_UNIQUE_TOKENS} tokens; output cap=server default")
    print(f"  requests_per_simulated_user={args.requests_per_concurrency}; theoretical_warm_prefix_share≈{theoretical_cache_share:.0%}")
    print(f"  weighted_avg_user_prefix≈{avg_user_prefix:.0f} tokens")
    for bucket in BUCKETS:
        max_out = "server_default" if bucket.max_tokens is None else str(bucket.max_tokens)
        print(f"  {bucket.name}: weight={bucket.weight}% user_prefix≈{bucket.user_prefix_tokens} max_out={max_out}")
    print("Preflight token counts:")
    for bucket in BUCKETS:
        user = make_user(1, bucket)
        count = token_count(args.base_url, args.model, api_key, make_prompt(user, 1), args.timeout)
        print(f"  {bucket.name}: configured_user_prefix={bucket.user_prefix_tokens} actual_prompt_tokens={count}")
        if count >= 160_000:
            raise SystemExit(f"preflight failed: {bucket.name} prompt has {count} tokens, >= 160000 max_model_len")
    print()

    for concurrency in [int(x) for x in args.concurrency.split(",") if x.strip()]:
        total_requests = concurrency * args.requests_per_concurrency
        estimated_prefix_footprint = concurrency * avg_user_prefix
        print("=" * 72)
        print(
            "Starting step: "
            f"simulated_users={concurrency} "
            f"turns_per_user={args.requests_per_concurrency} "
            f"total_requests={total_requests} "
            f"estimated_user_prefix_footprint≈{estimated_prefix_footprint:.0f} "
            f"global_prefix≈{GLOBAL_PREFIX_TOKENS} "
            f"turn_unique_tail≈{TURN_UNIQUE_TOKENS} "
            "user_prefix_distribution="
            + ",".join(f"{bucket.name}:{bucket.weight}%/{bucket.user_prefix_tokens}" for bucket in BUCKETS)
        )
        run_step(args.base_url, args.model, api_key, concurrency, args.requests_per_concurrency, args.timeout)
        if args.step_gap > 0:
            print(f"Sleeping {args.step_gap:.1f}s before next step...")
            time.sleep(args.step_gap)
        if args.pause:
            print("Press Enter for next step, Ctrl-C to stop.")
            input()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
