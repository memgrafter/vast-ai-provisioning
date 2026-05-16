#!/usr/bin/env python3
"""Generate a publish-safe Markdown report from the local launch metrics ledger.

The report intentionally avoids secret/PII-adjacent fields:
- no public IPs, mapped ports, base URLs, or Authorization data
- no raw details_json blobs
- no local artifact paths
- provider IDs are redacted by default
"""
from __future__ import annotations

import argparse
import math
import statistics
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import launch_ledger


COUNTER_METRICS = [
    "vllm.request_success_stop_total",
    "vllm.request_success_length_total",
    "vllm.request_success_error_total",
    "vllm.request_success_abort_total",
    "vllm.prompt_tokens_total",
    "vllm.generation_tokens_total",
    "vllm.ttft_count",
    "vllm.ttft_sum_seconds",
    "vllm.inference_count",
    "vllm.inference_sum_seconds",
    "vllm.queue_count",
    "vllm.queue_sum_seconds",
]


def now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def fmt(value: Any, digits: int = 2) -> str:
    if value is None:
        return "n/a"
    try:
        value = float(value)
    except Exception:
        return str(value)
    if not math.isfinite(value):
        return "n/a"
    if abs(value) >= 1000:
        return f"{value:,.{digits}f}"
    return f"{value:.{digits}f}"


def fmt_int(value: Any) -> str:
    if value is None:
        return "n/a"
    try:
        return f"{int(round(float(value))):,}"
    except Exception:
        return str(value)


def fmt_money(value: Any) -> str:
    if value is None:
        return "n/a"
    try:
        return f"${float(value):.4f}"
    except Exception:
        return "n/a"


def pct(value: Any) -> str:
    if value is None:
        return "n/a"
    try:
        return f"{float(value):.1f}%"
    except Exception:
        return "n/a"


def percentile(values: list[float], p: float) -> float | None:
    values = sorted(v for v in values if math.isfinite(v))
    if not values:
        return None
    idx = min(len(values) - 1, max(0, int(round((p / 100.0) * (len(values) - 1)))))
    return values[idx]


def avg(values: list[float]) -> float | None:
    values = [v for v in values if math.isfinite(v)]
    return statistics.mean(values) if values else None


def launch_where(instance_id: int | None, launch_key: str | None) -> tuple[str, tuple[Any, ...]]:
    if launch_key:
        return "launch_key = ?", (launch_key,)
    if instance_id is not None:
        return "instance_id = ?", (instance_id,)
    return "1=1", ()


def resolve_launch(con: Any, instance_id: int | None, launch_key: str | None) -> dict[str, Any]:
    where, params = launch_where(instance_id, launch_key)
    row = con.execute(
        f"""
        SELECT *
        FROM launches
        WHERE {where}
        ORDER BY created_at DESC
        LIMIT 1
        """,
        params,
    ).fetchone()
    if not row:
        raise SystemExit("No matching launch row found")
    return dict(row)


def metric_time_clause(since: str | None, until: str | None) -> tuple[str, list[Any]]:
    clauses = []
    params: list[Any] = []
    if since:
        clauses.append("sampled_at >= ?")
        params.append(since)
    if until:
        clauses.append("sampled_at <= ?")
        params.append(until)
    return (" AND " + " AND ".join(clauses)) if clauses else "", params


def fetch_windows(con: Any, launch_key: str, since: str | None, until: str | None) -> list[dict[str, Any]]:
    time_clause, params = metric_time_clause(since, until)
    rows = con.execute(
        f"""
        WITH pivot AS (
          SELECT sampled_at,
            max(CASE WHEN metric_name='vllm.requests_running' THEN metric_value END) AS running,
            max(CASE WHEN metric_name='vllm.requests_waiting' THEN metric_value END) AS waiting,
            max(CASE WHEN metric_name='vllm.kv_cache_usage_percent' THEN metric_value END) AS kv_pct,
            max(CASE WHEN metric_name='vllm.prompt_tokens_delta' THEN metric_value END) AS prompt_delta,
            max(CASE WHEN metric_name='vllm.generation_tokens_delta' THEN metric_value END) AS generation_delta,
            max(CASE WHEN metric_name='vllm.total_tokens_delta' THEN metric_value END) AS total_delta,
            max(CASE WHEN metric_name='vllm.prompt_tokens_per_second' THEN metric_value END) AS prompt_tps,
            max(CASE WHEN metric_name='vllm.generation_tokens_per_second' THEN metric_value END) AS generation_tps,
            max(CASE WHEN metric_name='vllm.total_tokens_per_second' THEN metric_value END) AS total_tps
          FROM launch_metric_samples
          WHERE launch_key = ?
            AND source = 'vllm_metrics_interval'
            {time_clause}
          GROUP BY sampled_at
        )
        SELECT * FROM pivot ORDER BY sampled_at
        """,
        [launch_key, *params],
    ).fetchall()
    return [dict(r) for r in rows]


