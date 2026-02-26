# Windmill Recovery Documentation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Update existing docs (CURRENT_STATE.md, DEPLOYMENT.md, ARCHITECTURE.md) so that all Windmill connective tissue (resources, variables, webhooks, watches, schedules) is fully documented with schemas, credential sources, and re-auth procedures — without hardcoding secrets. Also remove all stale references to deprecated components.

**Architecture:** No code changes. All edits are to existing Markdown files in `docs/`. The pattern for each resource: document the shape (keys), credential source (path in jake-system.json), Google Cloud project (if OAuth), scopes, re-auth procedure, and token lifecycle. Never include actual secret values.

**Tech Stack:** Markdown, Windmill API (POST for create/update — NOT PUT)

---

### Task 1: Remove stale claude-endpoint references from CURRENT_STATE.md

**Files:**
- Modify: `docs/CURRENT_STATE.md:247` (delete claude_endpoint_url line)
- Modify: `docs/CURRENT_STATE.md:84-85` (update windmill-worker image description)
- Modify: `docs/CURRENT_STATE.md:207-209` (update Windmill build description)

**Step 1: Delete the claude_endpoint_url variable line**

In `docs/CURRENT_STATE.md`, line 247, delete:
```
- `f/switchboard/claude_endpoint_url` — Claude API proxy on jake-macbook (`http://100.108.74.112:8787`)
```

**Step 2: Update windmill-worker image description**

In `docs/CURRENT_STATE.md`, the Windmill stack table (line ~84), change the windmill-worker row from:
```
| windmill-windmill_worker-1 | (same) | — | internal | Job executor |
```
to:
```
| windmill-windmill_worker-1 | windmill-worker:latest | — | internal | Job executor (Nix-layered: stock Windmill + Claude CLI) |
```

**Step 3: Update Windmill build section**

In `docs/CURRENT_STATE.md`, replace lines 206-209:
```
### Windmill

```
No build step — uses upstream image ghcr.io/windmill-labs/windmill:main
Workflows managed via Windmill UI or MCP API
```
```

with:
```
### Windmill

```
Server: upstream image ghcr.io/windmill-labs/windmill:main (no build)
Worker: Nix buildLayeredImage — stock Windmill + Claude CLI (/usr/local/bin/claude)
  Build: cd ~/rrg-server/windmill-worker && nix build && docker load < result
  Note: buildLayeredImage does NOT preserve base image CMD — must set command: windmill in docker-compose
Workflows: Windmill UI, MCP API, or wmill CLI
```
```

**Step 4: Verify no other claude-endpoint references remain**

Run: `grep -r "claude.endpoint\|8787\|pm2" docs/CURRENT_STATE.md`
Expected: No matches

---

### Task 2: Remove stale claude-endpoint references from DEPLOYMENT.md

**Files:**
- Modify: `docs/DEPLOYMENT.md:57-63` (delete rrg-claude-endpoint section)
- Modify: `docs/DEPLOYMENT.md:76-81` (update disaster recovery section)

**Step 1: Delete the rrg-claude-endpoint section**

In `docs/DEPLOYMENT.md`, delete lines 57-63 entirely:
```
## rrg-claude-endpoint (pm2 on jake-macbook)

```bash
pm2 start server.js --name claude-endpoint
pm2 restart claude-endpoint
pm2 logs claude-endpoint
```
```

**Step 2: Update disaster recovery section**

In `docs/DEPLOYMENT.md`, replace lines 74-81:
```
## Windmill Disaster Recovery

Flows/scripts are version-controlled in `windmill/f/` (via `wmill sync pull`).
To restore to a fresh Windmill instance:
```bash
cd ~/rrg-server/windmill
wmill sync push --base-url http://localhost:8000 --workspace rrg --token <token>
```
```

with:
```
## Windmill Disaster Recovery

**Flows/scripts** are version-controlled in `windmill/f/` (via `wmill sync pull`).
To restore flows/scripts to a fresh Windmill instance:
```bash
cd ~/rrg-server/windmill
wmill sync push --base-url http://localhost:8000 --workspace rrg --token <token>
```

**WARNING:** `wmill sync push` restores flows and scripts ONLY. It does NOT restore:
- Resources (OAuth credentials, Postgres connection, etc.)
- Variables (property_mapping, history cursors, tokens, etc.)
- Schedules, webhooks, or Gmail watches

To restore these, see the "Windmill Resources" and "Windmill Variables" sections in `CURRENT_STATE.md` for schemas, credential sources, and re-auth procedures. All secret values live in `~/.secrets/jake-system.json` on jake-macbook.

