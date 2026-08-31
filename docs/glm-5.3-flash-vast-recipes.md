# GLM-5.3-Flash (uncensored FP8) — Vast launch recipes

Four ready-to-test launch recipes for `orcarouter/GLM-5.3-Flash-Uncensored-FP8`
(321B/18B-active MoE, multimodal, 1M native context, FP8, 305.8 GiB on R2).

## Why a new template spec

GLM-5.3-Flash (`glm5_next` arch) requires **vLLM 0.29+ with the GLM-5.3
integration and FlashInfer ≥ 0.6.17** (NoPE sparse MLA). The stock
`vastai/vllm:v0.22.0-cuda-13.0` image used by `vllm-r2-base.public.json` is too
old, and the `glm53-flash` image has **no Vast supervisor** — its entrypoint is
plain `vllm serve`. So these recipes use:

- **Template spec**: `config/templates/vllm-glm53-flash.public.json`
  - image `vllm/vllm-openai:glm53-flash` (amd64, CUDA 13.0.1)
  - `runtype: ssh` + `ssh_direct` (onstart is only honored in ssh/jupyter modes)
  - onstart fetches `provision_glm53_flash_from_r2.sh` and execs it
- **Provisioning script**: `provision_glm53_flash_from_r2.sh` (public, no
  secrets) — installs awscli, R2-syncs the model, assembles `vllm serve` args
  from the `VLLM_*` env vars, and `exec vllm serve` in the foreground.
- **AWS creds + `VLLM_API_KEY`** come from Vast **account-level env vars**
  (same as all other templates; never in the template env).

## The four recipes

| Config | GPU profile | Model profile | Launch profile | TP | max-model-len | max-num-seqs | KV headroom |
|---|---|---|---|---:|---:|---:|---:|
| 4× H200 | `h200-4gpu-564gb` | `glm-5.3-flash-uncensored-fp8.h200-4gpu` | `...h200-4gpu.on-demand` | 4 | 262144 | 128 | ~236 GB |
| 8× H100 SXM | `h100-sxm-8gpu-640gb` | `...h100-sxm-8gpu` | `...h100-sxm-8gpu.on-demand` | 8 | 262144 | 128 | ~312 GB |
| 8× H200 | `h200-8gpu-1128gb` | `...h200-8gpu` | `...h200-8gpu.on-demand` | 8 | 524288 | 64 | ~800 GB |
| 4× B200 | `b200-4gpu-720gb` | `...b200-4gpu` | `...b200-4gpu.on-demand` | 4 | 262144 | 128 | ~392 GB |

All four share: `kv-cache-dtype fp8`, `gpu-memory-utilization 0.95`,
`max-num-batched-tokens 8192`, MTP spec decode
(`{"method":"mtp","num_speculative_tokens":5}`), `--no-enable-flashinfer-autotune`,
`--enable-auto-tool-choice --tool-call-parser glm47 --reasoning-parser glm45`,
prefix caching, 500 GB disk, on-demand market, verified offers only.

Rendered templates (local, review-ready):
`state/templates/glm-5.3-flash-uncensored-fp8.<cfg>.on-demand.rendered.json`

## To test (when ready)

1. **Push the provisioning script** to the public repo (the onstart fetches it
   from `main`):
   ```bash
   git add provision_glm53_flash_from_r2.sh
   git commit -m "provisioning: self-contained R2 sync + vllm serve for glm53-flash image"
   git push
   ```
2. **Create the remote template** for the config you want (repeat per config):
   ```bash
   . env.vast-management
   ./run.sh scripts/prepare_vast_template.py \
     --launch-profile config/launch-profiles/glm-5.3-flash-uncensored-fp8.h200-8gpu.on-demand.json \
     --template-spec config/templates/vllm-glm53-flash.public.json \
     --create
   ```
   This writes the returned `hash_id` back into the launch profile.
3. **Check offers / launch**:
   ```bash
   . env.vast-management
   ./run.sh scripts/select_and_launch.py \
     --launch-profile config/launch-profiles/glm-5.3-flash-uncensored-fp8.h200-8gpu.on-demand.json \
     --check-only --top 3
   ```
   then drop `--check-only` for the real launch (prompts before search and
   before launch).
4. **Verify** (after `actual_status == running`):
   ```bash
   curl -H "Authorization: Bearer $VLLM_API_KEY" http://<host>:<mapped_8000>/v1/models
   ./run.sh scripts/summarize_vllm_metrics.py --base-url http://<host>:<mapped_8000>/v1
   ```

## Caveats to verify on first test

- **Image tag drift**: `glm53-flash` is a rolling tag. If Z.ai/vLLM change it,
  pin the amd64 digest (`sha256:2e771fa…` at prep time) in the template spec.
- **`runtype: ssh` + onstart**: Vast replaces the image entrypoint in ssh mode;
  the onstart must keep the container alive — it does via `exec vllm serve`.
  Watch the instance log for the R2 sync markers, then `Application startup
  complete.`
- **305.8 GiB R2 sync**: at typical Vast R2 speeds this is ~10–30 min; the
  500 GB disk holds model + headroom.
- **Context sizing**: 8×H200 is set to 512K/64 seqs. For 1M context, lower
  `max_num_seqs` (e.g. 16–32) and raise `max_model_len` to 1048576 — KV
  headroom allows it.
- **Vision**: the model is multimodal (image+video). The recipe serves it with
  vision enabled (no `--language-model-only`). Vision tensors cost ~1 GiB.
- **Pricing caps** in the launch profiles are placeholders (4×H200 $14,
  8×H100 $12, 8×H200 $24, 4×B200 $20 dph) — tune with `--relax-policy` or edit
  after the first `--check-only` scan.
