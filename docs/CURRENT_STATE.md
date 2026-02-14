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
| jake-router | jake-router:latest | 2.15GB | 0.0.0.0:8501 | Streamlit chat UI, routes to workers |
| jake-pnl | jake-pnl:latest | 1.55GB | 8100 (internal) | P&L analysis worker |
| jake-brochure | jake-brochure:latest | 4.91GB | 8101 (internal) | CRE brochure generator |

Environment variables (from .env):
- `CLAUDE_CODE_OAUTH_TOKEN` — Anthropic API access
- `CLAUDE_MODEL` — haiku (default)
- `USE_WINDMILL` — true
- `WINDMILL_BASE_URL` — http://windmill-windmill_server-1:8000
- `WINDMILL_TOKEN` — Windmill API token
- `WINDMILL_WORKSPACE` — rrg

Routing:
- jake-router → jake-pnl via `http://jake-pnl:8100`
- jake-router → jake-brochure via `http://jake-brochure:8101`
- jake-router → windmill via `http://windmill-windmill_server-1:8000`

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
| larrys-macbook-pro | 100.79.238.103 | online | — |

---

## LISTENING PORTS

| Port | Protocol | Bound To | Service |
|------|----------|----------|---------|
| 22 | TCP | 0.0.0.0 | SSH |
| 3000 | TCP | 0.0.0.0 | DocuSeal |
| 8000 | TCP | 0.0.0.0 | Windmill |
| 8501 | TCP | 0.0.0.0 | jake-router |
| 443 | TCP | 100.97.86.99 | Tailscale Funnel (DocuSeal) |
| 8443 | TCP | 100.97.86.99 | Tailscale Funnel (Windmill) |
| 5432 | TCP | (container internal) | Postgres |

---

## DIRECTORY STRUCTURE

```
/home/andrea/
├── jake-deploy/                    # Docker compose for jake apps
│   ├── docker-compose.jake.yml     # 3 containers: router, pnl, brochure
│   └── .env                        # Claude token, Windmill config
├── jake-images/                    # Docker image tarballs (SCP'd from Mac)
│   ├── jake-pnl.tar.gz            # 261MB
│   └── jake-router.tar.gz         # 323MB
├── windmill/                       # Docker compose for Windmill
│   └── docker-compose.yml          # 3 containers: server, worker, postgres
├── docuseal/                       # Docker compose + customizations for DocuSeal
│   ├── docker-compose.yml          # 1 container: docuseal-rrg
│   ├── customizations/             # 4 custom Ruby/ERB files
│   ├── flake.nix                   # Nix flake (for building custom image)
│   └── .git/                       # Local git repo (no remote)
├── docuseal-src/                   # Full DocuSeal Ruby source (custom fork)
│   ├── Dockerfile                  # For building docuseal-rrg image
│   ├── Gemfile                     # Ruby 4.0.1
│   └── .git/                       # Origin: docusealco/docuseal.git
└── docuseal-source/                # Empty directory (leftover, safe to delete)
```

---

## BUILD & DEPLOY PIPELINE

### Jake Apps (router, pnl, brochure)

```
Mac: ~/Desktop/apps/jake-assistant/     (jake-router source)
Mac: ~/Desktop/apps/jake-pnl/           (jake-pnl source)
Mac: ~/Desktop/apps/jake-brochure/      (jake-brochure source)

1. nix build .#docker           → result (Docker image tarball)
2. scp result andrea@100.97.86.99:~/jake-images/jake-router.tar.gz
3. ssh andrea@100.97.86.99
4. docker load < ~/jake-images/jake-router.tar.gz
5. cd ~/jake-deploy && docker compose -f docker-compose.jake.yml up -d
```

### DocuSeal (custom)

```
Server: ~/docuseal-src/             (forked source with customizations)

1. cd ~/docuseal-src
2. docker build -t docuseal-rrg .
3. cd ~/docuseal && docker compose up -d
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
- `f/switchboard/message_router` — Route chat messages to worker containers

Known scripts (all `f/switchboard/` despite being scripts, not flows):
- `f/switchboard/write_signal` — Create a new signal in jake_signals
- `f/switchboard/read_signals` — Read pending signals
- `f/switchboard/act_signal` — Mark signal as acted in Postgres (does not resume/cancel suspended flows)
- `f/switchboard/get_pending_draft_signals` — Query pending lead_intake signals with draft_id_map
- `f/switchboard/gmail_pubsub_webhook` — Gmail Pub/Sub push notification handler (real-time sent detection)
- `f/switchboard/setup_gmail_watch` — Gmail SENT label watch setup (renew every 6 days)
- `s/docuseal_nda/completed` — DocuSeal NDA completion webhook handler

Windmill variables:
- `f/switchboard/property_mapping` — JSON property alias → canonical name mapping
- `f/switchboard/sms_gateway_url` — SMS gateway endpoint URL
- `f/switchboard/gmail_last_history_id` — Gmail History API cursor (last processed history ID)
- `f/switchboard/router_token` — Auth token for resume URL POSTs

---

## GMAIL PUB/SUB INTEGRATION

**Purpose:** Real-time detection (~2 seconds) when a lead intake draft is sent from Gmail.

### GCP Configuration

| Setting | Value |
|---------|-------|
| GCP Project | `rrg-gmail-automation` |
| Pub/Sub Topic | `projects/rrg-gmail-automation/topics/gmail-sent-notifications` |
| Push Subscription Endpoint | `https://rrg-server.tailc01f9b.ts.net:8443/api/w/rrg/webhooks/{TOKEN}/p/f/switchboard/gmail_pubsub_webhook` |
| Gmail Account | `teamgotcher@gmail.com` |
| Labels Watched | `SENT` |
| Watch Expiry | ~7 days (renewed every 6 by `setup_gmail_watch`) |

### How It Works

1. `setup_gmail_watch` calls `users().watch()` on the SENT label, publishing to the GCP topic
2. When any email is sent from `teamgotcher@gmail.com`, Gmail pushes `{emailAddress, historyId}` to the topic
3. The push subscription delivers the notification (as a base64-encoded JSON inside a Pub/Sub envelope) to the Windmill webhook URL
4. `gmail_pubsub_webhook` decodes the notification, queries Gmail History API for changes since the last stored history ID, checks each new SENT message for `X-Lead-Intake-*` headers
5. If headers found: looks up the matching signal in `jake_signals` and POSTs to its `resume_url` to wake Module F

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
4. If SENT message found: POSTs to `resume_url` (fallback for Pub/Sub miss)
5. If no SENT message: POSTs to `cancel_url` (draft was deleted — flow cancelled, Module F never runs)

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
| jake-brochure:latest | 4.91GB |
| docuseal-rrg:latest | 2.11GB |
| jake-router:latest | 2.15GB |
| jake-pnl:latest | 1.55GB |
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
4. **jake-brochure is 4.91GB** — Largest container, may include unnecessary dependencies
5. **docuseal-source/ is empty** — Leftover directory, can be deleted
6. **No monitoring** — No health checks or alerts if services go down

---

*Last verified: February 14, 2026*
*Source: Direct SSH inspection of running system*
