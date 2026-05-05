# Pure Model/Profile Refactor Plan

## Goal

Separate model, GPU, launch, and vLLM runtime concerns without changing operational behavior.

This is a pure refactor plan. It intentionally excludes:

- test tasks;
- validation tasks;
- live launch tasks;
- new model rollout tasks;
- 27B-specific work;
- pricing or bidding changes.

The current working behavior should remain functionally identical after the refactor.

## Current coupling to remove

- [ ] Move model identity out of the monolithic launch policy.
- [ ] Move GPU selection rules out of the monolithic launch policy.
- [ ] Move vLLM runtime parameters out of hardcoded provisioning script content.
- [ ] Keep the existing launcher policy shape available as a rendered compatibility output.
- [ ] Keep existing template/provisioning flow compatible with current scripts.

---

# Phase 1 — Introduce current model profile

## 1.1 Add profile directory

- [ ] Create:

```text
config/models/
```

## 1.2 Add current model profile

- [ ] Add a profile for the currently working model:

```text
config/models/qwen3.5-9b-awq.json
```

- [ ] Move current model-specific fields into it:
  - [ ] profile name
  - [ ] Hugging Face model ID
  - [ ] R2 prefix
  - [ ] local model directory
  - [ ] served model name
  - [ ] quantization metadata
  - [ ] expected model download size
  - [ ] vLLM dtype
  - [ ] vLLM max model length
  - [ ] vLLM GPU memory utilization
  - [ ] vLLM host
  - [ ] vLLM port
  - [ ] vLLM download directory
  - [ ] vLLM trust-remote-code setting
  - [ ] optional vLLM extra args
  - [ ] optional forced quantization value

## 1.3 Keep quantization policy explicit

- [ ] Represent quantization metadata separately from forced vLLM CLI quantization.
- [ ] Use a nullable field for forced quantization.
- [ ] Do not imply that metadata automatically becomes a `--quantization` CLI argument.

---

# Phase 2 — Introduce current GPU profile

## 2.1 Add GPU profile directory

- [ ] Create:

```text
config/gpu-profiles/
```

## 2.2 Add current GPU profile

- [ ] Add:

```text
config/gpu-profiles/qwen-9b-awq-1gpu.json
```

- [ ] Move current GPU policy fields into it:
  - [ ] preferred GPU name
  - [ ] allowed GPU names
  - [ ] number of GPUs
  - [ ] minimum total GPU RAM in MB
  - [ ] minimum CUDA version

---

# Phase 3 — Introduce current launch profile

## 3.1 Add launch profile directory

- [ ] Create:

```text
config/launch-profiles/
```

## 3.2 Add current launch profile

- [ ] Add:

```text
config/launch-profiles/qwen3.5-9b-awq.interruptible.json
```

- [ ] Reference the current model profile.
- [ ] Reference the current GPU profile.
- [ ] Keep template identity in the launch profile.
- [ ] Keep market type in the launch profile.
- [ ] Keep storage policy in the launch profile.
- [ ] Keep network policy in the launch profile.
- [ ] Keep pricing policy in the launch profile.
- [ ] Keep reliability policy in the launch profile.
- [ ] Keep interruptible/bid policy in the launch profile.
- [ ] Keep selection policy in the launch profile.

## 3.3 Preserve compatibility policy

- [ ] Leave the current monolithic policy file in place during the refactor.
- [ ] Treat it as a compatibility fixture until the launcher can consume rendered policies.

---

# Phase 4 — Add launch policy renderer

## 4.1 Add renderer script

- [ ] Add:

```text
scripts/render_launch_policy.py
```

## 4.2 Renderer inputs

- [ ] Accept a launch profile path.
- [ ] Load the launch profile.
- [ ] Load the referenced model profile.
- [ ] Load the referenced GPU profile.

## 4.3 Renderer output

- [ ] Emit the existing monolithic launch policy shape.
- [ ] Preserve current top-level policy keys:
  - [ ] `name`
  - [ ] `purpose`
  - [ ] `market`
  - [ ] `template`
  - [ ] `model`
  - [ ] `storage`
  - [ ] `gpu`
  - [ ] `network`
  - [ ] `pricing`
  - [ ] `reliability`
  - [ ] `spot`
  - [ ] `selection`

