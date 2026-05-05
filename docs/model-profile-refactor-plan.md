# Model/GPU Profile Refactor Plan

## Goal

Refactor the Vast.ai vLLM provisioning and launch machinery so the same tooling can serve multiple Hugging Face models with different GPU requirements, R2 prefixes, model directories, served model names, and vLLM parameters.

Initial supported profiles:

- Current tested model: `cyankiwi/Qwen3.5-9B-AWQ-4bit`
- New target model: `QuantTrio/Qwen3.6-27B-AWQ`

## Current problem

The current working path is too model-specific:

- [ ] `provision_vast_vllm_from_r2.sh` hardcodes current 9B vLLM args:
  - [ ] `--served-model-name qwen3.5-9b-awq`
  - [ ] `--max-model-len 8192`
  - [ ] `--gpu-memory-utilization 0.90`
- [ ] `config/launch-policy.l40s-prototype.json` mixes several concerns:
  - [ ] GPU selection policy
  - [ ] model metadata
  - [ ] Vast template identity
  - [ ] pricing strategy
  - [ ] storage/R2 expectations
- [ ] Vast template env vars are model-specific:
  - [ ] `R2_PREFIX`
  - [ ] `MODEL_DIR`
  - [ ] `VLLM_MODEL`
- [ ] Transfer flow assumes one current `MODEL_ID` unless manually edited.

## Refactor principles

- [ ] Preserve the existing script/config shape where practical.
- [ ] Keep `scripts/select_and_launch.py` mostly unchanged at first.
- [ ] Add profile files first, then render them into the existing launch-policy shape.
- [ ] Keep current 9B behavior passing before adding 27B launch behavior.
- [ ] Do not commit secrets, live instance JSON, R2 credentials, Hugging Face tokens, or vLLM API keys.
- [ ] Do not force `--quantization awq` unless the model profile explicitly requests it.
- [ ] Prefer model-declared quantization by default.
- [ ] Use `./test.sh all` before and after each phase.

---

# Phase 0 — Test baseline

- [ ] Run full test suite before refactor:

```bash
./test.sh all
```

- [ ] Confirm all current tests pass.
- [ ] Confirm working tree is clean or only contains intentional changes.
- [ ] Keep `config/launch-policy.l40s-prototype.json` as a compatibility fixture until downstream code is updated.

---

# Phase 1 — Add profile config without behavior change

## 1.1 Create model profile directory

- [ ] Create:

```text
config/models/
```

## 1.2 Add current 9B model profile

- [ ] Add:

```text
config/models/qwen3.5-9b-awq.json
```

- [ ] Include current working model values:

```json
{
  "name": "qwen3.5-9b-awq",
  "hf_model_id": "cyankiwi/Qwen3.5-9B-AWQ-4bit",
  "r2_prefix": "cyankiwi/Qwen3.5-9B-AWQ-4bit",
  "model_dir": "/workspace/models/cyankiwi/Qwen3.5-9B-AWQ-4bit",
  "served_model_name": "qwen3.5-9b-awq",
  "quantization": "compressed-tensors",
  "expected_model_download_tb": 0.01,
  "vllm": {
    "dtype": "half",
    "max_model_len": 8192,
    "gpu_memory_utilization": 0.9,
    "trust_remote_code": true,
    "host": "127.0.0.1",
    "port": 18000,
    "extra_args": [],
    "force_quantization": null
  }
}
```

- [ ] Preserve current behavior:
  - [ ] served model name remains `qwen3.5-9b-awq`
  - [ ] max model length remains `8192`
  - [ ] local model path remains `/workspace/models/cyankiwi/Qwen3.5-9B-AWQ-4bit`
  - [ ] no explicit `--quantization awq`

## 1.3 Add new 27B model profile

- [ ] Add:

```text
config/models/qwen3.6-27b-awq.json
```

- [ ] Include initial target values:

