"""
Context ladder bench — trustworthy prefill/decode TPS over growing context (standalone).

Generic progressive-context benchmark for LLM engines (vLLM and vLLM-compatible
serving stacks). Each round grows the prompt by a fixed repeated-string block
(`TOK ` x --tok-per-round) so the prefix cache absorbs the history, and appends a
fresh decode prompt (LeetCode-style solutions by default) so each round measures
real generation at that context length. Spec-decode acceptance is captured when
the engine exposes the counters (DFlash2/MTP); otherwise it is reported as null.

Reproduces the guarded counter-delta method that produced logs/DFLASH2-DECODE-CURVE.md.
No external deps (stdlib only). Requires a running vLLM endpoint exposing /metrics
with the vllm: engine counters.

Each round = ONE request wrapped in a six-gate checkpoint so the per-round delta is
provably owned by that single request:
    START idle      : vllm:num_requests_running == 0
    START settled   : two consecutive counter reads 250ms apart are identical
    END idle        : vllm:num_requests_running == 0
    END settled     : two consecutive counter reads identical
    gen integrity   : Δgeneration_tokens_total == usage.completion_tokens
    success integrity: Δrequest_success_total == 1
Any gate failure discards the round (reported as 'skip', never a poisoned number).

Output: JSON lines, one per round (flushed), plus a final {"done": true, "rounds_run": N}.

Usage:
    python3 context_ladder_bench.py [--base URL] [--model ID] [--n-sol N]
                                    [--min-tokens N] [--max-tokens N]
                                    [--rounds N] [--target-ctx N] [--tok-per-round N]
                                    [--out FILE]

Example (20k-step burnin against a 256k-ctx vLLM):
    python3 context_ladder_bench.py --base http://HOST:PORT --model qwen3.8-27b \
        --tok-per-round 20000 --target-ctx 262144 --out ladder-20k.jsonl
"""
import argparse, json, os, re, sys, time, urllib.request

DEFAULT_BASE  = "http://127.0.0.1:8095"
DEFAULT_MODEL = "qwen3.8-27b"

COUNTER_KEYS = [
    "vllm:generation_tokens_total",
    "vllm:request_decode_time_seconds_sum",
    "vllm:request_generation_tokens_sum",
    "vllm:spec_decode_num_accepted_tokens_total",
    "vllm:spec_decode_num_draft_tokens_total",
    "vllm:prompt_tokens_total",
    "vllm:request_prefill_kv_computed_tokens_sum",
    "vllm:request_prefill_time_seconds_sum",
]
GAUGE_KEYS = ["vllm:num_requests_running"]

DECODE_PROMPT_TEMPLATE = (
    "Generate exactly {n} complete, distinct, runnable LeetCode-style problem solutions. "
    "Output at least {min_tokens} tokens of code and explanation total. For each of the {n} "
    "solutions provide: (1) problem statement, (2) sample input/output, (3) complexity analysis, "
    "(4) a fully correct reference implementation in a real language, (5) a dry-run trace. "
    "Do NOT abbreviate or summarize. Make it long and thorough. Number each solution clearly. "
    "This is round {round}."
)

def fetch_metrics(base, timeout=30):
    raw = urllib.request.urlopen(base.rstrip("/") + "/metrics", timeout=timeout).read().decode()
    vals = {}
    for line in raw.splitlines():
        if not line or line.startswith("#"):
            continue
        if line.startswith("vllm:request_success_total{"):
            m = re.match(r'^vllm:request_success_total\{[^}]*finished_reason="(\w+)"[^}]*\}\s+([0-9.]+)', line)
            if m:
                vals.setdefault("request_success_total", {})[m.group(1)] = float(m.group(2))
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

def _snapshot(base):
    m = fetch_metrics(base)
    counters = {k: m[k] for k in COUNTER_KEYS if k in m}
    running  = m.get("vllm:num_requests_running", None)
    success  = m.get("request_success_total", {})
    return counters, running, success

def assert_idle(snap, label):
    counters, running, _ = snap
    if running != 0:
        raise RuntimeError(f"{label}: num_requests_running={running} (must be 0) — engine NOT idle")
    return counters

def settled_snapshot(base, label, settle=0.25, tries=3):
    last = None
    for i in range(tries):
        snap = _snapshot(base)
        c = assert_idle(snap, f"{label} (settle try {i})")
        if last is not None and c == last:
            return c, snap[2]
        last = c
        time.sleep(settle)
    raise RuntimeError(f"{label}: counters never settled after {tries} reads — engine busy or another writer")

def call_decode(base, model, messages, max_tokens=12000, timeout=1800, api_key=None):
    body = {"model": model, "messages": messages, "max_tokens": max_tokens,
            "temperature": 0.7, "top_p": 0.8, "top_k": 20, "min_p": 0.0, "stream": False}
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    req = urllib.request.Request(base.rstrip("/") + "/v1/chat/completions",
                                 data=json.dumps(body).encode(),
                                 headers=headers)
    t0 = time.time()
    payload = json.loads(urllib.request.urlopen(req, timeout=timeout).read().decode())
    wall = time.time() - t0
    u = payload.get("usage", {})
    return {"completion_tokens": u.get("completion_tokens", 0),
            "prompt_tokens": u.get("prompt_tokens", 0),
            "wall": wall}

