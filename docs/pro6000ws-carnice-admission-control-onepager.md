# RTX PRO 6000 WS Carnice admission control one-pager

## Goal

Prevent vLLM crashes or severe stalls by keeping admission decisions outside vLLM. Treat concurrency as a token-budget problem, not a user-count problem.

Profile context:

```text
GPU: RTX PRO 6000 WS, 96GB-class
Model: Carnice V2 27B NVFP4 TEXT MTP
max_model_len: 262144
max_num_seqs: 8
MTP: n=3
KV: fp8
```

## Rule of thumb from observed data

The c=6 full-context ramp showed no queueing while active contexts grew past ~100K tokens/agent. Earlier c=6 data around ~150K/agent reached roughly ~47% KV usage.

Use conservative active-token budgets:

```text
safe active budget:   ~1.5M tokens
warning zone:         ~1.7M tokens
queue/reject zone:    ~1.8M tokens
```

Examples:

```text
6 users * 250K = 1.50M  safe target
7 users * 250K = 1.75M  edge / experimental
20 users * 50K = 1.00M  KV-safe, decode may limit
100 users * 8K = 0.80M  KV-safe, scheduler/decode may limit
```

## Admission policy

For each incoming request, estimate:

```text
request_budget = prompt_tokens + max_tokens
```

Then apply:

```text
if prompt_tokens + max_tokens > 262144:
    reject or reduce max_tokens

if active_budget + request_budget > 1_500_000:
    queue

if vllm_kv_cache_usage > 0.80:
    queue

if vllm_num_requests_waiting > 0:
    queue

else:
    admit
```

For 32K-output clients, reserve that output headroom. Do not admit a 250K prompt with 32K max output; cap output to fit inside `max_model_len`.

## What to monitor

Use vLLM metrics:

```text
vllm:num_requests_running
vllm:num_requests_waiting
vllm:kv_cache_usage_perc
vllm:request_queue_time_seconds_*
vllm:time_to_first_token_seconds_*
vllm:generation_tokens_total
vllm:prompt_tokens_total
```

Healthy signs:

```text
waiting = 0
KV < 80%
queue avg ~0s
TTFT stable
generation TPS not collapsing for multiple windows
```

Danger signs:

```text
waiting > 0
KV > 80-90%
TTFT jumps sharply
queue time rises
generation TPS collapses while requests remain running
```

## Practical setup

- Keep `max_num_seqs=8` as the default throughput-oriented server cap; use client/proxy token budgets as the safety limit.
- Enforce real limits in a client/proxy admission layer.
- Track in-flight request budgets and subtract them when requests finish.
- Queue long-context requests before vLLM queues them.
- Prefer rejecting or reducing `max_tokens` over risking engine OOM.

Bottom line: **do not let vLLM discover the limit first**. Admit by active token budget, with c=6 full-context as the safe planning point and c=7+ full-context as edge/experimental unless the client/proxy is actively limiting context.
