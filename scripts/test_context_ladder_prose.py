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
        if state.get("fail_first") and state["n"] == 0:
            self._json({"error": "simulated engine failure"}, 500)
            state["n"] += 1
            return
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
        order = ["prose" if r.get("mode") == "prose" else "leetcode" for r in b_r]
        assert order == ["leetcode", "prose"] * 3, f"B: rounds must interleave per level: {order}"
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
        assert len(cl) == 3, f"C: all 3 leetcode rounds run (prose skips must not stop the ladder): {len(cl)}"
        assert len(cp) == 3 and all(r.get("skip") for r in cp), \
            f"C: all 3 prose rounds gate-skipped but ladder continues: {len(cp)}"
        assert all("prose gate" in r["skip"] for r in cp), f"C: skip reasons: {[r['skip'] for r in cp]}"
        print(f"C PASS  short prose answer skipped by gate: {cp[0]['skip'][:60]!r}")

        # ---- E: leetcode P0 failure stops the run (P0 is not special anymore) ----
        state.update(prose=False, short=False, n=0, fail_first=True)
        e_out = os.path.join(tmp, "e.jsonl")
        run_bench([], e_out)
        e_h, e_r = load_jsonl(e_out)
        assert len(e_r) == 1 and e_r[0].get("skip"), f"E: run must stop at failed P0: {e_r}"
        assert "request failed" in e_r[0]["skip"], f"E: skip reason: {e_r[0]['skip']}"
        state["fail_first"] = False
        print("E PASS  leetcode P0 failure stops the run")

        # ---- F: --start-ctx resume skips P0 and lower levels, appends to same --out ----
        state.update(prose=False, short=False, n=0)
        f_out = os.path.join(tmp, "f.jsonl")
        run_bench(["--start-ctx", "1000"], f_out)
        f_h, f_r = load_jsonl(f_out)
        assert f_h["run_header"].get("start_ctx") == 1000, f"F: header must record start_ctx: {f_h['run_header']}"
        labels = [r["round"] for r in f_r]
        assert "P0" not in labels, f"F: resume must skip P0, got {labels}"
        assert labels == ["P1000", "P2000"], f"F: resume levels wrong: {labels}"
        # appending on top of an existing jsonl keeps both runs' rows (autoresume via --out)
        run_bench(["--start-ctx", "1000"], f_out)
        f_h2, f_r2 = load_jsonl(f_out)
        assert len(f_r2) == 4, f"F: append must keep prior rows, got {len(f_r2)}"
        print(f"F PASS  --start-ctx 1000 resumes at P1000/P2000, appends to same --out (4 rows total)")

        # ---- G: incremental report is auto-rendered next to the jsonl after each level ----
        g_md = os.path.join(tmp, "bench-report-b.md")  # auto-written by bench during run B
        assert os.path.exists(g_md), "G: auto-generated bench report must exist next to b.jsonl"
        gm = open(g_md).read()
        assert "## 1. Ladder" in gm and "| mode |" in gm, "G: auto report must have ladder table w/ mode column"
        # a resume-append run also renders over the whole file (all level rows present)
        f_md = os.path.join(tmp, "bench-report-f.md")
        assert os.path.exists(f_md), "G: resume run must also auto-render a report"
        print("G PASS  bench auto-renders bench-report-<stem>.md next to the jsonl")

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
