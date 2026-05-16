# B200 Burn-in Metrics Report: Carnice v2 27B NVFP4 Text MTP, 128-way long generation

Generated: `2026-05-16T07:28:52Z`
Window: `2026-05-16T07:07:42Z` to `2026-05-16T07:26:36Z`

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
| configured concurrency | 128 |
| measured requests per simulated user | 4 |
| warmup turns | 1 |
| warmup max tokens | 1 |
| measured max tokens | 20,000 |
| shared prefix | true |
| fixed prefix tokens | 30,000 |
| max model length | 262,144 |

## Recorded sample coverage

| Metric | Value |
| --- | --- |
| all interval windows | 110 |
| active interval windows | 110 |
| first active sample | 2026-05-16T07:07:42Z |
| last active sample | 2026-05-16T07:26:36Z |
| latest recorded total TPS sample | 2026-05-16T07:26:36Z / 31.89 |

## Throughput summary from interval samples

| Metric | Value |
| --- | --- |
| prompt tokens | 19,431,785 |
| generation tokens | 5,969,956 |
| total tokens | 25,401,741 |
| prompt TPS avg / p95 / max | 17,416.29 / 36,106.45 / 385,149.70 |
| generation TPS avg / p95 / max | 5,349.83 / 7,387.75 / 7,518.44 |
| total TPS avg / p95 / max | 22,766.12 / 40,064.40 / 386,322.51 |
| generation TPS per active request avg / p95 / max | 69.49 / 179.14 / 572.77 |
| total TPS per active request avg / p95 / max | 195.85 / 481.33 / 3,018.14 |

## Concurrency and cache gauges

| Gauge | Value |
| --- | --- |
| running requests avg / p95 / max | 101.59 / 128.00 / 128.00 |
| waiting requests avg / p95 / max | 5.95 / 23.00 / 26.00 |
| KV cache usage avg / p95 / max | 83.9% / 99.8% / 100.0% |

## Cumulative counter deltas in report window

| Counter | Delta | Status |
| --- | --- | --- |
| vllm.request_success_stop_total | 416.00 | ok |
| vllm.request_success_length_total | 96.00 | ok |
| vllm.request_success_error_total | 0.00 | ok |
| vllm.request_success_abort_total | 0.00 | ok |
| vllm.prompt_tokens_total | 15,618,640.00 | ok |
| vllm.generation_tokens_total | 6,128,617.00 | ok |
| vllm.ttft_count | 512.00 | ok |
| vllm.ttft_sum_seconds | 7,456.17 | ok |
| vllm.inference_count | 512.00 | ok |
| vllm.inference_sum_seconds | 116,440.63 | ok |
| vllm.queue_count | 512.00 | ok |
| vllm.queue_sum_seconds | 6,667.74 | ok |

## Latency averages from counters

| Metric | Average |
| --- | --- |
| TTFT | 14.56 s |
| inference | 227.42 s |
| queue | 13.02 s |

## Latest active windows

| sampled_at | running | waiting | KV | prompt Δ | gen Δ | total TPS | gen TPS/request |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 2026-05-16T07:24:00Z | 68 | 0 | 60.9% | 122,021 | 55,412 | 17,495.95 | 80.35 |
| 2026-05-16T07:24:10Z | 64 | 0 | 56.4% | 61,009 | 56,744 | 11,605.95 | 87.39 |
| 2026-05-16T07:24:20Z | 56 | 0 | 48.0% | 91,515 | 54,517 | 14,408.27 | 96.05 |
| 2026-05-16T07:24:31Z | 51 | 0 | 42.7% | 91,515 | 51,453 | 14,100.32 | 99.50 |
| 2026-05-16T07:24:41Z | 45 | 0 | 36.9% | 61,009 | 48,027 | 10,756.08 | 105.28 |
| 2026-05-16T07:24:52Z | 43 | 0 | 36.0% | 30,505 | 47,302 | 7,678.80 | 108.56 |
| 2026-05-16T07:25:02Z | 41 | 0 | 35.3% | 0 | 44,767 | 4,412.48 | 107.62 |
| 2026-05-16T07:25:12Z | 32 | 0 | 28.2% | 0 | 43,517 | 4,289.68 | 134.05 |
| 2026-05-16T07:25:23Z | 25 | 0 | 22.5% | 0 | 43,114 | 4,253.61 | 170.14 |
| 2026-05-16T07:25:33Z | 19 | 0 | 16.4% | 61,010 | 34,523 | 9,418.72 | 179.14 |
| 2026-05-16T07:25:44Z | 16 | 0 | 14.2% | 0 | 31,843 | 3,138.18 | 196.14 |
| 2026-05-16T07:25:54Z | 8 | 0 | 7.4% | 0 | 22,746 | 2,240.68 | 280.08 |
| 2026-05-16T07:26:04Z | 4 | 0 | 3.9% | 0 | 13,213 | 1,303.13 | 325.78 |
| 2026-05-16T07:26:15Z | 3 | 0 | 3.4% | 0 | 8,877 | 875.60 | 291.87 |
| 2026-05-16T07:26:25Z | 1 | 0 | 1.7% | 0 | 5,807 | 572.77 | 572.77 |
| 2026-05-16T07:26:36Z | 0 | 0 | 0.0% | 0 | 323 | 31.89 | n/a |
