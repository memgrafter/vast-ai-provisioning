#!/usr/bin/env python3
"""vast_gpu_risk_scan.py — full GPU workup for a running Vast instance.

Scans a live instance for GPU underutilization, bad driver behavior, and other
risk factors BEFORE trusting a benchmark. It runs a read-only probe inside the
container via the Jupyter kernel channel (the image has no container SSH — same
mechanism as vast_jupyter_exec.py) and produces ONE structured machine-profile
log containing:

  * the full check matrix — every check with PASS / WARN / FAIL / NA + value
  * findings (critical / warning) derived from the matrix
  * the raw probe data (nvidia-smi summary, per-GPU CSV, -q detail, topo,
    nvlink, dmesg tail, driver version, NUMA)

Motivation: a 2x RTX PRO 6000 "TP=2" box that should have done ~400 decode TPS
did ~200 because of (a) SW power capping (mobile Max-Q die at 300W), (b) no
NVLink, and (c) a cross-NUMA (SYS) GPU-GPU topology — none of which show up in
the offer listing. This script finds all of that.

ADVISORY ONLY: findings are logged, never acted on. This script does NOT
destroy, terminate, or modify the instance — it only reads nvidia-smi/dmesg.
It collects ALL findings (never exits on the first one).

Usage:
  # explicit Jupyter base + token (token = instance jupyter_token):
  .venv/bin/python scripts/vast_gpu_risk_scan.py --base http://HOST:JUPPORT --token TOKEN

  # or by instance id (resolves IP + Jupyter port + token via the Vast API;
  # needs env.vast-management sourced for VAST_API_KEY):
  .venv/bin/python scripts/vast_gpu_risk_scan.py --instance-id 49861942

  # what the provisioner requested (e.g. 2 for a TP=2 launch):
  ... --expected-gpus 2

  # dump the raw probe output only (debug):
  ... --probe-only

Output (one structured log + a JSON twin):
  logs/gpu-risk-scan-<instance>-<ts>.log   human-readable machine profile
  logs/gpu-risk-scan-<instance>-<ts>.json  same data, machine-readable
  (override with --out FILE; the .log is derived from the .json path)
"""
import argparse
import datetime as _dt
import http.cookiejar
import json
import os
import re
import sys
import time
import urllib.request
import uuid

PROBE = r"""
echo '===PROBE:SUMMARY==='
nvidia-smi 2>&1 | head -40
echo '===PROBE:CSV==='
nvidia-smi --query-gpu=index,name,serial,uuid,pci.bus_id,driver_version,cuda_version,temperature.gpu,power.draw,power.limit,clocks.sm,clocks.max.sm,clocks.mem,clocks.max.mem,clocks_throttle_reasons.active,utilization.gpu,utilization.memory,memory.used,memory.total,ecc.errors.correctable.volatile.total,ecc.errors.uncorrectable.volatile.total --format=csv,noheader 2>&1
echo '===PROBE:DETAIL==='
nvidia-smi -q 2>&1 | head -400
echo '===PROBE:LIST==='
nvidia-smi -L 2>&1
echo '===PROBE:TOPO==='
nvidia-smi topo -m 2>&1
echo '===PROBE:NVLINK==='
nvidia-smi nvlink -s 2>&1 | head -20
echo '===PROBE:DMESG==='
dmesg 2>/dev/null | grep -iE 'xid|nvrm|nvidia' | tail -40 || echo 'dmesg-not-accessible'
echo '===PROBE:NUMA==='
lscpu 2>/dev/null | grep -iE 'NUMA|Socket' || true
echo '===PROBE:DRIVER==='
cat /proc/driver/nvidia/version 2>/dev/null || echo 'driver-version-not-visible'
echo '===PROBE:END==='
"""

SECTION_RE = re.compile(r"^===PROBE:([A-Z]+)===$")


