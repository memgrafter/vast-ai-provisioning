# Qwopus agentic redo report so far

## Copied logs

| file | size bytes |
|---|---:|
| `qwopus-redo-clean-server-intermediate.log` | 55,242 |
| `qwopus-redo-clean-session-intermediate.json` | 84,661 |
| `qwopus-redo-clean-runner-events-intermediate.log` | 3,921 |
| `qwopus-redo-clean-pane-intermediate.log` | 4,836 |

## Progress

- Sent prompts: `17`
- Completed prompts: `16`
- Stop/error events: `0`
- Latest send: `state/qwopus-agentic-redo-clean/prompts/09-javascript-sliding-window-median.prompt.txt`
- Latest done: `status=0 state/qwopus-agentic-redo-clean/prompts/08-java17-max-points-on-a-line.self-analysis.txt`

## Runtime

- Model path: `/workspace/models/qwenopus-3.6-stream/Qwopus3.6-27B-v2-MTP-Q4_K_M.gguf`
- Slot context: `160,000`
- Prompt cache: `8,192` MiB
- GPU: `0.00.283.280 I   - CUDA0   : NVIDIA GeForce RTX 3090 (24124 MiB, 23859 MiB free)`
- CPU: `0.00.283.294 I   - CPU     : Intel(R) Xeon(R) CPU E5-2696 v3 @ 2.30GHz (257808 MiB, 257808 MiB free)`

## Conversation coverage

- JSONL records: `36`
- Messages: `33`
- User prompts in session: `17`
- Assistant replies in session: `16`
- Coding prompts in session: `9`
- Self-analysis prompts in session: `8`

Language counts for coding prompts so far:

| language | count |
|---|---:|
| C++17 | 2 |
| Go 1.22 | 1 |
| Java 17 | 2 |
| JavaScript (Node.js) | 2 |
| Python 3 | 2 |

Coding prompts in session so far:

| # | language | chars | problem |
|---:|---|---:|---|
| 1 | Python 3 | 500 | LFU Cache |
| 2 | C++17 | 430 | Regular Expression Matching |
| 3 | Java 17 | 477 | Alien Dictionary |
| 4 | JavaScript (Node.js) | 495 | Expression Add Operators |
| 5 | Go 1.22 | 469 | Serialize and Deserialize N-ary Tree |
| 6 | Python 3 | 504 | Basic Calculator III |
| 7 | C++17 | 460 | Shortest Path to Get All Keys |
| 8 | Java 17 | 457 | Max Points on a Line |
| 9 | JavaScript (Node.js) | 445 | Sliding Window Median |

## Server stats so far

- Completed server requests: `16`
- Max final slot tokens: `20,700`
- Median final slot tokens: `11,074.50`
- Truncated requests: `0`
- Prefill TPS across logged samples: avg `82.54`, median `81.93`, min `74.80`, max `90.88`
- Decode TPS: avg `31.71`, median `33.39`, min `12.25`, max `36.88`
- Draft acceptance: avg `71.04%`, median `71.27%`, min `59.86%`, max `77.59%`

Per-request summary:

| task | final slot tokens | truncated | prompt samples | avg prefill t/s | max decoded | final decode t/s | draft acceptance |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 0 | 2,959 | 0 | 3 | 82.54 | 147 | 12.25 | 59.86% |
| 76 | 4,191 | 0 | 0 | n/a | 1,090 | 20.52 | 74.72% |
| 520 | 4,618 | 0 | 0 | n/a | 217 | 36.88 | 71.10% |
| 632 | 6,050 | 0 | 0 | n/a | 1,265 | 35.15 | 72.73% |
| 1163 | 6,489 | 0 | 0 | n/a | 202 | 35.22 | 71.43% |
| 1279 | 8,194 | 0 | 0 | n/a | 1,511 | 35.71 | 75.28% |
| 1909 | 9,255 | 0 | 0 | n/a | 846 | 35.40 | 75.42% |
| 2268 | 10,892 | 0 | 0 | n/a | 1,496 | 32.95 | 69.40% |
| 2900 | 11,257 | 0 | 0 | n/a | 100 | 33.54 | 63.25% |
| 2986 | 13,139 | 0 | 0 | n/a | 1,861 | 32.18 | 67.40% |
| 3811 | 13,613 | 0 | 0 | n/a | 292 | 32.23 | 69.29% |
| 3941 | 16,196 | 0 | 0 | n/a | 2,383 | 32.56 | 71.12% |
| 4955 | 16,537 | 0 | 0 | n/a | 101 | 33.74 | 76.92% |
| 5023 | 18,434 | 0 | 0 | n/a | 1,730 | 33.85 | 76.01% |
| 5722 | 18,962 | 0 | 0 | n/a | 283 | 31.87 | 65.16% |
| 5880 | 20,700 | 0 | 0 | n/a | 1,513 | 33.24 | 77.59% |

## Notes

- This is the corrected organic redo: only LeetCode prompt then immediate self-analysis prompt are being sent; no synthetic filler prompts are included.
- Responses are captured but not semantically evaluated in this report.
