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
Hopper architecture: webhook fires one flow per person (not one flow per batch).
6-module pipeline:
1. **WiseAgent Lookup + Create** — Search contacts by email; create new contacts immediately (logged to `contact_creation_log`)
2. **Property Match** — Match against `property_mapping` Windmill variable
3. **Dedup/Group** — Combine same-person multi-property notifications
4. **Generate Drafts + Gmail** — Create Gmail drafts, store thread_id for SENT matching (no custom headers — Gmail strips them)
5. **Approval Gate** — Suspend flow, write signal to `jake_signals` (stops cleanly if no drafts via `stop_after_if`)
6. **Post-Approval** — SMS first, then CRM note with accurate outcome; rejection notes on draft deletion

### Lead Conversation Flow (`f/switchboard/lead_conversation`)
Processes replies to CRE outreach (Crexi/LoopNet only). Triggered by `gmail_pubsub_webhook` when an unlabeled INBOX email's thread_id matches an acted `lead_intake` or `lead_conversation` signal. Full docs: `docs/LEAD_CONVERSATION_ENGINE.md`.

4-module pipeline:
1. **Classify Reply** — Fetch full Gmail thread, classify intent via Claude (haiku): INTERESTED (offer/want_something/general_interest), IGNORE, NOT_INTERESTED, ERROR
2. **Generate Response** — Terminal states (IGNORE/ERROR → CRM note, OFFER → notification signal) stop here. Actionable states create Gmail reply draft via Claude
3. **Approval Gate** — Same suspend pattern as lead_intake; draft_id_map stored for SENT matching
4. **Post-Approval** — CRM note + SMS after user sends/deletes draft

### WiseAgent CRM
- OAuth API: `sync.thewiseagent.com`
- Credentials: Windmill resource `f/switchboard/wiseagent_oauth` (auto-refreshed, shared with NDA handler)

### Signal System (Postgres `jake_signals` table)
- `s/switchboard/write_signal` — Create signal
- `s/switchboard/read_signals` — Read pending
- `s/switchboard/act_signal` — Approve/process
- `s/switchboard/get_pending_draft_signals` — Check draft signals

### Gmail Integration
- OAuth: `f/switchboard/gmail_oauth` (teamgotcher@gmail.com, GCP project `rrg-gmail-automation`)
- Polling: `f/switchboard/gmail_polling_trigger` — runs every 1 minute, checks historyId for changes, dispatches webhook async
- Webhook: `f/switchboard/gmail_pubsub_webhook` — handles SENT, INBOX, and reply detection
  - **SENT path:** Matches sent emails to signals by thread_id (JSONB query on `draft_id_map`), triggers Module F resume. Searches both `lead_intake` and `lead_conversation` signals.
  - **INBOX path (lead notifications):** Categorizes incoming emails, applies Gmail labels (Crexi/LoopNet/Realtor.com/Seller Hub/Unlabeled), parses lead notifications, triggers `f/switchboard/lead_intake`
  - **INBOX path (reply detection):** For "Unlabeled" emails, checks thread_id against acted signals to detect replies to our outreach. If match found, applies "Lead Reply" label and triggers `f/switchboard/lead_conversation`
- Watch: `f/switchboard/setup_gmail_watch` — watches SENT + INBOX labels, renews every 6 days
- Health: `f/switchboard/check_gmail_watch_health` — daily 10 AM ET, SMS alert if webhook stale >48h
- GCP: topic `gmail-sent-notifications` in project `rrg-gmail-automation` (TeamGotcher)
- Note: Pub/Sub push can't reach Windmill (behind Tailscale), so polling replaces push delivery

### Message Router (`f/switchboard/message_router`)
- Routes to rrg-pnl (port 8100) or rrg-brochure (port 8101)

### DocuSeal NDAs
- Webhook: `s/docuseal/nda_completed` (Bun/JS)
- Template ID 1 = NCND-RRG
- Self-hosted on rrg-server port 3000

### Windmill Resources
| Resource | Purpose |
|----------|---------|
| `f/switchboard/wiseagent_oauth` | WiseAgent OAuth tokens (auto-refreshed, includes client_id/secret for refresh) |
| `f/switchboard/gmail_oauth` | Gmail OAuth for teamgotcher@gmail.com (GCP: rrg-gmail-automation) |
| `f/switchboard/pg` | Postgres connection (jake_signals table) |
| `f/switchboard/tailscale_machines` | Network configs + SSH passwords |

### Windmill Variables
| Variable | Purpose |
|----------|---------|
| `f/switchboard/property_mapping` | Property alias-to-deal mapping (JSON, 21 properties). Supports optional `documents` field per property for file paths. |
| `f/switchboard/gmail_last_history_id` | Last processed Gmail history ID for webhook |
| `f/switchboard/sms_gateway_url` | Pixel 9a SMS gateway endpoint |
| `f/switchboard/claude_endpoint_url` | Claude API proxy on jake-macbook (port 8787) |
| `f/switchboard/router_token` | Windmill API token (secret) |

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
| `docs/LEAD_INTAKE_PIPELINE.md` | Lead intake flow detail (6 modules, resume mechanism) |
| `docs/LEAD_CONVERSATION_ENGINE.md` | Lead conversation engine detail (4 modules, intent classification) |

## Reference Files
- Network/IPs/ports → `.claude/rules/network.md`
- Email rules → `.claude/rules/email.md`
- Doc-sync enforcement → `.claude/rules/doc-sync.md`

## Absolute Rules

### Communication
1. Jake's provided contact info wins — never substitute CRM data
2. Jake uses DocuSeal (self-hosted) for NDAs — Template ID 1 is NCND-RRG

### Context Preservation
3. Jake's exact words — copy verbatim, never summarize unless >10 lines

### Pipeline Safety
4. Never approve signals without Jake's explicit approval
5. Never modify Windmill flows/scripts without reviewing current state first
6. Always verify WiseAgent OAuth token freshness before API calls
