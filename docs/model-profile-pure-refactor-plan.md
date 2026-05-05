# Pure Model/Profile Refactor Plan

## Goal

Separate model, GPU, launch, and vLLM runtime concerns without preserving legacy compatibility layers.

This is a pure refactor plan. It intentionally excludes:

- test tasks;
- validation tasks;
- live launch tasks;
- new model rollout tasks;
- 27B-specific work;
- pricing or bidding changes;
- backward-compatibility shims;
- rendered legacy policy adapters.

The refactor should make the profile-based shape the only supported shape.

## Current coupling to remove

- [x] Move model identity out of the monolithic launch policy.
- [x] Move GPU selection rules out of the monolithic launch policy.
- [x] Move vLLM runtime parameters out of hardcoded provisioning script content.
- [x] Remove the monolithic launch-policy shape as an active interface.
- [x] Make profile-based config the direct interface for launcher, template building, provisioning, and transfer tooling.

---

# Phase 1 — Introduce current model profile

## 1.1 Add profile directory

- [x] Create:

```text
config/models/
```

## 1.2 Add current model profile

- [x] Add a profile for the currently working model:

```text
config/models/qwen3.5-9b-awq.json
```

- [x] Move current model-specific fields into it:
  - [x] profile name
  - [x] Hugging Face model ID
  - [x] R2 prefix
  - [x] local model directory
  - [x] served model name
  - [x] quantization metadata
  - [x] expected model download size
  - [x] vLLM dtype
  - [x] vLLM max model length
  - [x] vLLM GPU memory utilization
  - [x] vLLM host
  - [x] vLLM port
  - [x] vLLM download directory
  - [x] vLLM trust-remote-code setting
  - [x] optional vLLM extra args
  - [x] optional forced quantization value

## 1.3 Keep quantization policy explicit

- [x] Represent quantization metadata separately from forced vLLM CLI quantization.
- [x] Use a nullable field for forced quantization.
- [x] Do not imply that metadata automatically becomes a `--quantization` CLI argument.

---

# Phase 2 — Introduce current GPU profile

## 2.1 Add GPU profile directory

- [x] Create:

```text
config/gpu-profiles/
```

## 2.2 Add current GPU profile

- [x] Add:

```text
config/gpu-profiles/qwen-9b-awq-1gpu.json
```

- [x] Move current GPU policy fields into it:
  - [x] preferred GPU name
  - [x] allowed GPU names
  - [x] number of GPUs
  - [x] minimum total GPU RAM in MB
  - [x] minimum CUDA version

---

# Phase 3 — Introduce current launch profile

## 3.1 Add launch profile directory

- [x] Create:

```text
config/launch-profiles/
```

## 3.2 Add current launch profile

- [x] Add:

```text
config/launch-profiles/qwen3.5-9b-awq.interruptible.json
```

- [x] Reference the current model profile.
- [x] Reference the current GPU profile.
- [x] Keep template identity in the launch profile.
- [x] Keep market type in the launch profile.
- [x] Keep storage policy in the launch profile.
- [x] Keep network policy in the launch profile.
- [x] Keep pricing policy in the launch profile.
- [x] Keep reliability policy in the launch profile.
- [x] Keep interruptible/bid policy in the launch profile.
- [x] Keep selection policy in the launch profile.

---

# Phase 4 — Refactor launcher to consume launch profiles directly

## 4.1 Remove monolithic policy as the primary input

- [x] Stop treating `config/launch-policy.l40s-prototype.json` as the operational source of truth.
- [x] Make launch profiles the direct launcher input.
- [x] Remove the need for a rendered intermediate policy file.
- [x] Do not add `scripts/render_launch_policy.py`.

## 4.2 Direct launcher inputs

- [x] Make the launcher accept a launch profile path.
- [x] Load the launch profile directly.
- [x] Load the referenced model profile directly.
- [x] Load the referenced GPU profile directly.
- [x] Compose these in memory into an internal launch context.

## 4.3 Internal launch context

- [x] Build an internal object or dictionary with:
  - [x] launch profile metadata
  - [x] model profile data
  - [x] GPU profile data
  - [x] template identity
  - [x] market type
  - [x] storage policy
  - [x] network policy
  - [x] pricing policy
  - [x] reliability policy
  - [x] interruptible/bid policy
  - [x] selection policy

## 4.4 Update launcher selection code to use launch context

