# Qwen3.6 27B AWQ on RTX 6000Ada — c=8 unique-prefix capacity smoke

Generated: `2026-06-07`  
Profile: `qwen3.6-27b-awq.stable`  
Model: `QuantTrio/Qwen3.6-27B-AWQ` served as `qwen3.6-27b-awq`  
GPU: `1x RTX 6000Ada`, 49,140 MB VRAM  
Runtime: vLLM `v0.22.0-cuda-13.0`  
Configured context: `262144` tokens  
Admission config: `max_num_seqs=8`, `max_num_batched_tokens=8192`, `max_new_tokens=32000`, BF16 model/KV, AWQ Marlin, prefix caching enabled.

## Purpose

Find the practical c=8 parallel prompt/context ceiling for the RTX 6000Ada profile using unique coding-agent-style prefixes. This was an admission/KV/prefill smoke, not a quality benchmark.

## Workload

Runner: `scripts/coding_agent_saturation_ramp.py`

Common flags:

```bash
--concurrency 8
--requests-per-concurrency 1
--warmup-turns 0
--max-tokens 256
--max-model-len 262144
```

Each step launched 8 simultaneous simulated users. Each user had a unique stable prefix; `--shared-prefix` was not used. Prefix cache reuse was therefore intentionally minimal.

## Results

| Configured prefix | Actual prompt/request | Requests OK | Max KV | Max waiting | Queue avg | TTFT avg | PP / prefill TPS | Gen TPS |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 10k | 10,496 | 8/8 | 32.7% | 6 | 9.75s | 23.02s | 1,987 tok/s | 48.4 tok/s |
| 15k | 15,496 | 8/8 | 44.5% | 6 | 16.17s | 32.38s | 2,049 tok/s | 33.8 tok/s |
| 20k | 20,496 | 8/8 | 56.1% | 7 | 25.96s | 44.80s | 2,026 tok/s | 25.3 tok/s |
| 25k | 25,496 | 8/8 | 67.3% | 7 | 34.40s | 55.92s | 2,004 tok/s | 20.1 tok/s |
| 30k | 30,496 | 8/8 | 79.8% | 7 | 42.48s | 67.28s | 1,988 tok/s | 16.7 tok/s |
| 35k | 35,496 | 8/8 | 91.4% | 7 | 52.19s | 78.35s | 1,976 tok/s | 14.3 tok/s |
| 38k | 38,496 | 8/8 | 98.8% | 7 | 56.60s | 85.82s | 1,962 tok/s | 13.0 tok/s |

## Interpretation

- c=8 works functionally across the ladder: every step completed 8/8 requests with no vLLM errors or aborts.
- Practical c=8 operating range is likely at or below ~30k prompt tokens/request. At 30k, KV reached 79.8% and queue/TTFT were already high.
- 35k is marginal for c=8: KV reached 91.4% and TTFT averaged 78.35s.
- 38k is effectively the observed cap for this configuration: KV reached 98.8%, so there is little safety margin for output growth, longer prompts, or workload variation.
- Aggregate prefill throughput was stable around ~2.0k prompt tokens/s. The degradation with longer prefixes showed up mainly as queueing, TTFT, KV pressure, and lower decode TPS.
- `max_num_batched_tokens=8192` is conservative for c=8 long-prefill traffic and contributes to waiting. Raising it may improve prefill admission/queueing, but will need a separate safety test because 48GB VRAM is tight at long contexts.

## Coding-agent interpretation and LMCache strategy

This was a coding-agent-style capacity smoke: each simulated user carried a unique stable repository/session prefix plus a turn-specific tail. It was not a generic short-chat benchmark and it was not a shared-prefix TPS test.

For this profile, assume GPU KV consumption scales approximately linearly with total resident tokens:

```text
KV usage ≈ f(sum(active prompt tokens + generated tokens))
```

From the c=8 ladder, the observed resident KV capacity is roughly **~310k-315k total active tokens** before saturation. The 38k-prefix run had ~38,496 prompt tokens per request and reached 98.8% KV at c=8.

Approximate prompt ceilings under this linear KV model:

| Active coding agents | Prompt/agent near KV cap | Safer prompt/agent target |
|---:|---:|---:|
| 1 | model-limited at ~262k | ~220k-240k |
| 2 | ~155k | ~125k-140k |
| 4 | ~78k | ~60k-65k |
| 8 | ~39k | ~30k |

For real coding agents, output headroom matters. With the configured `max_new_tokens=32000`, worst-case c=8 capacity is not 39k prompt + 32k output per agent; it is closer to:

```text
~312k total KV / 8 ≈ ~39k total tokens per active agent
~39k - 32k output headroom ≈ ~7k prompt budget per agent
```

So production admission should budget `prompt_tokens + reserved_output_tokens`, not prompt tokens alone. For high-concurrency coding-agent workloads, either cap output lower, admit fewer long-context agents, or reserve dynamic output headroom based on queue state.

