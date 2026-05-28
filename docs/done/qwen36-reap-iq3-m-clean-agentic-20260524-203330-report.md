# Clean Agentic Coding Run: Qwen3.6 REAP IQ3_M on RTX 5060 Ti

Date: 2026-05-24  
Run ID: `agentic-clean-20260524-203330`

## Executive summary

This is a clean sequential agentic-coding run from an empty restarted llama.cpp slot to near max context.

```text
requested context:        262144 tokens
final observed context:   256567 tokens
completed requests:       112
HTTP failures:            0
backend releases:         112
truncated responses:      0
run window UTC:           2026-05-24T20:31:52Z to 2026-05-24T21:12:02Z
```

Important hardware note: the checked backend log shows **one** RTX 5060 Ti (`CUDA0`), not a verified 2x RTX 5060 Ti run.

## Logs and correlation

Local copies:

```text
clean-agentic-20260524-203330/backend.log
clean-agentic-20260524-203330/proxy.log
clean-agentic-20260524-203330/client.jsonl
```

Host originals:

```text
/workspace/logs/llamacpp-backend-agentic-clean-20260524-203330.log
/workspace/logs/agentic-clean-20260524-203330/proxy.log
/workspace/logs/agentic-clean-20260524-203330/client.jsonl
/workspace/logs/agentic-clean-20260524-203330/transcript.md
```

Correlation method:

- `client.jsonl` records every `request_id`, iteration, client start/end time, HTTP status, usage, and the parsed backend `task` from the backend log after each request.
- `proxy.log` has exactly 112 `POST /v1/chat/completions` entries, all HTTP 200.
- `backend.log` has exactly 112 `stop processing` releases for those requests.
- Requests were issued sequentially, so there is no concurrency ambiguity.
- No synthetic/general-prefill tasks are included in this report.

## Runtime configuration

From the backend log:

```text
model: Qwen3.6-28B-REAP.i1-IQ3_M.gguf
ctx: 262144
npred: 32768
ngl: 999
batch: 256
ubatch: 64
parallel: 1
MTP: 0
speculative: ngram-mod
spec n_match/min/max: 24 / 48 / 63
requested KV: K=turbo3, V=turbo3
effective K: q8_0, auto-upgraded due GQA ratio
effective V: turbo3
GPU: CUDA0 NVIDIA GeForce RTX 5060 Ti
```

## Overall throughput

These are token-weighted from llama.cpp final per-request timing blocks.

```text
prompt-eval tokens:       260548
prompt-eval seconds:      428.520
weighted prefill TPS:     608.02 tok/s

generation tokens:        256722
generation seconds:       1892.680
weighted generation TPS:  135.64 tok/s

draft accepted/generated: 197231 / 233555
weighted draft acceptance: 84.45%
```

Note: llama.cpp `prompt eval time` covers the tokens actually evaluated for that request after slot/checkpoint reuse, not the full total prompt size. Full request prompt sizes are reflected in OpenAI-compatible `usage.prompt_tokens` in `client.jsonl`.

## Throughput by final context band

Banded by each request's final `stop processing: n_tokens = ...` context.

| Final context band | Requests | Context range | Prompt-eval tokens | Prefill weighted tok/s | Prefill median tok/s | Gen tokens | Gen weighted tok/s | Gen median tok/s | Gen tok/s range | Draft acceptance |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 0-30k | 9 | 4,248-27,004 | 23,453 | 987.52 | 984.32 | 36,864 | 79.32 | 76.30 | 68.42-133.55 | 50.0% |
| 30-60k | 12 | 31,195-56,997 | 33,764 | 834.54 | 802.82 | 28,832 | 203.27 | 274.23 | 57.36-376.55 | 88.7% |
| 60-90k | 11 | 61,157-88,506 | 29,964 | 748.70 | 741.57 | 30,490 | 107.77 | 149.47 | 51.70-265.64 | 78.8% |
| 90-120k | 10 | 91,979-117,025 | 31,442 | 660.89 | 657.16 | 27,556 | 206.75 | 208.95 | 156.59-219.86 | 87.0% |
| 120-150k | 11 | 120,474-149,514 | 31,004 | 600.32 | 596.18 | 31,486 | 120.30 | 198.63 | 42.65-264.60 | 79.3% |
| 150-180k | 16 | 150,877-177,990 | 31,720 | 548.56 | 548.93 | 26,969 | 159.68 | 188.95 | 47.41-282.20 | 87.9% |
| 180-210k | 17 | 181,509-209,851 | 33,015 | 499.51 | 493.78 | 30,263 | 196.12 | 230.09 | 154.96-302.48 | 88.7% |
| 210-240k | 17 | 213,401-239,785 | 31,090 | 465.03 | 463.13 | 28,332 | 145.90 | 205.10 | 36.68-261.79 | 86.7% |
| 240-270k | 9 | 241,107-256,567 | 15,096 | 440.17 | 438.59 | 15,930 | 175.49 | 217.52 | 123.41-253.49 | 88.3% |

## Context progression samples

```text
iter  ctx_tokens  prompt_eval_tps  gen_tps  draft_acceptance
1          4248           440.35    90.63    21.62%
10        31195           914.11   151.91    81.86%
20        55796           798.24   199.78    84.48%
30        83482           723.01   178.77    88.72%
40       112291           639.57   198.62    88.98%
50       143300           596.18   264.60    95.39%
60       158906           555.05   282.20   100.00%
70       181509           513.61   172.57    83.10%
80       199495           502.19   215.88    95.95%
90       217751           470.16   165.05    83.41%
100      235734           448.28   146.48    80.26%
110      249244           436.83   217.52    93.50%
112      256567           443.39   156.99    84.20%
```

## Interpretation notes

- Prefill throughput declines with context as expected: roughly ~988 tok/s in the first 30k band down to ~440 tok/s near 256k.
- Generation throughput is not monotonic because this run used `ngram-mod` speculative decoding. Generation TPS tracks draft acceptance and output shape, so high-acceptance requests can be much faster than neighboring low-acceptance requests.
- The run successfully reached ~256k context without truncation or backend failure.
- This report is from the clean rerun only; it does not reuse the earlier mixed synthetic/agentic log.
