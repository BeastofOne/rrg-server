# Network & Infrastructure

## Tailscale Machines
| Machine | IP | SSH User | Role |
|---------|-----|----------|------|
| jake-macbook | 100.108.74.112 | jacobphillips | Claude Code, claude-endpoint (pm2) |
| pixel-9a | 100.125.176.16 | — | SMS gateway (Termux + Flask, Crexi/LoopNet leads only) |
| rrg-server | 100.97.86.99 | andrea | Windmill, Postgres, Docker, n8n, DocuSeal |
| larry-sms-gateway | 100.79.238.103 | larrygotcher | iMessage relay (no longer SMS gateway) |

## Key Ports
- Claude Endpoint: 8787 (jake-macbook, pm2)
- n8n: 5678 (rrg-server)
- Windmill: 8000 (rrg-server)
- DocuSeal: 3000 (rrg-server)
- SMS Gateway: 8686 (pixel-9a, Termux Flask)

## SSH Access
- **Tailscale SSH enabled on rrg-server** — use `ssh andrea@rrg-server` (no keys/passwords needed)
- Key auth configured from jake-macbook → other machines
- Passwords in Windmill resource `f/switchboard/tailscale_machines`
