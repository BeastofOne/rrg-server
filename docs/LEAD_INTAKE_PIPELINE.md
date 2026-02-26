# Lead Intake Pipeline

> **Flow path:** `f/switchboard/lead_intake`
> **Last verified:** February 26, 2026

The lead intake pipeline processes incoming CRE leads from Crexi, LoopNet, BizBuySell, Realtor.com, Seller Hub, Social Connect, and UpNest. It enriches leads with CRM data, generates personalized Gmail drafts, suspends for human approval, then completes CRM updates and SMS outreach after approval.

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
  - [Pub/Sub Push Delivery](#pubsub-push-delivery)
  - [Apps Script Fallback (Deletion Detection)](#apps-script-fallback-deletion-detection)
- [Windmill Resources and Variables](#windmill-resources-and-variables)
- [Known Issues](#known-issues)

---

## Trigger: Gmail Pub/Sub Webhook

The pipeline is triggered automatically by `f/switchboard/gmail_pubsub_webhook`. This webhook handles Gmail Pub/Sub push notifications from **two accounts** — each with its own OAuth resource and history cursor.

**Split inbox architecture:**
- **leads@resourcerealtygroupmi.com** — receives lead notifications (Crexi/LoopNet/BizBuySell/Realtor.com/Seller Hub/Social Connect/UpNest)
- **teamgotcher@gmail.com** — sends drafts, receives replies to outreach

Pub/Sub push notifications arrive within ~2-5 seconds via Tailscale Funnel (`https://rrg-server.tailc01f9b.ts.net:8443`).

```
New lead notification arrives in leads@resourcerealtygroupmi.com INBOX
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
    │ notifications.crexi.com          → label "Crexi"          │
    │ loopnet.com + "favorited"        → label "LoopNet"        │
    │ bizbuysell.com                   → label "BizBuySell"     │
    │ subject: "New realtor.com lead…" → label "Realtor.com"    │
    │ subject: "New Verified Seller…"  → label "Seller Hub"     │
    │ subject: "…Social Connect…"      → label "Social Connect" │
    │ everything else                  → label "Unlabeled"      │
    └─────────────────────────────────────────────────────────┘
         │
    Apply Gmail label to message
         │
    Is it a lead source? (Crexi/LoopNet/BizBuySell/Realtor.com/Seller Hub/Social Connect)
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
    STAGING + BATCHING: Write leads to staged_leads table
    Schedule delayed processing (30s window per unique email)
         │
    After 30s batch window (process_staged_leads script):
    Collect all staged leads for this email, fire one lead_intake flow
         │
    HOPPER ARCHITECTURE: One flow per person
    POST http://localhost:8000/api/w/rrg/jobs/run/f/f/switchboard/lead_intake
         { "leads": [all leads for this person from batch window] }
         │
         ▼
    Pipeline starts (Module A → F) — one flow per person
```

**Categorization patterns** (from notification sender/subject, no LLM needed):

| Source | Sender Match | Subject Match | Gmail Label | Lead Parse |
|--------|-------------|---------------|-------------|------------|
| Crexi | `notifications.crexi.com` | — | "Crexi" | Yes — dedicated parser (bare-line format: name from subject, email/phone on standalone lines) |
| LoopNet | `loopnet.com` | Contains "favorited" | "LoopNet" | Yes — generic parser (name from subject only, rarely has email/phone) |
| BizBuySell | `bizbuysell.com` | — | "BizBuySell" | Yes — generic parser (labeled: `Contact Name:`, `Contact Email:`, `Contact Phone:`) |
| Realtor.com | — | Starts with "New realtor.com lead" | "Realtor.com" | Yes — generic parser (labeled: `First Name:`, `Email Address:`, `Phone Number:`) |
| Seller Hub | `sellerappointmenthub.com` | Contains "New Verified Seller Lead" | "Seller Hub" | Yes — generic parser (labeled: `Seller Name:`, `Email:`, `Phone Number:`) |
| Social Connect | — | Contains "Social Connect" | "Social Connect" | Yes — dedicated parser (label/value pairs on alternating lines: `Name\n[value]\nEmail\n[value]`) |
| UpNest (claimed) | `upnest.com` | Contains "Lead claimed" | "UpNest" | Yes — dedicated parser (name/type/city from subject, email/phone from body labels) |
| UpNest (info) | `upnest.com` | Other UpNest emails | "UpNest" | No — label only (no contact info in non-claimed emails) |
| Reply to outreach | — | — (thread_id matches acted signal) | "Lead Reply" | No (triggers `lead_conversation`) |
| Everything else | — | — | "Unlabeled" | No |

**Parser architecture:**
- **Dedicated parsers** (`parse_crexi_lead`, `parse_social_connect_lead`, `parse_upnest_lead`): Handle non-standard formats that don't use label prefixes
- **Generic parser** (`parse_lead_from_notification` → `parse_email_field`/`parse_name_field`/`parse_phone_field`): Handles labeled formats (`Key: Value`) with subject-line name fallback and bare-line phone fallback
- **Email exclusion**: Filters out system/notification sender domains (crexi.com, loopnet.com, etc.) and specific addresses (support@crexi.com, teamgotcher@gmail.com). gmail.com is NOT excluded — most Crexi leads use personal Gmail
- **Crexi source types**: `crexi_om`, `crexi_ca`, `crexi_info_request`, `crexi_brochure`, `crexi_floorplan`, `crexi_flyer`

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

Only applies to `crexi_om`, `crexi_flyer`, `loopnet`, and `bizbuysell` source types. Other source types get `is_mapped: null`.

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

**Fuzzy property dedup:** Crexi uses different property name formats depending on notification type (e.g., "CMC Transportation" for phone clicks vs "CMC Transportation in Ypsilanti" for flyer views). The `is_same_property()` helper detects when one name is a prefix of the other and the remainder starts with " in " (the city suffix). When a fuzzy match is found, the longer/more-detailed name is kept. This prevents false multi-property grouping that would trigger the wrong email template.

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

| Priority | Source | Condition | Template | Signed By |
|----------|--------|-----------|----------|-----------|
| 1 | Realtor.com | `source.lower() == "realtor.com"` | Residential buyer inquiry (`realtor_com`) | Andrea |
| 2 | UpNest | `source == "upnest"` and `lead_type == "buyer"` | Residential buyer — "Buying a home?" (`residential_buyer`) | Andrea |
| 3 | Seller Hub, Social Connect, UpNest | `is_residential_seller` catch-all | Residential seller — "Selling your home?" (`residential_seller`) | Andrea |
| 4 | Any | All properties are lead magnets | Lead magnet response (`lead_magnet`) | Larry |
| 5 | Crexi / LoopNet / BizBuySell | Multiple properties, followup | `commercial_multi_property_followup` | Larry |
| 6 | Crexi / LoopNet / BizBuySell | Multiple properties, first contact | `commercial_multi_property_first_contact` | Larry |
| 7 | Crexi / LoopNet / BizBuySell | Single property, followup | `commercial_followup_template` | Larry |
| 8 | Crexi / LoopNet / BizBuySell | Single property, first contact | `commercial_first_outreach_template` | Larry |
| 9 | Unknown | — | Skip (no draft created) | — |

**Residential templates (Realtor.com, Seller Hub, Social Connect, UpNest):** All residential templates are signed by Andrea with phone (734) 223-1015. HTML signatures are appended automatically from the `f/switchboard/email_signatures` Windmill variable. Each template has a matching SMS version. Residential seller/buyer templates use `{city}` extracted via `get_city()` (UpNest: from subject parsing; Seller Hub/Social Connect: from property_address).

**Commercial templates (Crexi/LoopNet/BizBuySell):** All commercial templates are signed by Larry with phone (734) 732-3789. No brochure highlights are included. Multi-property first contact uses inline property listing: "123 Main in Ann Arbor and 456 Oak in Ypsilanti" (Oxford comma for 3+). Each template has a matching SMS version.

**Property display in templates:** `format_property_list_inline()` uses `property_address` when it has a real street address (3+ comma-delimited parts, e.g., "826 N Main St, Adrian, MI 49221" → "826 N Main St in Adrian"). For city-only addresses like "South Lyon, MI", it falls back to `canonical_name` from the property mapping.

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
- **Sent:** Pub/Sub push → `f/switchboard/gmail_pubsub_webhook` → thread_id match → resumes the flow in ~2-5 seconds
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
| Jake sends a draft | Pub/Sub push → webhook → thread_id match → POST to `resume_url` | ~2-5 seconds | Module F runs (CRM update + SMS) |
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

### Pub/Sub Push Delivery

Gmail Pub/Sub push notifications are delivered directly to the webhook via Tailscale Funnel. Windmill is publicly reachable at `https://rrg-server.tailc01f9b.ts.net:8443`, so push subscriptions work without polling.

**GCP Configuration:**
- Topic: `projects/rrg-gmail-automation/topics/gmail-sent-notifications`
- Push subscription → `https://rrg-server.tailc01f9b.ts.net:8443/api/w/rrg/webhooks/<token>/p/f/switchboard/gmail_pubsub_webhook`
- Both accounts (teamgotcher@ and leads@) publish to the same topic
- The webhook distinguishes accounts via the `emailAddress` field in the push notification

```
Gmail change detected (either account)
         │
    Gmail Watch → Pub/Sub topic → push subscription
         │
    POST to Windmill webhook (~2-5 seconds)
         │
    Webhook decodes emailAddress:
    ┌────┴────────────────────────────┐
    │ leads@?                         │
    │  → Use gmail_leads_oauth        │
    │  → Use gmail_leads_last_history │
    │  → Process INBOX leads only     │
    │                                 │
    │ teamgotcher@?                   │
    │  → Use gmail_oauth              │
    │  → Use gmail_last_history_id    │
    │  → Process SENT + reply detect  │
    └─────────────────────────────────┘
```

**Latency:** ~2-5 seconds from Gmail change to webhook execution (vs ~1 minute with the old polling trigger).

**Fallback:** The deprecated polling trigger (`f/switchboard/gmail_polling_trigger`) is kept but its schedule is disabled. It can be re-enabled in an emergency, but only polls teamgotcher@ — not leads@.

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
| `f/switchboard/gmail_oauth` | Gmail OAuth for teamgotcher@gmail.com (drafts, SENT, replies) |
| `f/switchboard/gmail_leads_oauth` | Gmail OAuth for leads@resourcerealtygroupmi.com (INBOX notifications) |
| `f/switchboard/pg` | Postgres connection (jake_signals table) |

**Variables (simple key-value):**

| Variable | Purpose |
|----------|---------|
| `f/switchboard/property_mapping` | JSON mapping of property aliases → canonical names with metadata |
| `f/switchboard/sms_gateway_url` | SMS gateway endpoint URL (pixel-9a, Crexi/LoopNet leads only) |
| `f/switchboard/gmail_last_history_id` | Gmail History API cursor for teamgotcher@ |
| `f/switchboard/gmail_leads_last_history_id` | Gmail History API cursor for leads@ |
| `f/switchboard/router_token` | Auth token used by gmail_pubsub_webhook for resume URL POSTs |
| `f/switchboard/email_signatures` | JSON config: signer profiles (name, phone, HTML signature), template-prefix-to-signer mapping, source-to-signer mapping |

**Windmill Scripts (all under `f/switchboard/`):**

| Script | Purpose |
|--------|---------|
| `get_pending_draft_signals` | Query pending lead_intake signals with draft_id_map (used by Apps Script) |
| `gmail_pubsub_webhook` | Processes Gmail Pub/Sub push notifications — split inbox: leads@ for notifications, teamgotcher@ for SENT/replies |
| `gmail_polling_trigger` | DEPRECATED — kept as emergency fallback, schedule disabled |
| `setup_gmail_watch` | Sets up Gmail SENT + INBOX label watch on teamgotcher@, renew every 6 days |
| `setup_gmail_leads_watch` | Sets up Gmail INBOX label watch on leads@, renew every 6 days |
| `check_gmail_watch_health` | Daily 10 AM ET — alerts via SMS if webhook hasn't run in 48h (covers both accounts) |
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
9. ~~Pub/Sub push can't reach Windmill behind Tailscale~~ — **Fixed:** Tailscale Funnel exposes Windmill publicly at `https://rrg-server.tailc01f9b.ts.net:8443`. Pub/Sub push subscription delivers notifications directly in ~2-5 seconds. Polling trigger deprecated.
10. ~~Zombie flows when no drafts exist~~ — **Fixed:** Added `stop_after_if: result.skipped == true` on Module E. Flows with no drafts (no email, info requests only) terminate cleanly instead of suspending forever.

**Resolved (Feb 19, 2026):**
11. ~~Followup detection broken — `check_followup` searched notes for "outreach sent" / "initial outreach" but no note ever contained those phrases~~ — **Fixed:** Module A now checks for "Lead Intake" notes from the last 7 days AND writes a "Lead Intake" note for every lead processed. Gmail sent-folder check in Module D removed.
12. ~~Commercial templates signed by Jake instead of Larry~~ — **Fixed:** All Crexi/LoopNet templates now signed by Larry with phone (734) 732-3789. No brochure highlights. Name validation against ~500 SSA names (company names get "Hey there,").

**Resolved (Feb 23, 2026):**
13. ~~Module C exact-match property dedup treats Crexi name variants as different properties~~ — **Fixed:** Added `is_same_property()` fuzzy matching to Module C. Detects "Name" vs "Name in City" pattern (e.g., "CMC Transportation" vs "CMC Transportation in Ypsilanti"). Keeps the longer name. Prevents false multi-property grouping that selected `commercial_multi_property_first_contact` instead of `commercial_first_outreach_template`.
14. ~~Module D `format_property_list_inline` produces "South Lyon in MI" for city-only property addresses~~ — **Fixed:** Falls back to `canonical_name` when `property_address` has fewer than 3 comma parts (i.e., no street address). Only uses "street in city" format for full addresses like "826 N Main St, Adrian, MI".
15. ~~Separate Pub/Sub pushes for same person create duplicate flows~~ — **Fixed:** Webhook now stages leads to `staged_leads` table and schedules a delayed `process_staged_leads` job (30s batch window). All notifications arriving within the window are collected into a single `lead_intake` flow per person.

**Remaining:**
- **Lead parsing is regex-based.** If a notification source changes their email format, the parser may fail. Downgrade-to-Unlabeled makes format changes visible (emails pile up in Unlabeled). Monitor `downgraded_to_unlabeled: true` in webhook output.
- **No automated backups** for `jake_signals` or `contact_creation_log` tables.

---

## GCP Setup (One-Time)

The Gmail watch requires a Pub/Sub topic in the same GCP project as the OAuth client credentials.

**Project:** `rrg-gmail-automation` (TeamGotcher Google account)
**Topic:** `gmail-sent-notifications`

Pub/Sub push subscriptions deliver notifications directly to the webhook via Tailscale Funnel (`https://rrg-server.tailc01f9b.ts.net:8443`).

**If setting up from scratch (GCP Console):**
1. Go to Pub/Sub → Topics → Create Topic: `gmail-sent-notifications`
2. On the topic, add IAM binding: `gmail-api-push@system.gserviceaccount.com` → role `Pub/Sub Publisher`
3. Create push subscription → `https://rrg-server.tailc01f9b.ts.net:8443/api/w/rrg/webhooks/<token>/p/f/switchboard/gmail_pubsub_webhook`
4. Run `f/switchboard/setup_gmail_watch` to activate the teamgotcher@ watch
5. Run `f/switchboard/setup_gmail_leads_watch` to activate the leads@ watch
6. Both watches publish to the same topic; the webhook distinguishes accounts via `emailAddress`

---

## Related

- **Lead Conversation Engine:** [`docs/LEAD_CONVERSATION_ENGINE.md`](LEAD_CONVERSATION_ENGINE.md) — handles replies to outreach emails (classification, response drafts, approval)

---

*Last updated: February 26, 2026 — Residential templates (Andrea signs all), UpNest parser + buyer/seller disambiguation, three-way source classification, lead magnet template (Larry signs), email_signatures variable for signer determination, stale claude_endpoint_url removed. E2E verified for all sources.*
