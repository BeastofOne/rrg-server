# RRG-Server Architecture

This document provides visual diagrams of the RRG-Server infrastructure across three layers.

> **Verified:** February 14, 2026 via SSH inspection of running system.

---

## Layer 1: Physical Infrastructure

The hardware and network topology connecting all devices.

```mermaid
%%{init: {'theme': 'base', 'themeVariables': { 'primaryColor': '#e1f5fe', 'primaryTextColor': '#01579b', 'primaryBorderColor': '#0288d1', 'lineColor': '#0288d1'}}}%%

graph TB
    subgraph NETWORK["TAILSCALE MESH (BeastofOne@tailc01f9b.ts.net)"]
        direction TB

        subgraph OFFICE["RRG OFFICE"]
            RRG["<b>rrg-server</b><br/>Dell Inspiron 3880<br/>Ubuntu 24.04.3 LTS<br/>100.97.86.99"]
        end

        subgraph MOBILE["MOBILE"]
            MAC["<b>jake-macbook</b><br/>MacBook Air 2020<br/>macOS Sequoia<br/>100.108.74.112"]
            LARRY["<b>larrys-macbook</b><br/>MacBook Pro<br/>100.79.238.103"]
        end
    end

    subgraph PUBLIC["PUBLIC INTERNET"]
        FUNNEL_DS["https://rrg-server.tailc01f9b.ts.net<br/>→ DocuSeal"]
        FUNNEL_WM["https://rrg-server.tailc01f9b.ts.net:8443<br/>→ Windmill"]
    end

    %% Active Tailscale connections
    MAC <-->|"SSH, HTTP"| RRG
    MAC <-->|"SSH"| LARRY
    RRG <-->|"HTTP :8080"| LARRY

    %% Tailscale Funnel
    FUNNEL_DS -->|":443 → :3000"| RRG
    FUNNEL_WM -->|":8443 → :8000"| RRG

    %% Styling
    style PUBLIC fill:#fff8e1,stroke:#ffb300
```

### Key Points
- **RRG-Server** is at the RRG office, always on
- **Pixel 9a** (at the office) handles SMS for Crexi/LoopNet leads
- All inter-device communication uses **Tailscale IPs** (100.x.x.x)

---

## Layer 2: Service Topology

All services running on each device and their connections.

```mermaid
%%{init: {'theme': 'base', 'themeVariables': { 'primaryColor': '#e8f5e9', 'primaryTextColor': '#1b5e20', 'primaryBorderColor': '#43a047', 'lineColor': '#43a047'}}}%%

graph TB
    subgraph RRG["RRG-SERVER (100.97.86.99)"]
        direction TB

        subgraph FUNNEL["Tailscale Funnel — Public HTTPS"]
            F_DS["rrg-server.tailc01f9b.ts.net<br/>→ DocuSeal :3000"]
            F_WM["rrg-server.tailc01f9b.ts.net:8443<br/>→ Windmill :8000"]
        end

        subgraph JAKE_APPS["jake-deploy (docker-compose.jake.yml)"]
            ROUTER["<b>rrg-router</b><br/>:8501 — Streamlit chat UI"]
            PNL["<b>rrg-pnl</b><br/>:8100 — P&L worker"]
            BROCHURE["<b>rrg-brochure</b><br/>:8101 — Brochure worker"]
        end

        subgraph WM_STACK["windmill (docker-compose.yml)"]
            WM_SERVER["<b>windmill-server</b><br/>:8000 — Workflow engine"]
            WM_WORKER["<b>windmill-worker</b><br/>Job executor"]
            WM_DB["<b>postgres</b><br/>:5432 — Windmill DB"]
        end

        subgraph DS_STACK["docuseal (docker-compose.yml)"]
            DOCUSEAL["<b>docuseal</b><br/>:3000 — NDA signing"]
        end
    end

    subgraph MAC["JAKE'S MAC (100.108.74.112)"]
        CLAUDE_CLI["<b>Claude Code</b><br/>Interactive terminal"]
        MCP_HS["HubSpot MCP"]
        MCP_WM["Windmill MCP"]
    end

    subgraph PIXEL["PIXEL 9A (100.125.176.16)"]
        SMS_GW["<b>SMS Gateway</b><br/>:8686 (Termux + Flask)"]
    end

    subgraph CLOUD["CLOUD SERVICES"]
        HUBSPOT["HubSpot API"]
        WISEAGENT["WiseAgent API"]
        GMAIL["Gmail API"]
        ANTHROPIC["Anthropic API"]
    end

    %% Funnel routing
    F_DS --> DOCUSEAL
    F_WM --> WM_SERVER

    %% Jake apps internal routing
    ROUTER --> PNL
    ROUTER --> BROCHURE
    ROUTER --> WM_SERVER

    %% All RRG apps → Anthropic
    ROUTER --> ANTHROPIC
    PNL --> ANTHROPIC
    BROCHURE --> ANTHROPIC

    %% Windmill internals
    WM_SERVER --> WM_DB
    WM_WORKER --> WM_DB

    %% DocuSeal → Gmail
    DOCUSEAL --> GMAIL

    %% Windmill → external APIs
    WM_WORKER -->|"lead flows"| WISEAGENT
    WM_WORKER -->|"Gmail API"| GMAIL

    %% Claude CLI MCP connections
    CLAUDE_CLI --> MCP_HS
    CLAUDE_CLI --> MCP_WM
    MCP_HS --> HUBSPOT
    MCP_WM -->|"via Tailscale"| WM_SERVER

    %% Styling
    style FUNNEL fill:#fff8e1,stroke:#ffb300
    style CLOUD fill:#f3e5f5,stroke:#ab47bc
    style JAKE_APPS fill:#e3f2fd,stroke:#42a5f5
    style WM_STACK fill:#e8f5e9,stroke:#66bb6a
    style DS_STACK fill:#fce4ec,stroke:#ef5350
```

