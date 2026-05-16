# B200 Burn-in Metrics Report: Carnice v2 27B NVFP4 Text MTP, 24-way long generation

Generated: `2026-05-16T07:41:39Z`
Window: `2026-05-16T06:42:32Z` to `2026-05-16T06:49:20Z`

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
| configured concurrency | 24 |
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
| all interval windows | 40 |
| active interval windows | 40 |
| first active sample | 2026-05-16T06:42:32Z |
| last active sample | 2026-05-16T06:49:20Z |
| latest recorded total TPS sample | 2026-05-16T06:49:20Z / 22.48 |

## Throughput summary from interval samples

| Metric | Value |
| --- | --- |
| prompt tokens | 3,599,546 |
| generation tokens | 1,101,342 |
| total tokens | 4,700,888 |
| prompt TPS avg / p95 / max | 8,857.70 / 21,056.60 / 72,229.00 |
| generation TPS avg / p95 / max | 2,708.43 / 3,813.34 / 3,882.08 |
| total TPS avg / p95 / max | 11,566.13 / 24,319.83 / 74,781.79 |
| generation TPS per active request avg / p95 / max | 181.20 / 283.04 / 361.84 |
| total TPS per active request avg / p95 / max | 534.28 / 1,013.33 / 3,115.91 |

## Concurrency and cache gauges

| Gauge | Value |
| --- | --- |
| running requests avg / p95 / max | 17.30 / 24.00 / 24.00 |
| waiting requests avg / p95 / max | 0.00 / 0.00 / 0.00 |
| KV cache usage avg / p95 / max | 13.1% / 18.9% / 19.8% |

## Cumulative counter deltas in report window

| Counter | Delta | Status |
| --- | --- | --- |
| vllm.request_success_stop_total | 78.00 | ok |
| vllm.request_success_length_total | 18.00 | ok |
| vllm.request_success_error_total | 0.00 | ok |
| vllm.request_success_abort_total | 0.00 | ok |
| vllm.prompt_tokens_total | 2,928,444.00 | ok |
| vllm.generation_tokens_total | 1,133,056.00 | ok |
| vllm.ttft_count | 96.00 | ok |
| vllm.ttft_sum_seconds | 67.50 | ok |
| vllm.inference_count | 96.00 | ok |
| vllm.inference_sum_seconds | 7,322.73 | ok |
| vllm.queue_count | 96.00 | ok |
| vllm.queue_sum_seconds | 3.33 | ok |

## Latency averages from counters

| Metric | Average |
| --- | --- |
| TTFT | 0.70 s |
| inference | 76.28 s |
| queue | 0.03 s |

## Latest active windows

| sampled_at | running | waiting | KV | prompt Δ | gen Δ | total TPS | gen TPS/request |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 2026-05-16T06:47:24Z | 16 | 0 | 12.8% | 91,514 | 29,909 | 11,972.59 | 184.32 |
| 2026-05-16T06:47:35Z | 14 | 0 | 11.1% | 30,505 | 28,204 | 5,787.65 | 198.60 |
| 2026-05-16T06:47:45Z | 12 | 0 | 9.8% | 0 | 25,820 | 2,546.47 | 212.21 |
| 2026-05-16T06:47:56Z | 8 | 0 | 6.8% | 30,504 | 20,751 | 5,051.16 | 255.63 |
| 2026-05-16T06:48:06Z | 4 | 0 | 3.6% | 0 | 14,675 | 1,447.38 | 361.84 |
| 2026-05-16T06:48:17Z | 3 | 0 | 3.0% | 0 | 8,034 | 784.95 | 261.65 |
| 2026-05-16T06:48:27Z | 3 | 0 | 3.2% | 0 | 7,556 | 744.45 | 248.15 |
| 2026-05-16T06:48:38Z | 3 | 0 | 2.9% | 30,504 | 7,376 | 3,730.25 | 242.12 |
| 2026-05-16T06:48:48Z | 2 | 0 | 2.3% | 0 | 6,673 | 657.37 | 328.69 |
| 2026-05-16T06:48:59Z | 2 | 0 | 2.4% | 0 | 5,744 | 566.08 | 283.04 |
| 2026-05-16T06:49:09Z | 1 | 0 | 1.4% | 0 | 2,837 | 279.51 | 279.51 |
| 2026-05-16T06:49:20Z | 0 | 0 | 0.0% | 0 | 228 | 22.48 | n/a |