**CRITICAL:** The Windmill API uses **POST** (not PUT) for both `resources/create` and `resources/update` endpoints. PUT returns 405 silently.
```

**Step 3: Verify**

Run: `grep -r "pm2\|claude-endpoint" docs/DEPLOYMENT.md`
Expected: No matches

**Step 4: Commit**

```bash
git add docs/DEPLOYMENT.md
git commit -m "docs: remove deprecated claude-endpoint, fix disaster recovery section"
```

---

### Task 3: Remove stale claude-endpoint from ARCHITECTURE.md

**Files:**
- Modify: `docs/ARCHITECTURE.md:90-93` (remove claude-endpoint from diagram)

**Step 1: Remove claude-endpoint from Layer 2 diagram**

In `docs/ARCHITECTURE.md`, in the MAC subgraph (around line 90), delete:
```
        CLAUDE_EP["<b>claude-endpoint</b><br/>:8787 (pm2)"]
```

**Step 2: Verify**

Run: `grep -r "claude.endpoint\|8787\|pm2" docs/ARCHITECTURE.md`
Expected: No matches

**Step 3: Commit**

```bash
git add docs/ARCHITECTURE.md
git commit -m "docs: remove deprecated claude-endpoint from architecture diagram"
```

---

### Task 4: Add Windmill resource schemas and recovery info to CURRENT_STATE.md

This is the main task — adding the connective tissue documentation that was missing.

**Files:**
- Modify: `docs/CURRENT_STATE.md` — replace the bare resource/variable lists in the WINDMILL WORKFLOWS section with full schemas and recovery procedures

**Step 1: Replace the Windmill variables section (lines 241-247)**

Replace:
```
Windmill variables:
- `f/switchboard/property_mapping` — JSON property alias → canonical name mapping (with optional `documents` field per property)
- `f/switchboard/sms_gateway_url` — SMS gateway endpoint URL (Pixel 9a)
- `f/switchboard/gmail_last_history_id` — Gmail History API cursor for teamgotcher@
- `f/switchboard/gmail_leads_last_history_id` — Gmail History API cursor for leads@
- `f/switchboard/router_token` — Auth token for resume URL POSTs
- `f/switchboard/claude_endpoint_url` — Claude API proxy on jake-macbook (`http://100.108.74.112:8787`)
```

with:
```
Windmill variables:
| Variable | Purpose | Secret | Used By |
|----------|---------|--------|---------|
| `f/switchboard/property_mapping` | JSON: property alias → canonical name mapping | No | `lead_intake/property_match` |
| `f/switchboard/sms_gateway_url` | SMS gateway URL (Pixel 9a) | No | `lead_intake/post_approval`, `lead_conversation/post_approval`, `check_gmail_watch_health` |
| `f/switchboard/gmail_last_history_id` | Gmail History API cursor for teamgotcher@ | No | `gmail_pubsub_webhook` (read/write) |
| `f/switchboard/gmail_leads_last_history_id` | Gmail History API cursor for leads@ | No | `gmail_pubsub_webhook` (read/write) |
| `f/switchboard/router_token` | Auth token for internal Windmill API job triggers | Yes | `gmail_pubsub_webhook`, `process_staged_leads`, `check_gmail_watch_health` |
| `f/switchboard/email_signatures` | HTML email signatures (Larry + Andrea) | No | Not currently referenced by any script |

**Note:** `f/switchboard/email_signatures` exists but is unused by scripts. It may be safe to delete, or it may be needed for future draft generation enhancements.
```

**Step 2: Add a new "Windmill Resources (Recovery Reference)" section**

Insert this AFTER the variables section and BEFORE the "GMAIL INTEGRATION" section:

```
### Windmill Resources (Recovery Reference)

Each resource below documents its schema (required keys), where credential values live, and how to re-authorize if tokens are lost. **Never hardcode secret values in this file** — always reference `jake-system.json` paths.

**API note:** Windmill resource create/update endpoints use **POST** (not PUT). PUT returns HTTP 405 silently.

---