### Key Points
- **All RRG apps share the `windmill_default` Docker network** to communicate
- **rrg-router** is the entry point — routes chat messages to pnl/brochure workers
- **Source code lives on rrg-server** (`/home/andrea/rrg-*/`), images are built with Nix flakes on the server
- **DocuSeal source lives on the server** (`docuseal-src/`) — custom fork with RRG modifications
- **Windmill workflows live in Windmill's Postgres DB** — managed via Windmill UI or MCP
- **Tailscale Funnel** exposes DocuSeal (:443) and Windmill (:8443) publicly

---

## Layer 3: Application Workflows

The business logic — how services interact to accomplish tasks.

```mermaid
%%{init: {'theme': 'base', 'themeVariables': { 'primaryColor': '#fff3e0', 'primaryTextColor': '#e65100', 'primaryBorderColor': '#fb8c00', 'lineColor': '#fb8c00'}}}%%

graph TB
    subgraph TRIGGERS["TRIGGERS"]
        T_CHAT["User opens chat UI<br/>(:8501)"]
        T_NDA["Jake sends NDA<br/>(via Claude Code)"]
        T_SIGN["Recipient signs NDA<br/>(DocuSeal webhook)"]
        T_SCHED["Windmill scheduled job"]
        T_GMAIL["Gmail push notification<br/>(Pub/Sub)"]
    end

    subgraph CHAT_FLOW["CHAT FLOW"]
        ROUTER["rrg-router<br/>receives message"]
        ROUTE{{"Route by<br/>target_node"}}
        PNL["rrg-pnl<br/>P&L analysis"]
        BROCHURE["rrg-brochure<br/>Brochure generation"]
        WM_MSG["Windmill<br/>message_router"]
    end

    subgraph NDA_FLOW["NDA FLOW"]
        DS_CREATE["DocuSeal creates submission<br/>Template: NCND-RRG"]
        DS_EMAIL["Signing link emailed<br/>(teamgotcher SMTP)"]
        DS_SIGN["Recipient signs"]
        DS_HOOK["DocuSeal webhook fires"]
        DS_HANDLER["Windmill<br/>docuseal_nda/completed"]
    end

    subgraph SWITCHBOARD["WINDMILL SWITCHBOARD"]
        LEAD["lead_intake<br/>Process incoming leads"]
        CONV["lead_conversation<br/>Classify + respond to replies"]
        SIG_W["write_signal"]
        SIG_R["read_signals"]
        SIG_A["act_signal"]
        GMAIL_WH["gmail_pubsub_webhook"]
        GMAIL_WATCH["setup_gmail_watch<br/>(renew every 6 days)"]
    end

    subgraph EXTERNAL["EXTERNAL SERVICES"]
        WISEAGENT["WiseAgent CRM"]
        CLAUDE["Anthropic API"]
        GMAIL_API["Gmail API"]
    end

    %% Chat flow
    T_CHAT --> ROUTER --> ROUTE
    ROUTE -->|"pnl"| PNL
    ROUTE -->|"brochure"| BROCHURE
    ROUTE -->|"windmill"| WM_MSG
    PNL --> CLAUDE
    BROCHURE --> CLAUDE

    %% NDA flow
    T_NDA --> DS_CREATE --> DS_EMAIL --> DS_SIGN
    T_SIGN --> DS_HOOK
    DS_SIGN --> DS_HOOK
    DS_HOOK --> DS_HANDLER --> WISEAGENT

    %% Windmill flows
    T_SCHED --> LEAD --> WISEAGENT
    T_GMAIL --> GMAIL_WH --> SIG_W
    GMAIL_WH -->|"reply detected"| CONV
    CONV --> CLAUDE
    CONV --> WISEAGENT
    CONV --> SIG_W

    %% Signal pipeline
    SIG_W --> SIG_R --> SIG_A

    %% Gmail watch
    GMAIL_WATCH --> GMAIL_API

    %% Styling
    style TRIGGERS fill:#e3f2fd,stroke:#42a5f5
    style EXTERNAL fill:#f3e5f5,stroke:#ab47bc
    style SWITCHBOARD fill:#e8f5e9,stroke:#66bb6a
    style NDA_FLOW fill:#fce4ec,stroke:#ef5350
    style CHAT_FLOW fill:#fff3e0,stroke:#ffb300
```

