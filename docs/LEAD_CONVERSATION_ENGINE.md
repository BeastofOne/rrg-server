# Lead Conversation Engine

> **Flow path:** `f/switchboard/lead_conversation`
> **Last verified:** February 20, 2026

The lead conversation engine processes replies to outreach emails from commercial (Crexi, LoopNet, BizBuySell) and residential (Realtor.com, Seller Hub, Social Connect, UpNest) leads. It classifies the lead's intent using source-appropriate prompts, generates a response draft, and follows the same approval pattern as the lead intake pipeline.

---

## Table of Contents

- [Trigger: Reply Detection](#trigger-reply-detection)
- [Pipeline Overview](#pipeline-overview)
- [Module Reference](#module-reference)
  - [Module A: Classify Reply](#module-a-classify-reply)
  - [Module B: Generate Response](#module-b-generate-response)
  - [Module C: Approval Gate](#module-c-approval-gate)
  - [Module D: Post-Approval](#module-d-post-approval)
- [Intent Classifications](#intent-classifications)
- [Resume Mechanism](#resume-mechanism)
- [Windmill Resources and Variables](#windmill-resources-and-variables)

---

## Trigger: Reply Detection

The conversation engine is triggered by `f/switchboard/gmail_pubsub_webhook` during its INBOX processing. When an email doesn't match any lead notification format (Crexi, LoopNet, Realtor.com, Seller Hub), it's classified as "Unlabeled." Before applying the Unlabeled label, the webhook checks whether the email is a reply to our outreach:

```
Unlabeled INBOX email arrives
         │
    Get thread_id from message
         │
    Query jake_signals:
    "Does any ACTED signal (lead_intake or lead_conversation)
     have this thread_id in its draft_id_map?"
         │
    ┌────┴────┐
    │  Match  │──── no ─── Apply "Unlabeled" label (done)
    └────┬────┘
         │ yes
         ▼
    Apply "Lead Reply" label (remove "Unlabeled")
    Fetch full message body
         │
    Build reply_data:
    { thread_id, message_id, reply_body, reply_subject,
      reply_from, lead_email, lead_name, lead_phone,
      source, source_type, wiseagent_client_id,
      has_nda, properties, template_used }
         │
    POST http://localhost:8000/api/w/rrg/jobs/run/f/f/switchboard/lead_conversation
         │
         ▼
    Pipeline starts (Module A → D)
```

**Thread_id matching query:**

```sql
SELECT s.id, s.detail
FROM public.jake_signals s,
     jsonb_each(s.detail->'draft_id_map') AS kv
WHERE s.status = 'acted'
  AND s.source_flow IN ('lead_intake', 'lead_conversation')
  AND kv.value->>'thread_id' = %s
ORDER BY s.acted_at DESC
LIMIT 1
```

The reply_data is enriched with context from the matched signal: lead contact info, source metadata, WiseAgent client ID, NDA status, and the properties from the original outreach.

---

## Pipeline Overview

```
Input: { thread_id, message_id, reply_body, reply_subject, reply_from,
         lead_email, lead_name, lead_phone, source, source_type,
         wiseagent_client_id, has_nda, properties, template_used }

  Module A              Module B              Module C           Module D
  Classify Reply ───▶  Generate Response ──▶  Approval Gate ──▶  Post-Approval
  (fetch thread,       (create Gmail draft    (write signal,     (CRM update,
   classify via         or handle terminal     SUSPEND flow)      SMS send)
   Claude haiku)        states)

  Terminal states (flow stops at Module B):
  ├── IGNORE → CRM note only
  ├── ERROR → CRM note only
  └── INTERESTED/OFFER → notification signal + CRM note
```

---

## Module Reference

### Module A: Classify Reply

| Field | Value |
|-------|-------|
| **ID** | `a` |
| **Language** | Python 3.12 |
| **Input** | `flow_input` (reply_data from webhook) |
| **Output** | Classification result + thread context |

Fetches the full Gmail thread via `threads().get()`, formats messages chronologically (oldest first), then sends the thread context + latest reply to Claude (haiku model) for intent classification.

**Claude CLI:** Uses `subprocess.run(["claude", "-p", ...])` calling the Claude CLI installed in the Windmill worker container (`/usr/local/bin/claude`, teamgotcher account). Env vars `CLAUDE_CODE_OAUTH_TOKEN` and `CLAUDE_MODEL` passed through via `WHITELIST_ENVS`.

**Classification prompt branches by source type:**
- **Commercial** (Crexi, LoopNet, BizBuySell): CRE-specific wants (tour, om, financials, rent_roll, nda, etc.)
- **Residential buyer** (Realtor.com, UpNest buyer): Home-buying wants (tour, more_info, price, similar_homes, etc.)
- **Residential seller** (Seller Hub, Social Connect, UpNest seller): Home-selling wants (cma, home_value, commission, timeline, etc.)

**Classification output JSON:**
```json
{
  "classification": "INTERESTED|IGNORE|NOT_INTERESTED|ERROR",
  "sub_classification": "OFFER|WANT_SOMETHING|GENERAL_INTEREST|null",
  "wants": "what the lead is asking for (if WANT_SOMETHING)",
  "confidence": 0.0-1.0,
  "reasoning": "brief explanation"
}
```

**Fields added to output:**
- `classification`, `sub_classification`, `wants`, `confidence`, `reasoning`
- `thread_context` — formatted thread for Module B
- `latest_message_id_header` — `Message-ID` header from the reply (for `In-Reply-To`)
- All original `reply_data` fields passed through

---

### Module B: Generate Response

| Field | Value |
|-------|-------|
| **ID** | `b` |
| **Language** | Python 3.12 |
| **Input** | `results.a` (classification result) |
| **Output** | Response draft data or `{ skipped: true }` |
| **stop_after_if** | `result.skipped == true` — terminates flow for terminal states |

Routes by classification:

| Classification | Sub | Action | Terminal? |
|---------------|-----|--------|-----------|
| IGNORE | — | Write CRM note | Yes (`skipped: true`) |
| ERROR | — | Write CRM note | Yes (`skipped: true`) |
| INTERESTED | OFFER | Write notification signal + CRM note | Yes (`skipped: true`) |
| INTERESTED | WANT_SOMETHING | Look up property docs, generate response via Claude, create draft | No |
| INTERESTED | GENERAL_INTEREST | Generate follow-up via Claude, create draft | No |
| NOT_INTERESTED | — | Generate apology via Claude, create draft | No |

**Draft creation:** Creates Gmail reply drafts in the same thread:
```python
draft = service.users().drafts().create(
    userId='me',
    body={'message': {'raw': raw, 'threadId': thread_id}}
)
```

Drafts include `In-Reply-To` and `References` headers pointing to the reply's `Message-ID` so they thread correctly.

**Signing convention:** Determined by `determine_signer()` using the `f/switchboard/email_signatures` Windmill variable. Commercial leads (Crexi/LoopNet/BizBuySell) signed by Larry. Residential leads (Realtor.com, Seller Hub, Social Connect, UpNest) signed by Andrea. In-flight thread continuity preserved via `template_used` field.

**Response prompt frameworks branch by lead type:**
- **Commercial:** CRE-specific language (OM, NDA, brochure, financials, market status)
- **Residential buyer:** Home-buying language (showings, similar homes, neighborhood info)
- **Residential seller:** Home-selling language (CMA, commission, listing process, timeline)

**Document lookup (WANT_SOMETHING):** Checks `f/switchboard/property_mapping` for the property's `documents` field. If the requested document is available (non-null file path), includes it in the response. Currently all document paths are null — to be populated per property.

**SMS body:** For INTERESTED leads with phone numbers, Module B also generates an SMS body for post-approval delivery.

---

### Module C: Approval Gate

| Field | Value |
|-------|-------|
| **ID** | `c` |
| **Language** | Python 3.12 |
| **Input** | `results.b` (response data) |
| **Output** | `{ signal_id, resume_url, cancel_url }` |
| **Suspend** | `required_events: 1, timeout: 31536000` (1 year) |
| **stop_after_if** | `result.skipped == true` |

Same pattern as lead intake Module E. Writes a signal to `jake_signals`:

| Column | Value |
|--------|-------|
| `signal_type` | `"approval_needed"` |
| `source_flow` | `"lead_conversation"` |
| `summary` | Human-readable summary of the response |
| `detail` | JSON with `draft_id_map`, `drafts[]`, `resume_url`, `cancel_url` |
| `actions` | `["Approve", "Reject"]` |
| `status` | `"pending"` |

The `draft_id_map` uses the same structure as lead intake so the SENT detection path in `gmail_pubsub_webhook` works identically for both flows.

After writing the signal, the flow suspends.

---

### Module D: Post-Approval

| Field | Value |
|-------|-------|
| **ID** | `d` |
| **Language** | Python 3.12 |
| **Inputs** | `resume` (POST body from resume URL) + `results.b` (Module B output) |
| **Output** | `{ status, wiseagent_results[], sms_results[] }` |

Same pattern as lead intake Module F:

**`"email_sent"` path:**
1. Mark signal as acted
2. Send SMS (if lead has phone number and classification is INTERESTED)
3. Write WiseAgent CRM note: "Lead conversation reply sent. Classification: {classification}. SMS: {outcome}."

**`"draft_deleted"` path:**
1. Mark signal as acted
2. Write CRM rejection note: "Lead conversation draft rejected — deleted on {date}."

---

## Intent Classifications

### INTERESTED

The lead is engaging positively. Three sub-classifications:

| Sub | Meaning | Example | Action |
|-----|---------|---------|--------|
| **OFFER** | Lead is making or discussing an offer | "I'd like to offer $500K" | Terminal — signal created for Jake, no auto-reply |
| **WANT_SOMETHING** | Lead is requesting information or documents | "Can you send the rent roll?" | Look up docs in property_mapping, generate response |
| **GENERAL_INTEREST** | Lead expresses interest but no specific ask | "Tell me more about this property" | Generate general follow-up |

### IGNORE

Auto-replies, out-of-office messages, spam, newsletters, or unrelated emails. CRM note written, flow stops.

### NOT_INTERESTED

Lead explicitly declines, says wrong person, or requests removal. Apology draft created.

### ERROR

Unable to classify — garbled text, empty body, or unclear intent. CRM note written, flow stops.

---

## Resume Mechanism

Identical to lead intake. After Module C suspends:

| Trigger | Mechanism | Speed | Result |
|---------|-----------|-------|--------|
| Jake sends draft | Pub/Sub push → webhook → thread_id match → resume | ~2-5 seconds | Module D runs (CRM + SMS) |
| Jake deletes draft | Apps Script daily poll → resume with `draft_deleted` | Up to 24h | Module D runs (rejection note) |

The SENT path in `gmail_pubsub_webhook` now searches for pending signals from both `lead_intake` and `lead_conversation` (`source_flow IN ('lead_intake', 'lead_conversation')`).

---

## Windmill Resources and Variables

Uses the same resources as lead intake:

**Shared with lead intake:**
- `f/switchboard/gmail_oauth` — Gmail API access
- `f/switchboard/wiseagent_oauth` — CRM API access
- `f/switchboard/pg` — Postgres (jake_signals)
- `f/switchboard/property_mapping` — Property metadata + document paths
- `f/switchboard/sms_gateway_url` — SMS gateway endpoint
- `f/switchboard/router_token` — Windmill API token for triggering flows

---

## Not Yet Built

From the original plan, these remain:

1. **Automated follow-up** — Day 3/7/14 schedule for leads who haven't replied (the "Ignore" path re-engagement)
2. **Property document population** — All `documents` fields in `property_mapping` are currently null. Need to populate with actual file paths on rrg-server for each property.

---

*Last updated: February 25, 2026 — Migrated from deprecated HTTP claude_endpoint_url to subprocess Claude CLI in Windmill worker. E2E tested successfully.*
