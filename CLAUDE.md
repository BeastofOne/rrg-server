# RRG Server — CRE Workspace

## Overview

Jake's CRE business infrastructure. Five projects, one monorepo:

```
rrg-server/
├── rrg-router/            # Streamlit chat UI + intent router (port 8501)
├── rrg-pnl/              # P&L analysis (LangGraph + Flask, port 8100)
├── rrg-brochure/          # Property brochure generator (LangGraph + Flask, port 8101)
├── rrg-claude-endpoint/   # Claude API proxy (Node.js + pm2, port 8787)
├── rrg-email-assistant/   # Email automation (MCP tools, no server)
├── docs/                  # Architecture diagrams, current state
└── .claude/               # Rules, skills, hooks
```

## System Architecture

**Four machines on Tailscale** (details → `.claude/rules/network.md`):
- **jake-macbook** — Claude Code, claude-endpoint (pm2)
- **rrg-server** — Docker containers (pnl, brochure), Windmill, Postgres, DocuSeal
- **pixel-9a** — SMS gateway for Crexi/LoopNet leads (Termux + Flask, port 8686)
- **larry-sms-gateway** — iMessage relay

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

### rrg-router/ — Streamlit Chat UI + Intent Router
| File | What it does | Key exports |
|------|-------------|-------------|
| `app.py` | Streamlit UI — chat, signals tab, debug panel | — |
| `graph.py` | LangGraph intent classifier (routes to pnl/brochure/chat) | `build_graph()` |
| `config.py` | Worker URLs, Windmill settings, intent definitions | `WORKER_URLS`, `INTENTS` |
| `node_client.py` | HTTP client for direct worker calls | `WorkerNodeClient` class |
| `windmill_client.py` | HTTP client for Windmill message_router flow | `WindmillClient` class |
| `signal_client.py` | HTTP client for signal queue (read/act/resume) | `SignalClient` class |
| `claude_llm.py` | LangChain wrapper around `claude -p` CLI | `ChatClaudeCLI` class |
| `state.py` | LangGraph state TypedDict | `RouterState` |

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
- Pub/Sub: `f/switchboard/gmail_pubsub_webhook` — handles both SENT and INBOX
  - **SENT path:** Detects lead intake drafts being sent, triggers Module F resume
  - **INBOX path:** Categorizes ALL incoming emails, applies Gmail labels (Crexi/LoopNet/Realtor.com/Seller Hub/Unlabeled), parses lead notifications, triggers `f/switchboard/lead_intake`
- Watch: `f/switchboard/setup_gmail_watch` — watches SENT + INBOX labels, renews every 6 days
- GCP: topic `gmail-sent-notifications` in project `rrg-gmail-automation` (TeamGotcher)

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

### Source Location

Service source code lives on **rrg-server** (not jake-macbook):

```
/home/andrea/
├── rrg-brochure/      # Source + Nix flake
├── rrg-router/        # Source + Nix flake
├── rrg-pnl/           # Source + Nix flake
├── docuseal/          # DocuSeal Nix flake + customizations
├── jake-deploy/       # docker-compose + .env (unchanged)
└── windmill/          # docker-compose (unchanged)
```

Local `rrg-*/` directories on jake-macbook contain only `CLAUDE.md` (no source code).

### rrg-pnl / rrg-brochure / rrg-router (Nix → Docker → rrg-server)
```bash
# SSH to rrg-server via Tailscale
ssh andrea@rrg-server

# Build and load Docker image
cd ~/rrg-pnl  # or ~/rrg-brochure, ~/rrg-router
nix build && docker load < result

# Restart containers
cd ~/jake-deploy && docker compose -f docker-compose.jake.yml up -d
```
Env vars from `jake-deploy/.env`: `CLAUDE_CODE_OAUTH_TOKEN`, `CLAUDE_MODEL`

### DocuSeal (Nix → Docker → rrg-server)
DocuSeal v2.3.2 built from upstream source with 5 RRG customizations (auto-submit URL params, prefill fields, custom navbar, iframe embedding, no trilogy gem).

```bash
ssh andrea@rrg-server
cd ~/docuseal

# Rebuild image
nix build && docker load < result

# Restart
docker compose down && docker compose up -d
```

**Directory structure** (`~/docuseal/`):
| File | Purpose |
|------|---------|
| `flake.nix` | Full Nix build pipeline (source → gems → assets → Docker) |
| `Gemfile` / `Gemfile.lock` | Patched (no trilogy gem) |
| `gemset.nix` | Generated by `bundix` — gem hashes for Nix |
| `customizations/` | 4 RRG overlay files (controllers, navbar, frame_options) |
| `docker-compose.yml` | Runtime config (ports, volumes, SMTP, env) |

**Version bump workflow:**
1. Update `fetchFromGitHub` rev/hash in `flake.nix`
2. `bundle lock` → update `Gemfile.lock`
3. `bundix -l` → regenerate `gemset.nix`
4. Verify customization files still apply
5. `nix build && docker load < result && docker compose down && docker compose up -d`

### rrg-claude-endpoint (pm2 on jake-macbook)
```bash
pm2 start server.js --name claude-endpoint
pm2 restart claude-endpoint
pm2 logs claude-endpoint
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
