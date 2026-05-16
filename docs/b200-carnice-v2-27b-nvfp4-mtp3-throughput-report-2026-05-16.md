# B200 Carnice V2 27B NVFP4 MTP3 Throughput Report

Date: 2026-05-16T06:50:03Z

## Summary

Tested `sakamakismile/Carnice-V2-27b-NVFP4-TEXT-MTP` on a single Vast B200 with vLLM, NVFP4/modelopt weights, FP8 KV cache, prefix caching, and MTP3 speculative decoding.

Best quick peak-TPS result so far:

```text
c=128, shared 60K prefix, max_tokens=1024
3782 tok/s total
29.6 tok/s/user
max_kv ~75.7%
```

Best sustained agentic point so far:

```text
c=96, shared 30K prefix, max_tokens=20000, 4 sequential measured turns/user
5575 tok/s total
58.1 tok/s/user
max_kv ~75.3%, queue_avg ~0.11s
```

Upper-bound saturated point:

```text
c=128, shared 30K prefix, max_tokens=20000, 4 sequential measured turns/user
5450 tok/s total
42.6 tok/s/user
max_kv 100.0%, queue_avg ~13.0s
```

`c=192` was past the useful peak for the 60K-prefix TPS shape: KV reached ~99.9%, queueing rose, and aggregate throughput fell below `c=128`.

## Hardware / Server Profile

```text
provider: Vast.ai
instance_id: <redacted>
machine_id: <redacted>
gpu: 1x NVIDIA B200, 183GB
price: ~$3.9635/hr during test
```

Live model profile:

```text
model: sakamakismile/Carnice-V2-27b-NVFP4-TEXT-MTP
served_model_name: carnice-v2-27b-nvfp4-text-mtp-b200-maxctx-mtp3
quantization: modelopt / NVFP4
speculative decoding: MTP n=3
max_model_len: 262144
kv_cache_dtype: fp8
enable_prefix_caching: true
max_num_seqs: 512
max_num_batched_tokens: 16384
max_new_tokens: 30000
gpu_memory_utilization: 0.9
```

Important note: `max_num_batched_tokens=16384` was used because a prior Qwen FP8 B200 startup with `65536` crashed during torch.compile/Triton with CUDA illegal memory access.

## Harness / Methodology

Benchmark script:

```text
scripts/coding_agent_saturation_ramp.py
```

Relevant harness behavior:

- Sends Chat Completions requests against vLLM.
- Uses a coding-agent-shaped prompt, not a terse benchmark prompt.
- Supports a warmup phase before measured requests.
- Supports shared-prefix TPS mode.
- Reports client totals and server metrics from `/metrics`.

Shared-prefix TPS mode:

```text
--shared-prefix
--fixed-prefix-tokens <N>
```

This intentionally shares the long synthetic prompt prefix across workers to isolate decode throughput. It is **not** a KV-store residency test. For KV-residency testing, use unique per-user prefixes.

Strict-prefix implication:

```text
shared long prefix is reused
then user_id / turn / generated continuation diverges
live KV pressure is roughly shared_prefix + concurrency * active generated/suffix tokens
not shared_prefix * concurrency after the prefix is warm
```

## Results Table

| Run | Prefix | max_tokens | Measured turns/user | Total measured reqs | Total gen tok/s | tok/s/user | Max KV | Queue / waiting | Notes |
|---|---:|---:|---:|---:|---:|---:|---:|---|---|
| c=2 | 60K shared | 2048 | 2 | 4 | 397 | 198.4 | 2.6% | none | Low-concurrency per-user probe |
| c=24 | 60K shared | 2048 | 2 | 48 | 2528 | 105.3 | 15.3% | no meaningful queueing | Shorter response cap than agentic run |
| c=128 | 60K shared | 1024 | 2 | 256 | 3782 | 29.6 | 75.7% | max_waiting 12 | Best quick aggregate so far |
| c=192 | 60K shared | 1024 | 2 | 384 | 3071 | 16.0 | 99.9% | max_waiting 33 | KV/scheduler saturated; worse than c=128 |
| c=24 agentic | 30K shared | 20000 | 4 | 96 | 2845 | 118.5 | 19.8% | max_waiting 7, queue_avg 0.03s | Sustained long-output agentic run |
| c=64 agentic | 30K shared | 20000 | 4 | 256 | 4942 | 77.2 | 50.3% | max_waiting 12, queue_avg 0.11s | Clean service-shaped point |
| c=96 agentic | 30K shared | 20000 | 4 | 384 | 5575 | 58.1 | 75.3% | max_waiting 2, queue_avg 0.11s | Best sustained agentic point so far |
| c=128 agentic | 30K shared | 20000 | 4 | 512 | 5450 | 42.6 | 100.0% | max_waiting 26, queue_avg 13.02s | KV saturated; worse than c=96 aggregate |

