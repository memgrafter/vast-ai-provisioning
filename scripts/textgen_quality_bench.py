"""
Text-generation quality component — long-form prose generation vs a vLLM endpoint.

Companion to context_ladder_bench.py. The ladder measures prefill/decode TPS over a
growing-context ladder; this component measures long-form TEXT generation quality and
throughput with a fixed prompt:

    "Write a report on the last 100 years in physics. No calculations and text only format."

Hard gates (all must pass for PASS):
    min_tokens : usage.completion_tokens >= --min-tokens   (default 2000)
    min_chars  : len(text)                        >= --min-chars  (default 8000)
    finished   : finish_reason == "stop" (not truncated by max_tokens)
Soft check (reported, not gating):
    math_lines : lines that look like calculations/equations (pattern count + samples)

Decode TPS is taken from the engine's /metrics counter delta (same guarded
single-request ownership method as the ladder) when the counters are available,
falling back to wall-clock otherwise.

Stdlib only. Output: one JSON object to --out (or stdout). When --out points at a
file named *.json, a sibling *.md with the plain generated text is written too.

Usage:
    python3 textgen_quality_bench.py --base http://HOST:PORT --model qwen3.8-27b \\
        --min-tokens 2000 --min-chars 8000 --out logs/textgen-<ts>.json
"""
import argparse, json, os, re, sys, time, urllib.request

DEFAULT_BASE  = "http://127.0.0.1:8095"
DEFAULT_MODEL = "qwen3.8-27b"

SYSTEM_PROMPT = "You are a science historian writing for an educated general audience."
USER_PROMPT = (
    "Write a report on the last 100 years in physics. No calculations and text only "
    "format. Organize it chronologically by era with markdown section headings, and "
    "cover the major developments and discoveries of each era in plain prose. "
    "The report must be at least 2000 words long. Do not use equations, formulas, "
    "numbers-heavy derivations, bullet lists, or code blocks — flowing prose only."
)

MATH_LINE_RE = re.compile(
    r"""
    \$[^$]+\$                                  # $...$ latex
    | \\(frac|int|sum|sqrt|pi|alpha|beta)      # bare latex commands
    | ^\s*[\w().^~]+\s*=\s*[\w().^~+\-/*^]     # "E = mc2", "a = b/c"
    | [0-9]+\s*[-+*/=]\s*[0-9]+                # numeric arithmetic
    """,
    re.MULTILINE | re.VERBOSE,
)

COUNTER_KEYS = [
    "vllm:generation_tokens_total",
    "vllm:request_decode_time_seconds_sum",
    "vllm:spec_decode_num_accepted_tokens_total",
    "vllm:spec_decode_num_draft_tokens_total",
]
GAUGE_KEYS = ["vllm:num_requests_running"]


def fetch_metrics(base, timeout=30):
    raw = urllib.request.urlopen(base.rstrip("/") + "/metrics", timeout=timeout).read().decode()
    vals = {}
    for line in raw.splitlines():
        if not line or line.startswith("#"):
            continue
        name = line.split("{", 1)[0]
        if name in COUNTER_KEYS:
            m = re.search(r'\}\s+([0-9.eE+\-]+)\s*$', line)
            if m:
                vals[name] = float(m.group(1))
        elif name in GAUGE_KEYS:
            m = re.search(r'\{\S+\}\s+([0-9.eE+\-]+)\s*$', line)
            if m:
                vals[name] = float(m.group(1))
    return vals


def settled_snapshot(base, settle=0.25, tries=3):
    last = None
    for _ in range(tries):
        m = fetch_metrics(base)
        snap = {k: m[k] for k in COUNTER_KEYS if k in m}
        running = m.get("vllm:num_requests_running")
        if running == 0 and last is not None and snap == last:
            return snap
        last = snap
        time.sleep(settle)
    raise RuntimeError("counters never settled — engine busy or another writer")


def call_generate(base, model, system, user, max_tokens, timeout, api_key):
    body = {"model": model,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": user}],
            "max_tokens": max_tokens, "temperature": 0.7,
            "top_p": 0.8, "top_k": 20, "min_p": 0.0, "stream": False}
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    req = urllib.request.Request(base.rstrip("/") + "/v1/chat/completions",
                                 data=json.dumps(body).encode(), headers=headers)
    t0 = time.time()
    payload = json.loads(urllib.request.urlopen(req, timeout=timeout).read().decode())
    wall = time.time() - t0
    return payload, wall


