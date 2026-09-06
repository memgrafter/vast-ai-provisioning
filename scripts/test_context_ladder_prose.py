"""
test_context_ladder_prose.py — offline harness for context_ladder_bench.py (incl. prose mode).

Stdlib only. Stands up a fake vLLM endpoint (HTTP /metrics + /v1/chat/completions)
on 127.0.0.1 and drives the REAL bench code end-to-end:
  - leetcode-only run: byte-identical schema to the pre-prose bench (backward compat)
  - --prose run: leetcode ladder then prose ladder, prose gates enforced,
    prose text saved next to the jsonl
  - --prose run where the fake engine emits a 5-token prose answer: prose gate
    must skip (never poison a number), leetcode rounds untouched
  - bench_markdown_report.py renders the mixed-mode file (Mode column, prose band)

Usage:  python3 scripts/test_context_ladder_prose.py
Exit 0 = all pass.
"""
import json, os, re, shutil, subprocess, sys, tempfile, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
BENCH = os.path.join(HERE, "context_ladder_bench.py")
REPORT = os.path.join(HERE, "bench_markdown_report.py")
MODEL = "fake-27b"
PORT = 8791
BASE = f"http://127.0.0.1:{PORT}"

state = {"prose": False, "short": False, "n": 0}
counters = {"gen": 0.0, "dec": 0.0, "ptok": 0.0, "kv": 0.0, "pt": 0.0,
            "acc": 0.0, "drf": 0.0, "succ": 0.0}

def metrics_text():
    c = counters
    L = '{model_name="' + MODEL + '"}'
    return "\n".join([
        "# HELP vllm:generation_tokens_total x",
        f"vllm:generation_tokens_total{L} {c['gen']}",
        f"vllm:request_decode_time_seconds_sum{L} {c['dec']}",
        f"vllm:request_generation_tokens_sum{L} {c['gen']}",
        f"vllm:spec_decode_num_accepted_tokens_total{L} {c['acc']}",
        f"vllm:spec_decode_num_draft_tokens_total{L} {c['drf']}",
        f"vllm:prompt_tokens_total{L} {c['ptok']}",
        f"vllm:request_prefill_kv_computed_tokens_sum{L} {c['kv']}",
        f"vllm:request_prefill_time_seconds_sum{L} {c['pt']}",
        f'vllm:request_success_total{{model_name="{MODEL}",finished_reason="stop"}} {c["succ"]}',
        f"vllm:num_requests_running{L} 0",
        "",
    ])

