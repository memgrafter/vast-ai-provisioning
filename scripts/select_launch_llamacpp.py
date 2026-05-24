#!/usr/bin/env python3
"""Launch and bootstrap a Vast host for a llama.cpp stack.

Large artifacts are fetched from R2 by the Vast host. SSH is only used for
control-plane setup.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import shlex
import subprocess
import sys
import time
from requests import HTTPError
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from vastai import VastAI

DEFAULT_GPU_NAME = "RTX 5060 Ti"
DEFAULT_IMAGE = "nvidia/cuda:12.8.1-devel-ubuntu24.04"
DEFAULT_LABEL = "llamacpp-coding-agent"
DEFAULT_SERVER_BIN = "/workspace/clones/llama-cpp-turboquant/build-cuda/bin/llama-server"
DEFAULT_REMOTE_CODE_DIR = "/workspace/code/llm-cache-llama.cpp"
COSTING_STATUSES = {"running", "loading", "starting", "stopped", "exited", "unknown", "offline"}
BAD_STATUSES = {"exited", "offline"}
SENSITIVE_KEY_PARTS = ("key", "token", "secret", "password")


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: "<redacted>" if any(part in key.lower() for part in SENSITIVE_KEY_PARTS) else redact(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact(item) for item in value]
    return value


def instance_status(info: dict[str, Any]) -> str:
    return str(info.get("actual_status") or info.get("status") or info.get("cur_state") or "unknown")


def money(value: Any) -> str:
    if not isinstance(value, (int, float)):
        return "n/a"
    return f"${float(value):.4f}"


def number(value: Any, digits: int = 2) -> str:
    if not isinstance(value, (int, float)):
        return "n/a"
    return f"{float(value):.{digits}f}"


def ask(prompt: str) -> bool:
    return input(f"{prompt} [y/N] ").strip().lower() == "y"


def run(cmd: list[str], *, input_text: str | None = None, timeout: int | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, input=input_text, text=True, timeout=timeout, check=True)


def save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True, default=str) + "\n")


def require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise SystemExit(f"Missing required environment variable: {name}")
    return value


def shell_exports(values: dict[str, str]) -> str:
    return "".join(f"export {name}={shlex.quote(value)}\n" for name, value in values.items())


def model_filename(args: argparse.Namespace) -> str:
    if args.model_filename:
        return args.model_filename
    if not args.model_r2_key:
        return ""
    return Path(args.model_r2_key).name


def default_alias(filename: str) -> str:
    stem = filename.removesuffix(".gguf") if filename else "llamacpp-model"
    alias = re.sub(r"[^A-Za-z0-9._-]+", "-", stem).strip("-._")
    return alias.lower() or "llamacpp-model"


def get_instances(vast: VastAI) -> list[dict[str, Any]]:
    try:
        return vast.show_instances()
    except Exception as exc:
        print(f"WARN: could not list current instances: {exc}", file=sys.stderr)
        return []


def instance_hourly_cost(instance: dict[str, Any]) -> float:
    for key in ["dph_total", "actual_dph", "cur_state_dph", "dph_base"]:
        value = instance.get(key)
        if isinstance(value, (int, float)):
            return float(value)
    return 0.0


def print_current_infra(instances: list[dict[str, Any]]) -> None:
    print("Current Vast infra")
    print("==================")
    if not instances:
        print("Instances: none found")
    total = 0.0
    for instance in instances:
        status = str(instance.get("actual_status") or instance.get("status") or "unknown")
        if status.lower() not in COSTING_STATUSES:
            continue
        cost = instance_hourly_cost(instance)
        total += cost
        print(
            f"  id={instance.get('id') or instance.get('contract_id')} "
            f"status={status} label={instance.get('label')!r} "
            f"gpu={instance.get('gpu_name') or instance.get('gpu_names')} "
            f"machine={instance.get('machine_id')} cost={money(cost)}/hr"
        )
    print("Volumes: not checked")
    print(f"Known hourly burn, excluding unchecked owned volumes: {money(total)}/hr")
    print()


def offer_reject_reasons(offer: dict[str, Any], args: argparse.Namespace) -> list[str]:
    min_ram_mb = args.min_gpu_ram_gb * 1000.0
    checks = [
        (offer.get("verification") != "deverified", "deverified"),
        (offer.get("gpu_name") == args.gpu_name, "gpu_name"),
        (int(offer.get("num_gpus") or 0) == args.num_gpus, "num_gpus"),
        (float(offer.get("gpu_total_ram") or 0) >= min_ram_mb, "gpu_total_ram"),
        (float(offer.get("cuda_max_good") or 0) >= args.min_cuda, "cuda_max_good"),
        (float(offer.get("dph_total") or math.inf) <= args.max_dph, "dph_total"),
        (float(offer.get("reliability2") or 0) >= args.min_reliability, "reliability2"),
        (int(offer.get("direct_port_count") or 0) >= 1, "direct_port_count"),
        (float(offer.get("disk_space") or 0) >= args.disk_gb, "disk_space"),
        (float(offer.get("storage_total_cost") or math.inf) <= args.max_storage_hour, "storage_total_cost"),
        (float(offer.get("inet_down") or 0) >= args.min_inet_down, "inet_down"),
    ]
    return [name for ok, name in checks if not ok]


def offer_score(offer: dict[str, Any]) -> tuple[float, float, float, float, float]:
    return (
        float(offer.get("dph_total") or math.inf),
        -float(offer.get("reliability2") or 0),
        -float(offer.get("disk_bw") or offer.get("disk_io") or 0),
        float(offer.get("internet_down_cost_per_tb") or math.inf),
        -float(offer.get("inet_down") or 0),
    )


def search_offers(vast: VastAI, args: argparse.Namespace) -> list[dict[str, Any]]:
    quoted_gpu = json.dumps(args.gpu_name) if any(ch.isspace() for ch in args.gpu_name) else args.gpu_name
    query = " ".join(
        [
            f"num_gpus={args.num_gpus}",
            "rentable=true",
            "verified=true",
            f"gpu_name={quoted_gpu}",
            f"gpu_total_ram>={args.min_gpu_ram_gb}",
            f"cuda_max_good>={args.min_cuda}",
        ]
    )
    raw_offers = vast.search_offers(query=query, type="on-demand", order="dph_total", limit=args.search_limit, storage=args.disk_gb)
    passing: list[dict[str, Any]] = []

    print("Offer policy check")
    print("==================")
    print(f"query: {query}")
    print(f"search_limit: {args.search_limit}")
    for offer in raw_offers:
        reasons = offer_reject_reasons(offer, args)
        status = "PASS" if not reasons else "FAIL " + ",".join(reasons)
        print(
            f"{status:24} id={offer.get('id')} machine={offer.get('machine_id')} "
            f"gpu={offer.get('gpu_name')} cuda={offer.get('cuda_max_good')} "
            f"dph={money(offer.get('dph_total'))}/hr storage={money(offer.get('storage_total_cost'))}/hr "
            f"rel={number(offer.get('reliability2'), 4)} disk_bw={number(offer.get('disk_bw') or offer.get('disk_io'), 1)} "
            f"inet_down={number(offer.get('inet_down'), 1)}Mbps geo={offer.get('geolocation')}"
        )
        if not reasons:
            passing.append(offer)
    passing.sort(key=offer_score)
    print()
    return passing


def print_offer(offer: dict[str, Any], args: argparse.Namespace) -> None:
    dph = float(offer.get("dph_total") or 0)
    print("Selected offer")
    print("==============")
    print(f"offer_id:       {offer.get('id')}")
    print(f"machine_id:     {offer.get('machine_id')}")
    print(f"gpu:            {offer.get('gpu_name')} {offer.get('gpu_total_ram')}MB")
    print(f"cuda/driver:    {offer.get('cuda_max_good')} / {offer.get('driver_version')}")
    print(f"reliability2:   {number(offer.get('reliability2'), 4)}")
    print(f"geo:            {offer.get('geolocation')}")
    print(f"direct ports:   {offer.get('direct_port_count')}")
    print(f"disk available: {number(offer.get('disk_space'), 1)}GB")
    print(f"total hourly:   {money(dph)}/hr")
    print(f"10m estimate:   {money(dph * 10 / 60.0)}")
    print(f"disk request:   {args.disk_gb}GB")
    print()


def ssh_base(host: str, port: int) -> list[str]:
    return ["ssh", "-o", "StrictHostKeyChecking=accept-new", "-o", "ConnectTimeout=15", "-p", str(port), f"root@{host}"]


def ssh_run(host: str, port: int, command: str, *, input_text: str | None = None, timeout: int | None = None) -> None:
    run(ssh_base(host, port) + [command], input_text=input_text, timeout=timeout)


def sync_local_code(host: str, port: int, args: argparse.Namespace) -> None:
    local_dir = Path(args.local_code_dir).expanduser()
    if not local_dir.exists():
        raise SystemExit(f"Local code dir not found: {local_dir}")
    ssh_run(host, port, f"mkdir -p {shlex.quote(args.remote_code_dir)}", timeout=30)
    run(
        [
            "rsync",
            "-a",
            "--delete",
            "--exclude", ".git",
            "--exclude", "__pycache__",
            "--exclude", ".pytest_cache",
            "--exclude", "logs",
            "-e", f"ssh -o StrictHostKeyChecking=accept-new -p {port}",
            str(local_dir) + "/",
            f"root@{host}:{args.remote_code_dir}/",
        ],
        timeout=args.rsync_timeout,
    )


def ssh_target(info: dict[str, Any]) -> tuple[str, int]:
    ports = info.get("ports") or {}
    ssh_ports = ports.get("22/tcp") or []
    public_ip = info.get("public_ipaddr")
    if public_ip and ssh_ports:
        return str(public_ip), int(ssh_ports[0]["HostPort"])
    if info.get("ssh_host") and info.get("ssh_port"):
        return str(info["ssh_host"]), int(info["ssh_port"])
    raise RuntimeError("No SSH host/port found in instance info")


def public_url(info: dict[str, Any], container_port: int) -> str | None:
    ports = info.get("ports") or {}
    mapped = ports.get(f"{container_port}/tcp") or []
    public_ip = info.get("public_ipaddr")
    if public_ip and mapped:
        return f"http://{public_ip}:{mapped[0]['HostPort']}"
    return None


def poll_instance(vast: VastAI, instance_id: int, timeout_s: int) -> dict[str, Any]:
    start = time.time()
    last: dict[str, Any] = {}
    while time.time() - start < timeout_s:
        last = vast.show_instance(id=instance_id)
        status = instance_status(last)
        print(f"instance {instance_id} status={status}")
        if status == "running" or status.lower() in BAD_STATUSES:
            return last
        time.sleep(10)
    return last


def wait_for_ssh(host: str, port: int, timeout_s: int) -> None:
    start = time.time()
    while time.time() - start < timeout_s:
        try:
            ssh_run(host, port, "true", timeout=20)
            return
        except Exception:
            time.sleep(10)
    raise TimeoutError(f"SSH did not become ready at {host}:{port}")


def remote_env_text(args: argparse.Namespace) -> str:
    filename = model_filename(args)
    values = {
        "R2_BUCKET": require_env("R2_BUCKET"),
        "R2_ENDPOINT": require_env("R2_ENDPOINT"),
        "AWS_ACCESS_KEY_ID": require_env("AWS_ACCESS_KEY_ID"),
        "AWS_SECRET_ACCESS_KEY": require_env("AWS_SECRET_ACCESS_KEY"),
        "AWS_DEFAULT_REGION": os.environ.get("AWS_DEFAULT_REGION", "auto"),
        "MODEL_R2_KEY": args.model_r2_key,
        "ARTIFACT_R2_KEY": args.artifact_r2_key or "",
        "MODEL_FILENAME": filename,
    }
    if args.llamacpp_api_key_env:
        values["LLAMACPP_API_KEY"] = require_env(args.llamacpp_api_key_env)
    return shell_exports(values)


def write_remote_env(host: str, port: int, args: argparse.Namespace) -> None:
    ssh_run(host, port, "cat > /root/.llamacpp-r2.env && chmod 600 /root/.llamacpp-r2.env", input_text=remote_env_text(args), timeout=60)


def remote_bootstrap_script(args: argparse.Namespace) -> str:
    filename = model_filename(args)
    alias = args.model_alias or default_alias(filename)
    build_from_source = "1" if args.build_from_source else "0"
    api_key_argv_allowed = "1" if args.allow_api_key_argv else "0"
    extra_flags = args.extra_flags or ""
    remote_code_dir = shlex.quote(args.remote_code_dir)
    server_bin = shlex.quote(args.remote_server_bin)
    model_path = shlex.quote(f"/workspace/models/{filename}")
    alias_q = shlex.quote(alias)
    extra_flags_q = shlex.quote(extra_flags)

    return f"""#!/usr/bin/env bash
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
mkdir -p /workspace/models /workspace/code /workspace/clones /workspace/logs /workspace/cache/llama.cpp-launch-scripts/slot-kv /workspace/artifacts
apt-get update
apt-get install -y --no-install-recommends python3 python3-venv python3-pip ca-certificates curl jq lsof tar gzip git cmake ninja-build build-essential
if [ ! -x /workspace/awscli-venv/bin/aws ]; then
  python3 -m venv /workspace/awscli-venv
  /workspace/awscli-venv/bin/pip install -q --upgrade pip awscli