#### `f/switchboard/gmail_oauth`
- **Purpose:** teamgotcher@gmail.com — sends drafts, detects SENT messages, detects replies
- **Type:** Google OAuth2
- **Schema:** `{ client_id, client_secret, refresh_token, access_token, token_uri }`
- **Credentials source:** `jake-system.json` → `google_oauth.rrg_gmail_automation` (client_id, client_secret)
- **Google Cloud project:** `rrg-gmail-automation` (owned by teamgotcher@gmail.com)
- **Scopes:** `gmail.readonly`, `gmail.compose`, `gmail.modify`, `gmail.send`
- **Token lifecycle:** `access_token` auto-refreshes via google-auth library; `refresh_token` is long-lived but revoked if user changes password or removes app access
- **Re-auth procedure:**
  1. Get client_id from `jake-system.json` → `google_oauth.rrg_gmail_automation.client_id`
  2. Open: `https://accounts.google.com/o/oauth2/v2/auth?client_id=<CLIENT_ID>&redirect_uri=http%3A%2F%2Flocalhost&response_type=code&scope=https%3A%2F%2Fwww.googleapis.com%2Fauth%2Fgmail.readonly+...gmail.compose+...gmail.modify+...gmail.send&access_type=offline&prompt=consent&login_hint=teamgotcher%40gmail.com`
  3. Sign in as teamgotcher@gmail.com, authorize
  4. Copy `code=` from localhost redirect URL
  5. Exchange: `curl -X POST https://oauth2.googleapis.com/token --data-urlencode "grant_type=authorization_code" --data-urlencode "client_id=<CLIENT_ID>" --data-urlencode "client_secret=<CLIENT_SECRET>" --data-urlencode "code=<CODE>" --data-urlencode "redirect_uri=http://localhost"`
  6. Update Windmill: `curl -X POST http://localhost:8000/api/w/rrg/resources/update/f/switchboard/gmail_oauth -H "Authorization: Bearer <WINDMILL_TOKEN>" -H "Content-Type: application/json" -d '{"value": { ... }}'`
- **Used by:** `gmail_pubsub_webhook`, `setup_gmail_watch`, `gmail_polling_trigger`, `lead_conversation/fetch_thread`, `lead_conversation/generate_response`, `lead_intake/generate_drafts`, diagnostics

---

#### `f/switchboard/gmail_leads_oauth`
- **Purpose:** leads@resourcerealtygroupmi.com — receives lead notification emails
- **Type:** Google OAuth2
- **Schema:** `{ client_id, client_secret, refresh_token, access_token, token_uri }`
- **Credentials source:** `jake-system.json` → `google_oauth.claude_connector` (client_id, client_secret)
- **Google Cloud project:** `claude-connector-484817` (owned by jacob@resourcerealtygroupmi.com)
- **Important:** Uses a DIFFERENT Google Cloud project than gmail_oauth because leads@ is on the resourcerealtygroupmi.com domain, not a gmail.com account
- **Scopes:** `gmail.readonly`, `gmail.compose`, `gmail.modify`, `gmail.send`
- **Token lifecycle:** Same as gmail_oauth
- **Re-auth procedure:** Same as gmail_oauth, but use `claude_connector` client credentials and sign in as `leads@resourcerealtygroupmi.com`
- **Used by:** `gmail_pubsub_webhook`, `setup_gmail_leads_watch`

---

#### `f/switchboard/wiseagent_oauth`
- **Purpose:** WiseAgent CRM API access (contact lookup, create, update notes)
- **Type:** OAuth2
- **Schema:** `{ client_id, client_secret, access_token, refresh_token, expires_at, token_url }`
- **Credentials source:** `jake-system.json` → `wiseagent` (client_id, client_secret)
- **Token URL:** `https://sync.thewiseagent.com/WiseAuth/token`
- **Token lifecycle:** `access_token` expires (see `expires_at`); scripts auto-refresh using `refresh_token` via `wmill.set_resource()`. `refresh_token` is long-lived.
- **Re-auth procedure:**
  1. Get client_id from `jake-system.json` → `wiseagent.client_id`
  2. Open: `https://sync.thewiseagent.com/WiseAuth/auth?client_id=<CLIENT_ID>&redirect_uri=http://localhost&response_type=code&scope=profile%20team%20contacts%20properties`
  3. Sign in with Larry's WiseAgent credentials (teamgotcher@gmail.com)
  4. Copy `code=` from localhost redirect URL
  5. Exchange: `curl -X POST https://sync.thewiseagent.com/WiseAuth/token --data-urlencode "grant_type=authorization_code" --data-urlencode "client_id=<CLIENT_ID>" --data-urlencode "client_secret=<CLIENT_SECRET>" --data-urlencode "code=<CODE>" --data-urlencode "redirect_uri=http://localhost"`
  6. Update Windmill resource (same pattern as gmail_oauth, use POST)
- **Used by:** `lead_intake/wiseagent_lookup`, `lead_intake/post_approval`, `lead_conversation/generate_response`, `lead_conversation/post_approval`, `f/docuseal/nda_completed`

---

#### `f/switchboard/pg`
- **Purpose:** Postgres connection for Windmill's own DB (jake_signals, staged_leads, processed_notifications tables)
- **Type:** PostgreSQL
- **Schema:** `{ host, port, user, password, dbname, sslmode }`
- **Credentials source:** `jake-system.json` → `windmill.postgres`
- **Important:** `host` must be `db` (Docker internal hostname), NOT an external IP. Scripts run inside the Windmill worker container on the `windmill_default` Docker network.
- **Used by:** `gmail_pubsub_webhook`, `write_signal`, `read_signals`, `act_signal`, `get_pending_draft_signals`, `process_staged_leads`, `lead_intake/approval_gate`, `lead_intake/post_approval`, `lead_conversation/approval_gate`, `lead_conversation/post_approval`, `lead_conversation/generate_response`

