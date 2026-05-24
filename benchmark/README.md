# Deterministic agentic-coding benchmark

This benchmark uses a static problem manifest. The model solves fixed, language-bound problems; it does not invent benchmark tasks.

The default runner uses the OpenAI-compatible API directly. It does **not** drive a pi tmux pane. This is intentional for clean request/proxy/backend correlation. Pi config examples are included for separate pi-based launches.

## Dry run

```bash
python3 benchmark/run_deterministic_agentic_benchmark.py \
  --dry-run \
  --run-id example-dry-run \
  --out-dir benchmark/runs/example-dry-run
```

## Real llama.cpp run to max context

Run this on the host where the llama.cpp backend log is locally readable, or mount/stream that log path locally while the benchmark is running.

```bash
export LLAMACPP_API_KEY=...
python3 benchmark/run_deterministic_agentic_benchmark.py \
  --manifest benchmark/problem_manifest.example.json \
  --base-url http://127.0.0.1:8081/v1 \
  --model qwen3.6-28b-reap-iq3-m \
  --backend-log /workspace/logs/llamacpp-backend-<run>.log \
  --proxy-log /workspace/logs/<run>/proxy.log \
  --target-context 262144 \
  --max-iterations 1000 \
  --fail-fast
```

With `--target-context`, the script cycles through the selected manifest problems until the latest backend `stop processing: n_tokens = ...` reaches the target context or `--max-iterations` is hit.

The generated report includes 30k context bands:

```text
0-30k, 30-60k, 60-90k, ... up to the max observed context
```

For each band it reports prefill TPS, generation TPS, median TPS, and draft acceptance.

## Outputs

```text
benchmark/runs/<run-id>/requests.jsonl
benchmark/runs/<run-id>/responses/*.json
benchmark/runs/<run-id>/report.md
```

## Pi config examples

Examples are provided for registering the Vast llama.cpp endpoint as its own pi provider/model:

```text
.pi/models.json.example
.pi/settings.json.example
```

To use them for a pi session, copy them to real local config files and launch pi with the explicit model:

```bash
cp .pi/models.json.example .pi/models.json
cp .pi/settings.json.example .pi/settings.json
PI_CODING_AGENT_DIR="$PWD/.pi" \
  LLAMACPP_API_KEY="$LLAMACPP_API_KEY" \
  pi --model vast-llamacpp-benchmark/qwen3.6-28b-reap-iq3-m
```

Do not rely on changing a global default model for benchmark runs. Specify the model at launch.

## Manifest growth

Add more problems to the manifest in fixed order. Each problem binds its target language with `language` and `code_fence` so tasks can be designed to elicit language-specific implementation patterns.
