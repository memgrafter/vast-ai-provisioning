"""
bench_markdown_report.py — render a Markdown benchmark report for one ladder run.

Companion to context_ladder_bench.py / textgen_quality_bench.py. Reads a ladder
JSONL (one guarded round per line), optionally a textgen-quality JSON, plus run
metadata flags, and writes a Markdown report next to the ladder file:

    logs/bench-report-<ladder-stem>-<ts>.md

Format (v1):
    # Benchmark Report — <title>
    | run metadata table |
    ## TL;DR            (auto-computed bullets)
    ## 1. Ladder        (prefill/decode table + footnotes)
    ## 2. Headline numbers
    ## 3. Text generation (quality component table, or "not run")
    ## 4. Verdict        (prose via --verdict, or "—")
    ## 5. Method & caveats

The ladder file may begin with a {"run_header": {...}} line (written by newer
context_ladder_bench.py versions); it is used for metadata when present.

Stdlib only.

Usage:
    python3 bench_markdown_report.py \
        --ladder logs/window-bench-nvfp4-256k-20260904T035836Z.jsonl \
        [--textgen logs/textgen-....json] \
        --title "Qwen3.8-27B NVFP4 + fp8 KV · 1× RTX PRO 6000 WS" \
        --meta instance="49819168 (Vast.ai, on-demand, $1.23/hr)" \
        --meta hardware="1× NVIDIA RTX PRO 6000 WS — sm_120, 96 GB, 420 W" \
        --meta engine="vLLM 0.27.1" \
        --meta checkpoint="RadixArk/Qwen3.8-27B-NVFP4" \
        --meta serving="bfloat16 · KV fp8_e4m3 · 262144 ctx" \
        --meta spec="DFlash2 W4A16 drafter, n=7" \
        --verdict "..." \
        [--out FILE.md]
"""
import argparse, json, os, re, sys, time

META_LABELS = [
    ("instance", "Instance"), ("hardware", "Hardware"), ("engine", "Engine"),
    ("checkpoint", "Checkpoint"), ("serving", "Serving"), ("spec", "Spec decode"),
    ("ladder", "Ladder"), ("vram", "VRAM / GPU"), ("kv_pool", "KV pool"),
    ("box_cost", "Box cost"),
]


def parse_ts(s):
    m = re.search(r"(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})Z", s)
    return f"{m.group(1)}-{m.group(2)}-{m.group(3)} {m.group(4)}:{m.group(5)}" if m else None


def load_ladder(path):
    header, rounds, skips = None, [], []
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            if "run_header" in d:
                header = d["run_header"]
            elif "round" in d and "skip" in d:
                skips.append(d)
            elif "round" in d:
                rounds.append(d)
    return header, rounds, skips


def fmt_k(ctx):
    return f"{ctx // 1000}k"


def round_label(r):
    return f"{pretty_round(r['round'])} ({r['ctx_exact']:,})" if r.get("ctx_exact") else pretty_round(r["round"])


def decode_stats(rounds, mode=None):
    # missing mode == leetcode (backward-compat records carry no mode key)
    rs = [r for r in rounds if mode is None or (r.get("mode") or "leetcode") == mode]
    ds = [r["decode_tps"] for r in rs if r.get("decode_tps")]
    return (min(ds), max(ds)) if ds else (None, None)


def prefill_stats(rounds):
    ps = [(r["prefill_tps"], r) for r in rounds if r.get("prefill_tps") and r.get("ctx_exact", 0) >= 1000]
    return max(ps, key=lambda x: x[0]) if ps else None, max(ps, key=lambda x: x[1]["ctx_exact"]) if ps else None


def pretty_round(s):
    m = re.match(r"^P(\d+)$", s or "")
    return f"P{int(m.group(1)) // 1000}k" if m else s


def acceptance_stats(rounds):
    as_ = [r["acceptance"] for r in rounds if r.get("acceptance")]
    return (min(as_), max(as_)) if as_ else (None, None)