# --------------------------------------------------------------------------- #
# Jupyter-kernel exec (root into the container, no SSH)
# --------------------------------------------------------------------------- #
def run_probe(base: str, token: str, timeout: float = 90.0) -> str:
    import websocket  # websocket-client (in .venv)

    base = base.rstrip("/")
    auth = f"?token={token}"
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

    st, out = api("POST", "/api/kernels", {"name": "python3"})
    kid = json.loads(out)["id"]

    ws = websocket.create_connection(f"{ws_base}/api/kernels/{kid}/channels{auth}", timeout=timeout)
    time.sleep(0.5)

    session = uuid.uuid4().hex
    code = (
        "import subprocess, json\n"
        f"_r = subprocess.run({PROBE!r}, shell=True, capture_output=True, text=True, timeout={int(timeout)})\n"
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
        if m.get("msg_type") == "stream":
            out_parts.append(m["content"].get("text", ""))
        elif m.get("msg_type") == "execute_reply":
            done = True
    ws.close()
    try:
        api("DELETE", f"/api/kernels/{kid}")
    except Exception:
        pass

    text = "".join(out_parts)
    m = re.search(r"__KOUT__(\{.*\})", text)
    if m:
        d = json.loads(m.group(1))
        return d["out"] + ("\n" + d["err"] if d["err"] else "")
    return text


def resolve_instance(instance_id: int) -> tuple:
    from vastai import VastAI
    v = VastAI()
    r = v.client.get(f"/instances/{instance_id}/")
    d = r.json().get("instances", {})
    token = d.get("jupyter_token")
    ports = d.get("ports", {})
    jup = (ports.get("8080/tcp") or [{}])[0].get("HostPort")
    ip = d.get("ip")
    if not (token and jup and ip):
        raise SystemExit(f"could not resolve jupyter access for instance {instance_id}: "
                         f"token={bool(token)} jup_port={jup} ip={ip}")
    return f"http://{ip}:{jup}", token


# --------------------------------------------------------------------------- #
# Parsing
# --------------------------------------------------------------------------- #
def parse_probe(raw: str) -> dict:
    sections, cur = {}, None
    for line in raw.splitlines():
        m = SECTION_RE.match(line.strip())
        if m:
            cur = m.group(1)
            sections[cur] = []
            continue
        if cur is not None:
            sections[cur].append(line)
    return {k: "\n".join(v).strip() for k, v in sections.items()}


def parse_csv(text: str) -> list:
    lines = [l for l in text.splitlines() if l.strip()]
    if not lines:
        return []
    header, rows = None, []
    for l in lines:
        parts = [p.strip() for p in l.split(",")]
        if header is None:
            header = parts if parts and parts[0].lower() == "index" else [f"f{j}" for j in range(len(parts))]
            if parts and parts[0].lower() != "index":
                rows.append(dict(zip(header, parts)))
            continue
        if len(parts) == len(header):
            rows.append(dict(zip(header, parts)))
    return rows


def parse_detail(text: str) -> list:
    gpus, cur = [], None
    for line in text.splitlines():
        if re.match(r"^GPU\s+([0-9]+):", line):
            cur = {}
            gpus.append(cur)
            continue
        m = re.match(r"^\s{4}([A-Za-z][A-Za-z0-9 ]+?)\s{2,}:\s*(.+?)\s*$", line)
        if m and cur is not None:
            key = m.group(1).strip()
            if key not in cur:
                cur[key] = m.group(2).strip()
    return gpus


def parse_topo(text: str) -> dict:
    legend = {}
    for m in re.finditer(r"^\s{2}([A-Z0-9_]+)\s{2,}=\s*(.+)$", text, re.M):
        legend[m.group(1)] = m.group(2).strip()
    links = {}
    for line in text.splitlines():
        m = re.match(r"^\s*GPU(\d+)\s+(.+)$", line)
        if not m:
            continue
        src = f"GPU{m.group(1)}"
        cells = m.group(2).split()
        if any(c.startswith("GPU") for c in cells):
            continue  # header row
        for j, cell in enumerate(cells):
            if cell != "X":
                links[(src, f"GPU{j}")] = cell
    return {"links": links, "legend": legend}


def _fnum(s):
    try:
        return float(str(s).replace(" W", "").replace(" MHz", "").replace(" %", "").replace("MiB", "").strip())
    except Exception:
        return None


# --------------------------------------------------------------------------- #
# Workup — builds the FULL check matrix (PASS/WARN/FAIL/NA) + findings
# --------------------------------------------------------------------------- #
class Workup:
    def __init__(self):
        self.checks = []      # {check, scope, status, value, note}
        self.findings = []    # {severity, category, gpu, message}

    def add(self, check, status, value, scope="global", note="", sev=None):
        self.checks.append({"check": check, "scope": scope, "status": status,
                            "value": value, "note": note})
        if status in ("WARN", "FAIL"):
            self.findings.append({
                "severity": sev or ("critical" if status == "FAIL" else "warning"),
                "category": check, "gpu": scope.replace("gpu", "") if scope.startswith("gpu") else None,
                "message": f"{value}" + (f" — {note}" if note else ""),
            })


def workup(gpus_csv, detail, topo, dmesg, driver, numa, expected_gpus, detail_text):
    w = Workup()
    n = len(gpus_csv)

    # ---- global: GPU count ----
    if expected_gpus:
        if n == expected_gpus:
            w.add("gpu-count", "PASS", f"{n} GPUs (expected {expected_gpus})")
        else:
            w.add("gpu-count", "FAIL", f"{n} GPUs found, expected {expected_gpus}",
                  sev="critical")
    else:
        w.add("gpu-count", "PASS", f"{n} GPUs found")
    if n == 0:
        w.add("probe", "FAIL", "no GPUs visible to nvidia-smi", sev="critical")
        return w

    # ---- global: driver authenticity ----
    drv0 = gpus_csv[0].get("driver_version", "")
    if drv0 and re.match(r"^\d+\.\d+\.\d+$", drv0):
        w.add("driver-version-format", "PASS", f"{drv0} (normal NVIDIA version)")
    else:
        w.add("driver-version-format", "FAIL", f"'{drv0}' is not a normal NVIDIA version string",
              sev="critical")
    if driver and "NVIDIA UNIX" in driver and "Release Build" in driver:
        w.add("driver-genuine", "PASS", driver.splitlines()[0][:100])
    elif driver:
        w.add("driver-genuine", "WARN", f"driver build not marked 'Release Build': {driver.splitlines()[0][:100]}")
    else:
        w.add("driver-genuine", "NA", "driver version file not visible in container")

    # ---- global: GPU identity (spoofing) ----
    if n > 1:
        serials = [g.get("serial") for g in gpus_csv]
        uuids = [g.get("uuid") for g in gpus_csv]
        if len(set(serials)) == n and len(set(uuids)) == n:
            w.add("gpu-identity-unique", "PASS", f"{n} distinct serials + UUIDs")
        else:
            w.add("gpu-identity-unique", "FAIL",
                  f"duplicate serials={len(set(serials))}/{n} uuids={len(set(uuids))}/{n} — possible spoofed/duplicated card",
                  sev="critical")
    else:
        w.add("gpu-identity-unique", "NA", "single GPU")

    # ---- global: Xid errors ----
    xids = re.findall(r"Xid\s*\(?:\w+:\s*\)?\s*(\d+)", dmesg or "") or re.findall(r"Xid\s+(\d+)", dmesg or "")
    if xids:
        w.add("xid-errors", "FAIL", f"Xid errors present: {sorted(set(xids))}", sev="critical")
    elif dmesg and "dmesg-not-accessible" not in dmesg and dmesg.strip():
        w.add("xid-errors", "PASS", "driver messages in dmesg, no Xid errors")
    else:
        w.add("xid-errors", "NA", "dmesg not accessible in container")

    # ---- global: NUMA / sockets ----
    if numa:
        w.add("numa-layout", "PASS", " | ".join(l.strip() for l in numa.splitlines() if l.strip())[:160])
    else:
        w.add("numa-layout", "NA", "lscpu NUMA info not available")

    # ---- global: NVLink + topology (multi-GPU) ----
    links = topo.get("links", {})
    if n > 1:
        cross_numa = sorted({tuple(sorted((a, b))) for (a, b), c in links.items() if a != b and c == "SYS"})
        if cross_numa:
            w.add("topology", "WARN", f"GPU-GPU link = SYS (PCIe + inter-socket UPI/QPI): {cross_numa}",
                  note="cross-NUMA TP all-reduce is SLOW; prefer P2P/NVLink or same-NUMA")
        else:
            w.add("topology", "PASS", "no cross-NUMA (SYS) GPU-GPU links")
        nvlink_pairs = sorted({tuple(sorted((a, b))) for (a, b), c in links.items()
                               if a != b and c in ("NV4", "NV8", "NV12", "NV18", "NV#")})
        if nvlink_pairs:
            w.add("nvlink", "PASS", f"NVLink present: {nvlink_pairs}")
        else:
            w.add("nvlink", "WARN", f"{n}-GPU box has NO NVLink — TP all-reduce goes over PCIe")
        p2p = sorted({tuple(sorted((a, b))) for (a, b), c in links.items() if a != b and c == "PIX"})
        if p2p:
            w.add("topology-p2p", "PASS", f"same-PCIe-switch GPU pairs: {p2p}")

    # ---- per-GPU checks ----
    for g in gpus_csv:
        idx = g.get("index", "?")
        scope = f"gpu{idx}"

        # throttle reasons (hex bitmask)
        tr = g.get("clocks_throttle_reasons.active", "0")
        try:
            bits = int(tr, 16)
        except Exception:
            bits = 0
        sm, smax = _fnum(g.get("clocks.sm")), _fnum(g.get("clocks.max.sm"))
        clock_pct = f"{sm:.0f}/{smax:.0f} MHz ({100*sm/smax:.0f}%)" if (sm and smax) else g.get("clocks.sm", "?")
        pd, pl = _fnum(g.get("power.draw")), _fnum(g.get("power.limit"))
        pwr_str = f"{pd:.0f}W / limit {pl:.0f}W" if (pd and pl) else f"{g.get('power.draw','?')} / {g.get('power.limit','?')}"

        if bits & 0x4:
            w.add("power-cap", "WARN", f"SW power cap ACTIVE, SM clock {clock_pct}, {pwr_str}",
                  scope=scope, note="underutilized clocks — mobile/low-TDP die or host-imposed cap")
        else:
            w.add("power-cap", "PASS", "no SW power capping", scope=scope)
        if bits & 0x2:
            w.add("thermal", "WARN", "HW thermal slowdown ACTIVE", scope=scope)
        else:
            w.add("thermal", "PASS", "no thermal slowdown", scope=scope)
        if bits & 0x10:
            w.add("hw-slowdown", "WARN", "HW slowdown ACTIVE", scope=scope)
        else:
            w.add("hw-slowdown", "PASS", "no HW slowdown", scope=scope)
        if bits & 0x20:
            w.add("power-brake", "WARN", "HW power brake ACTIVE", scope=scope)
        else:
            w.add("power-brake", "PASS", "no power brake", scope=scope)

        # SM clock headroom (informational)
        if sm and smax:
            st = "PASS" if sm / smax >= 0.85 else "WARN"
            w.add("sm-clock", st, f"{clock_pct}", scope=scope,
                  note="" if st == "PASS" else "SM clock well below max (likely power-capped)")

        # power draw
        if pd and pl:
            w.add("power-draw", "PASS", f"{pd:.0f}W / limit {pl:.0f}W ({100*pd/pl:.0f}%)", scope=scope)
        else:
            w.add("power-draw", "NA", f"{g.get('power.draw','?')} / {g.get('power.limit','?')}", scope=scope)

        # temperature
        t = _fnum(g.get("temperature.gpu"))
        if t is not None:
            w.add("temperature", "PASS" if t < 83 else "WARN", f"{t:.0f}C", scope=scope,
                  note="" if t < 83 else "hot")

        # utilization / idle
        util = _fnum(g.get("utilization.gpu"))
        if util is not None:
            if util == 0:
                w.add("utilization", "WARN", "0% GPU utilization — idle / underutilized", scope=scope)
            else:
                w.add("utilization", "PASS", f"{util:.0f}% GPU utilization", scope=scope)
        else:
            w.add("utilization", "NA", "n/a", scope=scope)

        # memory
        mu, mt = _fnum(g.get("memory.used")), _fnum(g.get("memory.total"))
        if mu and mt:
            w.add("memory", "PASS", f"{mu:.0f}/{mt:.0f} MiB ({100*mu/mt:.0f}%)", scope=scope)

        # ECC
        ecc_u = _fnum(g.get("ecc.errors.uncorrectable.volatile.total")) or 0
        ecc_c = _fnum(g.get("ecc.errors.correctable.volatile.total")) or 0
        if ecc_u > 0:
            w.add("ecc-uncorrectable", "FAIL", f"{ecc_u:.0f} uncorrectable volatile ECC errors", scope=scope, sev="critical")
        else:
            w.add("ecc-uncorrectable", "PASS", "0 uncorrectable ECC errors", scope=scope)
        if ecc_c > 1000:
            w.add("ecc-correctable", "WARN", f"{ecc_c:.0f} correctable volatile ECC errors (high)", scope=scope)
        else:
            w.add("ecc-correctable", "PASS", f"{ecc_c:.0f} correctable ECC errors", scope=scope)

    # ---- per-GPU detail: power limit lowered, MIG, compute mode, retired pages ----
    for d in detail:
        idx = d.get("GPU index", "?")
        scope = f"gpu{idx}"
        cur, df, mx = _fnum(d.get("Current Power Limit")), _fnum(d.get("Default Power Limit")), _fnum(d.get("Max Power Limit"))
        if cur and df and cur < df - 1:
            w.add("power-limit-lowered", "WARN", f"current {cur:.0f}W < default {df:.0f}W (max {mx:.0f}W)",
                  scope=scope, note="host lowered the power cap")
        elif cur and df:
            w.add("power-limit-lowered", "PASS", f"current {cur:.0f}W = default {df:.0f}W", scope=scope)
        mig = d.get("MIG Mode")
        if mig:
            if "Enabled" in str(mig):
                w.add("mig-mode", "WARN", "MIG ENABLED — partitioned GPU, not full device", scope=scope)
            else:
                w.add("mig-mode", "PASS", "MIG disabled", scope=scope)
        cm = d.get("Compute Mode")
        if cm:
            if "Default" in cm:
                w.add("compute-mode", "PASS", cm, scope=scope)
            else:
                w.add("compute-mode", "WARN", f"Compute Mode = {cm} (not Default)", scope=scope)

    # retired pages from raw detail text
    for m in re.finditer(r"GPU\s+(\d+):.*?(?=GPU\s+\d+:|\Z)", detail_text, re.S):
        idx = m.group(1)
        block = m.group(0)
        hits = []
        for pm in re.finditer(r"(Row Remapper|Correctable|Uncorrectable|Pending)\s{2,}:(\d+)", block):
            if int(pm.group(2)) > 0:
                hits.append(f"{pm.group(2)} {pm.group(1)}")
        if hits:
            w.add("retired-pages", "WARN", f"retired-page/remapper counters: {hits}", scope=f"gpu{idx}",
                  note="failing memory rows")

    return w


# --------------------------------------------------------------------------- #
# Reporting — one structured log (matrix PASS+FAIL+WARN+NA) + JSON twin
# --------------------------------------------------------------------------- #
STATUS_ICON = {"PASS": "PASS", "WARN": "WARN", "FAIL": "FAIL", "NA": "  --"}


def render_log(report) -> str:
    L = []
    L.append("=" * 78)
    L.append(f"GPU WORKUP — instance {report['instance']} — {report['ts']}")
    L.append(f"VERDICT: {report['overall']}   "
             f"({report['critical']} critical, {report['warning']} warning, "
             f"{report['pass']} pass, {report['na']} n/a)")
    L.append(f"expected_gpus={report['expected_gpus']}  gpus_found={report['gpus_found']}")
    L.append(f"driver: {report['driver'].splitlines()[0] if report['driver'] else 'n/a'}")
    L.append("=" * 78)

    # machine profile
    L.append("\nMACHINE PROFILE")
    L.append("-" * 78)
    for g in report["gpus"]:
        L.append(f"  GPU {g.get('index')}: {g.get('name')}")
        L.append(f"      serial={g.get('serial')}  uuid={g.get('uuid')}  pci={g.get('pci.bus_id')}")
        L.append(f"      driver={g.get('driver_version')}  cuda={g.get('cuda_version')}  "
                 f"temp={g.get('temperature.gpu')}C  util={g.get('utilization.gpu')}%")
        L.append(f"      power={g.get('power.draw')} / {g.get('power.limit')}  "
                 f"sm={g.get('clocks.sm')} / {g.get('clocks.max.sm')}")
        L.append(f"      mem={g.get('memory.used')} / {g.get('memory.total')}  "
                 f"throttle={g.get('clocks_throttle_reasons.active')}")
    if report.get("topology", {}).get("links"):
        L.append(f"  topology links: {report['topology']['links']}")
        L.append(f"  topology legend: {report['topology']['legend']}")
    if report.get("numa"):
        L.append(f"  numa: {' | '.join(l.strip() for l in report['numa'].splitlines() if l.strip())}")

    # check matrix (ALL checks, grouped by scope)
    L.append("\nCHECK MATRIX  (PASS / WARN / FAIL / --)")
    L.append("-" * 78)
    L.append(f"  {'STATUS':6}  {'CHECK':24}  {'SCOPE':8}  VALUE / NOTE")
    order = {"global": 0}
    checks = sorted(report["checks"], key=lambda c: (0 if c["scope"] == "global" else 1,
                                                     c["scope"], c["check"]))
    for c in checks:
        icon = STATUS_ICON.get(c["status"], c["status"])
        val = c["value"] + (f"  [{c['note']}]" if c.get("note") else "")
        L.append(f"  {icon:6}  {c['check']:24}  {c['scope']:8}  {val}")

    # findings
    L.append("\nFINDINGS  (advisory only — nothing was destroyed or terminated)")
    L.append("-" * 78)
    if report["findings"]:
        for f in report["findings"]:
            g = f" [GPU {f['gpu']}]" if f.get("gpu") else ""
            L.append(f"  {f['severity'].upper():8} {f['category']}{g}: {f['message']}")
    else:
        L.append("  (none — all checks PASS or N/A)")

    # raw data appendix
    L.append("\nRAW PROBE DATA")
    L.append("-" * 78)
    for key in ("SUMMARY", "CSV", "TOPO", "NVLINK", "DMESG", "NUMA", "DRIVER"):
        if report["raw"].get(key):
            L.append(f"--- {key} ---")
            L.append(report["raw"][key])
    L.append("\n" + "=" * 78)
    L.append("END OF WORKUP")
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser(description="Full GPU workup for a running Vast instance (advisory only).")
    ap.add_argument("--base", help="Jupyter base URL http://HOST:JUPPORT")
    ap.add_argument("--token", help="instance jupyter_token")
    ap.add_argument("--instance-id", type=int, help="Vast instance id (resolves base+token via API)")
    ap.add_argument("--expected-gpus", type=int, default=None, help="expected GPU count (e.g. 2 for TP=2)")
    ap.add_argument("--probe-only", action="store_true", help="print raw probe output and exit")
    ap.add_argument("--out", default=None, help="JSON report path (default logs/gpu-risk-scan-<id>-<ts>.json)")
    ap.add_argument("--timeout", type=float, default=90.0)
    args = ap.parse_args()

    base = token = None
    inst_id = args.instance_id
    if args.base and args.token:
        base, token = args.base, args.token
    elif inst_id:
        base, token = resolve_instance(inst_id)
    else:
        ap.error("provide --base + --token, or --instance-id")

    raw = run_probe(base, token, timeout=args.timeout)
    if args.probe_only:
        print(raw)
        return

    sections = parse_probe(raw)
    gpus_csv = parse_csv(sections.get("CSV", ""))
    detail = parse_detail(sections.get("DETAIL", ""))
    topo = parse_topo(sections.get("TOPO", ""))
    dmesg = sections.get("DMESG", "")
    driver = sections.get("DRIVER", "")
    numa = sections.get("NUMA", "")

    w = workup(gpus_csv, detail, topo, dmesg, driver, numa, args.expected_gpus, sections.get("DETAIL", ""))

    n_crit = sum(1 for f in w.findings if f["severity"] == "critical")
    n_warn = sum(1 for f in w.findings if f["severity"] == "warning")
    n_pass = sum(1 for c in w.checks if c["status"] == "PASS")
    n_na = sum(1 for c in w.checks if c["status"] == "NA")
    overall = "CRITICAL" if n_crit else ("DEGRADED" if n_warn else "CLEAN")

    ts = _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    label = inst_id or (base or "?").replace("http://", "")
    out_path = args.out or f"logs/gpu-risk-scan-{label}-{ts}.json"
    log_path = os.path.splitext(out_path)[0] + ".log"

    report = {
        "instance": inst_id, "base": base, "ts": ts,
        "expected_gpus": args.expected_gpus, "gpus_found": len(gpus_csv),
        "overall": overall, "critical": n_crit, "warning": n_warn,
        "pass": n_pass, "na": n_na,
        "gpus": gpus_csv, "topology": topo, "driver": driver, "numa": numa,
        "checks": w.checks, "findings": w.findings,
        "raw": {k: sections.get(k, "") for k in ("SUMMARY", "CSV", "TOPO", "NVLINK", "DMESG", "NUMA", "DRIVER")},
    }

    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w") as fh:
        json.dump(report, fh, indent=2)
    with open(log_path, "w") as fh:
        fh.write(render_log(report))

    # concise stdout summary
    print(f"=== GPU WORKUP — instance {label} — {overall} "
          f"({n_crit} critical, {n_warn} warning, {n_pass} pass, {n_na} n/a) ===")
    for f in w.findings:
        g = f" [GPU {f['gpu']}]" if f.get("gpu") else ""
        print(f"  {f['severity'].upper():8} {f['category']}{g}: {f['message']}")
    print(f"\nFull structured log: {log_path}")
    print(f"JSON twin:           {out_path}")
    print("(advisory only — no instance was destroyed or terminated)")
    sys.exit(0)


if __name__ == "__main__":
    main()
