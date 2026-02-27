# E2E Pipeline Testing — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Implement all pre-test code fixes discovered during code review, then execute the 34-test E2E suite covering every branch of lead_intake and lead_conversation.

**Architecture:** Three phases: (1) dependency issues with ordering constraints, (2) remaining pre-test fixes, (3) code review gate + full E2E suite. Each fix is pushed to live Windmill and micro-tested before committing.

**Tech Stack:** Windmill (wmill CLI), Gmail API (messages.import), WiseAgent API, Postgres (psql via SSH), SMS gateway (pixel-9a)

---

## Prerequisites

**Credentials (from `~/.secrets/jake-system.json`):**
- Gmail OAuth for leads@: `google_oauth.claude_connector` project + `gmail.accounts.leads.refresh_token`
- Gmail OAuth for teamgotcher@: `google_oauth.rrg_gmail_automation` project + `gmail.accounts.teamgotcher.refresh_token`
- Windmill API token: `windmill.api_token`
- WiseAgent OAuth: via Windmill resource `f/switchboard/wiseagent_oauth`

**Windmill push command (ALWAYS use safe flags):**
```bash
wmill sync push --skip-variables --skip-secrets --skip-resources
```

**Rollback:** If any change breaks the pipeline, push the known-good main branch code:
```bash
cd ~/rrg-server && wmill sync push --skip-variables --skip-secrets --skip-resources
```

---

## Phase 1: Dependency Issues (8 tasks)

These have ordering constraints. Implement in this exact order.

---

### Task 1: Create oauth_token_backup table (C2 prerequisite)

**Why:** The C2 OAuth resilience code writes to this table. It must exist before the code is deployed.

**Step 1: Create the table on rrg-server Postgres**

```bash
ssh andrea@rrg-server
psql -U rrg -d rrg -c "
CREATE TABLE public.oauth_token_backup (
    service     TEXT PRIMARY KEY,
    token_data  JSONB NOT NULL,
    saved_at    TIMESTAMPTZ DEFAULT NOW()
);
"
```

**Step 2: Verify the table exists**

```bash
psql -U rrg -d rrg -c "\d public.oauth_token_backup"
```

Expected: table with columns `service`, `token_data`, `saved_at`.

**Step 3: Add status column to contact_creation_log (for CRM resilience fixes)**

```bash
psql -U rrg -d rrg -c "
ALTER TABLE public.contact_creation_log ADD COLUMN status TEXT DEFAULT 'created';
"
```

**Step 4: Verify**

```bash
psql -U rrg -d rrg -c "\d public.contact_creation_log"
```

Expected: new `status` column with default `'created'`.

**Step 5: Commit**

No code change — SQL only. Note in commit message.

```bash
git commit --allow-empty -m "chore: create oauth_token_backup table and add status column to contact_creation_log"
```

---

### Task 2: Extract WiseAgent API helper (S3 — do before C2 code changes)

**Why:** The C2 OAuth resilience and CRM retry fixes modify WiseAgent API call sites. Extracting the helper first means those fixes apply to one place per file instead of 4.

**Files:**
- Modify: `windmill/f/switchboard/lead_intake.flow/post_approval_(crm_+_sms).inline_script.py`
- Modify: `windmill/f/switchboard/lead_conversation.flow/post_approval_(crm_+_sms).inline_script.py`

**Step 1: Add `wa_post()` helper to Module F**

In `lead_intake.flow/post_approval_(crm_+_sms).inline_script.py`, add after the imports:

```python
def wa_post(token, request_type, data):
    """Make a WiseAgent API call."""
    resp = requests.post(
        BASE_URL + f"?requestType={request_type}",
        data=data,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/x-www-form-urlencoded"},
        timeout=15
    )
    resp.raise_for_status()
    return resp
```

Replace all 4 call sites (rejection note ~line 108, status update ~line 185, outreach note ~line 214, SMS note ~line 234) with one-liner `wa_post(token, "addContactNote", note_data)` or `wa_post(token, "updateContact", update_data)` calls.

**Step 2: Add `wa_post()` helper to Module D**

Same extraction in `lead_conversation.flow/post_approval_(crm_+_sms).inline_script.py`. Replace both call sites (rejection note ~line 108, reply note ~line 191). Note: `get_wa_token()` uses a different endpoint (`TOKEN_URL`), not `wa_post()`.

**Step 3: Push to Windmill and verify**

```bash
wmill sync push --skip-variables --skip-secrets --skip-resources
```

Seed one test lead through lead_intake, send the draft. Verify Module F email_sent path matches pre-refactor behavior: CRM status updated, outreach note added, SMS note added. Then seed another lead, and DELETE the draft to verify the rejection path: Module F should add a rejection note via `wa_post()`. Then seed a conversation reply, send the reply draft. Verify Module D output matches.

