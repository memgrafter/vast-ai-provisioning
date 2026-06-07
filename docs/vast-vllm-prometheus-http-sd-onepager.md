# Vast vLLM Prometheus integration one-pager

## Goal

Get live vLLM metrics from ever-changing Vast.ai instances into the local k3s Prometheus stack without manually editing scrape targets each time Vast remaps host ports or instances are replaced.

Local monitoring stack currently lives in `~/code/k3s_maintenance`:

```text
Prometheus: http://192.168.1.207:9090
Chart: kube-prometheus-stack
Config: monitoring-values.yaml
```

This repo already has read-only Vast/vLLM helpers:

```text
scripts/list_active_vllm_endpoints.py
scripts/summarize_vllm_metrics.py
scripts/archive_prometheus_metrics.py
```

## Recommendation

Use **Prometheus HTTP service discovery** backed by a small read-only Vast discovery service.

```text
Prometheus
  -> http_sd_configs
  -> vast-vllm-discovery service
  -> Vast show_instances_v1 read API
  -> current public vLLM /metrics host:port targets
  -> Prometheus scrapes Vast instances directly
```

Do **not** use Pushgateway for the main live metrics path. Pushgateway is better for one-shot summaries; live vLLM counters/histograms should be scraped directly so target lifecycle, staleness, rates, and labels behave naturally.

## Read-only discovery mode

Add a script such as:

```text
scripts/vast_vllm_prometheus_sd.py
```

Proposed modes:

```bash
# Print Prometheus HTTP SD JSON; no writes.
./run.sh scripts/vast_vllm_prometheus_sd.py --once --format http-sd

# Also probe GET /metrics and include health labels; still read-only.
./run.sh scripts/vast_vllm_prometheus_sd.py --once --probe

# Serve HTTP SD for Prometheus.
./run.sh scripts/vast_vllm_prometheus_sd.py --serve --listen 0.0.0.0:9808
```

Read-only guarantees:

- Only calls Vast read APIs.
- Optional probe only performs HTTP `GET /metrics`.
- Does not launch, stop, destroy, or mutate Vast instances.
- Does not write Kubernetes resources.
- Does not push metrics.
- Does not print secrets.

Example HTTP SD output:

```json
[
  {
    "targets": ["1.34.114.64:14496"],
    "labels": {
      "job": "vast-vllm",
      "vast_instance_id": "39549994",
      "vast_machine_id": "112243",
      "vast_gpu": "RTX PRO 6000 WS",
      "served_model": "qwen3.6-27b-awq-bf16-int4-pro6000ws-performance-256k-mtp2",
      "container_port": "8000/tcp"
    }
  }
]
```

## Prometheus config shape

After validating the read-only service locally, add a scrape job to `~/code/k3s_maintenance/monitoring-values.yaml`:

```yaml
prometheus:
  prometheusSpec:
    additionalScrapeConfigs:
    - job_name: vast-vllm
      scrape_interval: 10s
      scrape_timeout: 5s
      http_sd_configs:
      - url: http://vast-vllm-discovery.monitoring.svc.cluster.local:9808/targets
        refresh_interval: 30s
      metric_relabel_configs:
      - source_labels: [__name__]
        regex: 'vllm:.*'
        action: keep
```

The metric relabel keeps storage focused on vLLM metrics instead of Python GC/process noise.

If `/metrics` auth becomes required later, add a Prometheus bearer token secret and `authorization` block. Current checked endpoint allowed unauthenticated `/metrics`, so auth is not required for the first pass.

## Useful Grafana/PromQL panels

Generation TPS:

```promql
sum by (vast_instance_id, served_model) (
  rate(vllm:generation_tokens_total{job="vast-vllm"}[1m])
)
```

Prompt TPS by source:

```promql
sum by (vast_instance_id, served_model, source) (
  rate(vllm:prompt_tokens_by_source_total{job="vast-vllm"}[1m])
)
```

Scheduler state:

```promql
vllm:num_requests_running{job="vast-vllm"}
vllm:num_requests_waiting{job="vast-vllm"}
vllm:kv_cache_usage_perc{job="vast-vllm"} * 100
```

Spec decode accepted TPS:

```promql
sum by (vast_instance_id, served_model) (
  rate(vllm:spec_decode_num_accepted_tokens_total{job="vast-vllm"}[1m])
)
```

Spec decode acceptance rate:

```promql
sum by (vast_instance_id, served_model) (
  rate(vllm:spec_decode_num_accepted_tokens_total{job="vast-vllm"}[1m])
)
/
sum by (vast_instance_id, served_model) (
  rate(vllm:spec_decode_num_draft_tokens_total{job="vast-vllm"}[1m])
)
```

## Rollout plan

1. Implement `scripts/vast_vllm_prometheus_sd.py` in read-only mode.
2. Validate locally with `--once --probe`.
3. Run local `--serve` and confirm `/targets` JSON.
4. Add a small k3s Deployment/Service for discovery.
5. Add the `vast-vllm` scrape job to `monitoring-values.yaml`.
6. Helm upgrade the monitoring stack.
7. Check Prometheus `/targets` for `vast-vllm` health.
8. Add Grafana dashboard panels for TPS, queue, KV, prefix cache, and MTP acceptance.

## Caveats

- Vast container port `8000/tcp` maps to random external host ports; discovery must always read the live `ports` mapping.
- Instance labels may contain long model/profile names; use stable labels like `vast_instance_id`, `served_model`, `vast_gpu`, and `container_port`.
- Prometheus target staleness is handled naturally when HTTP SD stops returning destroyed instances.
- Keep private identifiers and API keys out of committed k3s manifests; use Kubernetes Secrets only when auth is required.
