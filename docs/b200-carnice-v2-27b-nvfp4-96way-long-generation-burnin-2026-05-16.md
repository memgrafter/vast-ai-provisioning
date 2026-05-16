# B200 Burn-in Metrics Report: Carnice v2 27B NVFP4 Text MTP, 96-way long generation

Generated: `2026-05-16T07:50:42Z`
Window: `2026-05-16T07:32:41Z` to `2026-05-16T07:46:43Z`

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
| configured concurrency | 96 |
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
| all interval windows | 82 |
| active interval windows | 82 |
| first active sample | 2026-05-16T07:32:41Z |
| last active sample | 2026-05-16T07:46:43Z |
| latest recorded total TPS sample | 2026-05-16T07:46:43Z / 451.04 |

## Throughput summary from interval samples

| Metric | Value |
| --- | --- |
| prompt tokens | 14,306,801 |
| generation tokens | 4,590,631 |
| total tokens | 18,897,432 |
| prompt TPS avg / p95 / max | 17,198.14 / 33,111.85 / 330,678.88 |
| generation TPS avg / p95 / max | 5,518.98 / 6,903.44 / 6,995.81 |
| total TPS avg / p95 / max | 22,717.12 / 38,921.23 / 330,927.13 |
| generation TPS per active request avg / p95 / max | 88.11 / 234.96 / 348.47 |
| total TPS per active request avg / p95 / max | 435.19 / 484.00 / 15,758.43 |

## Concurrency and cache gauges

| Gauge | Value |
| --- | --- |
| running requests avg / p95 / max | 77.38 / 96.00 / 96.00 |
| waiting requests avg / p95 / max | 0.00 / 0.00 / 0.00 |
| KV cache usage avg / p95 / max | 56.7% / 72.9% / 75.1% |

## Cumulative counter deltas in report window

| Counter | Delta | Status |
| --- | --- | --- |
| vllm.request_success_stop_total | 307.00 | ok |
| vllm.request_success_length_total | 77.00 | ok |
| vllm.request_success_error_total | 0.00 | ok |
| vllm.request_success_abort_total | 0.00 | ok |
| vllm.prompt_tokens_total | 11,286,819.00 | ok |
| vllm.generation_tokens_total | 4,701,319.00 | ok |
| vllm.ttft_count | 370.00 | ok |
| vllm.ttft_sum_seconds | 499.83 | ok |
| vllm.inference_count | 384.00 | ok |
| vllm.inference_sum_seconds | 66,302.93 | ok |
| vllm.queue_count | 384.00 | ok |
| vllm.queue_sum_seconds | 44.14 | ok |

## Latency averages from counters

| Metric | Average |
| --- | --- |
| TTFT | 1.35 s |
| inference | 172.66 s |
| queue | 0.11 s |

## Latest active windows

| sampled_at | running | waiting | KV | prompt Δ | gen Δ | total TPS | gen TPS/request |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 2026-05-16T07:44:48Z | 39 | 0 | 31.5% | 30,505 | 44,044 | 7,347.54 | 111.31 |
| 2026-05-16T07:44:59Z | 33 | 0 | 25.8% | 122,019 | 40,036 | 15,972.00 | 119.57 |
| 2026-05-16T07:45:09Z | 27 | 0 | 21.4% | 30,505 | 40,422 | 6,992.99 | 147.61 |
| 2026-05-16T07:45:20Z | 21 | 0 | 17.3% | 0 | 37,291 | 3,680.19 | 175.25 |
| 2026-05-16T07:45:30Z | 17 | 0 | 13.7% | 30,505 | 32,798 | 6,231.84 | 189.93 |
| 2026-05-16T07:45:41Z | 14 | 0 | 11.9% | 0 | 29,132 | 2,871.97 | 205.14 |
| 2026-05-16T07:45:51Z | 10 | 0 | 9.2% | 0 | 24,124 | 2,378.97 | 237.90 |
| 2026-05-16T07:46:01Z | 8 | 0 | 7.8% | 0 | 19,074 | 1,879.67 | 234.96 |
| 2026-05-16T07:46:12Z | 6 | 0 | 5.9% | 0 | 16,348 | 1,613.07 | 268.84 |
| 2026-05-16T07:46:22Z | 6 | 0 | 6.3% | 0 | 15,042 | 1,483.87 | 247.31 |
| 2026-05-16T07:46:32Z | 3 | 0 | 3.7% | 0 | 10,599 | 1,045.40 | 348.47 |
| 2026-05-16T07:46:43Z | 0 | 0 | 0.0% | 0 | 4,577 | 451.04 | n/a |
