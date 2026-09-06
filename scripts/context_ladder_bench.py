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

Modes:
    leetcode (default)  decode prompt = LeetCode-style code solutions (code TPS)
    prose   (--prose)   decode prompt = a ~10k-token prose-only dissertation on the
                        last 100 years in physics, no code/formulas/structure (text TPS)
    Both can run in one invocation, INTERLEAVED per context level:
        0k leetcode, 0k prose, 20k leetcode, 20k prose, 40k leetcode, 40k prose, ...
    Each request carries only its own "TOK " prefix + its own decode prompt — the
    prose request never sees the leetcode output. Prose rounds are tagged
    "mode": "prose"; leetcode rounds are untagged so a leetcode-only run's JSONL
    is byte-identical to before. The full prose text is saved next to the jsonl
    as <stem>.<round>.prose.txt.

Usage:
    python3 context_ladder_bench.py [--base URL] [--model ID] [--n-sol N]
                                    [--min-tokens N] [--max-tokens N]
                                    [--rounds N] [--target-ctx N] [--tok-per-round N]
                                    [--out FILE]
                                    [--prose] [--prose-min-tokens N] [--prose-max-tokens N]

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

PROSE_PROMPT_TEMPLATE = (
    "Think carefully about the last 100 years in physics, then write a long, continuous, "
    "prose-only dissertation on the subject — roughly {min_tokens} tokens (about "
    "{min_chars} characters) of flowing narrative paragraphs. Write as a physicist's essay: "
    "relativity, quantum mechanics, the Standard Model, cosmology, and the open questions. "
    "PROSE ONLY: no code, no formulas, no LaTeX, no bullet lists, no headings, no tables, "
    "no structured output of any kind — just plain connected paragraphs. Do not abbreviate "
    "or summarize; keep going until you have written the full dissertation. This is round {round}."
)

