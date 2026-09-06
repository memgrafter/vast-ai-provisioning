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
import sys
import threading
import time
import urllib.error
import urllib.request
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import launch_ledger


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


def make_user(user_id: int, bucket: PrefixBucket, shared_prefix: bool = False) -> SimUser:
    # Repeated "TOK " is close to one token per repeat for this Qwen tokenizer path.
    # Default mode puts user identity before the long body: exact-prefix matching
    # cannot cross the differing header, so users do not share each other's long
    # prefix. TPS mode can intentionally share this stable prefix across users;
    # keep that mode out of KV-store residency tests.
    identity = "shared TPS prefix" if shared_prefix else f"unique simulated user {user_id}"
    stable_prefix = (
        f"Stable synthetic repository/session prefix for {identity} bucket {bucket.name}.\n"
        + ("TOK " * max(1, bucket.user_prefix_tokens))
    )
    return SimUser(user_id=user_id, bucket=bucket, stable_prefix=stable_prefix)


def make_prompt(user: SimUser, turn: int) -> str:
    # Global prefix first, then user-stable prefix, then turn-unique tail. This
    # lets vLLM reuse a tiny global prefix across everyone and a large stable
    # prefix across serial turns for the same simulated user.
    return (
        "You are acting as a coding agent. Inspect the synthetic repository context, then solve a realistic implementation task with a detailed patch plan, code-level design, tests, edge cases, and rollout notes.\n"
        + ("TOK " * GLOBAL_PREFIX_TOKENS)
        + "\n\n"
        + user.stable_prefix
        + "\n\nCurrent turn:\n"
        f"user_id={user.user_id} turn={turn}\n"
        + ("TOK " * TURN_UNIQUE_TOKENS)
        + "\n\nCoding task: design a robust repository-wide change that touches parser logic, request scheduling, metrics reporting, and tests. Return a detailed coding response with root cause analysis, patch plan, implementation sketch, unit/integration tests, edge cases, performance considerations, and risks. Do not be terse."
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


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


class RequestLogger:
    def __init__(self, path: Path | None) -> None:
        self.path = path
        self.lock = threading.Lock()
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, row: dict[str, Any]) -> None:
        if not self.path:
            return
        with self.lock:
            with self.path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(row, sort_keys=True, default=str) + "\n")


class EndpointResolver:
    def __init__(
        self,
        base_url: str | None,
        instance_id: int | None,
        container_port: str,
        on_change: Callable[[str | None, str, dict[str, Any]], None] | None = None,
    ) -> None:
        self.fixed_base_url = base_url.rstrip("/") if base_url else None
        self.instance_id = instance_id
        self.container_port = container_port
        self.on_change = on_change
        self._current: str | None = self.fixed_base_url
        self._vast: Any | None = None
        self.lock = threading.Lock()
        self.endpoint_changes = 0
        self.last_error = ""

    def _vast_client(self) -> Any:
        if self._vast is None:
            from vastai import VastAI

            self._vast = VastAI()
        return self._vast

    def resolve(self, force: bool = False) -> str:
        if self.instance_id is None:
            if not self._current:
                raise RuntimeError("base_url is required when instance_id is not set")
            return self._current
        with self.lock:
            if self._current and not force:
                return self._current
            info = self._vast_client().show_instance(id=self.instance_id)
            host = info.get("public_ipaddr")
            ports = info.get("ports") or {}
            entries = ports.get(self.container_port) or []
            mapped = (entries[0] or {}).get("HostPort") if entries else None
            if not host or not mapped:
                raise RuntimeError(f"could not resolve {self.container_port} for instance {self.instance_id}")
            new_url = f"http://{host}:{mapped}"
            old_url = self._current
            if old_url and old_url != new_url:
                self.endpoint_changes += 1
                if self.on_change:
                    self.on_change(old_url, new_url, info)
            self._current = new_url
            return new_url

    def refresh(self) -> str:
        return self.resolve(force=True)

    def base_url(self) -> str:
        return self.resolve()

    def metrics_url(self) -> str:
        return self.resolve().rstrip("/") + "/metrics"

    def completion_url(self) -> str:
        return self.resolve().rstrip("/") + "/v1/chat/completions"

    def tokenize_url(self) -> str:
        return self.resolve().rstrip("/") + "/tokenize"