fi
. /root/.llamacpp-r2.env
AWS=/workspace/awscli-venv/bin/aws

fetch_r2_file() {{
  local key="$1"
  local dest="$2"
  local expected actual tmp
  expected="$($AWS s3api head-object --bucket "$R2_BUCKET" --key "$key" --endpoint-url "$R2_ENDPOINT" --query ContentLength --output text)"
  if [ -s "$dest" ]; then
    actual="$(stat -c %s "$dest")"
    if [ "$actual" = "$expected" ]; then
      echo "Using existing $dest ($actual bytes)"
      return 0
    fi
  fi
  tmp="$dest.r2tmp"
  rm -f "$tmp"
  echo "Downloading s3://$R2_BUCKET/$key -> $dest"
  $AWS s3 cp "s3://$R2_BUCKET/$key" "$tmp" --endpoint-url "$R2_ENDPOINT"
  actual="$(stat -c %s "$tmp")"
  if [ "$actual" != "$expected" ]; then
    echo "ERROR: size mismatch for $key expected=$expected actual=$actual" >&2
    exit 1
  fi
  mv -f "$tmp" "$dest"
}}

fetch_r2_file "$MODEL_R2_KEY" "/workspace/models/$MODEL_FILENAME"
if [ -n "${{ARTIFACT_R2_KEY:-}}" ]; then
  artifact="/workspace/artifacts/$(basename "$ARTIFACT_R2_KEY")"
  fetch_r2_file "$ARTIFACT_R2_KEY" "$artifact"
  case "$artifact" in
    *.tgz|*.tar.gz) tar -xzf "$artifact" -C /workspace ;;
    *.tar) tar -xf "$artifact" -C /workspace ;;
    *) echo "ERROR: unsupported artifact type: $artifact" >&2; exit 1 ;;
  esac
