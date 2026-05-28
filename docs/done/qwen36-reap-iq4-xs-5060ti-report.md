# Qwen3.6 REAP IQ4_XS on Vast RTX 5060 Ti

Date: 2026-05-24

## Result

`Qwen3.6-28B-REAP.i1-IQ4_XS.gguf` can run on a 16GB RTX 5060 Ti with full model GPU offload when the context cap is set below the observed VRAM cliff.

Recommended cap for this quant/host class:

```text
ctx: 107500 requested
actual llama.cpp slot: 107520
```

This cap was validated with synthetic prefill up to:

```text
107139 prompt tokens
```

No OOM occurred at that prefix length.

## Runtime configuration tested

```text
GPU: RTX 5060 Ti 16GB
instance: Vast on-demand
llama.cpp: TurboQuant build
model: Qwen3.6-28B-REAP.i1-IQ4_XS.gguf
model size: 15,302,884,320 bytes
NGL: 999
KV offload: enabled
requested CACHE_K: turbo3
requested CACHE_V: turbo3
effective K: q8_0  (auto-upgraded due GQA ratio)
effective V: turbo3
proxy: ~/code/llm-cache-llama.cpp LMCache proxy
Pi access: local Pi -> SSH tunnel -> remote proxy/backend
```

The log showed:

```text
upgrading K from turbo3 to q8_0
TURBOQUANT=1
CACHE_K=turbo3 CACHE_V=turbo3
```

## OOM findings

At `ctx=160000`, the model OOMed early:

```text
approx active context at OOM: ~5.8k-8.5k tokens
peak VRAM: ~15.84 GiB used
```

At `ctx=128000`, the model ran much farther but still OOMed:

```text
last completed context: 107950 tokens
last checkpoint before OOM: 107963 tokens
peak VRAM: 15845 MiB used
```

This established the practical cliff near 108k active context for this quant on this 16GB GPU.

## Validated cap

After restart at `ctx=107500`, llama.cpp rounded the slot to:

```text
new slot, n_ctx = 107520
```

Step-up synthetic prefill requests completed:

```text
40k target    -> 40002 prompt tokens
65k target    -> 64980 prompt tokens
85k target    -> 84967 prompt tokens
100k target   -> 99940 prompt tokens
105k target   -> 104954 prompt tokens
106.5k target -> 106449 prompt tokens
107k target   -> 106955 prompt tokens
107.2k target -> 107139 prompt tokens
```

Final status:

```text
OOM: false
max completed prompt: 107139 tokens
peak VRAM during capped run: 15597 MiB
reported free at end: ~251 MiB
```

## Prefill calibration

A generated synthetic prefill was used rather than model-generated content.

Observed tokenization ratio:

```text
117,379 chars -> 19,578 prompt tokens
chars/token = 5.99545
```

Python-derived target sizes:

```text
20k tokens -> 119,909 chars
25k tokens -> 149,886 chars
30k tokens -> 179,864 chars
```

Initial prefill at the capped context produced:

```text
19,578 prompt tokens
prefill speed: 1,292.94 tok/s
```

Longer step-up prefills near the cap ranged from roughly 780-1,290 tok/s depending on cached prefix reuse and request size.

## Operational notes

- Full model GPU offload was preserved; `NGL` was not reduced.
- Reducing `ctx` was the viable lever.
- `--no-kv-offload` was not used for the final cap validation.
- llama.cpp reserves/allocates around the configured slot context enough that reducing ctx materially changed survivability.
- The LMCache proxy needed Authorization forwarding so Pi could reach an API-key-protected llama.cpp backend through the proxy.

## Cleanup

The Vast instance used for the final run was terminated:

```text
instance: 37555805
termination check: target_instance_remaining=false
```