### Key Points
- **Chat flow** is the primary user-facing feature: Jake talks to rrg-router, which delegates to specialized workers
- **NDA flow** is self-contained: DocuSeal handles the full signing lifecycle
- **Windmill switchboard** handles background automation (lead intake, signal processing, Gmail webhooks)

---

## Lead Intake Pipeline (Detail)

The lead intake flow (`f/switchboard/lead_intake`) is the most complex workflow. It spans Windmill, Gmail, Google Cloud Pub/Sub, and a Google Apps Script. Full documentation: [`docs/LEAD_INTAKE_PIPELINE.md`](LEAD_INTAKE_PIPELINE.md).

The lead conversation engine (`f/switchboard/lead_conversation`) handles replies to outreach emails — classifying intent and generating response drafts. Full documentation: [`docs/LEAD_CONVERSATION_ENGINE.md`](LEAD_CONVERSATION_ENGINE.md).

```mermaid
%%{init: {'theme': 'base', 'themeVariables': { 'primaryColor': '#e8f5e9', 'primaryTextColor': '#1b5e20', 'primaryBorderColor': '#43a047', 'lineColor': '#43a047'}}}%%

graph TB
    subgraph WINDMILL_FLOW["WINDMILL: f/switchboard/lead_intake"]
        direction TB
        A["<b>Module A</b><br/>WiseAgent Lookup"]
        B["<b>Module B</b><br/>Property Match"]
        C["<b>Module C</b><br/>Dedup/Group"]
        D["<b>Module D</b><br/>Generate Drafts<br/>+ Gmail API"]
        E["<b>Module E</b><br/>Approval Gate<br/><i>⏸ SUSPEND</i>"]
        F["<b>Module F</b><br/>Post-Approval<br/>(CRM + SMS)"]
    end

    subgraph GMAIL["GMAIL (teamgotcher@gmail.com)"]
        DRAFTS["Drafts created<br/>with X-Lead-Intake-*<br/>headers"]
        SEND["Jake sends draft"]
        DELETE["Jake deletes draft"]
    end

    subgraph PUBSUB["GOOGLE CLOUD PUB/SUB"]
        TOPIC["Topic: gmail-sent-<br/>notifications"]
        PUSH["Push subscription<br/>→ Windmill webhook"]
    end

    subgraph DETECTION["DETECTION LAYER"]
        WEBHOOK["gmail_pubsub_webhook<br/>(~2 sec, real-time)"]
        APPSSCRIPT["Apps Script<br/>(daily 9 AM poll)"]
    end

    subgraph EXTERNAL["EXTERNAL"]
        WISEAGENT["WiseAgent CRM"]
        SMS["SMS Gateway<br/>(pixel-9a :8686)"]
    end

    A --> B --> C --> D
    D -->|"Gmail API"| DRAFTS
    D --> E
    E -->|"Write signal to<br/>jake_signals"| E

    SEND --> TOPIC --> PUSH --> WEBHOOK
    WEBHOOK -->|"POST resume_url"| F

    DELETE -.->|"Draft not found"| APPSSCRIPT
    APPSSCRIPT -.->|"POST resume_url<br/>action: draft_deleted"| F

    F --> WISEAGENT
    F --> SMS

    style WINDMILL_FLOW fill:#e8f5e9,stroke:#43a047
    style GMAIL fill:#e3f2fd,stroke:#42a5f5
    style PUBSUB fill:#fff3e0,stroke:#ffb300
    style DETECTION fill:#f3e5f5,stroke:#ab47bc
    style EXTERNAL fill:#fce4ec,stroke:#ef5350
    style E fill:#fff9c4,stroke:#f9a825
```

## Lead Conversation Engine (Detail)