---

#### `f/switchboard/tailscale_machines`
- **Purpose:** Machine IPs and metadata for reference
- **Type:** Object
- **Schema:** `{ "rrg-server": {...}, "jake-macbook": {...}, "pixel-9a": {...}, "larry-sms-gateway": {...} }`
- **Credentials source:** `jake-system.json` → `tailscale.machines` (or `.claude/rules/network.md`)
- **Used by:** Reference only — no scripts directly consume this
```

**Step 3: Verify the edit**

Read through the modified section to confirm:
- No actual secret values are present
- All 5 resources are documented
- All 6 variables are documented
- Re-auth procedures reference jake-system.json paths, not inline values

**Step 4: Commit**

```bash
git add docs/CURRENT_STATE.md
git commit -m "docs: add Windmill resource schemas and recovery procedures to CURRENT_STATE"
```

---

### Task 5: Remove stale claude_endpoint_url from LEAD_INTAKE_PIPELINE.md

**Files:**
- Modify: `docs/LEAD_INTAKE_PIPELINE.md:539`

**Step 1: Find and delete the stale reference**

In `docs/LEAD_INTAKE_PIPELINE.md`, find the line:
```
| `f/switchboard/claude_endpoint_url` | Claude API proxy URL on jake-macbook (`http://100.108.74.112:8787`) |
```

Delete it.

**Step 2: Verify**

Run: `grep "claude_endpoint" docs/LEAD_INTAKE_PIPELINE.md`
Expected: No matches

**Step 3: Commit**

```bash
git add docs/LEAD_INTAKE_PIPELINE.md
git commit -m "docs: remove deprecated claude_endpoint_url from lead intake pipeline docs"
```

---

### Task 6: Update verification date and known issues in CURRENT_STATE.md

**Files:**
- Modify: `docs/CURRENT_STATE.md:5` (verified date)
- Modify: `docs/CURRENT_STATE.md:349-357` (known issues)
- Modify: `docs/CURRENT_STATE.md:360` (last verified footer)

**Step 1: Update verified date at top**

Change line 5 from:
```
## Verified February 14, 2026
```
to:
```
## Verified February 26, 2026
```

**Step 2: Update known issues**

Review the known issues section. Add:
```
7. **Windmill resources not covered by sync** — `wmill sync push/pull` only handles flows/scripts. Resources, variables, schedules, and webhooks must be recreated manually. See "Windmill Resources (Recovery Reference)" section above.
```

**Step 3: Update footer date**

Change:
```
*Last verified: February 23, 2026*
```
to:
```
*Last verified: February 26, 2026*
```

**Step 4: Commit**

```bash
git add docs/CURRENT_STATE.md
git commit -m "docs: update verification date and add windmill sync limitation to known issues"
```

---

### Task 7: Final verification pass

**Step 1: Search all docs for remaining stale references**

Run these and confirm no matches:
```bash
grep -r "claude.endpoint\|8787\|pm2\|claude_endpoint_url" docs/ --include="*.md" | grep -v "plans/"
```
Expected: No matches (plan files are historical, they can keep their references)

**Step 2: Search for any hardcoded secrets that might have crept in**

```bash
grep -rE "GOCSPX-|1//0[0-9]|sk-ant-|muswxrd|ya29\." docs/ --include="*.md"
```
Expected: No matches

**Step 3: Read through the modified sections of CURRENT_STATE.md**

Visually confirm:
- Resource schemas list keys but no values
- Re-auth procedures use `<PLACEHOLDER>` not real credentials
- jake-system.json paths are correct
- "Used by" lists match the grep results from investigation

**Step 4: Final commit (if any fixups needed)**

```bash
git add docs/
git commit -m "docs: final cleanup pass"
```

---

## Summary

| Task | What | File(s) |
|------|------|---------|
| 1 | Remove stale claude-endpoint from CURRENT_STATE | `docs/CURRENT_STATE.md` |
| 2 | Remove stale claude-endpoint from DEPLOYMENT | `docs/DEPLOYMENT.md` |
| 3 | Remove stale claude-endpoint from ARCHITECTURE | `docs/ARCHITECTURE.md` |
| 4 | Add resource schemas + recovery procedures | `docs/CURRENT_STATE.md` |
| 5 | Remove stale reference from LEAD_INTAKE_PIPELINE | `docs/LEAD_INTAKE_PIPELINE.md` |
| 6 | Update dates and known issues | `docs/CURRENT_STATE.md` |
| 7 | Final verification — no stale refs, no hardcoded secrets | All docs |