def build_ladder_table(rounds, skips):
    mixed = any(r.get("mode") for r in rounds) or any(s.get("mode") for s in skips)
    lines = [
        "| ctx | mode | prefill tok/s* | decode tok/s | DFlash2 accept | round wall (s) |" if mixed
        else "| ctx | prefill tok/s* | decode tok/s | DFlash2 accept | round wall (s) |",
        "|---|---|---:|---:|---:|---:|" if mixed else "|---|---:|---:|---:|---:|",
    ]
    for r in rounds:
        pre = r.get("prefill_tps")
        ctx = r.get("ctx_exact", 0)
        pre_s = f"{pre:,.0f}" + (" †" if ctx < 1000 else "") if pre is not None else "—"
        dec = f"{r['decode_tps']:.1f}" if r.get("decode_tps") else "—"
        acc = f"{r['acceptance']:.3f}" if r.get("acceptance") is not None else "—"
        wall = f"{r.get('wall_ms', 0) / 1000:.1f}"
        if mixed:
            lines.append(f"| {round_label(r)} | {r.get('mode', 'leetcode')} | {pre_s} | {dec} | {acc} | {wall} |")
        else:
            lines.append(f"| {round_label(r)} | {pre_s} | {dec} | {acc} | {wall} |")
    for s in skips:
        label = f"| {pretty_round(s['round'])} | {s.get('mode', 'leetcode')} | — | skipped | — | — |" if mixed \
            else f"| {pretty_round(s['round'])} | — | skipped | — | — |"
        lines.append(label)
    return "\n".join(lines)


def build_tldr(rounds, textgen):
    dmin, dmax = decode_stats(rounds, mode=None if not any(r.get("mode") for r in rounds) else "leetcode")
    if dmin is None:
        return ["- No decode data."], {"dmin": None, "dmax": None}
    pmax, plast = prefill_stats(rounds)
    a_min, a_max = acceptance_stats(rounds)
    last = [r for r in rounds if r.get("mode") != "prose"][-1]
    bullets = []
    flat = dmin / dmax >= 0.8 if dmax else False
    band = f"{dmin:.0f}–{dmax:.0f}"
    note = " — **flat, no decay**" if flat else ""
    bullets.append(f"- **Decode {band} tok/s** across P0 → P{fmt_k(last.get('ctx_exact', 0))}{note} "
                   f"(P{fmt_k(last.get('ctx_exact', 0))} holds {last['decode_tps'] / dmax * 100:.0f}% of peak)")
    pmin, pmax2 = decode_stats(rounds, mode="prose")
    if pmin is not None:
        bullets.append(f"- **Prose decode {pmin:.0f}–{pmax2:.0f} tok/s** (dissertation rounds, same ladder)")
    if pmax:
        pmax_v, pmax_r = pmax
        plast_v, plast_r = plast
        bullets.append(f"- **Marginal prefill: {pmax_v:,.0f} tok/s** @P{fmt_k(pmax_r['ctx_exact'])} block "
                       f"→ {plast_v:,.0f} @P{fmt_k(plast_r['ctx_exact'])}")
    if a_min is not None:
        bullets.append(f"- DFlash2 acceptance {a_min:.2f}–{a_max:.2f}")
    if textgen:
        if textgen.get("all_gates_pass"):
            g = textgen["gates"]
            bullets.append(f"- Text-generation quality component: **PASS** — {g['min_chars']['got']:,} visible chars, "
                          f"natural stop, {textgen.get('math_line_count', '?')} calculation lines, "
                          f"{textgen.get('decode_tps', '?')} tok/s decode")
        elif textgen.get("verdict"):
            failed = [k for k, v in textgen.get("gates", {}).items() if not v.get("pass")]
            bullets.append(f"- Text-generation quality component: **FAIL** ({', '.join(failed) or textgen.get('verdict')})")
        else:
            bullets.append("- Text-generation quality component: **not run**")
    else:
        bullets.append("- Text-generation quality component: **not run**")
    return bullets, {"dmin": dmin, "dmax": dmax}


