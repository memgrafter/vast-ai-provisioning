# B200 Burn-in Metrics Report: qwen3.6-27b-awq

Generated: `2026-06-07T22:36:46Z`
Window: `2026-06-07T22:34:21Z` to `2026-06-07T22:36:46Z`

> Publish-safety: public IPs, mapped ports, raw URLs, auth data, local artifact paths, and raw JSON details are intentionally omitted. Provider IDs are redacted by default.

## Launch metadata

| Field | Value |
| --- | --- |
| workload model | qwen3.6-27b-awq |
| launch-profile model | qwen3.6-27b-awq |
| launch-profile HF model | QuantTrio/Qwen3.6-27B-AWQ |
| model profile | qwen3.6-27b-awq |
| GPU profile | qwen-27b-awq-48gb-rtx6000ada |
| launch profile | qwen3.6-27b-awq.stable |
| market | on-demand |
| GPU | RTX 6000Ada x1 |
| GPU RAM | 49,140 MB |
| lifecycle | ready |
| created_at | 2026-06-07T20:30:38Z |
| launch | redacted |
| instance_id | redacted |
| offer_id | redacted |
| machine_id | redacted |

## Cost and storage snapshot

| Metric | Value |
| --- | --- |
| total hourly | $0.8859 |
| compute hourly | $0.8600 |
| storage hourly | $0.0259 |
| requested disk | 100 GB |
| storage per requested GB-hour | $0.0003 |
| storage share of total | 2.9% |

## Workload configuration

| Field | Value |
| --- | --- |
| configured concurrency | 8 |
| measured requests per simulated user | 1 |
| warmup turns | 0 |
| warmup max tokens | 1 |
| measured max tokens | 256 |
| shared prefix | False |
| fixed prefix tokens | 35000 |
| max model length | 262144 |
| workload shape | coding-agent saturation |

## Recorded sample coverage

| Metric | Value |
| --- | --- |
| all interval windows | 0 |
| active interval windows | 0 |
| first active sample | n/a |
| last active sample | n/a |
| latest recorded total TPS sample | n/a / n/a |

## Throughput summary from interval samples

| Metric | Value |
| --- | --- |
| prompt tokens | 0 |
| generation tokens | 0 |
| total tokens | 0 |
| prompt TPS avg / p95 / max | n/a / n/a / n/a |
| generation TPS avg / p95 / max | n/a / n/a / n/a |
| total TPS avg / p95 / max | n/a / n/a / n/a |
| generation TPS per active request avg / p95 / max | n/a / n/a / n/a |
| total TPS per active request avg / p95 / max | n/a / n/a / n/a |

## Concurrency and cache gauges

| Gauge | Value |
| --- | --- |
| running requests avg / p95 / max | n/a / n/a / n/a |
| waiting requests avg / p95 / max | n/a / n/a / n/a |
| KV cache usage avg / p95 / max | n/a / n/a / n/a |

## Cumulative counter deltas in report window

| Counter | Delta | Status |
| --- | --- | --- |
| vllm.request_success_stop_total | n/a | missing |
| vllm.request_success_length_total | n/a | missing |
| vllm.request_success_error_total | n/a | missing |
| vllm.request_success_abort_total | n/a | missing |
| vllm.prompt_tokens_total | n/a | missing |
| vllm.generation_tokens_total | n/a | missing |
| vllm.ttft_count | n/a | missing |
| vllm.ttft_sum_seconds | n/a | missing |
| vllm.inference_count | n/a | missing |
| vllm.inference_sum_seconds | n/a | missing |
| vllm.queue_count | n/a | missing |
| vllm.queue_sum_seconds | n/a | missing |

## Latency averages from counters

| Metric | Average |
| --- | --- |
| TTFT | n/a s |
| inference | n/a s |
| queue | n/a s |