The conversation engine (`f/switchboard/lead_conversation`) processes replies to CRE outreach emails. Triggered by `gmail_pubsub_webhook` when an unlabeled INBOX email's thread_id matches an acted signal.

```mermaid
%%{init: {'theme': 'base', 'themeVariables': { 'primaryColor': '#fff3e0', 'primaryTextColor': '#e65100', 'primaryBorderColor': '#fb8c00', 'lineColor': '#fb8c00'}}}%%

graph TB
    subgraph TRIGGER["TRIGGER"]
        REPLY["Reply arrives in INBOX<br/>(unlabeled email)"]
        MATCH{"Thread_id matches<br/>acted signal?"}
    end

    subgraph CONV_FLOW["WINDMILL: f/switchboard/lead_conversation"]
        direction TB
        A["<b>Module A</b><br/>Fetch Thread +<br/>Classify Intent<br/>(Claude haiku)"]
        B["<b>Module B</b><br/>Generate Response<br/>Draft + Gmail API"]
        C["<b>Module C</b><br/>Approval Gate<br/><i>⏸ SUSPEND</i>"]
        D["<b>Module D</b><br/>Post-Approval<br/>(CRM + SMS)"]
    end

    subgraph CLASSIFY["CLASSIFICATIONS"]
        INT["INTERESTED<br/>(offer / want_something /<br/>general_interest)"]
        IGN["IGNORE<br/>(auto-reply, spam)"]
        NOT["NOT_INTERESTED<br/>(wrong person, unsubscribe)"]
        ERR["ERROR<br/>(parse failure)"]
    end

    subgraph TERMINAL["TERMINAL STATES"]
        T_IGN["CRM note only<br/>(flow stops)"]
        T_OFFER["Signal + CRM note<br/>(flow stops)"]
    end

    REPLY --> MATCH
    MATCH -->|"Yes"| A
    MATCH -->|"No"| SKIP["Label: Unlabeled<br/>(not a reply)"]

    A --> INT & IGN & NOT & ERR

    IGN --> T_IGN
    ERR --> T_IGN
    INT -->|"OFFER"| T_OFFER
    INT -->|"WANT_SOMETHING /<br/>GENERAL_INTEREST"| B
    NOT --> B

    B --> C --> D

    style TRIGGER fill:#e3f2fd,stroke:#42a5f5
    style CONV_FLOW fill:#e8f5e9,stroke:#43a047
    style CLASSIFY fill:#fff3e0,stroke:#ffb300
    style TERMINAL fill:#fce4ec,stroke:#ef5350
    style C fill:#fff9c4,stroke:#f9a825
```

---

## Quick Reference

### Network

| Device | Tailscale IP | Location | Status |
|--------|-------------|----------|--------|
| rrg-server | 100.97.86.99 | RRG Office | **Online** |
| jake-macbook | 100.108.74.112 | Mobile | **Online** |
| pixel-9a | 100.125.176.16 | RRG Office | **Online** |
| larrys-macbook | 100.79.238.103 | Mobile | **Online** |

### Ports (RRG-Server)

| Port | Service | Exposure |
|------|---------|----------|
| 22 | SSH | Tailscale |
| 3000 | DocuSeal | Tailscale + Funnel (public HTTPS) |
| 5432 | Postgres (Windmill) | Internal only |
| 8000 | Windmill Server | Tailscale + Funnel (:8443 public HTTPS) |
| 8100 | rrg-pnl | Internal (Docker network) |
| 8101 | rrg-brochure | Internal (Docker network) |
| 8501 | rrg-router | Tailscale |

### Docker Compose Files

| File | Manages | Location on Server |
|------|---------|-------------------|
| `jake-deploy/docker-compose.jake.yml` | rrg-router, rrg-pnl, rrg-brochure | `/home/andrea/jake-deploy/` |
| `windmill/docker-compose.yml` | windmill-server, windmill-worker, postgres | `/home/andrea/windmill/` |
| `docuseal/docker-compose.yml` | docuseal (custom image) | `/home/andrea/docuseal/` |

### Source Code Locations

| Component | Source | Build | Deploy |
|-----------|--------|-------|--------|
| rrg-router | Server: `/home/andrea/rrg-router/` | `nix build` on server | `docker load < result` |
| rrg-pnl | Server: `/home/andrea/rrg-pnl/` | `nix build` on server | `docker load < result` |
| rrg-brochure | Server: `/home/andrea/rrg-brochure/` | `nix build` on server | `docker load < result` |
| DocuSeal (custom) | Server: `/home/andrea/docuseal/` | `nix build` on server | `docker load < result` |
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

*Last verified: February 20, 2026*
*Source: Direct SSH inspection + dataflow analysis*