**Step 4: Commit**

```bash
git add windmill/f/switchboard/lead_intake.flow/post_approval_\(crm_+_sms\).inline_script.py \
        windmill/f/switchboard/lead_conversation.flow/post_approval_\(crm_+_sms\).inline_script.py
git commit -m "refactor: extract wa_post() helper in Module F and Module D"
```

---

### Task 3: WiseAgent OAuth token save resilience (C2)

**Why:** Silent `except: pass` on token save has caused two full outages. Fix all 4 files.

**Files:**
- Modify: `windmill/f/switchboard/lead_intake.flow/wiseagent_lookup_+_create.inline_script.py` (Module A `get_token()`)
- Modify: `windmill/f/switchboard/lead_intake.flow/post_approval_(crm_+_sms).inline_script.py` (Module F `get_token()`)
- Modify: `windmill/f/switchboard/lead_conversation.flow/generate_response_draft.inline_script.py` (Module B `get_wa_token()`)
- Modify: `windmill/f/switchboard/lead_conversation.flow/post_approval_(crm_+_sms).inline_script.py` (Module D `get_wa_token()`)

**Step 1: Update each `get_token()`/`get_wa_token()` function**

In each file, replace the `except: pass` on `wmill.set_resource()` with:
1. Save BEFORE using the new token
2. Retry 2-3 times with brief pause
3. On final failure: write to `oauth_token_backup` table via Postgres
4. Log the error visibly in Windmill output

**Step 2: Push and verify**

```bash
wmill sync push --skip-variables --skip-secrets --skip-resources
```

Seed a test lead (exercises Module A). Send the draft (exercises Module F). Seed a conversation reply (exercises Module B). Send the reply draft (exercises Module D). Check Windmill job output for each — confirm "save first" ordering. Check `oauth_token_backup` table for a row if a refresh happened.

**Step 3: Commit**

```bash
git add windmill/f/switchboard/lead_intake.flow/wiseagent_lookup_+_create.inline_script.py \
        windmill/f/switchboard/lead_intake.flow/post_approval_\(crm_+_sms\).inline_script.py \
        windmill/f/switchboard/lead_conversation.flow/generate_response_draft.inline_script.py \
        windmill/f/switchboard/lead_conversation.flow/post_approval_\(crm_+_sms\).inline_script.py
git commit -m "fix: add retry + Postgres backup for WiseAgent OAuth token save (C2)"
```

---

### Task 4: Resume failure recovery (C4)

**Why:** If resume call fails after signal marked acted, signal is stuck. Fix: roll back to pending on failure.

**Files:**
- Modify: `windmill/f/switchboard/gmail_pubsub_webhook.py` (SENT processing path, after `trigger_resume()`)

**Step 1: Add HTTP response check after `trigger_resume()`**

After the `trigger_resume()` call in the SENT path, check the status code. If 5xx or timeout: UPDATE the signal back to `pending`, raise error. If 2xx/4xx: leave as acted.

**Step 2: Push and verify**

```bash
wmill sync push --skip-variables --skip-secrets --skip-resources
```

Seed a test lead, send the draft. Verify signal is `status = 'acted'` and Module F completed. The rollback path is code-review only.

**Step 3: Commit**

```bash
git add windmill/f/switchboard/gmail_pubsub_webhook.py
git commit -m "fix: roll back signal to pending when resume fails (C4)"
```

---

### Task 5: Propagate lead_type through pipeline (I6 — atomic deploy)

**Why:** UpNest buyer/seller routing depends on this. All 5 files must be pushed together.

**Files:**
- Modify: `windmill/f/switchboard/lead_intake.flow/generate_drafts_+_gmail.inline_script.py` (add `lead_type` to draft dict)
- Modify: `windmill/f/switchboard/gmail_pubsub_webhook.py` (`find_outreach_by_thread()` — return `lead_type`)
- Modify: `windmill/f/switchboard/lead_conversation.flow/fetch_thread_+_classify_reply.inline_script.py` (pass `lead_type` through)
- Modify: `windmill/f/switchboard/lead_conversation.flow/generate_response_draft.inline_script.py` (use `lead_type` for prompt selection)
- Modify: `windmill/f/switchboard/lead_conversation.flow/flow.yaml` (add `lead_type` to schema)

**Step 1: Implement all 5 changes locally**