class MetricsSampler:
    def __init__(self, endpoint: EndpointResolver, api_key: str, interval: float = 2.0) -> None:
        self.endpoint = endpoint
        self.api_key = api_key
        self.interval = interval
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.samples: list[dict[str, float]] = []
        self.before: dict[str, float] = {}
        self.after: dict[str, float] = {}
        self.scrape_attempts = 0
        self.scrape_failures = 0
        self.last_error = ""

    def scrape(self) -> dict[str, float]:
        self.scrape_attempts += 1
        last_exc: Exception | None = None
        for attempt in range(2):
            try:
                req = urllib.request.Request(self.endpoint.metrics_url(), headers={"Authorization": f"Bearer {self.api_key}"})
                with urllib.request.urlopen(req, timeout=10) as response:
                    text = response.read().decode(errors="replace")
                break
            except Exception as exc:
                last_exc = exc
                self.last_error = f"{type(exc).__name__}: {exc}"
                if attempt == 0 and self.endpoint.instance_id is not None:
                    try:
                        self.endpoint.refresh()
                        continue
                    except Exception as refresh_exc:
                        last_exc = refresh_exc
                        self.last_error = f"refresh {type(refresh_exc).__name__}: {refresh_exc}"
                self.scrape_failures += 1
                raise last_exc
        else:
            self.scrape_failures += 1
            raise RuntimeError("metrics scrape failed")
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
            "metrics_scrape_attempts": float(self.scrape_attempts),
            "metrics_scrape_failures": float(self.scrape_failures),
            "metrics_endpoint_changes": float(self.endpoint.endpoint_changes),
        }


def token_count(endpoint: EndpointResolver, model: str, api_key: str, prompt: str, timeout: int) -> int:
    """Estimate token count from character length (1 token ≈ 4 chars)."""
    return max(1, len(prompt) // 4)


def one_request(
    endpoint: EndpointResolver,
    model: str,
    api_key: str,
    user: SimUser,
    turn: int,
    timeout: int,
    phase: str,
    concurrency: int,
    request_logger: RequestLogger,
    max_tokens_override: int | None = None,
) -> dict[str, Any]:
    request_id = uuid.uuid4().hex
    started_at = now_utc()
    started = time.monotonic()
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": make_prompt(user, turn)}],
        "temperature": 0,
    }
    if max_tokens_override is not None:
        payload["max_tokens"] = max_tokens_override
    elif user.bucket.max_tokens is not None:
        payload["max_tokens"] = user.bucket.max_tokens

    result: dict[str, Any]
    last_exc: Exception | None = None
    for attempt in range(2):
        try:
            req = urllib.request.Request(
                endpoint.completion_url(),
                data=json.dumps(payload).encode(),
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=timeout) as response:
                body = json.loads(response.read().decode())
            elapsed = time.monotonic() - started
            usage = body.get("usage") or {}
            choice = (body.get("choices") or [{}])[0]
            result = {
                "ok": True,
                "bucket": user.bucket.name,
                "user_id": user.user_id,
                "turn": turn,
                "elapsed": elapsed,
                "prompt_tokens": int(usage.get("prompt_tokens") or 0),
                "completion_tokens": int(usage.get("completion_tokens") or 0),
                "finish_reason": choice.get("finish_reason"),
            }
            break
        except urllib.error.HTTPError as exc:
            # 502/503 can happen while a remapped Vast proxy is still coming up;
            # refresh once in dynamic mode. Other HTTP errors are request-level failures.
            last_exc = exc
            if attempt == 0 and endpoint.instance_id is not None and exc.code in {502, 503, 504}:
                try:
                    endpoint.refresh()
                    continue
                except Exception:
                    pass
            result = {"ok": False, "bucket": user.bucket.name, "user_id": user.user_id, "turn": turn, "elapsed": time.monotonic() - started, "error": f"HTTP {exc.code}"}
            break
        except Exception as exc:
            last_exc = exc
            if attempt == 0 and endpoint.instance_id is not None:
                try:
                    endpoint.refresh()
                    continue
                except Exception:
                    pass
            result = {"ok": False, "bucket": user.bucket.name, "user_id": user.user_id, "turn": turn, "elapsed": time.monotonic() - started, "error": type(exc).__name__}
            break
    else:
        result = {"ok": False, "bucket": user.bucket.name, "user_id": user.user_id, "turn": turn, "elapsed": time.monotonic() - started, "error": type(last_exc).__name__ if last_exc else "UnknownError"}

    ended_at = now_utc()
    request_logger.write({
        "request_id": request_id,
        "phase": phase,
        "concurrency": concurrency,
        "started_at": started_at,
        "ended_at": ended_at,
        **result,
    })
    return result


