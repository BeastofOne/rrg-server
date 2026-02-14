# RRG Server — CRE Workspace

## Overview

Jake's CRE business infrastructure. Four projects, one monorepo:

```
rrg-server/
├── rrg-pnl/              # P&L analysis (LangGraph + Flask, port 8100)
├── rrg-brochure/          # Property brochure generator (LangGraph + Flask, port 8101)
├── rrg-claude-endpoint/   # Claude API proxy (Node.js + pm2, port 8787)
├── rrg-email-assistant/   # Email automation (MCP tools, no server)
├── docs/                  # Architecture diagrams, current state
└── .claude/               # Rules, skills, hooks
```

## System Architecture

**Three machines on Tailscale** (details → `.claude/rules/network.md`):
- **jake-macbook** — Claude Code, claude-endpoint (pm2)
- **rrg-server** — Docker containers (pnl, brochure), Windmill, Postgres, DocuSeal
- **larry-sms-gateway** — SMS/iMessage relay

**Worker pattern:** rrg-pnl and rrg-brochure are identical Flask microservices behind a message router. Both expose `POST /process` with the same request/response contract:

```json
// Request (both workers)
{
  "command": "create" | "continue",
  "user_message": "string",
  "chat_history": [{"role": "user|assistant", "content": "..."}],
  "state": {}  // opaque, passed back from previous response
}

// Response (both workers)
{
  "response": "string",       // display to user
  "state": {},                // pass back next time
  "active": true,             // true = worker still owns conversation
  "pdf_bytes": "base64|null", // generated PDF
  "pdf_filename": "string|null"
}
```

## Code Map

### rrg-pnl/ — P&L Analysis Worker
| File | What it does | Key exports |
|------|-------------|-------------|
| `server.py` | Flask app, `POST /process` + `GET /health` | `process()`, `health()` |
| `graph.py` | LangGraph workflow (7 nodes: entry → extract/nudge/triage → edit/approve/question/cancel → END) | `build_graph()`, `PnlState` TypedDict |
| `pnl_handler.py` | LLM-powered data extraction/modification | `extract_pnl_data()`, `apply_changes()`, `is_approval()`, `compute_pnl()`, `format_pnl_table()` |
| `pnl_pdf.py` | Jinja2 template → HTML → WeasyPrint PDF | `generate_pnl_pdf(data) → bytes` |
| `claude_llm.py` | LangChain wrapper around `claude -p` CLI | `ChatClaudeCLI` class |
| `templates/pnl.html` | Jinja2 HTML template for PDF | — |

### rrg-brochure/ — Property Brochure Generator
| File | What it does | Key exports |
|------|-------------|-------------|
| `server.py` | Flask app, `POST /process` + `GET /health` | `process()`, `health()` |
| `graph.py` | LangGraph workflow (10 nodes: entry → extract/nudge/triage → edit/approve/preview/question/cancel/photo_search → END) | `build_graph()`, `BrochureState` TypedDict, `BROCHURE_ZONES` |
| `brochure_pdf.py` | Jinja2 template → HTML → Playwright/Chromium PDF (11"×8.5" landscape) | `generate_brochure_pdf(data) → bytes` |
| `photo_scraper.py` | Claude CLI + WebSearch → page fetch → regex image extraction → HEAD filter | `search_property_photos(name, address) → [{url, description, source}]` |
| `photo_search_pdf.py` | Downloads images → numbered contact sheet PDF via Playwright | `generate_photo_search_pdf(photos, name, address) → bytes` |
| `claude_llm.py` | Same as rrg-pnl (LangChain wrapper around `claude -p`) | `ChatClaudeCLI` class |
| `templates/brochure.html` | Jinja2 HTML template for brochure | — |
| `templates/static/` | Logo, headshots (rrg-logo.png, larry-headshot.png, jake-headshot.png) | — |

### rrg-claude-endpoint/ — Claude API Proxy
| File | What it does | Key exports |
|------|-------------|-------------|
| `server.js` | Node.js HTTP server, pipes prompts to `claude -p` CLI | Listens on port 8787 |

### rrg-email-assistant/ — Email Automation
| File | What it does |
|------|-------------|
| `email_templates.md` | Property-specific email templates (Parkwood, DQ, Mattawan, etc.) |
| `gmail-mcp/` | Gmail MCP server (Node.js) |
| `autofill-dotloop.py` | DEPRECATED — legacy browser automation |