fi

SERVER_BIN={server_bin}
if [ ! -x "$SERVER_BIN" ] && [ "{build_from_source}" = "1" ]; then
  rm -rf /workspace/clones/llama-cpp-turboquant
  git clone --depth 1 https://github.com/TheTom/llama-cpp-turboquant.git /workspace/clones/llama-cpp-turboquant
  cmake -S /workspace/clones/llama-cpp-turboquant -B /workspace/clones/llama-cpp-turboquant/build-cuda -G Ninja -DCMAKE_BUILD_TYPE=Release -DGGML_CUDA=ON -DCMAKE_CUDA_ARCHITECTURES={args.cuda_arch} -DGGML_CUDA_FA=ON
  cmake --build /workspace/clones/llama-cpp-turboquant/build-cuda --target llama-server -j"$(nproc)"
fi
if [ ! -x "$SERVER_BIN" ]; then
  echo "ERROR: llama-server missing at $SERVER_BIN; provide an artifact or use --build-from-source" >&2
  exit 1
fi
if [ ! -x {remote_code_dir}/run-lmcache-proxy-stack.sh ]; then
  echo "ERROR: stack missing at {args.remote_code_dir}; include it in the artifact or use --sync-local-code" >&2
  exit 1
fi
python3 - <<'PY'
from pathlib import Path
path = Path({remote_code_dir!r}) / "lmcache-proxy-on-demand.py"
if path.exists():
    text = path.read_text()
    marker = 'authorization = self.headers.get("Authorization")'
    nl = chr(10)
    old = "        if body_bytes:" + nl + '            req.add_header("Content-Type", self.headers.get("Content-Type", "application/json"))' + nl
    new = old + nl + '        authorization = self.headers.get("Authorization")' + nl + '        if authorization:' + nl + '            req.add_header("Authorization", authorization)' + nl
    if marker not in text and old in text:
        path.write_text(text.replace(old, new, 1))
        print("Patched LMCache proxy to forward Authorization headers")
