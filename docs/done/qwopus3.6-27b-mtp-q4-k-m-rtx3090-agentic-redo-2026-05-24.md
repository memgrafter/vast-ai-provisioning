# Qwopus3.6 27B MTP Q4_K_M on 1x RTX 3090: organic agentic LeetCode run

Date: 2026-05-24

## Executive summary

This was the corrected organic agentic run: each turn sent one LeetCode-style coding problem, followed immediately by a self-analysis prompt. No synthetic filler was used in this run.

The run was intentionally stopped after `48` prompts sent and `47` prompts completed because generation speed had fallen to the low-teens token/s range by approximately `71,481` active slot tokens. The final in-flight request was cancelled cleanly by interrupting the local runner; llama.cpp released the slot with `truncated = 0`.

## Hardware and runtime

| field | value |
|---|---|
| GPU | `0.00.283.280 I   - CUDA0   : NVIDIA GeForce RTX 3090 (24124 MiB, 23859 MiB free)` |
| CPU | `0.00.283.294 I   - CPU     : Intel(R) Xeon(R) CPU E5-2696 v3 @ 2.30GHz (257808 MiB, 257808 MiB free)` |
| Model | `/workspace/models/qwenopus-3.6-stream/Qwopus3.6-27B-v2-MTP-Q4_K_M.gguf` |
| Configured slot context | `160,000` tokens |
| Model train context | `262,144` tokens |
| Prompt cache | `8,192` MiB |
| System line | `0.00.283.403 I system_info: n_threads = 36 (n_threads_batch = 36) / 72 | CUDA : ARCHS = 860 | USE_GRAPHS = 1 | PEER_MAX_BATCH_SIZE = 128 | CPU : SSE3 = 1 | SSSE3 = 1 | AVX = 1 | AVX2 = 1 | F16C = 1 | FMA = 1 | BMI2 = 1 | LLAMAFILE = 1 | OPENMP = 1 | REPACK = 1 |` |

Runtime configuration used by the launcher: `--ctx-size 160000`, `--cache-type-k q4_0`, `--cache-type-v q4_0`, `--spec-type draft-mtp`, `--spec-draft-n-max 2`, and `--gpu-layers 99`.

## Workload progress

| metric | value |
|---|---:|
| Planned prompts | 60 |
| Sent prompts | 48 |
| Completed prompts | 47 |
| Coding prompts in session | 24 |
| Self-analysis prompts in session | 24 |
| Assistant replies in session | 47 |
| Server requests released | 48 |
| Cancelled server tasks | 1 |
| Truncated requests | 0 |

Language coverage for completed/sent coding prompts:

| language | coding prompts |
|---|---:|
| C++17 | 5 |
| Go 1.22 | 4 |
| Java 17 | 5 |
| JavaScript (Node.js) | 5 |
| Python 3 | 5 |

Coding prompts reached before stop:

| # | language | problem |
|---:|---|---|
| 1 | Python 3 | LFU Cache |
| 2 | C++17 | Regular Expression Matching |
| 3 | Java 17 | Alien Dictionary |
| 4 | JavaScript (Node.js) | Expression Add Operators |
| 5 | Go 1.22 | Serialize and Deserialize N-ary Tree |
| 6 | Python 3 | Basic Calculator III |
| 7 | C++17 | Shortest Path to Get All Keys |
| 8 | Java 17 | Max Points on a Line |
| 9 | JavaScript (Node.js) | Sliding Window Median |
| 10 | Go 1.22 | Recover Binary Search Tree |
| 11 | Python 3 | Word Search II |
| 12 | C++17 | Number of Islands II |
| 13 | Java 17 | Minimum Window Subsequence |
| 14 | JavaScript (Node.js) | Course Schedule IV |
| 15 | Go 1.22 | Palindrome Pairs |
| 16 | Python 3 | Burst Balloons |
| 17 | C++17 | Count of Smaller Numbers After Self |
| 18 | Java 17 | Longest Increasing Path in a Matrix |
| 19 | JavaScript (Node.js) | Maximum Profit in Job Scheduling |
| 20 | Go 1.22 | Design In-Memory File System |
| 21 | Python 3 | Find Median from Data Stream |
| 22 | C++17 | Minimum Cost to Make at Least One Valid Path in a Grid |
| 23 | Java 17 | Remove Invalid Parentheses |
| 24 | JavaScript (Node.js) | Text Justification |