- [x] Read GPU requirements from the GPU profile section of launch context.
- [x] Read storage requirements from launch profile section of launch context.
- [x] Read network requirements from launch profile section of launch context.
- [x] Read reliability requirements from launch profile section of launch context.
- [x] Read pricing requirements from launch profile section of launch context.
- [x] Read preferred machine IDs from launch profile selection section.
- [x] Read greylisted machine IDs from launch profile selection section.
- [x] Read expected model download size from the model profile unless the launch profile overrides it.

## 4.5 Update launcher output

- [x] Print selected model profile name.
- [x] Print served model name.
- [x] Print Hugging Face model ID.
- [x] Print R2 prefix.
- [x] Print GPU profile name.
- [x] Print market type.
- [x] Print template name/hash.
- [x] Continue printing cost, storage, bandwidth, reliability, preferred, and greylist details.

## 4.6 Remove legacy compatibility assumptions

- [x] Remove assumptions that model data lives under a monolithic `model` key.
- [x] Remove assumptions that GPU data lives under a monolithic `gpu` key loaded from one policy file.
- [x] Remove assumptions that selection data comes from one policy file.
- [x] Remove default dependency on `config/launch-policy.l40s-prototype.json` once launch profile input exists.

## 4.7 Avoid unrelated behavior changes

- [x] Do not change offer filtering semantics except for reading values from the new context.
- [x] Do not change cost gate semantics except for reading values from the new context.
- [x] Do not change preferred machine semantics except for reading values from the new context.
- [x] Do not change greylist semantics except for reading values from the new context.
- [x] Do not change market mapping semantics except for reading values from the new context.
- [x] Do not change monitor startup semantics except for passing through profile-derived metadata if needed.

---

# Phase 5 — Make provisioning vLLM args env-driven

## 5.1 Remove hardcoded served-model args

- [x] Replace hardcoded vLLM args in:

```text
provision_vast_vllm_from_r2.sh
```

- [x] Generate `/etc/vllm-args.conf` from environment variables instead.

## 5.2 Supported vLLM env vars

- [x] Support `SERVED_MODEL_NAME`.
- [x] Support `VLLM_DTYPE`.
- [x] Support `VLLM_MAX_MODEL_LEN`.
- [x] Support `VLLM_HOST`.
- [x] Support `VLLM_PORT`.
- [x] Support `VLLM_DOWNLOAD_DIR`.
- [x] Support `VLLM_GPU_MEMORY_UTILIZATION`.
- [x] Support `VLLM_TRUST_REMOTE_CODE`.
- [x] Support `VLLM_FORCE_QUANTIZATION`.
- [x] Support `VLLM_EXTRA_ARGS`.

## 5.3 Defaults

- [x] Default `SERVED_MODEL_NAME` from an explicit env var or existing model context.
- [x] Default `VLLM_DTYPE` to the current value.
- [x] Default `VLLM_MAX_MODEL_LEN` to the current value.
- [x] Default `VLLM_HOST` to the current value.
- [x] Default `VLLM_PORT` to the current value.
- [x] Default `VLLM_DOWNLOAD_DIR` to the current value.
- [x] Default `VLLM_GPU_MEMORY_UTILIZATION` to the current value.
- [x] Default `VLLM_TRUST_REMOTE_CODE` to the current value.

## 5.4 API key handling

- [x] Preserve literal runtime expansion of:

```bash
${VLLM_API_KEY}
```

- [x] Keep API key value out of logs.
- [x] Keep API key value out of generated public files.
- [x] Keep API key value out of committed template snapshots.

## 5.5 Quantization handling

- [x] Only emit `--quantization` when `VLLM_FORCE_QUANTIZATION` is non-empty.
- [x] Do not derive `--quantization` automatically from profile metadata.

## 5.6 Extra args handling

- [x] Append `VLLM_EXTRA_ARGS` after generated core args.
- [x] Keep empty extra args as no-op.

---

# Phase 6 — Build template from model profile

## 6.1 Add profile-aware local template building

- [x] Replace remote-first template patching with local template source-of-truth building.
- [x] Add profile-specific builder script:

```text
scripts/build_vast_template.py
```

## 6.2 Input

- [x] Accept a model profile path.
- [x] Accept a public-safe template spec path.
- [x] Read model profile fields.
- [x] Convert model profile fields into non-secret Vast template env vars.

## 6.3 Template env output

