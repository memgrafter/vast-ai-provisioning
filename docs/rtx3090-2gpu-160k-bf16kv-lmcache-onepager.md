# LMCache: KV Cache Offload for 2x RTX 3090 160K bf16 Profiles

## Motivation

The 27B AWQ and 35B-A3B AWQ profiles on 2x RTX 3090 (24 GB VRAM each) with bf16 KV cache at
160K max context exhibit a fundamental bottleneck: the KV cache is too small to hold more than
~6K token positions at once, causing severe serialization during prefill and full eviction of
one request's KV data when another runs.

This document summarizes the empirical evidence, explains the root cause, and makes the case
for integrating LMCache to recover concurrency and enable efficient agentic workloads.

---

## Test Environment

| Property | Value |
|---|---|
| Instance | 39830199 |
| Machine | 125042 |
| GPU | 2x RTX 3090 (24 GB each, 48 GB total) |
| GPU RAM | 49,152 MB total |
| Host RAM | 515,778 MB (≈500 GB) |
| vLLM version | 0.22.0 |
| Image | `vastai/vllm:v0.22.0-cuda-13.0` |
| Template | `vLLM_R2_Qwen3_6_27B_AWQ_RTX3090_2GPU_160K_BF16KV_MTP2_V2` |
| Model | `QuantTrio/Qwen3.6-27B-AWQ` (27B, AWQ 4-bit, dense) |
| TP | 2 |
| Dtype | bfloat16 |
| KV cache dtype | bfloat16 |
| Max model len | 160,000 tokens |
| GPU memory utilization | 0.93 |
| Max num seqs | 2 |
| Max num batched tokens | 8,192 |
| Enable prefix caching | true |

---

## KV Cache Capacity: The Hard Constraint

The live vLLM metrics report:

```
num_gpu_blocks = 393
block_size = 16
```

**393 blocks × 16 tokens/block = 6,288 cached token positions** total across both GPUs.

For a 158K prompt, that means:

```
158,000 tokens / 16 = 9,875 blocks needed for full cache
9,875 / 393 = 25× oversubscription
```

vLLM handles this by **cycling blocks** — the first ~6K tokens are cached, then evicted as
tokens 6K–12K are processed, and so on. Each block is written and evicted ~25 times during a
single 158K prefill. When a second request arrives, its blocks evict the first request's
blocks entirely.

---

## Empirical Results

### Single 158K Request (cold cache)

| Metric | Value |
|---|---|
| Prompt tokens | 158,018 |
| Completion tokens | 50 |
| Wall time | ~160 s |
| Peak KV cache usage | ~54% (≈212 blocks) |
| Prefill time (avg across all requests) | ~29 s per request (from metrics) |
| Decode time (50 tokens) | ~2-5 s |

### Two Concurrent 158K Requests (unique prefixes to defeat prefix caching)

```
  time  | running | waiting | kv_cache
--------|---------|---------|---------
    5s  |    0    |    0    |  0.0%
   11s  |    1    |    0    |  8.4%
   16s  |    1    |    1    | 11.0%
    ...  |    1    |    1    | ... climbs to 54%
  160s  |    1    |    1    | 54%  ← seq1 finishes, evicted blocks freed
  166s  |    1    |    0    |  4.8% ← seq2 starts (full re-prefill, no cached blocks)
   ...  |    1    |    0    | ... climbs again
  325s  |    0    |    0    |  0.0% ← seq2 finishes
```

**Finding:** `running=1` throughout — the second request **serializes** behind the first.
Each request takes ~160 s, total wall time ~325 s. No concurrent prefill.

### Three Concurrent 158K Requests

Same pattern — `running=1, waiting=2` → `running=1, waiting=1` → `running=1, waiting=0`.
Total wall time ~484 s for 3 requests that could theoretically complete in ~160 s if
parallelized.

### Prefix Cache Hit Behavior

When all requests use the **identical** prompt (`"TOK " * 158000` repeated verbatim), vLLM's
prefix caching is effective: 8 concurrent requests completed in ~35 s (≈4.4 s each). This is
because all requests share the same prefix hashes, so only the first request does real
computation.