```json
{
  "name": "qwen3.6-27b-awq",
  "hf_model_id": "QuantTrio/Qwen3.6-27B-AWQ",
  "r2_prefix": "QuantTrio/Qwen3.6-27B-AWQ",
  "model_dir": "/workspace/models/QuantTrio/Qwen3.6-27B-AWQ",
  "served_model_name": "qwen3.6-27b-awq",
  "quantization": null,
  "expected_model_download_tb": 0.035,
  "vllm": {
    "dtype": "half",
    "max_model_len": 8192,
    "gpu_memory_utilization": 0.9,
    "trust_remote_code": true,
    "host": "127.0.0.1",
    "port": 18000,
    "extra_args": [],
    "force_quantization": null
  }
}
```

- [ ] Verify actual Hugging Face model config before forcing quantization.
- [ ] Keep `force_quantization` unset/null for first launch.
- [ ] Do not assume repo name `AWQ` means vLLM should receive `--quantization awq`.

## 1.4 Create GPU profile directory

- [ ] Create:

```text
config/gpu-profiles/
```

## 1.5 Add current broad 9B GPU profile

- [ ] Add:

```text
config/gpu-profiles/qwen-9b-awq-1gpu.json
```

- [ ] Include:

```json
{
  "name": "qwen-9b-awq-1gpu",
  "num_gpus": 1,
  "min_gpu_total_ram_mb": 21000,
  "allowed_gpu_names": [
    "L40S",
    "L40",
    "RTX 3090",
    "RTX 3090 Ti",
    "RTX 4090",
    "RTX 5090",
    "RTX A5000",
    "RTX A6000",
    "A10",
    "A100 PCIE",
    "A100 SXM4"
  ],
  "min_cuda_max_good": 13.0
}
```

- [ ] Preserve current `min_gpu_total_ram_mb = 21000`.
- [ ] Preserve current allowed GPU list unless deliberately changed later.

## 1.6 Add 27B GPU profile

- [ ] Add:

```text
config/gpu-profiles/qwen-27b-awq-48gb.json
```

- [ ] Include initial safer 48GB-class target:

```json
{
  "name": "qwen-27b-awq-48gb",
  "num_gpus": 1,
  "min_gpu_total_ram_mb": 45000,
  "allowed_gpu_names": [
    "L40S",
    "L40",
    "RTX A6000",
    "RTX 6000 Ada",
    "RTX 5090",
    "A100 PCIE",
    "A100 SXM4",
    "H100 PCIe",
    "H100 SXM"
  ],
  "min_cuda_max_good": 13.0
}
```

- [ ] Avoid 24GB GPUs by default for the initial 27B path.
- [ ] Consider 24GB experiments later only with constrained settings:
  - [ ] `--max-model-len 4096`
  - [ ] `--gpu-memory-utilization 0.95`

## 1.7 Create launch profile directory

- [ ] Create:

```text
config/launch-profiles/
```

## 1.8 Add current 9B interruptible launch profile

- [ ] Add:

```text
config/launch-profiles/qwen3.5-9b-awq.interruptible.json
```

- [ ] Reference:
  - [ ] `config/models/qwen3.5-9b-awq.json`
  - [ ] `config/gpu-profiles/qwen-9b-awq-1gpu.json`

- [ ] Preserve current template:

```json
"template": {
  "name": "vLLM_R2_Model_20260504",
  "hash_id": "b174caeb667a9c8e5cd7a68bd8b8af2e"
}
```

- [ ] Preserve current pricing/storage/network/reliability/selection behavior from `config/launch-policy.l40s-prototype.json`.

## 1.9 Add 27B interruptible launch profile

- [ ] Add:

```text
config/launch-profiles/qwen3.6-27b-awq.interruptible.json
```

- [ ] Reference:
  - [ ] `config/models/qwen3.6-27b-awq.json`
  - [ ] `config/gpu-profiles/qwen-27b-awq-48gb.json`

- [ ] Use initial 27B launch settings:
  - [ ] `market = interruptible`
  - [ ] `disk_gb = 80`
  - [ ] `min_disk_bw = 500`
  - [ ] `max_dph_total` high enough for 48GB cards, likely `1.5` to start
  - [ ] `spot.max_bid_dph` high enough for validation, likely `2.0` to start
  - [ ] `target_first_test_minutes = 15`

## 1.10 Add 27B stable launch profile

- [ ] Add:

```text
config/launch-profiles/qwen3.6-27b-awq.stable.json
```

