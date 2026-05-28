# Qwen3.6 REAP IQ3_M on Vast RTX 5060 Ti

Date: 2026-05-24

> **Warning / status note — 2026-05-24T13:11:23 local:** the user believes earlier stats in this report were wrong. Treat throughput here as a corrected best-effort parse of the copied raw llama.cpp backend log, not a final benchmark.
>
> **Important:** the checked host/log shows **one** RTX 5060 Ti (`CUDA0`) on instance `37632250`, not a cleanly verified 2x RTX 5060 Ti run.

## Raw log used

Copied locally for review:

```text
./llamacpp-backend-20260524-183433.log
```

Host source:

```text
/workspace/logs/llamacpp-backend-20260524-183433.log
```

## Runtime configuration

From the backend log:

```text
model: /workspace/models/Qwen3.6-28B-REAP.i1-IQ3_M.gguf
CTX: 262144
NPRED: 32768
NGL: 999
batch: 256
ubatch: 64
parallel: 1
MTP: 0
speculative: ngram-mod
requested CACHE_K: turbo3
requested CACHE_V: turbo3
effective K: q8_0  (auto-upgraded due GQA ratio)
effective V: turbo3
GPU observed: CUDA0 NVIDIA GeForce RTX 5060 Ti
```

## What was excluded

Excluded from agentic coding TPS:

- task `0`: health/small initial request
- tasks `14` through `1073`: synthetic/general max-context fill; these use ~30k prompt chunks and `eval_tokens=1`
- tasks `54275` through `56038`: later reset/fill testing; these use ~30k prompt chunks and `eval_tokens=256`

Included as agentic coding TPS:

- tasks `1080` through `53985`
- 41 completed timing blocks
- each included task generated roughly 3k-4.5k tokens

Task `54255` is counted only as an end-of-window context observation because it has no complete final timing block.

## Context result

The server slot was configured for full context:

```text
requested ctx: 262144
actual slot:   262144
```

But the isolated agentic coding section did **not** go from 0 to max context.

```text
max synthetic/general-test context before agentic run: 261837 tokens
first included agentic task final context:              5017 tokens
max included agentic context with timing block:       141714 tokens
max observed agentic-window context incl. task 54255: 141883 tokens
truncated=1 observed in included agentic rows:        no
```

## Corrected agentic coding throughput by 30k context band

Method:

- Use final llama.cpp timing blocks:
  - `prompt eval time = ... / ... tokens ... tokens per second`
  - `eval time = ... / ... tokens ... tokens per second`
- Do **not** convert cumulative `n_decoded = ..., tg = ...` points into interval TPS.
- Band each completed agentic task by its final `stop processing: n_tokens = ...` context.
- Token-weighted TPS is `sum(tokens) / sum(seconds)` within the band.

| Final context band | Requests | Context range | Prefill tokens | Prefill weighted tok/s | Prefill median tok/s | Generation tokens | Generation weighted tok/s | Generation median tok/s | Generation tok/s range |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 0-30k | 7 | 5,017-27,791 | 1,144 | 625.63 | 619.40 | 26,654 | 73.32 | 72.16 | 64.38-84.15 |
| 30-60k | 9 | 31,208-59,624 | 4,181 | 749.75 | 567.44 | 30,903 | 75.74 | 60.52 | 52.67-258.01 |
| 60-90k | 9 | 63,288-89,573 | 27,409 | 721.74 | 723.83 | 29,022 | 204.71 | 196.60 | 160.91-256.68 |
| 90-120k | 9 | 92,858-118,944 | 29,961 | 651.32 | 656.75 | 28,444 | 183.88 | 181.67 | 162.96-219.17 |
| 120-150k | 7 | 122,154-141,714 | 20,065 | 598.50 | 597.60 | 22,049 | 188.76 | 206.62 | 162.01-221.61 |

Overall for included completed agentic tasks:

```text
completed agentic timing blocks: 41
prefill tokens: 82760
weighted prefill TPS: 662.57 tok/s
generation tokens: 137072
weighted generation TPS: 115.69 tok/s
```

## Included agentic task rows

```text
task   final_ctx  prompt_tokens  prefill_tps  gen_tokens  gen_tps
1080        5017            526       641.02        4492    84.15
5572        8343            103       643.34        3224    79.45
8791       12541            103       625.93        4096    75.72
12876      17016            103       619.40        4373    72.09
17172      21330            103       612.77        4212    72.16
21059      24529            103       587.22        3097    65.37
24116      27791            103       593.51        3160    64.38
27192      31208            103       581.68        3315    63.19
30351      35831            103       574.59        4521    60.52
34806      39041            104       573.64        3107    57.38
37881      42705            104       567.44        3561    56.37
41394      46354            104       558.13        3546    54.80
44882      49840            104       554.41        3381   258.01
45075      53048            102       535.86        3107   253.79
45191      56334            104       541.55        3183    52.67
48085      59624           3353       817.94        3182   243.69
48247      63288           3353       761.63        3561   256.68
48452      66492           3732       757.84        3107   251.64
48569      69982            104       505.67        3381   235.51
48777      73267           3552       731.41        3182   177.07
49137      76530           3353       723.83        3160   160.91
49570      79815           3331       731.73        3182   196.60
49824      83100           3353       704.32        3182   229.60
49986      86310           3353       693.40        3107   184.47
50268      89573           3278       681.99        3160   189.20
50559      92858           3331       691.34        3182   162.96
50930      96068           3353       667.03        3107   219.17
51078      99353           3278       656.92        3182   183.77
51360     102616           3353       656.75        3160   181.67
51651     105901           3331       660.75        3182   182.19
51905     109111           3353       641.82        3107   212.19
52053     112396           3278       631.73        3182   176.00
52335     115659           3353       628.24        3160   174.86
52626     118944           3331       632.21        3182   176.63
52880     122154           3353       616.03        3107   206.62
53028     125439           3278       605.79        3182   165.46
53312     128724           3353       604.70        3182   207.12
53474     131934           3353       597.60        3107   221.61
53589     135219           3278       588.94        3182   163.97
53871     138430           3353       588.17        3107   220.15
53985     141714             97       389.37        3182   162.01
```

## Note on cumulative timing lines

The periodic lines are cumulative within a task, for example:

```text
n_decoded = 100,  tg = 89.98 t/s
n_decoded = 4398, tg = 84.23 t/s
```

The corrected table above does not treat those as interval measurements. It uses the final per-task timing blocks for TPS and the cumulative lines only as a sanity check.
