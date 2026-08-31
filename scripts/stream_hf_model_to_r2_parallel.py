#!/usr/bin/env python3
"""Stream a Hugging Face model repo to R2 in parallel, without local staging.

Parallelizes across whole files (shards): each worker streams one file from
Hugging Face directly into `aws s3 cp` stdin. Designed for repos where the
per-connection HF rate is low but the aggregate link is higher.

Usage:
  . env.modeltransfer
  .venv/bin/python scripts/stream_hf_model_to_r2_parallel.py \
    --model-profile config/models/glm-5.3-flash-uncensored-fp8.json \
    --workers 6
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from huggingface_hub import HfApi, hf_hub_url

MANIFEST_SUFFIX = ".stream-manifest.json"
CHUNK = 16 * 1024 * 1024
RETRIES = 4
BACKOFF_BASE = 5.0

_print_lock = threading.Lock()


def log(msg: str) -> None:
    with _print_lock:
        print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def s3_uri(bucket: str, key: str) -> str:
    return f"s3://{bucket}/{key}"


def aws_head_size(bucket: str, key: str, endpoint_url: str) -> int | None:
    cmd = [
        ".venv/bin/aws", "s3api", "head-object",
        "--bucket", bucket, "--key", key,
        "--endpoint-url", endpoint_url,
        "--query", "ContentLength", "--output", "text",
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
        ".venv/bin/aws", "s3", "cp", "-",
        s3_uri(bucket, key), "--endpoint-url", endpoint_url,
        "--content-type", "application/json",
    ]
    subprocess.run(cmd, input=body, check=True)


def stream_file(*, repo_id: str, path: str, token: str | None, bucket: str, key: str,
                endpoint_url: str, expected_size: int | None) -> None:
    """Stream one file from HF to S3 with retries."""
    url = hf_hub_url(repo_id, filename=path)
    last_err: Exception | None = None
    for attempt in range(1, RETRIES + 1):
        headers = {}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        req = Request(url, headers=headers)
        proc: subprocess.Popen | None = None
        response = None
        transferred = 0
        try:
            response = urlopen(req, timeout=120)
            cmd = [".venv/bin/aws", "s3", "cp", "-", s3_uri(bucket, key),
                   "--endpoint-url", endpoint_url]
            if expected_size is not None:
                cmd += ["--expected-size", str(expected_size)]
            proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
            assert proc.stdin is not None
            while True:
                chunk = response.read(CHUNK)
                if not chunk:
                    break
                proc.stdin.write(chunk)
                transferred += len(chunk)
            proc.stdin.close()
            rc = proc.wait()
            if rc != 0:
                raise RuntimeError(f"aws upload exited {rc}")
            if expected_size is not None and transferred != expected_size:
                raise RuntimeError(f"short download: got {transferred}, expected {expected_size}")
            return
        except (HTTPError, RuntimeError, OSError) as exc:
            last_err = exc
            if response is not None:
                response.close()
            if proc is not None and proc.poll() is None:
                proc.kill()
            if attempt < RETRIES:
                delay = BACKOFF_BASE * (2 ** (attempt - 1))
                log(f"retry {attempt}/{RETRIES - 1} for {path} in {delay:.0f}s: {str(exc)[:160]}")
                time.sleep(delay)
    raise RuntimeError(f"giving up on {path} after {RETRIES} attempts: {last_err}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Stream HF model repo to R2 in parallel")
    parser.add_argument("--model-profile", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--skip-existing", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--revision", default=None)
    parser.add_argument("--include-cache", action="store_true")
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

    todo: list[tuple[str, int | None]] = []
    skipped: list[dict[str, Any]] = []
    for sibling in siblings:
        path = sibling.rfilename
        if not args.include_cache and path.startswith(".cache/"):
            continue
        size = getattr(sibling, "size", None)
        key = f"{r2_prefix}/{path}"
        if args.skip_existing and size is not None:
            if aws_head_size(bucket, key, endpoint) == int(size):
                log(f"skip existing {path} ({size} bytes)")
                skipped.append({"path": path, "size": size})
                continue
        todo.append((path, size))

    total_bytes = sum(s or 0 for _, s in todo)
    log(f"repo={repo_id} files_to_upload={len(todo)} total={total_bytes / 2**30:.1f} GiB workers={args.workers}")

    uploaded: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []
    done_bytes = 0
    t0 = time.time()

    def work(item: tuple[str, int | None]) -> tuple[str, int | None, bool]:
        path, size = item
        stream_file(repo_id=repo_id, path=path, token=token, bucket=bucket,
                    key=f"{r2_prefix}/{path}", endpoint_url=endpoint, expected_size=size)
        return path, size, True

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(work, item): item for item in todo}
        for future in as_completed(futures):
            path, size = futures[future]
            try:
                future.result()
                uploaded.append({"path": path, "size": size})
                done_bytes += size or 0
                elapsed = time.time() - t0
                rate = done_bytes / elapsed / 2**20 if elapsed > 0 else 0
                remaining = (total_bytes - done_bytes) / (rate * 2**20) if rate > 0 else float("inf")
                log(f"done {path} ({(size or 0) / 2**30:.2f} GiB) "
                    f"progress={done_bytes / total_bytes * 100:.1f}% rate={rate:.1f} MiB/s eta={remaining / 60:.0f} min")
            except Exception as exc:
                failed.append({"path": path, "size": size, "error": str(exc)[:300]})
                log(f"FAILED {path}: {str(exc)[:200]}")

    manifest = {
        "hf_model_id": repo_id,
        "revision": args.revision or getattr(info, "sha", None),
        "r2_prefix": r2_prefix,
        "uploaded": sorted(uploaded, key=lambda x: x["path"]),
        "skipped": skipped,
        "failed": failed,
    }
    if not failed:
        aws_put_manifest(bucket, f"{r2_prefix}/{MANIFEST_SUFFIX}", endpoint, manifest)
        log(f"manifest written: {r2_prefix}/{MANIFEST_SUFFIX}")
    else:
        log(f"{len(failed)} files failed; manifest NOT written. Re-run to retry (skip-existing is on).")

    log(f"summary: uploaded={len(uploaded)} skipped={len(skipped)} failed={len(failed)}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