Per-file specifics:
1. **Module D draft dict** (`generate_drafts_+_gmail.inline_script.py`): Add `"lead_type": lead.get("lead_type", "")` to the draft dict (around line 256-269, alongside `has_nda`).
2. **Webhook** (`gmail_pubsub_webhook.py`): In `find_outreach_by_thread()`, add `"lead_type": matched_draft.get("lead_type", "")` to the return dict (around line 922-933).
3. **Conversation Module A** (`fetch_thread_+_classify_reply.inline_script.py`): Read `lead_type` from the incoming `reply_data` dict and include it in the return dict. Without this, `lead_type` enters from the webhook but gets dropped before Module B sees it.
4. **Conversation Module B** (`generate_response_draft.inline_script.py`): Check `lead_type` directly for buyer vs seller prompt selection, instead of inferring from `template_used`.
5. **Flow schema** (`flow.yaml`): Add `lead_type: type: string` to the input schema.

**Step 2: Push ALL 5 files in one push**

```bash
wmill sync push --skip-variables --skip-secrets --skip-resources
```

**Step 3: Verify**

Seed one UpNest buyer lead and one UpNest seller lead. After drafts appear, query jake_signals — confirm `lead_type` is `"buyer"` and `"seller"` in the signal detail JSON. Send the buyer draft, seed a reply, verify conversation engine selected residential BUYER prompt.

**Step 4: Commit**

```bash
git add windmill/f/switchboard/lead_intake.flow/generate_drafts_+_gmail.inline_script.py \
        windmill/f/switchboard/gmail_pubsub_webhook.py \
        windmill/f/switchboard/lead_conversation.flow/fetch_thread_+_classify_reply.inline_script.py \
        windmill/f/switchboard/lead_conversation.flow/generate_response_draft.inline_script.py \
        windmill/f/switchboard/lead_conversation.flow/flow.yaml
git commit -m "feat: propagate lead_type as first-class field through pipeline (I6)"
```

---

### Task 6: Don't mark leads as done until processed (C1)

**Why:** If trigger call fails, leads are permanently marked handled but never processed.

**Files:**
- Modify: `windmill/f/switchboard/process_staged_leads.py`

**Step 1: Implement claim/unclaim pattern**

After the intake trigger call, check HTTP response. On failure: set `processed = FALSE`, send SMS to Jake, raise error. Move timer lock deletion to success path only. Remove `except: pass` on timer lock delete.

**Step 2: Push and verify**

```bash
wmill sync push --skip-variables --skip-secrets --skip-resources
```

Seed a test lead, let it process. Query `staged_leads` — rows `processed = TRUE`. Query `processed_notifications` — timer lock deleted. Check Windmill output for trigger success.

**Step 3: Commit**

```bash
git add windmill/f/switchboard/process_staged_leads.py
git commit -m "fix: unclaim leads and alert on trigger failure, delete timer lock only on success (C1)"
```

---

### Task 7: City extraction for 4 residential sources (I5)

**Why:** Draft templates say "selling your home in [city]" but city extraction is broken for most sources.

**Files:**
- Modify: `windmill/f/switchboard/gmail_pubsub_webhook.py` (Seller Hub, Social Connect, Realtor.com parsers)
- Modify: `windmill/f/switchboard/lead_intake.flow/property_match.inline_script.py` (set `property_address` for non-commercial)
- Modify: `windmill/f/switchboard/lead_intake.flow/generate_drafts_+_gmail.inline_script.py` (`get_city()`)

**Step 1: Update parsers**

- Seller Hub: extract `property_address` from body ("Property Address: ...")
- Social Connect: extract `property_address` from body
- Realtor.com: make city extraction explicit
- UpNest Buyer: already working (city from subject)

**Step 2: Push and verify each source**

```bash
wmill sync push --skip-variables --skip-secrets --skip-resources
```

1. Seed Seller Hub lead with "Property Address: 456 Test St, Ypsilanti, MI 48197". Verify draft says "selling your home in Ypsilanti".
2. Seed Social Connect lead with "789 Test Blvd, Saline, MI". Verify "selling your home in Saline".
3. Seed UpNest buyer with "in Pinckney" in subject. Verify "purchase a home in Pinckney".
4. Seed Realtor.com lead with "123 Test Ave, Ann Arbor". Verify city "Ann Arbor".

**Step 3: Commit**

```bash
git add windmill/f/switchboard/gmail_pubsub_webhook.py \
        windmill/f/switchboard/lead_intake.flow/property_match.inline_script.py \
        windmill/f/switchboard/lead_intake.flow/generate_drafts_+_gmail.inline_script.py
git commit -m "fix: explicit city extraction for Seller Hub, Social Connect, Realtor.com (I5)"
```

---

### Task 8: Collapse Crexi source types (deploy safely)

