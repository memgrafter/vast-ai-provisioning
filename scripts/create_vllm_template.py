#!/usr/bin/env python3
"""Create Vast.ai vLLM-from-R2 templates.

Default is dry-run: prints the SDK payload and docker options string.
Pass --apply to call VastAI.create_template().

Secrets note: keep AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY in Vast account-level
environment variables, not in this template, unless the template is private and you
intentionally accept that risk.
"""
from __future__ import annotations

import argparse
import json
import shlex
from pathlib import Path

from vastai import VastAI


PORTS = {
    1111: 11111,  # Instance Portal
    7860: 17860,  # Model UI
    8000: 18000,  # vLLM API
    8265: 28265,  # Ray Dashboard
    8080: 18080,  # Jupyter
}

DEFAULT_MODEL = "cyankiwi/Qwen3.5-9B-AWQ-4bit"
DEFAULT_SCRIPT = "https://raw.githubusercontent.com/memgrafter/vast-ai-provisioning/main/provision_vast_vllm_from_r2.sh"
DEFAULT_IMAGE = "vastai/vllm"
DEFAULT_TAG = "v0.20.1-cuda-12.9"


def docker_options(env: dict[str, str], ports: dict[int, int] = PORTS) -> str:
    parts: list[str] = []
    for external, internal in ports.items():
        parts += ["-p", f"{external}:{internal}"]
    for key, value in env.items():
        parts += ["-e", f"{key}={value}"]
    return " ".join(shlex.quote(p) for p in parts)


def build_env(args: argparse.Namespace) -> dict[str, str]:
    model_dir = args.model_dir or f"/workspace/models/{args.model_id}"
    served_name = args.served_model_name or args.model_id.split("/")[-1].lower().replace("_", "-")

    vllm_args = args.vllm_args or " ".join(
        [
            f"--served-model-name {served_name}",
            "--quantization awq",
            "--dtype half",
            "--host 127.0.0.1",
            "--port 18000",
            "--download-dir /workspace/models",
            f"--gpu-memory-utilization {args.gpu_memory_utilization}",
            "--trust-remote-code",
        ]
    )

    env = {
        "R2_BUCKET": args.r2_bucket,
        "R2_PREFIX": args.r2_prefix or args.model_id,
        "R2_ENDPOINT": args.r2_endpoint,
        "AWS_DEFAULT_REGION": "auto",
        "MODEL_DIR": model_dir,
        "VLLM_MODEL": model_dir,
        "VLLM_ARGS": vllm_args,
        "AUTO_PARALLEL": str(args.auto_parallel).lower(),
        "PROVISIONING_SCRIPT": args.provisioning_script,
    }
    if args.enable_https:
        env["ENABLE_HTTPS"] = "true"
    return env


def main() -> None:
    parser = argparse.ArgumentParser(description="Create Vast.ai vLLM-from-R2 template")
    parser.add_argument("--apply", action="store_true", help="Actually create the template via Vast SDK")
    parser.add_argument("--mode", choices=["production", "discovery"], default="production")
    parser.add_argument("--name", default=None)
    parser.add_argument("--image", default=DEFAULT_IMAGE)
    parser.add_argument("--image-tag", default=DEFAULT_TAG)
    parser.add_argument("--disk-space", type=float, default=80.0)
    parser.add_argument("--public", action="store_true", help="Create a public template. Do not use with secrets.")

    parser.add_argument("--model-id", default=DEFAULT_MODEL)
    parser.add_argument("--r2-prefix", default=None)
    parser.add_argument("--model-dir", default=None)
    parser.add_argument("--served-model-name", default="qwen3.5-9b-awq")
    parser.add_argument("--gpu-memory-utilization", default="0.90")
    parser.add_argument("--auto-parallel", action="store_true", help="Let Vast vLLM image add tensor parallelism for all GPUs")
    parser.add_argument("--vllm-args", default=None, help="Override complete VLLM_ARGS string")

    parser.add_argument("--r2-bucket", required=True)
    parser.add_argument("--r2-endpoint", required=True)
    parser.add_argument("--provisioning-script", default=DEFAULT_SCRIPT)
    parser.add_argument("--enable-https", action="store_true")

    args = parser.parse_args()

    env = build_env(args)
    onstart = None
    jupyter = False
    ssh = False
    direct = False
    jupyter_lab = False
    runtype_note = "Docker ENTRYPOINT"

    if args.mode == "discovery":
        onstart = Path("onstart.vast-vllm-discovery.sh").read_text()
        jupyter = True
        ssh = True
        direct = True
        jupyter_lab = True
        runtype_note = "Jupyter + SSH"

    name = args.name or f"vLLM R2 {args.model_id.split('/')[-1]} ({args.mode})"
    payload = {
        "name": name,
        "image": args.image,
        "image_tag": args.image_tag,
        "env": docker_options(env),
        "onstart_cmd": onstart,
        "jupyter": jupyter,
        "ssh": ssh,
        "direct": direct,
        "jupyter_lab": jupyter_lab,
        "disk_space": args.disk_space,
        "public": args.public,
        "desc": f"vLLM serving {args.model_id} from R2 via {runtype_note}",
        "readme": f"Serves {args.model_id} with vLLM. Model is synced from R2 before vLLM starts.",
        "hide_readme": False,
    }

    print("Template mode:", runtype_note)
    print("Docker options/env string:\n", payload["env"], sep="")
    print("\nSDK payload:")
    safe_payload = dict(payload)
    if safe_payload.get("onstart_cmd"):
        safe_payload["onstart_cmd"] = safe_payload["onstart_cmd"].strip()
    print(json.dumps(safe_payload, indent=2))

    if not args.apply:
        print("\nDry run only. Re-run with --apply to create the template.")
        return

    vast = VastAI()
    result = vast.create_template(**payload)
    print("\nCreate result:")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
