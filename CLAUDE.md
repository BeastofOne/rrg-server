# RRG Server — CRE Workspace

## Overview

Jake's CRE business infrastructure. Monorepo with source code, deploy config, and Windmill flows.

```
rrg-server/
├── rrg-router/            # Streamlit chat UI + intent router (port 8501)
├── rrg-pnl/              # P&L analysis (LangGraph + Flask, port 8100)
├── rrg-brochure/          # Property brochure generator (LangGraph + Flask, port 8101)
├── windmill-worker/       # Nix flake: stock Windmill + Claude CLI layer
├── rrg-claude-endpoint/   # DEPRECATED — Claude CLI now in containers directly
├── rrg-email-assistant/   # Email automation (MCP tools, no server)
├── windmill-mcp/          # Local Windmill MCP server (Node.js)
├── windmill/              # Windmill flows/scripts (auto-synced from DB)
├── deploy/                # Docker Compose + env config
├── docs/                  # Architecture diagrams, pipeline docs
└── .claude/               # Rules, skills, hooks
```

## System Architecture

**Four machines on Tailscale** (details → `.claude/rules/network.md`):
- **jake-macbook** — Claude Code
- **rrg-server** — Docker containers (pnl, brochure, router), Windmill, Postgres, DocuSeal
- **pixel-9a** — SMS gateway (Termux + Flask, port 8686)
- **larry-sms-gateway** — iMessage relay

**Two-machine sync:** `rrg-sync.sh` runs on 5-min cron on both machines. Changes auto-commit and push/pull via GitHub. Windmill flows sync hourly.

## Key Patterns

**Worker contract:** rrg-pnl and rrg-brochure expose identical `POST /process` (command, user_message, chat_history, state) → (response, state, active, pdf_bytes).

**claude_llm.py:** Shared across all three services. LangChain `BaseChatModel` wrapping `claude -p` CLI. Model from env `CLAUDE_MODEL` (default: "haiku").

**Windmill flows** (source in `windmill/f/switchboard/`):
- `lead_intake` — 6-module pipeline: WiseAgent lookup → property match → dedup → drafts → approval gate → post-approval. Handles commercial (Crexi/LoopNet/BizBuySell) and residential (Realtor.com/Seller Hub/Social Connect/UpNest) sources.
- `lead_conversation` — 4-module pipeline: classify reply → generate response → approval gate → post-approval. Source-branched prompts (commercial/residential buyer/residential seller) with rigid frameworks.
- `message_router` — Routes to rrg-pnl or rrg-brochure
- `gmail_pubsub_webhook` — Gmail Pub/Sub handler (lead detection, SENT matching, reply detection)

**Gmail split inbox:**
- **leads@resourcerealtygroupmi.com** — receives lead notifications
- **teamgotcher@gmail.com** — sends drafts, receives replies

**DocuSeal:** Separate fork repo (`BeastofOne/docuseal`, `rrg` branch). Self-hosted on port 3000. Template ID 1 = NCND-RRG.

## Windmill Resources & Variables

Resources: `wiseagent_oauth`, `gmail_oauth`, `gmail_leads_oauth`, `pg`, `tailscale_machines`
Variables: `property_mapping`, `gmail_last_history_id`, `gmail_leads_last_history_id`, `sms_gateway_url`, `router_token`, `email_signatures`
(All under `f/switchboard/` namespace)

**Lead sources & signers:**
- **Commercial** (Crexi, LoopNet, BizBuySell) — signed by Larry
- **Residential buyer** (Realtor.com, UpNest buyer) — signed by Andrea
- **Residential seller** (Seller Hub, Social Connect, UpNest seller) — signed by Andrea
- Signer determination: `f/switchboard/email_signatures` variable (template prefix → signer, source → signer, with in-flight thread continuity via `template_used`)

## Deployment

See `docs/DEPLOYMENT.md` for full build/deploy instructions.

Quick reference:
```bash
ssh andrea@rrg-server
cd ~/rrg-server/rrg-pnl && nix build && docker load < result
cd ~/rrg-server/deploy && docker compose up -d
```

## Documentation

| Doc | Contents |
|-----|----------|
| `docs/DEPLOYMENT.md` | Build pipeline, deploy commands, auto-sync, disaster recovery |
| `docs/ARCHITECTURE.md` | Three-layer system diagrams (Mermaid) |
| `docs/CURRENT_STATE.md` | Verified technical details |
| `docs/LEAD_INTAKE_PIPELINE.md` | Lead intake flow detail (6 modules, resume mechanism) |
| `docs/LEAD_CONVERSATION_ENGINE.md` | Lead conversation engine detail (4 modules, intent classification) |

## Reference Files

- Network/IPs/ports → `.claude/rules/network.md`
- Email rules → `.claude/rules/email.md`
- Doc-sync enforcement → `.claude/rules/doc-sync.md`

## Absolute Rules

1. Jake's provided contact info wins — never substitute CRM data
2. Jake uses DocuSeal (self-hosted) for NDAs — Template ID 1 is NCND-RRG
3. Jake's exact words — copy verbatim, never summarize unless >10 lines
4. Never approve signals without Jake's explicit approval
5. Never modify Windmill flows/scripts without reviewing current state first
6. Always verify WiseAgent OAuth token freshness before API calls
