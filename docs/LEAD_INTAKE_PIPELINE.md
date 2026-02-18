# Lead Intake Pipeline

> **Flow path:** `f/switchboard/lead_intake`
> **Last verified:** February 17, 2026

The lead intake pipeline processes incoming CRE leads from Crexi, LoopNet, Realtor.com, and the Seller Hub. It enriches leads with CRM data, generates personalized Gmail drafts, suspends for human approval, then completes CRM updates and SMS outreach after approval.

---

## Table of Contents

- [Trigger: Gmail Pub/Sub Webhook](#trigger-gmail-pubsub-webhook)
- [Pipeline Overview](#pipeline-overview)
- [Module Reference](#module-reference)
  - [Module A: WiseAgent Lookup](#module-a-wiseagent-lookup)
  - [Module B: Property Match](#module-b-property-match)
  - [Module C: Dedup and Group](#module-c-dedup-and-group)
  - [Module D: Generate Drafts + Gmail](#module-d-generate-drafts--gmail)
  - [Module E: Approval Gate](#module-e-approval-gate)
  - [Module F: Post-Approval](#module-f-post-approval)
- [Resume Mechanism](#resume-mechanism)
  - [How Windmill Suspend/Resume Works](#how-windmill-suspendresume-works)
  - [Gmail Pub/Sub Chain (Sent Detection)](#gmail-pubsub-chain-sent-detection)
  - [Apps Script Fallback (Deletion Detection)](#apps-script-fallback-deletion-detection)
- [X-Lead-Intake Headers](#x-lead-intake-headers)
- [Windmill Resources and Variables](#windmill-resources-and-variables)
- [Known Issues](#known-issues)

---

## Trigger: Gmail Pub/Sub Webhook

The pipeline is triggered automatically by `f/switchboard/gmail_pubsub_webhook`. This webhook handles **all** Gmail Pub/Sub notifications (both SENT and INBOX) in a single script with a single history cursor.

```
New email arrives in teamgotcher@gmail.com INBOX
         │
Gmail Pub/Sub notification → Windmill webhook
         │
    ┌────┴────┐
    │ INBOX?  │──── no (SENT, DRAFT, etc.) ─── see Resume Mechanism
    └────┬────┘
         │ yes
         ▼
    Fetch sender + subject (metadata only)
         │
    Categorize by pattern matching:
    ┌─────────────────────────────────────────────────────────┐
    │ notifications.crexi.com          → label "Crexi"        │
    │ loopnet.com + "favorited"        → label "LoopNet"      │
    │ subject: "New realtor.com lead…" → label "Realtor.com"  │
    │ subject: "New Verified Seller…"  → label "Seller Hub"   │
    │ everything else                  → label "Unlabeled"    │
    └─────────────────────────────────────────────────────────┘
         │
    Apply Gmail label to message
         │
    Is it a lead source? (Crexi/LoopNet/Realtor.com/Seller Hub)
    ┌────┴────┐
    │  yes    │──── no ─── done (labeled only)
    └────┬────┘
         │
    Fetch full message body
    Parse: name, email, phone, property_name, source_type
         │
    Add to leads_batch
         │
    After all messages processed:
    if leads_batch not empty →
         │
    HOPPER ARCHITECTURE: Group leads by email address
    Fire one flow per person (parallel)
         │
    For each person group:
    POST http://localhost:8000/api/w/rrg/jobs/run/f/f/switchboard/lead_intake
         { "leads": [leads for this person] }
         │
         ▼
    Pipeline starts (Module A → F) — one flow per person
```

**Categorization patterns** (from notification sender/subject, no LLM needed):

| Source | Sender Match | Subject Match | Gmail Label | Lead Parse |
|--------|-------------|---------------|-------------|------------|
| Crexi | `notifications.crexi.com` | — | "Crexi" | Yes (source_type from body: om/flyer/info_request) |
| LoopNet | `loopnet.com` | Contains "favorited" | "LoopNet" | Yes |
| Realtor.com | — | Starts with "New realtor.com lead" | "Realtor.com" | Yes |
| Seller Hub | — | Contains "New Verified Seller Lead" | "Seller Hub" | Yes |
| Everything else | — | — | "Unlabeled" | No |

**Lead parser output** (per lead, passed to `lead_intake` flow):
```json
{
    "name": "John Doe",
    "email": "john@example.com",
    "phone": "(555) 123-4567",
    "source": "Crexi",
    "source_type": "crexi_om",
    "property_name": "Dairy Queen",
    "notification_message_id": "msg_abc123"
}
```

Per-property differentiation for Crexi happens downstream in Module B (`property_mapping` variable), not in the webhook.

---

## Pipeline Overview

```
Input: { leads: [{name, email, phone, source, source_type, property_name, ...}] }

  Module A          Module B           Module C            Module D
  WiseAgent  ───▶  Property    ───▶  Dedup/Group  ───▶  Generate Drafts
  Lookup           Match                                 + Gmail API
  (enrich w/       (canonical         (group by          (create drafts w/
   CRM data)        names,             email,             X-Lead-Intake-*
                    deal IDs)          separate            headers)
                                       info reqs)
                                                              │
                                                              ▼
                                                         Module E
                                                         Approval Gate
                                                         (write signal,
                                                          SUSPEND flow)
                                                              │
                                              ┌───────────────┤
                                              │               │
                                         Jake sends      Jake deletes
                                         draft in        draft in
                                         Gmail           Gmail
                                              │               │
                                              ▼               ▼
                                         Pub/Sub         Apps Script
                                         webhook         (daily 9 AM)
                                         (~2 sec)        POSTs to
                                         POSTs to        resume_url w/
                                         resume_url      "draft_deleted"
                                              │               │
                                              ▼               ▼
                                         Module F        Module F
                                         Post-Approval   (writes CRM
                                         (CRM updates,   rejection note)
                                          SMS send)
```

---

## Module Reference

### Module A: WiseAgent Lookup

| Field | Value |
|-------|-------|
| **ID** | `a` |
| **Language** | Python 3.12 |
| **Input** | `flow_input.leads` |
| **Output** | Enriched leads array |

Searches WiseAgent CRM by email for each lead. If the contact doesn't exist, **creates it immediately** (moved from Module F). This ensures every lead exits Module A with a valid `wiseagent_client_id`, which is embedded in `X-Lead-Intake-WiseAgent-Client-ID` headers by Module D.

Also determines whether the contact has a signed NDA and whether outreach has already been sent (by checking contact notes for "outreach sent" / "initial outreach").

New contact creations are logged to the `contact_creation_log` Postgres table for audit/batch-fix purposes.

**OAuth handling:** Reads `f/switchboard/wiseagent_oauth`, checks token expiry, refreshes via `https://sync.thewiseagent.com/WiseAuth/token` if expired, writes refreshed tokens back to the Windmill resource.

**Fields added to each lead:**
- `wiseagent_client_id` — CRM client ID (always populated — created if new)
- `is_new` — true if contact was just created
- `has_nda` — true if contact has "NDA Signed" category
- `is_followup` — true if outreach notes already exist
- `wiseagent_status`, `wiseagent_rank` — CRM fields (existing contacts only)

---

### Module B: Property Match

| Field | Value |
|-------|-------|
| **ID** | `b` |
| **Language** | Python 3.12 |
| **Input** | `results.a` |
| **Output** | Leads with property metadata |

Matches lead property names against the `f/switchboard/property_mapping` Windmill variable. This variable contains a JSON mapping of property aliases to canonical names with metadata.

Only applies to `crexi_om`, `crexi_flyer`, and `loopnet` source types. Other source types get `is_mapped: null`.

**Fields added to each lead:**
- `is_mapped` — true/false/null
- `canonical_name` — standardized property name
- `deal_id` — HubSpot deal ID
- `brochure_highlights` — short property description
- `lead_magnet` — boolean (info-only listing, no OM to send)
- `response_override` — custom response text for lead magnets
- `property_address`, `asking_price`

---

### Module C: Dedup and Group

| Field | Value |
|-------|-------|
| **ID** | `c` |
| **Language** | Python 3.12 |
| **Input** | `results.b` |
| **Output** | `{ standard_leads[], info_requests[], total, info_request_count, multi_property_count }` |

Groups leads by email address so that one person who inquired about multiple properties gets a single multi-property email instead of separate emails. Separates `crexi_info_request` source types into a distinct list.

Each grouped lead carries all properties as a `properties[]` array and collects all `notification_message_ids` from the original leads.

---

### Module D: Generate Drafts + Gmail

| Field | Value |
|-------|-------|
| **ID** | `d` |
| **Language** | Python 3.12 |
| **Input** | `results.c` |
| **Output** | `{ preflight_checklist, drafts[], info_requests[], summary }` |

The largest module. Selects an email template for each lead based on source type and context, then creates Gmail drafts via the Gmail API with tracking headers embedded.

**Template selection logic:**

| Source Type | Condition | Template |
|------------|-----------|----------|
| `realtor_com` | — | Tour inquiry response |
| `seller_hub` | — | Seller outreach |
| Any | All properties are lead magnets | Lead magnet response (uses `response_override`) |
| `crexi_om` / `crexi_flyer` / `loopnet` | Multiple properties, not followup | Multi-property intro |
| `crexi_om` / `crexi_flyer` / `loopnet` | Multiple properties, is followup | Multi-property followup |
| `crexi_om` / `crexi_flyer` / `loopnet` | Single property, not followup | Single property intro |
| `crexi_om` / `crexi_flyer` / `loopnet` | Single property, is followup | Single property followup |

**Follow-up detection:** Beyond WiseAgent notes (Module A), Module D also checks Gmail sent folder for recent emails to the same address (last 7 days). If found, overrides `is_followup` to true.

**Gmail draft creation** is a two-step process per draft:
1. Create draft with all `X-Lead-Intake-*` headers except Draft-ID (unknown until created)
2. Update draft to add `X-Lead-Intake-Draft-ID` header (now known)

Each draft object includes: email content, template used, SMS body (if phone available), Gmail draft/message/thread IDs, and creation status.

**OAuth:** Uses `f/switchboard/gmail_oauth` for `teamgotcher@gmail.com`.

---

### Module E: Approval Gate

| Field | Value |
|-------|-------|
| **ID** | `e` |
| **Language** | Python 3.12 |
| **Input** | `results.d` |
| **Output** | `{ signal_id, created_at, resume_url, cancel_url, draft_count }` |
| **Suspend** | `required_events: 1, timeout: 0` |

Writes a signal to the `jake_signals` Postgres table, then **suspends the Windmill flow** indefinitely until an external system POSTs to the resume or cancel URL.

**What gets written to `jake_signals`:**

| Column | Value |
|--------|-------|
| `signal_type` | `"approval_needed"` |
| `source_flow` | `"lead_intake"` |
| `summary` | Human-readable summary from Module D |
| `detail` | JSON containing: `preflight_checklist`, `drafts[]`, `info_requests[]`, `draft_id_map`, `resume_url`, `cancel_url`, `summary` |
| `actions` | `["Approve All", "Reject All"]` |
| `status` | `"pending"` |

**The `draft_id_map`** is a lookup table keyed by Gmail draft ID:
```json
{
  "r-12345": { "email": "lead@example.com", "thread_id": "t-abc", "draft_index": 0 },
  "r-67890": { "email": "other@example.com", "thread_id": "t-def", "draft_index": 1 }
}
```
This map is how external systems (Pub/Sub webhook, Apps Script) find the matching signal for a given draft.

After writing the signal, the module returns and the flow **suspends**. Two external systems watch for Jake's action on the draft:
- **Sent:** Gmail Pub/Sub → `f/switchboard/gmail_pubsub_webhook` resumes the flow in ~2 seconds
- **Deleted:** `gmail-draft-deletion-watcher` (Google Apps Script, daily 9 AM) POSTs to `resume_url` with `action: "draft_deleted"` so Module F can write CRM rejection notes

See [Resume Mechanism](#resume-mechanism) for full details.

---

### Module F: Post-Approval

| Field | Value |
|-------|-------|
| **ID** | `f` |
| **Language** | Python 3.12 |
| **Inputs** | `resume` (POST body from resume URL) + `results.d` (Module D output, preserved across suspend) |
| **Output** | `{ status, wiseagent_results[], sms_results[] }` |

Runs after the flow is resumed. First marks the signal as `acted` in `jake_signals` (prevents duplicate processing). Then branches on `resume_payload.action`:

**`"email_sent"` path:**
1. Run SMS loop FIRST — send SMS to leads with phone numbers via pixel-9a gateway
2. Get WiseAgent OAuth token
3. For each draft in `draft_data.drafts`:
   - Update contact status to "Contacted" (contact already exists — created by Module A)
   - Add CRM note with **accurate** SMS outcome: "Email sent... SMS sent to {phone}." or "No phone number — SMS not sent." or "SMS attempted but failed."

   Note: SMS runs before CRM notes because WiseAgent notes can't be edited after creation. Writing the note after SMS ensures accuracy.

**`"draft_deleted"` path:**
1. For each draft: add rejection note to the existing WiseAgent contact: "Lead rejected — draft deleted on {date}. Property: {names}."
2. Return `{ status: "rejected" }`

**`"error"` in payload:** Returns `{ status: "rejected" }`. This occurs when the flow is cancelled via Windmill's cancel URL.

---

## Resume Mechanism

After Module E suspends, the flow is frozen. Three things can wake it up or kill it:

| Trigger | Mechanism | Speed | What happens |
|---------|-----------|-------|-------------|
| Jake sends a draft | Gmail Pub/Sub → Windmill webhook → POST to `resume_url` | ~2 seconds | Module F runs (CRM update + SMS) |
| Jake deletes a draft | `gmail-draft-deletion-watcher` (Apps Script daily poll) → POST to `resume_url` with `action: "draft_deleted"` | Up to 24 hours | Module F runs (CRM rejection note) |
| Nothing happens | — | — | Flow stays suspended (`timeout: 0`) — visible reminder in Windmill |

### How Windmill Suspend/Resume Works

When Module E's code finishes, Windmill's suspend feature pauses the flow. `wmill.get_resume_urls()` generates two cryptographically signed URLs:

- **`resume_url`**: `https://rrg-server.tailc01f9b.ts.net:8443/api/w/rrg/jobs_u/resume/{JOB_ID}/{RESUME_ID}/{SIGNATURE}`
- **`cancel_url`**: `https://rrg-server.tailc01f9b.ts.net:8443/api/w/rrg/jobs_u/cancel/{JOB_ID}/{RESUME_ID}/{SIGNATURE}`

The signature baked into the URL provides authentication. Any system that knows the URL can POST to it.

**Resuming (POST to `resume_url`):** The JSON body of the POST becomes the `resume` variable in the next module's `input_transforms`. Module F maps this as `resume_payload`. Windmill also preserves all prior module outputs (`results.a` through `results.e`) across the suspend, so Module F can access `results.d` (Module D's output) directly.

**Cancelling (POST to `cancel_url`):** The flow is immediately terminated. Module F never runs. The cancellation payload becomes the flow's final result.

### Gmail Pub/Sub Chain (Sent Detection + Inbox Categorization)

A single webhook (`f/switchboard/gmail_pubsub_webhook`) handles both SENT detection (draft resume) and INBOX categorization (email labeling + lead intake trigger).

**Prerequisites:**
- `f/switchboard/setup_gmail_watch` has been run (and renews every 6 days)
- GCP project `rrg-gmail-automation` (TeamGotcher) has topic `gmail-sent-notifications`
- Topic has a push subscription pointing to the Windmill webhook URL
- `gmail-api-push@system.gserviceaccount.com` has Pub/Sub Publisher permission on the topic

**Chain of events:**

```
1. Gmail mailbox change (new email received OR email sent)
         │
2. Gmail detects label change on teamgotcher@gmail.com (SENT or INBOX)
         │
3. Gmail pushes to GCP Pub/Sub topic:
         │   { emailAddress: "teamgotcher@gmail.com", historyId: 1001 }
         │   (base64-encoded in the Pub/Sub message envelope)
         │
4. Pub/Sub push subscription POSTs to Windmill webhook:
         │   https://rrg-server.tailc01f9b.ts.net:8443/api/w/rrg/webhooks/{TOKEN}/p/f/switchboard/gmail_pubsub_webhook
         │
5. gmail_pubsub_webhook runs:
         │
         ├── Decode base64 → get historyId (1001)
         ├── Read stored cursor from f/switchboard/gmail_last_history_id (e.g. 1000)
         ├── Query Gmail History API: "what changed between 1000 and 1001?"
         │     → Returns list of messageAdded events (no label filter)
         │
         ├── For each message with SENT label:
         │     ├── Fetch X-Lead-Intake-* headers
         │     ├── If X-Lead-Intake-Draft-ID exists:
         │     │     ├── Query jake_signals for matching draft_id
         │     │     └── POST to resume_url: { action: "email_sent", ... }
         │     └── Otherwise: silently ignore (normal sent email)
         │
         ├── For each message with INBOX label:
         │     ├── Fetch sender + subject (metadata only)
         │     ├── Categorize → apply Gmail label
         │     ├── If lead source: fetch full body, parse lead data
         │     └── Add parsed lead to leads_batch
         │
         ├── If leads_batch not empty:
         │     └── POST to lead_intake flow: { leads: leads_batch }
         │
         └── Save new historyId (1001) to f/switchboard/gmail_last_history_id
```

**Single cursor, single subscription:** Both SENT and INBOX events come through the same Pub/Sub subscription and use the same `gmail_last_history_id` cursor. The webhook branches on the `labelIds` array that comes with each `messageAdded` event.

**Gmail History ID explained:** Every change in a Gmail mailbox increments a counter. The history ID is that counter value. When a Pub/Sub notification arrives with `historyId: 1001`, the webhook asks Gmail "what happened between my last checkpoint and 1001?" This range query is necessary because Gmail may batch multiple changes into a single notification (e.g., 3 emails sent quickly may produce only 1 notification with the latest history ID).

### Apps Script Fallback (Deletion Detection)

Detects when Jake deletes a lead intake draft (rejection). Low priority, runs daily.

**Location:** Google Apps Script project ID `1xLmwzHJh0heGgoBBdWQMZJtuuY3bXRsiOpoeteY9fYJ-MuYouu6VVfcD`
**Local source:** `~/Desktop/other/services/gmail-draft-deletion-watcher/Code.js`

**Schedule:** Daily at 9 AM (time-based trigger on `watchDrafts` function)

**How it works:**

```
1. Call f/switchboard/get_pending_draft_signals via Windmill API
   → Returns all pending lead_intake signals with draft_id_map
         │
2. For each signal, for each draft_id in draft_id_map:
         │
         ├── Try Gmail.Users.Drafts.get('me', draftId)
         │
         ├── Draft exists → skip (still waiting for Jake to act)
         │
         └── Draft not found (404):
               ├── Check thread for SENT messages
               │     (Gmail.Users.Threads.get → look for SENT label)
               │
               ├── SENT message found → draft was sent
               │     POST to resume_url: { action: "email_sent" }
               │     (fallback in case Pub/Sub missed it)
               │
               └── No SENT message → draft was deleted
                     POST to resume_url: { action: "draft_deleted" }
                     (Module F runs, writes CRM rejection note)
```

**Auth:** `WINDMILL_TOKEN` stored in Apps Script Properties. Communicates via public Tailscale Funnel URL (`https://rrg-server.tailc01f9b.ts.net:8443`).

**Also exposes** a web app (`doGet`) for remote triggering: `?action=run` to execute immediately, `?action=setup` to install the trigger, `?action=status` to check trigger status.

---

## X-Lead-Intake Headers

Module D embeds custom headers in each Gmail draft. These headers are invisible to the email recipient but travel with the message content. When Gmail assigns a new message ID on send (draft IDs and message IDs are destroyed when a draft is sent), the headers survive inside the sent message. This is how the Pub/Sub webhook matches a sent email back to the original lead intake flow.

| Header | Purpose |
|--------|---------|
| `X-Lead-Intake-Draft-ID` | Original Gmail draft ID (primary lookup key) |
| `X-Lead-Intake-Message-ID` | Original notification message ID |
| `X-Lead-Intake-Thread-ID` | Gmail thread ID |
| `X-Lead-Intake-WiseAgent-Client-ID` | WiseAgent CRM client ID |
| `X-Lead-Intake-WiseAgent-Deal-ID` | Associated deal ID |
| `X-Lead-Intake-Phone` | Lead's phone number |
| `X-Lead-Intake-Name` | Lead's name |
| `X-Lead-Intake-Email` | Lead's email address |

---

## Windmill Resources and Variables

**Resources (credentials/connections):**

| Resource | Purpose |
|----------|---------|
| `f/switchboard/wiseagent_oauth` | WiseAgent OAuth tokens (auto-refreshed by Module A, F, and NDA handler) |
| `f/switchboard/gmail_oauth` | Gmail OAuth for teamgotcher@gmail.com |
| `f/switchboard/pg` | Postgres connection (jake_signals table) |

**Variables (simple key-value):**

| Variable | Purpose |
|----------|---------|
| `f/switchboard/property_mapping` | JSON mapping of property aliases → canonical names with metadata |
| `f/switchboard/sms_gateway_url` | SMS gateway endpoint URL (pixel-9a, Crexi/LoopNet leads only) |
| `f/switchboard/gmail_last_history_id` | Gmail History API cursor — last processed history ID |
| `f/switchboard/router_token` | Auth token used by gmail_pubsub_webhook for resume URL POSTs |

**Windmill Scripts (all under `f/switchboard/`):**

| Script | Purpose |
|--------|---------|
| `get_pending_draft_signals` | Query pending lead_intake signals with draft_id_map (used by Apps Script) |
| `gmail_pubsub_webhook` | Receives Gmail Pub/Sub notifications — SENT: triggers resume; INBOX: categorizes, labels, triggers lead intake |
| `setup_gmail_watch` | Sets up Gmail SENT + INBOX label watch, renew every 6 days |
| `check_gmail_watch_health` | Daily 10 AM ET — alerts via SMS if webhook hasn't run in 48h |
| `act_signal` | Marks signal as acted in Postgres (does NOT resume/cancel suspended flows) |
| `read_signals` | Query pending signals |
| `write_signal` | Insert new signal row |

---

## Known Issues

**Resolved (Feb 18, 2026):**
1. ~~Module F processes all drafts on any resume~~ — **Fixed:** Hopper architecture (one flow per person) means each flow has exactly 1 draft.
2. ~~Module F's `draft_deleted` branch unreachable~~ — **Fixed:** Apps Script now POSTs to `resume_url` (not `cancel_url`), so Module F runs and writes CRM rejection notes.
3. ~~`act_signal` does not wake suspended flows~~ — **By design:** Router UI is read-only for lead intake. Gmail IS the UI (send = approve, delete = reject).
4. ~~`sent_at` never populated~~ — **Fixed:** Both Pub/Sub webhook and Apps Script now include `sent_at` in resume payloads.
5. ~~`timeout: 0` zombie flows~~ — **By design:** Suspended flows are visible reminders. With hopper architecture, each has exactly 1 draft.
6. ~~Pub/Sub webhook `lead_data` ignored~~ — **Fixed:** Removed dead-weight `lead_data` from resume payload.
7. ~~Lead parsing fails silently~~ — **Mitigated:** `validate_lead()` cross-checks fields. Failed/invalid parses downgrade to "Unlabeled" label. New contact creations logged to `contact_creation_log` table for retroactive batch-fix.

**Remaining:**
- **Lead parsing is regex-based.** If a notification source changes their email format, the parser may fail. Downgrade-to-Unlabeled makes format changes visible (emails pile up in Unlabeled). Monitor `downgraded_to_unlabeled: true` in webhook output.
- **No automated backups** for `jake_signals` or `contact_creation_log` tables.

---

## GCP Setup (One-Time)

The Gmail watch requires a Pub/Sub topic in the same GCP project as the OAuth client credentials.

**Project:** `rrg-gmail-automation` (TeamGotcher Google account)
**Topic:** `gmail-sent-notifications`

The topic and push subscription should already exist from the original SENT-only setup. The only change needed is to update the `f/switchboard/gmail_oauth` Windmill resource so its `client_id` and `client_secret` come from the `rrg-gmail-automation` GCP project (not `claude-connector-484817`). Then run `f/switchboard/setup_gmail_watch` to activate the watch with INBOX added.

**If setting up from scratch (GCP Console):**
1. Go to Pub/Sub → Topics → Create Topic: `gmail-sent-notifications`
2. On the topic, add IAM binding: `gmail-api-push@system.gserviceaccount.com` → role `Pub/Sub Publisher`
3. Create a Push Subscription on the topic:
   - Endpoint URL: `https://rrg-server.tailc01f9b.ts.net:8443/api/w/rrg/webhooks/{TOKEN}/p/f/switchboard/gmail_pubsub_webhook`
   - (The `{TOKEN}` is the Windmill webhook token, visible in the Windmill UI)
4. Run `f/switchboard/setup_gmail_watch` to activate the watch

---

*Last updated: February 18, 2026 — Hopper architecture, Module A creates contacts, Module F simplified*