**Why:** 7 Crexi sub-types are unnecessary complexity. All Crexi leads are just "crexi".

**Files:**
- Modify: `windmill/f/switchboard/gmail_pubsub_webhook.py` (delete `determine_crexi_source_type()`, replace call with `"crexi"`)
- Modify: `windmill/f/switchboard/lead_intake.flow/property_match.inline_script.py` (update source_type check)
- Modify: `windmill/f/switchboard/lead_intake.flow/dedup_and_group.inline_script.py` (delete info_request split)

**Step 1: Implement all 3 changes**

Delete `determine_crexi_source_type()`. Replace call site with `"crexi"`. Update `property_match` to accept `"crexi"` (temporarily also accept old values during transition). Delete lines 20-22 in `dedup_and_group` (info_request split).

**Step 2: Push during quiet period**

```bash
wmill sync push --skip-variables --skip-secrets --skip-resources
```

**Step 3: Verify**

Seed one Crexi OM lead and one Crexi info request. Both should get `source_type: "crexi"`, both should produce drafts. Verify Module C has zero info_requests.

**Step 4: After 1 minute, push final version**

Remove the transitional old values from `property_match` — only accept `"crexi"`.

```bash
wmill sync push --skip-variables --skip-secrets --skip-resources
```

**Step 5: Commit**

```bash
git add windmill/f/switchboard/gmail_pubsub_webhook.py \
        windmill/f/switchboard/lead_intake.flow/property_match.inline_script.py \
        windmill/f/switchboard/lead_intake.flow/dedup_and_group.inline_script.py
git commit -m "fix: collapse Crexi source types to just 'crexi', remove info_request split"
```

---

## Phase 2: Remaining Pre-Test Changes (14 tasks)

These are independent and can be done in any order. Grouped by file to minimize push/verify cycles.

---

### Task 9: BCC leads@ + BCC filter (atomic deploy)

**Files:**
- Modify: `windmill/f/switchboard/lead_intake.flow/generate_drafts_+_gmail.inline_script.py` (add BCC header)
- Modify: `windmill/f/switchboard/lead_conversation.flow/generate_response_draft.inline_script.py` (add BCC header)
- Modify: `windmill/f/switchboard/gmail_pubsub_webhook.py` (skip teamgotcher@ sender in leads@ processing)

**Step 1: Add BCC to both draft creation functions**

Add `message['bcc'] = 'leads@resourcerealtygroupmi.com'` in both files.

**Step 2: Add sender skip in webhook**

Early in the INBOX message processing loop: if sender is `teamgotcher@gmail.com`, skip before parsing.

**Step 3: Push ALL changes in one push**

```bash
wmill sync push --skip-variables --skip-secrets --skip-resources
```

**Step 4: Verify**

Seed a Crexi test lead. Check intake draft headers for BCC field. Send the draft. Verify leads@ got a copy AND the BCC copy was skipped by the webhook (no phantom intake). Then seed a conversation reply to create a reply draft — check that reply draft also has BCC header set to `leads@resourcerealtygroupmi.com`.

**Step 5: Commit**

```bash
git add windmill/f/switchboard/lead_intake.flow/generate_drafts_+_gmail.inline_script.py \
        windmill/f/switchboard/lead_conversation.flow/generate_response_draft.inline_script.py \
        windmill/f/switchboard/gmail_pubsub_webhook.py
git commit -m "feat: BCC leads@ on all outbound emails + filter to prevent loop"
```

---

### Task 10: Postgres try/finally cleanup (12 files)

**Files:** All 12 files listed in design doc "Always Close Postgres Connections on Errors" section.

**Step 1: Wrap all `psycopg2.connect()` call sites in try/finally or with statements**

Structural change only — no behavior change. Go through each of the 12 files.

**Step 2: Push and verify**

```bash
wmill sync push --skip-variables --skip-secrets --skip-resources
```

Seed one test lead through the full pipeline. Verify it completes identically to before. Check Postgres connection count before and after.

**Step 3: Commit**

```bash
git add <all 12 files>
git commit -m "fix: always close Postgres connections on errors (try/finally in 12 files)"
```

---

### Task 11: Remove silent failure on signal status update (I8) + write_crm_note

**Files:**
- Modify: `windmill/f/switchboard/lead_intake.flow/post_approval_(crm_+_sms).inline_script.py` (`mark_signal_acted()`)
- Modify: `windmill/f/switchboard/lead_conversation.flow/post_approval_(crm_+_sms).inline_script.py` (`mark_signal_acted()`)
- Modify: `windmill/f/switchboard/lead_conversation.flow/generate_response_draft.inline_script.py` (`write_crm_note()`)

