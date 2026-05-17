# Handoff: launch ledger, metrics capture, and burn-in reports

Date: 2026-05-16

This handoff is a standalone summary of the metrics/ledger/burn-in work added during the B200 testing session.

## What changed

The repo now has a local SQLite launch ledger and publish-safe report generator.

Core files:

```text
docs/launch-ledger-schema.sql
scripts/launch_ledger.py
scripts/reconcile_launch_ledger.py
scripts/report_launch_metrics.py
scripts/summarize_vllm_metrics.py
scripts/clean_terminate_instance.py
scripts/select_and_launch.py
scripts/monitor_instance_readiness.py
scripts/coding_agent_saturation_ramp.py
```

Committed changes of interest:

```text
8ec2448 feat(metrics): add launch ledger and report generator
451decc feat(bench): make saturation ramp self-reporting
6ebf6b7 docs(metrics): add B200 burn-in reports
```

Another agent also committed related docs in:

```text
9e420c0 feat(launch): add launch ledger and storage cost tracking
a07169b docs(vast): document storage policy and llama MTP workflows
```

## Ledger location and schema

The local analytics DB is:

```text
state/launches.sqlite3
```

`state/` is gitignored. The DB is intentionally local analytics state, not application-driving state.

Schema file:

```text
docs/launch-ledger-schema.sql
```

Tables:

```text
launches
launch_events
launch_metric_samples
```

### `launches`

One row per launched Vast instance. Key:

```text
launch_key = vast:instance:<instance_id>
```

Stores launch/profile/cost/storage/readiness summary. Avoids secrets. Stores local artifact paths only in ignored paths.

### `launch_events`

First-seen timeline events:

```text
launch_requested
sdk_create_returned
instance_running
image_pull_seen
image_cached
provisioning_started
r2_sync_started
r2_transfer_active
r2_sync_finished
provisioning_complete
vllm_started
api_ready
smoke_passed / smoke_failed
burnin_started
burnin_step_started_c<N>
burnin_step_finished_c<N>
burnin_endpoint_changed
burnin_finished
```

### `launch_metric_samples`

Generic metric samples:

```text
launch_key
sampled_at
source
metric_name
metric_value
labels_json
details_json
```

Sources currently include:

```text
vast_reconcile
vllm_metrics
vllm_metrics_interval
burnin_step
```

## SQLite connection behavior

All writers should go through:

```python
launch_ledger.init_db(...)
```

All read-only ledger opens should go through:

```python
launch_ledger.open_readonly_db(...)
```

The helper configures SQLite for CLI concurrency:

```sql
PRAGMA busy_timeout = 30000;
PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;
```

Read-only opens use:

```sql
PRAGMA query_only = ON;
```

Do not add raw `sqlite3.connect(...)` calls elsewhere unless they use the same helper behavior.

## Launch workflow integration

`scripts/select_and_launch.py` now writes ledger rows after actual launches:

1. after `vast.create_instance(...)`: insert launch row
2. after polling instance: update status/running info
3. after monitor: update monitor result / destroyed status
4. after smoke: record smoke exit code

`--check-only` remains read-only and does not create launch rows.

Known bug fixed:

- `poll_instance()` no longer treats immediate `unknown` as terminal. Vast can briefly return unknown after `create_instance`; now polling continues unless status is `exited` or `offline`.

## Reconcile

Script:

```text
scripts/reconcile_launch_ledger.py
```

Default is dry-run only:

```bash
. env.vast-management
./run.sh scripts/reconcile_launch_ledger.py
```

To update local ledger metrics/status from current Vast API state:

```bash
. env.vast-management
./run.sh scripts/reconcile_launch_ledger.py --write
```

It only uses read-only Vast SDK calls. It does not mutate/destroy instances.

Captured Vast-side sample metrics include:

```text
vast.dph_total
vast.cur_state_dph
vast.storage_total_cost_per_hour
vast.duration_seconds
vast.gpu_utilization_percent
vast.gpu_memory_used_mb
vast.disk_usage_gb
```

These depend on fields returned by Vast.

## vLLM metrics capture

Script:

```text
scripts/summarize_vllm_metrics.py
```

It still prints human summaries, and now can record selected metrics into the ledger.

Point-in-time scrape:

```bash
./run.sh scripts/summarize_vllm_metrics.py \
  --base-url http://<host>:<port>/v1 \
  --instance-id <INSTANCE_ID> \
  --record-ledger
```

Interval/rate scrape:

