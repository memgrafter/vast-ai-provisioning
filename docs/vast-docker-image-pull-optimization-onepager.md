# Vast Docker Image Pull Optimization One-Pager

Date: 2026-05-25

## Problem

Cold Vast hosts can spend tens of minutes pulling the vLLM Docker image before provisioning logs appear. For example, `vastai/vllm:v0.20.0-cuda-13.0` has a linux/amd64 manifest with 38 layers and roughly 8.36 GiB of compressed layer data. Large layers include:

```text
f679be53f59f  ~3.30 GiB
deaab889caa9  ~2.27 GiB
140381194cfe  ~1.16 GiB
c938ea1c03a3  ~0.51 GiB
```

Vast web-console status messages such as `5958d5976b4e: Download complete` and `140381194cfe: Pull complete` are Docker layer progress, not R2 model-sync progress. R2 only matters after the container starts and the provisioner logs `Provisioning model from R2` / `Syncing s3://...`.

## Why advertised host bandwidth is not enough

A host advertising ~1 Gbps should ideally download 8.36 GiB in about 85 seconds, but real cold-start time can be much longer because:

- Docker Hub/CDN routing to the provider/datacenter may be slow.
- Docker pulls layers concurrently, so status messages can appear out of order.
- Large layer decompression and extraction can bottleneck on old CPUs or disks.
- Docker daemon/storage-driver overhead is outside the advertised network number.
- Docker Hub rate limits and anonymous-pull behavior can add variance.

## Practical speedup options

### 1. Prefer cached hosts

If a cheap host finishes pulling the image, keep the instance/host warm when possible. Restarting on the same machine should reuse local Docker layer cache and avoid a full cold pull.

### 2. Rehost the image on another registry

Retag and push the exact image to a registry with better routing, then update the Vast template image.

Candidate registries:

```text
GHCR public
AWS ECR Public
Regional private ECR, if Vast auth is cleanly supported
```

Expected impact: cold-start pull time may drop from 20-40+ minutes to 3-8 minutes on bad Docker Hub routes, but extraction time still remains.

### 3. R2-backed registry/proxy

R2 alone cannot serve Docker images directly because Docker needs the Registry HTTP API, not just object blobs. But the registry can be a thin metadata/control-plane service while R2 stores the layer blobs. Use a separate bucket from model artifacts, for example:

```text
r2-vast-models      # existing/private model artifacts
r2-vast-registry    # docker registry blobs/manifests/uploads
```

Important implementation detail: make sure layer downloads do not all stream through a tiny registry VM. Prefer a registry/storage setup that redirects blob downloads to presigned R2/S3 URLs, or run the registry somewhere with enough egress. Otherwise the registry process becomes the bottleneck even if R2 is the backing store.

### 4. Docker registry mirror

A daemon-level mirror is ideal technically, but renters usually cannot change the Vast host Docker daemon config.

### 5. Smaller purpose-built image

A slimmer vLLM/CUDA image would reduce pull time and extraction time. This is the most durable structural fix, but it adds maintenance risk and must preserve CUDA/vLLM compatibility.

## Recommendation

Short term:

```text
Keep cheap hosts alive once image pull completes.
Monitor show_instance().status_msg during loading.
Do not destroy cheap instances just because logs have not reached the container yet.
```

Medium term:

```text
Push vastai/vllm:v0.20.0-cuda-13.0 to GHCR or ECR Public.
Create a parallel Vast template using the rehosted image.
A/B cold-start on similar Vast machines against Docker Hub.
```

Success metric:

```text
time from create_instance to first provisioner marker:
  Provisioning model from R2
```

Track separately:

```text
image pull/start time
R2 model sync time
vLLM model load time
API readiness time
```
