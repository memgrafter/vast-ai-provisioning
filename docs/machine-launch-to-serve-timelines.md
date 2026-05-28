# Machine launch-to-serve timelines

This file records observed Vast.ai launch timelines from offer selection through external vLLM API readiness and first smoke request.

## Table of contents

- [2026-05-27 — Carnice NVFP4 MTP3, 2x RTX 5060 Ti, 160K fp8 KV, c=2 smoke then 160K OOM](#2026-05-27--carnice-nvfp4-mtp3-2x-rtx-5060-ti-160k-fp8-kv-c2-smoke-then-160k-oom)
- [2026-05-27 — Carnice NVFP4 MTP3, 2x RTX 5060 Ti, 160K fp8 KV, c=1 / 90% failed KV sizing](#2026-05-27--carnice-nvfp4-mtp3-2x-rtx-5060-ti-160k-fp8-kv-c1--90-failed-kv-sizing)
- [2026-05-27 — Carnice NVFP4 MTP3, 2x RTX 5060 Ti, 153.5K fp8 KV, c=1 / 91% successful edge test](#2026-05-27--carnice-nvfp4-mtp3-2x-rtx-5060-ti-1535k-fp8-kv-c1--91-successful-edge-test)
- [2026-05-27 — Qwen3.6 27B AWQ, 2x RTX 3090, 160K fp8 KV MTP2, failed external smoke](#2026-05-27--qwen36-27b-awq-2x-rtx-3090-160k-fp8-kv-mtp2-failed-external-smoke)

## 2026-05-27 — Carnice NVFP4 MTP3, 2x RTX 5060 Ti, 160K fp8 KV, c=2 smoke then 160K OOM

Profile:

```text
config/launch-profiles/carnice-v2-27b-nvfp4-text-mtp.rtx5060ti-2gpu.agentic-160k-fp8kv-mtp3.on-demand.json
```

Instance:

```text
instance_id: 38130143
machine_id: 113463
gpu: 2x RTX 5060 Ti
hourly_cost: $0.4171/hr
endpoint: http://<host>:<mapped_port>/v1
```

Timeline, UTC:

```text
19:40:40  Launch command started
19:40:44  Offer selected, Vast create returned, instance ID 38130143
19:44:40  Docker image setup done; instance status running
19:44:42  Provisioning script detected
19:44:43  R2 sync started
19:46:37  R2 sync finished
19:46:38  Provisioning complete
19:47:09  vLLM model architecture resolved
19:47:18  MTP draft architecture resolved
19:47:29  vLLM engine init started
19:47:48  Main weights loaded
19:47:50  Model loading reported complete
19:51:31  KV cache profiled: 56,000 tokens
19:51:31  Max concurrency for 160K request: 1.22x
19:51:44  vLLM server started on local port 18000
19:52:02  External /v1/models ready on mapped port 42484
19:52:02  First smoke request started
19:52:08  First smoke request completed HTTP 200
```

Durations from launch start:

```text
Create/instance ID:        0:04
Docker setup done:         4:00
Provisioning started:      4:02
R2 sync started:           4:03
R2 sync finished:          5:57
Provisioning complete:     5:58
vLLM engine init:          6:49
KV profiling complete:    10:51
External API ready:       11:22
Smoke complete:           11:28
```

Smoke metrics:

```text
/v1/models: HTTP 200
/v1/chat/completions: HTTP 200
smoke_request_elapsed: 6.32s
prompt_tokens: 17
generation_tokens: 32
TTFT: ~2.85s
inference_time: ~5.93s
```

Notes:

```text
The instance reached API readiness and passed smoke, but vLLM reported only
1.22x maximum concurrency for 160,000-token requests. This does not meet the
concurrency >= 2 full-context target.
```

Post-smoke max-context probe:

```text
19:58:26  Tokenized near-max prompt
19:58:28  Confirmed prompt_tokens=159,999
19:58:28  Sent chat request with max_tokens=1
19:58:30  HTTP 500; EngineCore failed
19:58:31  Worker_TP0 and Worker_TP1 reported CUDA OOM
```

Failure detail:

```text
prompt_tokens: 159,999
max_tokens: 1
chat_http: 500
error: torch.OutOfMemoryError during Qwen3.5 hybrid/Mamba FLA chunk allocation
allocation: 94 MiB per GPU
per-GPU total: 15.48 GiB
per-GPU process memory: 15.39 GiB (~99.4%)
per-GPU free: 84.62 MiB (~0.5%)
```

Restart attempt on the same config:

```text
20:11:52  Reboot requested after OOM-wedged API
20:14:06  vLLM startup failed again before API readiness
```

Restart failure detail:

```text
gpu_memory_utilization: 0.95
max_num_seqs: 2
max_model_len: 160,000
error: CUDA out of memory during EngineCore startup
allocation: 272 MiB
per-GPU free: 206.62 MiB
process memory: 15.27 / 15.48 GiB (~98.6%)
```

Outcome:

```text
Destroyed before relaunching lower-utilization variants.
Conclusion: 160K at c=2 / 95% is unstable on 2x16GB RTX 5060 Ti.
```

## 2026-05-27 — Carnice NVFP4 MTP3, 2x RTX 5060 Ti, 160K fp8 KV, c=1 / 90% failed KV sizing

Profile:

```text
config/launch-profiles/carnice-v2-27b-nvfp4-text-mtp.rtx5060ti-2gpu.agentic-160k-fp8kv-mtp3.on-demand.json
```

Instance:

```text
instance_id: 38134004
machine_id: 113463
gpu: 2x RTX 5060 Ti
hourly_cost: $0.4171/hr
endpoint: http://<host>:<mapped_port>/v1
```

Configuration:

```text
max_model_len: 160,000
gpu_memory_utilization: 0.90
max_num_seqs: 1
tensor_parallel_size: 2
kv_cache_dtype: fp8
MTP: qwen3_5_mtp, 3 speculative tokens
```

Timeline, UTC:

```text
20:21:03  Launch command started
20:21:05  Offer selected, Vast create returned, instance ID 38134004
20:21:38  Instance running; endpoint mapped
20:21:40  Provisioning / R2 sync already visible
20:23:22  R2 sync finished
20:23:23  Provisioning complete
20:24:19  vLLM EngineCore init started
20:27:40  Shared-memory wait warning during profiling/compile
20:27:52  Initial profiling/warmup run took 78.34s
20:28:07  Torch compile graph completed
20:28:16  KV sizing failed; EngineCore failed to start
20:28:25  vLLM process exited; API remained 502
```

Failure detail:

```text
Available KV cache memory: 2.9 GiB
Required KV cache for one 160K request: 2.98 GiB
Estimated maximum model length at 90%: 153,600
error: ValueError before API readiness
```

Outcome:

```text
Destroyed before relaunching 153.5K / 91% variant.
Conclusion: 160K at c=1 / 90% does not allocate enough KV cache.
```

## 2026-05-27 — Carnice NVFP4 MTP3, 2x RTX 5060 Ti, 153.5K fp8 KV, c=1 / 91% successful edge test

Profile:

```text
config/launch-profiles/carnice-v2-27b-nvfp4-text-mtp.rtx5060ti-2gpu.agentic-160k-fp8kv-mtp3.on-demand.json
```

Instance:

```text
instance_id: 38136222
machine_id: 113463
gpu: 2x RTX 5060 Ti
hourly_cost: $0.4171/hr
endpoint: http://<host>:<mapped_port>/v1
```

Configuration:

```text
max_model_len: 153,500
gpu_memory_utilization: 0.91
max_num_seqs: 1
tensor_parallel_size: 2
kv_cache_dtype: fp8
MTP: qwen3_5_mtp, 3 speculative tokens
```

Timeline, UTC:

```text
20:42:14  Launch command started
20:42:17  Offer selected, Vast create returned, instance ID 38136222
20:42:48  Instance running; endpoint mapped
20:42:48  R2 sync visible; external API still 502
20:44:33  R2 sync finished and provisioning complete
20:45:24  vLLM EngineCore init started
20:49:20  KV cache profiled: 46,400 tokens
20:49:20  Max concurrency for 153,500-token request: 1.05x
20:49:34  vLLM local server started; external /v1/models returned HTTP 200
20:49:34  API ready
20:50-ish Short smoke chat returned HTTP 200 in 6.26s
```

Durations from launch start:

```text
Create/instance ID:        0:03
Instance running:          0:34
R2/provisioning visible:   0:34
R2 sync/provisioning done: 2:19
vLLM engine init:          3:10
KV profiling complete:     7:06
External API ready:        7:20
```

vLLM startup memory/KV:

```text
world_size: 2
rank 0 / rank 1 active via NCCL
--gpu-memory-utilization=0.9100
effective utilization without CUDA graph profiling: 0.9034
Available KV cache memory: 3.05 GiB
GPU KV cache size: 46,400 tokens
Maximum concurrency for 153,500 tokens/request: 1.05x
```

Prompt ramp, c=1, max_tokens=1:

```text
30,000   prompt tokens + 1 output: HTTP 200, 20.54s
60,000   prompt tokens + 1 output: HTTP 200, 26.34s
90,000   prompt tokens + 1 output: HTTP 200, 31.14s
120,000  prompt tokens + 1 output: HTTP 200, 36.28s
150,000  prompt tokens + 1 output: HTTP 200, 41.00s
153,000  prompt tokens + 1 output: HTTP 200, 9.30s  (prefix-cache aided)
153,400  prompt tokens + 1 output: HTTP 200, 5.37s  (prefix-cache aided)
153,490  prompt tokens + 1 output: HTTP 200, 5.95s  (prefix-cache aided)
153,499  prompt tokens + 1 output: HTTP 200, 5.52s  (prefix-cache aided)
153,500  prompt tokens + 1 output: HTTP 400 context limit
153,501  prompt tokens + 1 output: HTTP 400 context limit
```

Edge result:

```text
Maximum successful request shape: 153,499 prompt tokens + 1 output token = 153,500 total tokens.
The server correctly rejects 153,500 prompt tokens + 1 output token because total requested tokens exceed max_model_len.
```

Metrics after ramp:

```text
requests length: 9
errors: 0
prompt_tokens_total: 909,907
generation_tokens_total: 40
prefix cache hit rate: ~81.2%
avg TTFT: ~18.96s
avg inference: ~19.09s
idle KV cache usage after ramp: 0.0%
```

Outcome:

```text
Successful c=1 near-max-context profile. Keep running for follow-up tests.
This profile does not meet c>=2, but it reaches the practical c=1 context ceiling on 2x16GB RTX 5060 Ti.
```

## 2026-05-27 — Qwen3.6 27B AWQ, 2x RTX 3090, 160K fp8 KV MTP2, failed external smoke

Instance details:

```text
instance_id: 38111733
machine_id: 57625
host_id: 315182
offer_id: 36465153
location: Japan
cost: ~$0.404/hr
```

Timeline, UTC:

```text
17:04:52  create submitted
17:04:53  create returned
17:22:43  instance reached running / provisioning visible
17:22:55  R2 sync started
17:27:05  rclone showed ~100% transferred at ~83 MB/s
17:35:36  R2 sync officially finished
17:35:38  provisioning complete
17:36:34  vLLM workers started loading model
17:39:57  target weights loaded; 201.8s
17:40:14  model loading complete; 218.9s total
17:43:09  KV cache ready: 156,800 tokens, max concurrency 3.52x
17:43:19  vLLM local API started on 127.0.0.1:18000
17:46:55  external API probes began; public port timed out
17:55:34  instance destroyed
```

Findings:

```text
R2/network was fine: ~85 MB/s speed test, ~83 MB/s transfer.
Disk/finalization was bad: ~8.5 min after transfer reached 100%.
vLLM loaded successfully locally.
Public Vast port/SSH were blackholed, so smoke could not reach it.
```

Outcome:

```text
Failed external smoke; destroyed; machine 57625 greylisted.
```
