# Previous Deterministic Agentic Run Report

Run ID: `det-agentic-20260524-223511`  
Date: 2026-05-24

## Status

This run is **not a final valid benchmark**. It was manually stopped after discovering that the project-local `.pi/models.json` used the wrong custom provider/model shape and did not match the relevant `~/.pi/agent/models.json` entry. The runner also did not yet preserve returned reasoning traces into accumulated history.

Use this report only as a record of what happened before the config/runner fixes.

## Logs

Local copies:

```text
det-agentic-20260524-223511/requests.jsonl
det-agentic-20260524-223511/backend.log
det-agentic-20260524-223511/proxy.log
```

Host originals:

```text
/workspace/logs/det-agentic-20260524-223511/benchmark-run/requests.jsonl
/workspace/logs/llamacpp-backend-det-agentic-20260524-223511.log
/workspace/logs/det-agentic-20260524-223511/proxy.log
```

## Run summary

```text
requests completed:      22
validated responses:     22 / 22
proxy POSTs:             22
HTTP failures:           0
backend releases:        22
truncated responses:     0
max observed context:    66,245 tokens
target context:          256,000 tokens
stop reason:             manually stopped after config issue found
```

The server context was still the full llama.cpp context; this run simply did not continue to the target.

```text
configured llama.cpp context: 262144
benchmark target context:     256000
```

## Overall llama.cpp timing

Token-weighted from llama.cpp final timing blocks:

```text
prompt-eval tokens:       61,777
weighted prefill TPS:     850.62 tok/s

generation tokens:        144,779
weighted generation TPS:  102.42 tok/s

draft acceptance:         68.25%
```

## Throughput by 30k context band

Banded by each request's final `stop processing: n_tokens = ...` context.

| Final context band | Requests | Context range | Prompt-eval tokens | Prefill weighted tok/s | Prefill median tok/s | Gen tokens | Gen weighted tok/s | Gen median tok/s | Gen tok/s range | Draft acceptance |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 0-30k | 8 | 12,368-26,105 | 20,807 | 948.55 | 931.59 | 62,760 | 104.85 | 110.03 | 88.52-133.83 | 62.78% |
| 30-60k | 11 | 30,236-57,578 | 32,211 | 823.56 | 820.56 | 64,335 | 106.93 | 104.23 | 85.00-147.55 | 72.59% |
| 60-90k | 3 | 60,887-66,245 | 8,759 | 756.50 | 754.77 | 17,684 | 82.88 | 84.04 | 80.30-84.20 | 67.37% |

## Per-request progression

| Iter | Context | Prompt eval toks | Prefill tok/s | Gen toks | Gen tok/s | Draft acc | Prompt usage | Cached toks | Visible chars |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 12,368 | 497 | 785.56 | 11,872 | 88.52 | 47.65% | 497 | 0 | 8,244 |
| 2 | 13,850 | 2,765 | 1051.78 | 10,657 | 89.49 | 37.73% | 3,194 | 429 | 8,830 |
| 3 | 13,792 | 2,936 | 1014.99 | 7,728 | 133.83 | 79.37% | 6,062 | 3,126 | 8,813 |
| 4 | 16,892 | 2,932 | 958.48 | 7,964 | 126.35 | 71.05% | 8,926 | 5,994 | 8,738 |
| 5 | 17,322 | 2,916 | 937.25 | 5,546 | 129.54 | 69.22% | 11,774 | 8,858 | 8,751 |
| 6 | 21,561 | 2,914 | 925.93 | 6,939 | 96.32 | 66.78% | 14,620 | 11,706 | 8,797 |
| 7 | 23,757 | 2,921 | 911.26 | 6,282 | 107.27 | 63.58% | 17,473 | 14,552 | 8,816 |
| 8 | 26,105 | 2,926 | 897.91 | 5,772 | 112.78 | 65.25% | 20,331 | 17,405 | 8,831 |
| 9 | 30,236 | 2,929 | 883.64 | 7,042 | 118.20 | 86.26% | 23,192 | 20,263 | 8,818 |
| 10 | 31,710 | 2,923 | 870.94 | 5,661 | 144.40 | 87.95% | 26,047 | 23,124 | 8,799 |
| 11 | 34,671 | 2,918 | 855.30 | 5,772 | 96.77 | 62.62% | 28,897 | 25,979 | 8,803 |
| 12 | 37,549 | 2,918 | 844.11 | 5,800 | 105.89 | 68.49% | 31,747 | 28,829 | 8,803 |
| 13 | 39,934 | 2,918 | 831.54 | 5,335 | 147.55 | 87.62% | 34,597 | 31,679 | 8,803 |
| 14 | 41,183 | 2,918 | 820.56 | 3,734 | 126.75 | 85.57% | 37,447 | 34,529 | 8,803 |
| 15 | 45,787 | 2,918 | 810.66 | 5,488 | 100.29 | 61.56% | 40,297 | 37,379 | 8,803 |
| 16 | 48,882 | 2,918 | 801.84 | 5,733 | 104.23 | 67.65% | 43,147 | 40,229 | 8,822 |
| 17 | 54,527 | 2,923 | 795.58 | 8,523 | 93.76 | 71.50% | 46,002 | 43,079 | 8,971 |
| 18 | 54,365 | 2,964 | 784.93 | 5,465 | 100.91 | 69.01% | 48,898 | 45,934 | 8,971 |
| 19 | 57,578 | 2,964 | 776.28 | 5,782 | 85.00 | 60.67% | 51,794 | 48,830 | 8,822 |
| 20 | 60,887 | 2,923 | 767.43 | 6,236 | 84.20 | 67.28% | 54,649 | 51,726 | 8,803 |
| 21 | 63,055 | 2,918 | 754.77 | 5,554 | 80.30 | 66.02% | 57,499 | 54,581 | 8,803 |
| 22 | 66,245 | 2,918 | 747.55 | 5,894 | 84.04 | 68.67% | 60,349 | 57,431 | 8,803 |

## What invalidated this run

- The project-local `.pi/models.json` had been created with a made-up provider name and `reasoning: false` instead of copying the real `vast_llama.cpp` entry from `~/.pi/agent/models.json`.
- The runner did not yet apply the `qwen-chat-template` thinking payload from model compatibility settings.
- The runner did not yet preserve returned `reasoning_content` / `reasoning` into replayed history.

Those issues have since been fixed in the benchmark runner and `.pi` config, but this run predates those fixes.