def prose_purity(text):
    """ROUGH purity check — deliberately not a precise detector (~95% bar).
    Returns (ok, reason). Penalizes fenced code blocks, heavy math-symbol lines,
    list/heading structure, and long all-caps token runs (code identifiers)."""
    n = len(text)
    if n == 0:
        return False, "empty text"
    bad = 0
    bad += len(re.findall(r"```", text)) // 2                      # fenced code blocks
    mathy = sum(1 for ln in text.splitlines()
                if sum(ch in "∑∏∫√∂∇≈≠≤≥αβγδεζηθλμνξπρσφωψΩ" for ch in ln) >= 3)
    bad += mathy                                                     # formula-like lines
    bad += len(re.findall(r"(?m)^\s*[-*]\s+", text))               # bullet lists
    bad += len(re.findall(r"(?m)^\s*#{1,6}\s", text))              # markdown headings
    caps = sum(1 for ln in text.splitlines()
               if len(re.findall(r"\b[A-Z_]{4,}\b", ln)) >= 3)     # code-identifier lines
    bad += caps
    if bad > max(1, n // 5000):                                      # >~0.02% of chars worth of hits
        return False, f"non-prose structure detected ({bad} hits)"
    return True, "ok"

def prose_finalize(base, model, system, user_content, rnd, max_tokens,
                   min_tokens, api_key, out_path, mode="prose"):
    """measured_round + prose-specific gates + save full text next to the jsonl."""
    rr = measured_round(base, model, system, user_content, rnd=rnd,
                        max_tokens=max_tokens, api_key=api_key, mode=mode)
    text = rr.pop("text", None)
    if rr.get("skip"):
        return rr
    if rr["completion_tokens"] < min_tokens:
        rr["skip"] = (f"prose gate: completion {rr['completion_tokens']} < "
                      f"min_tokens {min_tokens} (truncated?)")
        return rr
    ok, why = prose_purity(text or "")
    if not ok:
        rr["skip"] = f"prose gate: {why}"
        return rr
    rr["text_chars"] = len(text)
    if out_path:
        stem = os.path.splitext(os.path.basename(out_path))[0]
        with open(os.path.join(os.path.dirname(os.path.abspath(out_path)),
                               f"{stem}.{rnd}.prose.txt"), "w") as fh:
            fh.write(text)
    return rr

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

def call_decode(base, model, messages, max_tokens=12000, timeout=1800, api_key=None,
                capture_text=False):
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
    out = {"completion_tokens": u.get("completion_tokens", 0),
           "prompt_tokens": u.get("prompt_tokens", 0),
           "wall": wall}
    if capture_text:
        out["text"] = (payload.get("choices") or [{}])[0].get("message", {}).get("content", "")
    return out

def measured_round(base, model, system, user_content, rnd, max_tokens=12000, api_key=None,
                   mode=None):
    """Single request with BOTH prefill and generation windows measured independently.
    user_content should already include the TOK*n history + decode prompt.
    mode, when set (e.g. "prose"), is added to the round record; leetcode rounds
    pass mode=None and their records are unchanged."""
    c_start, s_start = settled_snapshot(base, f"r{rnd}.start")
    messages = [{"role": "system", "content": system}] + [{"role": "user", "content": user_content}]
    try:
        r = call_decode(base, model, messages, max_tokens=max_tokens, api_key=api_key,
                        capture_text=mode is not None)
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

    rec = {
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
    if mode:
        rec["mode"] = mode
    if "text" in r:
        rec["text"] = r["text"]
    return rec

def run_ladder(base, model, n_solutions, min_tokens, max_tokens,
               tok_per_round, target_ctx, rounds, out, api_key=None,
               prose=False, prose_min_tokens=10000, prose_max_tokens=12000):
    out_fh = open(out, "a") if out else sys.stdout

    nonce = f"anchor-{int(time.time())}"
    header = {"bench": "context-ladder-v1",
              "ts": time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()),
              "base": base, "model": model,
              "n_solutions": n_solutions,
              "max_tokens": max_tokens,
              "tok_per_round": tok_per_round,
              "target_ctx": target_ctx,
              "rounds": rounds, "nonce": nonce}
    if prose:
        header["prose"] = {"min_tokens": prose_min_tokens, "max_tokens": prose_max_tokens}
    if out:  # self-describing header so bench_markdown_report.py can fill metadata
        out_fh.write(json.dumps({"run_header": header}) + "\n")
        out_fh.flush()

    def emit(rec):
        out_fh.write(json.dumps(rec) + "\n"); out_fh.flush()

    results = []

    # ---- per-mode setup (leetcode always; prose optional) ----
    lc_system = f"You are a coding challenge generator. Session nonce: {nonce}. Keep a running conversation."
    lc_decode = DECODE_PROMPT_TEMPLATE.format(n=n_solutions, min_tokens=min_tokens, round="{round}")
    if prose:
        pr_system = (f"You are a physicist writing a long-form dissertation. "
                     f"Session nonce: {nonce}. Keep a running conversation.")
        pr_decode = PROSE_PROMPT_TEMPLATE.format(min_tokens=prose_min_tokens,
                                                 min_chars=prose_min_tokens * 4, round="{round}")

    # ---- ladder: INTERLEAVED per level — 0k lc, 0k prose, 20k lc, 20k prose, ...
    # Both requests of a level share the same TOK prefix; the prose request is a
    # separate request and never sees the leetcode output.
    hist = ""
    r0 = measured_round(base, model, lc_system, lc_decode.format(round=0), rnd="P0",
                        max_tokens=max_tokens, api_key=api_key)
    results.append(r0); emit(r0)
    if prose:
        r0p = prose_finalize(base, model, pr_system, pr_decode.format(round=0), rnd="P0",
                             max_tokens=prose_max_tokens, min_tokens=prose_min_tokens,
                             api_key=api_key, out_path=out)
        results.append(r0p); emit(r0p)

    rnd = 1
    while rnd <= rounds:
        ctx_target = rnd * tok_per_round
        if ctx_target >= target_ctx:
            print(json.dumps({"done": True, "rounds_run": len(results),
                              "note": f"stopped: next target {ctx_target} >= target_ctx {target_ctx}",
                              "nonce": nonce}))
            break
        hist = hist + "TOK " * tok_per_round
        rr = measured_round(base, model, lc_system, hist + lc_decode.format(round=ctx_target),
                            rnd=f"P{ctx_target}", max_tokens=max_tokens, api_key=api_key)
        results.append(rr); emit(rr)
        if rr.get("skip"):
            print(json.dumps({"done": True, "rounds_run": len(results),
                              "stopped": rr["skip"], "nonce": nonce}))
            break
        if prose:
            rp = prose_finalize(base, model, pr_system, hist + pr_decode.format(round=ctx_target),
                                rnd=f"P{ctx_target}", max_tokens=prose_max_tokens,
                                min_tokens=prose_min_tokens,
                                api_key=api_key, out_path=out)
            results.append(rp); emit(rp)
            if rp.get("skip"):
                print(json.dumps({"done": True, "rounds_run": len(results),
                                  "stopped": rp["skip"], "nonce": nonce}))
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
    ap.add_argument("--prose", action="store_true",
                    help="also run prose-dissertation rounds (text TPS), interleaved per level "
                         "with the leetcode rounds (0k lc, 0k prose, 20k lc, 20k prose, ...)")
    ap.add_argument("--prose-min-tokens", type=int, default=10000,
                    help="prose mode: minimum completion tokens per round (default 10000 ≈ 40000 chars)")
    ap.add_argument("--prose-max-tokens", type=int, default=12000,
                    help="prose mode: max_tokens per request (default 12000)")
    args = ap.parse_args()

    run_ladder(args.base, args.model, args.n_sol, args.min_tokens, args.max_tokens,
               args.tok_per_round, args.target_ctx, args.rounds, args.out, api_key=args.api_key,
               prose=args.prose, prose_min_tokens=args.prose_min_tokens,
               prose_max_tokens=args.prose_max_tokens)

if __name__ == "__main__":
    main()
