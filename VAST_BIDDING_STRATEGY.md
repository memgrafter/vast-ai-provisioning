# Vast.ai bidding strategy notes

## Current observation

During the 2026-05-05 smoke-test session, interruptible instances were repeatedly outbid or became unavailable within roughly 15 minutes. Interruptible pricing was useful for fast experiments, but it was not stable enough for completing multi-step validation reliably.

## Current policy posture

The launcher currently uses:

```json
"market": "interruptible",
"spot": {
  "max_bid_dph": 1.0
}
```

This keeps spend bounded, but does not guarantee runtime. The bid can be high while still losing if the host owner or market clears above our bid.

## When interruptible makes sense

Use interruptible for:

- Docker image cache discovery.
- R2 path speed tests.
- Template/provisioning smoke checks.
- Short API validation after vLLM is already known to start.
- Building preferred/greylisted machine IDs.

Do not rely on interruptible for:

- Long evaluations.
- User-facing demos.
- Anything requiring more than ~10 minutes uninterrupted unless willing to relaunch.

## Preferred-machine strategy

Maintain two policy lists:

```json
"preferred_machine_ids": [],
"greylisted_machine_ids": []
```

Prefer machines that have proven:

- Fast/cached Docker startup.
- Successful R2 speed test.
- Completed model sync.
- vLLM reached `/health` and `/v1/models`.
- Stable enough to run chat completions.

Greylist machines that show:

- Slow/no Docker image progress before provisioning.
- Bad R2 speed after optimized parallel/rclone path.
- Repeated credential/env injection failures.
- Repeated vLLM startup failures unrelated to our config.
- Outbid before provisioning repeatedly.

Current known-good preferred machines include:

- `1569` — RTX 5090, successful R2 sync and authenticated chat completions.
- `68063` — L40S, successful R2 speed/sync and vLLM API startup; later stopped/outbid.

## Bid tiers

Suggested operating tiers:

### Tier 0: cheapest interruptible discovery

Use for initial host search and failure classification.

```json
"max_bid_dph": 0.65
```

Expected behavior: many outbids; acceptable only for short probes.

### Tier 1: smoke-test interruptible

Current default:

```json
"max_bid_dph": 1.0
```

Use when testing full launch path. Still expect outbids within minutes on popular machines.

### Tier 2: high-bid interruptible for one complete validation

Use when we need one uninterrupted validation but still want interruptible economics:

```json
"max_bid_dph": 1.5
```

Only use with explicit approval and cost display.

### Tier 3: on-demand for stability

Use on-demand once the template and model path are known-good, especially for demos or longer runs.

Switch:

```json
"market": "on-demand"
```

and do not send a bid price. This is more expensive but avoids interruptible outbid churn.

## Practical launch rule

For future sessions:

1. Use interruptible + `max_bid_dph=1.0` for early probes.
2. If a machine passes R2 and vLLM readiness, immediately add its `machine_id` to `preferred_machine_ids`.
3. If three launches in a row are outbid before validation, switch one run to either:
   - high-bid interruptible (`1.5`), or
   - on-demand.
4. For any user-facing test, prefer on-demand over repeated interruptible relaunches.

## Cost guardrails

The launcher should continue printing:

- Existing instances and known hourly burn.
- Selected offer base/storage/total hourly cost.
- Per-minute and 10-minute smoke-test estimates.
- Network egress costs.
- Bid cap or on-demand market.

Keep explicit `y/N` approval before launch.

## Automation improvements

Potential improvements:

- Auto-greylist machines outbid before provisioning more than once.
- Record outcome per machine in a small local ignored state file.
- Prefer previously successful machines even if their effective cost is slightly higher.
- Add a `--stable` launcher mode that switches to on-demand or higher interruptible bid.
- Add max total active burn guard before launch.
