# Handoff: add minimum rentable disk / storage-price checks to Vast launch policy

## Why this exists

The RTX 3090 llama.cpp/MTP session exposed a policy gap in our Vast launcher: GPU hourly price can look cheap while local disk rental makes the real hourly cost much higher.

On the Illinois RTX 3090 host we used for SSH/model work, the GPU portion was roughly:

```text
gpuCostPerHour: ~$0.173/hr
```

but storage was billed separately and was expensive at large disk sizes. For the 800GB instance we launched:

```text
storage/disk: ~$0.222/hr
total:        ~$0.396/hr
```

So storage cost more than the GPU. This was okay for a one-off model staging box, but our automated profile policy should catch or surface it before launch.

This doc is only about the launcher/policy gap. The llama.cpp MTP repro itself is already documented in:

```text
docs/llama-cpp-qwen36-mtp-rtx3090-howto.md
```

## Current launcher behavior

Relevant code path:

```text
scripts/select_and_launch.py
```

Current launch profiles have storage policy like:

```json
"storage": {
  "disk_gb": 100,
  "max_storage_cost_per_gb_hour": 0.0003,
  "max_storage_total_cost_per_hour": 0.03,
  "min_disk_bw": 500
}
```

But in `offer_passes_policy`, the code currently enforces:

```text
offer.disk_space >= storage.disk_gb
offer.storage_total_cost <= storage.max_storage_total_cost_per_hour
offer.disk_bw >= storage.min_disk_bw
```

It does **not** currently enforce:

```text
storage.max_storage_cost_per_gb_hour
```

Also, the search call passes:

```python
storage=storage_gb
```

so `storage_total_cost` reflects the requested disk size, not necessarily a host-level minimum rentable disk cost or a future larger ad-hoc disk request.

## Policy gap

We need to distinguish at least four things:

1. `disk_gb` requested by our profile
2. host free/available disk (`offer.disk_space`)
3. storage cost for the requested disk (`offer.storage_total_cost`)
4. host storage rate / minimum rentable disk behavior

The launcher currently treats `disk_gb` as the only desired disk size. That is fine for automated model-serving launches, but not enough for exploratory SSH boxes where we may intentionally rent 300GB–1000GB to stage multiple GGUFs.

## Proposed changes

### 1. Enforce per-GB storage cost already present in profiles

Add a check in `offer_passes_policy`:

```python
requested_disk_gb = float(storage["disk_gb"])
storage_total = float(offer.get("storage_total_cost") or math.inf)
storage_per_gb_hour = storage_total / requested_disk_gb if requested_disk_gb > 0 else math.inf

(storage_per_gb_hour <= float(storage["max_storage_cost_per_gb_hour"]), "storage_cost_per_gb_hour")
```

This makes the existing profile field real.

### 2. Print storage rate in offer table

In `search_policy_offers`, add display columns:

```text
storage_total=$.../hr
storage_per_gb=$.../GB-hr
requested_disk=<N>GB
```

This would have made the Illinois host's storage price obvious immediately.

### 3. Print GPU/storage cost split in selected offer

`print_selected_offer` already prints storage hourly and total hourly. Keep that, but add percentage/split:

```text
gpu hourly:        $X/hr
storage hourly:    $Y/hr
storage share:     YY% of total
```

Warn if storage is a large fraction of total, e.g.:

```text
WARN: storage is 56% of total hourly cost
```

### 4. Add profile support for exploratory storage sizes

For SSH/model-staging launches, add an explicit profile field rather than editing normal serving profiles:

```json
"storage": {
  "disk_gb": 800,
  "max_storage_cost_per_gb_hour": 0.00012,
  "max_storage_total_cost_per_hour": 0.10,
  "min_disk_bw": 1000,
  "warn_if_storage_fraction_gt": 0.35
}
```

The exact limits should be tuned, but the point is to separate:

```text
serving profile: 100GB-ish, cheap storage cap
staging profile: 300-1000GB, strict per-GB cap
```

### 5. Add minimum-rentable-disk probing/check-only helper

Vast offer results do not clearly expose a stable `min_rentable_disk_gb` field in our current launcher output. To discover host behavior, add a read-only helper that searches the same machine/offer class at several storage sizes:

```text
50GB, 100GB, 300GB, 500GB, 800GB, 1000GB
```

For each tier print:

```text
offer_id
machine_id
dph_total
storage_total_cost
storage_per_gb_hour
whether the offer appears at that storage size
```

This makes host storage behavior visible before launch. It also lets us see whether a host disappears below a minimum disk request or just charges linearly.

Possible command shape:

```bash
./run.sh scripts/check_storage_tiers.py \
  --gpu-name "RTX 3090" \
  --num-gpus 1 \
  --machine-id <optional> \
  --market on-demand \
  --tiers 50,100,300,500,800,1000
```

Keep this read-only.

## Suggested implementation steps

1. Update `scripts/select_and_launch.py`:
   - compute `storage_per_gb_hour`
   - enforce `max_storage_cost_per_gb_hour`
   - add failure reason `storage_cost_per_gb_hour`
   - print storage per GB in offer table
   - warn when storage fraction is high

2. Add a small read-only script:

```text
scripts/check_storage_tiers.py
```

3. Add a local/staging launch profile template if needed, e.g. ignored under `state/launch-profiles/` for ad-hoc SSH boxes.

4. Run check-only examples against RTX 3090 offers:

```bash
. env.vast-management
./run.sh scripts/select_and_launch.py \
  --launch-profile <profile> \
  --check-only \
  --skip-current-infra \
  --top 10
```

5. Verify that existing profiles still pass for normal 100GB serving cases.

## Acceptance criteria

A future launcher run should make these obvious before launch:

```text
GPU hourly cost
storage hourly cost
storage cost per GB-hour
storage share of total cost
requested disk size
```

A host should fail policy if either is true:

```text
storage_total_cost > max_storage_total_cost_per_hour
storage_total_cost / requested_disk_gb > max_storage_cost_per_gb_hour
```

For exploratory large-disk runs, the operator should have a read-only way to compare storage tiers before renting.

## Notes from the 3090 session

The Illinois RTX 3090 host was useful because it had fast disk/network and enough local space for GGUF staging, but it was not storage-cheap. Large-disk model staging should not reuse normal model-serving storage thresholds silently.

The key lesson: **cheap GPU offers are not necessarily cheap instances once disk is included**.