def build_headline(rounds, stats):
    dmin, dmax = stats["dmin"], stats["dmax"]
    pmax, plast = prefill_stats(rounds)
    last = [r for r in rounds if r.get("mode") != "prose"][-1]
    dec_rounds = [r for r in rounds if r.get("decode_tps") and r.get("mode") != "prose"]
    floor = min(dec_rounds, key=lambda r: r["decode_tps"])
    rows = [
        ("Peak decode (P0)", f"{rounds[0]['decode_tps']:.1f} tok/s" if rounds[0].get("decode_tps") else "—"),
        ("Decode @ last ctx (P{})".format(fmt_k(last.get("ctx_exact", 0))),
         f"{last['decode_tps']:.1f} tok/s ({last['decode_tps'] / dmax * 100:.1f}% of peak)" if last.get("decode_tps") else "—"),
        ("Decode floor (P{})".format(fmt_k(floor["ctx_exact"])),
         f"{dmin:.1f} tok/s ({dmin / dmax * 100:.1f}% of peak)"),
        ("Decode band", f"{dmin:.0f}–{dmax:.0f} tok/s" + (" (flat)" if dmin / dmax >= 0.8 else "")),
    ]
    pmin, pmax2 = decode_stats(rounds, mode="prose")
    if pmin is not None:
        rows.append(("Prose decode band", f"{pmin:.0f}–{pmax2:.0f} tok/s (dissertation rounds)"))
    if pmax:
        rows.append(("Peak marginal prefill", f"{pmax[0]:,.0f} tok/s @P{fmt_k(pmax[1]['ctx_exact'])}"))
    if plast:
        rows.append(("Prefill @ last ctx (marginal)", f"{plast[0]:,.0f} tok/s"))
    lines = ["| Metric | Value |", "|---|---:|"]
    lines += [f"| {k} | {v} |" for k, v in rows]
    return "\n".join(lines)


def build_textgen(textgen, ladder_dir):
    if not textgen:
        return ("Not run — the ladder was recorded without the text-generation quality component. "
                "Component: fixed prompt (\"Write a report on the last 100 years in physics. No calculations "
                "and text only format.\"), gates ≥2,000 tokens / ≥8,000 visible chars / natural stop.")
    g = textgen.get("gates", {})
    lines = []
    if textgen.get("prompt_user"):
        lines.append(f"Fixed prompt: *\"{textgen['prompt_user'].splitlines()[0]} …\"* "
                     f"(params: {json.dumps(textgen.get('params', {}))})")
    stem = os.path.splitext(os.path.basename(textgen.get("_path", "textgen")))[0]
    md_path = os.path.join(ladder_dir, stem + ".md")
    if os.path.exists(md_path):
        lines.append(f"Sample: [`{stem}.md`]({stem}.md)")
    lines.append("")
    lines.append("| Gate | Need | Got | Pass |")
    lines.append("|---|---:|---:|:-:|")
    for name in ("min_tokens", "min_chars", "finished"):
        if name in g:
            mark = "✅" if g[name]["pass"] else "❌"
            lines.append(f"| {name.replace('_', ' ')} | {g[name]['need']} | {g[name]['got']} | {mark} |")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|---|---:|")
    lines.append(f"| Decode speed (this sample) | {textgen.get('decode_tps', '—')} tok/s |")
    if textgen.get("acceptance") is not None:
        lines.append(f"| DFlash2 acceptance | {textgen['acceptance']} (prose drafts less than code) |")
    lines.append(f"| Calculation lines detected | {textgen.get('math_line_count', '—')} |")
    lines.append(f"| Wall time | {textgen.get('wall_s', '—')} s |")
    return "\n".join(lines)


