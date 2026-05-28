# RTX PRO 6000 WS Carnice c=15 agent benchmark report — 2026-05-28

## Summary

A 15-agent coding workload ran successfully against `sakamakismile/Carnice-V2-27b-NVFP4-TEXT-MTP` on a single RTX PRO 6000 WS Vast instance after hot-patching the live vLLM runtime to `--max-num-seqs 15`.

Key result: the workload reached more than **1.15M aggregate observed session input tokens** with **no vLLM request errors**, **max KV cache usage ~53.5%**, and only a brief raw-metrics queue blip of **2 waiting requests**.

This supports using `max_num_seqs=15` for mixed-context coding-agent traffic when client/proxy admission controls active context. It does **not** prove that 15 simultaneous near-256K contexts are safe.

## Run metadata

```text
run_base:        carnice-pro6000ws-c15-60k-20260528T031355Z
run_dir:         benchmark/runs/carnice-pro6000ws-c15-60k-20260528T031355Z
instance_id:     38172141
machine_id:      51218
gpu:             RTX PRO 6000 WS
api_base_url:    http://<host>:<mapped_port>/v1
served_model:    carnice-v2-27b-nvfp4-text-mtp-pro6000ws-performance-256k-mtp3
```

Live vLLM runtime was verified before the run:

```text
/etc/vllm-args.conf: --max-num-seqs 15
max_model_len:        262144
max_num_batched_tokens: 16384
kv_cache_dtype:       fp8
MTP speculative tokens: 3
```

Client guardrail for this run:

```text
.pi/models.json contextWindow: 65536
.pi/models.json maxTokens:     8192
```

## Metrics sources

Summary metrics:

```text
benchmark/runs/carnice-pro6000ws-c15-60k-20260528T031355Z/metrics.log
```

Raw Prometheus snapshots:

```text
benchmark/runs/carnice-pro6000ws-c15-60k-20260528T031355Z/prometheus-metrics.jsonl
```

Raw archive span:

```text
first snapshot: 2026-05-28T03:13:55.648Z
last snapshot:  2026-05-28T04:01:06.637Z
snapshots:      284
span:           47.18 minutes
```

## Capacity observations

Raw Prometheus maxima:

```text
max requests running: 15 at 2026-05-28T03:14:15.653Z
max requests waiting: 2  at 2026-05-28T03:33:56.051Z
max KV cache usage:   53.51% at 2026-05-28T03:38:36.158Z
```

Most summary snapshots showed no queueing. Raw Prometheus captured one transient `waiting=2` event. Treat this as a warning blip, not sustained saturation.

## Token throughput and cache behavior

Counter deltas over the archived span:

```text
prompt_tokens_delta:              42,990,208
generation_tokens_delta:           1,051,200
net_tokens_delta:                 44,041,408

prompt_tokens_cached_total_delta: 37,148,800
prompt local_compute delta:        5,841,408
prompt local_cache_hit delta:     37,148,800
prompt external_kv delta:                  0
```

Average over the 47.18-minute archive span:

```text
prompt_total_tps:      ~15,187 tok/s
generation_tps:           ~371 tok/s
total_tps:             ~15,558 tok/s
local_compute_prompt_tps: ~2,063 tok/s
cache_hit_prompt_tps:    ~13,123 tok/s
```

Prompt-token source split:

```text
local_cache_hit / prompt_total ≈ 86.41%
local_compute / prompt_total   ≈ 13.59%
external_kv / prompt_total     = 0%
```

The high cache-hit fraction matters: this run is representative of repeated coding-agent/tool-call context patterns, not independent unrelated 64K prompts.

## Request outcomes

Request success counter deltas:

```text
finished_reason=stop:       +977
finished_reason=length:       +0
finished_reason=abort:        +0
finished_reason=error:        +0
finished_reason=repetition:   +0
```

vLLM did not report request errors during the archived run.

## Latency histograms

Histogram deltas from raw Prometheus snapshots. Buckets are coarse, so percentiles are upper-bucket estimates.

