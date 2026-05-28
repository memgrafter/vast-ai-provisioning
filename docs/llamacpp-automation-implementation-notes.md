Wrote the first automation slice:

```text
docs/llamacpp-vast-automation-onepager.md
docs/llamacpp-vast-automation-technical-design.md
scripts/select_launch_llamacpp.py
```

Validation run:

```bash
./run.sh scripts/select_launch_llamacpp.py \
  --check-only \
  --skip-current-infra \
  --top 1 \
  --search-limit 10
```

It found passing verified on-demand 5060 Ti offers and selected one.

Script shape:

```bash
. env.vast-management
. env.modeltransfer

./run.sh scripts/select_launch_llamacpp.py \
  --model-r2-key llama-cpp/qwen3.6-28b-reap-iq3xxs/Qwen3.6-28B-REAP.i1-IQ3_XXS.gguf \
  --artifact-r2-key llama-cpp/artifacts/qwen36-reap-5060ti-linux-cuda.tgz
```

It supports:

- verified on-demand offer search
- `-p 8081:8081` Vast port exposure
- SSH key attach
- R2 model download
- R2 artifact extraction
- optional source build fallback
- remote launcher generation
- `CTX=262144`, `NPRED=32768`
- optional llama.cpp API-key env support if binary supports safe auth
- smoke output / tunnel fallback

Requirements / questions / considerations for next revision:

1. **Artifact format**
   - Need to produce/upload:
     ```text
     llama-cpp/artifacts/qwen36-reap-5060ti-linux-cuda.tgz
     ```
   - Expected contents:
     ```text
     code/llm-cache-llama.cpp/...
     clones/llama-cpp-turboquant/build-cuda/bin/llama-server
     clones/llama-cpp-turboquant/build-cuda/bin/lib*.so*
     ```

2. **Auth**
   - Need confirm current `llama-server` supports `--api-key-file`.
   - If not, decide whether `--api-key` argv exposure is acceptable or keep SSH tunnel only.

3. **Base image**
   - Current default:
     ```text
     nvidia/cuda:12.8.1-devel-ubuntu24.04
     ```
   - Could switch to smaller runtime image once artifact is self-contained.

4. **Artifact builder**
   - Next useful script: build/package/upload the artifact to R2 from a known-good host.

5. **Profiles**
   - For now script flags are explicit.
   - Later: JSON profiles for model/GPU/launch like vLLM path.

6. **Lifecycle**
   - Add optional destroy-on-bootstrap-fail.
   - Add launch ledger rows if this becomes routine.

7. **Metrics extraction**
   - Add parser for llama.cpp logs to output context-band stats automatically:
     30k, 60k, 90k, 120k, 150k, 180k, 200k+.

Check before relying on launch mode:
```bash
python -m py_compile scripts/select_launch_llamacpp.py
./run.sh scripts/select_launch_llamacpp.py --help
```
