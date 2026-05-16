# B200 Burn-in Metrics Report: Carnice v2 27B NVFP4 Text MTP, 64-way long generation

Generated: `2026-05-16T07:41:39Z`
Window: `2026-05-16T06:54:53Z` to `2026-05-16T07:05:26Z`

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

## Workload configuration

| Field | Value |
| --- | --- |
| configured concurrency | 64 |
| measured requests per simulated user | 4 |
| warmup turns | 1 |
| warmup max tokens | 1 |
| measured max tokens | 20,000 |
| shared prefix | true |
| fixed prefix tokens | 30,000 |
| max model length | 262,144 |
| workload shape | long generation |

## Recorded sample coverage

| Metric | Value |
| --- | --- |
| all interval windows | 62 |
| active interval windows | 62 |
| first active sample | 2026-05-16T06:54:53Z |
| last active sample | 2026-05-16T07:05:26Z |
| latest recorded total TPS sample | 2026-05-16T07:05:26Z / 371.11 |

## Throughput summary from interval samples

| Metric | Value |
| --- | --- |
| prompt tokens | 9,273,477 |
| generation tokens | 3,076,432 |
| total tokens | 12,349,909 |
| prompt TPS avg / p95 / max | 14,691.25 / 24,100.21 / 270,126.41 |
| generation TPS avg / p95 / max | 4,893.54 / 6,382.64 / 6,433.00 |
| total TPS avg / p95 / max | 19,584.79 / 29,528.68 / 270,453.08 |
| generation TPS per active request avg / p95 / max | 111.57 / 229.35 / 373.38 |
| total TPS per active request avg / p95 / max | 414.98 / 573.57 / 7,117.19 |

## Concurrency and cache gauges

| Gauge | Value |
| --- | --- |
| running requests avg / p95 / max | 51.02 / 64.00 / 64.00 |
| waiting requests avg / p95 / max | 0.19 / 0.00 / 12.00 |
| KV cache usage avg / p95 / max | 37.7% / 49.0% / 50.1% |

## Cumulative counter deltas in report window

| Counter | Delta | Status |
| --- | --- | --- |
| vllm.request_success_stop_total | 200.00 | ok |
| vllm.request_success_length_total | 56.00 | ok |
| vllm.request_success_error_total | 0.00 | ok |
| vllm.request_success_abort_total | 0.00 | ok |
| vllm.prompt_tokens_total | 6,985,616.00 | ok |
| vllm.generation_tokens_total | 3,147,454.00 | ok |
| vllm.ttft_count | 229.00 | ok |
| vllm.ttft_sum_seconds | 252.22 | ok |
| vllm.inference_count | 256.00 | ok |
| vllm.inference_sum_seconds | 32,920.84 | ok |
| vllm.queue_count | 256.00 | ok |
| vllm.queue_sum_seconds | 28.10 | ok |

## Latency averages from counters

| Metric | Average |
| --- | --- |
| TTFT | 1.10 s |
| inference | 128.60 s |
| queue | 0.11 s |

## Latest active windows

| sampled_at | running | waiting | KV | prompt Δ | gen Δ | total TPS | gen TPS/request |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 2026-05-16T07:03:32Z | 31 | 0 | 25.2% | 61,009 | 42,080 | 10,174.19 | 133.97 |
| 2026-05-16T07:03:42Z | 29 | 0 | 23.5% | 30,505 | 42,365 | 7,174.98 | 143.84 |
| 2026-05-16T07:03:53Z | 27 | 0 | 21.5% | 91,515 | 39,052 | 12,878.29 | 142.66 |
| 2026-05-16T07:04:03Z | 23 | 0 | 17.7% | 91,514 | 35,326 | 12,517.73 | 151.58 |
| 2026-05-16T07:04:14Z | 21 | 0 | 16.5% | 30,505 | 34,252 | 6,394.27 | 161.05 |
| 2026-05-16T07:04:24Z | 19 | 0 | 15.7% | 0 | 33,192 | 3,273.15 | 172.27 |
| 2026-05-16T07:04:35Z | 18 | 0 | 15.6% | 0 | 31,155 | 3,074.99 | 170.83 |
| 2026-05-16T07:04:45Z | 10 | 0 | 8.7% | 30,505 | 27,593 | 5,735.73 | 272.41 |
| 2026-05-16T07:04:55Z | 6 | 0 | 5.4% | 0 | 17,124 | 1,689.51 | 281.58 |
| 2026-05-16T07:05:06Z | 5 | 0 | 4.9% | 0 | 11,621 | 1,146.76 | 229.35 |
| 2026-05-16T07:05:16Z | 2 | 0 | 2.6% | 0 | 7,568 | 746.75 | 373.38 |
| 2026-05-16T07:05:26Z | 0 | 0 | 0.0% | 0 | 3,761 | 371.11 | n/a |