- [x] Set `R2_PREFIX` from model profile.
- [x] Set `MODEL_DIR` from model profile.
- [x] Set `VLLM_MODEL` from model profile model directory.
- [x] Set `SERVED_MODEL_NAME` from model profile.
- [x] Set `VLLM_DTYPE` from model profile.
- [x] Set `VLLM_MAX_MODEL_LEN` from model profile.
- [x] Set `VLLM_HOST` from model profile.
- [x] Set `VLLM_PORT` from model profile.
- [x] Set `VLLM_DOWNLOAD_DIR` from model profile.
- [x] Set `VLLM_GPU_MEMORY_UTILIZATION` from model profile.
- [x] Set `VLLM_TRUST_REMOTE_CODE` from model profile.
- [x] Set `VLLM_FORCE_QUANTIZATION` from model profile when present.
- [x] Set `VLLM_EXTRA_ARGS` from model profile when present.

## 6.4 Preserve existing template behavior

- [x] Keep `VLLM_ARGS` empty.
- [x] Keep `AUTH_EXCLUDE` unchanged.
- [x] Keep provisioning script URL unchanged.
- [x] Keep template secret-free.

## 6.5 Remaining work

- [x] Add explicit remote apply/update command that writes the locally rendered template payload to Vast.
- [x] Add private ignored overlay support for private-but-not-secret values such as real R2 bucket and endpoint.

---

# Phase 7 — Transfer script profile input

## 7.1 Add model-profile input

- [x] Extend:

```text
transfer_model_to_R2.sh
```

- [x] Accept a model profile path.

## 7.2 Profile-derived transfer fields

- [x] Read Hugging Face model ID from the model profile.
- [x] Read R2 prefix from the model profile.

## 7.3 Preserve existing env input

- [ ] Keep existing env-based transfer behavior.
- [x] Keep full-repo transfer behavior available.
- [ ] Keep single-file transfer behavior available if already supported.

Note: env-based model selection was intentionally removed from the active interface. `env.modeltransfer` remains the source for credentials/private R2 settings only.

---

# Phase 8 — Environment cleanup

## 8.1 Consolidate env file responsibilities

- [ ] Make `env.vast-management` only responsible for Vast management/auth and local client-side API testing variables.
- [ ] Make `env.modeltransfer` only responsible for Hugging Face download auth and R2 transfer credentials/private destinations.
- [ ] Keep Vast runtime secrets only in Vast account-level env vars, not launch/template/profile files.
- [ ] Document which env vars are local-only versus injected into Vast runtime.

## 8.2 Remove confusing duplicated model envs

- [ ] Remove model identity from local env files now that model profiles own `hf_model_id` and `r2_prefix`.
- [ ] Remove stale `HF_REPO_ID`, `MODEL_ID`, `HF_FILENAME`, or `R2_PREFIX` expectations from docs/scripts unless they are credentials/private-destination related.
- [ ] Keep model selection explicit via `--model-profile`.

## 8.3 Add safe env examples

- [ ] Update example env files so they contain credentials/private destination placeholders only.
- [ ] Do not include real bucket names, account IDs, API keys, tokens, or instance URLs.
- [ ] Include comments showing which values belong in Vast account-level env vars.

---

# Phase 9 — Documentation cleanup

## 8.1 Update operator docs

- [x] Replace single-current-model language with profile language.
- [x] Document model profiles.
- [x] Document GPU profiles.
- [x] Document launch profiles.
- [x] Document direct launcher use of launch profiles.

## 8.2 Update operational commands

- [x] Document direct launch-profile command.
- [x] Document profile-aware template building.
- [x] Document profile-aware model transfer.

## 8.3 Keep public docs secret-free

- [x] Do not include API keys.
- [x] Do not include R2 secret keys.
- [x] Do not include Hugging Face tokens.
- [x] Do not include live instance JSON.

---

# Refactor boundaries

## In scope

- [x] Config decomposition.
- [x] Direct launch-profile consumption by launcher.
- [x] Env-driven vLLM args generation.
- [x] Profile-aware template building.
- [x] Profile-aware transfer inputs.
- [x] Removal of monolithic policy as an active interface.

## Out of scope

- [x] Adding a new model operationally.
- [x] Changing GPU selection behavior.
- [x] Changing bidding strategy.
- [x] Changing monitor destroy behavior.
- [x] Adding SQLite history tracking.
- [x] Running live Vast launches.
- [x] Mirroring new Hugging Face repos.
- [x] Changing public/private template policy.

---

# Desired end state

- [x] Current model information lives in `config/models/`.
- [x] Current GPU selection information lives in `config/gpu-profiles/`.
- [x] Current launch policy information lives in `config/launch-profiles/`.
- [x] The launcher consumes launch profiles directly.
- [x] No rendered legacy policy adapter is required.
- [x] Provisioning script no longer hardcodes the current served model name.
- [x] Template building can derive non-secret model env vars from a model profile.
- [x] Transfer script can derive source/destination model identifiers from a model profile.
