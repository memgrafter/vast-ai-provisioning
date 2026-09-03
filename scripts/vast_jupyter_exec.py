#!/usr/bin/env python3
"""Run a shell command inside a Vast instance container via its Jupyter kernel.

The Vast vLLM image does not expose container SSH (port 22) or a Jupyter
terminal by default, but it DOES run a Jupyter server (supervisor app "jupyter")
fronted by the Instance Portal. This helper creates a python3 kernel over the
Jupyter REST API, connects to its WebSocket channel, and runs the command via
subprocess — giving root exec into the container without SSH.

Auth: the Jupyter server is token-protected. The token is the instance's
`jupyter_token` (from `show_instance` / the raw /instances/{id}/ API).

Usage:
  vast_jupyter_exec.py --base http://HOST:8080 --token TOKEN '<shell command>' [timeout_s]

  # base is the Jupyter app's EXTERNAL/mapped port (the Instance Portal's
  # "Jupyter" app, external_port 8080 -> mapped host port). token = jupyter_token.
"""
import sys, json, time, uuid, re
import urllib.request, http.cookiejar
import websocket  # websocket-client


def parse_args(argv):
    if len(argv) < 4 or argv[1] != "--base" or argv[3] != "--token":
        sys.stderr.write(__doc__)
        sys.exit(2)
    base = argv[2].rstrip("/")
    token = argv[4]
    cmd = argv[5]
    timeout = float(argv[6]) if len(argv) > 6 else 120.0
    return base, token, cmd, timeout


def main():
    base, token, cmd, timeout = parse_args(sys.argv)
    auth = f"?token={token}"
    # websocket base: swap http(s) -> ws(s)
    ws_base = base.replace("https://", "wss://").replace("http://", "ws://")

    cj = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))

    def get_xsrf():
        try:
            opener.open(base + "/tree" + auth, timeout=15).read()
        except Exception:
            pass
        for c in cj:
            if c.name == "_xsrf":
                return c.value
        return None

    def api(method, path, body=None):
        data = json.dumps(body).encode() if body is not None else None
        headers = {"Content-Type": "application/json"}
        if method in ("POST", "PUT", "DELETE"):
            x = get_xsrf()
            if x:
                headers["X-XSRFToken"] = x
        req = urllib.request.Request(base + path + auth, data=data, method=method, headers=headers)
        with opener.open(req, timeout=20) as r:
            return r.status, r.read().decode()

    # 1) create a python3 kernel
    st, out = api("POST", "/api/kernels", {"name": "python3"})
    kid = json.loads(out)["id"]
    print(f"[jupexec] kernel {kid}", file=sys.stderr)

    ws = websocket.create_connection(f"{ws_base}/api/kernels/{kid}/channels{auth}", timeout=timeout)
    time.sleep(0.5)

    session = uuid.uuid4().hex
    code = (
        "import subprocess, json\n"
        f"_r = subprocess.run({cmd!r}, shell=True, capture_output=True, text=True, timeout={int(timeout)})\n"
        "print('__KOUT__' + json.dumps({'out': _r.stdout, 'err': _r.stderr, 'rc': _r.returncode}))\n"
    )
    msg = {
        "header": {"msg_id": uuid.uuid4().hex, "msg_type": "execute_request",
                   "username": "", "session": session, "version": "5.3"},
        "parent_header": {}, "metadata": {},
        "content": {"code": code, "silent": False, "store_history": True,
                    "user_expressions": {}, "allow_stdin": False},
        "buffers": [], "signature": "", "key": "",
    }
    ws.send(json.dumps(msg))

    out_parts = []
    deadline = time.time() + timeout
    done = False
    while time.time() < deadline and not done:
        try:
            raw = ws.recv()
        except websocket.WebSocketTimeoutException:
            break
        if not raw:
            continue
        try:
            m = json.loads(raw)
        except Exception:
            continue
        mt = m.get("msg_type")
        if mt == "stream":
            out_parts.append(m["content"].get("text", ""))
        elif mt == "execute_reply":
            done = True
            if m["content"].get("status") != "ok":
                out_parts.append("\n[execute_reply status=%s] %s" % (
                    m["content"].get("status"), m["content"].get("ename", "")))
    ws.close()
    try:
        api("DELETE", f"/api/kernels/{kid}")
    except Exception:
        pass

    text = "".join(out_parts)
    m = re.search(r"__KOUT__(\{.*\})", text)
    if m:
        d = json.loads(m.group(1))
        sys.stdout.write(d["out"])
        if d["err"]:
            sys.stderr.write(d["err"])
        sys.exit(d["rc"])
    else:
        sys.stdout.write(text)
        sys.stderr.write("\n[jupexec] no __KOUT__ marker; raw output above\n")
        sys.exit(1)


if __name__ == "__main__":
    main()
