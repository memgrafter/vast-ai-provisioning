# Qwen3.6 27B NVFP4 PRO6000WS c=8 40k burn-in report — 2026-05-28

## Run

```text
instance_id: 38195259
model: qwen3.6-27b-nvfp4-pro6000ws-performance-256k-mtp2
base_url: http://<host>:<mapped_port>/v1
run_base: qwen36-nvfp4-pro6000ws-c8-40k-20260528T055238Z
run_dir: benchmark/runs/qwen36-nvfp4-pro6000ws-c8-40k-20260528T055238Z
agents: 8
target_context: 40,000
```

The local benchmark/monitor processes and tmux session were stopped after the run. The Vast instance was left running for manual burn-in.

## Metrics capture

Artifacts:

```text
benchmark/runs/qwen36-nvfp4-pro6000ws-c8-40k-20260528T055238Z/metrics.log
benchmark/runs/qwen36-nvfp4-pro6000ws-c8-40k-20260528T055238Z/prometheus-metrics.jsonl
benchmark/runs/qwen36-nvfp4-pro6000ws-c8-40k-20260528T055238Z/analysis-summary.json
```

Raw Prometheus archive:

```text
first snapshot: 2026-05-28T05:52:38.812Z
last snapshot:  2026-05-28T06:14:19.290Z
snapshots:      131
```

Prometheus maxes:

```text
max requests running: 8
max requests waiting: 0
max KV cache usage:   25.4%
```

Token deltas over archive span:

```text
prompt_tokens_delta:     3,687,413
generation_tokens_delta:   353,561
cached_prompt_delta:      3,368,000
```

Request result deltas:

```text
finished_reason=stop:   +117
finished_reason=length:   +1
finished_reason=error:    +0
```

MTP/spec decode deltas:

```text
draft_tokens_delta:    273,806
accepted_tokens_delta: 216,658
acceptance_rate:       ~79.1%
```

## Final agent state

```text
agent1: input=42,714 output=4,573 assistants=21 stop=stop    done=true
agent2: input=47,655 output=109   assistants=19 stop=toolUse done=true
agent3: input=28,510 output=3,603 assistants=7  stop=stop    done=false
agent4: input=54,839 output=172   assistants=8  stop=toolUse done=true
agent5: input=10,580 output=5,047 assistants=4  stop=toolUse done=false
agent6: input=15,350 output=28,410 assistants=3 stop=toolUse done=false; saw one zero-token/error pi record
agent7: input=61,637 output=3,968 assistants=28 stop=stop    done=true
agent8: input=54,896 output=107   assistants=30 stop=toolUse done=true
```

Summary:

```text
agents reaching >=40k context: 5/8
max final input: 61,637
sum final input: 316,181
```

Agent6 had one pi/provider zero-token `stopReason=error` record. vLLM metrics showed `finished_reason=error` delta `0`, so this does not look like a vLLM engine failure.

## Observations

The c=8 burn-in looked healthy from vLLM's perspective:

```text
max_running=8
max_waiting=0
max_KV=25.4%
vLLM request errors=0
```

Generation throughput in sampled windows was typically a few hundred tok/s. MTP2 acceptance during the archived span was strong at roughly 79% accepted draft tokens.

This supports c=8 as a stable default for throughput-oriented PRO6000WS operation on this Qwen NVFP4 profile, with substantial KV headroom at 40k-class coding-agent contexts.

## Cleanup status

Stopped local run resources:

```text
driver: stopped
summary metrics monitor: stopped
raw Prometheus archiver: stopped
tmux session bench_qwen36_c8_40k_20260528T055238Z: stopped
```

Instance intentionally left running:

```text
instance_id: 38195259
endpoint: http://<host>:<mapped_port>/v1
```

## TPS analysis

TPS is computed from consecutive raw Prometheus snapshots in `prometheus-metrics.jsonl`, using actual scrape interval (`dt`) for each window. Prompt TPS is split into local prefill compute and prefix-cache-hit prompt tokens.

### Aggregate TPS distributions

| metric | windows | mean | median | p10 | p90 | max |
|---|---:|---:|---:|---:|---:|---:|
| Prompt total TPS, active windows | 75 | 4,918.90 | 3,813.68 | 1,565.05 | 10,134.65 | 22,214.29 |
| Prefill local-compute TPS, active prompt windows | 75 | 425.69 | 348.93 | 71.85 | 798.26 | 1,533.93 |
| Prefill cache-hit TPS, active prompt windows | 75 | 4,493.22 | 3,363.08 | 1,171.65 | 9,509.58 | 21,599.55 |
| Generation TPS, active decode windows | 129 | 274.09 | 278.82 | 188.41 | 347.74 | 387.13 |
| Total TPS, active windows | 129 | 3,133.92 | 1,983.18 | 266.81 | 8,280.88 | 22,403.79 |
| Accepted MTP TPS, active decode windows | 129 | 167.97 | 170.06 | 117.23 | 210.77 | 236.80 |