def render_report(ladder_path, out_path=None, title=None, meta=None, verdict=None, textgen=None):
    """Render a markdown report from a ladder jsonl. Callable from other modules.
    
    Args:
        ladder_path: Path to the ladder jsonl file
        out_path: Output markdown path (default: bench-report-<stem>-<ts>.md next to ladder)
        title: Report title (default: ladder file stem)
        meta: Dict of metadata {"key": "value", ...}
        verdict: Prose verdict text for §4
        textgen: Dict from textgen quality json (optional)
    """
    meta = meta or {}
    stem = os.path.splitext(os.path.basename(ladder_path))[0]
    ladder_dir = os.path.dirname(os.path.abspath(ladder_path))
    header, rounds, skips = load_ladder(ladder_path)
    if not rounds:
        return False  # no data to render
    
    date = meta.get("date") or parse_ts(stem)
    tldr_bullets, stats = build_tldr(rounds, textgen)
    ts = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    out_path = out_path or os.path.join(ladder_dir, f"bench-report-{stem}-{ts}.md")
    title = title or stem
    
    meta_rows = [("Run ID", f"`{stem}`")]
    if date:
        meta_rows.append(("Date (UTC)", date))
    for key, label in META_LABELS:
        if meta.get(key):
            meta_rows.append((label, meta[key]))
    have = {k for k, _ in meta_rows}
    if header and "Ladder" not in have:
        tpr, mt = header.get("tok_per_round"), header.get("max_tokens")
        if tpr:
            meta_rows.append(("Ladder", f"{tpr // 1000}k-step × {mt}-token rounds, c=1"))
    meta_table = "| | |\n|---|---|\n" + "\n".join(f"| **{k}** | {v} |" for k, v in meta_rows)
    
    caveats = [
        "- **Guarded counter-delta.** Each round is one request bracketed by six gates: engine idle at start, "
        "two settled counter reads 250 ms apart, idle at end, two settled reads, "
        "Δgeneration_tokens == usage.completion_tokens, Δrequest_success == 1. Skips are discarded, never counted.",
        "- **Prefill is marginal, not full-context.** Prefix caching absorbs earlier ladder blocks; "
        "only rows where `prefill_kv_computed` ≈ full context measure whole-context prefill.",
        "- **Single stream (c=1).** Per-request numbers, not batched throughput.",
        "- **DFlash2 counts include drafts**: decode tok/s = completion tokens / engine decode time.",
    ]
    if any(r.get("mode") == "prose" for r in rounds):
        caveats.append("- **Prose rounds** (`mode: prose`) run the SAME ladder shape on a fresh TOK history "
                       "after the leetcode ladder: ~10k-token physics dissertation, prose only. "
                       "They measure TEXT decode TPS, which differs from code TPS; full texts are saved "
                       "as `<stem>.<round>.prose.txt` next to the jsonl.")
    if skips:
        caveats.append("- Skipped rounds: " + "; ".join(f"{pretty_round(s['round'])} ({s['skip'][:80]})" for s in skips))
    
    today = time.strftime("%Y-%m-%d")
    parts = [
        f"# Benchmark Report — {title}",
        "",
        meta_table,
        "",
        "## TL;DR",
        "",
        "\n".join(tldr_bullets),
        "",
        "## 1. Ladder — prefill / decode by context",
        "",
        "Each round appends a fixed-size block so the prefix cache absorbs all prior history; prefill therefore "
        "measures only the **marginal new block**, and decode measures one full generation at that exact context.",
        "",
        build_ladder_table(rounds, skips),
        "",
        "\\* Marginal new-block prefill only (prefix cache absorbs earlier context).  "
        "† P0 prefill covers a <1k-token warmup prompt — warmup artifact, not a prefill measurement.",
        "",
        "## 2. Headline numbers",
        "",
        build_headline(rounds, stats),
        "",
        "## 3. Text generation (quality component)",
        "",
        build_textgen(textgen, ladder_dir),
        "",
        "## 4. Verdict",
        "",
        verdict.strip() if verdict else "—",
        "",
        "## 5. Method & caveats",
        "",
        "\n".join(caveats),
        "",
        f"*Generated by bench_markdown_report.py on {today}. Source: `{os.path.basename(ladder_path)}`"
        + (f" + `{os.path.basename(textgen['_path'])}`" if textgen else "") + ".",
        "",
    ]
    with open(out_path, "w") as fh:
        fh.write("\n".join(parts))
    return True


def main():
    ap = argparse.ArgumentParser(description="Render a Markdown benchmark report for one ladder run")
    ap.add_argument("--ladder", required=True, help="ladder JSONL from context_ladder_bench.py")
    ap.add_argument("--textgen", default=None, help="textgen quality JSON (optional)")
    ap.add_argument("--title", default=None, help="H1 title (default: run stem)")
    ap.add_argument("--meta", action="append", default=[], metavar="KEY=VALUE",
                    help=f"metadata row, repeatable. keys: {', '.join(k for k, _ in META_LABELS)}")
    ap.add_argument("--verdict", default=None, help="prose verdict paragraph (§4)")
    ap.add_argument("--out", default=None, help="output .md (default: bench-report-<stem>-<ts>.md next to the ladder)")
    args = ap.parse_args()

    meta = {}
    for item in args.meta:
        k, _, v = item.partition("=")
        meta[k.strip()] = v.strip()

    textgen = None
    if args.textgen:
        with open(args.textgen) as fh:
            textgen = json.load(fh)
        textgen["_path"] = os.path.abspath(args.textgen)

    if render_report(args.ladder, args.out, args.title, meta, args.verdict, textgen):
        stem = os.path.splitext(os.path.basename(args.ladder))[0]
        ladder_dir = os.path.dirname(os.path.abspath(args.ladder))
        _, rounds, skips = load_ladder(args.ladder)
        ts = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
        out_path = args.out or os.path.join(ladder_dir, f"bench-report-{stem}-{ts}.md")
        print(f"[bench-report] wrote {out_path} ({len(rounds)} rounds, {len(skips)} skips)")
        return 0
    else:
        print(f"[bench-report] no valid rounds in {args.ladder}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