PY

cat > {remote_code_dir}/run-vast-llamacpp-stack.sh <<'SH'
#!/usr/bin/env bash
set -euo pipefail
cd {remote_code_dir}
. /root/.llamacpp-r2.env || true
export SERVER_BIN={server_bin}
export MODEL={model_path}
export ALIAS={alias_q}
export PUBLIC_HOST=0.0.0.0
export PUBLIC_PORT={args.container_port}
export BACKEND_HOST=127.0.0.1
export BACKEND_PORT={args.backend_port}
export CTX=${{CTX:-{args.ctx}}}
export NPRED=${{NPRED:-{args.n_predict}}}
export NGL=${{NGL:-{args.ngl}}}
export THREADS=${{THREADS:-{args.threads}}}
export BATCH=${{BATCH:-{args.batch}}}
export UBATCH=${{UBATCH:-{args.ubatch}}}
export CACHE_K=${{CACHE_K:-{args.cache_k}}}
export CACHE_V=${{CACHE_V:-{args.cache_v}}}
export SPEC_TYPE=${{SPEC_TYPE:-{args.spec_type}}}
export FLASH_ATTN=${{FLASH_ATTN:-{args.flash_attn}}}
export KV_OFFLOAD=${{KV_OFFLOAD:-{1 if args.kv_offload else 0}}}
export EXTRA_FLAGS={extra_flags_q}
export LOG_DIR=/workspace/logs
export CACHE_DIR=/workspace/cache/llama.cpp-launch-scripts/slot-kv
export BACKEND_LOG=/workspace/logs/llamacpp-backend-${{STAMP:-$(date +%Y%m%d-%H%M%S)}}.log
export BACKEND_PID_FILE=/tmp/llamacpp-backend.pid
export STARTUP_TIMEOUT={args.startup_timeout}
if [ -n "${{LLAMACPP_API_KEY:-}}" ]; then
  help_text="$($SERVER_BIN --help 2>&1 || true)"
  case "$help_text" in
    *--api-key-file*)
      printf '%s' "$LLAMACPP_API_KEY" > /root/.llamacpp-api-key
      chmod 600 /root/.llamacpp-api-key
      export EXTRA_FLAGS="--api-key-file /root/.llamacpp-api-key $EXTRA_FLAGS"
      ;;
    *--api-key*)
      if [ "{api_key_argv_allowed}" = "1" ]; then
        export EXTRA_FLAGS="--api-key $LLAMACPP_API_KEY $EXTRA_FLAGS"
      else
        echo "WARN: llama.cpp only advertised argv API key support; not using it without --allow-api-key-argv" >&2
      fi
      ;;
    *) echo "WARN: llama.cpp API key requested but no supported auth flag was advertised" >&2 ;;
  esac