When each request has a **unique ~800-token prefix**, prefix caching provides no benefit
(both the unique prefix and the shared `"TOK"` filler hash to different blocks under the
unique prefix's influence), and each request takes ~160 s.

### Eviction Confirmation

Rerunning the same unique-prefixed request after an intervening request proved that seq1's KV
blocks are **fully evicted** by seq2:

```
seq1 (cold):     159.8 s
seq2 (different): 160.2 s  ← evicts seq1's blocks
seq1 (rerun):     159.9 s  ← full recompute, 1.0× speed
```

### Small-Prompt Concurrency Works

With 20K or 4K prompts, vLLM correctly schedules 2 concurrent requests (`running=2`):

```
20K prompts: sum=67.9s total=35.7s → CONCURRENT (1.9× overlap)
 4K prompts: sum=19.0s total=10.5s → CONCURRENT (1.8× overlap)
```

This confirms the scheduler and `max_num_seqs=2` work — the bottleneck is purely
KV cache capacity for long-context requests.

---

## Root Cause Summary

**The 2x RTX 3090 24 GB with bf16 KV cache at 0.93 GPU memory utilization allocates only
393 GPU blocks (6,288 token positions).**

A 158K context request needs 25× that capacity. vLLM handles this by cycling through blocks
— each prefill step writes new KV data and evicts old blocks. During this process, the
scheduler holds the prefill slot for one request and queues all others. The second request
cannot start until the first finishes because:

1. The first request's **multi-chunk prefill** (20 iterations of 8,192 tokens) occupies the
   scheduler's attention for ~160 seconds.
2. Even though KV cache usage peaks at ~54%, the scheduler sees insufficient contiguous free
   blocks to accommodate a second 158K prefill's working set.
3. vLLM v0.22's scheduler does not interleave prefill chunks from different requests
   (multi-prefill batching).

---

## Why LMCache

[LMCache](https://github.com/LMCache/LMCache) (8.4k GitHub stars, v0.4.6 on PyPI) is a
KV cache layer that offloads blocks to host CPU RAM and reloads them on demand via fast
PCIe/NVMe, avoiding recomputation when blocks are evicted from GPU VRAM.

### Expected Benefit for 2x RTX 3090

**Host RAM is abundant:** 515 GB available. The entire KV cache for one 160K context at
bf16 with this model is:

```
393 blocks × 16 tokens × 2 (K+V) × 128 (hidden per head × num_heads...) ≈ ~90 MB per GPU
```

Even with 100 concurrent 158K contexts, host RAM usage would be ~9 GB — trivial.

**The key improvement:** when seq2 runs and evicts seq1's blocks from GPU VRAM, LMCache
preserves those blocks in host memory. When seq1's turn comes again (or during decode when
seq1 needs previously-evicted blocks for attention), LMCache reloads them from host RAM
instead of forcing recomputation.

### Specific Workload Impact

| Scenario | Without LMCache | With LMCache |
|---|---|---|
| Seq1 @ 158K → Seq2 @ 158K → Seq1 rerun | 160s + 160s + 160s = 480s | 160s + 160s + ~5s (block reload) = 325s |
| Agentic worker with tool calls (long context, many decode steps) | Each decode step recomputes evicted blocks → high latency | Decode loads from host → low latency |
| 2 concurrent 158K decode phases | Serial (can't fit both KV) | Both fit in host RAM, GPU swaps blocks on demand |

### Integration Path

The integration is not straightforward:

1. **vLLM 0.22.0 compatibility:** LMCache's vLLM plugin interface was added post-0.22.0.
   Compatibility with 0.22.0 needs verification. (Covered in next-steps #1–#3.)

2. **Installation method:** Options include:
   - `pip install lmcache` in the onstart provisioning script.
   - Building a custom Docker image with LMCache pre-installed.
   - Running a separate LMCache server container.

3. **Configuration flags:**
   - `--kv-connector lmcache` (vLLM 0.25+)
   - Or LMCache plugin config via `--lmcache-config-file`
   - Cache backend: CPU offload (`cpu`), local disk (`disk`), or both.

4. **Block size alignment:** LMCache works best when its block size matches vLLM's
   (`block_size=16` in our config).

5. **Ray compatibility:** The profile enables Ray for TP=2. LMCache must be configured
   to work across Ray workers. (Covered in next-steps #6.)

---

## Applicability to 35B-A3B

The 35B-A3B AWQ model (cyankiwi/Qwen3.6-35B-A3B-AWQ-4bit) shares the same attention
architecture (same number of layers, same hidden size, same head count) as the 27B dense
model. The MoE nature only affects FFN layers.

**KV cache per token is identical** between 27B and 35B-A3B on this hardware.

The 35B model has slightly larger weight memory (≈9 GB vs ≈7 GB per GPU), leaving
≈2 GB less VRAM for KV cache. This means:

- Fewer GPU blocks (estimated ~340 vs 393)
- Slightly more eviction churn during prefill
- Same serialization behavior
- Same benefit from LMCache offload

The 35B profile has `max_num_seqs=8` vs the 27B's `max_num_seqs=2`, but as demonstrated,
this parameter has no effect at 158K context — effective concurrency is 1 regardless.

---

## Next Steps

1. #todo: Determine minimum vLLM version needed for LMCache integration.
2. #todo: Test LMCache pip installation in the `vastai/vllm:v0.22.0-cuda-13.0` container.
3. #todo: If 0.22.0 is incompatible, identify a Vast image tag with a compatible vLLM
   version (v0.25+ for `--kv-connector lmcache`), or switch to the official LMCache Docker image.
4. #todo: Design the provisioning script changes (pip install + flag injection).
5. #todo: Test single-request decode performance with LMCache offload enabled.
6. #todo: Test concurrent 158K decode and Ray TP=2 with LMCache.
7. #todo: Update the 27B and 35B model profiles with LMCache flags once proven.