```bash
./run.sh scripts/summarize_vllm_metrics.py \
  --base-url http://<host>:<port>/v1 \
  --interval 10 \
  --instance-id <INSTANCE_ID> \
  --record-ledger
```

Repeat loop:

```bash
./run.sh scripts/summarize_vllm_metrics.py \
  --base-url http://<host>:<port>/v1 \
  --interval 10 \
  --repeat \
  --instance-id <INSTANCE_ID> \
  --record-ledger
```

Metrics recorded include:

```text
vllm.requests_running
vllm.requests_waiting
vllm.kv_cache_usage_percent
vllm.prompt_tokens_total
vllm.generation_tokens_total
vllm.prompt_tokens_delta
vllm.generation_tokens_delta
vllm.total_tokens_delta
vllm.prompt_tokens_per_second
vllm.generation_tokens_per_second
vllm.total_tokens_per_second
vllm.request_success_stop_total
vllm.request_success_length_total
vllm.request_success_error_total
vllm.request_success_abort_total
vllm.ttft_count
vllm.ttft_sum_seconds
vllm.queue_count
vllm.queue_sum_seconds
vllm.inference_count
vllm.inference_sum_seconds
```

Important lesson from the session: an external collector pinned to a Vast mapped port is fragile because Vast remaps ports after restarts/recycles. For production burn-ins, use the saturation ramp with `--instance-id` instead.

## Saturation ramp / burn-in

Script:

```text
scripts/coding_agent_saturation_ramp.py
```

Old fixed `--base-url` mode has been removed. Use `--instance-id` only so the script derives the current Vast mapped port on demand.

Example:

```bash
. env.vast-management
OPENAI_API_KEY="$VLLM_API_KEY" ./run.sh scripts/coding_agent_saturation_ramp.py \
  --instance-id <INSTANCE_ID> \
  --model carnice-v2-27b-nvfp4-text-mtp-b200-maxctx-mtp3 \
  --concurrency 96 \
  --requests-per-concurrency 4 \
  --warmup-turns 1 \
  --warmup-max-tokens 1 \
  --max-tokens 20000 \
  --shared-prefix \
  --fixed-prefix-tokens 30000 \
  --post-warmup-gap 2 \
  --max-model-len 262144 \
  --timeout 7200 \
  --step-gap 0
```

Defaults now are intended to be sane:

```text
ledger recording: on
request JSONL: on
end-of-run Markdown report: on
container port: 8000/tcp
metrics sample interval: 2s
```

Opt out explicitly:

```text
--no-record-ledger
--no-request-log
--no-report
```

Default request log path:

```text
state/burnin/<instance_id>-<timestamp>-coding-agent-saturation.requests.jsonl
```

Default report path:

```text
docs/reports/<model-slug>-<concurrency-list>way-burnin-<timestamp>.md
```

The ramp records:

```text
burnin_started
burnin_step_started_c<N>
burnin_step_finished_c<N>
burnin_endpoint_changed
burnin_finished
```

and step summary metrics with `burnin.*` metric names.

## Clean terminate / closeout

Script:

```text
scripts/clean_terminate_instance.py
```

Preferred closeout path for benchmark rentals:

```bash
. env.vast-management
./run.sh scripts/clean_terminate_instance.py \
  --instance-id <INSTANCE_ID> \
  --metrics-interval 10 \
  --yes
```

What it does, in order:

1. saves a pre-destroy `show_instance` snapshot under ignored `state/terminate/`
2. saves a Vast log tail under ignored `state/terminate/`
3. captures final cumulative vLLM metrics into the ledger
4. optionally captures a final interval TPS window with `--metrics-interval`
5. calls Vast destroy only when `--yes` is provided
6. attempts a post-destroy snapshot/error capture
7. marks the ledger row `destroyed`

Safe capture-only mode:

```bash
./run.sh scripts/clean_terminate_instance.py \
  --instance-id <INSTANCE_ID> \
  --metrics-interval 10 \
  --dry-run
```

Use `--require-metrics` when the instance should not be destroyed unless the final vLLM metrics scrape succeeds.

## Report generator

Script:

```text
scripts/report_launch_metrics.py
```

Generates publish-safe Markdown from the ledger.

Example:

```bash
scripts/report_launch_metrics.py \
  --instance-id <INSTANCE_ID> \
  --since 2026-05-16T07:32:41Z \
  --until 2026-05-16T07:46:43Z \
  --workload-model carnice-v2-27b-nvfp4-text-mtp-b200-maxctx-mtp3 \
  --report-title '# B200 Burn-in Metrics Report: Carnice v2 27B NVFP4 Text MTP, 96-way long generation' \
  --workload-config-json '{"configured concurrency":96,"measured requests per simulated user":4,"warmup turns":1,"warmup max tokens":1,"measured max tokens":20000,"shared prefix":true,"fixed prefix tokens":30000,"max model length":262144,"workload shape":"long generation"}' \
  --out docs/reports/example.md
```

Publish-safe defaults:

- provider IDs redacted
- no public IPs
- no mapped ports
- no URLs
- no auth/API key strings
- no local artifact paths
- no raw `details_json`

Optional non-publish mode:

```text
--include-provider-ids
```

Report contents:

```text
launch metadata
cost/storage snapshot
workload configuration if supplied
sample coverage
prompt/generation/total TPS
TPS per active request
running/waiting/KV gauges
counter deltas
TTFT/inference/queue averages
latest active windows
```

## Reports generated during this session

Generated and committed:

```text
docs/b200-carnice-v2-27b-nvfp4-24way-long-generation-burnin-2026-05-16.md
docs/b200-carnice-v2-27b-nvfp4-64way-long-generation-burnin-2026-05-16.md
docs/b200-carnice-v2-27b-nvfp4-96way-long-generation-burnin-2026-05-16.md
docs/b200-carnice-v2-27b-nvfp4-128way-long-generation-burnin-2026-05-16.md
docs/b200-carnice-v2-27b-nvfp4-128way-long-generation-partial-burnin-2026-05-16.md
```

The 24/64/96/128 reports were generated from DB time windows and then given workload config based on session command history. Future runs should not need this manual step if started with the new `--instance-id` defaults.

## B200 run windows found in the DB

Observed active clusters for the B200 test instance during the session. The provider instance ID is intentionally redacted in this public handoff. To recover the local launch key from the ignored ledger tomorrow:

```bash
sqlite3 state/launches.sqlite3 \
  "select launch_key, launch_profile_name, gpu_name, created_at from launches where gpu_name like '%B200%' order by created_at desc;"
```

Run windows:

```text
24-way:  2026-05-16T06:42:32Z -> 2026-05-16T06:49:20Z
64-way:  2026-05-16T06:54:53Z -> 2026-05-16T07:05:26Z
128-way: 2026-05-16T07:07:42Z -> 2026-05-16T07:26:36Z
96-way:  2026-05-16T07:32:41Z -> 2026-05-16T07:46:43Z
```

Workload config used for those long-generation reports:

```text
requests-per-concurrency: 4
warmup-turns: 1
warmup-max-tokens: 1
max-tokens: 20000
shared-prefix: true
fixed-prefix-tokens: 30000
max-model-len: 262144
```

## Gotchas / next improvements

1. The committed report files live directly under `docs/`. New auto-generated reports default to `docs/reports/`. Consider moving historical reports there later if desired.
2. `launches.lifecycle_status` for the B200 row was stale as `unknown` because it was launched before the polling fix. Use reconcile to update local status if needed:

```bash
. env.vast-management
./run.sh scripts/reconcile_launch_ledger.py --write
```

3. Prefer `scripts/clean_terminate_instance.py --yes` over ad-hoc `vast.destroy_instance(...)` so final metrics/logs are preserved before the rental is released.
4. Request JSONL is intentionally under ignored `state/burnin/`; publish summaries via Markdown reports only.
5. Do not commit `state/launches.sqlite3`; it is local analytics state.
6. If adding more scripts that touch SQLite, use `scripts.launch_ledger` connection helpers so WAL/busy timeout behavior stays consistent.

## Verification commands

Syntax checks used:

```bash
python -m py_compile \
  scripts/launch_ledger.py \
  scripts/reconcile_launch_ledger.py \
  scripts/report_launch_metrics.py \
  scripts/clean_terminate_instance.py \
  scripts/select_and_launch.py \
  scripts/monitor_instance_readiness.py \
  scripts/summarize_vllm_metrics.py \
  scripts/coding_agent_saturation_ramp.py
```

Publish-safety grep used for docs:

```bash
rg -n "([0-9]{1,3}\\.){3}[0-9]{1,3}|ssh[0-9]+\\.vast\\.ai|http://[^<]|https://[^<]|/Users/|Bearer|Authorization|api[_-]?key|secret|ssh-ed25519|BEGIN .*PRIVATE|root@|public_ip|HostPort|details_json" docs/<report>.md
```

Expected: no sensitive hits. Some non-sensitive words such as `tokens` may match broad patterns if the regex is too broad.
