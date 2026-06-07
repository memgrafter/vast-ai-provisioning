# Vast SSH authorized_keys repair runbook

Use this when a Vast instance is running but SSH fails even though the local key is being offered.

Typical log symptoms:

```text
Authentication refused: bad ownership or modes for file /root/.ssh/authorized_keys
Failed publickey for root ... ED25519 SHA256:<fingerprint>
```

## Confirm the local key being offered

```bash
ssh -vvv \
  -o IdentitiesOnly=yes \
  -i ~/.ssh/id_ed25519 \
  -p <mapped_22_host_port> \
  root@<public_ip> true
```

Look for:

```text
Offering public key: ... ~/.ssh/id_ed25519 ... explicit
```

If the instance logs show the same fingerprint, the client is presenting the intended key and the failure is server-side.

## Repair without destroying the instance

Vast `execute` only works when the instance is fully stopped/exited. Do not destroy the instance.

Set the instance id:

```bash
export VAST_INSTANCE_ID=<instance_id>
source env.vast-management
```

Stop the instance:

```bash
.venv/bin/python - <<'PY'
import os
from vastai import VastAI
print(VastAI().stop_instance(id=int(os.environ["VAST_INSTANCE_ID"])))
PY
```

Wait until `actual_status` is `exited` or `stopped`:

```bash
.venv/bin/python - <<'PY'
import os
from vastai import VastAI
info = VastAI().show_instance(id=int(os.environ["VAST_INSTANCE_ID"]))
print(info.get("actual_status"), info.get("cur_state"), info.get("intended_status"))
PY
```

Remove the broken SSH directory while stopped:

```bash
.venv/bin/python - <<'PY'
import os
from vastai import VastAI
print(VastAI().execute(id=int(os.environ["VAST_INSTANCE_ID"]), command="rm -r /root/.ssh"))
PY
```

Reattach the local account key:

```bash
.venv/bin/python - <<'PY'
import os
from pathlib import Path
from vastai import VastAI
vast = VastAI()
key = Path("~/.ssh/id_ed25519.pub").expanduser().read_text().strip()
print(vast.attach_ssh(instance_id=int(os.environ["VAST_INSTANCE_ID"]), ssh_key=key))
PY
```

Start the instance:

```bash
.venv/bin/python - <<'PY'
import os
from vastai import VastAI
print(VastAI().start_instance(id=int(os.environ["VAST_INSTANCE_ID"])))
PY
```

After it returns to `running`, test SSH:

```bash
ssh -o IdentitiesOnly=yes \
  -i ~/.ssh/id_ed25519 \
  -p <mapped_22_host_port> \
  root@<public_ip> \
  'echo SSH_OK; stat -c "%U:%G %a %n" /root/.ssh /root/.ssh/authorized_keys; wc -l /root/.ssh/authorized_keys'
```

Expected output includes:

```text
SSH_OK
root:root 700 /root/.ssh
root:root 600 /root/.ssh/authorized_keys
```

## Notes

- Do not rely on updating `onstart` to repair an already-created instance; Vast may not rewrite `/root/onstart.sh` for the existing container snapshot.
- Reboot alone may not fix ownership/mode problems.
- The stopped-instance `execute` command is constrained; common allowed commands include `ls`, `cat`, `du`, and `rm`.
- If `attach_ssh` says the key is already associated, the important step is still removing the broken `/root/.ssh` while stopped and starting again so Vast recreates it.
