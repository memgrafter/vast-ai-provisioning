#!/usr/bin/env python3
"""Launch one profiled Vast vLLM instance, test chat once, then destroy it."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vastai import VastAI

from scripts.monitor_instance_readiness import analyze_logs, port_url
from scripts.select_and_launch import load_launch_context, search_policy_offers


def api_get_json(url: str, api_key: str, timeout: int = 10) -> tuple[int, Any]:
    req = Request(url, headers={"Authorization": f"Bearer {api_key}"})
    try:
        with urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode() or "{}")
    except HTTPError as exc:
        return exc.code, exc.read().decode(errors="replace")
    except URLError as exc:
        return 0, str(exc)


def api_post_json(url: str, api_key: str, payload: dict[str, Any], timeout: int = 120) -> tuple[int, Any]:
    body = json.dumps(payload).encode()
    req = Request(
        url,
        data=body,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode() or "{}")
    except HTTPError as exc:
        return exc.code, exc.read().decode(errors="replace")
    except URLError as exc:
        return 0, str(exc)


def main() -> int:
    parser = argparse.ArgumentParser(description="Launch, wait for chat readiness, send one chat, destroy")
    parser.add_argument("--launch-profile", type=Path, default=Path("config/launch-profiles/qwen3.5-9b-awq.interruptible.json"))
    parser.add_argument("--launch-attempts", type=int, default=3)
    parser.add_argument("--ready-timeout", type=int, default=1200)
    parser.add_argument("--interval", type=int, default=15)
    parser.add_argument("--tail", type=int, default=2500)
    parser.add_argument("--message", default="Say hello in one short sentence.")
    args = parser.parse_args()

    api_key = __import__("os").environ.get("VLLM_API_KEY")
    if not api_key:
        raise SystemExit("missing local VLLM_API_KEY for smoke chat request")

    context = load_launch_context(args.launch_profile)
    launch = context["launch"]
    model = context["model"]
    vast = VastAI()

    for attempt in range(1, args.launch_attempts + 1):
        print(f"=== launch attempt {attempt}/{args.launch_attempts}: {launch['name']} ===", flush=True)
        offers = search_policy_offers(vast, context)
        if not offers:
            print("no offers passed policy; retrying", flush=True)
            time.sleep(args.interval)
            continue
        offer = offers[0]
        print(f"launching offer={offer.get('id')} machine={offer.get('machine_id')} gpu={offer.get('gpu_name')}", flush=True)
        create_kwargs = {
            "id": int(offer["id"]),
            "disk": float(launch["storage"]["disk_gb"]),
            "template_hash": launch["template"]["hash_id"],
            "label": f"smoke-{launch['name']}-{model['served_model_name']}",
        }
        if launch.get("market") in {"interruptible", "bid", "spot"}:
            create_kwargs["price"] = float(launch["spot"]["max_bid_dph"])
        result = vast.create_instance(**create_kwargs)
        instance_id = result.get("new_contract") or result.get("id")
        print("create:", json.dumps(result, sort_keys=True, default=str), flush=True)
        if not instance_id:
            continue
        instance_id = int(instance_id)
        try:
            start = time.time()
            while time.time() - start < args.ready_timeout:
                info = vast.show_instance(id=instance_id)
                logs = str(vast.logs(instance_id=instance_id, tail=str(args.tail)))
                signals = analyze_logs(logs, launch.get("image", "vastai/vllm:v0.20.0-cuda-13.0"))
                url = port_url(info)
                status = info.get("actual_status") or info.get("status")
                print(
                    f"probe instance={instance_id} status={status} url={url or '-'} "
                    f"sync={signals.r2_sync_finished} fail={signals.speed_test_failed or signals.provisioning_failed} "
                    f"vllm={signals.vllm_started or signals.api_ready}",
                    flush=True,
                )
                if signals.speed_test_failed or signals.provisioning_failed:
                    print("provisioning failed; destroying and retrying", flush=True)
                    break
                if url:
                    code, models = api_get_json(f"{url}/v1/models", api_key)
                    if code == 200:
                        chat_completions_url = f"{url}/v1/chat/completions"
                        print("models ok:", json.dumps(models, default=str)[:500], flush=True)
                        print(f"chat_completions_url={chat_completions_url}", flush=True)
                        print(f"model={model['served_model_name']}", flush=True)
                        code, chat = api_post_json(
                            chat_completions_url,
                            api_key,
                            {
                                "model": model["served_model_name"],
                                "messages": [{"role": "user", "content": args.message}],
                                "max_tokens": 64,
                                "temperature": 0,
                            },
                        )
                        print(f"chat_http={code}")
                        print(json.dumps(chat, indent=2, default=str)[:2000])
                        return 0 if code == 200 else 1
                time.sleep(args.interval)
            print("ready timeout/failure; retrying", flush=True)
        finally:
            print(f"destroying instance {instance_id}", flush=True)
            try:
                print(json.dumps(vast.destroy_instance(id=instance_id), sort_keys=True, default=str), flush=True)
            except Exception as exc:
                print(f"WARN destroy failed: {exc}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