class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass
    def _json(self, obj, code=200):
        b = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)
    def do_GET(self):
        if self.path == "/metrics":
            b = metrics_text().encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)
        else:
            self._json({"error": "not found"}, 404)
    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        req = json.loads(self.rfile.read(n) or b"{}")
        body = json.dumps(req.get("messages", []))
        is_prose = "dissertation" in body
        p = len(req.get("messages", [])) * 100 + 5
        comp = 100
        if is_prose:
            comp = 5 if state["short"] else 4500
        time.sleep(0.05)
        state["n"] += 1
        counters["gen"] += comp
        counters["dec"] += comp / 1000.0
        counters["ptok"] += p
        counters["kv"] += p
        counters["pt"] += 0.02
        counters["acc"] += comp
        counters["drf"] += comp
        counters["succ"] += 1
        text = ("PROSE-" + "x" * 2000) if (is_prose and not state["short"]) else "code"
        self._json({"id": "c", "object": "chat.completion", "model": MODEL,
                    "choices": [{"index": 0, "message": {"role": "assistant", "content": text},
                                 "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": p, "completion_tokens": comp,
                              "total_tokens": p + comp}})

def run_bench(extra, out):
    cmd = [sys.executable, BENCH, "--base", BASE, "--model", MODEL,
           "--tok-per-round", "1000", "--target-ctx", "3000", "--rounds", "2",
           "--out", out] + extra
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if r.returncode != 0:
        raise AssertionError(f"bench rc={r.returncode}\nSTDOUT:{r.stdout}\nSTDERR:{r.stderr}")
    return r.stdout

def load_jsonl(path):
    rows = [json.loads(l) for l in open(path) if l.strip()]
    return rows[0], [r for r in rows[1:] if "round" in r]

def main():
    tmp = tempfile.mkdtemp(prefix="ladder-prose-test-")
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        # ---- A: leetcode-only run (backward compat: no mode/prose keys anywhere) ----
        state.update(prose=False, short=False, n=0)
        a_out = os.path.join(tmp, "a.jsonl")
        run_bench([], a_out)
        a_h, a_r = load_jsonl(a_out)
        assert a_h.get("run_header"), "A: missing run_header"
        assert "prose" not in a_h["run_header"], f"A: header must not carry prose key: {a_h['run_header']}"
        assert len(a_r) == 3, f"A: expected P0 + 2 TOK rounds = 3, got {len(a_r)}"
        for r in a_r:
            assert "mode" not in r, f"A: leetcode-only round must not carry 'mode': {r}"
            assert "text" not in r, f"A: leetcode-only round must not carry 'text': {r}"
            for k in ("round", "ctx_exact", "decode_tps", "prefill_tps", "wall_ms", "acceptance"):
                assert k in r, f"A: round missing key {k}"
        print("A PASS  leetcode-only: schema byte-compatible (no mode/text/prose keys)")

        # ---- B: --prose run (leetcode ladder, then prose ladder; gates; text files) ----
        state.update(prose=False, short=False, n=0)
        b_out = os.path.join(tmp, "b.jsonl")
        run_bench(["--prose", "--prose-min-tokens", "4000", "--prose-max-tokens", "5000"], b_out)
        b_h, b_r = load_jsonl(b_out)
        assert b_h["run_header"].get("prose") == {"min_tokens": 4000, "max_tokens": 5000}, \
            f"B: header prose config wrong: {b_h['run_header'].get('prose')}"
        bl = [r for r in b_r if r.get("mode") != "prose"]
        bp = [r for r in b_r if r.get("mode") == "prose"]
        assert len(bl) == 3 and len(bp) == 3, f"B: expected 3 leetcode + 3 prose rounds: {len(bl)}/{len(bp)}"
        for r in bp:
            assert r["completion_tokens"] >= 4000, f"B: prose round below token floor: {r}"
            assert r.get("text_chars", 0) >= 2000, f"B: prose round missing text_chars: {r}"
            assert "text" not in r, f"B: full text must NOT be inlined in jsonl: {list(r)}"
        for r in bl:
            assert "text" not in r, "B: leetcode round must not carry text"
        # prose text files saved next to the jsonl
        txts = [f for f in os.listdir(tmp) if f.startswith("b.") and f.endswith(".txt")]
        assert len(txts) == 3, f"B: expected 3 prose text files, got {txts}"
        assert open(os.path.join(tmp, txts[0])).read().startswith("PROSE-"), "B: prose text file content"
        print(f"B PASS  --prose: 2 leetcode + 2 prose rounds, gates ok, text files {sorted(txts)}")

        # ---- C: --prose run where engine emits a 5-token prose answer -> gate skips ----
        state.update(prose=True, short=True, n=0)
        c_out = os.path.join(tmp, "c.jsonl")
        run_bench(["--prose", "--prose-min-tokens", "4000", "--prose-max-tokens", "5000"], c_out)
        c_h, c_r = load_jsonl(c_out)
        cl = [r for r in c_r if r.get("mode") != "prose"]
        cp = [r for r in c_r if r.get("mode") == "prose"]
        assert len(cl) == 3, f"C: leetcode rounds must be intact: {len(cl)}"
        assert len(cp) == 2 and all(r.get("skip") for r in cp), f"C: expected 2 skipped prose rounds (P0+P1000, loop breaks on 2nd): {cp}"
        assert "prose gate" in cp[0]["skip"], f"C: skip reason: {cp[0]['skip']}"
        print(f"C PASS  short prose answer skipped by gate: {cp[0]['skip'][:60]!r}")

        # ---- D: report renders the mixed-mode file ----
        md = os.path.join(tmp, "report.md")
        rd = subprocess.run([sys.executable, REPORT, "--ladder", b_out, "--out", md,
                             "--title", "t"], capture_output=True, text=True, timeout=120)
        assert rd.returncode == 0, f"D: report rc={rd.returncode}\n{rd.stderr}"
        m = open(md).read()
        assert "| mode |" in m, "D: report table must have a mode column"
        assert re.search(r"\| P1k \(\d+\) \| prose \|", m), f"D: prose row missing in table:\n{m[:1500]}"
        assert "Prose decode band" in m, "D: prose decode band row missing"
        assert "Text-generation quality component: **not run**" in m, "D: textgen section must stay 'not run'"
        print("D PASS  report renders mixed-mode file (Mode column, prose band, textgen section intact)")
    finally:
        srv.shutdown()
        shutil.rmtree(tmp, ignore_errors=True)
    print("ALL PASS")

if __name__ == "__main__":
    main()