### Shared Pattern: `claude_llm.py`
Both rrg-pnl and rrg-brochure use identical `ChatClaudeCLI` class:
- LangChain `BaseChatModel` subclass
- Calls `claude -p <prompt> --model <model> --allowedTools ""` (no tools, pure reasoning)
- Formats messages as `[System]\n...\n\n[User]\n...` blocks
- `model_name` from env `CLAUDE_MODEL` (default: "haiku")

## Windmill Pipeline (rrg-server)

### Lead Intake Flow (`f/switchboard/lead_intake`)
6-module pipeline:
1. **WiseAgent Lookup** — Search contacts by email, check existing/NDA status
2. **Property Match** — Match against `property_mapping` Windmill variable
3. **Dedup/Group** — Combine same-person multi-property notifications
4. **Generate Drafts + Gmail** — Create Gmail drafts with `X-Lead-Intake-*` headers
5. **Approval Gate** — Suspend flow, write signal to `jake_signals` Postgres table
6. **Post-Approval** — Update WiseAgent notes + send SMS via gateway

### WiseAgent CRM (lead intake only)
- OAuth API: `sync.thewiseagent.com`
- Credentials: Windmill resource `f/switchboard/wiseagent_oauth` (auto-refreshed)
- Client ID/secret: Windmill resource `f/wiseagent/credentials`

### Signal System (Postgres `jake_signals` table)
- `s/switchboard/write_signal` — Create signal
- `s/switchboard/read_signals` — Read pending
- `s/switchboard/act_signal` — Approve/process
- `s/switchboard/get_pending_draft_signals` — Check draft signals

### Gmail Integration
- OAuth: `f/switchboard/gmail_oauth` (teamgotcher@gmail.com)
- Pub/Sub: `s/switchboard/gmail_pubsub_webhook`
- Watch: `s/switchboard/setup_gmail_watch`

### Message Router (`f/switchboard/message_router`)
- Routes to rrg-pnl (port 8100) or rrg-brochure (port 8101)

### DocuSeal NDAs
- Webhook: `s/docuseal/nda_completed` (Bun/JS)
- Template ID 1 = NCND-RRG
- Self-hosted on rrg-server port 3000

### Windmill Resources
| Resource | Purpose |
|----------|---------|
| `f/switchboard/wiseagent_oauth` | WiseAgent OAuth tokens (auto-refreshed) |
| `f/wiseagent/credentials` | WiseAgent client ID/secret |
| `f/switchboard/gmail_oauth` | Gmail OAuth for teamgotcher@gmail.com |
| `f/switchboard/pg` | Postgres connection (jake_signals table) |
| `f/switchboard/tailscale_machines` | Network configs + SSH passwords |

## Deployment

### rrg-pnl / rrg-brochure (Nix → Docker → rrg-server)
```bash
# Build Docker image locally
nix build .#docker

# Copy to rrg-server and load
scp result andrea@100.97.86.99:~/jake-images/<name>.tar.gz
ssh andrea@100.97.86.99 'docker load < ~/jake-images/<name>.tar.gz && cd ~/jake-deploy && docker compose -f docker-compose.jake.yml up -d'
```
Env vars from `jake-deploy/.env`: `CLAUDE_CODE_OAUTH_TOKEN`, `CLAUDE_MODEL`

### rrg-claude-endpoint (pm2 on jake-macbook)
```bash
pm2 start server.js --name claude-endpoint
pm2 restart claude-endpoint
pm2 logs claude-endpoint
```

### Local dev (any Python worker)
```bash
nix develop
python graph.py  # or python server.py
```

## Infrastructure Docs
| File | Contents |
|------|----------|
| `docs/ARCHITECTURE.md` | Three-layer system diagrams (Mermaid) |
| `docs/CURRENT_STATE.md` | Verified technical details |
| `docs/mermaid/*.mmd` | Standalone diagram source files |

## Reference Files
- Network/IPs/ports → `.claude/rules/network.md`
- Email rules → `.claude/rules/email.md`
- Doc-sync enforcement → `.claude/rules/doc-sync.md`

## Absolute Rules

### Communication
1. Jake's provided contact info wins — never substitute CRM data
2. Jake uses DocuSeal (self-hosted) for NDAs — Template ID 1 is NCND-RRG
3. CC Jasmin on ALL emails: Jasmin@resourcerealtygroupmi.com

### Context Preservation
4. Jake's exact words — copy verbatim, never summarize unless >10 lines

### Pipeline Safety
5. Never approve signals without Jake's explicit approval
6. Never modify Windmill flows/scripts without reviewing current state first
7. Always verify WiseAgent OAuth token freshness before API calls