**Step 1: Remove `except: pass` from `mark_signal_acted()` in both Module F and Module D files**

Let the exception propagate. It runs before any CRM/SMS work, so no duplicate risk.

**Step 2: Log `write_crm_note()` failures in conversation Module B**

`write_crm_note()` (line 64-78 of `generate_response_draft.inline_script.py`) wraps the entire CRM note write in `except: pass`. Used for IGNORE, ERROR, and OFFER terminal paths. Replace with `except Exception as e: print(f"CRM note failed: {e}")` so the failure is at least logged in Windmill output. Don't crash the flow — CRM notes are supplementary to the signal+SMS alerts added by Tasks 15-19.

**Step 3: Push and verify**

```bash
wmill sync push --skip-variables --skip-secrets --skip-resources
```

Send a pending test draft. Query jake_signals — confirm signal is acted.

**Step 4: Commit**

```bash
git add windmill/f/switchboard/lead_intake.flow/post_approval_\(crm_+_sms\).inline_script.py \
        windmill/f/switchboard/lead_conversation.flow/post_approval_\(crm_+_sms\).inline_script.py \
        windmill/f/switchboard/lead_conversation.flow/generate_response_draft.inline_script.py
git commit -m "fix: remove except:pass on mark_signal_acted and write_crm_note (I8)"
```

---

### Task 12: CRM contact creation resilience

**Files:**
- Modify: `windmill/f/switchboard/lead_intake.flow/wiseagent_lookup_+_create.inline_script.py` (CRM creation block, lines 179-203)

**Step 1: Implement 4-layer resilience**

1. Retry WiseAgent API call (3 attempts, 2s pause)
2. On final failure: continue with `client_id = None`
3. SMS to Jake + email to teamgotcher@
4. Log to `contact_creation_log` with `status = 'failed'`

**Step 2: Push and verify**

```bash
wmill sync push --skip-variables --skip-secrets --skip-resources
```

Seed a test lead with new email. Verify CRM contact created, `contact_creation_log` row has `status = 'created'`. No SMS/email alert (success = silent). Failure path is code-review only.

**Step 3: Commit**

```bash
git add windmill/f/switchboard/lead_intake.flow/wiseagent_lookup_+_create.inline_script.py
git commit -m "fix: retry + alert + log on CRM contact creation failure"
```

---

### Task 13: CRM post-approval update resilience

**Prerequisite:** Task 2 (S3 wa_post extraction). This task modifies the same CRM call sites in Module F. Task 2 extracts them into `wa_post()` first, so the retry logic here applies to the helper instead of 4 raw call sites.

**Files:**
- Modify: `windmill/f/switchboard/lead_intake.flow/post_approval_(crm_+_sms).inline_script.py` (CRM update block, lines 181-246)

**Step 1: Break single try/except into 3 independent blocks**

Each block (status update, outreach note, SMS note) retries independently (3 attempts, 2s pause). On final failure: SMS to Jake, email to teamgotcher@, log to `contact_creation_log` with `status = 'crm_update_failed'` including which calls failed and the full text of each missed note.

**Step 2: Push and verify**

```bash
wmill sync push --skip-variables --skip-secrets --skip-resources
```

Send a pending test draft. Verify all 3 CRM calls succeed on first try. Failure path is code-review only.

**Step 3: Commit**

```bash
git add windmill/f/switchboard/lead_intake.flow/post_approval_\(crm_+_sms\).inline_script.py
git commit -m "fix: retry each CRM post-approval call independently, alert + log on failure"
```

---

### Task 14: Fail webhook on trigger/scheduling failure (I2)

**Files:**
- Modify: `windmill/f/switchboard/gmail_pubsub_webhook.py`

**Step 1: Add two checks before history ID advancement**

After the message processing loop but BEFORE history ID advance:
1. Check if any INBOX_REPLY trigger failures were recorded — raise if found
2. Check if any `schedule_results` entries have `error` key — raise if found

Neither check raises inside its loop.

**Step 2: Push and verify**

```bash
wmill sync push --skip-variables --skip-secrets --skip-resources
```

Seed one normal conversation reply and one normal lead. Verify both paths work — check Windmill job output for status code logging and scheduling success. Failure paths are code-review only.

**Step 3: Commit**

```bash
git add windmill/f/switchboard/gmail_pubsub_webhook.py
git commit -m "fix: block history ID advancement on trigger/scheduling failures (I2)"
```

---

### Task 15: Stop pipeline on AI failure (I3)

**Files:**
- Modify: `windmill/f/switchboard/lead_conversation.flow/generate_response_draft.inline_script.py` (~line 489-490)

**Step 1: Replace generic fallback with signal + SMS**