def active_windows(windows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for row in windows:
        activity = float(row.get("running") or 0) + float(row.get("waiting") or 0) + float(row.get("prompt_delta") or 0) + float(row.get("generation_delta") or 0)
        if activity > 0:
            out.append(row)
    return out


def counter_delta(con: Any, launch_key: str, metric: str, since: str | None, until: str | None) -> tuple[float | None, str]:
    time_clause, params = metric_time_clause(since, until)
    rows = con.execute(
        f"""
        SELECT sampled_at, metric_value
        FROM launch_metric_samples
        WHERE launch_key = ? AND metric_name = ? {time_clause}
        ORDER BY sampled_at, sample_id
        """,
        [launch_key, metric, *params],
    ).fetchall()
    if not rows:
        return None, "missing"
    first = float(rows[0]["metric_value"] or 0)
    last = float(rows[-1]["metric_value"] or 0)
    delta = last - first
    if delta < 0:
        return None, "counter reset or server restart"
    return delta, "ok"


def latest_metric(con: Any, launch_key: str, metric: str, since: str | None, until: str | None) -> tuple[str | None, float | None]:
    time_clause, params = metric_time_clause(since, until)
    row = con.execute(
        f"""
        SELECT sampled_at, metric_value
        FROM launch_metric_samples
        WHERE launch_key = ? AND metric_name = ? {time_clause}
        ORDER BY sampled_at DESC, sample_id DESC
        LIMIT 1
        """,
        [launch_key, metric, *params],
    ).fetchone()
    if not row:
        return None, None
    return row["sampled_at"], row["metric_value"]


def markdown_table(headers: list[str], rows: list[list[str]]) -> str:
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join(["---"] * len(headers)) + " |"]
    lines += ["| " + " | ".join(row) + " |" for row in rows]
    return "\n".join(lines)