### Throughput by run quarter

| quarter | prompt total TPS mean | prefill compute TPS mean | generation TPS mean | total TPS mean | active windows |
|---:|---:|---:|---:|---:|---:|
| 1 | 1,428.64 | 310.06 | 329.25 | 1,757.89 | 31 |
| 2 | 1,920.99 | 204.72 | 292.44 | 2,213.43 | 33 |
| 3 | 3,147.94 | 248.40 | 256.69 | 3,404.63 | 32 |
| 4 | 4,863.73 | 230.61 | 220.81 | 5,084.54 | 33 |

### Top generation TPS windows

| end | gen TPS | accepted MTP TPS | prompt TPS | prefill compute TPS | cache-hit TPS | total TPS | running | waiting | KV % |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 2026-05-28T05:53:48.836Z | 387.13 | 236.80 | 0.00 | 0.00 | 0.00 | 387.13 | 8 | 0 | 9.4 |
| 2026-05-28T05:53:38.831Z | 383.84 | 233.70 | 0.00 | 0.00 | 0.00 | 383.84 | 8 | 0 | 9.4 |
| 2026-05-28T05:54:08.841Z | 382.44 | 234.35 | 0.00 | 0.00 | 0.00 | 382.44 | 8 | 0 | 10.2 |
| 2026-05-28T05:56:18.887Z | 373.62 | 235.66 | 1,453.41 | 10.62 | 1,442.79 | 1,827.03 | 8 | 0 | 12.7 |
| 2026-05-28T05:55:28.868Z | 372.75 | 229.76 | 0.00 | 0.00 | 0.00 | 372.75 | 8 | 0 | 11.7 |
| 2026-05-28T05:53:58.841Z | 372.61 | 223.12 | 0.00 | 0.00 | 0.00 | 372.61 | 8 | 0 | 9.4 |
| 2026-05-28T05:56:38.891Z | 371.10 | 235.46 | 1,467.78 | 27.41 | 1,440.37 | 1,838.88 | 8 | 0 | 13.1 |
| 2026-05-28T05:57:58.935Z | 370.83 | 227.10 | 2,337.55 | 138.69 | 2,198.86 | 2,708.38 | 8 | 0 | 14.7 |
| 2026-05-28T05:55:58.879Z | 370.31 | 228.90 | 0.00 | 0.00 | 0.00 | 370.31 | 8 | 0 | 12.1 |
| 2026-05-28T05:54:28.848Z | 367.55 | 220.45 | 0.00 | 0.00 | 0.00 | 367.55 | 8 | 0 | 10.3 |

### Top prefill local-compute TPS windows

| end | prefill compute TPS | prompt total TPS | cache-hit TPS | gen TPS | total TPS | running | waiting | KV % |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 2026-05-28T05:52:58.820Z | 1,533.93 | 4,409.86 | 2,875.93 | 237.36 | 4,647.23 | 8 | 0 | 9.2 |
| 2026-05-28T05:57:18.916Z | 1,271.60 | 6,722.30 | 5,450.70 | 185.56 | 6,907.86 | 8 | 0 | 13.6 |
| 2026-05-28T06:02:19.029Z | 1,219.94 | 8,580.76 | 7,360.82 | 146.82 | 8,727.58 | 7 | 0 | 16.6 |
| 2026-05-28T06:04:09.073Z | 1,015.14 | 9,972.83 | 8,957.69 | 160.76 | 10,133.59 | 8 | 0 | 21.3 |
| 2026-05-28T05:54:48.856Z | 918.39 | 2,019.08 | 1,100.69 | 264.85 | 2,283.93 | 8 | 0 | 10.8 |
| 2026-05-28T06:10:49.215Z | 884.99 | 9,959.81 | 9,074.82 | 117.42 | 10,077.23 | 6 | 0 | 18.8 |
| 2026-05-28T05:54:18.843Z | 829.52 | 1,789.30 | 959.79 | 281.14 | 2,070.44 | 8 | 0 | 10.2 |
| 2026-05-28T05:59:08.961Z | 805.02 | 2,243.79 | 1,438.78 | 214.42 | 2,458.21 | 8 | 0 | 16.0 |
| 2026-05-28T06:05:59.111Z | 788.13 | 12,288.14 | 11,500.01 | 198.75 | 12,486.90 | 8 | 0 | 23.3 |
| 2026-05-28T06:12:29.251Z | 780.78 | 11,976.22 | 11,195.44 | 153.34 | 12,129.56 | 7 | 0 | 23.9 |