Remove the "Thanks for getting back to me!" canned response. On Claude failure: create jake_signals notification, send SMS, no draft, return `skipped: True`.

**Step 2: Push and verify**

```bash
wmill sync push --skip-variables --skip-secrets --skip-resources
```

Run one normal conversation reply to confirm Claude generates a real response. Failure path is code-review only.

**Step 3: Commit**

```bash
git add windmill/f/switchboard/lead_conversation.flow/generate_response_draft.inline_script.py
git commit -m "fix: stop pipeline and alert Jake on AI generation failure (I3)"
```

---

### Task 16: Alert on draft creation failure (I4)

**Files:**
- Modify: `windmill/f/switchboard/lead_conversation.flow/generate_response_draft.inline_script.py` (~line 660-667)

**Step 1: Replace silent `skipped: True` with signal + SMS**

On Gmail API failure: create jake_signals notification, send SMS, return `skipped: True`.

**Step 2: Push and verify (combine with Task 15 if both touch same file)**

Verify one normal conversation reply creates a draft successfully. Failure path is code-review only.

**Step 3: Commit**

```bash
git add windmill/f/switchboard/lead_conversation.flow/generate_response_draft.inline_script.py
git commit -m "fix: alert Jake when conversation draft creation fails (I4)"
```

---

### Task 17: Alert on unrecognized response_type

**Files:**
- Modify: `windmill/f/switchboard/lead_conversation.flow/generate_response_draft.inline_script.py` (else branch ~line 466-467)

**Step 1: Replace canned generic response with signal + SMS**

Remove old `else` return. Create jake_signals notification (include thread_id and response_type value), send SMS, return `skipped: True`.

**Step 2: Push and verify (combine with Tasks 15-16 if same file)**

Verify one normal conversation reply works. Failure path is code-review only.

**Step 3: Commit**

```bash
git add windmill/f/switchboard/lead_conversation.flow/generate_response_draft.inline_script.py
git commit -m "fix: alert Jake on unrecognized response_type (code bug safety net)"
```

---

### Task 18: Alert on classification failure (ERROR path)

**Files:**
- Modify: `windmill/f/switchboard/lead_conversation.flow/generate_response_draft.inline_script.py` (ERROR handling ~line 533-545)

**Step 1: Replace vague CRM note with signal + SMS**

Remove "Manual review needed" CRM note. Create jake_signals notification (include thread_id), send SMS, return `skipped: True`.

**Step 2: Push and verify (combine with Tasks 15-17 if same file)**

Verify one normal conversation reply classifies successfully. Failure path is code-review only.

**Step 3: Commit**

```bash
git add windmill/f/switchboard/lead_conversation.flow/generate_response_draft.inline_script.py
git commit -m "fix: alert Jake on classification failure, remove vague CRM note"
```

**Note:** Tasks 15-18 all modify `generate_response_draft.inline_script.py`. Consider implementing all 4 together as one push + one commit to reduce push/verify cycles.

---

### Task 19: OFFER signal write SMS fallback

**Files:**
- Modify: `windmill/f/switchboard/lead_conversation.flow/generate_response_draft.inline_script.py` (OFFER path ~line 548-567)

**Step 1: Add SMS fallback when `write_notification_signal()` returns None**

If signal write fails, send SMS to Jake as fallback. OFFER is highest-value terminal path — must never fail silently.

**Step 2: Push and verify (combine with Tasks 15-18 if same file)**

Seed one normal OFFER reply. Verify signal created, CRM note written, flow returns `skipped: True`. Failure path is code-review only.

**Step 3: Commit**

```bash
git add windmill/f/switchboard/lead_conversation.flow/generate_response_draft.inline_script.py
git commit -m "fix: SMS fallback when OFFER notification signal write fails"
```

---

### Task 20: Roll back timer lock when scheduling fails (C3)

**Files:**
- Modify: `windmill/f/switchboard/gmail_pubsub_webhook.py` (`schedule_delayed_processing()`)

**Step 1: Check HTTP status after scheduling call**

If non-2xx: delete the timer lock row, raise error for Windmill retry.

**Step 2: Push and verify**

```bash
wmill sync push --skip-variables --skip-secrets --skip-resources
```

Seed a test lead. Verify scheduling succeeds, timer lock inserted, delayed job fires. Failure path is code-review only.

**Step 3: Commit**

```bash
git add windmill/f/switchboard/gmail_pubsub_webhook.py
git commit -m "fix: roll back timer lock when scheduling call fails (C3)"
```

---

### Task 21: Exact domain matching for system email filter

**Files:**
- Modify: `windmill/f/switchboard/gmail_pubsub_webhook.py` (`parse_email_field()` ~line 450)