LMCache should be treated as a recompute reducer for repeated agent/session prefixes, not as permission to exceed active GPU KV capacity. It can improve multi-turn coding-agent throughput when each agent reuses a stable repo/session prefix, but active decoding still needs resident KV for admitted sequences.

## Concurrency plans: without LMCache vs with LMCache

Assume the following mixed coding-agent pool:

```text
2 long agents   @ 120k current context
4 medium agents @ 60k current context
2 short agents  @ 30k current context
```

Use a conservative active budget of **~260k resident tokens**. This keeps the host below the observed cliff while leaving some scheduling/output margin.

### Without LMCache

Without LMCache, evicted or queued sessions that lose prefix-cache residency pay full prefill again. At the measured aggregate prefill rate of about **~2,000 prompt tok/s**, recomputing a prefix costs roughly:

```text
30k prefix  ≈ 15s aggregate prefill
60k prefix  ≈ 30s aggregate prefill
120k prefix ≈ 60s aggregate prefill
```

Recommended non-LMCache admission should therefore avoid churn and keep a small, stable active set:

| Active mix | Resident tokens before output reserve | Read |
|---|---:|---|
| 4 × 60k | 240k | good upper target |
| 1 × 120k + 2 × 60k | 240k | good mixed target |
| 2 × 120k | 240k | good long-context target |
| 1 × 120k + 3 × 60k | 300k | marginal / avoid |
| 8 × 60k | 480k | not viable |

Without LMCache, prefer **2-4 active coding agents** depending on context size. Queue the rest explicitly rather than letting many large sessions thrash prefix cache.

### With LMCache

With LMCache, inactive/stalled session prefixes can be retained outside the active GPU KV path, reducing repeated prefill when a session resumes. This supports more total live sessions, but not more active resident tokens.

Plan around token-budgeted waves:

| Wave | Active agents | Approx active tokens | Read |
|---:|---|---:|---|
| 1 | 1 long + 1 medium + 1 short | 210k before output reserve | safe |
| 2 | 1 long + 1 medium + 1 short | 210k before output reserve | safe |
| 3 | 2 medium | 120k before output reserve | safe |

With a 4k output reserve per active agent:

```text
long   = 120k + 4k = 124k
medium = 60k  + 4k = 64k
short  = 30k  + 4k = 34k
```

Good LMCache-backed active mixes:

| Active mix | Budgeted active tokens | Read |
|---|---:|---|
| 1 long + 2 medium | 252k | good |
| 4 medium | 256k | good |
| 3 medium + 2 short | 260k | good but near target |
| 1 long + 3 medium | 316k | too high |
| 8 medium | 512k | too high |

With LMCache, the scheduler can keep **more total coding-agent sessions warm/in rotation**, but active admission should still target about **260k budgeted active tokens**. A practical policy for this host is:

```text
without LMCache: 2-4 active sessions, minimize eviction churn
with LMCache:    rotate more live sessions, but admit only ~260k active tokens at once
```

## FP8 KV cache savings

This run used BF16 KV cache. If the model/runtime works correctly with FP8 KV cache, KV memory per token should be roughly halved:

```text
BF16 KV = 2 bytes/value
FP8 KV  = 1 byte/value
```

So the active resident-token capacity should roughly double, assuming KV memory is the binding resource.

Estimated effect for this RTX 6000Ada profile:

| KV dtype | Observed/estimated hard active KV | Safer active budget | Approx 60k sessions | Approx 120k sessions |
|---|---:|---:|---:|---:|
| BF16 | ~310k-315k tokens | ~250k-270k | ~4 | ~2 |
| FP8 | ~620k tokens | ~500k-540k | ~8 | ~4 |

FP8 KV would mostly improve **resident context capacity and concurrency**, not raw prefill compute TPS. It may also reduce eviction pressure and make LMCache-backed rotation less necessary for medium-context sessions.

Caveats:

- FP8 KV quality/long-context recall should be checked on coding-agent tasks.
- Scheduler bottlenecks such as `max_num_batched_tokens=8192` can still create waiting even if KV memory is available.
- AWQ + FP8 KV compatibility needs a direct startup and c=8 smoke on this exact vLLM/model profile.

## Final cumulative metrics after smoke ladder

```text
requests running: 0
requests waiting: 0
KV cache usage: 0.0%
stop:   1
length: 72
error:  0
abort:  0
prompt_tokens_total:     1,489,510
generation_tokens_total: 18,498
prefix cache hit rate:   ~0.6%
avg TTFT:                ~43.51s
avg queue:               ~26.16s
avg inference:           ~51.01s
```

## Recommended next tests

1. Repeat c=8 at 30k with `max_tokens=1024` or `2048` to observe output growth headroom.
2. Test c=8 at 30k with higher `max_num_batched_tokens` to see whether queue/TTFT improves without destabilizing memory.
3. Test warmed multi-turn agent behavior with `--warmup-turns 1` and `--requests-per-concurrency 2` to measure prefix-cache benefit for realistic serial agent sessions.
