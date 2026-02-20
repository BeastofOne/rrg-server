# Lead Intake Pipeline

> **Flow path:** `f/switchboard/lead_intake`
> **Last verified:** February 19, 2026

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
  - [Thread ID Matching (Sent Detection)](#thread-id-matching-sent-detection)
  - [Polling Trigger](#polling-trigger)
  - [Apps Script Fallback (Deletion Detection)](#apps-script-fallback-deletion-detection)
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
    │  yes    │──── no ─── Is it a reply to outreach?
    └────┬────┘            (thread_id matches acted signal)
         │                 ┌────┴────┐
         │                 │  yes    │──── no ─── done (Unlabeled)
         │                 └────┬────┘
         │                      │
         │                 Relabel "Lead Reply"
         │                 Fetch reply body
         │                 Trigger f/switchboard/lead_conversation
         │
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
| Reply to outreach | — | — (thread_id matches acted signal) | "Lead Reply" | No (triggers `lead_conversation`) |
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
  (enrich w/       (canonical         (group by          (create drafts,
   CRM data)        names,             email,             store thread_id
                    deal IDs)          separate            for SENT matching)
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

Searches WiseAgent CRM by email for each lead. If the contact doesn't exist, **creates it immediately** (moved from Module F). This ensures every lead exits Module A with a valid `wiseagent_client_id`.

Also determines whether the contact has a signed NDA and whether this is a followup (by checking for "Lead Intake" notes from the last 7 days).

**Followup detection:** For existing contacts, Module A checks WiseAgent notes for any note with subject containing "Lead Intake" created in the last 7 days. If found → `is_followup = True`. Followup requires BOTH: (1) contact already existed (not just created), and (2) has a recent "Lead Intake" note.

**Lead Intake note writing:** After the followup check, Module A writes a "Lead Intake" note for ALL leads (new and existing) with a `wiseagent_client_id`. This note is what future runs will find when determining followup status. The note is written AFTER the followup check so the current note doesn't count for the current lead.

New contact creations are logged to the `contact_creation_log` Postgres table for audit/batch-fix purposes.

**OAuth handling:** Reads `f/switchboard/wiseagent_oauth`, checks token expiry, refreshes via `https://sync.thewiseagent.com/WiseAuth/token` if expired, writes refreshed tokens back to the Windmill resource.

**Fields added to each lead:**
- `wiseagent_client_id` — CRM client ID (always populated — created if new)
- `is_new` — true if contact was just created
- `has_nda` — true if contact has "NDA Signed" category
- `is_followup` — true if existing contact has a "Lead Intake" note from the last 7 days
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

The largest module. Selects an email template for each lead based on source type and context, then creates Gmail drafts via the Gmail API.

**Name validation:** Uses `get_first_name()` which validates the first word of the lead's name against a set of ~500 common US first names (SSA data). If recognized → "Hey John,". If not recognized (company names like "Bridgerow Blinds") → "Hey there,".

**Template selection logic (order matters):**

| Priority | Source Type | Condition | Template | Signed By |
|----------|------------|-----------|----------|-----------|
| 1 | `realtor_com` | — | Tour inquiry response | Jake |
| 2 | `seller_hub` | — | Seller outreach | Jake |
| 3 | Any | All properties are lead magnets | Lead magnet response (uses `response_override`) | Jake |
| 4 | `crexi_om` / `crexi_flyer` / `loopnet` | Multiple properties, followup | `commercial_multi_property_followup` | Larry |
| 5 | `crexi_om` / `crexi_flyer` / `loopnet` | Multiple properties, first contact | `commercial_multi_property_first_contact` | Larry |
| 6 | `crexi_om` / `crexi_flyer` / `loopnet` | Single property, followup | `commercial_followup_template` | Larry |
| 7 | `crexi_om` / `crexi_flyer` / `loopnet` | Single property, first contact | `commercial_first_outreach_template` | Larry |
| 8 | Unknown | — | Skip (no draft created) | — |

**Commercial templates (Crexi/LoopNet):** All commercial templates are signed by Larry with phone (734) 732-3789. No brochure highlights are included. Multi-property first contact uses inline property listing: "123 Main in Ann Arbor and 456 Oak in Ypsilanti" (Oxford comma for 3+). Each template has a matching SMS version.

**Followup detection:** Comes entirely from Module A (WiseAgent notes). Module D does NOT check Gmail sent folder.

**Gmail draft creation** is a single API call per draft — `drafts().create()`. No custom headers are added because **Gmail strips all custom X- headers when a draft is sent**. Instead, the `thread_id` returned by the create call is stored and used for SENT matching (thread IDs are stable across draft→sent transitions).

Each draft object includes: email content, template used, SMS body (if phone available), Gmail draft/thread IDs, and creation status.

**OAuth:** Uses `f/switchboard/gmail_oauth` for `teamgotcher@gmail.com`.

---

### Module E: Approval Gate

| Field | Value |
|-------|-------|
| **ID** | `e` |
| **Language** | Python 3.12 |
| **Input** | `results.d` |
| **Output** | `{ signal_id, created_at, resume_url, cancel_url, draft_count }` |
| **Suspend** | `required_events: 1, timeout: 31536000` (1 year) |
| **stop_after_if** | `result.skipped == true` — terminates flow cleanly when no drafts exist |

If there are no drafts (e.g., lead had no email, or all leads were info requests), Module E returns `{ skipped: true }` and the flow terminates immediately via `stop_after_if` — no signal is created and no zombie flow is left behind.

Otherwise, writes a signal to the `jake_signals` Postgres table, then **suspends the Windmill flow** until an external system POSTs to the resume URL.

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
- **Sent:** Polling trigger → `f/switchboard/gmail_pubsub_webhook` → thread_id match → resumes the flow in ~1 minute
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

After Module E suspends, the flow is frozen. Three things can wake it up:

| Trigger | Mechanism | Speed | What happens |
|---------|-----------|-------|-------------|
| Jake sends a draft | Polling trigger → webhook → thread_id match → POST to `resume_url` | ~1 minute | Module F runs (CRM update + SMS) |
| Jake deletes a draft | `gmail-draft-deletion-watcher` (Apps Script daily poll) → POST to `resume_url` with `action: "draft_deleted"` | Up to 24 hours | Module F runs (CRM rejection note) |
| Nothing happens | — | — | Flow stays suspended (1 year timeout) — visible reminder in Windmill |

### How Windmill Suspend/Resume Works

When Module E's code finishes, Windmill's suspend feature pauses the flow. `wmill.get_resume_urls()` generates two cryptographically signed URLs:

- **`resume_url`**: `https://rrg-server.tailc01f9b.ts.net:8443/api/w/rrg/jobs_u/resume/{JOB_ID}/{RESUME_ID}/{SIGNATURE}`
- **`cancel_url`**: `https://rrg-server.tailc01f9b.ts.net:8443/api/w/rrg/jobs_u/cancel/{JOB_ID}/{RESUME_ID}/{SIGNATURE}`

The signature baked into the URL provides authentication. Any system that knows the URL can POST to it.

**Resuming (POST to `resume_url`):** The JSON body of the POST becomes the `resume` variable in the next module's `input_transforms`. Module F maps this as `resume_payload`. Windmill also preserves all prior module outputs (`results.a` through `results.e`) across the suspend, so Module F can access `results.d` (Module D's output) directly.

**Cancelling (POST to `cancel_url`):** The flow is immediately terminated. Module F never runs. The cancellation payload becomes the flow's final result.

### Thread ID Matching (Sent Detection)

When a draft is sent from Gmail, the webhook matches the sent email back to its lead intake signal using **thread_id**. Gmail preserves the thread_id across the draft→sent transition (unlike draft_id and message_id, which change).

**Why not X-headers?** Gmail strips ALL custom `X-` headers when drafts are sent. Only 7 standard headers survive (`Content-Type`, `Date`, `From`, `MIME-Version`, `Message-ID`, `Subject`, `To`). Thread_id is the only stable identifier.

**Matching logic** (`find_and_update_signal_by_thread`):
1. Webhook receives a SENT message, fetches its `threadId` via Gmail API (`format='minimal'`)
2. Queries `jake_signals` with a JSONB search: `WHERE detail->'draft_id_map' contains a draft with matching thread_id`
3. If found: marks signal as `acted`, returns `resume_url` and matched `draft_id`
4. POSTs to `resume_url` with `{ action: "email_sent", draft_id, sent_at }`

```sql
-- JSONB query to find signal by thread_id (matches both lead_intake and lead_conversation signals)
UPDATE public.jake_signals
SET status = 'acted', acted_by = 'gmail_pubsub', acted_at = NOW()
WHERE status = 'pending'
  AND source_flow IN ('lead_intake', 'lead_conversation')
  AND id = (
    SELECT s.id FROM public.jake_signals s,
    jsonb_each(s.detail->'draft_id_map') AS kv
    WHERE s.status = 'pending'
      AND s.source_flow IN ('lead_intake', 'lead_conversation')
      AND kv.value->>'thread_id' = %s
    LIMIT 1
  )
RETURNING id, resume_url, detail
```

**Full webhook flow** (`f/switchboard/gmail_pubsub_webhook`):

```
gmail_pubsub_webhook runs:
         │
         ├── Decode base64 → get historyId
         ├── Read stored cursor from f/switchboard/gmail_last_history_id
         ├── Query Gmail History API: "what changed since cursor?"
         │     → Returns list of messageAdded events
         │
         ├── For each message with SENT label:
         │     ├── Fetch threadId (minimal format, 1 API call)
         │     ├── Search jake_signals for matching thread_id
         │     │     ├── Found → POST to resume_url (Module F runs)
         │     │     └── Not found → skip (normal sent email)
         │
         ├── For each message with INBOX label:
         │     ├── Fetch sender + subject (metadata only)
         │     ├── Categorize → apply Gmail label
         │     ├── If lead source: fetch full body, parse lead data
         │     └── Add parsed lead to leads_batch
         │
         ├── If leads_batch not empty:
         │     └── Group by email, fire one lead_intake flow per person
         │
         └── Save new historyId to f/switchboard/gmail_last_history_id
```

**Gmail History ID explained:** Every change in a Gmail mailbox increments a counter. When the webhook runs, it asks Gmail "what happened between my last checkpoint and now?" This range query handles batched changes (e.g., 3 emails sent quickly may produce only 1 notification).

### Polling Trigger

Google Pub/Sub push cannot reach Windmill because rrg-server is behind Tailscale (no public push endpoint). Instead, a **polling trigger** checks Gmail every minute.

**Script:** `f/switchboard/gmail_polling_trigger`
**Schedule:** `0 */1 * * * *` (every 1 minute, Windmill 6-field cron)

```
Every 1 minute:
         │
    Get Gmail profile → current historyId
         │
    Compare to f/switchboard/gmail_last_history_id
         │
    ┌────┴────┐
    │ Same?   │──── yes → return { skipped: true }
    └────┬────┘
         │ no (changes detected)
         ▼
    Build simulated Pub/Sub message (same format as real push)
    Call wmill.run_script_async("f/switchboard/gmail_pubsub_webhook")
         │
    return { triggered: true, webhook_job_id: ... }
```

**Why `run_script_async`?** Using synchronous `run_script` would deadlock — the polling trigger holds a worker slot while waiting for the webhook, but the webhook needs a free worker slot to run. Async dispatch avoids this.

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
| `f/switchboard/claude_endpoint_url` | Claude API proxy URL on jake-macbook (`http://100.108.74.112:8787`) |

**Windmill Scripts (all under `f/switchboard/`):**

| Script | Purpose |
|--------|---------|
| `get_pending_draft_signals` | Query pending lead_intake signals with draft_id_map (used by Apps Script) |
| `gmail_pubsub_webhook` | Processes Gmail changes — SENT: thread_id match → triggers resume; INBOX: categorizes, labels, triggers lead intake; reply detection → triggers lead_conversation |
| `gmail_polling_trigger` | Polls Gmail every 1 min, dispatches webhook async if history changed (replaces Pub/Sub push) |
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
4. ~~`sent_at` never populated~~ — **Fixed:** Both webhook and Apps Script now include `sent_at` in resume payloads.
5. ~~`timeout: 0` zombie flows~~ — **By design:** Suspended flows are visible reminders. With hopper architecture, each has exactly 1 draft.
6. ~~Pub/Sub webhook `lead_data` ignored~~ — **Fixed:** Removed dead-weight `lead_data` from resume payload.
7. ~~Lead parsing fails silently~~ — **Mitigated:** `validate_lead()` cross-checks fields. Failed/invalid parses downgrade to "Unlabeled" label. New contact creations logged to `contact_creation_log` table for retroactive batch-fix.
8. ~~Gmail strips custom X-headers when drafts are sent~~ — **Fixed:** Removed all `X-Lead-Intake-*` headers from Module D. SENT matching now uses thread_id (stable across draft→sent) via JSONB query on `jake_signals.detail.draft_id_map`.
9. ~~Pub/Sub push can't reach Windmill behind Tailscale~~ — **Fixed:** Added polling trigger (`f/switchboard/gmail_polling_trigger`) that runs every 1 minute and dispatches webhook async. ~1 minute latency instead of ~2 seconds, but reliable.
10. ~~Zombie flows when no drafts exist~~ — **Fixed:** Added `stop_after_if: result.skipped == true` on Module E. Flows with no drafts (no email, info requests only) terminate cleanly instead of suspending forever.

**Resolved (Feb 19, 2026):**
11. ~~Followup detection broken — `check_followup` searched notes for "outreach sent" / "initial outreach" but no note ever contained those phrases~~ — **Fixed:** Module A now checks for "Lead Intake" notes from the last 7 days AND writes a "Lead Intake" note for every lead processed. Gmail sent-folder check in Module D removed.
12. ~~Commercial templates signed by Jake instead of Larry~~ — **Fixed:** All Crexi/LoopNet templates now signed by Larry with phone (734) 732-3789. No brochure highlights. Name validation against ~500 SSA names (company names get "Hey there,").

**Remaining:**
- **Lead parsing is regex-based.** If a notification source changes their email format, the parser may fail. Downgrade-to-Unlabeled makes format changes visible (emails pile up in Unlabeled). Monitor `downgraded_to_unlabeled: true` in webhook output.
- **No automated backups** for `jake_signals` or `contact_creation_log` tables.

---

## GCP Setup (One-Time)

The Gmail watch requires a Pub/Sub topic in the same GCP project as the OAuth client credentials.

**Project:** `rrg-gmail-automation` (TeamGotcher Google account)
**Topic:** `gmail-sent-notifications`

**Note:** Pub/Sub push subscriptions cannot reach Windmill (behind Tailscale). The polling trigger (`f/switchboard/gmail_polling_trigger`) replaces push delivery. The Pub/Sub topic and Gmail watch are still required for the Gmail History API to work — the watch tells Gmail to track changes, even though we poll for them instead of receiving pushes.

**If setting up from scratch (GCP Console):**
1. Go to Pub/Sub → Topics → Create Topic: `gmail-sent-notifications`
2. On the topic, add IAM binding: `gmail-api-push@system.gserviceaccount.com` → role `Pub/Sub Publisher`
3. (Push subscription is optional — polling trigger handles delivery)
4. Run `f/switchboard/setup_gmail_watch` to activate the watch
5. Create schedule `f/switchboard/gmail_polling_schedule` — cron `0 */1 * * * *` — targeting `f/switchboard/gmail_polling_trigger`

---

## Related

- **Lead Conversation Engine:** [`docs/LEAD_CONVERSATION_ENGINE.md`](LEAD_CONVERSATION_ENGINE.md) — handles replies to outreach emails (classification, response drafts, approval)

---

*Last updated: February 20, 2026 — Added reply detection (unlabeled emails → thread_id match → lead_conversation), updated SENT path SQL to match both lead_intake and lead_conversation signals, added claude_endpoint_url variable*