**Step 1: Change substring to exact domain match**

The domain after `@` must exactly equal the system domain.

**Step 2: Push and verify**

```bash
wmill sync push --skip-variables --skip-secrets --skip-resources
```

Seed a LoopNet lead with contact email `testuser@myloopnet.com`. Verify email is extracted (NOT filtered). Seed a normal LoopNet lead — verify `leads@loopnet.com` IS filtered.

**Step 3: Commit**

```bash
git add windmill/f/switchboard/gmail_pubsub_webhook.py
git commit -m "fix: use exact domain matching for system email filter"
```

---

### Task 22: Remove dead code in webhook

**Files:**
- Modify: `windmill/f/switchboard/gmail_pubsub_webhook.py`

**Step 1: Delete `trigger_lead_intake()` (never called)**

**Step 2: Delete Crexi branch in `parse_property_name()` (unreachable)**

**Step 3: Push and verify**

```bash
wmill sync push --skip-variables --skip-secrets --skip-resources
```

Seed one Crexi lead and one LoopNet lead. Both should work identically to before.

**Step 4: Commit**

```bash
git add windmill/f/switchboard/gmail_pubsub_webhook.py
git commit -m "chore: remove dead trigger_lead_intake() and unreachable Crexi parse branch"
```

---

### Task 23: Document draft_id_map contract

**Files:**
- Modify: `windmill/f/switchboard/lead_intake.flow/approval_gate_(draft).inline_script.py` (add comment)
- Modify: `windmill/f/switchboard/gmail_pubsub_webhook.py` (add comment)
- Modify: `windmill/f/switchboard/lead_conversation.flow/approval_gate_(reply_draft).inline_script.py` (add comment)

**Step 1: Add cross-referencing WARNING comments in all 3 locations**

See design doc for exact comment text.

**Step 2: Push and verify**

No behavior change. Visual review.

**Step 3: Commit**

```bash
git add windmill/f/switchboard/lead_intake.flow/approval_gate_\(draft\).inline_script.py \
        windmill/f/switchboard/gmail_pubsub_webhook.py \
        windmill/f/switchboard/lead_conversation.flow/approval_gate_\(reply_draft\).inline_script.py
git commit -m "docs: add cross-reference comments for draft_id_map contract"
```

---

### Task 24: Propagate has_nda into draft data

**Files:**
- Modify: `windmill/f/switchboard/lead_intake.flow/generate_drafts_+_gmail.inline_script.py` (draft dict ~line 256-269)

**Step 1: Add `"has_nda": lead.get("has_nda", False)` to draft dict**

**Step 2: Push and verify**

```bash
wmill sync push --skip-variables --skip-secrets --skip-resources
```

Seed a test lead. Query jake_signals — confirm `has_nda` field is present in signal detail JSON.

**Step 3: Commit**

```bash
git add windmill/f/switchboard/lead_intake.flow/generate_drafts_+_gmail.inline_script.py
git commit -m "fix: propagate has_nda into draft data for conversation engine"
```

---

### Task 25: Hardcoded signature fallbacks

**Files:**
- Modify: `windmill/f/switchboard/lead_intake.flow/generate_drafts_+_gmail.inline_script.py`
- Modify: `windmill/f/switchboard/lead_conversation.flow/generate_response_draft.inline_script.py`

**Step 1: Add hardcoded fallbacks when `email_signatures` config is missing**

Commercial: "Talk soon, Larry" + (734) 732-3789. Residential: "Talk soon, Andrea" + (734) 223-1015.

**Also fix `determine_signer()` default in conversation Module B.** Currently defaults to Larry for all lead types. Change the default to follow the same split: Larry for commercial, Andrea for residential/seller — matching the hardcoded fallbacks.

**Step 2: Push and test directly**

Temporarily rename `f/switchboard/email_signatures` variable. Seed one commercial and one residential lead. Verify correct fallback signatures. Rename variable back. Seed one more lead to confirm normal signatures resume.

**Step 3: Commit**

```bash
git add windmill/f/switchboard/lead_intake.flow/generate_drafts_+_gmail.inline_script.py \
        windmill/f/switchboard/lead_conversation.flow/generate_response_draft.inline_script.py
git commit -m "fix: hardcoded signature fallbacks when email_signatures config is missing"
```

---

### Task 26: Apps Script can see conversation draft deletions

**Files:**
- Modify: `windmill/f/switchboard/get_pending_draft_signals.py` (line 23 + line 8)

**Step 1: Update SQL query**

Change `WHERE source_flow = 'lead_intake'` to `WHERE source_flow IN ('lead_intake', 'lead_conversation')`. Update docstring.

