# RRG-Server — Current State

## Verified February 14, 2026

This document reflects the **actual current state** of RRG-Server, verified by SSH inspection:
- `docker ps` for all running containers
- `ss -tlnp` for listening ports
- `tailscale status` for network peers
- `df -h` for disk usage
- Docker compose files read directly

---

## PHYSICAL INFRASTRUCTURE

### Hardware

| Spec | Value |
|------|-------|
| Model | Dell Inspiron 3880 |
| CPU | Intel i5-10400 @ 2.9GHz (6 cores, 12 threads) |
| RAM | 12GB |
| Disk | 98GB (LVM: ubuntu--vg-ubuntu--lv) |
| OS | Ubuntu 24.04.3 LTS |

### Network

| Interface | Address |
|-----------|---------|
| Local IP | 192.168.1.31 |
| Tailscale IP | 100.97.86.99 |
| WiFi | SpectrumSetup-E0 / ***REDACTED_WIFI_PASSWORD*** |

### SSH Access

```
ssh andrea@100.97.86.99
Password: ***REDACTED***
```

### Installed System Software

- Docker (containerd + docker.service)
- Nix 2.33.2 (daemon mode)
- Tailscale (tailscaled.service)

---

## DOCKER CONTAINERS (7 Running)

### jake-deploy stack (3 containers)

Compose file: `/home/andrea/jake-deploy/docker-compose.jake.yml`
Env file: `/home/andrea/jake-deploy/.env`
Network: `windmill_default` (external)

| Container | Image | Size | Port | Purpose |
|-----------|-------|------|------|---------|
| rrg-router | rrg-router:latest | 2.15GB | 0.0.0.0:8501 | Streamlit chat UI, routes to workers |
| rrg-pnl | rrg-pnl:latest | 1.55GB | 8100 (internal) | P&L analysis worker |
| rrg-brochure | rrg-brochure:latest | 4.91GB | 8101 (internal) | CRE brochure generator |

Environment variables (from .env):
- `CLAUDE_CODE_OAUTH_TOKEN` — Anthropic API access
- `CLAUDE_MODEL` — haiku (default)
- `USE_WINDMILL` — true
- `WINDMILL_BASE_URL` — http://windmill-windmill_server-1:8000
- `WINDMILL_TOKEN` — Windmill API token
- `WINDMILL_WORKSPACE` — rrg

Routing:
- rrg-router → rrg-pnl via `http://rrg-pnl:8100`
- rrg-router → rrg-brochure via `http://rrg-brochure:8101`
- rrg-router → windmill via `http://windmill-windmill_server-1:8000`

### Windmill stack (3 containers)

Compose file: `/home/andrea/windmill/docker-compose.yml`
Network: `windmill_default` (created by this stack)

| Container | Image | Size | Port | Purpose |
|-----------|-------|------|------|---------|
| windmill-windmill_server-1 | ghcr.io/windmill-labs/windmill:main | 5.18GB | 0.0.0.0:8000 | Workflow server |
| windmill-windmill_worker-1 | (same) | — | internal | Job executor |
| windmill-db-1 | postgres:16-alpine | 395MB | 5432 (internal) | Windmill database |

Windmill config:
- `DATABASE_URL` — postgres://postgres:***REDACTED***@db/windmill
- `BASE_URL` — http://100.97.86.99:8000
- Worker has Docker socket mounted for container-based jobs

### DocuSeal (1 container)

Compose file: `/home/andrea/docuseal/docker-compose.yml`
Network: default (bridge)

| Container | Image | Size | Port | Purpose |
|-----------|-------|------|------|---------|
| docuseal | docuseal-rrg:latest | 2.11GB | 0.0.0.0:3000 | NDA signing (custom build) |

DocuSeal config:
- `HOST` — rrg-server.tailc01f9b.ts.net
- `FORCE_SSL` — true
- `SECRET_KEY_BASE` — ***REDACTED_DOCUSEAL_KEY***
- SMTP: teamgotcher@gmail.com via smtp.gmail.com:587
- NDA Template ID: 1 (NCND-RRG)
- Admin URL: https://rrg-server.tailc01f9b.ts.net/

Customizations (4 files in `docuseal/customizations/`):
- `app/views/shared/_navbar.html.erb` — Custom navbar
- `app/controllers/start_form_controller.rb` — Custom start form
- `app/controllers/submit_form_controller.rb` — Custom submit form
- `config/initializers/frame_options.rb` — Frame embedding config

