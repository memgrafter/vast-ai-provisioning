# Additional Model Profile Plan

## Goal

Add another model by adding profiles only. The refactor already made model, GPU, launch, template-building, and transfer paths profile-driven.

Target model:

```text
QuantTrio/Qwen3.6-27B-AWQ
```

Current known-good model remains:

```text
config/models/qwen3.5-9b-awq.json
```

## Principle

Do not change launcher/provisioner/template builder architecture for a new model. Add profile files, mirror the model, build/apply a model-specific template payload, and launch with the new launch profile.

Each model/profile case should have its own remote Vast template. Do not mutate a shared 9B template for a 27B launch. Manual tuning is expected for GPU requirements, pricing, storage, vLLM args, and interruption strategy.

---

# Phase 1 — Add 27B model profile

- [ ] Add:

```text
config/models/qwen3.6-27b-awq.json
```

- [ ] Include:
  - [ ] `name = qwen3.6-27b-awq`
  - [ ] `hf_model_id = QuantTrio/Qwen3.6-27B-AWQ`
  - [ ] `r2_prefix = QuantTrio/Qwen3.6-27B-AWQ`
  - [ ] `model_dir = /workspace/models/QuantTrio/Qwen3.6-27B-AWQ`
  - [ ] `served_model_name = qwen3.6-27b-awq`
  - [ ] estimated model download size
  - [ ] vLLM dtype
  - [ ] vLLM max model length
  - [ ] vLLM GPU memory utilization
  - [ ] vLLM host/port/download directory
  - [ ] trust-remote-code setting
  - [ ] optional extra args
  - [ ] nullable forced quantization

- [ ] Keep forced quantization null until the actual model config is inspected.

---

# Phase 2 — Add 27B GPU profile

- [ ] Add:

```text
config/gpu-profiles/qwen-27b-awq-48gb.json
```

- [ ] Start with 48GB-class single-GPU requirements:
  - [ ] `num_gpus = 1`
  - [ ] `min_gpu_total_ram_mb >= 45000`
  - [ ] CUDA requirement matching current image support
  - [ ] allowed GPUs such as L40S, RTX A6000, RTX 6000 Ada, A100, H100-class cards

- [ ] Avoid 24GB cards for the first 27B profile unless deliberately creating a constrained profile later.

---

# Phase 3 — Add 27B launch profiles

## 3.1 Add interruptible launch profile

- [ ] Add:

```text
config/launch-profiles/qwen3.6-27b-awq.interruptible.json
```

- [ ] Reference:
  - [ ] `config/models/qwen3.6-27b-awq.json`
  - [ ] `config/gpu-profiles/qwen-27b-awq-48gb.json`

- [ ] Use larger storage than the 9B profile.
- [ ] Use higher price/bid ceilings appropriate for 48GB cards.
- [ ] Keep preferred/greylisted machine handling profile-local.

## 3.2 Add stable launch profile

- [ ] Add if needed:

```text
config/launch-profiles/qwen3.6-27b-awq.stable.json
```

- [ ] Use on-demand market for first serious validation if interruptible churn is too costly.

---

# Phase 4 — Mirror model to R2

- [ ] Use the profile-driven transfer command:

```bash
source env.modeltransfer
./transfer_model_to_R2.sh --model-profile config/models/qwen3.6-27b-awq.json
```

- [ ] Confirm the model exists under the profile R2 prefix.

---

# Phase 5 — Build and apply a separate 27B template payload

- [ ] Use a model-specific remote Vast template for 27B, separate from the current 9B template.
- [ ] Set the intended 27B remote template name in the private overlay or rendered payload, for example:

```text
vLLM_R2_Qwen3_6_27B_AWQ
```

- [ ] Build a reviewed local rendered template payload:

```bash
./run.sh scripts/build_vast_template.py \
  --template-spec config/templates/vllm-r2-base.public.json \
  --private-overlay config/private/vllm-r2.local.json \
  --model-profile config/models/qwen3.6-27b-awq.json \
  --out state/templates/vllm-r2.qwen3.6-27b-awq.rendered.json
```

- [ ] Create the separate 27B remote Vast template on first use and write the resulting hash directly into the 27B launch profile:

```bash
. env.vast-management
./run.sh scripts/apply_vast_template.py \
  --create \
  --template state/templates/vllm-r2.qwen3.6-27b-awq.rendered.json \
  --update-launch-profile config/launch-profiles/qwen3.6-27b-awq.interruptible.json
```

- [ ] For later edits to the same 27B template, update by the 27B template hash:

```bash
. env.vast-management
./run.sh scripts/apply_vast_template.py \
  --hash-id <remote-27b-template-hash> \
  --template state/templates/vllm-r2.qwen3.6-27b-awq.rendered.json \
  --update-launch-profile config/launch-profiles/qwen3.6-27b-awq.interruptible.json
```

- [ ] Record the resulting 27B template hash in the 27B launch profile.
- [ ] Do not overwrite the current 9B template hash in `config/launch-profiles/qwen3.5-9b-awq.interruptible.json`.

---

# Phase 6 — Launch with the 27B launch profile

- [ ] Launch directly with the profile:

```bash
. env.vast-management
./run.sh scripts/select_and_launch.py \
  --launch-profile config/launch-profiles/qwen3.6-27b-awq.interruptible.json
```

- [ ] If interruptible churn prevents validation, use the stable/on-demand profile.

---

# Phase 7 — Record what we learn

- [ ] If a machine works well, add it to the 27B launch profile preferred list.
- [ ] If a machine fails for machine-specific reasons, add it to the 27B launch profile greylist.
- [ ] If vLLM needs different args, update only the 27B model profile.
- [ ] If GPU requirements are too low or too high, update only the 27B GPU profile.

---

# Done criteria

- [ ] 27B model profile exists.
- [ ] 27B GPU profile exists.
- [ ] 27B launch profile exists.
- [ ] 27B has its own remote Vast template/hash separate from the 9B template.
- [ ] Model is mirrored to R2 via `--model-profile`.
- [ ] Template payload is built from model profile and applied remotely.
- [ ] Launcher uses the 27B launch profile directly.
- [ ] Any learned machine/model/vLLM changes are captured in profile files only.