### Top total TPS windows

| end | total TPS | prompt TPS | prefill compute TPS | cache-hit TPS | gen TPS | running | waiting | KV % |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 2026-05-28T06:12:09.242Z | 22,403.79 | 22,214.29 | 614.74 | 21,599.55 | 189.50 | 6 | 0 | 19.2 |
| 2026-05-28T06:11:49.234Z | 15,942.04 | 15,753.51 | 399.54 | 15,353.97 | 188.53 | 7 | 0 | 23.2 |
| 2026-05-28T06:05:59.111Z | 12,486.90 | 12,288.14 | 788.13 | 11,500.01 | 198.75 | 8 | 0 | 23.3 |
| 2026-05-28T06:12:29.251Z | 12,129.56 | 11,976.22 | 780.78 | 11,195.44 | 153.34 | 7 | 0 | 23.9 |
| 2026-05-28T06:12:49.261Z | 11,305.05 | 11,102.04 | 619.19 | 10,482.85 | 203.00 | 7 | 0 | 24.1 |
| 2026-05-28T06:04:19.075Z | 10,565.99 | 10,305.58 | 233.03 | 10,072.56 | 260.41 | 8 | 0 | 21.4 |
| 2026-05-28T06:11:09.222Z | 10,507.52 | 10,276.21 | 524.36 | 9,751.85 | 231.31 | 7 | 0 | 22.4 |
| 2026-05-28T06:11:29.227Z | 10,479.57 | 10,242.53 | 316.88 | 9,925.65 | 237.03 | 7 | 0 | 22.7 |
| 2026-05-28T06:04:09.073Z | 10,133.59 | 9,972.83 | 1,015.14 | 8,957.69 | 160.76 | 8 | 0 | 21.3 |
| 2026-05-28T06:10:49.215Z | 10,077.23 | 9,959.81 | 884.99 | 9,074.82 | 117.42 | 6 | 0 | 18.8 |

### Interpretation

- Generation throughput peaked around 387 tok/s in short active decode windows, with active-window mean around the low hundreds of tok/s because later windows include long decode/inference tails.
- Prompt total TPS is dominated by prefix-cache hits; local prefill compute is much smaller than prompt total due to the ~91% cache-hit fraction.
- The best local prefill compute bursts reached several thousand tok/s, while total TPS bursts exceeded 20k tok/s when cached prompt tokens dominated.
- No queueing was observed (`max_waiting=0`), so this c=8 40k burn-in did not hit an admission/runtime cap.


## Detailed metrics analysis

Raw Prometheus archive analysis from `prometheus-metrics.jsonl`.

### Archive span

```text
first snapshot: 2026-05-28T05:52:38.812Z
last snapshot:  2026-05-28T06:14:19.290Z
snapshots:      131
span:           21.67 minutes
```

### Request concurrency and KV

```text
max running: 8 at 2026-05-28T05:52:58.820Z
max waiting: 0 at 2026-05-28T05:52:48.815Z
max KV:      25.40% at 2026-05-28T06:14:09.286Z
final running: 5
final waiting: 0
final KV:      16.99%
```

### Token counters

```text
prompt_tokens_delta:     3,687,413
generation_tokens_delta: 353,561
total_tokens_delta:      4,040,974
cached_prompt_delta:     3,368,000
local_compute_delta:     319,413
local_cache_hit_delta:   3,368,000
external_kv_delta:       0
cache_hit_fraction:      91.34%
local_compute_fraction:  8.66%
```

### Request outcomes

```text
stop:       +117
length:     +1
error:      +0
abort:      +0
repetition: +0
```

### MTP / speculative decoding

```text
drafts_delta:          136,903
draft_tokens_delta:    273,806
accepted_tokens_delta: 216,658
acceptance_rate:       79.13%
accepted_per_draft:    1.58
accepted_pos_0_delta:  117,069
accepted_pos_1_delta:  99,589
```

### Per-window throughput extremes

Top generation TPS windows:

```text
2026-05-28T05:53:48.836Z: gen_tps=387.13, prompt_tps=0.00, total_tps=387.13, running=8, waiting=0, KV=9.4%
2026-05-28T05:53:38.831Z: gen_tps=383.84, prompt_tps=0.00, total_tps=383.84, running=8, waiting=0, KV=9.4%
2026-05-28T05:54:08.841Z: gen_tps=382.44, prompt_tps=0.00, total_tps=382.44, running=8, waiting=0, KV=10.2%
2026-05-28T05:56:18.887Z: gen_tps=373.62, prompt_tps=1453.41, total_tps=1827.03, running=8, waiting=0, KV=12.7%
2026-05-28T05:55:28.868Z: gen_tps=372.75, prompt_tps=0.00, total_tps=372.75, running=8, waiting=0, KV=11.7%
```

Top total TPS windows:

```text
2026-05-28T06:12:09.242Z: total_tps=22403.79, prompt_tps=22214.29, gen_tps=189.50, running=6, waiting=0, KV=19.2%
2026-05-28T06:11:49.234Z: total_tps=15942.04, prompt_tps=15753.51, gen_tps=188.53, running=7, waiting=0, KV=23.2%
2026-05-28T06:05:59.111Z: total_tps=12486.90, prompt_tps=12288.14, gen_tps=198.75, running=8, waiting=0, KV=23.3%
2026-05-28T06:12:29.251Z: total_tps=12129.56, prompt_tps=11976.22, gen_tps=153.34, running=7, waiting=0, KV=23.9%
2026-05-28T06:12:49.261Z: total_tps=11305.05, prompt_tps=11102.04, gen_tps=203.00, running=7, waiting=0, KV=24.1%
```

Highest KV windows:

```text
2026-05-28T06:14:09.286Z: KV=25.40%, running=7, waiting=0, gen_tps=243.66, total_tps=243.66
2026-05-28T06:13:59.284Z: KV=24.93%, running=7, waiting=0, gen_tps=252.53, total_tps=252.53
2026-05-28T06:13:39.279Z: KV=24.84%, running=7, waiting=0, gen_tps=251.79, total_tps=251.79
2026-05-28T06:13:49.284Z: KV=24.84%, running=7, waiting=0, gen_tps=262.16, total_tps=262.16
2026-05-28T06:07:29.137Z: KV=24.74%, running=8, waiting=0, gen_tps=291.27, total_tps=291.27
```

### Histogram deltas

Averages are over requests completed during the archive span. p50/p90/p99 are approximate from cumulative final Prometheus histogram buckets.

| metric | count delta | sum delta (s) | avg (s) | approx p50 final | approx p90 final | approx p99 final |
|---|---:|---:|---:|---:|---:|---:|
| TTFT | 124 | 212.45 | 1.71 | 1.40 | 4.07 | 17.65 |
| queue | 118 | 0.00 | 0.00 | 0.15 | 0.27 | 0.30 |
| inference | 118 | 7,815.09 | 66.23 | 21.25 | 141.00 | 668.80 |
| prefill | 118 | 179.57 | 1.52 | 1.17 | 4.02 | 13.86 |
| decode | 118 | 7,635.52 | 64.71 | 19.17 | 141.00 | 668.80 |
| e2e | 118 | 7,837.67 | 66.42 | 22.22 | 141.00 | 668.80 |

### Request token histograms

```text
request_prompt_tokens_count_delta:     118
request_prompt_tokens_sum_delta:       3,504,582
avg_prompt_tokens_per_request:         29,699.85
request_generation_tokens_count_delta: 118
request_generation_tokens_sum_delta:   287,754
avg_generation_tokens_per_request:     2,438.59
```

### Final agent/session usage

| agent | users | assistants | input | output | max seen input | last stop | zero/error | reached 40k |
|---|---:|---:|---:|---:|---:|---|---|---|
| agent1 | 1 | 21 | 42,714 | 4,573 | 42,714 | stop | False/False | True |
| agent2 | 2 | 19 | 47,655 | 109 | 47,655 | toolUse | False/False | True |
| agent3 | 2 | 7 | 28,510 | 3,603 | 28,510 | stop | False/False | False |
| agent4 | 2 | 8 | 54,839 | 172 | 54,839 | toolUse | False/False | True |
| agent5 | 2 | 4 | 10,580 | 5,047 | 10,580 | toolUse | False/False | False |
| agent6 | 4 | 3 | 15,350 | 28,410 | 15,350 | toolUse | True/True | False |
| agent7 | 2 | 28 | 61,637 | 3,968 | 61,637 | stop | False/False | True |
| agent8 | 4 | 30 | 54,896 | 107 | 54,896 | toolUse | False/False | True |

```text
agents >=40k: 5/8
sum final input: 316,181
max final input: 61,637
```