## Detailed Runs

### c=2 quick low-concurrency probe

```text
concurrency: 2
requests_per_concurrency: 2
warmup_turns: 1
warmup_max_tokens: 1
max_tokens: 2048
shared_prefix: true
fixed_prefix_tokens: 60000
actual prompt tokens: ~60494
```

Result:

```text
ok: 4/4
wall_s: 20.6
generation_tps_total: 396.88 tok/s
tok/s/user: 198.44
latency_avg: 9.99s
TTFT_avg: 0.34s
max_running: 2
max_waiting: 0
max_kv: 2.6%
```

Server window:

```text
417.8 tok/s @ 2 running = 208.9 tok/s/running user
```

### c=24 quick TPS probe

```text
concurrency: 24
requests_per_concurrency: 2
warmup_turns: 1
warmup_max_tokens: 1
max_tokens: 2048
shared_prefix: true
fixed_prefix_tokens: 60000
actual prompt tokens: ~60494
```

Result:

```text
ok: 48/48
wall_s: 38.9
generation_tps_total: 2527.52 tok/s
tok/s/user: 105.31
latency_avg: 18.84s
latency_p95: 20.31s
max_running: 24
max_waiting: 0
max_kv: 15.3%
queue_avg_s: 0.09
TTFT_avg_s: 2.65
```

Best server window:

```text
3234.5 tok/s @ 24 running = 134.8 tok/s/running user
```

MTP acceptance:

```text
best windows ~80-82% draft acceptance
```

### c=128 quick peak-TPS probe

```text
concurrency: 128
requests_per_concurrency: 2
warmup_turns: 1
warmup_max_tokens: 1
max_tokens: 1024
shared_prefix: true
fixed_prefix_tokens: 60000
actual prompt tokens: ~60494
```

Result:

```text
ok: 256/256
wall_s: 69.1
generation_tps_total: 3782.01 tok/s
tok/s/user: 29.55
latency_avg: 32.15s
latency_p95: 46.42s
max_running: 128
max_waiting: 12
max_kv: 75.7%
queue_avg_s: 0.08
TTFT_avg_s: 5.26
```

Server decode windows:

```text
3899.2 tok/s @ 118 running
3478.6 tok/s @ 123 running
5327.6 tok/s @ 99 running  # best observed window
```

MTP acceptance:

```text
main windows ~64-72% draft acceptance
tail window ~77.7%
```

Interpretation: this is the best aggregate throughput measured in the quick peak-TPS lane.

### c=192 oversaturation probe

```text
concurrency: 192
requests_per_concurrency: 2
warmup_turns: 1
warmup_max_tokens: 1
max_tokens: 1024
shared_prefix: true
fixed_prefix_tokens: 60000
actual prompt tokens: ~60494
```

Result:

```text
ok: 384/384
wall_s: 127.5
generation_tps_total: 3070.64 tok/s
tok/s/user: 15.99
latency_avg: 58.81s
latency_p95: 80.02s
latency_max: 107.67s
max_running: 178
max_waiting: 33
max_kv: 99.9%
queue_avg_s: 5.26
TTFT_avg_s: 12.35
```

Interpretation:

```text
c=192 is past the saturation cliff for this 60K-prefix TPS shape.
Aggregate throughput dropped from 3782 tok/s at c=128 to 3071 tok/s.
KV reached ~100%, and queueing/waiting became significant.
```

### c=24 sustained agentic run

This run was added after deciding that agentic service tests should use much larger response caps than the quick TPS probes.

```text
concurrency: 24
requests_per_concurrency: 4
warmup_turns: 1
warmup_max_tokens: 1
max_tokens: 20000
shared_prefix: true
fixed_prefix_tokens: 30000
actual prompt tokens: 30494
post_warmup_gap: 2s
```

Total planned work:

```text
warmup requests: 24
measured requests: 24 * 4 = 96
max possible generated tokens: 96 * 20000 = 1,920,000
```

Result:

```text
ok: 96/96
errors: 0
wall_s: 398.3
generation_tps_total: 2844.91 tok/s
tok/s/user: 118.54
rps: 0.24
client_prompt_tps: 7352.83
client_total_tps: 10197.74
latency_avg: 76.92s
latency_p50: 69.91s
latency_p95: 130.48s
latency_max: 133.01s
max_running: 24
max_waiting: 7
max_kv: 19.8%
queue_avg_s: 0.03
TTFT_avg_s: 0.70
```

Server sustained decode windows:

```text
3553.6 tok/s @ 24 running, KV 17.5%, draft acceptance 85.1%
3437.2 tok/s @ 23 running, KV 17.0%, draft acceptance 83.4%
3509.4 tok/s @ 24 running, KV 18.0%, draft acceptance 85.1%
3378.8 tok/s @ 23 running, KV 16.5%, draft acceptance 84.6%
3519.1 tok/s @ 24 running, KV 17.5%, draft acceptance 83.2%
3353.0 tok/s @ 20 running, KV 15.0%, draft acceptance 83.1%
```

