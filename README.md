# RRG-Server

Infrastructure documentation and configuration for the Resource Realty Group server.

**Hardware:** Dell Inspiron 3880 (i5-10400, 12GB RAM, Ubuntu 24.04.3 LTS)
**Location:** RRG Office
**Tailscale IP:** 100.97.86.99

## What Runs Here

- **rrg-router** — Streamlit chat UI that routes to specialized workers
- **rrg-pnl** — P&L analysis worker
- **rrg-brochure** — CRE brochure generator worker
- **DocuSeal** — Self-hosted NDA signing (custom fork)
- **Windmill** — Workflow automation (switchboard, lead intake, signals)

## Documentation

- [Architecture](docs/ARCHITECTURE.md) — Three-layer system diagrams (physical, services, workflows)
- [Current State](docs/CURRENT_STATE.md) — Verified technical details
- [Lead Intake Pipeline](docs/LEAD_INTAKE_PIPELINE.md) — Automated CRE lead processing (6 modules)
- [Lead Conversation Engine](docs/LEAD_CONVERSATION_ENGINE.md) — Reply classification and response (4 modules)

## Related Repositories

- [jake-assistant-system](https://github.com/BeastofOne/jake-assistant-system) — Executive function support system (artifacts, skills, CRM integration)
- [soggy-potatoes](https://github.com/BeastofOne/soggy-potatoes) — Sticker shop (separate project)

