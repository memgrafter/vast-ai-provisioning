# Qwopus 27B Q4_K_M 160k agentic test report

## Source logs copied to repo root

| file | size bytes |
|---|---:|
| `qwopus-server-160k.log` | 49,658 |
| `qwopus-bootstrap.log` | 4,409,822 |
| `qwopus-agentic-test-pane.log` | 39,556 |
| `qwopus-agentic-test-session.json` | 582,379 |

## Runtime configuration

- Model path: `/workspace/models/qwenopus-3.6-stream/Qwopus3.6-27B-v2-MTP-Q4_K_M.gguf`
- llama.cpp version: `9206 (2dff7ff8f)`
- llama.cpp commit: `2dff7ff8f90ce6daefd6adb097d58a4276e5dd2d`
- Build completed: `True`; max build step: `420/420`
- Configured slot context: `160,000` tokens
- Model train context observed: `262,144` tokens
- Prompt cache limit: `8,192` MiB
- GPU line: `0.00.319.235 I   - CUDA0   : NVIDIA GeForce RTX 3090 (24124 MiB, 23859 MiB free)`
- CPU line: `0.00.319.261 I   - CPU     : Intel(R) Xeon(R) CPU E5-2696 v3 @ 2.30GHz (257808 MiB, 257808 MiB free)`
- System line: `0.00.319.387 I system_info: n_threads = 36 (n_threads_batch = 36) / 72 | CUDA : ARCHS = 860 | USE_GRAPHS = 1 | PEER_MAX_BATCH_SIZE = 128 | CPU : SSE3 = 1 | SSSE3 = 1 | AVX = 1 | AVX2 = 1 | F16C = 1 | FMA = 1 | BMI2 = 1 | LLAMAFILE = 1 | OPENMP = 1 | REPACK = 1 |`

## Conversation/test coverage

- JSONL records: `23`
- Messages: `20`
- User prompts: `10`
- Assistant replies: `10`
- Coding/problem prompts: `6`
- Self-analysis prompts: `4`
- Long/near-max-context prompts: `3`

Language/problem prompts, excluding self-analysis:

| # | language | chars | long ctx | problem/description |
|---:|---|---:|---:|---|
| 1 | Python 3 | 419 | False | Design and implement an LRU Cache with capacity N supporting get(key) and put(key, value) in O(1) average time. If capacity is exceeded, evict the least recentl |
| 2 | C++17 | 349 | False | Given two sorted arrays nums1 and nums2 of sizes m and n, return the median of the two sorted arrays. The required runtime complexity is O(log(m+n)). Provide pr |
| 3 | Java 17 | 432 | False | Given beginWord, endWord, and a wordList, return the length of the shortest transformation sequence from beginWord to endWord where each step changes exactly on |
| 4 | JavaScript (Node.js). | 427 | False | Implement serialize(root) and deserialize(data) for a binary tree. The codec must correctly preserve tree shape and node values, including negative values and d |
| 5 | Go 1.22. | 515,731 | True | Implement a production-quality solution for "Minimum Window Substring". |
| 6 | C# 12 / .NET. | 1,623 | True | Merge k sorted linked lists and return one sorted linked list. Use LeetCode's ListNode convention. Provide production-quality C# code, explain the priority queu |

Language counts, excluding self-analysis:

| language | count |
|---|---:|
| C# 12 / .NET. | 1 |
| C++17 | 1 |
| Go 1.22. | 1 |
| Java 17 | 1 |
| JavaScript (Node.js). | 1 |
| Python 3 | 1 |

## Server request stats

- Completed server requests: `11`
- Max final slot tokens: `159,999`
- Median final slot tokens: `12,504`
- Requests with truncation: `1`; tasks: `[5075]`
- Max checkpoint tokens: `159,204`
- Prompt processing TPS across logged prefill samples: avg `466.58`, median `455.88`, min `349.65`, max `617.44`
- Decode TPS: avg `30.43`, median `32.71`, min `19.68`, max `37.82`
- Draft acceptance: avg `70.45%`, median `69.20%`, min `63.36%`, max `77.22%`

Prefill stretches parsed from `prompt processing` log lines:

| task | samples | token start | token end | elapsed s | avg prefill t/s | median t/s | min t/s | max t/s | final cumulative t/s |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 3 | 4 | 2,048 | 4,855 | 9.03 | 506.80 | 531.22 | 427.23 | 537.51 | 537.51 |
| 4067 | 70 | 2,048 | 141,035 | 403.36 | 464.28 | 452.32 | 349.65 | 617.44 | 349.65 |

Per-request server summary:

| task | final slot tokens | truncated | max prompt tokens | avg prefill t/s | final prompt t/s | max decoded | final decode t/s | draft acceptance | checkpoint max |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 0 | 17 | 0 | n/a | n/a | n/a | n/a | n/a | n/a | n/a |
| 3 | 5,554 | 0 | 4,855 | 506.80 | 537.51 | 670 | 37.82 | 75.00% | 4,855 |
| 287 | 6,437 | 0 | n/a | n/a | n/a | 754 | 35.53 | 69.73% | 5,626 |
| 627 | 8,178 | 0 | n/a | n/a | n/a | 1,576 | 37.37 | 77.22% | 6,538 |
| 1273 | 9,244 | 0 | n/a | n/a | n/a | 890 | 32.91 | 63.36% | 8,256 |
| 1710 | 12,504 | 0 | n/a | n/a | n/a | 3,127 | 33.26 | 68.67% | 9,360 |
| 3036 | 13,582 | 0 | n/a | n/a | n/a | 966 | 31.80 | 63.93% | 12,580 |
| 3477 | 15,079 | 0 | n/a | n/a | n/a | 1,294 | 32.51 | 68.57% | 13,683 |
| 4067 | 157,014 | 0 | 141,035 | 464.28 | 349.65 | 890 | 21.62 | 76.91% | 156,114 |
| 4492 | 158,704 | 0 | n/a | n/a | n/a | 1,298 | 19.68 | 64.66% | 157,370 |
| 5075 | 159,999 | 1 | n/a | n/a | n/a | 750 | 21.76 | 76.48% | 159,204 |

## Output-size stats from Pi session

These counts are character counts from the Pi JSONL session, not model token counts.

- Assistant total message chars: avg `4,852.90`, median `3,639.00`, max `13,952`
- Assistant visible text chars: avg `3,541`, median `3,475.50`, max `4,864`
- Assistant thinking chars: avg `1,310.90`, median `137.50`, max `10,319`

## Key findings

- Max-context target reached: `True` (`159,999` final slot tokens vs `160,000` configured).
- Large-context sequence: task 4067: 157,014 tokens, truncated=0, task 4492: 158,704 tokens, truncated=0, task 5075: 159,999 tokens, truncated=1.
- Near-full-context decode TPS: avg `21.02`, median `21.62`, min `19.68`, max `21.76`.
- Prompt processing speed decreased as context grew; see per-request prompt TPS and max prompt-token rows above.
- Coverage note: `6` coding/problem prompts and `4` self-analysis prompts were present in the copied session log.
- Responses were not semantically evaluated in this report; this report summarizes run coverage and runtime stats only.
