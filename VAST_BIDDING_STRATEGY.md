# Vast.ai bidding strategy notes

## Current observation

During the 2026-05-05 smoke-test session, interruptible instances were repeatedly outbid or became unavailable within roughly 15 minutes. Interruptible pricing was useful for fast experiments, but it was not stable enough for completing multi-step validation reliably.

## Current price snapshot

A current SDK search with our broad 1-GPU, verified, CUDA >= 13, >=21 GB VRAM criteria showed these rough lowest prices for 40 GB disk:

| Market | Example GPU | Low observed total $/hr | Notes |
|---|---:|---:|---|
| Interruptible | RTX 3090 | ~$0.087-$0.16/hr | Cheapest, but repeatedly interrupted/outbid. |
| Interruptible | RTX 4090/L40S/5090 | ~$0.27-$0.34/hr | Good for smoke tests when host is fast. Still interruptible. |
| On-demand | RTX 3090 | ~$0.16-$0.27/hr | Often overlaps high-quality interruptible pricing. Much more stable. |
| On-demand | RTX 4090 / L40-class | ~$0.30-$0.40+/hr | More suitable for demos/longer runs. |

Important: individual offers move constantly. Treat these as session-level guidance, not fixed rates.

## Market types and risk

### Interruptible

Interruptible is cheapest, but the host can reclaim/outbid the instance. Raising the bid cap helps only if the market-clearing price is the cause. It does not protect against host-side interruptions, owner actions, or capacity churn.

Use interruptible when the job can tolerate automatic relaunch and the useful work starts quickly.

### On-demand

On-demand costs more but avoids bid-based interruption. It is the practical baseline for "do not interrupt me" operation.

Use on-demand for:

- user-facing demos;
- long validations;
- any run where relaunching loses more time/money than the on-demand premium.

### Reserved / long-duration arrangements

Vast also has longer-duration/reservation-style economics depending on host/offer availability. Treat these as a stability tool only after we know a machine/template/model path is good. Do not reserve an unproven machine.

Reserved capacity makes sense when:

- the machine ID is already preferred/known-good;
- expected use is hours/days, not minutes;
- avoiding outbid/relaunch churn is worth the commitment.

## The real cost of interruption

The cheapest hourly price is not necessarily cheapest per successful request. Cold start has a fixed time cost:

```text
T_launch = image/startup + provisioning + R2 sync + vLLM load
```

For successful recent runs, R2 sync could complete quickly, but full readiness still cost several minutes. If an interruptible instance dies before or shortly after readiness, the effective cost of useful work increases sharply.

Approximate effective cost per useful hour:

```text
effective_cost = hourly_price / useful_fraction
useful_fraction = useful_runtime / (launch_time + useful_runtime)
```

Example with 5 minutes launch time:

| Useful runtime before interruption | Useful fraction | $0.17/hr interruptible effective | $0.34/hr on-demand equivalent |
|---:|---:|---:|---:|
| 5 min | 50% | $0.34/useful-hr | equal |
| 10 min | 67% | $0.25/useful-hr | cheaper |
| 15 min | 75% | $0.23/useful-hr | cheaper |
| 30 min | 86% | $0.20/useful-hr | much cheaper |

If we get outbid every ~15 minutes and launch takes ~5 minutes, interruptible at half the on-demand price can still be worthwhile. If launch takes 10+ minutes or interruption happens before validation, on-demand wins.

## Percentage-of-time launch budget

Use launch percentage to decide how much interruption risk is acceptable:

```text
launch_percentage = launch_time / (launch_time + expected_useful_runtime)
```

Target bands:

| Launch percentage | Interpretation | Strategy |
|---:|---|---|
| <10% | Good | Interruptible likely worthwhile. |
| 10-25% | Acceptable | Use interruptible only on preferred machines/high bid. |
| 25-50% | Risky | Consider on-demand or reserved if validation matters. |
| >50% | Bad | Interruptible churn dominates; use on-demand. |

Examples:

| Launch time | Useful runtime | Launch % |
|---:|---:|---:|
| 3 min | 30 min | 9% |
| 5 min | 15 min | 25% |
| 5 min | 10 min | 33% |
| 8 min | 15 min | 35% |
| 10 min | 10 min | 50% |

Operational rule: if recent interruption history says we only get ~15 minutes, we should require launch-to-ready under ~5 minutes to justify interruptible. If launch-to-ready exceeds that, switch to on-demand or reserved.

## Current policy posture

The launcher currently uses:

```json
"market": "interruptible",
"spot": {
  "max_bid_dph": 1.0
}
```

This keeps spend bounded, but does not guarantee runtime. The bid can be high while still losing if the host owner or market clears above our bid.

## Strategy for avoiding interruptions while still saving money

The goal is not "always use interruptible"; the goal is "pay less than on-demand when interruption risk is low enough."

Recommended strategy:

1. **Discovery phase: interruptible, strict monitor, auto-destroy.**
   - Use interruptible to classify machines cheaply.
   - Auto-destroy slow image pull, bad R2 path, missing env, or vLLM startup failures.
   - Record machine outcome.

2. **Validation phase: preferred machine + high interruptible bid.**
   - Use only `preferred_machine_ids` when possible.
   - Bid up to near comparable on-demand, e.g. `$1.0-$1.5/hr`, only for a short validation window.
   - This can still be cheaper than repeated failed launches.

3. **Stable phase: on-demand if interruption cost exceeds savings.**
   - If a run must last longer than the expected interruptible lifetime, use on-demand.
   - If three interruptible launches die before useful work, use on-demand for the next validation.

4. **Reserved phase: reserve only proven machines.**
   - After a machine is known-good and needed for hours/days, consider reserved/longer-duration options.

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
- Anything requiring more than ~10-15 minutes uninterrupted unless willing to relaunch.

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

Only use with explicit approval and cost display. This can be reasonable even near on-demand range because the intent is to avoid losing launch time repeatedly.

### Tier 3: on-demand for stability

Use on-demand once the template and model path are known-good, especially for demos or longer runs.

Switch:

```json
"market": "on-demand"
```

and do not send a bid price. This is more expensive per wall-clock hour but can be cheaper per useful hour when interruption churn is high.

## Practical launch rule

For future sessions:

1. Use interruptible + `max_bid_dph=1.0` for early probes.
2. If a machine passes R2 and vLLM readiness, immediately add its `machine_id` to `preferred_machine_ids`.
3. If three launches in a row are outbid before validation, switch one run to either:
   - high-bid interruptible (`1.5`), or
   - on-demand.
4. For any user-facing test, prefer on-demand over repeated interruptible relaunches.
5. If launch time is >25% of expected useful runtime, use high-bid/on-demand instead of cheap interruptible.

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
- Track launch-time percentage and warn when interruption risk makes interruptible uneconomic.
