# Hermes Stack Memory Profile — 4GB VM (observed 2026-05)

## Steady-state (healthy, after restart)
| Process | RSS |
|---|---|
| hermes-gateway | ~196MB (5.0% of 3.8GB) |
| hermes-webui | ~197MB (4.9%) |
| hermes mcp serve ×2 | ~84MB each |
| hermes-wechat | ~40MB |
| hermes-metrics | ~20MB |
| rss_panel.py | ~28MB |
| sub2api | ~115MB |
| dockerd | ~76MB |
| new-api (in container) | ~67MB |
| containerd | ~49MB |
| postgres (multiple workers) | ~30MB each |
| sing-box | ~33MB |
| cloudflared | ~29MB |
| **Total approx** | **~1.5GB** |

## Peak / leak state (after days without restart)
| Process | Peak RSS |
|---|---|
| hermes-gateway | up to 1.2GB (confirmed leak) |
| hermes-webui | up to 2.2GB (heavy session) |
| **Total at peak** | **~2.3GB+ → triggers swap** |

## Observed cleanup gains (2026-05-10 session)
- Killed 10 hung `bash -c rg` processes from 2026-05-08
- `swapoff -a && swapon -a` → swap 606MB → 0
- Restarted gateway (done by another agent) → gateway 663MB → 196MB
- Available RAM: 1.5GB → 2.3GB

## Swap threshold guidance
- Swap < 50MB: normal, ignore
- Swap 50–200MB: monitor
- Swap > 200MB: investigate and relieve
- Swap > 500MB: active thrashing, restart leaking services immediately
