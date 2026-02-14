# RRG-Server Architecture

This document provides visual diagrams of the RRG-Server infrastructure across three layers.

> **Verified:** February 14, 2026 via SSH inspection of running system.
> **Relationship:** Loosely based on [jake-assistant-system](https://github.com/BeastofOne/jake-assistant-system/blob/main/docs/ARCHITECTURE.md) architecture.

---

## Layer 1: Physical Infrastructure

The hardware and network topology connecting all devices.

```mermaid
%%{init: {'theme': 'base', 'themeVariables': { 'primaryColor': '#e1f5fe', 'primaryTextColor': '#01579b', 'primaryBorderColor': '#0288d1', 'lineColor': '#0288d1'}}}%%

graph TB
    subgraph OFFICE["RRG OFFICE (192.168.1.x)"]
        INTERNET["INTERNET"]

        ROUTER["Office Router<br/>WiFi: SpectrumSetup-E0"]

        subgraph SERVER["RRG-SERVER (Always On)"]
            SERVER_INFO["Dell Inspiron 3880<br/>i5-10400 @ 2.9GHz (12 threads) | 12GB RAM<br/>98GB disk | Ubuntu 24.04.3 LTS"]
            SERVER_LOCAL["Local: 192.168.1.31"]
            SERVER_TS["Tailscale: 100.97.86.99"]
        end

        INTERNET <--> ROUTER
        ROUTER <--> SERVER
    end

    subgraph TAILSCALE["TAILSCALE MESH OVERLAY (BeastofOne@)"]

        subgraph TS_MAC["JAKE'S MAC"]
            MAC_INFO["MacBook Air 2020 Intel<br/>i5 @ 1.1GHz | 16GB RAM<br/>macOS Sequoia"]
            MAC_TS["100.108.74.112"]
        end

        subgraph TS_RRG["RRG-SERVER"]
            TS_RRG_IP["100.97.86.99"]
        end

        subgraph TS_LARRY["LARRY'S MACBOOK"]
            LARRY_INFO["MacBook Pro<br/>SMS Gateway host"]
            LARRY_TS["100.79.238.103"]
        end
    end

    subgraph OFFLINE["OFFLINE DEVICES"]
        JAKE_SERVER["jake-server<br/>100.87.241.99<br/>OFFLINE 9+ days"]
        PHONE["Samsung Galaxy S22<br/>100.118.198.116<br/>OFFLINE 9+ days"]
    end

    MAC_TS <-.->|"WireGuard<br/>SSH, HTTP"| TS_RRG_IP
    TS_RRG_IP <-.->|"WireGuard"| LARRY_TS
```

### Key Points
- **RRG-Server** is at the RRG office (not Jake's home)
- **jake-server** (Dell Latitude at home) is offline/paused — not part of this system
- **Larry's MacBook** hosts the SMS Gateway (replaced the Samsung phone)
- All inter-device communication uses **Tailscale IPs** (100.x.x.x)
- SSH access: `ssh andrea@100.97.86.99` (password: password)

---

## Layer 2: Service Topology

All services running on each device and their connections.

```mermaid
%%{init: {'theme': 'base', 'themeVariables': { 'primaryColor': '#e8f5e9', 'primaryTextColor': '#1b5e20', 'primaryBorderColor': '#43a047'}}}%%

graph TB
    subgraph MAC["JAKE'S MAC (100.108.74.112)"]
        subgraph MAC_SERVICES["Services"]
            CLAUDE_CLI["Claude Code CLI<br/>(Interactive terminal)"]
            CLAUDE_ENDPOINT["Claude Endpoint<br/>:8787 (pm2)"]
        end

        subgraph MAC_SOURCE["Source Code (apps/)"]
            SRC_ROUTER["jake-assistant/<br/>(jake-router source)"]
            SRC_PNL["jake-pnl/<br/>(P&L source)"]
            SRC_BROCHURE["jake-brochure/<br/>(Brochure source)"]
        end

        subgraph MCP_SERVERS["MCP Servers"]
            MCP_HUBSPOT["HubSpot MCP"]
            MCP_WINDMILL["Windmill MCP"]
        end
    end

    subgraph RRG["RRG-SERVER (100.97.86.99)"]
        subgraph DOCKER["Docker Containers"]

            subgraph JAKE_APPS["Jake Apps (jake-deploy/)"]
                ROUTER["jake-router<br/>:8501 (public)<br/>Streamlit chat UI"]
                PNL["jake-pnl<br/>:8100 (internal)<br/>P&L worker"]
                BROCHURE["jake-brochure<br/>:8101 (internal)<br/>Brochure worker"]
            end

            subgraph DOCUSEAL_STACK["DocuSeal (docuseal/)"]
                DOCUSEAL["docuseal<br/>:3000 (public + Funnel)<br/>Custom-built from source"]
            end

            subgraph WINDMILL_STACK["Windmill (windmill/)"]
                WM_SERVER["windmill-server<br/>:8000 (public + Funnel)"]
                WM_WORKER["windmill-worker<br/>(internal)"]
                WM_DB["postgres:16-alpine<br/>:5432 (internal)"]
            end
        end

        subgraph FUNNEL["Tailscale Funnel (Public HTTPS)"]
            FUNNEL_DS["rrg-server.tailc01f9b.ts.net<br/>→ :3000 (DocuSeal)"]
            FUNNEL_WM["rrg-server.tailc01f9b.ts.net:8443<br/>→ :8000 (Windmill)"]
        end
    end

    subgraph LARRY["LARRY'S MAC (100.79.238.103)"]
        SMS_GW["SMS Gateway<br/>:8080"]
    end

    subgraph CLOUD["CLOUD SERVICES"]
        HUBSPOT_API["HubSpot API"]
        GMAIL_SMTP["Gmail SMTP<br/>(teamgotcher@gmail.com)"]
        CLAUDE_API["Anthropic API"]
    end

    %% Build pipeline
    SRC_ROUTER -.->|"nix build → tarball → SCP"| ROUTER
    SRC_PNL -.->|"nix build → tarball → SCP"| PNL
    SRC_BROCHURE -.->|"nix build → tarball → SCP"| BROCHURE

    %% Claude CLI connections
    CLAUDE_CLI <--> MCP_HUBSPOT
    CLAUDE_CLI <--> MCP_WINDMILL

    %% MCP to services
    MCP_HUBSPOT <-->|"REST API"| HUBSPOT_API
    MCP_WINDMILL <-->|"HTTP :8000"| WM_SERVER

    %% Inter-container (windmill_default network)
    ROUTER -->|"HTTP :8100"| PNL
    ROUTER -->|"HTTP :8101"| BROCHURE
    ROUTER -->|"HTTP :8000"| WM_SERVER

    %% All jake apps use Claude API
    ROUTER -->|"OAuth token"| CLAUDE_API
    PNL -->|"OAuth token"| CLAUDE_API
    BROCHURE -->|"OAuth token"| CLAUDE_API

    %% DocuSeal
    DOCUSEAL -->|"SMTP"| GMAIL_SMTP

    %% Windmill
    WM_SERVER --> WM_DB
    WM_WORKER --> WM_DB
```

### Key Points
- **All jake apps share the `windmill_default` Docker network** to communicate
- **jake-router** is the entry point — routes chat messages to pnl/brochure workers
- **Source code lives on Mac**, images are built with Nix flakes, shipped as tarballs via SCP
- **DocuSeal source lives on the server** (`docuseal-src/`) — custom fork with RRG modifications
- **Windmill workflows live in Windmill's Postgres DB** — managed via Windmill UI or MCP
- **Tailscale Funnel** exposes DocuSeal (:443) and Windmill (:8443) publicly

---

## Layer 3: Application Workflows

The business logic — how services interact to accomplish tasks.

```mermaid
%%{init: {'theme': 'base', 'themeVariables': { 'primaryColor': '#fff3e0', 'primaryTextColor': '#e65100', 'primaryBorderColor': '#fb8c00'}}}%%

graph TB
    subgraph TRIGGERS["TRIGGERS"]
        T1["Jake opens chat UI<br/>(rrg-server:8501)"]
        T2["Jake sends NDA<br/>(via Claude Code)"]
        T3["Recipient signs NDA<br/>(DocuSeal)"]
        T4["Windmill scheduled job<br/>or manual trigger"]
    end

    subgraph CHAT_FLOW["CHAT FLOW (jake-router)"]
        ROUTER_IN["jake-router receives message"]
        ROUTE_DECIDE{"Route by target_node"}
        PNL_WORKER["jake-pnl<br/>P&L analysis"]
        BROCHURE_WORKER["jake-brochure<br/>Brochure generation"]
        WM_FLOW["Windmill flow<br/>(message_router)"]
    end

    subgraph NDA_FLOW["NDA FLOW"]
        NDA_SEND["DocuSeal creates submission<br/>from Template ID 1 (NCND-RRG)"]
        NDA_EMAIL["Signing link emailed<br/>via teamgotcher@gmail.com"]
        NDA_SIGN["Recipient signs"]
        NDA_COMPLETE["DocuSeal fires webhook"]
    end

    subgraph WINDMILL_FLOWS["WINDMILL SWITCHBOARD"]
        WM_LEAD["f/switchboard/lead_intake"]
        WM_SIGNAL_W["s/switchboard/write_signal"]
        WM_SIGNAL_R["s/switchboard/read_signals"]
        WM_SIGNAL_A["s/switchboard/act_signal"]
        WM_GMAIL["s/switchboard/gmail_pubsub_webhook"]
    end

    subgraph ENDPOINTS["EXTERNAL"]
        HUBSPOT["HubSpot CRM"]
        CLAUDE["Anthropic API"]
    end

    %% Chat flow
    T1 --> ROUTER_IN
    ROUTER_IN --> ROUTE_DECIDE
    ROUTE_DECIDE -->|"pnl"| PNL_WORKER
    ROUTE_DECIDE -->|"brochure"| BROCHURE_WORKER
    ROUTE_DECIDE -->|"windmill"| WM_FLOW
    PNL_WORKER --> CLAUDE
    BROCHURE_WORKER --> CLAUDE

    %% NDA flow
    T2 --> NDA_SEND
    NDA_SEND --> NDA_EMAIL
    NDA_EMAIL --> NDA_SIGN
    NDA_SIGN --> NDA_COMPLETE
    NDA_COMPLETE --> HUBSPOT

    %% Windmill
    T4 --> WM_LEAD
    WM_LEAD --> HUBSPOT
    WM_SIGNAL_W --> WM_SIGNAL_R
    WM_SIGNAL_R --> WM_SIGNAL_A

    T3 --> NDA_COMPLETE
```

### Key Points
- **Chat flow** is the primary user-facing feature: Jake talks to jake-router, which delegates to specialized workers
- **NDA flow** is self-contained: DocuSeal handles the full signing lifecycle
- **Windmill switchboard** handles background automation (lead intake, signal processing, Gmail webhooks)
- **No n8n on RRG-Server** — that was jake-server only
- **No Inbox Zero on RRG-Server** — that was jake-server only

---

## Quick Reference

### Network

| Device | Tailscale IP | Location | Status |
|--------|-------------|----------|--------|
| rrg-server | 100.97.86.99 | RRG Office | **Online** |
| jake-macbook | 100.108.74.112 | Mobile | **Online** |
| larrys-macbook | 100.79.238.103 | Mobile | **Online** |
| jake-server | 100.87.241.99 | Jake's Home | Offline (paused) |
| samsung-phone | 100.118.198.116 | — | Offline |

### Ports (RRG-Server)

| Port | Service | Exposure |
|------|---------|----------|
| 22 | SSH | Tailscale |
| 3000 | DocuSeal | Tailscale + Funnel (public HTTPS) |
| 5432 | Postgres (Windmill) | Internal only |
| 8000 | Windmill Server | Tailscale + Funnel (:8443 public HTTPS) |
| 8100 | jake-pnl | Internal (Docker network) |
| 8101 | jake-brochure | Internal (Docker network) |
| 8501 | jake-router | Tailscale |

### Docker Compose Files

| File | Manages | Location on Server |
|------|---------|-------------------|
| `jake-deploy/docker-compose.jake.yml` | jake-router, jake-pnl, jake-brochure | `/home/andrea/jake-deploy/` |
| `windmill/docker-compose.yml` | windmill-server, windmill-worker, postgres | `/home/andrea/windmill/` |
| `docuseal/docker-compose.yml` | docuseal (custom image) | `/home/andrea/docuseal/` |

### Source Code Locations

| Component | Source | Build | Deploy |
|-----------|--------|-------|--------|
| jake-router | Mac: `apps/jake-assistant/` | `nix build` → `.tar.gz` | SCP to server, `docker load` |
| jake-pnl | Mac: `apps/jake-pnl/` | `nix build` → `.tar.gz` | SCP to server, `docker load` |
| jake-brochure | Mac: `apps/jake-brochure/` | `nix build` → `.tar.gz` | SCP to server, `docker load` |
| DocuSeal (custom) | Server: `docuseal-src/` | `docker build` on server | Local image `docuseal-rrg:latest` |
| Windmill workflows | Windmill DB | Windmill UI/API | In-database |
| Deploy configs | Server: `jake-deploy/`, `windmill/`, `docuseal/` | N/A | `docker compose up -d` |

### Credentials

All credentials in `~/.secrets/jake-system.json` on Mac. Key ones for RRG-Server:

| What | Where to Find |
|------|---------------|
| SSH password | `tailscale.machines.rrg-server.ssh_users.andrea.password` |
| Windmill token | `windmill.api_token` |
| DocuSeal API key | `docuseal.api_key` |
| Claude OAuth token | `anthropic.claude_code_oauth_token` |
| DocuSeal SMTP | `docuseal.smtp` |
| WiFi password | artifact_8 |

### Disk Warning

As of Feb 14, 2026: **94% full (6.4GB free)**. Largest consumers:
- Docker images/data: ~14GB in `/var/lib/docker/`
- `docuseal-src/`: 693MB (full Ruby source + node_modules)
- `jake-images/`: 584MB (deployment tarballs)

---

## What's NOT on RRG-Server (vs. jake-server)

These services ran on jake-server and are **not deployed** on RRG-Server:

| Service | Was On jake-server | Status |
|---------|-------------------|--------|
| n8n | :5678, 8 workflows | Not on RRG-Server |
| Inbox Zero | :3001 web, :5432 postgres, :redis | Not on RRG-Server |
| Inbox API | :3002, SQLite event queue | Not on RRG-Server |
| Pi-Hole | :53 DNS, :80 admin | Not on RRG-Server |
| LLM Intercept | n8n workflow → Claude Endpoint | Not on RRG-Server |
| SMS integration | n8n workflows for send/receive | Not on RRG-Server |
| Email automation | n8n Send Email workflow | Not on RRG-Server |

---

*Last verified: February 14, 2026*
*Source: Direct SSH inspection of running system*