## Throughput summary

| metric | value |
|---|---:|
| Max final slot tokens | 71,481 |
| Median final slot tokens | 41,470.00 |
| Avg decode TPS | 18.71 |
| Median decode TPS | 13.12 |
| Min decode TPS | 8.33 |
| Max decode TPS | 36.88 |
| Avg per-request draft acceptance | 76.1% |
| Median per-request draft acceptance | 76.5% |
| Weighted MTP draft acceptance | 75.6% |
| MTP accepted/generated draft tokens | 36,665 / 48,520 |
| Logged prefill sample avg TPS | 41.76 |
| Logged prefill sample median TPS | 40.34 |

Decode speed by final slot-token band:

| final slot tokens | requests | avg decode t/s | median decode t/s | min | max | avg draft acceptance | MTP accepted/generated |
|---|---:|---:|---:|---:|---:|---:|---:|
| 1-10,000 | 7 | 30.16 | 35.22 | 12.25 | 36.88 | 71.5% | 3,308 / 4,488 |
| 10,001-20,000 | 8 | 32.87 | 32.76 | 31.87 | 33.85 | 69.8% | 5,060 / 7,176 |
| 20,001-30,000 | 1 | 33.24 | 33.24 | 33.24 | 33.24 | 77.6% | 973 / 1,254 |
| 30,001-40,000 | 8 | 12.80 | 13.31 | 8.33 | 14.31 | 74.5% | 8,300 / 11,904 |
| 40,001-50,000 | 4 | 11.01 | 10.84 | 10.00 | 12.38 | 74.9% | 7,850 / 9,922 |
| 50,001-60,000 | 7 | 11.34 | 10.97 | 9.87 | 13.73 | 81.1% | 5,447 / 6,690 |
| 60,001-80,000 | 13 | 12.70 | 12.83 | 11.11 | 13.77 | 81.4% | 5,727 / 7,086 |

## MTP/speculative decoding stats

The server ran with `--spec-type draft-mtp --spec-draft-n-max 2 --spec-draft-n-min 2`. llama.cpp reports draft acceptance per completed request as `accepted / generated` draft tokens.

| metric | value |
|---|---:|
| Requests with MTP stats | 47 |
| Total accepted draft tokens | 36,665 |
| Total generated draft tokens | 48,520 |
| Weighted acceptance | 75.6% |
| Per-request acceptance avg | 76.1% |
| Per-request acceptance median | 76.5% |
| Per-request acceptance min | 59.9% |
| Per-request acceptance max | 88.6% |

Per-request MTP rows:

| task | final slot tokens | decode t/s | acceptance | accepted/generated draft tokens |
|---:|---:|---:|---:|---:|
| 0 | 2,959 | 12.25 | 59.9% | 85 / 142 |
| 76 | 4,191 | 20.52 | 74.7% | 659 / 882 |
| 520 | 4,618 | 36.88 | 71.1% | 155 / 218 |
| 632 | 6,050 | 35.15 | 72.7% | 768 / 1,056 |
| 1163 | 6,489 | 35.22 | 71.4% | 160 / 224 |
| 1279 | 8,194 | 35.71 | 75.3% | 944 / 1,254 |
| 1909 | 9,255 | 35.40 | 75.4% | 537 / 712 |
| 2268 | 10,892 | 32.95 | 69.4% | 873 / 1,258 |
| 2900 | 11,257 | 33.54 | 63.3% | 105 / 166 |
| 2986 | 13,139 | 32.18 | 67.4% | 1,108 / 1,644 |
| 3811 | 13,613 | 32.23 | 69.3% | 176 / 254 |
| 3941 | 16,196 | 32.56 | 71.1% | 1,438 / 2,022 |
| 4955 | 16,537 | 33.74 | 76.9% | 100 / 130 |
| 5023 | 18,434 | 33.85 | 76.0% | 1,058 / 1,392 |
| 5722 | 18,962 | 31.87 | 65.2% | 202 / 310 |
| 5880 | 20,700 | 33.24 | 77.6% | 973 / 1,254 |
| 6510 | 30,107 | 13.45 | 66.5% | 5,279 / 7,936 |
| 10481 | 30,750 | 13.17 | 75.9% | 305 / 402 |
| 10685 | 31,155 | 13.94 | 78.6% | 143 / 182 |
| 10779 | 32,530 | 13.75 | 76.5% | 747 / 976 |
| 11270 | 32,808 | 8.33 | 79.5% | 70 / 88 |
| 11317 | 34,307 | 12.45 | 72.4% | 808 / 1,116 |
| 11878 | 34,611 | 13.04 | 66.1% | 78 / 118 |
| 11940 | 36,163 | 14.31 | 80.1% | 870 / 1,086 |
| 12486 | 46,777 | 12.38 | 80.9% | 6,452 / 7,978 |
| 16478 | 47,295 | 10.79 | 80.5% | 235 / 292 |
| 16627 | 48,219 | 10.00 | 62.2% | 423 / 680 |
| 16970 | 49,581 | 10.88 | 76.1% | 740 / 972 |
| 17459 | 50,056 | 10.66 | 81.0% | 188 / 232 |
| 17578 | 54,176 | 11.31 | 82.0% | 2,473 / 3,016 |
| 19089 | 54,650 | 9.87 | 75.4% | 190 / 252 |
| 19218 | 55,846 | 10.97 | 82.6% | 661 / 800 |
| 19621 | 56,210 | 12.20 | 80.0% | 120 / 150 |
| 19699 | 59,186 | 13.73 | 80.9% | 1,750 / 2,164 |
| 20784 | 59,461 | 10.66 | 85.5% | 65 / 76 |
| 20825 | 60,780 | 13.06 | 83.8% | 736 / 878 |
| 21267 | 61,091 | 11.94 | 85.6% | 89 / 104 |
| 21322 | 62,602 | 12.09 | 79.5% | 841 / 1,058 |
| 21854 | 62,908 | 11.11 | 85.3% | 87 / 102 |
| 21908 | 64,907 | 12.55 | 80.8% | 1,147 / 1,420 |
| 22621 | 65,174 | 13.08 | 81.7% | 67 / 82 |
| 22665 | 66,325 | 12.26 | 82.6% | 633 / 766 |
| 23051 | 66,694 | 13.77 | 88.6% | 117 / 132 |
| 23120 | 68,150 | 13.35 | 83.0% | 812 / 978 |
| 23612 | 68,438 | 12.59 | 76.0% | 76 / 100 |
| 23665 | 70,304 | 12.83 | 76.8% | 1,047 / 1,364 |
| 24350 | 70,584 | 12.90 | 73.5% | 75 / 102 |

## Interpretation

The run was useful enough to reject this configuration for interactive agentic coding at high context. Decode speed was acceptable early, then degraded sharply as context grew:

- Around 5k-20k slot tokens, many requests were still in the low-to-mid 30 token/s range.
- Around 30k-50k slot tokens, long generations dropped into roughly 10-14 token/s territory.
- By roughly 70k slot tokens, the stopped request was generating at about 13-14 token/s before cancellation.

The earlier synthetic saturation run showed the server can reach the configured 160k context, but this corrected organic run shows the user experience becomes too slow well before that point on a single RTX 3090 with this GGUF/runtime combination.

## Artifacts

Local run artifacts are under:

```text
logs/qwopus-agentic-redo-clean-20260524/
```

Important files:

```text
qwopus-redo-clean-server-final.log
qwopus-redo-clean-session-final.jsonl
qwopus-redo-clean-runner-events-final.log
logs/qwopus-agentic-redo-clean-20260524/report-final.md
logs/qwopus-agentic-redo-clean-20260524/outputs/
```

No semantic grading of model answers is included here; this report is runtime/performance coverage only.
