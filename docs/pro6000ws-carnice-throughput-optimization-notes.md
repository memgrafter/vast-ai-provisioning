# PRO 6000 WS Carnice throughput optimization notes

## Summary

For sustained coding-agent throughput, the current evidence suggests using the vLLM server cap as burst headroom, not as the normal active concurrency target.

Recommended default operating point:

```text
server max_num_seqs: 8
normal active decode concurrency: 6-8
higher burst concurrency: use a separate stress/burst profile, not the default
client/proxy cap: active token budget, not raw user count
```

## Evidence

The c=15 run proved that the hotpatched vLLM runtime can admit 15 concurrent requests:

```text
max_running: 15
max_waiting: initially 0
```

However, as contexts grew, c=15 showed signs of throughput/latency degradation:

```text
KV cache usage: ~50-56% mid-run
requests waiting: transient 1-2
generation_tps: fell as low as ~35-58 tok/s in heavy windows
TTFT / inference time: jumped during deeper-context windows
```

Earlier c=6 observations were cleaner:

```text
waiting: 0 in observed healthy windows
generation throughput: comparable or better for useful work
latency/TTFT: less scheduler contention
```

Interpretation: c=15 is valid as an admission ceiling for mixed short/medium requests, but not necessarily the best point for sustained coding-agent throughput once prompts become large.

## Recommended policy

Use separate limits:

```text
vLLM hard cap:              max_num_seqs=8
proxy active decode slots:  6-8
safe active token budget:   ~1.2M-1.5M tokens
queue threshold:            waiting > 0 or KV > ~70-80%
```

Admit by estimated request budget:

```text
request_budget = prompt_tokens + max_tokens
```

Queue or delay if any are true:

```text
active_decode_requests >= 8
active_token_budget + request_budget > 1.5M
vllm:num_requests_waiting > 0
vllm:kv_cache_usage_perc > 0.80
TTFT or queue-time histogram jumps
```

Allow more than 8 only for short-context requests or deliberate stress tests.

## Next benchmark matrix

Run the same 122k guardrail workload at:

```text
c=6
c=8
c=10
c=15
```

Compare:

```text
completed agent turns/min
generation_tps
prompt_total_tps and cache hit fraction
TTFT histogram
queue time histogram
requests waiting
KV cache usage
vLLM request errors
pi/provider zero-token errors
```

Expected outcome:

```text
c=6: safest / best latency
c=8: likely best throughput-latency tradeoff
c=10: possible edge of useful throughput
c=15: burst/stress capacity, not optimal sustained throughput
```

## Operational note

Use `max_num_seqs=8` as the default server cap for throughput-oriented operation. If higher burst admission is needed, use a separate profile and keep the proxy/client responsible for shaping active concurrency based on both request count and active token budget.
