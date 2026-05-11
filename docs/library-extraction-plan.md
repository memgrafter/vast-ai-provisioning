# Vast Provisioning: Library Extraction Plan

## Overview

**Current state:** ~1,840 lines of working code across 6 Python scripts, 5 shell scripts, 13 config profiles, 9 docs. Written in a 24h LLM-assisted sprint.

**Goal:** Extract reusable library (`vast-provisioning`) from the monolithic scripts, while keeping the original repo as a thin CLI wrapper.

---

## Stats

### Code inventory

| Category | Count | ~Lines |
|---|---|---|
| Python scripts (core) | 6 | 1,340 |
| Python tests | 8 | ~600 |
| Shell scripts | 5 | ~500 |
| Config profiles (JSON) | 13 | ~300 |
| Documentation (.md) | 9 | ~600 |

### Per-file breakdown

| File | Lines | Role |
|---|---|---|
| `scripts/select_and_launch.py` | ~530 | Infra listing, offer search, policy filtering, cost estimation, instance creation, polling, monitoring, smoke chat, cleanup |
| `scripts/monitor_instance_readiness.py` | ~260 | Log analysis, readiness signals, port URL resolution |
| `scripts/build_vast_template.py` | ~160 | Template payload rendering, env generation, secret safety checks |
| `scripts/apply_vast_template.py` | ~160 | Remote Vast template create/update, manifest validation |
| `scripts/smoke_chat_once.py` | ~150 | Launch → wait → chat → destroy loop with retry |
| `scripts/prepare_vast_template.py` | ~80 | CLI glue: build + apply in one shot |
| `provision_vast_vllm_from_r2.sh` | ~200 | Boot script: R2 speed test → sync → vLLM args |
| `transfer_model_to_R2.sh` | ~100 | HF → R2 upload |

### Ratios

- **Test-to-code:** ~1:1 file ratio (8 tests for 6 scripts)
- **Docs-to-code:** ~1:3 line ratio
- **Duplication:** ~50 lines of `api_get_json`/`api_post_json` copy-pasted across 2 files
- **Bottleneck:** `select_and_launch.py` does 10+ distinct responsibilities in 530 lines

---

## Target Library Structure

```
vast_provisioning/
├── __init__.py                   # Public API surface
├── errors.py                     # ProvisioningError, PolicyViolation, ReadinessTimeout
├── profiles/
│   ├── __init__.py
│   ├── schema.py                 # Pydantic base models, validators
│   ├── model.py                  # ModelProfile (hf_model_id, r2_prefix, vllm config)
│   ├── gpu.py                    # GpuProfile (gpu_name, num_gpus, min_vram)
│   ├── launch.py                 # LaunchProfile + load_launch_context()
│   └── policy.py                 # OfferPolicy, GpuFilter, PricingFilter, etc.
├── template/
│   ├── __init__.py
│   ├── builder.py                # build_template(), env_from_specs(), deep_merge()
│   ├── safety.py                 # assert_public_safe(), SECRET_ENV_NAMES
│   └── manifest.py               # TemplateManifest, update_manifest()
├── offers/
│   ├── __init__.py
│   ├── search.py                 # Query builder for Vast search
│   ├── scoring.py                # effective_cost(), selection_sort_key()
│   └── machine.py                # is_preferred_machine(), is_greylisted_machine()
├── monitor/
│   ├── __init__.py
│   ├── signals.py                # Signals dataclass (already clean)
│   ├── analyzer.py               # analyze_logs() (already pure)
│   └── readiness.py              # poll_until_ready(), port_url()
├── vast/
│   ├── __init__.py
│   ├── client.py                 # Thin typed wrapper around VastAI SDK
│   └── template_ops.py           # apply_template(), update_kwargs()
└── lifecycle.py                  # launch_instance(), destroy_instance(), smoke_chat()
```

---

## What stays in the original repo

These are **not** library material — they stay as-is:

- `provision_vast_vllm_from_r2.sh` — runs on the Vast instance, not in Python
- `transfer_model_to_R2.sh` — shell script with awscli/rclone
- `onstart.vast-vllm-discovery.sh` — Vast onstart hook
- `run.sh` — local venv bootstrap
- `test.sh` — local test runner
- `config/` — user data (profiles, templates, private overlays)
- `state/`, `offers/`, `instances/` — runtime output

The original repo becomes a thin `cli/` layer calling the library.

---

## Key design decisions

### 1. Profiles → Pydantic models

```python
# Before: raw dict access, silent missing keys
model = json.loads(path.read_text())
served_name = model.get("served_model_name")  # could be None

# After: validated, typed, fail-fast
model = ModelProfile.model_validate_json(path.read_text())
served_name = model.served_model_name  # required field, validated at load
```

### 2. Template builder → pure functions

```python
# Before: mixed I/O + logic
payload, metadata = build_from_launch_profile(
    launch_profile_path=Path("..."),
    template_spec_path=Path("..."),
    private_overlay_path=Path("..."),
)

# After: I/O is the caller's responsibility
template_spec = TemplateSpec.model_validate_json(Path("...").read_text())
model_profile = ModelProfile.model_validate_json(Path("...").read_text())
rendered = build_template(template_spec, model_profile, private=True)
```

### 3. Offer policy → composable filter objects

