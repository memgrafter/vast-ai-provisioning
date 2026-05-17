#!/usr/bin/env python3
"""Fetch vLLM Prometheus metrics and print a compact human summary.

Usage:
    . env.vast-management
    ./run.sh scripts/summarize_vllm_metrics.py \
      --instance-id <vast-instance-id>

Or print a recent throughput gauge from two scrapes:
    . env.vast-management
    ./run.sh scripts/summarize_vllm_metrics.py \
      --instance-id <vast-instance-id> \
      --interval 10

Fixed URL mode is still available for non-Vast targets:
    ./run.sh scripts/summarize_vllm_metrics.py \
      --metrics-url http://<host>:<mapped_8000>/metrics
"""

from __future__ import annotations

import argparse
import contextlib
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import launch_ledger


SAMPLE_RE = re.compile(r"^(?P<name>[a-zA-Z_:][a-zA-Z0-9_:]*)(?P<labels>\{[^}]*\})?\s+(?P<value>[-+0-9.eE]+)\s*$")
LABEL_RE = re.compile(r'([a-zA-Z_][a-zA-Z0-9_]*)="((?:[^"\\]|\\.)*)"')


@dataclass
class Metrics:
    values: dict[str, float] = field(default_factory=dict)
    labeled: dict[tuple[str, tuple[tuple[str, str], ...]], float] = field(default_factory=dict)
    ttft_buckets: list[tuple[str, float]] = field(default_factory=list)

    def get(self, name: str, default: float = 0.0) -> float:
        return self.values.get(name, default)

    def label_value(self, name: str, **labels: str) -> float:
        wanted = tuple(sorted(labels.items()))
        for (metric_name, metric_labels), value in self.labeled.items():
            if metric_name != name:
                continue
            label_dict = dict(metric_labels)
            if all(label_dict.get(k) == v for k, v in wanted):
                return value
        return 0.0


def parse_labels(raw: str | None) -> dict[str, str]:
    if not raw:
        return {}
    return {m.group(1): m.group(2).replace(r'\"', '"').replace(r"\\", "\\") for m in LABEL_RE.finditer(raw)}


def parse_metrics(text: str) -> Metrics:
    metrics = Metrics()
    for line in text.splitlines():
        if not line or line.startswith("#"):
            continue
        match = SAMPLE_RE.match(line)
        if not match:
            continue
        name = match.group("name")
        labels = parse_labels(match.group("labels"))
        value = float(match.group("value"))
        key = (name, tuple(sorted(labels.items())))
        metrics.labeled[key] = value
        if not labels:
            metrics.values[name] = value
        else:
            # Keep the unlabeled convenience value for metrics with a single model/engine series.
            metrics.values[name] = value
        if name == "vllm:time_to_first_token_seconds_bucket" and "le" in labels:
            metrics.ttft_buckets.append((labels["le"], value))
    return metrics


def fmt_num(value: float) -> str:
    if value == int(value):
        return f"{int(value):,}"
    return f"{value:,.2f}"


def pct(numer: float, denom: float) -> str:
    if denom <= 0:
        return "n/a"
    return f"{(numer / denom) * 100:.1f}%"


def avg(total: float, count: float) -> str:
    if count <= 0:
        return "n/a"
    return f"{total / count:.2f}"


class MetricsEndpoint:
    def __init__(self, *, metrics_url: str | None, base_url: str | None, instance_id: int | None, container_port: str) -> None:
        self.fixed_metrics_url = metrics_url.rstrip("/") if metrics_url else None
        self.fixed_base_url = base_url.rstrip("/") if base_url else None
        self.instance_id = instance_id
        self.container_port = container_port
        self._current_metrics_url: str | None = None
        self._vast: Any | None = None
        self.endpoint_changes = 0

    def _vast_client(self) -> Any:
        if self._vast is None:
            from vastai import VastAI

            self._vast = VastAI()
        return self._vast

    def _url_from_fixed_base(self) -> str | None:
        if not self.fixed_base_url:
            return None
        base = self.fixed_base_url
        if base.endswith("/v1"):
            base = base[:-3]
        return base + "/metrics"

    def _resolve_vast_metrics_url(self) -> str:
        if self.instance_id is None:
            raise RuntimeError("instance_id is not set")
        info = self._vast_client().show_instance(id=self.instance_id)
        host = info.get("public_ipaddr")
        ports = info.get("ports") or {}
        entries = ports.get(self.container_port) or []
        mapped = (entries[0] or {}).get("HostPort") if entries else None
        if not host or not mapped:
            raise RuntimeError(f"could not resolve {self.container_port} for instance {self.instance_id}")
        return f"http://{host}:{mapped}/metrics"

    def resolve(self, *, force: bool = False) -> str:
        if self.fixed_metrics_url:
            return self.fixed_metrics_url
        fixed_base_url = self._url_from_fixed_base()
        if fixed_base_url:
            return fixed_base_url
        if not force and self._current_metrics_url:
            return self._current_metrics_url
        new_url = self._resolve_vast_metrics_url()
        if self._current_metrics_url and self._current_metrics_url != new_url:
            self.endpoint_changes += 1
        self._current_metrics_url = new_url
        return new_url

    def refresh(self) -> str:
        return self.resolve(force=True)

    @property
    def is_dynamic(self) -> bool:
        return not self.fixed_metrics_url and not self.fixed_base_url and self.instance_id is not None


