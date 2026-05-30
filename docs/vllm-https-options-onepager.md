# HTTPS options for Vast vLLM endpoints

## Current state

Vast exposes the vLLM API through a mapped public host port, e.g.:

```text
http://<public_ip>:<mapped_8000>/v1
```

That direct mapped port is plain HTTP. The API is protected by `Authorization: Bearer $VLLM_API_KEY`, but transport is not encrypted.

## Recommended path: Cloudflare Tunnel

Use `cloudflared` on the instance/container to expose local vLLM through a Cloudflare hostname:

```text
https://vllm.example.com/v1  ->  http://127.0.0.1:18000/v1
```

Benefits:

- HTTPS without relying on Vast inbound `:443`.
- Stable hostname independent of Vast random external ports.
- No public origin port required if using an outbound tunnel.
- Can add Cloudflare Access/WAF/rate limits in front of vLLM.
- Keeps existing vLLM bearer auth.

Operational notes:

- Store tunnel credentials outside the public repo.
- Keep `VLLM_API_KEY` required at vLLM/proxy layer.
- Prefer a named tunnel and DNS route managed in Cloudflare.
- Health-check `/v1/models` after tunnel startup.

## Alternative: in-container Caddy/nginx TLS

Run Caddy or nginx on the instance and proxy HTTPS to local vLLM:

```text
https://vllm.example.com/v1  ->  http://127.0.0.1:18000/v1
```

Requirements:

- A domain pointing at the Vast host/IP.
- Inbound mapped port for `443/tcp` or another HTTPS port.
- Certificate automation via ACME/Let’s Encrypt.

Downside: Vast public IPs/ports are ephemeral, so DNS and cert issuance can be brittle unless launch automation updates them.

## Alternative: Vast portal HTTPS

Vast’s portal/Caddy layer may provide HTTPS links for some services, but direct container port mappings remain HTTP. Treat portal HTTPS as convenience, not the canonical production API endpoint, unless verified for the specific instance and port.

## Local/private option: SSH tunnel

For personal testing, tunnel the remote vLLM port locally and terminate HTTPS locally if needed:

```text
local HTTPS proxy -> localhost tunnel -> remote http://127.0.0.1:18000
```

This is simple for one user but not suitable as a shared production endpoint.

## Recommendation

Use **Cloudflare Tunnel** for production-style Vast vLLM access:

```text
client -> HTTPS Cloudflare hostname -> cloudflared tunnel -> local vLLM HTTP
```

Keep bearer auth enabled, do not commit tunnel credentials, and make readiness checks use the HTTPS hostname once configured.