MTP acceptance during sustained middle:

```text
avg draft acceptance: ~83-86%
pos0: ~93-94%
pos1: ~83-85%
pos2: ~73-76%
```

Interpretation:

```text
This is the best current service-shaped result: long output cap, four sequential measured turns per user, low KV pressure, and stable sustained decode windows around 3.3k-3.55k tok/s.
The end-to-end measured average was 2.845k tok/s because the full run includes wave turnover and tail drain.
```

### c=64 sustained agentic run

Same agentic shape as the c=24 sustained run, but higher concurrency.

```text
concurrency: 64
requests_per_concurrency: 4
warmup_turns: 1
warmup_max_tokens: 1
max_tokens: 20000
shared_prefix: true
fixed_prefix_tokens: 30000
actual prompt tokens: 30494
post_warmup_gap: 2s
```

Total planned work:

```text
warmup requests: 64
measured requests: 64 * 4 = 256
max possible generated tokens: 256 * 20000 = 5,120,000
```

Result:

```text
ok: 256/256
errors: 0
wall_s: 637.5
generation_tps_total: 4942.33 tok/s
tok/s/user: 77.22
rps: 0.40
client_prompt_tps: 12249.74
client_total_tps: 17192.07
latency_avg: 129.67s
latency_p50: 118.09s
latency_p95: 216.89s
latency_max: 221.23s
max_running: 64
max_waiting: 12
max_kv: 50.3%
queue_avg_s: 0.11
TTFT_avg_s: 1.22
```

Server sustained decode windows:

```text
5693.7 tok/s @ 60 running, KV 47.2%, draft acceptance 87.9%
5491.3 tok/s @ 58 running, KV 46.2%, draft acceptance 88.4%
5162.3 tok/s @ 56 running, KV 43.1%, draft acceptance 87.3%
5252.4 tok/s @ 55 running, KV 43.3%, draft acceptance 86.1%
4756.2 tok/s @ 54 running, KV 39.8%, draft acceptance 84.9%
4716.1 tok/s @ 52 running, KV 36.8%, draft acceptance 81.7%
```

MTP acceptance during sustained middle:

```text
avg draft acceptance: ~82-88%
pos0: ~92-95%
pos1: ~82-88%
pos2: ~72-82%
```

Interpretation:

```text
c=64 substantially improved aggregate throughput over c=24 agentic: 4942 tok/s vs 2845 tok/s.
Per-user throughput dropped from 118.5 to 77.2 tok/s/user, but this is still strong for long-output agentic mode.
KV remained below saturation at ~50%, and queueing stayed low on average, so c=64 is a good current service-shaped aggregate point.
```

### c=96 sustained agentic run

Same agentic shape as c=24 and c=64, testing the likely sweet spot between c=64 and the saturated c=128 run.

```text
concurrency: 96
requests_per_concurrency: 4
warmup_turns: 1
warmup_max_tokens: 1
max_tokens: 20000
shared_prefix: true
fixed_prefix_tokens: 30000
actual prompt tokens: 30494
post_warmup_gap: 2s
```

Total planned work:

```text
warmup requests: 96
measured requests: 96 * 4 = 384
max possible generated tokens: 384 * 20000 = 7,680,000
```

Result:

```text
ok: 384/384
errors: 0
wall_s: 843.7
generation_tps_total: 5574.90 tok/s
tok/s/user: 58.07
rps: 0.46
client_prompt_tps: 13883.36
client_total_tps: 19458.27
latency_avg: 173.91s
latency_p50: 157.35s
latency_p95: 294.98s
latency_max: 304.04s
max_running: 96
max_waiting: 2
max_kv: 75.3%
queue_avg_s: 0.11
TTFT_avg_s: 1.34
```

Server decode windows near the sustained high-throughput section:

```text
5911.8 tok/s @ 85 running, KV 64.7%, draft acceptance 86.5%
5448.0 tok/s @ 84 running, KV 62.7%, draft acceptance 84.0%
5446.9 tok/s @ 84 running, KV 60.6%, draft acceptance 81.4%
5716.3 tok/s @ 82 running, KV 59.7%, draft acceptance 82.7%
5928.4 tok/s @ 77 running, KV 56.6%, draft acceptance 83.8%
5717.4 tok/s @ 71 running, KV 52.5%, draft acceptance 84.7%
```

MTP acceptance during sustained middle:

```text
avg draft acceptance: ~81-87%
pos0: ~92-95%
pos1: ~81-87%
pos2: ~71-79%
```

Interpretation:

```text
c=96 is currently the best service-shaped point: it beat c=128 on aggregate throughput while avoiding c=128's KV saturation and high queueing.
Compared with c=64, aggregate improved from 4942 to 5575 tok/s (+12.8%) while per-user TPS dropped from 77.2 to 58.1 tok/s.
Compared with c=128, aggregate improved from 5450 to 5575 tok/s (+2.3%), per-user TPS improved 36%, max KV stayed at ~75% instead of 100%, and queue_avg stayed ~0.11s instead of ~13s.
```

### c=128 sustained agentic run

Same agentic shape as c=24 and c=64, but pushed to 128 concurrent simulated users.

```text
concurrency: 128
requests_per_concurrency: 4
warmup_turns: 1
warmup_max_tokens: 1
max_tokens: 20000
shared_prefix: true
fixed_prefix_tokens: 30000
actual prompt tokens: 30494
post_warmup_gap: 2s
```

Total planned work:

```text
warmup requests: 128
measured requests: 128 * 4 = 512
max possible generated tokens: 512 * 20000 = 10,240,000
```

Result:

```text
ok: 512/512
errors: 0
wall_s: 1124.5
generation_tps_total: 5449.96 tok/s
tok/s/user: 42.58
rps: 0.46
client_prompt_tps: 13889.09
client_total_tps: 19339.04
latency_avg: 241.79s
latency_p50: 225.13s
latency_p95: 417.22s
latency_max: 452.75s
max_running: 128
max_waiting: 26
max_kv: 100.0%
queue_avg_s: 13.02
TTFT_avg_s: 14.56
```

Server decode windows near the high-throughput section:

```text
6025.1 tok/s @ 103 running, KV 91.7%, draft acceptance 83.5%
6388.6 tok/s @ 99 running, KV 88.9%, draft acceptance 84.7%
6503.9 tok/s @ 97 running, KV 87.4%, draft acceptance 86.1%
6520.9 tok/s @ 97 running, KV 88.7%, draft acceptance 87.2%
6388.9 tok/s @ 93 running, KV 83.9%, draft acceptance 86.3%
6466.5 tok/s @ 92 running, KV 84.8%, draft acceptance 86.4%
```

MTP acceptance during sustained middle:

```text
avg draft acceptance: ~83-87%
pos0: ~93-95%
pos1: ~84-88%
pos2: ~74-79%
```

Interpretation:

```text
c=128 produced high server windows peaking around 6.5k tok/s, but its full-run aggregate was slightly worse than c=96.
The run hit KV saturation at 100%, queueing rose materially, and p95 latency reached ~417s.
This is useful as an upper saturation point, but c=96 is the better current service-shaped target.
```

## Comparison to PRO 6000 WS datapoint

User observed a PRO 6000 WS online running this model around:

```text
96 concurrent * 24 tok/s/user = 2304 tok/s aggregate
```

Compared with B200 quick c=128:

```text
B200: 3782 tok/s aggregate
PRO 6000 WS observed: 2304 tok/s aggregate
B200 aggregate lift: 3782 / 2304 = 1.64x
B200 submitted-user TPS lift: 29.55 / 24 = 1.23x
```

Compared with B200 sustained c=24 agentic:

```text
B200: 2845 tok/s aggregate
B200 per-user at c=24: 118.5 tok/s/user
```

This is not apples-to-apples with the PRO 6000 WS `c=96` datapoint, but it shows the B200 has strong low/moderate-concurrency per-user performance and higher aggregate peak.

## Caveats

1. These are not all apples-to-apples.

```text
c=2 and c=24 quick used max_tokens=2048
c=128 and c=192 used max_tokens=1024
agentic runs used max_tokens=20000 and 30K prefix
```

2. Shared-prefix mode is intentional for decode/TPS tests, not for KV-store residency tests.

3. `max_tokens` is a response/completion token cap. Actual generations can stop earlier.

4. The agentic runs used a shorter 30K shared prefix to reduce unnecessary KV footprint for long-output service testing.

5. FP8 KV cache scaling/calibration remains a quality caveat to review separately.

## Recommended Next Tests

For a cleaner quick TPS curve under one shape:

```text
shared_prefix=true
fixed_prefix_tokens=30000 or 60000, choose one and keep fixed
warmup_turns=1
warmup_max_tokens=1
requests_per_concurrency=2
max_tokens=1024
concurrency sweep: 48, 64, 96, 128, 160
```

For service-shaped agentic testing:

```text
shared_prefix=true
fixed_prefix_tokens=30000
warmup_turns=1
warmup_max_tokens=1
requests_per_concurrency=4
max_tokens=20000
concurrency points already measured: 24, 64, 96, 128
recommended next curve points: 80, 112
```

c=96 is the current sweet spot under this shape. c=128 is known to hit KV saturation and high queueing.