def fetch_metrics(endpoint: MetricsEndpoint, api_key: str | None, timeout: int) -> str:
    headers = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    last_exc: Exception | None = None
    for attempt in range(2):
        try:
            req = urllib.request.Request(endpoint.resolve(), headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as response:
                return response.read().decode("utf-8", errors="replace")
        except Exception as exc:
            last_exc = exc
            if attempt == 0 and endpoint.is_dynamic:
                endpoint.refresh()
                continue
            raise
    raise RuntimeError(f"metrics fetch failed: {last_exc}")


def print_gauge(before: Metrics, after: Metrics, elapsed_s: float) -> None:
    prompt_delta = after.get("vllm:prompt_tokens_total") - before.get("vllm:prompt_tokens_total")
    prompt_compute_delta = after.label_value("vllm:prompt_tokens_by_source_total", source="local_compute") - before.label_value(
        "vllm:prompt_tokens_by_source_total", source="local_compute"
    )
    prompt_cache_hit_delta = after.label_value("vllm:prompt_tokens_by_source_total", source="local_cache_hit") - before.label_value(
        "vllm:prompt_tokens_by_source_total", source="local_cache_hit"
    )
    prompt_external_kv_delta = after.label_value("vllm:prompt_tokens_by_source_total", source="external_kv_transfer") - before.label_value(
        "vllm:prompt_tokens_by_source_total", source="external_kv_transfer"
    )
    generation_delta = after.get("vllm:generation_tokens_total") - before.get("vllm:generation_tokens_total")
    total_delta = prompt_delta + generation_delta

    print(f"Recent {elapsed_s:.2f}s gauge:\n")
    print("```text")
    print(f"requests running: {fmt_num(after.get('vllm:num_requests_running'))}")
    print(f"requests waiting: {fmt_num(after.get('vllm:num_requests_waiting'))}")
    print(f"KV cache usage: {after.get('vllm:kv_cache_usage_perc'):.1%}")
    print("```")
    print()

    print("Throughput:\n")
    print("```text")
    print(f"prompt_total_delta:     {fmt_num(prompt_delta)} tokens")
    print(f"prompt_compute_delta:   {fmt_num(prompt_compute_delta)} tokens")
    print(f"prompt_cache_hit_delta: {fmt_num(prompt_cache_hit_delta)} tokens")
    print(f"prompt_external_kv_delta: {fmt_num(prompt_external_kv_delta)} tokens")
    print(f"generation_delta:       {fmt_num(generation_delta)} tokens")
    print(f"total_delta:            {fmt_num(total_delta)} tokens")
    print("")
    print(f"prompt_total_tps:       {prompt_delta / elapsed_s:.2f} tok/s")
    print(f"prompt_compute_tps:     {prompt_compute_delta / elapsed_s:.2f} tok/s")
    print(f"prompt_cache_hit_tps:   {prompt_cache_hit_delta / elapsed_s:.2f} tok/s")
    print(f"prompt_external_kv_tps: {prompt_external_kv_delta / elapsed_s:.2f} tok/s")
    print(f"generation_tps:         {generation_delta / elapsed_s:.2f} tok/s")
    print(f"total_tps:              {total_delta / elapsed_s:.2f} tok/s")
    print("```")
    print()

    print("Completed in window:\n")
    print("```text")
    for reason in ("stop", "length", "error", "abort", "repetition"):
        delta = after.label_value("vllm:request_success_total", finished_reason=reason) - before.label_value(
            "vllm:request_success_total", finished_reason=reason
        )
        if delta:
            print(f"{reason}: {fmt_num(delta)}")

    for metric, label in (
        ("vllm:request_queue_time_seconds", "queue"),
        ("vllm:request_inference_time_seconds", "inference"),
        ("vllm:time_to_first_token_seconds", "TTFT"),
    ):
        count_delta = after.get(metric + "_count") - before.get(metric + "_count")
        sum_delta = after.get(metric + "_sum") - before.get(metric + "_sum")
        if count_delta:
            print(f"{label}_completed: {fmt_num(count_delta)} avg_s: {sum_delta / count_delta:.2f}")
    print("```")


def current_metrics_payload(metrics: Metrics) -> dict[str, float]:
    return {
        "vllm.requests_running": metrics.get("vllm:num_requests_running"),
        "vllm.requests_waiting": metrics.get("vllm:num_requests_waiting"),
        "vllm.kv_cache_usage_percent": metrics.get("vllm:kv_cache_usage_perc") * 100.0,
        "vllm.prompt_tokens_total": metrics.get("vllm:prompt_tokens_total"),
        "vllm.generation_tokens_total": metrics.get("vllm:generation_tokens_total"),
        "vllm.prefix_cache_queries_total": metrics.get("vllm:prefix_cache_queries_total"),
        "vllm.prefix_cache_hits_total": metrics.get("vllm:prefix_cache_hits_total"),
        "vllm.prompt_tokens_cached_total": metrics.get("vllm:prompt_tokens_cached_total"),
        "vllm.request_success_stop_total": metrics.label_value("vllm:request_success_total", finished_reason="stop"),
        "vllm.request_success_length_total": metrics.label_value("vllm:request_success_total", finished_reason="length"),
        "vllm.request_success_error_total": metrics.label_value("vllm:request_success_total", finished_reason="error"),
        "vllm.request_success_abort_total": metrics.label_value("vllm:request_success_total", finished_reason="abort"),
        "vllm.ttft_count": metrics.get("vllm:time_to_first_token_seconds_count"),
        "vllm.ttft_sum_seconds": metrics.get("vllm:time_to_first_token_seconds_sum"),
        "vllm.queue_count": metrics.get("vllm:request_queue_time_seconds_count"),
        "vllm.queue_sum_seconds": metrics.get("vllm:request_queue_time_seconds_sum"),
        "vllm.inference_count": metrics.get("vllm:request_inference_time_seconds_count"),
        "vllm.inference_sum_seconds": metrics.get("vllm:request_inference_time_seconds_sum"),
    }


def interval_metrics_payload(before: Metrics, after: Metrics, elapsed_s: float) -> dict[str, float]:
    prompt_delta = after.get("vllm:prompt_tokens_total") - before.get("vllm:prompt_tokens_total")
    generation_delta = after.get("vllm:generation_tokens_total") - before.get("vllm:generation_tokens_total")
    return {
        "vllm.window_seconds": elapsed_s,
        "vllm.prompt_tokens_delta": prompt_delta,
        "vllm.generation_tokens_delta": generation_delta,
        "vllm.total_tokens_delta": prompt_delta + generation_delta,
        "vllm.prompt_tokens_per_second": prompt_delta / elapsed_s if elapsed_s > 0 else 0.0,
        "vllm.generation_tokens_per_second": generation_delta / elapsed_s if elapsed_s > 0 else 0.0,
        "vllm.total_tokens_per_second": (prompt_delta + generation_delta) / elapsed_s if elapsed_s > 0 else 0.0,
        **current_metrics_payload(after),
    }


def print_summary(metrics: Metrics) -> None:
    running = metrics.get("vllm:num_requests_running")
    waiting = metrics.get("vllm:num_requests_waiting")
    kv = metrics.get("vllm:kv_cache_usage_perc")

    stop = metrics.label_value("vllm:request_success_total", finished_reason="stop")
    length = metrics.label_value("vllm:request_success_total", finished_reason="length")
    error = metrics.label_value("vllm:request_success_total", finished_reason="error")
    abort = metrics.label_value("vllm:request_success_total", finished_reason="abort")

    prompt_total = metrics.get("vllm:prompt_tokens_total")
    gen_total = metrics.get("vllm:generation_tokens_total")
    queries = metrics.get("vllm:prefix_cache_queries_total")
    hits = metrics.get("vllm:prefix_cache_hits_total")
    cached = metrics.get("vllm:prompt_tokens_cached_total")
    local_compute = metrics.label_value("vllm:prompt_tokens_by_source_total", source="local_compute")
    local_hit = metrics.label_value("vllm:prompt_tokens_by_source_total", source="local_cache_hit")
    external_kv = metrics.label_value("vllm:prompt_tokens_by_source_total", source="external_kv_transfer")

    req_prompt_count = metrics.get("vllm:request_prompt_tokens_count")
    req_prompt_sum = metrics.get("vllm:request_prompt_tokens_sum")
    req_gen_count = metrics.get("vllm:request_generation_tokens_count")
    req_gen_sum = metrics.get("vllm:request_generation_tokens_sum")

    ttft_count = metrics.get("vllm:time_to_first_token_seconds_count")
    ttft_sum = metrics.get("vllm:time_to_first_token_seconds_sum")
    queue_count = metrics.get("vllm:request_queue_time_seconds_count")
    queue_sum = metrics.get("vllm:request_queue_time_seconds_sum")
    infer_count = metrics.get("vllm:request_inference_time_seconds_count")
    infer_sum = metrics.get("vllm:request_inference_time_seconds_sum")

    print("Current metrics:\n")
    print("```text")
    print(f"requests running: {fmt_num(running)}")
    print(f"requests waiting: {fmt_num(waiting)}")
    print(f"KV cache usage: {kv:.1%}")
    print("```\n")

    print("Requests:\n")
    print("```text")
    print(f"stop:   {fmt_num(stop)}")
    print(f"length: {fmt_num(length)}")
    print(f"error:  {fmt_num(error)}")
    print(f"abort:  {fmt_num(abort)}")
    print("```\n")

    print("Tokens:\n")
    print("```text")
    print(f"prompt_tokens_total:      {fmt_num(prompt_total)}")
    print(f"generation_tokens_total:  {fmt_num(gen_total)}")
    print(f"total counter tokens:     {fmt_num(prompt_total + gen_total)}")
    print("```\n")

    print("Request histograms:\n")
    print("```text")
    print(f"request_prompt_tokens_count:      {fmt_num(req_prompt_count)}")
    print(f"request_prompt_tokens_sum: {fmt_num(req_prompt_sum)}")
    print(f"avg prompt/request:        ~{fmt_num(req_prompt_sum / req_prompt_count) if req_prompt_count else 'n/a'}")
    print("")
    print(f"request_generation_tokens_count:  {fmt_num(req_gen_count)}")
    print(f"request_generation_tokens_sum: {fmt_num(req_gen_sum)}")
    print(f"avg generation/request:    ~{fmt_num(req_gen_sum / req_gen_count) if req_gen_count else 'n/a'}")
    print("```\n")

    print("Prefix cache:\n")
    print("```text")
    print(f"prefix_cache_queries_total: {fmt_num(queries)}")
    print(f"prefix_cache_hits_total:    {fmt_num(hits)}")
    print(f"prompt_tokens_cached_total: {fmt_num(cached)}")
    print(f"hit rate:                   ~{pct(hits, queries)}")
    print("```\n")

    print("Prompt sources:\n")
    print("```text")
    print(f"local_compute:   {fmt_num(local_compute)}")
    print(f"local_cache_hit: {fmt_num(local_hit)}")
    print(f"external_kv:     {fmt_num(external_kv)}")
    print("```\n")

    print("TTFT:\n")
    print("```text")
    print(f"count: {fmt_num(ttft_count)}")
    print(f"sum:   {ttft_sum:.2f}s")
    print(f"avg:   ~{avg(ttft_sum, ttft_count)}s")
    print("```\n")

    if metrics.ttft_buckets:
        print("TTFT buckets:\n")
        print("```text")
        wanted = {"0.1", "0.25", "0.5", "0.75", "1.0", "2.5", "5.0", "80.0"}
        def bucket_key(item: tuple[str, float]) -> float:
            return float("inf") if item[0] == "+Inf" else float(item[0])
        for le, value in sorted(metrics.ttft_buckets, key=bucket_key):
            if le in wanted:
                print(f"<= {float(le):>4.2f}s: {fmt_num(value)}")
        print("```\n")

    print("Queue:\n")
    print("```text")
    print(f"count: {fmt_num(queue_count)}")
    print(f"sum:   {queue_sum:.5f}s")
    print(f"avg:   ~{avg(queue_sum, queue_count)}s")
    print("```\n")

    print("Inference:\n")
    print("```text")
    print(f"count: {fmt_num(infer_count)}")
    print(f"sum:   {infer_sum:.2f}s")
    print(f"avg:   ~{avg(infer_sum, infer_count)}s")
    print("```")


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Summarize vLLM /metrics output")
    parser.add_argument("--base-url", help="Base URL, e.g. http://host:port or http://host:port/v1. Optional when --instance-id is set")
    parser.add_argument("--metrics-url", help="Full metrics URL. Overrides --base-url and --instance-id endpoint resolution")
    parser.add_argument("--api-key-env", default="VLLM_API_KEY", help="Env var containing bearer token")
    parser.add_argument("--no-auth", action="store_true", help="Do not send Authorization header")
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--interval", type=float, help="Print a recent throughput gauge using two scrapes this many seconds apart")
    parser.add_argument("--log-file", help="Append output to this file instead of stdout")
    parser.add_argument("--repeat", action="store_true", help="Repeat interval gauges forever; requires --interval")
    parser.add_argument("--instance-id", type=int, help="Vast instance id for dynamic port resolution and writing metrics to launch ledger")
    parser.add_argument("--container-port", default="8000/tcp", help="Container port to resolve when --instance-id is used without --base-url/--metrics-url")
    parser.add_argument("--record-ledger", action="store_true", help="Record selected vLLM metrics to state/launches.sqlite3")
    parser.add_argument("--db", type=Path, default=launch_ledger.DEFAULT_DB_PATH, help="Launch ledger sqlite path")
    args = parser.parse_args(argv)

    if not (args.metrics_url or args.base_url or args.instance_id):
        parser.error("provide --instance-id, --base-url, or --metrics-url")
    endpoint = MetricsEndpoint(
        metrics_url=args.metrics_url,
        base_url=args.base_url,
        instance_id=args.instance_id,
        container_port=args.container_port,
    )

    api_key = None if args.no_auth else os.environ.get(args.api_key_env)
    if not args.no_auth and not api_key:
        print(f"ERROR: {args.api_key_env} is not set", file=sys.stderr)
        return 2

    try:
        if args.repeat and args.interval is None:
            parser.error("--repeat requires --interval")
        if args.interval is not None and args.interval <= 0:
            parser.error("--interval must be > 0")

        if args.record_ledger and args.instance_id is None:
            parser.error("--record-ledger requires --instance-id")

        def record_payload(payload: dict[str, float], interval: bool) -> None:
            if not args.record_ledger:
                return
            launch_ledger.record_metric_samples(
                instance_id=args.instance_id,
                source="vllm_metrics_interval" if interval else "vllm_metrics",
                metrics=payload,
                details={
                    "endpoint_source": "instance_id" if endpoint.is_dynamic else "fixed_url",
                    "container_port": args.container_port if endpoint.is_dynamic else None,
                    "interval": args.interval if interval else None,
                    "endpoint_changes": endpoint.endpoint_changes,
                },
                db_path=args.db,
            )

        def emit_once() -> None:
            text = fetch_metrics(endpoint, api_key, args.timeout)
            if args.interval is not None:
                before = parse_metrics(text)
                start = time.monotonic()
                time.sleep(args.interval)
                after = parse_metrics(fetch_metrics(endpoint, api_key, args.timeout))
                elapsed = time.monotonic() - start
                print(f"=== {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')} ===")
                print_gauge(before, after, elapsed)
                record_payload(interval_metrics_payload(before, after, elapsed), interval=True)
            else:
                metrics = parse_metrics(text)
                print_summary(metrics)
                record_payload(current_metrics_payload(metrics), interval=False)

        if args.log_file:
            while True:
                with open(args.log_file, "a", encoding="utf-8") as log:
                    with contextlib.redirect_stdout(log):
                        emit_once()
                        print()
                if not args.repeat:
                    break
                time.sleep(1)
        else:
            while True:
                emit_once()
                if not args.repeat:
                    break
                print()
                time.sleep(1)
    except urllib.error.HTTPError as exc:
        print(f"ERROR: HTTP {exc.code}: {exc.read().decode(errors='replace')[:500]}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