```text
TTFT count: 978
TTFT avg:   2.29s
TTFT p50:   <=2.5s
TTFT p90:   <=7.5s
TTFT p95:   <=20s
TTFT p99:   <=20s

queue count: 977
queue avg:   0.12s
queue p50:   <=0.3s
queue p90:   <=0.3s
queue p95:   <=0.3s
queue p99:   <=10s

e2e latency count: 977
e2e avg:   33.62s
e2e p50:   <=10s
e2e p90:   <=120s
e2e p95:   <=240s
e2e p99:   <=480s

prefill avg: 1.88s
decode avg:  31.33s
```

Interpretation: queueing was low on average, but long decode/tool-call chains produced high tail e2e latencies.

## Final agent/session state

Final observed session usage:

| Agent | Input tokens | Output tokens | Users | Assistant msgs | Last stop |
|---:|---:|---:|---:|---:|---|
| 1 | 75,318 | 3,301 | 4 | 61 | stop |
| 2 | 19,817 | 76 | 2 | 13 | toolUse |
| 3 | 110,205 | 60 | 4 | 112 | toolUse |
| 4 | 94,733 | 1,849 | 3 | 62 | stop |
| 5 | 60,177 | 2,271 | 2 | 51 | stop |
| 6 | 76,724 | 2,128 | 2 | 109 | stop |
| 7 | 77,231 | 2,975 | 5 | 64 | stop |
| 8 | 81,528 | 2,126 | 4 | 82 | stop |
| 9 | 99,864 | 465 | 4 | 86 | stop |
| 10 | 57,248 | 3,443 | 3 | 55 | stop |
| 11 | 69,974 | 1,606 | 5 | 59 | stop |
| 12 | 62,550 | 2,456 | 2 | 26 | stop |
| 13 | 86,893 | 3,618 | 1 | 44 | stop |
| 14 | 71,196 | 3,843 | 2 | 58 | stop |
| 15 | 116,163 | 3,566 | 4 | 97 | stop |

Aggregate:

```text
sum final input tokens:    1,159,621
sum max-seen input tokens: 1,173,433
sessions with final input >=60k: 13/15
max final input:             116,163
```

Agent2 was the outlier and ended with a zero-token usage record in the pi session. Prometheus showed no vLLM request errors, so this is most likely a pi/provider/session record issue rather than a vLLM engine failure.

## What this run proves

This run gives evidence for the following:

1. The hotpatched runtime admitted 15 concurrent vLLM requests.
2. A 15-agent mixed coding workload reached >1.1M aggregate session input tokens.
3. KV usage remained well below exhaustion, peaking at ~53.5%.
4. vLLM request error counters did not increase.
5. Queueing was mostly absent, with one transient raw snapshot at `waiting=2`.

## What this run does not prove

This run does not prove:

1. 15 simultaneous full 256K contexts are safe.
2. Independent no-cache 64K prompts would perform the same way.
3. Tail latency is acceptable for all user-facing workloads.
4. The live `--max-num-seqs 15` patch will survive a full Vast reboot.

## Operational implications

For mixed coding-agent sessions on this instance/profile:

```text
15 concurrent sessions: viable under observed 64K-ish guardrail
Observed aggregate input: >1.15M tokens
Observed KV headroom: roughly half of cache still free at peak
Primary limiter seen: tail decode/tool-use latency, not KV exhaustion
```

Recommended admission-control posture:

```text
- Keep server max_num_seqs=15 only as a loose scheduler cap.
- Enforce actual safety by active token budget in client/proxy.
- Continue monitoring KV %, waiting requests, queue time, TTFT, and generation TPS.
- Treat sustained waiting >0 or KV >80% as queue/reject signals.
```

## Caveats and next fixes

Before the next longer run:

1. Fix the driver stop condition so target context is checked on latest usage even when `stopReason=toolUse`.
2. Keep the raw Prometheus JSONL archiver running for the whole run.
3. Verify the live container still has:

```text
/etc/vllm-args.conf: --max-num-seqs 15
```

4. If the instance was rebooted, run a direct c=15 smoke and confirm:

```text
max_running: 15
max_waiting: 0
```

## Bottom line

The first c=15 agent benchmark was successful for mixed-context coding-agent traffic. It showed substantial headroom at the observed workload level and produced no vLLM request errors. The next step is a higher client guardrail run, but with the driver fixed so agents stop at the intended context target instead of overshooting during tool-use chains.
