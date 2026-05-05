# Vast fast-start termination plan

Goal: avoid paying for interruptible instances that are stuck pulling/unpacking the Vast vLLM image instead of reaching provisioning quickly.

## Signal

Preferred fast-start signal in Vast logs:

```text
Status: Image is up to date for vastai/vllm:v0.20.0-cuda-13.0
```

This means the selected host already has the target Docker image cached. On machine `56761` this appeared immediately at:

```text
2026-05-05 08:36:47 UTC
```

The slow path to avoid looks like image layers downloading/verifying/pulling for minutes before the container starts.

## Current launcher mitigation

`config/launch-policy.l40s-prototype.json` now prefers known-good cached-image machines:

```json
"preferred_machine_ids": [56761, 51970]
```

Selection order is now:

1. preferred machine ID
2. effective cost
3. reliability

This is a proxy because the Vast offer payload does not currently expose an image-cache field. Current preferred machines:

- `56761` — A100 PCIE, confirmed cached image via `Status: Image is up to date...`
- `51970` — RTX 3090, reached container/provisioning quickly in prior launch

## Termination policy

For an interruptible smoke-test launch, terminate and relaunch if neither of these events occurs quickly:

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
Sync started at:
download:
Sync finished at:
vLLM startup paused until instance provisioning has completed
```

At that point the container has started and the bottleneck has moved to R2 sync/model loading, not Docker image pull.

## R2 speed greylist policy

For future launches, set a non-secret template env threshold:

```bash
R2_SPEED_TEST_MIN_MBPS=100
R2_SPEED_TEST_MAX_MB=512
```

The provisioning script will copy one large model object before full sync and log:

```text
R2 speed test result: <bytes> bytes in <seconds>s = <MB/s> MB/s
```

If below threshold it exits with code `42`. Treat that machine as bad for this R2/model path and add its machine ID to:

```json
"greylisted_machine_ids": []
```

Greylist reasons to track in commit/log notes:

- slow R2 speed test
- repeat slow/no cached Docker image
- outbid before provisioning despite high bid
- bad disk bandwidth despite advertised offer fields
- repeated provisioning failures unrelated to credentials

## Future automation

Add `scripts/monitor_launch.py` to:

1. Poll `show_instance()` until status is `loading` or `running`.
2. Fetch recent instance logs if the SDK exposes logs, or require user-pasted logs until log API is identified.
3. Detect the cached-image and provisioning-start strings above.
4. Call Vast destroy/detach instance if the kill rule fires.
5. Relaunch via `scripts/select_and_launch.py`, preferring known-good cached machine IDs.

If no log API is available, implement a manual checklist command that prints the exact kill deadline from status timestamps and the strings to look for.