## 4.4 Field mapping

- [ ] Map model profile `hf_model_id` to rendered policy `model.id`.
- [ ] Map model profile `served_model_name` to rendered policy `model.served_model_name`.
- [ ] Map model profile `quantization` to rendered policy `model.quantization`.
- [ ] Map model profile vLLM max model length to rendered policy `model.max_model_len`.
- [ ] Map GPU profile fields to rendered policy `gpu`.
- [ ] Map launch profile storage fields to rendered policy `storage`.
- [ ] Map launch profile network fields to rendered policy `network`.
- [ ] Map launch profile pricing fields to rendered policy `pricing`.
- [ ] Map launch profile reliability fields to rendered policy `reliability`.
- [ ] Map launch profile interruptible fields to rendered policy `spot`.
- [ ] Map launch profile selection fields to rendered policy `selection`.

## 4.5 Output destination

- [ ] Support writing rendered policy JSON to an explicit output path.
- [ ] Support printing rendered policy JSON to stdout when no output path is supplied.

---

# Phase 5 — Keep launcher compatible

## 5.1 Continue supporting current policy input

- [ ] Keep existing launcher behavior for `--policy` or default policy path.
- [ ] Do not require direct launcher knowledge of model profiles in this phase.

## 5.2 Optional launch-profile convenience

- [ ] Add an optional launcher argument for a launch profile path.
- [ ] Internally render the launch profile to the existing policy shape.
- [ ] Reuse the existing selection and launch code path after rendering.

## 5.3 Avoid selection behavior changes

- [ ] Do not change offer filtering logic.
- [ ] Do not change cost gates.
- [ ] Do not change preferred machine behavior.
- [ ] Do not change greylist behavior.
- [ ] Do not change market mapping.
- [ ] Do not change monitor startup behavior.

---

# Phase 6 — Make provisioning vLLM args env-driven

## 6.1 Remove hardcoded served-model args

- [ ] Replace hardcoded vLLM args in:

```text
provision_vast_vllm_from_r2.sh
```

- [ ] Generate `/etc/vllm-args.conf` from environment variables instead.

## 6.2 Supported vLLM env vars

- [ ] Support `SERVED_MODEL_NAME`.
- [ ] Support `VLLM_DTYPE`.
- [ ] Support `VLLM_MAX_MODEL_LEN`.
- [ ] Support `VLLM_HOST`.
- [ ] Support `VLLM_PORT`.
- [ ] Support `VLLM_DOWNLOAD_DIR`.
- [ ] Support `VLLM_GPU_MEMORY_UTILIZATION`.
- [ ] Support `VLLM_TRUST_REMOTE_CODE`.
- [ ] Support `VLLM_FORCE_QUANTIZATION`.
- [ ] Support `VLLM_EXTRA_ARGS`.

## 6.3 Defaults

- [ ] Default `SERVED_MODEL_NAME` from an explicit env var or existing model context.
- [ ] Default `VLLM_DTYPE` to the current value.
- [ ] Default `VLLM_MAX_MODEL_LEN` to the current value.
- [ ] Default `VLLM_HOST` to the current value.
- [ ] Default `VLLM_PORT` to the current value.
- [ ] Default `VLLM_DOWNLOAD_DIR` to the current value.
- [ ] Default `VLLM_GPU_MEMORY_UTILIZATION` to the current value.
- [ ] Default `VLLM_TRUST_REMOTE_CODE` to the current value.

## 6.4 API key handling

- [ ] Preserve literal runtime expansion of:

```bash
${VLLM_API_KEY}
```

- [ ] Keep API key value out of logs.
- [ ] Keep API key value out of generated public files.
- [ ] Keep API key value out of committed template snapshots.

## 6.5 Quantization handling

- [ ] Only emit `--quantization` when `VLLM_FORCE_QUANTIZATION` is non-empty.
- [ ] Do not derive `--quantization` automatically from profile metadata.

## 6.6 Extra args handling