**Step 2: Push and verify**

```bash
wmill sync push --skip-variables --skip-secrets --skip-resources
```

Seed one lead_intake lead (creates pending signal) and one conversation reply (creates pending signal). Call `get_pending_draft_signals` via Windmill API. Verify BOTH signals appear.

**Step 3: Commit**

```bash
git add windmill/f/switchboard/get_pending_draft_signals.py
git commit -m "fix: include lead_conversation signals in get_pending_draft_signals"
```

---

### Task 27: Update pipeline documentation

**Files:**
- Modify: `docs/LEAD_INTAKE_PIPELINE.md`
- Modify: `docs/LEAD_CONVERSATION_ENGINE.md`

**Step 1: Fix all inaccuracies listed in design doc**

- Signer table: Andrea for residential, Larry for commercial + lead magnets (not Jake)
- Add UpNest to all tables
- Template count: 9 (not 8)
- Add UpNest to lead source list
- Fix `wants` field: list of strings, not a string
- Add BizBuySell, Social Connect, UpNest to unlabeled detection sources
- Update Crexi source types: collapsed from 7 sub-types to just "crexi" (no more crexi_om, crexi_flyer, etc.)
- Add `lead_type` field to conversation engine's reply_data schema documentation
- Update webhook flow diagram to show current staging/delayed-processing pattern (not old direct-trigger)

**Step 2: Commit**

```bash
git add docs/LEAD_INTAKE_PIPELINE.md docs/LEAD_CONVERSATION_ENGINE.md
git commit -m "docs: fix pipeline documentation to match code (signers, UpNest, wants field)"
```

---

## Phase 3: Code Review Gate + Full E2E Suite

---

### Task 28: Post-implementation code review (13 failure paths)

**Before running the E2E suite**, review each of the 13 failure paths listed in the design doc's "Post-Implementation Code Review: Failure Paths" table. These cannot be triggered in E2E testing — they require breaking live infrastructure. Verify the error handling is correct by reading the code.

This is a gate. Do not proceed to Task 29 until all 13 failure paths are confirmed correct.

---

### Task 29: Pre-flight checks

Run these before starting the E2E suite:

1. **Verify `messages.import` triggers Pub/Sub:** Seed a throwaway email into leads@, confirm webhook fires within ~15 seconds.
2. **Verify SMS gateway:** `curl -s http://100.125.176.16:8686/` — must be reachable.
3. **Verify WiseAgent OAuth:** Make a test API call via Windmill.
4. **Refresh Gmail tokens:** Get fresh access tokens for both leads@ and teamgotcher@.
5. **Add temporary lead_magnet property:** Add `"TEST Lead Magnet Property"` with `lead_magnet: true` to `property_mapping` via Windmill API.

---

### Tasks 30-63: Full E2E Suite (34 tests)

Execute all 34 test cases from the design doc's Test Matrix. One test at a time, sequential. Fix issues before moving to next test.

**Group 1: Source + Template (Tasks 30-38, Tests 1-9)**
**Group 2: Commercial Branching (Tasks 39-41, Tests 10-12)**
**Group 3: Edge Cases (Tasks 42-48, Tests 13-16, 29-31)**
**Group 4: Approval Loop (Tasks 49-51, Tests 17-19)**
**Group 5: Conversation Classifications (Tasks 52-56, Tests 20-24)**
**Group 6: Conversation Special Prompts (Tasks 57-61, Tests 25-26, 32-34)**
**Group 7: Conversation Approval Loop (Tasks 62-63, Tests 27-28)**

**Dependency:** Groups 5-7 (conversation tests) require sent drafts from Groups 1-3 (intake tests) to create the Gmail threads that conversation replies are seeded into. Run Groups 1-4 first.

Each test follows the execution flow from the design doc:
1. Seed test email (or reply)
2. Pub/Sub fires → webhook runs
3. Verify Windmill job completed
4. Jake checks draft in Gmail
5. Verify draft: correct template, signer, BCC, content
6. Jake sends draft (or deletes for rejection tests)
7. Verify post-approval: signal status, CRM, SMS, BCC
8. Checkpoint: fix or move on

See the design doc's Test Matrix for exact seed emails, verification steps, and expected outputs per test.

---

### Task 64: Cleanup

1. Delete all `TEST -` prefixed contacts from WiseAgent
2. Clean up remaining test drafts in teamgotcher@
3. Remove temporary lead_magnet property from `property_mapping`
4. Test signals in jake_signals are already acted — no cleanup needed

---

**Total: 64 tasks (27 pre-test fixes + 1 code review gate + 1 pre-flight + 34 E2E tests + 1 cleanup)**