fi
exec ./run-lmcache-proxy-stack.sh --background
SH
chmod +x {remote_code_dir}/run-vast-llamacpp-stack.sh
if [ -f /tmp/lmcache-proxy-stack.pid ]; then kill "$(cat /tmp/lmcache-proxy-stack.pid)" 2>/dev/null || true; fi
pkill -f lmcache-proxy-on-demand.py 2>/dev/null || true
pkill -f llama-server 2>/dev/null || true
sleep 2
{remote_code_dir}/run-vast-llamacpp-stack.sh
"""


def bootstrap_host(host: str, port: int, args: argparse.Namespace) -> None:
    if not args.model_r2_key:
        raise SystemExit("--model-r2-key is required for bootstrap")
    write_remote_env(host, port, args)
    if args.sync_local_code:
        sync_local_code(host, port, args)
    ssh_run(
        host,
        port,
        "cat > /workspace/bootstrap-llamacpp.sh && chmod +x /workspace/bootstrap-llamacpp.sh && /workspace/bootstrap-llamacpp.sh",
        input_text=remote_bootstrap_script(args),
        timeout=args.bootstrap_timeout,
    )
    for _ in range(max(1, args.service_timeout // 5)):
        try:
            ssh_run(host, port, f"curl -fsS --max-time 2 http://127.0.0.1:{args.container_port}/health >/dev/null", timeout=10)
            return
        except Exception:
            time.sleep(5)
    raise TimeoutError("llama.cpp endpoint did not become healthy")


def api_get(url: str, api_key: str | None) -> tuple[int, str]:
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    request = Request(url, headers=headers)
    try:
        with urlopen(request, timeout=10) as response:
            return response.status, response.read().decode(errors="replace")
    except HTTPError as exc:
        return exc.code, exc.read().decode(errors="replace")
    except URLError as exc:
        return 0, str(exc)


def print_endpoint(info: dict[str, Any], host: str, port: int, args: argparse.Namespace) -> None:
    endpoint = public_url(info, args.container_port)
    print("llama.cpp endpoint")
    print("==================")
    if endpoint:
        api_key = os.environ.get(args.llamacpp_api_key_env) if args.llamacpp_api_key_env else None
        print(f"external_base_url={endpoint}/v1")
        code, body = api_get(f"{endpoint}/health", api_key)
        print(f"health_http={code} body={body[:200]}")
        code, body = api_get(f"{endpoint}/v1/models", api_key)
        print(f"models_http={code} body={body[:500]}")
        if not args.llamacpp_api_key_env:
            print("WARN: no API key env was configured; prefer SSH tunnel if the public endpoint is unauthenticated")
    else:
        print(f"No public mapping found for {args.container_port}/tcp.")
    print(f"ssh=root@{host} -p {port}")
    print(f"tunnel=ssh -L 18081:127.0.0.1:{args.container_port} -p {port} root@{host}")
    print("tunnel_base_url=http://127.0.0.1:18081/v1")


def launch_instance(vast: VastAI, offer: dict[str, Any], args: argparse.Namespace) -> int:
    env = {f"-p {args.container_port}:{args.container_port}": "1"} if args.publish_port else {}
    try:
        result = vast.create_instance(
            id=int(offer["id"]),
            image=args.image,
            disk=args.disk_gb,
            label=args.label,
            runtype="ssh_direc ssh_proxy",
            env=env,
            onstart_cmd="mkdir -p /workspace && echo llama.cpp-vast-ready > /workspace/onstart.txt",
            cancel_unavail=True,
        )
    except HTTPError as exc:
        response_text = ""
        if exc.response is not None:
            response_text = exc.response.text[:1000]
        raise RuntimeError(f"Vast create_instance failed for offer {offer['id']}: {response_text or exc.response.status_code if exc.response is not None else 'HTTP error'}") from None
    redacted_result = redact(result)
    print("Create result:")
    print(json.dumps(redacted_result, indent=2, sort_keys=True, default=str))
    save_json(Path("state/last-create-llamacpp.json"), {"offer": offer, "create_result": redacted_result})
    instance_id = result.get("new_contract") or result.get("id")
    if not instance_id:
        raise RuntimeError("Create result did not include an instance id")
    return int(instance_id)


def attach_ssh_key(vast: VastAI, instance_id: int, key_path: Path) -> None:
    path = key_path.expanduser()
    if not path.exists():
        return
    public_key = path.read_text().strip()
    try:
        vast.create_ssh_key(ssh_key=public_key)
    except Exception:
        pass
    try:
        vast.attach_ssh(instance_id=instance_id, ssh_key=public_key)
    except Exception as exc:
        print(f"WARN: attach_ssh failed: {exc}", file=sys.stderr)


def validate_args(args: argparse.Namespace) -> None:
    if args.check_only or args.no_bootstrap:
        return
    if not args.model_r2_key:
        raise SystemExit("--model-r2-key is required unless --check-only or --no-bootstrap is used")
    if not args.artifact_r2_key and not args.sync_local_code:
        raise SystemExit("bootstrap needs code from --artifact-r2-key or --sync-local-code")
    if not args.artifact_r2_key and not args.build_from_source:
        raise SystemExit("bootstrap needs llama-server from --artifact-r2-key or --build-from-source")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Select, launch, and bootstrap a Vast llama.cpp instance")
    parser.add_argument("--check-only", action="store_true")
    parser.add_argument("--skip-current-infra", action="store_true")
    parser.add_argument("--top", type=int, default=5)
    parser.add_argument("--yes-current-infra", action="store_true")
    parser.add_argument("--yes-launch", action="store_true")
    parser.add_argument("--yes-bootstrap", action="store_true")
    parser.add_argument("--no-bootstrap", action="store_true")
    parser.add_argument("--instance-id", type=int, default=0, help="bootstrap or inspect an already-created Vast instance")
    parser.add_argument("--search-limit", type=int, default=50)
    parser.add_argument("--gpu-name", default=DEFAULT_GPU_NAME)
    parser.add_argument("--num-gpus", type=int, default=1)
    parser.add_argument("--min-gpu-ram-gb", type=float, default=15.0)
    parser.add_argument("--min-cuda", type=float, default=12.8)
    parser.add_argument("--min-reliability", type=float, default=0.96)
    parser.add_argument("--min-inet-down", type=float, default=100.0)
    parser.add_argument("--max-dph", type=float, default=0.40)
    parser.add_argument("--max-storage-hour", type=float, default=0.08)
    parser.add_argument("--disk-gb", type=float, default=80.0)
    parser.add_argument("--image", default=DEFAULT_IMAGE)
    parser.add_argument("--label", default=DEFAULT_LABEL)
    parser.add_argument("--publish-port", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--container-port", type=int, default=8081)
    parser.add_argument("--backend-port", type=int, default=8082)
    parser.add_argument("--model-r2-key", default="")
    parser.add_argument("--model-filename", default="")
    parser.add_argument("--model-alias", default="")
    parser.add_argument("--artifact-r2-key", default="")
    parser.add_argument("--build-from-source", action="store_true")
    parser.add_argument("--sync-local-code", action="store_true")
    parser.add_argument("--local-code-dir", default="~/code/llm-cache-llama.cpp")
    parser.add_argument("--remote-code-dir", default=DEFAULT_REMOTE_CODE_DIR)
    parser.add_argument("--local-ssh-pub-key", type=Path, default=Path("~/.ssh/id_ed25519.pub"))
    parser.add_argument("--remote-server-bin", default=DEFAULT_SERVER_BIN)
    parser.add_argument("--cuda-arch", default="120")
    parser.add_argument("--ctx", type=int, default=35000)
    parser.add_argument("--n-predict", type=int, default=4096)
    parser.add_argument("--ngl", type=int, default=999)
    parser.add_argument("--threads", type=int, default=12)
    parser.add_argument("--batch", type=int, default=64)
    parser.add_argument("--ubatch", type=int, default=16)
    parser.add_argument("--cache-k", default="turbo3")
    parser.add_argument("--cache-v", default="turbo3")
    parser.add_argument("--spec-type", default="ngram-mod")
    parser.add_argument("--flash-attn", default="auto")
    parser.add_argument("--kv-offload", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--extra-flags", default="")
    parser.add_argument("--llamacpp-api-key-env", default="")
    parser.add_argument("--allow-api-key-argv", action="store_true")
    parser.add_argument("--poll-timeout", type=int, default=900)
    parser.add_argument("--ssh-timeout", type=int, default=600)
    parser.add_argument("--bootstrap-timeout", type=int, default=2400)
    parser.add_argument("--startup-timeout", type=int, default=600)
    parser.add_argument("--service-timeout", type=int, default=900)
    parser.add_argument("--rsync-timeout", type=int, default=1800)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    validate_args(args)
    vast = VastAI()

    if not (args.check_only and args.skip_current_infra):
        instances = get_instances(vast)
        save_json(Path("state/current-infra.json"), {"instances": instances, "volumes_note": "owned volumes not checked"})
        print_current_infra(instances)

    if args.instance_id:
        info = poll_instance(vast, args.instance_id, args.poll_timeout)
        save_json(Path(f"instances/{args.instance_id}.llamacpp.json"), redact(info))
        status = instance_status(info)
        if status != "running":
            raise RuntimeError(f"Instance {args.instance_id} did not reach running status; status={status}")
        host, ssh_port = ssh_target(info)
        print(f"ssh=root@{host} -p {ssh_port}")
        wait_for_ssh(host, ssh_port, args.ssh_timeout)
        if args.no_bootstrap:
            print_endpoint(info, host, ssh_port, args)
            return
        if not args.yes_bootstrap and not ask("Bootstrap llama.cpp stack on this instance?"):
            print("Aborted before bootstrap.")
            return
        bootstrap_host(host, ssh_port, args)
        info = vast.show_instance(id=args.instance_id)
        save_json(Path(f"instances/{args.instance_id}.llamacpp.json"), redact(info))
        print_endpoint(info, host, ssh_port, args)
        return

    if not args.check_only and not args.yes_current_infra:
        if not ask("Continue to search/select a new llama.cpp instance?"):
            print("Aborted before search.")
            return

    offers = search_offers(vast, args)
    if not offers:
        raise SystemExit("No offers passed policy.")

    count = max(1, args.top if args.check_only else 1)
    for index, offer in enumerate(offers[:count], start=1):
        if args.check_only and count > 1:
            print(f"Passing offer #{index}")
            print("================")
        save_json(Path(f"offers/{offer['id']}.selected-llamacpp.json"), offer)
        print_offer(offer, args)

    if args.check_only:
        print("Check only: not launching.")
        return

    selected = offers[0]
    if not args.yes_launch and not ask("Launch this instance?"):
        print("Aborted before launch.")
        return
    if args.publish_port and not args.llamacpp_api_key_env:
        print("WARN: service port will be public unless Vast omits the mapping; no API key env was provided.")

    instance_id = launch_instance(vast, selected, args)
    attach_ssh_key(vast, instance_id, args.local_ssh_pub_key)

    info = poll_instance(vast, instance_id, args.poll_timeout)
    save_json(Path(f"instances/{instance_id}.llamacpp.json"), redact(info))
    status = instance_status(info)
    if status != "running":
        raise RuntimeError(f"Instance {instance_id} did not reach running status; status={status}")

    host, ssh_port = ssh_target(info)
    print(f"ssh=root@{host} -p {ssh_port}")
    wait_for_ssh(host, ssh_port, args.ssh_timeout)

    if args.no_bootstrap:
        print_endpoint(info, host, ssh_port, args)
        return
    if not args.yes_bootstrap and not ask("Bootstrap llama.cpp stack on this instance?"):
        print("Aborted before bootstrap.")
        return

    bootstrap_host(host, ssh_port, args)
    info = vast.show_instance(id=instance_id)
    save_json(Path(f"instances/{instance_id}.llamacpp.json"), redact(info))
    print_endpoint(info, host, ssh_port, args)


if __name__ == "__main__":
    main()
