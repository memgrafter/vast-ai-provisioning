-- Launch ledger analytics schema.
-- Purpose: one golden analytics row per launched Vast instance.
-- This database is read/write for audit/reconciliation only; it must not drive
-- launch selection or runtime application behavior.
-- Suggested local path: state/launches.sqlite3

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS launches (
  -- Canonical identity
  launch_key TEXT PRIMARY KEY,              -- e.g. vast:instance:36801724
  provider TEXT NOT NULL DEFAULT 'vast',
  instance_id INTEGER UNIQUE NOT NULL,
  offer_id INTEGER,
  machine_id INTEGER,

  -- Lifecycle timestamps, UTC ISO-8601 text
  created_at TEXT NOT NULL,
  running_at TEXT,
  ready_at TEXT,
  terminated_at TEXT,
  last_seen_at TEXT,

  lifecycle_status TEXT,                    -- created/running/ready/failed/destroyed/unknown
  termination_reason TEXT,
  destroyed_by_script INTEGER NOT NULL DEFAULT 0,

  -- Canonical profile join keys and immutable profile fingerprints
  launch_profile_name TEXT,
  launch_profile_path TEXT,
  launch_profile_sha256 TEXT,

  model_profile_name TEXT,
  model_profile_path TEXT,
  model_profile_sha256 TEXT,

  gpu_profile_name TEXT,
  gpu_profile_path TEXT,
  gpu_profile_sha256 TEXT,

  template_name TEXT,
  template_hash_id TEXT,

  -- Model/runtime profile snapshot, intentionally non-secret
  hf_model_id TEXT,
  served_model_name TEXT,
  quantization TEXT,
  dtype TEXT,
  max_model_len INTEGER,
  gpu_memory_utilization REAL,
  expected_model_download_tb REAL,

  -- Market/GPU/offer snapshot
  market TEXT,                               -- on-demand/interruptible/spot/bid
  gpu_name TEXT,
  num_gpus INTEGER,
  gpu_total_ram_mb REAL,
  cuda_max_good REAL,
  driver_version TEXT,
  verification TEXT,
  reliability2 REAL,

  disk_available_gb REAL,
  disk_bw REAL,
  inet_down_mbps REAL,
  inet_up_mbps REAL,
  direct_port_count INTEGER,

  -- Storage policy and net storage cost snapshot
  requested_disk_gb REAL,
  storage_total_cost_per_hour REAL,
  storage_cost_per_requested_gb_hour REAL,
  storage_fraction_of_total REAL,

  policy_max_storage_total_cost_per_hour REAL,
  policy_max_storage_cost_per_gb_hour REAL,
  policy_max_storage_fraction_of_total REAL,
  policy_warn_storage_fraction_of_total REAL,

  -- Cost snapshot at launch/selection time
  dph_base REAL,
  dph_total REAL,
  compute_cost_per_hour REAL,
  internet_down_cost_per_tb REAL,
  internet_up_cost_per_tb REAL,
  spot_bid_dph REAL,

  estimated_pull_cost_usd REAL,
  estimated_runtime_cost_usd REAL,
  estimated_total_cost_usd REAL,

  -- Readiness/provisioning summary
  image_cached INTEGER,
  provisioning_started INTEGER,
  r2_sync_started INTEGER,
  r2_sync_finished INTEGER,
  provisioning_complete INTEGER,
  vllm_started INTEGER,
  api_ready INTEGER,
  speed_test_failed INTEGER,
  provisioning_failed INTEGER,

  monitor_exit_code INTEGER,
  smoke_exit_code INTEGER,
  error_summary TEXT,

  -- Pointers to local ignored artifacts; avoid embedding large raw JSON/logs here.
  selected_offer_json_path TEXT,
  instance_json_path TEXT,
  monitor_json_path TEXT,
  logs_path TEXT,

  -- Ledger bookkeeping
  inserted_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_launches_provider_instance
  ON launches(provider, instance_id);

CREATE INDEX IF NOT EXISTS idx_launches_machine
  ON launches(provider, machine_id);

CREATE INDEX IF NOT EXISTS idx_launches_profiles
  ON launches(launch_profile_name, model_profile_name, gpu_profile_name);

CREATE INDEX IF NOT EXISTS idx_launches_model
  ON launches(served_model_name, hf_model_id, quantization);

CREATE INDEX IF NOT EXISTS idx_launches_market_gpu
  ON launches(market, gpu_name, num_gpus);

CREATE INDEX IF NOT EXISTS idx_launches_lifecycle
  ON launches(lifecycle_status, created_at, terminated_at);

CREATE INDEX IF NOT EXISTS idx_launches_cost
  ON launches(dph_total, storage_total_cost_per_hour, storage_fraction_of_total);

CREATE INDEX IF NOT EXISTS idx_launches_storage_policy
  ON launches(storage_cost_per_requested_gb_hour, policy_max_storage_cost_per_gb_hour);

CREATE TABLE IF NOT EXISTS launch_events (
  -- First-seen lifecycle/provisioning/smoke events for launch timeline analytics.
  -- One row per event name per launch. Use this to calculate launch legs like:
  -- sdk_create_returned - launch_requested, running - sdk_create_returned,
  -- api_ready - r2_sync_finished, smoke_passed - launch_requested, etc.
  launch_key TEXT NOT NULL,
  event_name TEXT NOT NULL,
  event_at TEXT NOT NULL,
  source TEXT NOT NULL,                    -- select_and_launch/monitor/reconcile/smoke/manual
  details_json TEXT,
  inserted_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  PRIMARY KEY (launch_key, event_name),
  FOREIGN KEY (launch_key) REFERENCES launches(launch_key) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_launch_events_name_time
  ON launch_events(event_name, event_at);

CREATE INDEX IF NOT EXISTS idx_launch_events_launch_time
  ON launch_events(launch_key, event_at);

CREATE TABLE IF NOT EXISTS launch_metric_samples (
  -- Lightweight analytics samples. This is intentionally generic so we can
  -- record current Vast instance metrics and selected vLLM Prometheus metrics
  -- without running a metrics server yet.
  sample_id INTEGER PRIMARY KEY AUTOINCREMENT,
  launch_key TEXT NOT NULL,
  sampled_at TEXT NOT NULL,
  source TEXT NOT NULL,                    -- vast/reconcile/vllm/prometheus/manual
  metric_name TEXT NOT NULL,
  metric_value REAL,
  labels_json TEXT,
  details_json TEXT,
  inserted_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  FOREIGN KEY (launch_key) REFERENCES launches(launch_key) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_launch_metric_samples_launch_time
  ON launch_metric_samples(launch_key, sampled_at);

CREATE INDEX IF NOT EXISTS idx_launch_metric_samples_metric_time
  ON launch_metric_samples(metric_name, sampled_at);
