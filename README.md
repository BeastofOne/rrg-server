# RRG-Server

Infrastructure documentation and configuration for the Resource Realty Group server.

**Hardware:** Dell Inspiron 3880 (i5-10400, 12GB RAM, Ubuntu 24.04.3 LTS)
**Location:** RRG Office
**Tailscale IP:** 100.97.86.99

## What Runs Here

- **jake-router** — Streamlit chat UI that routes to specialized workers
- **jake-pnl** — P&L analysis worker
- **jake-brochure** — CRE brochure generator worker
- **DocuSeal** — Self-hosted NDA signing (custom fork)
- **Windmill** — Workflow automation (switchboard, lead intake, signals)

## Documentation

- [Architecture](docs/ARCHITECTURE.md) — Three-layer system diagrams (physical, services, workflows)
- [Current State](docs/CURRENT_STATE.md) — Verified technical details

## Related Repositories

- [jake-assistant-system](https://github.com/BeastofOne/jake-assistant-system) — Executive function support system (artifacts, skills, CRM integration)
- [jake-assistant](https://github.com/BeastofOne/jake-assistant) — jake-router source code (Streamlit + LangGraph)
- [soggy-potatoes](https://github.com/BeastofOne/soggy-potatoes) — Sticker shop (separate project)