```python
# Before: 15 hardcoded checks in a single function
ok, reasons = offer_passes_policy(offer, context)

# After: explicit policy with named filters
policy = OfferPolicy(
    gpu=GpuFilter(name="NVIDIA GeForce RTX 4090", min_vram_mb=24000),
    pricing=PricingFilter(max_dph=0.90),
    network=NetworkFilter(min_down_mbps=100),
    machine=MachineFilter(preferred=[123], greylisted=[789]),
)
passing = [offer for offer in offers if policy.check(offer)]
```

### 4. Monitor signals → lift as-is

`Signals` is already a frozen dataclass. `analyze_logs(logs, image)` is pure (string → Signals). These move with minimal change.

### 5. Vast SDK as optional dependency

```toml
[project.optional-dependencies]
vast = ["vastai>=1.0.9"]   # only needed for Vast client
dev = ["pytest", "ruff", "mypy"]
```

Profile parsing, template building, and log analysis work without `vastai` installed.

---

## Migration steps

Extract one domain at a time. Each step is independently mergeable and testable.

### Step 1: Profiles + schemas

**Files:** `profiles/schema.py`, `profiles/model.py`, `profiles/gpu.py`, `profiles/launch.py`

**What changes:**
- Add Pydantic models for each profile type
- `load_launch_context()` validates all three profiles at load time
- Missing/invalid config fields fail fast with clear error messages
- Satisfies the `todo.txt` pre-launch env guard (add env var checks as validators)

**Risk:** Low. Only changes config loading, not any business logic.

### Step 2: Template builder

**Files:** `template/builder.py`, `template/safety.py`, `template/manifest.py`

**What changes:**
- Extract `deep_merge()`, `env_from_specs()`, `build_template()`, `assert_public_safe()`
- Remove I/O from `build_from_launch_profile()` — caller reads files and passes models
- `update_manifest()` becomes a separate concern

**Risk:** Low. Pure functions, already well-tested.

### Step 3: Monitor signals + analyzer

**Files:** `monitor/signals.py`, `monitor/analyzer.py`, `monitor/readiness.py`

**What changes:**
- Move `Signals`, `analyze_logs()`, `port_url()` almost verbatim
- `poll_until_ready()` adds a clean high-level API

**Risk:** Very low. Already clean code.

### Step 4: Offer policy + scoring

**Files:** `profiles/policy.py`, `offers/search.py`, `offers/scoring.py`, `offers/machine.py`

**What changes:**
Replace the 15 hardcoded checks in `offer_passes_policy()` with composable filter objects. Extract `effective_cost()`, `selection_sort_key()`, `is_preferred_machine()`, `is_greylisted_machine()` into focused modules.

**Risk:** Medium. This touches the core launch decision logic. Needs thorough test migration.

- search_policy_offers() — the Vast query builder + policy filtering loop. Goes in offers/search.py but also handles CLI printing of each offer's PASS/FAIL. The query building goes in library, the printing stays in CLI.
- load_launch_context() — not in Step 1, it straddles Step 1 (profiles) and Step 4 (attaches policy). Should be in profiles/launch.py.
- instance_hourly_cost() — derives cost from existing instance dicts. Belongs in offers/scoring.py or a costing.py module.
- get_instances() / get_volumes() — thin Vast SDK calls. Go in vast/client.py.
- print_current_infra() / print_selected_offer() — display-only, stays in CLI.

The main gap: Step 4 also needs to extract the search query builder (turning GPU profile + storage + market into a Vast search string), which is ~30 lines of string formatting in search_policy_offers().

### Step 5: CLI thinning

**Files:** Rewrite each `scripts/*.py` as ~30-60 lines of argparse → library calls

**What changes:**
- `select_and_launch.py` drops from ~530 lines to ~60
- `smoke_chat_once.py` drops from ~150 lines to ~40
- `prepare_vast_template.py` drops from ~80 lines to ~30
- `apply_vast_template.py` drops from ~160 lines to ~50
- `monitor_instance_readiness.py` drops from ~260 lines to ~50

**Risk:** Medium-High. Most changes, but the library is already tested at this point.

---

## Estimated effort

| Step | Effort | Value |
|---|---|---|
| Profiles + schemas | 2-3h | High — fail-fast on bad config prevents wasted GPU hours |
| Template builder | 1-2h | Medium — enables reusability |
| Monitor signals | 1h | Low — mostly file moves |
| Offer policy | 3-4h | High — enables policy composition and testing |
| CLI thinning | 2-3h | Medium — cleanliness, no new functionality |
| **Total** | **9-13h** | |

---

## Dependencies

```toml
[project]
name = "vast-provisioning"
version = "0.1.0"
description = "Profile-driven Vast.ai instance provisioning"
requires-python = ">=3.10"

[project.optional-dependencies]
vast = ["vastai>=1.0.9"]
dev = ["pytest", "pytest-asyncio", "ruff", "mypy"]
```

---

## What this solves

| Problem | Before | After |
|---|---|---|
| Bad config silently fails | `.get()` returns None, crashes deep in launch | Pydantic validates at load, clear error message |
| Can't reuse logic in other tools | `sys.path.insert(0, ...)` hack | `pip install vast-provisioning` |
| Can't test policy in isolation | Policy is 15 checks inside a 530-line CLI | `Policy.check(offer)` is a pure function |
| Duplication across scripts | Copy-pasted HTTP helpers | Shared `vast.client` module |
| No pre-launch guard | Listed in `todo.txt` as open work | Env validators in profile schema |
| LLM can't reason about the code | 530-line monolith | 6 small focused modules