- [ ] Reference the same 27B model/GPU profiles.
- [ ] Use:
  - [ ] `market = on-demand`
  - [ ] `disk_gb = 80`
  - [ ] `max_dph_total` high enough for L40S/A6000/A100-class cards
  - [ ] no interruptible bid cap required

## 1.11 Add profile config tests

- [ ] Add:

```text
tests/integration/test_profiles_config.py
```

- [ ] Test all JSON profile files parse.
- [ ] Test launch profiles reference existing model profile files.
- [ ] Test launch profiles reference existing GPU profile files.
- [ ] Test 9B model profile values match current known working values.
- [ ] Test 9B GPU profile preserves `min_gpu_total_ram_mb = 21000`.
- [ ] Test 27B model profile has `hf_model_id = QuantTrio/Qwen3.6-27B-AWQ`.
- [ ] Test 27B GPU profile uses `min_gpu_total_ram_mb >= 45000`.
- [ ] Test `force_quantization` is null/absent unless explicitly set.

## 1.12 Validate Phase 1

- [ ] Run:

```bash
./test.sh all
```

- [ ] Commit Phase 1 separately.

---

# Phase 2 — Render profiles to existing launch policy shape

## 2.1 Add policy renderer

- [ ] Add:

```text
scripts/render_launch_policy.py
```

## 2.2 Define renderer usage

- [ ] Support:

```bash
./run.sh scripts/render_launch_policy.py \
  --launch-profile config/launch-profiles/qwen3.6-27b-awq.interruptible.json \
  --out state/qwen3.6-27b-awq.policy.json
```

- [ ] Output must be compatible with existing `scripts/select_and_launch.py` policy shape.
- [ ] Do not require launcher refactor in this phase.

## 2.3 Renderer behavior

- [ ] Load launch profile JSON.
- [ ] Load referenced model profile JSON.
- [ ] Load referenced GPU profile JSON.
- [ ] Merge into old-style policy keys:
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
- [ ] Set `model.id` from `model_profile.hf_model_id`.
- [ ] Set `model.served_model_name` from `model_profile.served_model_name`.
- [ ] Set `model.quantization` from `model_profile.quantization`.
- [ ] Set `model.max_model_len` from `model_profile.vllm.max_model_len`.
- [ ] Set `selection.expected_model_download_tb` from model profile unless launch profile overrides it.

## 2.4 Keep 9B rendered output semantically equivalent

- [ ] Render 9B profile.
- [ ] Compare to `config/launch-policy.l40s-prototype.json`.
- [ ] Preserve current values:
  - [ ] model id
  - [ ] served model name
  - [ ] quantization metadata
  - [ ] max model length
  - [ ] disk size
  - [ ] min GPU RAM
  - [ ] allowed GPU names
  - [ ] network gates
  - [ ] reliability gates
  - [ ] preferred machine IDs including `1569` and `68063`
  - [ ] greylisted machine IDs including `8357`

## 2.5 Add renderer unit tests

- [ ] Add:

```text
tests/unit/test_render_launch_policy.py
```

- [ ] Test rendered 9B policy preserves:
  - [ ] `model.id = cyankiwi/Qwen3.5-9B-AWQ-4bit`
  - [ ] `model.served_model_name = qwen3.5-9b-awq`
  - [ ] `model.max_model_len = 8192`
  - [ ] `gpu.min_gpu_total_ram_mb = 21000`
  - [ ] preferred machines include `1569`
  - [ ] preferred machines include `68063`
  - [ ] greylist includes `8357`
- [ ] Test rendered 27B interruptible policy has:
  - [ ] `model.id = QuantTrio/Qwen3.6-27B-AWQ`
  - [ ] `model.served_model_name = qwen3.6-27b-awq`
  - [ ] `storage.disk_gb = 80`
  - [ ] `gpu.min_gpu_total_ram_mb >= 45000`
  - [ ] higher price/bid caps than 9B
- [ ] Test rendered 27B stable policy has:
  - [ ] `market = on-demand`
  - [ ] no reliance on interruptible-only behavior

## 2.6 Validate Phase 2

- [ ] Run:

```bash
./test.sh all
```

- [ ] Commit Phase 2 separately.

---

# Phase 3 — Make provisioning vLLM args env-driven

## 3.1 Refactor provisioning args generation

- [ ] Edit:

```text
provision_vast_vllm_from_r2.sh
```

- [ ] Remove hardcoded current-model vLLM args.
- [ ] Generate `/etc/vllm-args.conf` from env vars.

## 3.2 Supported env vars

- [ ] Support:

```bash
SERVED_MODEL_NAME
VLLM_DTYPE
VLLM_MAX_MODEL_LEN
VLLM_HOST
VLLM_PORT
VLLM_DOWNLOAD_DIR
VLLM_GPU_MEMORY_UTILIZATION
VLLM_TRUST_REMOTE_CODE
VLLM_FORCE_QUANTIZATION
VLLM_EXTRA_ARGS
```

## 3.3 Required/default behavior

- [ ] Require or default `SERVED_MODEL_NAME` safely.
- [ ] Default `VLLM_DTYPE` to `half`.
- [ ] Default `VLLM_MAX_MODEL_LEN` to `8192`.
- [ ] Default `VLLM_HOST` to `127.0.0.1`.
- [ ] Default `VLLM_PORT` to `18000`.
- [ ] Default `VLLM_DOWNLOAD_DIR` to `/workspace/models`.
- [ ] Default `VLLM_GPU_MEMORY_UTILIZATION` to `0.90`.
- [ ] Default `VLLM_TRUST_REMOTE_CODE` to `true`.
- [ ] Include `--trust-remote-code` only when enabled.
- [ ] Include `--quantization <value>` only when `VLLM_FORCE_QUANTIZATION` is non-empty.
- [ ] Append `VLLM_EXTRA_ARGS` if non-empty.

## 3.4 Preserve API key behavior

- [ ] Keep literal API key expansion in args file:

```bash
--api-key ${VLLM_API_KEY}
```

- [ ] Do not print the actual API key.
- [ ] Do not expand the API key while writing public logs.
- [ ] Continue requiring Vast account-level env var `VLLM_API_KEY` at runtime.

## 3.5 Expected generated args for 9B

- [ ] Ensure current 9B profile/template can generate:

```bash
--served-model-name qwen3.5-9b-awq \
--dtype half \
--max-model-len 8192 \
--host 127.0.0.1 \
--port 18000 \
--download-dir /workspace/models \
--gpu-memory-utilization 0.90 \
--trust-remote-code \
--api-key ${VLLM_API_KEY}
```

## 3.6 Expected generated args for 27B

- [ ] Ensure 27B profile/template can generate:

```bash
--served-model-name qwen3.6-27b-awq \
--dtype half \
--max-model-len 8192 \
--host 127.0.0.1 \
--port 18000 \
--download-dir /workspace/models \
--gpu-memory-utilization 0.90 \
--trust-remote-code \
--api-key ${VLLM_API_KEY}
```

- [ ] Do not include explicit quantization unless verified and configured.

## 3.7 Update provisioning static tests

- [ ] Update:

```text
tests/integration/test_provisioning_script_static.py
```

- [ ] Replace hardcoded current model assertions with env-driven assertions.
- [ ] Test script references `SERVED_MODEL_NAME`.
- [ ] Test script references `VLLM_MAX_MODEL_LEN`.
- [ ] Test script references `VLLM_GPU_MEMORY_UTILIZATION`.
- [ ] Test script still writes `/etc/vllm-args.conf`.
- [ ] Test script still contains `--api-key ${VLLM_API_KEY}`.
- [ ] Test script does not hardcode `qwen3.5-9b-awq`.
- [ ] Test script does not hardcode stale `--quantization awq`.
- [ ] Test R2/rclone behavior remains intact.
- [ ] Test no obvious secret echoing is introduced.

## 3.8 Validate Phase 3

- [ ] Run:

```bash
./test.sh all
```

- [ ] Patch private Vast template with 9B values first.
- [ ] Run one 9B smoke launch to verify no regression.
- [ ] Confirm `/v1/models` still returns:

```text
qwen3.5-9b-awq
```

- [ ] Confirm `max_model_len = 8192`.
- [ ] Commit Phase 3 separately.

---

# Phase 4 — Patch template from model profile

## 4.1 Add or extend template patching script

- [ ] Either extend:

```text
scripts/patch_vllm_template.py
```

- [ ] Or add:

```text
scripts/patch_template_from_profile.py
```

## 4.2 Define usage

- [ ] Support:

```bash
./run.sh scripts/patch_template_from_profile.py \
  --model-profile config/models/qwen3.6-27b-awq.json
```

## 4.3 Template env vars to update

- [ ] Update only non-secret env vars:
  - [ ] `R2_PREFIX`
  - [ ] `MODEL_DIR`
  - [ ] `VLLM_MODEL`
  - [ ] `SERVED_MODEL_NAME`
  - [ ] `VLLM_DTYPE`
  - [ ] `VLLM_MAX_MODEL_LEN`
  - [ ] `VLLM_HOST`
  - [ ] `VLLM_PORT`
  - [ ] `VLLM_DOWNLOAD_DIR`
  - [ ] `VLLM_GPU_MEMORY_UTILIZATION`
  - [ ] `VLLM_TRUST_REMOTE_CODE`
  - [ ] `VLLM_FORCE_QUANTIZATION`
  - [ ] `VLLM_EXTRA_ARGS`

## 4.4 Preserve template invariants

- [ ] Keep:

```bash
VLLM_ARGS=""
```

- [ ] Keep:

```bash
AUTH_EXCLUDE="8000"
```

- [ ] Keep:

```bash
PROVISIONING_SCRIPT="https://raw.githubusercontent.com/memgrafter/vast-ai-provisioning/main/provision_vast_vllm_from_r2.sh"
```

- [ ] Do not add actual secrets to template.
- [ ] Template may reference `VLLM_API_KEY` by name only.

## 4.5 Snapshot remote template before patching

- [ ] Before editing remote Vast template, download timestamped private snapshot under ignored `templates/`.
- [ ] Do not commit private template snapshots.
- [ ] Keep/update public-safe template skeleton only if sanitized.

## 4.6 Add patcher tests

- [ ] Add:

```text
tests/unit/test_patch_template_from_profile.py
```

- [ ] Use fake local template JSON.
- [ ] Do not call Vast API.
- [ ] Test 9B profile renders expected env vars.
- [ ] Test 27B profile renders expected env vars.
- [ ] Test no secret values are inserted.
- [ ] Test `VLLM_ARGS` remains empty.

## 4.7 Validate Phase 4

- [ ] Run:

```bash
./test.sh all
```

- [ ] Patch private template with 9B profile first.
- [ ] Run one 9B smoke launch if needed.
- [ ] Patch private template with 27B profile only after 27B model is mirrored to R2.
- [ ] Commit Phase 4 separately.

---

# Phase 5 — Transfer script accepts model profile

## 5.1 Refactor transfer script

- [ ] Edit:

```text
transfer_model_to_R2.sh
```

- [ ] Add model profile support:

```bash
./transfer_model_to_R2.sh --model-profile config/models/qwen3.6-27b-awq.json
```

## 5.2 Transfer behavior

- [ ] Read `hf_model_id` from model profile.
- [ ] Read `r2_prefix` from model profile.
- [ ] Mirror full Hugging Face repo to:

```text
s3://$R2_BUCKET/<r2_prefix>
```

- [ ] Keep `HF_FILENAME=""` / full-repo transfer as default for vLLM models.

## 5.3 Backward compatibility

- [ ] Preserve existing env-based behavior:
  - [ ] `MODEL_ID`
  - [ ] `HF_FILENAME`
  - [ ] `R2_PREFIX`

- [ ] Existing current-model transfer flow should still work.

## 5.4 Transfer tests

- [ ] Add static tests:

```text
tests/integration/test_transfer_script_static.py
```

- [ ] Test script accepts `--model-profile`.
- [ ] Test script references `hf_model_id`.
- [ ] Test script references `r2_prefix`.
- [ ] Test script does not require secrets in committed files.
- [ ] Test backward-compatible env names still exist.

## 5.5 Validate Phase 5

- [ ] Run:

```bash
./test.sh all
```

- [ ] Mirror 27B model to R2 when ready:

```bash
source env.modeltransfer
./transfer_model_to_R2.sh --model-profile config/models/qwen3.6-27b-awq.json
```

- [ ] Commit Phase 5 separately.

---

# Phase 6 — Launcher convenience for launch profiles