Source code: `/home/andrea/docuseal-src/` (forked from docusealco/docuseal, Ruby 4.0.1)

---

## TAILSCALE

### Funnel Configuration (Public HTTPS)

| Public URL | Proxies To |
|------------|-----------|
| https://rrg-server.tailc01f9b.ts.net | http://127.0.0.1:3000 (DocuSeal) |
| https://rrg-server.tailc01f9b.ts.net:8443 | http://localhost:8000 (Windmill) |

### Network Peers (as seen from RRG-Server)

| Machine | Tailscale IP | Status | Last Seen |
|---------|-------------|--------|-----------|
| rrg-server (self) | 100.97.86.99 | online | — |
| jacobs-macbook-air-2 | 100.108.74.112 | online, direct | — |
| pixel-9a | 100.125.176.16 | online | — |
| larrys-macbook-pro | 100.79.238.103 | online | — |

---

## LISTENING PORTS

| Port | Protocol | Bound To | Service |
|------|----------|----------|---------|
| 22 | TCP | 0.0.0.0 | SSH |
| 3000 | TCP | 0.0.0.0 | DocuSeal |
| 8000 | TCP | 0.0.0.0 | Windmill |
| 8501 | TCP | 0.0.0.0 | rrg-router |
| 443 | TCP | 100.97.86.99 | Tailscale Funnel (DocuSeal) |
| 8443 | TCP | 100.97.86.99 | Tailscale Funnel (Windmill) |
| 5432 | TCP | (container internal) | Postgres |

---

## DIRECTORY STRUCTURE

```
/home/andrea/
├── rrg-router/                     # Source + Nix flake
├── rrg-pnl/                        # Source + Nix flake
├── rrg-brochure/                   # Source + Nix flake
├── jake-deploy/                    # Docker compose for RRG apps
│   ├── docker-compose.jake.yml     # 3 containers: router, pnl, brochure
│   └── .env                        # Claude token, Windmill config
├── jake-images/                    # Docker image tarballs (SCP'd from Mac)
│   ├── rrg-pnl.tar.gz            # 261MB
│   └── rrg-router.tar.gz         # 323MB
├── windmill/                       # Docker compose for Windmill
│   └── docker-compose.yml          # 3 containers: server, worker, postgres
├── docuseal/                       # DocuSeal v2.3.2 — Nix flake + customizations
│   ├── flake.nix                   # Full Nix build pipeline (source → gems → assets → Docker)
│   ├── docker-compose.yml          # 1 container: docuseal-rrg
│   ├── customizations/             # 4 custom Ruby/ERB files
│   ├── Gemfile / Gemfile.lock      # Patched (no trilogy gem)
│   ├── gemset.nix                  # Generated by bundix — gem hashes for Nix
│   └── .git/                       # Local git repo (no remote)
```

---

## BUILD & DEPLOY PIPELINE

### RRG Apps (router, pnl, brochure)

```
Server: /home/andrea/rrg-router/    (rrg-router source + Nix flake)
Server: /home/andrea/rrg-pnl/       (rrg-pnl source + Nix flake)
Server: /home/andrea/rrg-brochure/  (rrg-brochure source + Nix flake)

1. ssh andrea@rrg-server
2. cd ~/rrg-router   (or rrg-pnl, rrg-brochure)
3. nix build && docker load < result
4. cd ~/jake-deploy && docker compose -f docker-compose.jake.yml up -d
```

### DocuSeal (custom)

```
Server: ~/docuseal/                 (Nix flake + customizations)

1. cd ~/docuseal
2. nix build && docker load < result
3. docker compose down && docker compose up -d
```

### Windmill

```
No build step — uses upstream image ghcr.io/windmill-labs/windmill:main
Workflows managed via Windmill UI or MCP API
```

---

## WINDMILL WORKFLOWS

Workspace: `rrg`
API: http://100.97.86.99:8000 (internal) or https://rrg-server.tailc01f9b.ts.net:8443 (public)

Known flows:
- `f/switchboard/lead_intake` — Process incoming CRE leads (6 modules, suspend/resume). See [`LEAD_INTAKE_PIPELINE.md`](LEAD_INTAKE_PIPELINE.md).
- `f/switchboard/lead_conversation` — Classify and respond to replies to CRE outreach (4 modules, suspend/resume). See [`LEAD_CONVERSATION_ENGINE.md`](LEAD_CONVERSATION_ENGINE.md).
- `f/switchboard/message_router` — Route chat messages to worker containers

