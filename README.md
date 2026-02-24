# RRG Server

Infrastructure monorepo for Resource Realty Group — CRE brokerage automation.

## What's Here

| Directory | Description | Stack |
|-----------|-------------|-------|
| `rrg-router/` | Chat UI + intent router | Streamlit, LangGraph, Python |
| `rrg-pnl/` | P&L analysis worker | Flask, LangGraph, WeasyPrint |
| `rrg-brochure/` | Property brochure generator | Flask, LangGraph, Playwright |
| `rrg-claude-endpoint/` | Claude API proxy | Node.js, pm2 |
| `rrg-email-assistant/` | Email automation tools | Gmail MCP, Node.js |
| `windmill-mcp/` | Windmill MCP server | TypeScript, MCP SDK |
| `windmill/` | Windmill flows/scripts (auto-synced) | Python, TypeScript |
| `deploy/` | Docker Compose + env config | Docker, Nix |

## Architecture

Four machines on [Tailscale](https://tailscale.com/):

```
jake-macbook ─── Claude Code + claude-endpoint (pm2)
                   │
rrg-server   ─── Docker (pnl, brochure, router) + Windmill + Postgres + DocuSeal
                   │
pixel-9a     ─── SMS gateway (Termux + Flask)
                   │
larry-sms    ─── iMessage relay
```

**rrg-server hardware:** Dell Inspiron 3880 (i5-10400, 12GB RAM, Ubuntu 24.04)
**Tailscale IP:** 100.97.86.99

## Build & Deploy

All services use Nix flakes for reproducible Docker image builds:

```bash
ssh andrea@rrg-server
cd ~/rrg-server/rrg-pnl
nix build && docker load < result
cd ~/rrg-server/deploy && docker compose up -d
```

See [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) for full details.

## Sync

Both machines run `rrg-sync.sh` on 5-minute cron — auto-commits, pushes, and pulls. Windmill flows export hourly via `wmill sync pull`.

## Documentation

- [Architecture](docs/ARCHITECTURE.md) — System diagrams (Mermaid)
- [Deployment](docs/DEPLOYMENT.md) — Build pipeline, deploy commands, disaster recovery
- [Current State](docs/CURRENT_STATE.md) — Verified technical details
- [Lead Intake Pipeline](docs/LEAD_INTAKE_PIPELINE.md) — Automated CRE lead processing
- [Lead Conversation Engine](docs/LEAD_CONVERSATION_ENGINE.md) — Reply classification and response

## Related

- [BeastofOne/docuseal](https://github.com/BeastofOne/docuseal) — DocuSeal fork with RRG customizations (`rrg` branch)
