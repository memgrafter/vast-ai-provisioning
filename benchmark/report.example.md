# Deterministic Agentic Benchmark Report

Run ID: `example`
Manifest: `benchmark/problem_manifest.example.json`
Backend log: `/path/to/llamacpp-backend.log`
Proxy log: `/path/to/proxy.log` (HTTP 200: 1)

## llama.cpp runtime

- model: `example model path`
- ctx_line: `CTX=262144 NPRED=32768 ...`
- gpu: `CUDA0 example GPU line`

## Validity

- Requests completed: 1
- Responses passing validation: 1 / 1
- Backend-correlated requests: 1 / 1
- Max backend context: example only
- Truncated responses: 0
- Proxy status counts: HTTP 200: 1

## Overall llama.cpp timing

- Prompt-eval tokens: generated from llama.cpp `prompt eval time`
- Prompt-eval seconds: generated from llama.cpp `prompt eval time`
- Weighted prefill TPS: generated from llama.cpp `prompt eval time`
- Generation tokens: generated from llama.cpp `eval time`
- Generation seconds: generated from llama.cpp `eval time`
- Weighted generation TPS: generated from llama.cpp `eval time`
- Draft acceptance: generated from llama.cpp `draft acceptance rate`

## Context bands

The real report bands requests by final `stop processing: n_tokens = ...` context.

## Requests

The real report includes per-request context, prompt-eval tokens/TPS, generation tokens/TPS, and draft acceptance.