def make_report(args: argparse.Namespace) -> str:
    con = launch_ledger.open_readonly_db(args.db)
    con.row_factory = None
    # Re-open row factory through helper then set by name for dict conversions.
    con.close()
    con = launch_ledger.open_readonly_db(args.db)
    launch = resolve_launch(con, args.instance_id, args.launch_key)
    launch_key = launch["launch_key"]
    windows = fetch_windows(con, launch_key, args.since, args.until)
    active = active_windows(windows)

    running = [float(r.get("running") or 0) for r in active]
    waiting = [float(r.get("waiting") or 0) for r in active]
    kv = [float(r.get("kv_pct") or 0) for r in active]
    prompt_tps = [float(r.get("prompt_tps") or 0) for r in active]
    generation_tps = [float(r.get("generation_tps") or 0) for r in active]
    total_tps = [float(r.get("total_tps") or 0) for r in active]
    per_running_gen = [float(r.get("generation_tps") or 0) / float(r.get("running") or 0) for r in active if float(r.get("running") or 0) > 0]
    per_running_total = [float(r.get("total_tps") or 0) / float(r.get("running") or 0) for r in active if float(r.get("running") or 0) > 0]

    prompt_sum = sum(float(r.get("prompt_delta") or 0) for r in active)
    generation_sum = sum(float(r.get("generation_delta") or 0) for r in active)
    total_sum = sum(float(r.get("total_delta") or 0) for r in active)

    latest_at, latest_total_tps = latest_metric(con, launch_key, "vllm.total_tokens_per_second", args.since, args.until)

    title_model = args.workload_model or launch.get("served_model_name") or launch.get("model_profile_name") or "model"
    title_gpu = launch.get("gpu_name") or "GPU"
    lines: list[str] = []
    lines.append(args.report_title or f"# Launch Metrics Report: {title_model} on {title_gpu}")
    lines.append("")
    lines.append(f"Generated: `{now_utc()}`")
    if args.since or args.until:
        lines.append(f"Window: `{args.since or 'beginning'}` to `{args.until or 'latest'}`")
    else:
        lines.append("Window: `all recorded samples`")
    lines.append("")
    lines.append("> Publish-safety: public IPs, mapped ports, raw URLs, auth data, local artifact paths, and raw JSON details are intentionally omitted. Provider IDs are redacted by default.")
    lines.append("")

    provider_rows = [
        ["launch", "redacted" if not args.include_provider_ids else str(launch.get("launch_key"))],
        ["instance_id", "redacted" if not args.include_provider_ids else str(launch.get("instance_id"))],
        ["offer_id", "redacted" if not args.include_provider_ids else str(launch.get("offer_id"))],
        ["machine_id", "redacted" if not args.include_provider_ids else str(launch.get("machine_id"))],
    ]
    lines.append("## Launch metadata")
    lines.append("")
    rows = [
        ["workload model", str(args.workload_model or launch.get("served_model_name") or "n/a")],
        ["launch-profile model", str(launch.get("served_model_name") or "n/a")],
        ["launch-profile HF model", str(launch.get("hf_model_id") or "n/a")],
        ["model profile", str(launch.get("model_profile_name") or "n/a")],
        ["GPU profile", str(launch.get("gpu_profile_name") or "n/a")],
        ["launch profile", str(launch.get("launch_profile_name") or "n/a")],
        ["market", str(launch.get("market") or "n/a")],
        ["GPU", f"{launch.get('gpu_name') or 'n/a'} x{launch.get('num_gpus') or 'n/a'}"],
        ["GPU RAM", f"{fmt_int(launch.get('gpu_total_ram_mb'))} MB"],
        ["lifecycle", str(launch.get("lifecycle_status") or "n/a")],
        ["created_at", str(launch.get("created_at") or "n/a")],
        *provider_rows,
    ]
    lines.append(markdown_table(["Field", "Value"], rows))
    lines.append("")

    lines.append("## Cost and storage snapshot")
    lines.append("")
    cost_rows = [
        ["total hourly", fmt_money(launch.get("dph_total"))],
        ["compute hourly", fmt_money(launch.get("compute_cost_per_hour"))],
        ["storage hourly", fmt_money(launch.get("storage_total_cost_per_hour"))],
        ["requested disk", f"{fmt(launch.get('requested_disk_gb'), 0)} GB"],
        ["storage per requested GB-hour", fmt_money(launch.get("storage_cost_per_requested_gb_hour"))],
        ["storage share of total", pct((launch.get("storage_fraction_of_total") or 0) * 100)],
    ]
    lines.append(markdown_table(["Metric", "Value"], cost_rows))
    lines.append("")

    workload_config = getattr(args, "workload_config", None)
    if workload_config:
        lines.append("## Workload configuration")
        lines.append("")
        lines.append(markdown_table(["Field", "Value"], [[str(k), str(v)] for k, v in workload_config.items()]))
        lines.append("")

    lines.append("## Recorded sample coverage")
    lines.append("")
    lines.append(markdown_table(
        ["Metric", "Value"],
        [
            ["all interval windows", fmt_int(len(windows))],
            ["active interval windows", fmt_int(len(active))],
            ["first active sample", active[0]["sampled_at"] if active else "n/a"],
            ["last active sample", active[-1]["sampled_at"] if active else "n/a"],
            ["latest recorded total TPS sample", f"{latest_at or 'n/a'} / {fmt(latest_total_tps)}"],
        ],
    ))
    lines.append("")

    lines.append("## Throughput summary from interval samples")
    lines.append("")
    throughput_rows = [
        ["prompt tokens", fmt_int(prompt_sum)],
        ["generation tokens", fmt_int(generation_sum)],
        ["total tokens", fmt_int(total_sum)],
        ["prompt TPS avg / p95 / max", f"{fmt(avg(prompt_tps))} / {fmt(percentile(prompt_tps, 95))} / {fmt(max(prompt_tps) if prompt_tps else None)}"],
        ["generation TPS avg / p95 / max", f"{fmt(avg(generation_tps))} / {fmt(percentile(generation_tps, 95))} / {fmt(max(generation_tps) if generation_tps else None)}"],
        ["total TPS avg / p95 / max", f"{fmt(avg(total_tps))} / {fmt(percentile(total_tps, 95))} / {fmt(max(total_tps) if total_tps else None)}"],
        ["generation TPS per active request avg / p95 / max", f"{fmt(avg(per_running_gen))} / {fmt(percentile(per_running_gen, 95))} / {fmt(max(per_running_gen) if per_running_gen else None)}"],
        ["total TPS per active request avg / p95 / max", f"{fmt(avg(per_running_total))} / {fmt(percentile(per_running_total, 95))} / {fmt(max(per_running_total) if per_running_total else None)}"],
    ]
    lines.append(markdown_table(["Metric", "Value"], throughput_rows))
    lines.append("")

    lines.append("## Concurrency and cache gauges")
    lines.append("")
    gauge_rows = [
        ["running requests avg / p95 / max", f"{fmt(avg(running))} / {fmt(percentile(running, 95))} / {fmt(max(running) if running else None)}"],
        ["waiting requests avg / p95 / max", f"{fmt(avg(waiting))} / {fmt(percentile(waiting, 95))} / {fmt(max(waiting) if waiting else None)}"],
        ["KV cache usage avg / p95 / max", f"{pct(avg(kv))} / {pct(percentile(kv, 95))} / {pct(max(kv) if kv else None)}"],
    ]
    lines.append(markdown_table(["Gauge", "Value"], gauge_rows))
    lines.append("")

    lines.append("## Cumulative counter deltas in report window")
    lines.append("")
    counter_rows = []
    for metric in COUNTER_METRICS:
        delta, status = counter_delta(con, launch_key, metric, args.since, args.until)
        counter_rows.append([metric, fmt(delta), status])
    lines.append(markdown_table(["Counter", "Delta", "Status"], counter_rows))
    lines.append("")

    # Derived averages from counter deltas when available.
    def delta_for(name: str) -> float | None:
        value, status = counter_delta(con, launch_key, name, args.since, args.until)
        return value if status == "ok" else None

    ttft_count = delta_for("vllm.ttft_count")
    ttft_sum = delta_for("vllm.ttft_sum_seconds")
    infer_count = delta_for("vllm.inference_count")
    infer_sum = delta_for("vllm.inference_sum_seconds")
    queue_count = delta_for("vllm.queue_count")
    queue_sum = delta_for("vllm.queue_sum_seconds")
    lines.append("## Latency averages from counters")
    lines.append("")
    lines.append(markdown_table(
        ["Metric", "Average"],
        [
            ["TTFT", f"{fmt(ttft_sum / ttft_count if ttft_count and ttft_sum is not None else None)} s"],
            ["inference", f"{fmt(infer_sum / infer_count if infer_count and infer_sum is not None else None)} s"],
            ["queue", f"{fmt(queue_sum / queue_count if queue_count and queue_sum is not None else None)} s"],
        ],
    ))
    lines.append("")

    if active:
        lines.append("## Latest active windows")
        lines.append("")
        tail = active[-min(len(active), args.tail_windows):]
        rows = [
            [
                str(r["sampled_at"]),
                fmt(r.get("running"), 0),
                fmt(r.get("waiting"), 0),
                pct(r.get("kv_pct")),
                fmt_int(r.get("prompt_delta")),
                fmt_int(r.get("generation_delta")),
                fmt(r.get("total_tps")),
                fmt((float(r.get("generation_tps") or 0) / float(r.get("running") or 0)) if float(r.get("running") or 0) > 0 else None),
            ]
            for r in tail
        ]
        lines.append(markdown_table(["sampled_at", "running", "waiting", "KV", "prompt Δ", "gen Δ", "total TPS", "gen TPS/request"], rows))
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate publish-safe Markdown from launch metric samples")
    parser.add_argument("--db", type=Path, default=launch_ledger.DEFAULT_DB_PATH)
    parser.add_argument("--instance-id", type=int)
    parser.add_argument("--launch-key")
    parser.add_argument("--since", help="Inclusive UTC ISO timestamp, e.g. 2026-05-16T07:07:00Z")
    parser.add_argument("--until", help="Inclusive UTC ISO timestamp")
    parser.add_argument("--out", type=Path, help="Write report to this path instead of stdout")
    parser.add_argument("--include-provider-ids", action="store_true", help="Include instance/offer/machine IDs; off by default for publish-safe reports")
    parser.add_argument("--tail-windows", type=int, default=12)
    parser.add_argument("--workload-model", help="Override displayed workload model name when the served model differs from launch profile metadata")
    parser.add_argument("--report-title", help="Full Markdown H1 title override, including leading #")
    parser.add_argument("--workload-config-json", help="Optional JSON object rendered as a Workload configuration table")
    args = parser.parse_args()
    if args.workload_config_json:
        import json

        args.workload_config = json.loads(args.workload_config_json)
    else:
        args.workload_config = None

    report = make_report(args)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(report)
        print(f"wrote {args.out}")
    else:
        print(report, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
