# Deterministic agentic-coding benchmark

This benchmark uses a static problem manifest. The model solves fixed, language-bound problems; it does not invent benchmark tasks.

The default runner uses the OpenAI-compatible API directly. It does **not** drive a pi tmux pane. This is intentional for clean request/proxy/backend correlation. Pi/tmux mode is available explicitly when you want a real persistent pi session instead of direct HTTP replay.

## Dry run

```bash
python3 benchmark/run_deterministic_agentic_benchmark.py \
  --dry-run \
  --run-id example-dry-run \
  --out-dir benchmark/runs/example-dry-run
```

## Real llama.cpp run to max context

Run this on the host where the llama.cpp backend log is locally readable, or mount/stream that log path locally while the benchmark is running. If `--max-tokens` is omitted, the runner reads `maxTokens` from `.pi/models.json` for the selected model.

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

With `--target-context`, the script cycles through the selected manifest problems until the latest backend `stop processing: n_tokens = ...` reaches the target context or `--max-iterations` is hit. By default each request includes prior turns so the slot grows toward max context. Use `--no-accumulate-context` only for independent-request latency tests.

The generated report includes 30k context bands:

```text
0-30k, 30-60k, 60-90k, ... up to the max observed context
```

For each band it reports prefill TPS, generation TPS, median TPS, and draft acceptance.

## Pi tmux mode

Use `--driver pi-tmux` to run one persistent pi session inside its own tmux session. By default the runner creates a unique tmux session per benchmark run and tears it down on exit unless `--keep-session` is set. In this mode, `--max-iterations` means total turns even when the manifest contains only one problem.

```bash
python3 benchmark/run_deterministic_agentic_benchmark.py \
  --driver pi-tmux \
  --pi-model provider/model \
  --max-iterations 200
```

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

## Reasoning traces

For models configured with `reasoning: true` and `compat.thinkingFormat`, the runner enables the corresponding thinking payload when supported. For `qwen-chat-template`, it sends:

```json
{"chat_template_kwargs": {"enable_thinking": true}}
```

When the response includes `reasoning_content` or `reasoning`, the runner prepends it to the stored assistant message inside `<reasoning>...</reasoning>` before adding it to accumulated history. This keeps replayed context aligned with models whose quality depends on returned reasoning traces.