def run(args):
    ts = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    label = args.label
    out = {
        "component": "textgen-quality-v1",
        "label": label,
        "timestamp_utc": ts,
        "base": args.base,
        "model": args.model,
        "prompt_system": args.prompt_system,
        "prompt_user": args.prompt_user,
        "params": {"max_tokens": args.max_tokens, "temperature": 0.7,
                   "top_p": 0.8, "top_k": 20, "min_p": 0.0},
    }
    try:
        before = settled_snapshot(args.base)
    except Exception as e:
        print(json.dumps({"component": "textgen-quality-v1", "skip": f"metrics: {e!r}"}))
        return 1

    payload, wall = call_generate(args.base, args.model, args.prompt_system,
                                  args.prompt_user, args.max_tokens, args.timeout,
                                  args.api_key)
    after = settled_snapshot(args.base)

    msg = payload["choices"][0]
    text = msg.get("message", {}).get("content") or ""
    finish = msg.get("finish_reason")
    usage = payload.get("usage", {})
    comp = usage.get("completion_tokens", 0)
    prompt_toks = usage.get("prompt_tokens", 0)

    dgen = after.get("vllm:generation_tokens_total", 0) - before.get("vllm:generation_tokens_total", 0)
    ddec = after.get("vllm:request_decode_time_seconds_sum", 0) - before.get("vllm:request_decode_time_seconds_sum", 0)
    dacc = after.get("vllm:spec_decode_num_accepted_tokens_total", 0) - before.get("vllm:spec_decode_num_accepted_tokens_total", 0)
    ddrf = after.get("vllm:spec_decode_num_draft_tokens_total", 0) - before.get("vllm:spec_decode_num_draft_tokens_total", 0)

    math_hits = MATH_LINE_RE.findall(text)
    math_lines = [ln for ln in text.splitlines() if MATH_LINE_RE.search(ln)]

    gates = {
        "min_tokens": {"pass": comp >= args.min_tokens, "need": args.min_tokens, "got": comp},
        "min_chars": {"pass": len(text) >= args.min_chars, "need": args.min_chars, "got": len(text)},
        "finished": {"pass": finish == "stop", "need": "stop", "got": finish},
    }
    all_pass = all(g["pass"] for g in gates.values())

    out.update({
        "usage": {"prompt_tokens": prompt_toks, "completion_tokens": comp},
        "text_chars": len(text),
        "wall_s": round(wall, 3),
        "decode_time_s": round(ddec, 4) if ddec > 0 else None,
        "decode_tps": round(dgen / ddec, 1) if ddec > 0 else None,
        "accepted": int(dacc) if dacc else None,
        "drafted": int(ddrf) if ddrf else None,
        "acceptance": round(dacc / ddrf, 4) if ddrf else None,
        "math_line_count": len(math_lines),
        "math_line_samples": math_lines[:5],
        "gates": gates,
        "all_gates_pass": all_pass,
        "verdict": "PASS" if all_pass else "FAIL",
        "text": text,
    })
    print(json.dumps(out))
    if args.out:
        with open(args.out, "w") as fh:
            json.dump(out, fh, indent=2)
        if args.out.endswith(".json"):
            md = args.out[:-5] + ".md"
            with open(md, "w") as fh:
                fh.write(f"# Text generation sample — {label}\n\n")
                fh.write(f"_run {ts} · model {args.model} · {comp} tokens · {len(text)} chars · verdict {out['verdict']}_\n\n")
                fh.write(text + "\n")
            print(f"[textgen] wrote {md}", file=sys.stderr)
    return 0


def main():
    ap = argparse.ArgumentParser(description="Long-form textgen quality/throughput component for vLLM engines")
    ap.add_argument("--base", default=DEFAULT_BASE, help="vLLM base URL")
    ap.add_argument("--model", default=DEFAULT_MODEL, help="served model id")
    ap.add_argument("--label", default="physics-report-100y", help="report label")
    ap.add_argument("--prompt-system", default=SYSTEM_PROMPT)
    ap.add_argument("--prompt-user", default=USER_PROMPT)
    ap.add_argument("--min-tokens", type=int, default=2000, help="gate: min completion tokens")
    ap.add_argument("--min-chars", type=int, default=8000, help="gate: min text characters")
    ap.add_argument("--max-tokens", type=int, default=8192, help="max_tokens for the request")
    ap.add_argument("--timeout", type=int, default=1800, help="request timeout s")
    ap.add_argument("--out", default=None, help="write JSON result to file")
    ap.add_argument("--api-key", default=os.environ.get("VLLM_API_KEY", ""))
    args = ap.parse_args()
    sys.exit(run(args))


if __name__ == "__main__":
    main()