Known scripts (all `f/switchboard/` despite being scripts, not flows):
- `f/switchboard/write_signal` — Create a new signal in jake_signals
- `f/switchboard/read_signals` — Read pending signals
- `f/switchboard/act_signal` — Mark signal as acted in Postgres (does not resume/cancel suspended flows)
- `f/switchboard/get_pending_draft_signals` — Query pending lead_intake signals with draft_id_map
- `f/switchboard/gmail_pubsub_webhook` — Gmail Pub/Sub push handler — split inbox: leads@ for notifications, teamgotcher@ for SENT/replies
- `f/switchboard/gmail_polling_trigger` — DEPRECATED: kept as emergency fallback, schedule disabled
- `f/switchboard/setup_gmail_watch` — Gmail SENT + INBOX label watch for teamgotcher@ (renew every 6 days)
- `f/switchboard/setup_gmail_leads_watch` — Gmail INBOX label watch for leads@ (renew every 6 days)
- `f/docuseal/nda_completed` — DocuSeal NDA completion webhook handler (uses `f/switchboard/wiseagent_oauth`)
- `f/switchboard/check_gmail_watch_health` — Daily health check: alerts via SMS if webhook hasn't run in 48h

Windmill schedules:
- `f/switchboard/gmail_polling_schedule` — DISABLED (was: every 1 min polling trigger, replaced by Pub/Sub push)
- `f/switchboard/schedule_gmail_watch_renewal` — cron `0 0 9 */6 * *` → `f/switchboard/setup_gmail_watch` (teamgotcher@)
- `f/switchboard/schedule_gmail_leads_watch_renewal` — cron `0 0 9 */6 * *` → `f/switchboard/setup_gmail_leads_watch` (leads@)
- `f/switchboard/gmail_watch_health_daily` — cron `0 0 10 * * *` → `f/switchboard/check_gmail_watch_health`

Windmill variables:
- `f/switchboard/property_mapping` — JSON property alias → canonical name mapping (with optional `documents` field per property)
- `f/switchboard/sms_gateway_url` — SMS gateway endpoint URL (Pixel 9a)
- `f/switchboard/gmail_last_history_id` — Gmail History API cursor for teamgotcher@
- `f/switchboard/gmail_leads_last_history_id` — Gmail History API cursor for leads@
- `f/switchboard/router_token` — Auth token for resume URL POSTs
- `f/switchboard/claude_endpoint_url` — Claude API proxy on jake-macbook (`http://100.108.74.112:8787`)

---

## GMAIL INTEGRATION (Split Inbox)

**Purpose:** Detect when lead intake/conversation drafts are sent (~2-5 seconds), categorize incoming lead notifications, and detect replies to outreach.

### Split Inbox Architecture

| Account | Purpose | OAuth Resource | History Variable |
|---------|---------|----------------|-----------------|
| `leads@resourcerealtygroupmi.com` | Receives lead notifications | `f/switchboard/gmail_leads_oauth` | `f/switchboard/gmail_leads_last_history_id` |
| `teamgotcher@gmail.com` | Sends drafts, receives replies | `f/switchboard/gmail_oauth` | `f/switchboard/gmail_last_history_id` |

### GCP Configuration

| Setting | Value |
|---------|-------|
| GCP Project | `rrg-gmail-automation` |
| Pub/Sub Topic | `projects/rrg-gmail-automation/topics/gmail-sent-notifications` |
| Push Subscription | → `https://rrg-server.tailc01f9b.ts.net:8443/api/w/rrg/webhooks/.../p/f/switchboard/gmail_pubsub_webhook` |
| Accounts | `teamgotcher@gmail.com` (SENT+INBOX), `leads@resourcerealtygroupmi.com` (INBOX) |
| Watch Expiry | ~7 days (renewed every 6 by `setup_gmail_watch` and `setup_gmail_leads_watch`) |
| Delivery | Pub/Sub push via Tailscale Funnel (~2-5 seconds) |

### How It Works