## 6.1 Add optional launch-profile flag

- [ ] Extend:

```text
scripts/select_and_launch.py
```

- [ ] Support:

```bash
./run.sh scripts/select_and_launch.py \
  --launch-profile config/launch-profiles/qwen3.6-27b-awq.interruptible.json
```

## 6.2 Internal behavior

- [ ] Render launch profile to a temp/ignored policy under `state/`.
- [ ] Continue using existing launcher selection logic.
- [ ] Keep existing `--policy` behavior.
- [ ] Do not remove compatibility with `config/launch-policy.l40s-prototype.json`.

## 6.3 Launcher tests

- [ ] Add or update unit tests for:
  - [ ] `--policy` still works.
  - [ ] `--launch-profile` renders and launches through same path.
  - [ ] generated search query still uses GPU RAM in GB-ish units, e.g. `gpu_total_ram>=45.0` for 27B.
  - [ ] market mapping still works for `interruptible` and `on-demand`.

## 6.4 Validate Phase 6

- [ ] Run:

```bash
./test.sh all
```

- [ ] Commit Phase 6 separately.

---

# Phase 7 — Monitor/profile validation improvements

## 7.1 Expected served model name

- [ ] Allow monitor/API validation to know expected served model name from policy/profile.
- [ ] Fail or warn if `/v1/models` returns full local path instead of profile `served_model_name`.

## 7.2 27B-specific startup validation

- [ ] Detect common 27B failures:
  - [ ] CUDA OOM
  - [ ] quantization mismatch
  - [ ] max model length too high
  - [ ] model architecture unsupported
  - [ ] missing trust-remote-code issue

## 7.3 Prefix/cache and launch-time metrics

- [ ] Record launch-to-ready time.
- [ ] Record percentage of expected useful runtime spent launching.
- [ ] Record vLLM prefix cache hit rate when visible in logs.
- [ ] Feed these into future SQLite history DB.

## 7.4 Validate Phase 7

- [ ] Run:

```bash
./test.sh all
```

- [ ] Commit Phase 7 separately.

---

# Phase 8 — Documentation updates

## 8.1 Update AGENTS.md

- [ ] Replace singular `Current model` language with profile-based language.
- [ ] Add default tested model profile:

```text
config/models/qwen3.5-9b-awq.json
```

- [ ] Add new intended 27B profile:

```text
config/models/qwen3.6-27b-awq.json
```

- [ ] Document required Vast account-level env vars remain:

```bash
AWS_ACCESS_KEY_ID
AWS_SECRET_ACCESS_KEY
VLLM_API_KEY
```

## 8.2 Update README.md

- [ ] Keep README succinct.
- [ ] Point to profile workflow and `AGENTS.md`.

## 8.3 Update bidding strategy docs

- [ ] Update:

```text
VAST_BIDDING_STRATEGY.md
```

- [ ] Add note that 27B failures/interruption are more expensive.
- [ ] Recommend high-bid interruptible or on-demand for first 27B validation.
- [ ] Recommend 48GB+ GPU profile for first 27B validation.

## 8.4 Update todo.txt

- [ ] Link profile refactor to SQLite history DB idea.
- [ ] Add future task: score machine suitability by model profile, not globally.

## 8.5 Validate Phase 8

- [ ] Run:

```bash
./test.sh all
```

- [ ] Commit Phase 8 separately.

---

# Phase 9 — First 27B operational rollout

## 9.1 Inspect model config

- [ ] Inspect `QuantTrio/Qwen3.6-27B-AWQ` config before launch.
- [ ] Verify quantization method.
- [ ] Decide whether `force_quantization` should remain null or be explicitly set.
- [ ] Update model profile only if needed.

## 9.2 Mirror 27B to R2

- [ ] Run:

```bash
source env.modeltransfer
./transfer_model_to_R2.sh --model-profile config/models/qwen3.6-27b-awq.json
```

- [ ] Verify R2 objects exist under:

```text
s3://$R2_BUCKET/QuantTrio/Qwen3.6-27B-AWQ
```

## 9.3 Patch template for 27B

- [ ] Snapshot remote private template under ignored `templates/`.
- [ ] Patch template using 27B model profile.
- [ ] Verify template contains only non-secret profile values.
- [ ] Verify `VLLM_ARGS=""` remains empty.

