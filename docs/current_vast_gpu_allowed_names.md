# Current Vast GPU allowed names

This is a documentation-only snapshot of the exact Vast `gpu_name` strings currently allowed by profiles under `config/gpu-profiles/`.

The launcher does not read this file. Each GPU profile is the source of truth for launch filtering through its own `allowed_gpu_names` or `allowed_gpu_configs` list.

## Unique allowed names

- `A10`
- `A100 PCIE`
- `A100 SXM4`
- `B200`
- `H100 SXM`
- `H200`
- `L40`
- `L40S`
- `RTX 3090`
- `RTX 3090 Ti`
- `RTX 4090`
- `RTX 5060`
- `RTX 5060 Ti`
- `RTX 5070`
- `RTX 5070 Ti`
- `RTX 5080`
- `RTX 5090`
- `RTX 6000Ada`
- `RTX A5000`
- `RTX A6000`
- `RTX PRO 4000`
- `RTX PRO 4500`
- `RTX PRO 5000`
- `RTX PRO 6000`
- `RTX PRO 6000 S`
- `RTX PRO 6000 WS`

## Allowed names by profile

| Profile | Preferred GPU | Allowed GPU names |
| --- | --- | --- |
| `b200-1gpu.json` | `B200` | `B200` |
| `carnice-v2-27b-nvfp4-mtp-blackwell-1gpu.json` | — | `RTX 5060`, `RTX 5070`, `RTX 5060 Ti`, `RTX 5070 Ti`, `RTX 5080`, `RTX 5090`, `RTX PRO 4000`, `RTX PRO 4500`, `RTX PRO 5000`, `RTX PRO 6000`, `RTX PRO 6000 S`, `RTX PRO 6000 WS` |
| `carnice-v2-27b-nvfp4-mtp-rtx5060ti-2gpu.json` | — | `RTX 5060 Ti` |
| `carnice-v2-27b-nvfp4-mtp-rtx5070ti-2gpu.json` | — | `RTX 5070 Ti` |
| `carnice-v2-27b-nvfp4-mtp-rtx5090-1gpu.json` | — | `RTX 5090` |
| `h100-sxm-1gpu.json` | `H100 SXM` | `H100 SXM` |
| `h200-1gpu.json` | `H200` | `H200` |
| `qwen-27b-awq-48gb.json` | — | `A100 PCIE`, `A100 SXM4`, `L40`, `L40S`, `RTX 4090`, `RTX 6000Ada`, `RTX PRO 5000`, `RTX PRO 6000 S`, `RTX PRO 6000 WS` |
| `qwen-27b-awq-96gb-rtx-pro-6000-ws.json` | — | `RTX PRO 6000 WS` |
| `qwen-27b-awq-rtx3090-2gpu.json` | `RTX 3090` | `RTX 3090` |
| `qwen-9b-awq-1gpu.json` | — | `L40S`, `L40`, `RTX 3090`, `RTX 3090 Ti`, `RTX 4090`, `RTX 5090`, `RTX A5000`, `RTX A6000`, `A10`, `A100 PCIE`, `A100 SXM4` |

## Mixed GPU-count profiles

Profiles with `allowed_gpu_configs` can allow different GPU counts per `gpu_name`.

| Profile | GPU name | Required GPUs | Minimum total GPU RAM |
| --- | --- | ---: | ---: |
| `carnice-v2-27b-nvfp4-mtp-blackwell-1gpu.json` | `RTX 5060` | 4 | 30000 MB |
| `carnice-v2-27b-nvfp4-mtp-blackwell-1gpu.json` | `RTX 5070` | 4 | 30000 MB |
| `carnice-v2-27b-nvfp4-mtp-blackwell-1gpu.json` | `RTX 5060 Ti` | 2 | 30000 MB |
| `carnice-v2-27b-nvfp4-mtp-blackwell-1gpu.json` | `RTX 5070 Ti` | 2 | 30000 MB |
| `carnice-v2-27b-nvfp4-mtp-blackwell-1gpu.json` | `RTX 5080` | 2 | 30000 MB |
| `carnice-v2-27b-nvfp4-mtp-blackwell-1gpu.json` | `RTX 5090` | 1 | 30000 MB |
| `carnice-v2-27b-nvfp4-mtp-blackwell-1gpu.json` | `RTX PRO 4000` | 2 | 30000 MB |
| `carnice-v2-27b-nvfp4-mtp-blackwell-1gpu.json` | `RTX PRO 4500` | 1 | 30000 MB |
| `carnice-v2-27b-nvfp4-mtp-blackwell-1gpu.json` | `RTX PRO 5000` | 1 | 30000 MB |
| `carnice-v2-27b-nvfp4-mtp-blackwell-1gpu.json` | `RTX PRO 6000` | 1 | 30000 MB |
| `carnice-v2-27b-nvfp4-mtp-blackwell-1gpu.json` | `RTX PRO 6000 S` | 1 | 30000 MB |
| `carnice-v2-27b-nvfp4-mtp-blackwell-1gpu.json` | `RTX PRO 6000 WS` | 1 | 30000 MB |

## Notes

- Keep names exact; Vast offer filtering compares against `gpu_name` strings.
- `RTX 6000Ada` is intentionally written without a space because that is the observed Vast string used by the profiles.
- Mixed Blackwell filtering uses `allowed_gpu_configs` so 8-12GB cards are only accepted as 4-GPU offers, 16GB-class GPUs such as `RTX 5060 Ti` are only accepted as 2-GPU offers, and all mixed configs require at least about 32GB total VRAM.
- This file should be updated when profile `allowed_gpu_names` or `allowed_gpu_configs` lists change.
