# B200 Burn-in Metrics Report: Carnice v2 27B NVFP4 Text MTP

Generated: `2026-05-16T07:19:37Z`
Window: `2026-05-16T07:07:42Z` to `2026-05-16T07:18:58Z`

> Publish-safety: public IPs, mapped ports, raw URLs, auth data, local artifact paths, and raw JSON details are intentionally omitted. Provider IDs are redacted by default.

## Launch metadata

| Field | Value |
| --- | --- |
| workload model | carnice-v2-27b-nvfp4-text-mtp-b200-maxctx-mtp3 |
| launch-profile model | qwen3.6-27b-fp8 |
| launch-profile HF model | Qwen/Qwen3.6-27B-FP8 |
| model profile | qwen3.6-27b-fp8 |
| GPU profile | b200-1gpu |
| launch profile | qwen3.6-27b-fp8.b200.on-demand |
| market | on-demand |
| GPU | B200 x1 |
| GPU RAM | 183,359 MB |
| lifecycle | unknown |
| created_at | 2026-05-16T04:57:57Z |
| launch | redacted |
| instance_id | redacted |
| offer_id | redacted |
| machine_id | redacted |

## Cost and storage snapshot

| Metric | Value |
| --- | --- |
| total hourly | $3.9635 |
| compute hourly | $3.9375 |
| storage hourly | $0.0260 |
| requested disk | 100 GB |
| storage per requested GB-hour | $0.0003 |
| storage share of total | 0.7% |

## Recorded sample coverage

| Metric | Value |
| --- | --- |
| all interval windows | 66 |
| active interval windows | 66 |
| first active sample | 2026-05-16T07:07:42Z |
| last active sample | 2026-05-16T07:18:58Z |
| latest recorded total TPS sample | 2026-05-16T07:18:58Z / 28,222.79 |

## Throughput summary from interval samples

| Metric | Value |
| --- | --- |
| prompt tokens | 15,832,184 |
| generation tokens | 3,848,843 |
| total tokens | 19,681,027 |
| prompt TPS avg / p95 / max | 23,650.89 / 60,143.12 / 385,149.70 |
| generation TPS avg / p95 / max | 5,747.82 / 7,424.90 / 7,518.44 |
| total TPS avg / p95 / max | 29,398.70 / 64,418.46 / 386,322.51 |
| generation TPS per active request avg / p95 / max | 47.73 / 58.01 / 58.74 |
| total TPS per active request avg / p95 / max | 194.21 / 285.29 / 3,018.14 |

## Concurrency and cache gauges

| Gauge | Value |
| --- | --- |
| running requests avg / p95 / max | 119.98 / 128.00 / 128.00 |
| waiting requests avg / p95 / max | 5.76 / 20.00 / 22.00 |
| KV cache usage avg / p95 / max | 93.9% / 99.8% / 100.0% |

## Cumulative counter deltas in report window

| Counter | Delta | Status |
| --- | --- | --- |
| vllm.request_success_stop_total | 243.00 | ok |
| vllm.request_success_length_total | 42.00 | ok |
| vllm.request_success_error_total | 0.00 | ok |
| vllm.request_success_abort_total | 0.00 | ok |
| vllm.prompt_tokens_total | 12,019,039.00 | ok |
| vllm.generation_tokens_total | 3,955,603.00 | ok |
| vllm.ttft_count | 394.00 | ok |
| vllm.ttft_sum_seconds | 4,193.05 | ok |
| vllm.inference_count | 285.00 | ok |
| vllm.inference_sum_seconds | 65,816.13 | ok |
| vllm.queue_count | 285.00 | ok |
| vllm.queue_sum_seconds | 518.98 | ok |

## Latency averages from counters

| Metric | Average |
| --- | --- |
| TTFT | 10.64 s |
| inference | 230.93 s |
| queue | 1.82 s |

## Latest active windows

| sampled_at | running | waiting | KV | prompt Δ | gen Δ | total TPS | gen TPS/request |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 2026-05-16T07:17:04Z | 111 | 17 | 99.5% | 91,515 | 47,822 | 13,735.36 | 42.47 |
| 2026-05-16T07:17:14Z | 110 | 18 | 98.8% | 122,022 | 45,546 | 16,524.06 | 40.83 |
| 2026-05-16T07:17:25Z | 109 | 19 | 99.4% | 91,516 | 56,587 | 14,609.04 | 51.21 |
| 2026-05-16T07:17:35Z | 110 | 16 | 99.5% | 122,023 | 56,606 | 17,608.74 | 50.73 |
| 2026-05-16T07:17:45Z | 109 | 18 | 99.8% | 122,020 | 50,018 | 16,957.77 | 45.23 |
| 2026-05-16T07:17:56Z | 109 | 18 | 99.7% | 244,043 | 42,720 | 28,271.11 | 38.64 |
| 2026-05-16T07:18:06Z | 109 | 17 | 99.0% | 213,535 | 45,628 | 25,558.96 | 41.28 |
| 2026-05-16T07:18:17Z | 106 | 20 | 98.8% | 122,021 | 49,338 | 16,905.85 | 45.92 |
| 2026-05-16T07:18:27Z | 107 | 20 | 99.7% | 122,023 | 50,915 | 17,044.27 | 46.90 |
| 2026-05-16T07:18:38Z | 105 | 22 | 99.6% | 30,506 | 50,034 | 7,949.68 | 47.03 |
| 2026-05-16T07:18:48Z | 106 | 21 | 98.8% | 183,031 | 42,816 | 22,269.54 | 39.83 |
| 2026-05-16T07:18:58Z | 109 | 18 | 99.7% | 244,040 | 42,054 | 28,222.79 | 38.06 |
