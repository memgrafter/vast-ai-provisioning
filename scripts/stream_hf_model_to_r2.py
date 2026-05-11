#!/usr/bin/env python3
"""Stream a Hugging Face model repo to R2 without staging model files locally."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from huggingface_hub import HfApi, hf_hub_url


MANIFEST_SUFFIX = ".stream-manifest.json"


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def s3_uri(bucket: str, key: str) -> str:
    return f"s3://{bucket}/{key}"


def aws_head_size(bucket: str, key: str, endpoint_url: str) -> int | None:
    cmd = [
        ".venv/bin/aws",
        "s3api",
        "head-object",
        "--bucket",
        bucket,
        "--key",
        key,
        "--endpoint-url",
        endpoint_url,
        "--query",
        "ContentLength",
        "--output",
        "text",
    ]
    result = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode != 0:
        return None
    try:
        return int(result.stdout.strip())
    except ValueError:
        return None


def aws_put_manifest(bucket: str, key: str, endpoint_url: str, manifest: dict[str, Any]) -> None:
    body = json.dumps(manifest, indent=2, sort_keys=True).encode()
    cmd = [
        ".venv/bin/aws",
        "s3",
        "cp",
        "-",
        s3_uri(bucket, key),
        "--endpoint-url",
        endpoint_url,
        "--content-type",
        "application/json",
    ]
    subprocess.run(cmd, input=body, check=True)


def stream_url_to_s3(*, url: str, token: str | None, bucket: str, key: str, endpoint_url: str, expected_size: int | None) -> None:
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = Request(url, headers=headers)
    try:
        response = urlopen(req, timeout=60)
    except HTTPError as exc:
        raise RuntimeError(f"download HTTP {exc.code} for {url}: {exc.read().decode(errors='replace')[:500]}") from exc

    cmd = [
        ".venv/bin/aws",
        "s3",
        "cp",
        "-",
        s3_uri(bucket, key),
        "--endpoint-url",
        endpoint_url,
    ]
    # AWS CLI requires expected-size only for stdin streams above 50GB. Passing it
    # when known is harmless and avoids surprises if future repos have huge shards.
    if expected_size is not None:
        cmd += ["--expected-size", str(expected_size)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    assert proc.stdin is not None
    transferred = 0
    try:
        while True:
            chunk = response.read(16 * 1024 * 1024)
            if not chunk:
                break
            proc.stdin.write(chunk)
            transferred += len(chunk)
        proc.stdin.close()
        rc = proc.wait()
    finally:
        response.close()
        if proc.poll() is None:
            proc.kill()
    if rc != 0:
        raise RuntimeError(f"aws upload failed for {key} with exit code {rc}")
    if expected_size is not None and transferred != expected_size:
        raise RuntimeError(f"short download for {key}: got {transferred}, expected {expected_size}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Stream Hugging Face model repo files directly to R2")
    parser.add_argument("--model-profile", type=Path, required=True)
    parser.add_argument("--skip-existing", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--revision", default=None)
    parser.add_argument("--include-cache", action="store_true", help="also upload Hugging Face cache metadata; default skips it")
    args = parser.parse_args()

    profile = load_json(args.model_profile)
    repo_id = profile["hf_model_id"]
    r2_prefix = str(profile["r2_prefix"]).strip("/")
    bucket = os.environ["R2_BUCKET"]
    endpoint = os.environ["R2_ENDPOINT"]
    token = os.environ.get("HF_TOKEN") or None

    api = HfApi(token=token)
    info = api.model_info(repo_id, revision=args.revision, files_metadata=True)
    siblings = sorted(info.siblings, key=lambda item: item.rfilename)
    uploaded: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    for sibling in siblings:
        path = sibling.rfilename
        if not args.include_cache and path.startswith(".cache/"):
            continue
        size = getattr(sibling, "size", None)
        key = f"{r2_prefix}/{path}"
        if args.skip_existing and size is not None:
            existing_size = aws_head_size(bucket, key, endpoint)
            if existing_size == int(size):
                print(f"skip existing {path} ({size} bytes)", flush=True)
                skipped.append({"path": path, "size": size})
                continue
        url = hf_hub_url(repo_id, filename=path, revision=args.revision)
        print(f"stream upload {path} -> {s3_uri(bucket, key)} size={size if size is not None else 'unknown'}", flush=True)
        stream_url_to_s3(url=url, token=token, bucket=bucket, key=key, endpoint_url=endpoint, expected_size=size)
        uploaded.append({"path": path, "size": size})

    manifest = {
        "hf_model_id": repo_id,
        "revision": args.revision or getattr(info, "sha", None),
        "r2_prefix": r2_prefix,
        "uploaded": uploaded,
        "skipped": skipped,
    }
    aws_put_manifest(bucket, f"{r2_prefix}/{MANIFEST_SUFFIX}", endpoint, manifest)
    print(json.dumps({"uploaded": len(uploaded), "skipped": len(skipped), "manifest": f"{r2_prefix}/{MANIFEST_SUFFIX}"}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
