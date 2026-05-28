# Model Profiles as Workload Profiles

Date: 2026-05-25

## Conclusion

The existing profile system already has enough structure to represent production workload types without changing the launcher decision process. In practice, `config/models/*.json` model profiles are also workload profiles.

A model profile owns not just the model identity, but the runtime shape:

```text
model repo / R2 prefix
served model name
context length
KV cache dtype
quantization/runtime kernel choice
MTP/speculative decoding settings
scheduler limits
expected model download size
provisioning tolerance
```

That is enough to encode whether a run is a strict interactive smoke, a cheap evening burn-in, an overnight benchmark, or a production agent backend.

## Separation of concerns

### Model profile = workload/runtime policy

Use model profiles for settings that answer:

```text
What is being run?
How much context does it need?
How should vLLM be configured?
How long can startup take?
How much R2/model-transfer pain is acceptable?
```

Examples:

```json
"provisioning": {
  "r2_speed_test_warn_only": true,
  "r2_speed_test_min_mbps": 16
}
```

or strict:

```json
"provisioning": {
  "r2_speed_test_warn_only": false,
  "r2_speed_test_min_mbps": 100
}
```

Notes:

```text
r2_speed_test_min_mbps is currently MB/s, despite the name.
16 MB/s ~= 128 Mbps consumer-class floor.
100 MB/s ~= 800 Mbps strict/datacenter-class floor.
```

### Launch profile = infrastructure/market policy

Use launch profiles for settings that answer:

```text
Where can it run?
How much can it cost?
Which market type?
Which GPU class/count?
What reliability/network floor?
Which machines are preferred or greylisted?
Which remote Vast template identity?
```

Examples:

```text
gpu_profile
market
max_dph_total
min_reliability2
min_inet_down
preferred_machine_ids
greylisted_machine_ids
template.hash_id
```

## Workload archetypes

### interactive-smoke

```text
Goal: prove startup/API quickly.
R2 policy: strict fail-hard.
Rental duration: short.
Cold-start tolerance: low.
```

Suggested provisioning:

```json
{"r2_speed_test_warn_only": false, "r2_speed_test_min_mbps": 100}
```

### cheap-evening-burnin

```text
Goal: keep a cheap rare GPU for hours.
R2 policy: relaxed or warn-only.
Rental duration: medium/long.
Cold-start tolerance: high.
```

Suggested provisioning:

```json
{"r2_speed_test_warn_only": true, "r2_speed_test_min_mbps": 16}
```

### production-agent

```text
Goal: stable interactive coding-agent backend.
R2 policy: strict.
Rental duration: long.
Cold-start tolerance: low/medium.
Latency requirement: high.
```

Suggested provisioning:

```json
{"r2_speed_test_warn_only": false, "r2_speed_test_min_mbps": 100}
```

### overnight-benchmark

```text
Goal: long benchmark or context-fill test.
R2 policy: relaxed, especially when model download is small versus rental length.
Rental duration: long.
Cold-start tolerance: high.
```

Suggested provisioning:

```json
{"r2_speed_test_warn_only": true, "r2_speed_test_min_mbps": 16}
```

## Practical naming pattern

Prefer explicit profile names over hidden decision logic:

```text
carnice-v2-27b-nvfp4-text-mtp.pro6000ws-256k-strict.json
carnice-v2-27b-nvfp4-text-mtp.pro6000ws-256k-evening.json
carnice-v2-27b-nvfp4-text-mtp.rtx5090-160k-smoke.json
carnice-v2-27b-nvfp4-text-mtp.consumer-64k-warnonly.json
```

Then launch profiles can stay simple and point at the desired workload profile.

## Recommendation

Do not add a new decision layer yet. Continue using:

```text
model profile = workload/runtime intent
launch profile = infrastructure/market constraints
gpu profile = GPU compatibility filter
```

Add workload-specific model profiles when R2 tolerance, context length, scheduler limits, or MTP settings differ materially.
