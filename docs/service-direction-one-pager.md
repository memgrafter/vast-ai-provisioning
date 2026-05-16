# Service direction, without converting yet

## Position

Keep the current workflow as CLI scripts for now, but structure new work as if the scripts are thin command wrappers around service-ready domain modules.

Do **not** introduce a web service yet. The next production step is durable launch accountability through the SQLite launch ledger, plus clearer module boundaries.

## Why

The project is still in active exploration mode: Vast offer behavior, storage costs, model profiles, and readiness checks are changing quickly. A service would add operational surface area before the core domain is stable.

But the code already has service-shaped responsibilities:

- load profiles
- search offers
- evaluate policy
- select an offer
- request launch
- monitor readiness
- destroy failed instances
- record costs and outcomes

If these are kept as script-local logic, later service conversion will be expensive. If we extract them now behind clean functions/modules, the eventual service can be thin.

## Near-term architecture

Keep CLIs:

```text
scripts/select_and_launch.py
scripts/monitor_instance_readiness.py
```

Extract reusable modules over time:

```text
scripts/profiles.py          # load/validate launch/model/gpu/template profiles
scripts/pricing_policy.py    # offer pass/fail, reasons, effective cost, storage metrics
scripts/vast_client.py       # narrow Vast SDK wrapper, normalized response helpers
scripts/launch_ledger.py     # sqlite schema init + insert/update analytics records
scripts/provision_monitor.py # log signal extraction and readiness state
```

The CLIs should orchestrate these modules, not own business logic permanently.

## Service-shaped API later

If/when this becomes a service, the natural API is:

```text
POST /launch-plans          # read-only offer search + policy evaluation
POST /launches              # create instance from an approved plan
GET  /launches/:id          # status, cost, readiness, profile metadata
POST /launches/:id/monitor  # start/update monitor workflow
POST /launches/:id/destroy  # guarded destroy
GET  /analytics/launches    # query ledger records
```

The service should not invent new domain concepts. It should expose the same canonical objects the scripts already use.

## Canonical identifiers

Use stable string keys wherever possible:

```text
provider = vast
launch_key = vast:instance:<instance_id>
launch_profile_name
model_profile_name
gpu_profile_name
template_hash_id
served_model_name
machine_id
offer_id
```

The launch ledger should use these as analytics join keys. It should not drive launch selection.

## Side-effect boundaries

Every side effect should be explicit and isolated:

```text
search offers        read-only Vast call
create instance      mutating Vast call
attach/provision     mutating Vast/template behavior
destroy instance     mutating Vast call
write snapshots      local ignored files
write ledger         local ignored sqlite analytics DB
run smoke test       external HTTP request
```

No function that claims to evaluate policy should launch, destroy, or write state.

## Immediate production steps

1. Add the SQLite launch ledger from:

```text
docs/launch-ledger-schema.sql
```

2. Wire first write points:

```text
after create_instance: insert launch row
after poll_instance: update status + instance snapshot path
after monitor: update readiness/destroy result
```

3. Keep `--check-only` strictly read-only. It may print policy/cost details but should not write launch rows.

4. Move storage/cost policy logic toward a pure module once the ledger is wired.

## Non-goals for now

- No daemon/web service yet.
- No scheduler yet.
- No launch selection driven by SQLite.
- No secrets in ledger.
- No raw large logs embedded in SQLite; store local file paths instead.

## Rule of thumb

Build scripts today so that a future service is mostly:

```text
HTTP/API layer + auth + job orchestration
```

not a rewrite of launch policy, profile loading, monitoring, and cost accounting.