## 9.4 Render 27B policy

- [ ] Run:

```bash
./run.sh scripts/render_launch_policy.py \
  --launch-profile config/launch-profiles/qwen3.6-27b-awq.interruptible.json \
  --out state/qwen3.6-27b-awq.policy.json
```

## 9.5 Choose first-launch market

- [ ] Prefer high-bid interruptible or on-demand to avoid conflating model fit with interruption.
- [ ] Initial recommended settings:
  - [ ] `market = on-demand` or high-bid interruptible
  - [ ] `disk_gb = 80`
  - [ ] `min_gpu_total_ram_mb >= 45000`
  - [ ] GPU class: L40S/A6000/A100/H100
  - [ ] `max_model_len = 8192`
  - [ ] `force_quantization = null`

## 9.6 Launch 27B smoke test

- [ ] Run launcher with rendered 27B policy.
- [ ] Watch readiness monitor.
- [ ] Confirm R2 speed gate passes.
- [ ] Confirm sync completes.
- [ ] Confirm vLLM starts on:

```text
127.0.0.1:18000
```

- [ ] Confirm external mapped `8000` endpoint works.
- [ ] Confirm `/v1/models` returns:

```text
qwen3.6-27b-awq
```

- [ ] Confirm `max_model_len = 8192`.
- [ ] Run `/v1/chat/completions` smoke test.

## 9.7 If 27B fails

- [ ] If CUDA OOM:
  - [ ] reduce `max_model_len` to `4096`
  - [ ] consider `gpu_memory_utilization = 0.95`
  - [ ] use larger GPU class if needed
- [ ] If quantization mismatch:
  - [ ] inspect model config
  - [ ] update `quantization` metadata
  - [ ] set or unset `force_quantization` accordingly
- [ ] If model load too slow:
  - [ ] prefer cached/proven machines
  - [ ] consider on-demand
  - [ ] record launch-time percentage
- [ ] If R2 sync too slow:
  - [ ] greylist machine/path by reason
  - [ ] record R2 speed in history DB when available

## 9.8 Record outcome

- [ ] Update preferred machine list if successful.
- [ ] Update greylist if failure is machine-specific.
- [ ] Add notes to `todo.txt` or future SQLite history DB.
- [ ] Commit safe config/doc updates only.

---

# 27B initial assumptions

- [ ] Start with 48GB+ VRAM target.
- [ ] Start with `disk_gb = 80`.
- [ ] Start with `max_model_len = 8192`.
- [ ] Start with `gpu_memory_utilization = 0.90`.
- [ ] Start with `force_quantization = null`.
- [ ] Use high-bid interruptible or on-demand for first validation.
- [ ] Avoid 24GB cards until the 48GB path is proven.

Potential first GPU candidates:

- [ ] L40S 48GB
- [ ] RTX A6000 48GB
- [ ] RTX 6000 Ada 48GB
- [ ] A100 40GB/80GB
- [ ] H100 80GB

Avoid initially unless intentionally testing constrained mode:

- [ ] RTX 3090
- [ ] RTX 4090
- [ ] A10
- [ ] L4

---

# Commit strategy

- [ ] Commit 1: profile files + profile tests.
- [ ] Commit 2: policy renderer + renderer tests.
- [ ] Commit 3: env-driven provisioning args + static tests.
- [ ] Commit 4: template patch from profile + tests.
- [ ] Commit 5: transfer script profile support + tests.
- [ ] Commit 6: launcher `--launch-profile` convenience + tests.
- [ ] Commit 7: monitor/profile validation improvements + tests.
- [ ] Commit 8: docs updates.
- [ ] Commit 9: safe 27B operational config updates after first launch learnings.

---

# Required validation after each commit

- [ ] Run:

```bash
./test.sh all
```

- [ ] Verify no secrets are staged:

```bash
git diff --cached
```

- [ ] Verify ignored runtime/private files are not staged:
  - [ ] `instances/`
  - [ ] `offers/`
  - [ ] `state/`
  - [ ] private `templates/*.json` snapshots
  - [ ] `env.modeltransfer`
  - [ ] `env.vast-management`

- [ ] Commit only public-safe code/config/docs/tests.