def measured_round(base, model, system, user_content, rnd, max_tokens=12000, api_key=None):
    """Single request with BOTH prefill and generation windows measured independently.
    user_content should already include the TOK*n history + decode prompt."""
    c_start, s_start = settled_snapshot(base, f"r{rnd}.start")
    messages = [{"role": "system", "content": system}] + [{"role": "user", "content": user_content}]
    try:
        r = call_decode(base, model, messages, max_tokens=max_tokens, api_key=api_key)
    except Exception as e:
        return {"round": rnd, "skip": f"request failed: {repr(e)}"}
    c_end, s_end = settled_snapshot(base, f"r{rnd}.end")

    dgen = c_end["vllm:generation_tokens_total"] - c_start["vllm:generation_tokens_total"]
    dcompl = r["completion_tokens"]
    if abs(dgen - dcompl) > 1:
        return {"round": rnd, "skip": f"gen-delta {dgen} != completion {dcompl}"}
    dsucc = sum(s_end.values()) - sum(s_start.values())
    if dsucc != 1:
        return {"round": rnd, "skip": f"success-delta {dsucc} != 1"}

    dprompt    = c_end["vllm:prompt_tokens_total"] - c_start["vllm:prompt_tokens_total"]
    dprefill_kv = c_end["vllm:request_prefill_kv_computed_tokens_sum"] - c_start["vllm:request_prefill_kv_computed_tokens_sum"]
    dprefill_t = c_end["vllm:request_prefill_time_seconds_sum"] - c_start["vllm:request_prefill_time_seconds_sum"]
    prefill_tps = (dprefill_kv / dprefill_t) if dprefill_t > 0 else None

    ddecs = c_end["vllm:request_decode_time_seconds_sum"] - c_start["vllm:request_decode_time_seconds_sum"]
    decode_tps = (dgen / ddecs) if ddecs > 0 else None

    dacc = c_end["vllm:spec_decode_num_accepted_tokens_total"] - c_start["vllm:spec_decode_num_accepted_tokens_total"]
    ddrf = c_end["vllm:spec_decode_num_draft_tokens_total"] - c_start["vllm:spec_decode_num_draft_tokens_total"]

    return {
        "round": rnd, "ctx_exact": r["prompt_tokens"], "completion_tokens": dcompl,
        "wall_ms": int(r["wall"] * 1000),
        "prefill_prompt_tokens": int(dprompt),
        "prefill_kv_computed": int(dprefill_kv),
        "prefill_time_s": round(dprefill_t, 4) if dprefill_t else None,
        "prefill_tps": round(prefill_tps, 1) if prefill_tps else None,
        "decode_time_s": round(ddecs, 4) if ddecs else None,
        "decode_tps": round(decode_tps, 1) if decode_tps else None,
        "accepted": int(dacc), "drafted": int(ddrf),
        "acceptance": round(dacc / ddrf, 4) if ddrf else None,
    }

def run_ladder(base, model, n_solutions, min_tokens, max_tokens,
               tok_per_round, target_ctx, rounds, out, api_key=None):
    out_fh = open(out, "a") if out else sys.stdout

    nonce = f"anchor-{int(time.time())}"
    system = f"You are a coding challenge generator. Session nonce: {nonce}. Keep a running conversation."
    decode = DECODE_PROMPT_TEMPLATE.format(n=n_solutions, min_tokens=min_tokens, round="{round}")

    hist = ""
    results = []

    r0_user = decode.format(round=0)
    r0 = measured_round(base, model, system, r0_user, rnd="P0", max_tokens=max_tokens, api_key=api_key)
    results.append(r0)
    out_fh.write(json.dumps(r0) + "\n"); out_fh.flush()

    rnd = 1
    while rnd <= rounds:
        ctx_target = rnd * tok_per_round
        if ctx_target >= target_ctx:
            print(json.dumps({"done": True, "rounds_run": len(results),
                              "note": f"stopped: next target {ctx_target} >= target_ctx {target_ctx}",
                              "nonce": nonce}))
            break
        hist = hist + "TOK " * tok_per_round
        user = hist + decode.format(round=ctx_target)
        rr = measured_round(base, model, system, user, rnd=f"P{ctx_target}", max_tokens=max_tokens, api_key=api_key)
        results.append(rr)
        out_fh.write(json.dumps(rr) + "\n"); out_fh.flush()
        if rr.get("skip"):
            print(json.dumps({"done": True, "rounds_run": len(results),
                              "stopped": rr["skip"], "nonce": nonce}))
            break
        rnd += 1
        time.sleep(1)

    print(json.dumps({"done": True, "rounds_run": len(results), "nonce": nonce}))
    if out:
        out_fh.close()
    return results

def main():
    ap = argparse.ArgumentParser(description="Guarded context-ladder prefill/decode TPS bench for vLLM engines")
    ap.add_argument("--base", default=DEFAULT_BASE, help="vLLM base URL")
    ap.add_argument("--model", default=DEFAULT_MODEL, help="served model id")
    ap.add_argument("--n-sol", type=int, default=10, help="solutions per round")
    ap.add_argument("--min-tokens", type=int, default=10000, help="min tokens per round")
    ap.add_argument("--max-tokens", type=int, default=12000, help="max_tokens per request")
    ap.add_argument("--tok-per-round", type=int, default=25000, help="TOK history appended per round")
    ap.add_argument("--target-ctx", type=int, default=262144, help="max_model_len ceiling")
    ap.add_argument("--rounds", type=int, default=10, help="max ladder rounds")
    ap.add_argument("--out", default=None, help="append JSON lines to file (default stdout)")
    ap.add_argument("--api-key", default=os.environ.get("VLLM_API_KEY", ""),
                    help="API key for the endpoint (default: $VLLM_API_KEY)")
    args = ap.parse_args()

    run_ladder(args.base, args.model, args.n_sol, args.min_tokens, args.max_tokens,
               args.tok_per_round, args.target_ctx, args.rounds, args.out, api_key=args.api_key)

if __name__ == "__main__":
    main()