1. `setup_gmail_watch` tells Gmail to track teamgotcher@ changes on SENT + INBOX labels
2. `setup_gmail_leads_watch` tells Gmail to track leads@ changes on INBOX label
3. Both watches publish to the same Pub/Sub topic
4. Push subscription delivers notifications directly to `gmail_pubsub_webhook` (~2-5 seconds)
5. Webhook detects account from `emailAddress` in the push notification, uses correct OAuth + history cursor
6. **leads@ INBOX:** Categorizes by sender/subject, applies Gmail labels, parses leads, triggers `lead_intake` flow
7. **teamgotcher@ SENT:** Fetches `threadId`, searches `jake_signals` for matching thread_id via JSONB query, POSTs to `resume_url` to wake post-approval module
8. **teamgotcher@ INBOX (reply detection):** For "Unlabeled" emails, checks thread_id against acted signals. If match found, applies "Lead Reply" label and triggers `lead_conversation` flow

**Key design choice:** Gmail strips all custom `X-` headers when drafts are sent. Sent emails are matched to signals by **thread_id** (stable across draft→sent transitions), not headers.

---

## GMAIL APPS SCRIPT (DRAFT DELETION FALLBACK)

**Purpose:** Detect deleted drafts (lead rejections). Runs daily since deletion is low-priority.

| Setting | Value |
|---------|-------|
| Apps Script Project ID | `1xLmwzHJh0heGgoBBdWQMZJtuuY3bXRsiOpoeteY9fYJ-MuYouu6VVfcD` |
| Schedule | Daily at 9 AM (time-based trigger) |
| Auth | `WINDMILL_TOKEN` in Script Properties |
| Endpoint | Windmill API via Tailscale Funnel |

### How It Works

1. Calls `f/switchboard/get_pending_draft_signals` to get all pending signals with `draft_id_map`
2. For each draft ID: tries `Gmail.Users.Drafts.get()` — if the draft still exists, skips it
3. If draft not found: checks the thread for SENT messages
4. If SENT message found: POSTs to `resume_url` with `action: "email_sent"` (fallback for Pub/Sub miss)
5. If no SENT message: POSTs to `resume_url` with `action: "draft_deleted"` (Module F runs, writes CRM rejection note)

Also exposes a web app for remote triggering (`?action=run`, `?action=setup`, `?action=status`).

---

## DISK USAGE

**WARNING: 94% full (6.4GB free of 98GB)**

| Path | Size | Notes |
|------|------|-------|
| /var/lib/docker/ | 14GB | Docker images, volumes, layers |
| docuseal-src/ | 693MB | Full Ruby source + node_modules + vendor |
| jake-images/ | 584MB | Deployment tarballs |
| docuseal-source/ | 0MB | Empty, safe to delete |

Docker image sizes:
| Image | Size |
|-------|------|
| ghcr.io/windmill-labs/windmill:main | 5.18GB |
| rrg-brochure:latest | 4.91GB |
| docuseal-rrg:latest | 2.11GB |
| rrg-router:latest | 2.15GB |
| rrg-pnl:latest | 1.55GB |
| node:20 | 1.59GB |
| docuseal/docuseal:latest | 1.09GB |
| postgres:16-alpine | 395MB |
| node:20-slim | 291MB |
| alpine:latest | 13.1MB |

Unused images that could be cleaned:
- `node:20` and `node:20-slim` — likely build leftovers
- `docuseal/docuseal:latest` — upstream image, replaced by `docuseal-rrg:latest`
- `alpine:latest` — utility image

Docker volumes (some may be orphaned):
- `docuseal_data` — Active (DocuSeal data)
- `windmill_windmill_db` — Active (Postgres data)
- `windmill_worker_dependency_cache` — Active (Windmill worker cache)
- `docuseal_nix_data`, `docuseal_nix_test*` — Likely leftover from build experiments

---

## KNOWN ISSUES

1. **Disk 94% full** — Needs cleanup of unused Docker images and orphaned volumes
2. **No automated backups** — DocuSeal data and Windmill DB have no backup strategy
3. **Default SSH password** — `andrea:***REDACTED***` should be changed
4. ~~**rrg-brochure is 4.91GB**~~ — Accepted; Chromium + claude-code are required, works as-is
5. ~~**docuseal-source/ is empty**~~ — Deleted (was empty leftover)
6. **No monitoring** — No health checks or alerts if services go down

---

*Last verified: February 23, 2026*
*Source: Direct SSH inspection + dataflow analysis*