- [ ] Append `VLLM_EXTRA_ARGS` after generated core args.
- [ ] Keep empty extra args as no-op.

---

# Phase 7 — Patch template from model profile

## 7.1 Add profile-aware template patching

- [ ] Extend the existing template patch script or add a new profile-specific script.

## 7.2 Input

- [ ] Accept a model profile path.
- [ ] Read model profile fields.
- [ ] Convert model profile fields into non-secret Vast template env vars.

## 7.3 Template env output

- [ ] Set `R2_PREFIX` from model profile.
- [ ] Set `MODEL_DIR` from model profile.
- [ ] Set `VLLM_MODEL` from model profile model directory.
- [ ] Set `SERVED_MODEL_NAME` from model profile.
- [ ] Set `VLLM_DTYPE` from model profile.
- [ ] Set `VLLM_MAX_MODEL_LEN` from model profile.
- [ ] Set `VLLM_HOST` from model profile.
- [ ] Set `VLLM_PORT` from model profile.
- [ ] Set `VLLM_DOWNLOAD_DIR` from model profile.
- [ ] Set `VLLM_GPU_MEMORY_UTILIZATION` from model profile.
- [ ] Set `VLLM_TRUST_REMOTE_CODE` from model profile.
- [ ] Set `VLLM_FORCE_QUANTIZATION` from model profile when present.
- [ ] Set `VLLM_EXTRA_ARGS` from model profile when present.

## 7.4 Preserve existing template behavior

- [ ] Keep `VLLM_ARGS` empty.
- [ ] Keep `AUTH_EXCLUDE` unchanged.
- [ ] Keep provisioning script URL unchanged.
- [ ] Keep template secret-free.

---

# Phase 8 — Transfer script profile input

## 8.1 Add model-profile input

- [ ] Extend:

```text
transfer_model_to_R2.sh
```

- [ ] Accept a model profile path.

## 8.2 Profile-derived transfer fields

- [ ] Read Hugging Face model ID from the model profile.
- [ ] Read R2 prefix from the model profile.

## 8.3 Preserve existing env input

- [ ] Keep existing env-based transfer behavior.
- [ ] Keep full-repo transfer behavior available.
- [ ] Keep single-file transfer behavior available if already supported.

---

# Phase 9 — Documentation cleanup

## 9.1 Update operator docs

- [ ] Replace single-current-model language with profile language.
- [ ] Document model profiles.
- [ ] Document GPU profiles.
- [ ] Document launch profiles.
- [ ] Document rendering a launch policy from profiles.

## 9.2 Update operational commands

- [ ] Document profile-rendering command.
- [ ] Document launcher compatibility with rendered policies.
- [ ] Document profile-aware template patching.
- [ ] Document profile-aware model transfer.

## 9.3 Keep public docs secret-free

- [ ] Do not include API keys.
- [ ] Do not include R2 secret keys.
- [ ] Do not include Hugging Face tokens.
- [ ] Do not include live instance JSON.

---

# Refactor boundaries

## In scope

- [ ] Config decomposition.
- [ ] Policy rendering.
- [ ] Env-driven vLLM args generation.
- [ ] Profile-aware template patching.
- [ ] Profile-aware transfer inputs.
- [ ] Backward compatibility with current launcher shape.

## Out of scope

- [ ] Adding a new model operationally.
- [ ] Changing GPU selection behavior.
- [ ] Changing bidding strategy.
- [ ] Changing monitor destroy behavior.
- [ ] Adding SQLite history tracking.
- [ ] Running live Vast launches.
- [ ] Mirroring new Hugging Face repos.
- [ ] Changing public/private template policy.

---

# Desired end state

- [ ] Current model information lives in `config/models/`.
- [ ] Current GPU selection information lives in `config/gpu-profiles/`.
- [ ] Current launch policy information lives in `config/launch-profiles/`.
- [ ] A renderer can produce the existing monolithic policy format.
- [ ] The launcher can continue consuming the existing policy format.
- [ ] Provisioning script no longer hardcodes the current served model name.
- [ ] Template patching can derive non-secret model env vars from a model profile.
- [ ] Transfer script can derive source/destination model identifiers from a model profile.