def run_step(
    endpoint: EndpointResolver,
    model: str,
    api_key: str,
    concurrency: int,
    turns_per_user: int,
    warmup_turns: int,
    warmup_max_tokens: int,
    measured_max_tokens: int | None,
    post_warmup_gap: float,
    timeout: int,
    buckets: list[PrefixBucket],
    shared_prefix: bool,
    metrics_interval: float,
    request_logger: RequestLogger,
    instance_id: int | None = None,
    record_ledger: bool = False,
) -> dict[str, Any]:
    weighted = [bucket for bucket in buckets for _ in range(bucket.weight)]
    users = [make_user(user_id, random.choice(weighted), shared_prefix) for user_id in range(1, concurrency + 1)]
    requests = concurrency * turns_per_user
    submitted = 0
    skipped_followup_turns = 0
    results: list[dict[str, Any]] = []
    started = time.monotonic()
    last_progress = started
    first_measured_turn = warmup_turns + 1

    def submit_turn(
        pool: futures.ThreadPoolExecutor,
        user: SimUser,
        turn: int,
        max_tokens_override: int | None = None,
    ) -> futures.Future[dict[str, Any]]:
        nonlocal submitted
        submitted += 1
        return pool.submit(one_request, endpoint, model, api_key, user, turn, timeout, "warmup" if turn <= warmup_turns else "measured", concurrency, request_logger, max_tokens_override)

    def print_progress(pending_count: int) -> None:
        ok_count = sum(1 for r in results if r.get("ok"))
        error_count = len(results) - ok_count
        print(
            "  progress "
            f"planned={requests} submitted={submitted} completed={len(results)} "
            f"ok={ok_count} errors={error_count} in_flight={pending_count} "
            f"skipped_followup_turns={skipped_followup_turns}"
        )

    warmup_results: list[dict[str, Any]] = []
    warmup_started = time.monotonic()
    if warmup_turns > 0:
        print(f"  warming prefix cache: warmup_turns={warmup_turns} warmup_max_tokens={warmup_max_tokens}")
        with futures.ThreadPoolExecutor(max_workers=concurrency) as pool:
            pending: set[futures.Future[dict[str, Any]]] = {
                submit_turn(pool, user, 1, warmup_max_tokens) for user in users
            }
            while pending:
                done, pending = futures.wait(pending, timeout=5, return_when=futures.FIRST_COMPLETED)
                for fut in done:
                    result = fut.result()
                    warmup_results.append(result)
                    turn = int(result.get("turn") or 0)
                    if result.get("ok") and turn < warmup_turns:
                        user = users[int(result["user_id"]) - 1]
                        pending.add(submit_turn(pool, user, turn + 1, warmup_max_tokens))
        warmup_wall = time.monotonic() - warmup_started
        warmup_ok = sum(1 for r in warmup_results if r.get("ok"))
        print(f"  warmup complete ok={warmup_ok}/{len(warmup_results)} wall_s={warmup_wall:.1f}")
        if post_warmup_gap > 0:
            print(f"  post-warmup settle {post_warmup_gap:.1f}s")
            time.sleep(post_warmup_gap)

    submitted = 0
    skipped_followup_turns = 0
    results = []
    started = time.monotonic()
    last_progress = started
    with MetricsSampler(endpoint, api_key, interval=metrics_interval) as sampler:
        with futures.ThreadPoolExecutor(max_workers=concurrency) as pool:
            pending = {submit_turn(pool, user, first_measured_turn, measured_max_tokens) for user in users}
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
                    measured_idx = int(result.get("turn") or 0) - warmup_turns
                    if result.get("ok") and measured_idx < turns_per_user:
                        user = users[int(result["user_id"]) - 1]
                        pending.add(submit_turn(pool, user, int(result["turn"]) + 1, measured_max_tokens))
                    elif not result.get("ok"):
                        skipped_followup_turns += max(0, turns_per_user - measured_idx)
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
    latency_avg = statistics.mean(latencies) if latencies else 0.0
    latency_p50 = percentile(latencies, 50)
    latency_p95 = percentile(latencies, 95)
    latency_max = max(latencies) if latencies else 0.0
    summary: dict[str, Any] = {
        "concurrency": concurrency,
        "warmup_turns": warmup_turns,
        "measured_turns_per_user": turns_per_user,
        "requests_planned": requests,
        "requests_submitted": submitted,
        "requests_completed": len(results),
        "requests_ok": len(ok),
        "requests_failed": len(bad),
        "skipped_followup_turns": skipped_followup_turns,
        "wall_seconds": wall,
        "rps": len(ok) / wall if wall else 0.0,
        "client_prompt_tokens": prompt_tokens,
        "client_completion_tokens": completion_tokens,
        "client_prompt_tps": prompt_tokens / wall if wall else 0.0,
        "client_generation_tps": completion_tokens / wall if wall else 0.0,
        "client_total_tps": (prompt_tokens + completion_tokens) / wall if wall else 0.0,
        "latency_avg_seconds": latency_avg,
        "latency_p50_seconds": latency_p50,
        "latency_p95_seconds": latency_p95,
        "latency_max_seconds": latency_max,
        **server,
    }

    if record_ledger and instance_id is not None:
        launch_ledger.record_metric_samples(
            instance_id=instance_id,
            source="burnin_step",
            metrics={f"burnin.{k}": float(v) for k, v in summary.items() if isinstance(v, (int, float))},
            labels={"concurrency": concurrency},
            details={"base_url": endpoint.base_url(), "request_log": str(request_logger.path) if request_logger.path else None},
        )
        launch_ledger.record_event(
            instance_id=instance_id,
            event_name=f"burnin_step_finished_c{concurrency}",
            source="burnin",
            details={"concurrency": concurrency, "requests_ok": len(ok), "requests_failed": len(bad)},
        )

    print(f"concurrency={concurrency} simulated_users={concurrency} warmup_turns={warmup_turns} measured_turns_per_user={turns_per_user} planned_measured_requests={requests} submitted_requests={submitted} completed_measured_results={len(results)} skipped_followup_turns={skipped_followup_turns} wall_s={wall:.1f}")
    print(f"  ok={len(ok)} errors={len(bad)} rps={len(ok) / wall:.2f}")
    print(f"  client_prompt_tps={summary['client_prompt_tps']:.2f} client_generation_tps={summary['client_generation_tps']:.2f} client_total_tps={summary['client_total_tps']:.2f}")
    print(f"  latency_s avg={latency_avg:.2f} p50={latency_p50:.2f} p95={latency_p95:.2f} max={latency_max:.2f}")
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
    for bucket in buckets:
        count = sum(1 for r in ok if r.get("bucket") == bucket.name)
        if count:
            print(f"  bucket {bucket.name}: {count}")
    if bad:
        errors: dict[str, int] = {}
        for r in bad:
            errors[str(r.get("error"))] = errors.get(str(r.get("error")), 0) + 1
        print(f"  errors_by_type={errors}")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Coding-agent-shaped saturation ramp")
    parser.add_argument("--model", required=True)
    parser.add_argument("--concurrency", default="36,40,44,46", help="Comma-separated concurrency steps")
    parser.add_argument("--requests-per-concurrency", type=int, default=6, help="Measured serial turns per simulated user/worker after warmup")
    parser.add_argument("--warmup-turns", type=int, default=1, help="unmeasured serial turns per simulated user to seed prefix/KV cache before measuring")
    parser.add_argument("--warmup-max-tokens", type=int, default=1, help="max_tokens for warmup turns; keep small to pay prefill without burning decode")
    parser.add_argument("--max-tokens", type=int, default=0, help="max_tokens for measured turns; <=0 uses server default")
    parser.add_argument("--post-warmup-gap", type=float, default=2.0, help="Seconds to sleep after warmup before measured round")
    parser.add_argument("--max-model-len", type=int, default=160000, help="preflight prompt token limit for the active model profile")
    parser.add_argument("--shared-prefix", action="store_true", help="TPS-only mode: all simulated users share the same stable prefix; do not use for KV-cache residency tests")
    parser.add_argument("--fixed-prefix-tokens", type=int, default=0, help="TPS-only mode: if >0, use one fixed prefix bucket of this size for all users")
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument("--step-gap", type=float, default=10.0, help="Seconds to sleep between concurrency steps")
    parser.add_argument("--pause", action="store_true", help="Pause for Enter between concurrency steps, after --step-gap")
    parser.add_argument("--base-url", help="Fixed OpenAI-compatible base URL; use for Cloudflare tunnel or non-Vast endpoints")
    parser.add_argument("--instance-id", type=int, help="Vast instance id; enables dynamic port resolution and ledger writes")
    parser.add_argument("--container-port", default="8000/tcp", help="Container port to resolve when --instance-id is set")
    parser.add_argument("--metrics-sample-interval", type=float, default=2.0)
    parser.add_argument("--no-record-ledger", action="store_true", help="Disable default launch ledger recording")
    parser.add_argument("--request-log", type=Path, help="Write request-level JSONL; default is auto under state/burnin")
    parser.add_argument("--no-request-log", action="store_true", help="Disable default request-level JSONL")
    parser.add_argument("--report-out", type=Path, help="Publish-safe Markdown report path; default under docs/reports")
    parser.add_argument("--no-report", action="store_true", help="Disable default end-of-run report generation")
    args = parser.parse_args()

    api_key = os.environ.get("OPENAI_API_KEY") or os.environ.get("VLLM_API_KEY")
    if not api_key:
        raise SystemExit("set OPENAI_API_KEY or source env.vast-management so VLLM_API_KEY is set")
    if args.instance_id is None and not args.base_url:
        raise SystemExit("provide --instance-id or --base-url")

    record_ledger = bool(args.instance_id is not None and not args.no_record_ledger)
    run_started_at = now_utc()
    run_stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')

    request_log_path = None if args.no_request_log else args.request_log
    if request_log_path is None and not args.no_request_log:
        endpoint_slug = str(args.instance_id) if args.instance_id is not None else "external"
        request_log_path = Path("state/burnin") / f"{endpoint_slug}-{run_stamp}-coding-agent-saturation.requests.jsonl"
    request_logger = RequestLogger(request_log_path)

    workload_config = {
        "configured concurrency": args.concurrency,
        "measured requests per simulated user": args.requests_per_concurrency,
        "warmup turns": args.warmup_turns,
        "warmup max tokens": args.warmup_max_tokens,
        "measured max tokens": "server_default" if args.max_tokens <= 0 else args.max_tokens,
        "shared prefix": bool(args.shared_prefix),
        "fixed prefix tokens": args.fixed_prefix_tokens,
        "max model length": args.max_model_len,
        "workload shape": "long generation" if args.max_tokens > 1024 else "coding-agent saturation",
    }

    def on_endpoint_change(old: str | None, new: str, info: dict[str, Any]) -> None:
        print(f"Endpoint changed: {old or 'none'} -> {new}")
        if record_ledger:
            launch_ledger.record_event(
                instance_id=args.instance_id,
                event_name="burnin_endpoint_changed",
                source="burnin",
                details={"old": old, "new": new, "machine_id": info.get("machine_id")},
            )

    endpoint = EndpointResolver(args.base_url, args.instance_id, args.container_port, on_endpoint_change)
    print(f"base_url={endpoint.refresh() if args.instance_id is not None else endpoint.base_url()}")
    if request_logger.path:
        print(f"request_log={request_logger.path}")
    if record_ledger:
        launch_ledger.record_event(
            instance_id=args.instance_id,
            event_name="burnin_started",
            source="burnin",
            details={"model": args.model, "base_url": endpoint.base_url(), "request_log": str(request_logger.path) if request_logger.path else None, "workload_config": workload_config},
        )

    active_buckets = [PrefixBucket(f"fixed_prefix_{args.fixed_prefix_tokens}", 100, args.fixed_prefix_tokens, None)] if args.fixed_prefix_tokens > 0 else BUCKETS
    avg_user_prefix = sum(bucket.weight * bucket.user_prefix_tokens for bucket in active_buckets) / sum(bucket.weight for bucket in active_buckets)
    theoretical_cache_share = 1.0 if args.warmup_turns > 0 else max(0, args.requests_per_concurrency - 1) / args.requests_per_concurrency
    print("Buckets:")
    measured_cap = "server_default" if args.max_tokens <= 0 else str(args.max_tokens)
    print(f"  global_prefix≈{GLOBAL_PREFIX_TOKENS} tokens; turn_unique_tail≈{TURN_UNIQUE_TOKENS} tokens; measured_output_cap={measured_cap}")
    print(f"  warmup_turns={args.warmup_turns}; measured_requests_per_simulated_user={args.requests_per_concurrency}; theoretical_measured_warm_prefix_share≈{theoretical_cache_share:.0%}")
    if args.shared_prefix:
        print("  shared_prefix=true (TPS-only; not a KV-cache residency test)")
    print(f"  weighted_avg_user_prefix≈{avg_user_prefix:.0f} tokens")
    for bucket in active_buckets:
        max_out = "server_default" if bucket.max_tokens is None else str(bucket.max_tokens)
        print(f"  {bucket.name}: weight={bucket.weight}% user_prefix≈{bucket.user_prefix_tokens} max_out={max_out}")
    print("Preflight token counts:")
    for bucket in active_buckets:
        user = make_user(1, bucket, args.shared_prefix)
        count = token_count(endpoint, args.model, api_key, make_prompt(user, 1), args.timeout)
        print(f"  {bucket.name}: configured_user_prefix={bucket.user_prefix_tokens} actual_prompt_tokens={count}")
        if count >= args.max_model_len:
            raise SystemExit(f"preflight failed: {bucket.name} prompt has {count} tokens, >= {args.max_model_len} max_model_len")
    print()

    for concurrency in [int(x) for x in args.concurrency.split(",") if x.strip()]:
        total_requests = concurrency * args.requests_per_concurrency
        total_warmup_requests = concurrency * args.warmup_turns
        estimated_prefix_footprint = concurrency * avg_user_prefix
        print("=" * 72)
        print(
            "Starting step: "
            f"simulated_users={concurrency} "
            f"warmup_turns={args.warmup_turns} "
            f"measured_turns_per_user={args.requests_per_concurrency} "
            f"warmup_requests={total_warmup_requests} "
            f"measured_requests={total_requests} "
            f"estimated_user_prefix_footprint≈{estimated_prefix_footprint:.0f} "
            f"global_prefix≈{GLOBAL_PREFIX_TOKENS} "
            f"turn_unique_tail≈{TURN_UNIQUE_TOKENS} "
            "user_prefix_distribution="
            + ",".join(f"{bucket.name}:{bucket.weight}%/{bucket.user_prefix_tokens}" for bucket in active_buckets)
        )
        if record_ledger:
            launch_ledger.record_event(
                instance_id=args.instance_id,
                event_name=f"burnin_step_started_c{concurrency}",
                source="burnin",
                details={"concurrency": concurrency, "measured_requests": total_requests, "warmup_requests": total_warmup_requests, "workload_config": workload_config},
            )
        run_step(
            endpoint,
            args.model,
            api_key,
            concurrency,
            args.requests_per_concurrency,
            args.warmup_turns,
            args.warmup_max_tokens,
            None if args.max_tokens <= 0 else args.max_tokens,
            args.post_warmup_gap,
            args.timeout,
            active_buckets,
            args.shared_prefix,
            args.metrics_sample_interval,
            request_logger,
            args.instance_id,
            record_ledger,
        )
        if args.step_gap > 0:
            print(f"Sleeping {args.step_gap:.1f}s before next step...")
            time.sleep(args.step_gap)
        if args.pause:
            print("Press Enter for next step, Ctrl-C to stop.")
            input()
    run_finished_at = now_utc()
    if record_ledger:
        launch_ledger.record_event(
            instance_id=args.instance_id,
            event_name="burnin_finished",
            source="burnin",
            details={"model": args.model, "base_url": endpoint.base_url(), "endpoint_changes": endpoint.endpoint_changes, "workload_config": workload_config},
        )

    if not args.no_report:
        report_out = args.report_out
        if report_out is None:
            model_slug = re.sub(r"[^a-zA-Z0-9._-]+", "-", args.model).strip("-")
            conc_slug = re.sub(r"[^0-9,]+", "", args.concurrency).replace(",", "-") or "run"
            report_out = Path("docs/reports") / f"{model_slug}-{conc_slug}way-burnin-{run_stamp}.md"
        try:
            from scripts import report_launch_metrics

            report_args = SimpleNamespace(
                db=launch_ledger.DEFAULT_DB_PATH,
                instance_id=args.instance_id,
                launch_key=None,
                since=run_started_at,
                until=run_finished_at,
                out=None,
                include_provider_ids=False,
                tail_windows=12,
                workload_model=args.model,
                report_title=f"# B200 Burn-in Metrics Report: {args.model}",
                workload_config=workload_config,
            )
            report = report_launch_metrics.make_report(report_args)
            report_out.parent.mkdir(parents=True, exist_ok=True)
            report_out.write_text(report)
            print(f"report={report_out}")
        except Exception as exc:
            print(f"WARN: report generation failed: {exc}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
