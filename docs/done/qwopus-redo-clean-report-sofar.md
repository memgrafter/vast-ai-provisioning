# Qwopus agentic redo report so far

## Copied logs

| file | size bytes |
|---|---:|
| `qwopus-redo-clean-server-sofar.log` | 29,474 |
| `qwopus-redo-clean-session-sofar.json` | 53,574 |
| `qwopus-redo-clean-runner-events-sofar.log` | 2,723 |
| `qwopus-redo-clean-pane-sofar.log` | 3,628 |

## Progress

- Sent prompts: `12`
- Completed prompts: `11`
- Stop/error events: `0`
- Latest send: `state/qwopus-agentic-redo-clean/prompts/06-python3-basic-calculator-iii.self-analysis.txt`
- Latest done: `status=0 state/qwopus-agentic-redo-clean/prompts/06-python3-basic-calculator-iii.prompt.txt`

## Runtime

- Model path: `/workspace/models/qwenopus-3.6-stream/Qwopus3.6-27B-v2-MTP-Q4_K_M.gguf`
- Slot context: `160,000`
- Prompt cache: `8,192` MiB
- GPU: `0.00.283.280 I   - CUDA0   : NVIDIA GeForce RTX 3090 (24124 MiB, 23859 MiB free)`
- CPU: `0.00.283.294 I   - CPU     : Intel(R) Xeon(R) CPU E5-2696 v3 @ 2.30GHz (257808 MiB, 257808 MiB free)`

## Conversation coverage

- JSONL records: `26`
- Messages: `23`
- User prompts in session: `12`
- Assistant replies in session: `11`
- Coding prompts in session: `6`
- Self-analysis prompts in session: `6`

Language counts for coding prompts so far:

| language | count |
|---|---:|
| C++17 | 1 |
| Go 1.22 | 1 |
| Java 17 | 1 |
| JavaScript (Node.js) | 1 |
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

## Server stats so far

- Completed server requests: `11`
- Max final slot tokens: `13,613`
- Median final slot tokens: `8,194`
- Truncated requests: `0`
- Prefill TPS across logged samples: avg `82.54`, median `81.93`, min `74.80`, max `90.88`
- Decode TPS: avg `31.09`, median `33.54`, min `12.25`, max `36.88`
- Draft acceptance: avg `69.99%`, median `71.10%`, min `59.86%`, max `75.42%`

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

## Notes

- This is the corrected organic redo: only LeetCode prompt then immediate self-analysis prompt are being sent; no synthetic filler prompts are included.
- Responses are captured but not semantically evaluated in this report.
