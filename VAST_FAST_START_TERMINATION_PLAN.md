# Vast fast-start termination plan

Goal: avoid paying for interruptible instances that are stuck pulling/unpacking the Vast vLLM image instead of reaching provisioning quickly.

## Signal

Preferred fast-start signal in Vast logs:

```text
Status: Image is up to date for vastai/vllm:v0.20.0-cuda-13.0
```

The slow path to avoid looks like image layers downloading/verifying/pulling for minutes before the container starts.

## Current launcher mitigation

The active launch config is profile-based:

```text
config/launch-profiles/qwen3.5-9b-awq.interruptible.json
```

That launch profile keeps model-specific preferred and greylisted machine IDs under:

```json
"selection": {
  "preferred_machine_ids": [],
  "greylisted_machine_ids": []
}
```

Current known-good preferred machines are recorded in the profile and should be adjusted as more launches produce evidence.

Selection order is:

1. preferred machine ID
2. effective cost
3. reliability

This is a proxy because the Vast offer payload does not currently expose an image-cache field.

## Termination policy

For an interruptible smoke-test launch, terminate and relaunch if neither of these events occurs quickly.

### Event A: cached image confirmed

The instance log contains:

```text
Status: Image is up to date for vastai/vllm:v0.20.0-cuda-13.0
```

Expected within: **60 seconds after the first image pull log line**.

### Event B: provisioning has started

The instance log contains one of:

```text
Provisioning instance with manifest
Provisioning model from R2
R2 speed test enabled
Sync started at:
```

Expected within: **180 seconds after instance status first becomes loading/running**.

## Kill rule

Terminate the instance if:

```text
elapsed_since_loading >= 180s
AND cached-image signal not seen
AND provisioning-start signal not seen
```

Rationale: if provisioning has not started within ~3 minutes, we are likely paying for Docker pull/extract on an uncached/slow host. A cached host can reach provisioning almost immediately.

## Do not terminate if

Do not terminate once any of these appears:

```text
Provisioning model from R2
R2 speed test enabled
Sync started at:
download:
Sync finished at:
vLLM startup paused until instance provisioning has completed
```

At that point the container has started and the bottleneck has moved to R2 sync/model loading, not Docker image pull.

## R2 speed greylist policy

The provisioning script has a built-in non-secret speed threshold:

```bash
R2_SPEED_TEST_MIN_MBPS=100
R2_SPEED_TEST_MAX_MB=512
```

No template env is required. Override with Vast account/template env only when tuning; set `R2_SPEED_TEST_MIN_MBPS=0` to disable.

The provisioning script measures aggregate download with parallel ranged GETs, then uses rclone by default for the full R2 download. This keeps the 100 MB/s gate but tests a parallel path closer to the optimized transfer path.

Default transfer knobs:

```bash
R2_TRANSFER_TOOL=rclone
RCLONE_TRANSFERS=16
RCLONE_CHECKERS=32
RCLONE_MULTI_THREAD_STREAMS=8
```

Note: `--s3-upload-concurrency` is an rclone upload knob; this workflow downloads from R2 to Vast. The download-side equivalents we use are `--transfers` plus `--multi-thread-streams`.

The speed test logs:

```text
R2 speed test range: first <bytes> bytes across <N> parallel ranged GETs
R2 speed test result: <bytes> bytes in <seconds>s = <MB/s> MB/s
```

If below threshold it exits with code `42`. Treat that machine as bad for this R2/model path and add its machine ID to the relevant launch profile greylist.

Greylist reasons to track in commit/log notes:

- slow R2 speed test
- repeat slow/no cached Docker image
- outbid before provisioning despite high bid
- bad disk bandwidth despite advertised offer fields
- repeated provisioning failures unrelated to credentials

## Current automation

The guarded launcher starts the readiness monitor by default:

```bash
./run.sh scripts/select_and_launch.py \
  --launch-profile config/launch-profiles/qwen3.5-9b-awq.interruptible.json
```

The monitor is:

```text
scripts/monitor_instance_readiness.py
```

It detects provisioning, R2 sync, speed-test failures, vLLM startup, and hard provisioning failures. By default, launches from the guarded launcher monitor and destroy failed/stuck instances unless disabled with launcher flags.
