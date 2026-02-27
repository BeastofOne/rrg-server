# E2E Pipeline Testing Design

> **Date:** 2026-02-26
> **Scope:** Exhaustive end-to-end testing of lead_intake and lead_conversation pipelines, plus production bug fixes and reliability improvements discovered during code review

---

## Goal

Verify every branch of both pipelines works correctly in a full loop: seeded email in inbox → Pub/Sub fires → webhook parses → pipeline runs → draft created in Gmail → manual approval → Pub/Sub SENT detection → resume → CRM update + SMS.

---

## Test Environment

- **Real systems:** Gmail (leads@ + teamgotcher@), WiseAgent CRM, Postgres (jake_signals), SMS gateway (pixel-9a), Pub/Sub
- **Fake data:** Test contacts prefixed `TEST -` for easy cleanup
- **Email recipient:** jacob@resourcerealtygroupmi.com (all drafts)
- **SMS recipient:** (734) 896-0518 (Jake's phone, all test leads with phone numbers)
- **Email seeding:** Gmail API `messages.import` into leads@ with correct sender headers so the webhook's parser extracts lead data correctly
- **Approval:** Manual — Jake sends or deletes each draft in Gmail
- **Execution:** One test case at a time, sequential. Fix issues before moving to the next test.
- **Token expiry:** Gmail access tokens expire every hour. Refresh between test groups or whenever a seed command returns a 401. The full 34-test suite with manual approvals could take several hours — a 401 means the token expired, not that the test is broken.

---

## Implementation Strategy

All pre-test changes are implemented one at a time. After each change:

1. **Implement** the fix in the local worktree
2. **Push to Windmill** (`wmill sync push --skip-variables --skip-secrets --skip-resources`)
3. **Run the immediate verification** described in that section — a small, focused micro test proving the change works in isolation
4. **Commit** only after verification passes
5. Move to the next change

After ALL pre-test changes are implemented and individually verified, run the full 34-test E2E suite.

### Rollback Plan

All changes are pushed to live Windmill, which processes real leads. If a change breaks the pipeline, revert by pushing the known-good code from the main branch (not the worktree):

```bash
cd ~/rrg-server
wmill sync push --skip-variables --skip-secrets --skip-resources
```

This restores Windmill to the pre-change state within a couple minutes. There's a small window of risk between pushing a broken change and noticing — but real leads arrive only a few times per day, and any that fail during that window are still sitting in the Gmail inbox. The next webhook run after the revert picks them up normally.

### Phase 1: Dependency Issues (implement first)

The 8 dependency issues discovered during the dependency analysis MUST be implemented before the remaining pre-test changes. Several have hard ordering constraints between them or are prerequisites for other changes.

**Implementation order (constraints noted):**

| Order | Issue | Design Section | Ordering Constraint |
|-------|-------|---------------|---------------------|
| 1 | C2: Create backup table | WiseAgent OAuth Token Save Resilience | **Prerequisite:** `CREATE TABLE oauth_token_backup` must exist in Postgres BEFORE the code that writes to it is deployed |
| 2 | C4: Resume failure recovery | Recover From Failed Resume After Signal Marked Acted | Independent — 1-file change in `gmail_pubsub_webhook.py` only. No ripple files, no atomic deploy needed. |
| 3 | I6: lead_type Module A passthrough | Propagate lead_type as First-Class Field Through Pipeline | **Atomic deploy:** All 5 files (Module D draft dict, webhook `find_outreach_by_thread()`, conversation Module A passthrough, conversation Module B prompt selection, conversation `flow.yaml` schema) must be pushed together. Deploying the webhook change without Module A passthrough means lead_type enters the conversation flow but gets dropped. |
| 4 | C1: staged_leads claim/unclaim | Don't Mark Leads as Done Until Actually Processed | Independent — no ordering constraint with other dependency issues |
| 5 | S3: WiseAgent helper in Module D | Extract WiseAgent API Helper in Module F and Module D | Independent — pure refactor, but do BEFORE C2 code changes so the OAuth resilience fix applies to the clean helper instead of the duplicated call sites |
| 6 | I5: City extraction (4 sources) | Proper City Extraction for Residential Sources (UpNest Seller Deferred) | Independent — no external dependencies. UpNest Seller geocoding (Google Maps API) deferred to a future session. |
| 7 | Crexi deployment timing | Collapse Crexi Source Types (deployment note) | **Deploy safely:** Either deploy during quiet period OR use transitional `property_match` that accepts both old and new values |
| 8 | contact_creation_log mixed values | Collapse Crexi Source Types (informational note) | No action — informational only, mixed historical values are expected |

**Micro test per dependency issue:** Each has an "Immediate verification" subsection in its design section. After implementing each one, run that micro test before committing. These are small, focused tests — typically seeding one or two test leads and checking Windmill job output. They prove the change works in isolation before moving on.

**E2E coverage at the end:** Each dependency issue also has an "E2E coverage" subsection listing which of the 34 test cases exercise it. The full E2E suite runs only after ALL pre-test changes (dependency issues + remaining fixes) are complete. This is the comprehensive stress test — every dependency issue gets tested again as part of the full pipeline flow, not just in isolation.

### Phase 2: Remaining Pre-Test Changes

After all 8 dependency issues are implemented and micro-tested, implement the remaining pre-test changes in the order they appear in this document. These are independent of the dependency issues and can be done in any order relative to each other.

### Phase 3: Code Review Gate + Full E2E Suite

After all pre-test changes are implemented:
1. Run the Post-Implementation Code Review (failure paths — see table below)
2. Run the full 34-test E2E suite

### Post-Implementation Code Review: Failure Paths

Twelve of the pre-test fixes add retry/alert behavior for when external systems fail. These failure paths cannot be triggered in E2E testing without breaking live infrastructure. After all pre-test changes are implemented but BEFORE running the full E2E suite, do a dedicated code review of each failure path to verify the error handling is correct:

| Change | What to verify in code review |
|--------|-------------------------------|
| C1: Don't mark done until processed | On trigger failure: `processed` set back to `FALSE`, SMS sent to Jake, error raised for Windmill retry. Timer lock kept intact during retries (deleted only on success). 7-day TTL self-cleans if all retries exhausted. |
| C2: OAuth token save resilience | Save happens BEFORE using the new token. Retry loop (2-3 attempts). Postgres backup write on final failure. No `except: pass`. |
| C3: Roll back timer lock | HTTP status checked after `requests.post()`. On non-2xx: timer lock row deleted, error raised. |
| I2: Fail webhook on trigger/scheduling failure | Two checks before history ID advancement: (1) `trigger_lead_conversation` status code checked, failures recorded with `path: INBOX_REPLY`, raise if any found. (2) `schedule_delayed_processing` exceptions recorded in `schedule_results`, raise if any have `error` key. Both checks happen after loops end, before history ID advances. Neither raises inside its loop. |
| I3: Stop pipeline on AI failure | Generic fallback removed. On Claude failure: jake_signals notification created, SMS sent, no draft created. |
| I4: Alert on draft creation failure | `skipped: True` silent exit removed. On Gmail failure: jake_signals notification created, SMS sent. |
| I8: Remove silent signal status failure | `except: pass` removed. Exception propagates, crashing Module F/D before any CRM or SMS work. Windmill retries from clean slate — no duplicate risk. |
| OFFER signal write fallback | If `write_notification_signal()` returns `None`: SMS sent to Jake as fallback alert. OFFER is the highest-value terminal path — must never fail silently. |
| CRM contact creation resilience | Retry loop (3 attempts, 2s pause). On final failure: SMS to Jake, alert email to teamgotcher@, `contact_creation_log` row with `status = 'failed'`. Lead continues with `client_id = None`. |
| Classification failure (ERROR path) | Old CRM note ("Manual review needed") removed. On ERROR classification: jake_signals notification created (with thread_id), SMS sent. No draft created. |
| CRM post-approval update resilience | Single try/except broken into 3 independent blocks (status, outreach note, SMS note). Each retries (3 attempts, 2s pause). On final failure: SMS to Jake, alert email to teamgotcher@, `contact_creation_log` row with `status = 'crm_update_failed'`. Module F continues. |
| Unrecognized response_type safety net | Old generic canned response removed. On unknown `response_type`: jake_signals notification created (with thread_id and response_type value), SMS sent. No draft created, flow returns `skipped: True`. |
| C4: Resume failure recovery | On resume failure (5xx/timeout): signal rolled back from `acted` to `pending`, error raised for Windmill retry. After all retries exhausted: signal stays `pending`, history ID not advanced (I2 fix), next webhook run re-processes and retries automatically. |

This code review is a gate — do not proceed to the full E2E suite until all thirteen failure paths have been reviewed and confirmed correct.

---

## Pre-Test Code Change: BCC leads@ on All Outbound Emails

**What:** Add `bcc: leads@resourcerealtygroupmi.com` to every outgoing email draft so all office agents have visibility into outbound lead communication.

**Where:**
- `lead_intake` Module D: `create_gmail_draft()` — add BCC header to MIMEText
- `lead_conversation` Module B: `create_reply_draft()` — add BCC header to MIMEText

**Atomic deploy with BCC filter:** This change MUST be pushed to Windmill in the same `wmill sync push` as the "Ignore BCC Copies from teamgotcher@" change below. If BCC goes live without the filter, the first sent draft BCCs a copy to leads@, the webhook processes it as a new lead notification, triggers a phantom intake, which creates another draft, which gets sent, which BCCs again — infinite loop. Implement both changes locally, then push once.

**Immediate verification:** Seed one Crexi test lead into leads@. After the draft appears in teamgotcher@, inspect the draft headers via Gmail API — confirm BCC field is set to `leads@resourcerealtygroupmi.com`. Send the draft, then verify leads@ received a copy AND that the BCC copy was skipped by the webhook (no phantom lead intake triggered).

**E2E coverage:** Every test that sends a draft naturally verifies this.

---

## Pre-Test Code Fix: Don't Mark Leads as Done Until Actually Processed

**Problem:** `process_staged_leads.py` marks leads as `processed = TRUE` before triggering the intake flow. If the trigger HTTP call fails, those leads are permanently marked as handled but were never actually processed. Nobody gets notified.

**Fix:** Keep the existing `processed = TRUE` as the claim (same as now — prevents duplicate workers from grabbing the same batch). After the intake flow trigger call, check the HTTP response. If it succeeded, leave `processed = TRUE` and delete the timer lock (current behavior, correct). If it failed, set `processed = FALSE` to unclaim the leads, send an SMS to Jake so he knows something is wrong, and raise an error so Windmill retries `process_staged_leads` — which re-finds the unclaimed leads, claims them, and re-attempts the trigger.

**Keep the timer lock intact during retries.** The lock prevents a new Pub/Sub notification from scheduling a second `process_staged_leads` job while the retry is in progress. Don't delete it on failure, and don't try to detect the "last retry" (Windmill doesn't expose retry count to scripts). If Windmill exhausts all retries, the timer lock stays — but it lives in `processed_notifications` which has a 7-day TTL, so it self-cleans. The leads are unclaimed (`processed = FALSE`), so once the lock expires, the next notification for that email schedules a fresh `process_staged_leads` job and the leads get processed. The SMS alert means Jake knows to investigate rather than waiting 7 days.

**Timer lock deletion:** Only on success. The `DELETE FROM processed_notifications WHERE message_id = 'timer:...'` stays in the success path (after confirmed trigger). Remove the `except: pass` wrapper around it — if the timer lock delete fails after a successful trigger, that should be visible in logs (non-critical but worth knowing).

**Where:** `windmill/f/switchboard/process_staged_leads.py`

**Immediate verification:** Seed a test lead, let it process normally. Query `staged_leads` — rows should be `processed = TRUE` with `processed_at` set. Query `processed_notifications` — timer lock should be deleted. Check Windmill job output to confirm the trigger succeeded. The failure path (trigger fails → unclaim → SMS → retry) cannot be tested without breaking the Windmill API — verified by code review.

**E2E coverage:** Happy path verified by every Group 1-3 test (leads get processed). Failure path verified by code review only.

---

## Pre-Test Cleanup: Always Close Postgres Connections on Errors

**Problem:** When the code opens a database connection, runs a query, and the query crashes, the connection never gets closed. It stays open doing nothing. If this happens enough times, the database runs out of available connections and nothing can talk to it.

**Fix:** Wrap all database calls in `try/finally` or `with` statements so the connection is always closed — whether the query succeeds or crashes. One-line structural change at each call site, no behavior change.

**Where:** All 12 files that use `psycopg2.connect()`:
- `windmill/f/switchboard/gmail_pubsub_webhook.py` (`claim_message_ids`, `schedule_delayed_processing`)
- `windmill/f/switchboard/process_staged_leads.py`
- `windmill/f/switchboard/get_pending_draft_signals.py`
- `windmill/f/switchboard/act_signal.py`
- `windmill/f/switchboard/read_signals.py`
- `windmill/f/switchboard/write_signal.py`
- `windmill/f/switchboard/lead_intake.flow/wiseagent_lookup_+_create.inline_script.py` (`log_contact_creation`)
- `windmill/f/switchboard/lead_intake.flow/approval_gate_(draft).inline_script.py`
- `windmill/f/switchboard/lead_intake.flow/post_approval_(crm_+_sms).inline_script.py`
- `windmill/f/switchboard/lead_conversation.flow/generate_response_draft.inline_script.py`
- `windmill/f/switchboard/lead_conversation.flow/approval_gate_(reply_draft).inline_script.py`
- `windmill/f/switchboard/lead_conversation.flow/post_approval_(crm_+_sms).inline_script.py`

**Immediate verification:** Structural refactor — no behavior change. Push to Windmill, seed one test lead through the full pipeline (intake → draft → send → CRM + SMS). If it completes the same as before, the refactor is safe. Check Postgres connection count before and after to confirm no leak.

**E2E coverage:** Implicitly verified by every test that touches the database.

---

## Pre-Test Cleanup: Extract WiseAgent API Helper in Module F and Module D

**Problem:** Both Module F (lead_intake post-approval) and Module D (lead_conversation post-approval) repeat the same 5-line WiseAgent API call pattern multiple times. Module F has 4 call sites (contact note, status update, SMS note, rejection note). Module D has 3 call sites (rejection note at line 108, reply note at line 191, plus the same `get_wa_token()` OAuth refresh at line 21-45). The only things that change between call sites are the `requestType` and the `data`.

**Fix:** Extract a small `wa_post(token, request_type, data)` helper at the top of each file. Each call site becomes a one-liner. No behavior change — just means if you need to adjust timeout, headers, or error handling for WiseAgent calls, you do it in one place instead of three or four. Apply the same extraction to both files independently (they are separate Windmill scripts, so they cannot share imports).

**Where:**
- `windmill/f/switchboard/lead_intake.flow/post_approval_(crm_+_sms).inline_script.py` (Module F — 4 call sites)
- `windmill/f/switchboard/lead_conversation.flow/post_approval_(crm_+_sms).inline_script.py` (Module D — 3 call sites)

**Immediate verification:** Pure refactor for both files. Push to Windmill, then:
- **Module F:** Send one pending test draft through lead_intake. Module F should produce the same CRM contact, CRM notes, and SMS as before. Compare Windmill job output before/after.
- **Module D:** Send one pending reply draft through lead_conversation. Module D should produce the same CRM notes and SMS as before. Compare Windmill job output before/after.

**E2E coverage:** Module F implicitly verified by every test that hits it (Tasks 17, 19, 27). Module D implicitly verified by every conversation test that reaches post-approval (Tasks 22, 23, 25, 26, 32, 33).

---

## Pre-Test Cleanup: Remove Dead Code in Webhook

**Dead function:** `trigger_lead_intake()` (around line 971-980) is never called. The pipeline now uses `stage_leads` + `schedule_delayed_processing` instead. Delete it.

**Dead code branch:** The Crexi branch inside `parse_property_name()` (around line 513-524) is unreachable. Crexi emails are routed to the dedicated `parse_crexi_lead()` parser, which extracts property names itself. The generic `parse_lead_from_notification()` path (which calls `parse_property_name`) never receives Crexi emails. Delete the branch.

**Where:** `windmill/f/switchboard/gmail_pubsub_webhook.py`

**Immediate verification:** Push to Windmill, seed one Crexi lead and one LoopNet lead. Both should parse and flow through the pipeline identically to before. If anything was accidentally calling the deleted code, it breaks immediately.

**E2E coverage:** If anything depended on the deleted code, existing tests catch it.

---

## Pre-Test Cleanup: Collapse Crexi Source Types to Just "crexi"

**Problem:** The `determine_crexi_source_type()` function returns 7 different strings for Crexi notifications: `crexi_om`, `crexi_ca`, `crexi_brochure`, `crexi_floorplan`, `crexi_flyer`, `crexi_phone_click`, and `crexi_info_request`. These were from a time when we differentiated Crexi leads by action type. We no longer do — all Crexi leads are just "Crexi" leads and go through the same template. Additionally, Module C splits `crexi_info_request` leads into a separate list that gets no draft, no email, no outreach. Crexi leads are Crexi leads — info requests should be treated the same as every other Crexi notification.

**Fix:**

1. **Replace `determine_crexi_source_type()` with a constant** — Delete the entire function. All Crexi leads get `source_type: "crexi"`. No branches, no sub-types.

2. **Update `property_match.inline_script.py` line 17** — Change `source_type in ("crexi_om", "crexi_flyer", "loopnet", "bizbuysell")` to `source_type in ("crexi", "loopnet", "bizbuysell")`.

3. **Remove the `crexi_info_request` split in Module C** — Delete lines 20-22 of `dedup_and_group.inline_script.py` (`if lead.get("source_type") == "crexi_info_request": info_requests.append(lead); continue`). Info requests now flow through grouping, dedup, and draft creation like every other Crexi lead. The `info_requests` list stays as an empty list (other code references it) but nothing ever goes into it.

**Where:**
- `windmill/f/switchboard/gmail_pubsub_webhook.py` (`determine_crexi_source_type()`, line 394-411 — delete function, replace call site with `"crexi"`)
- `windmill/f/switchboard/lead_intake.flow/property_match.inline_script.py` (line 17)
- `windmill/f/switchboard/lead_intake.flow/dedup_and_group.inline_script.py` (lines 20-22 — delete info_request split)

**Immediate verification:** Push to Windmill, seed one Crexi OM lead and one Crexi info request. Both should get `source_type: "crexi"`, both should flow through property matching, and both should produce a draft in teamgotcher@. Verify in Windmill job output that Module C has zero info_requests and all leads are in standard_leads.

**E2E coverage:** Tasks 1 (Crexi OM → now "crexi") and 11 (Crexi flyer → now "crexi"). Info requests are now just regular Crexi leads — no separate test needed.

**Behavior change note:** Previously only `crexi_om` and `crexi_flyer` were listed in the `property_match` check, so the other four sub-types (`crexi_ca`, `crexi_brochure`, `crexi_floorplan`, `crexi_phone_click`) skipped property matching entirely. After the collapse, ALL Crexi leads go through property matching. This is an improvement — matching either adds useful data or harmlessly finds no match.

**Deployment note:** The `staged_leads` table stores `source_type` in its `raw_lead` JSON column. Any leads staged BEFORE this change is deployed but processed AFTER will have the old value (e.g., `"crexi_om"`) in their `raw_lead`. After the collapse, `property_match` expects `"crexi"` — those in-flight leads would miss property matching. The risk is very low (staged leads are processed within ~30 seconds, so the window is tiny), but to eliminate it entirely: either deploy during a quiet period with no incoming Crexi leads, or temporarily make `property_match` accept both old and new values during the transition: `source_type in ("crexi", "crexi_om", "crexi_flyer", "loopnet", "bizbuysell")`. Once all in-flight leads have cleared (within a minute), push the final version that only accepts `"crexi"`.

**Informational — no code change needed:** Module A (`wiseagent_lookup_+_create.inline_script.py`, line 122-133) writes `source_type` to the `contact_creation_log` table when creating new contacts. After this collapse, new entries will say `"crexi"` where they previously said `"crexi_om"`, `"crexi_flyer"`, etc. No code reads this column for decisions — it's a human-readable audit trail. The log will have mixed values (old records with the granular types, new records with just `"crexi"`), which is fine.

---

## Pre-Test Code Fix: Use Exact Domain Matching for System Email Filter

**Problem:** The system filters out "system" email addresses (from loopnet.com, crexi.com, etc) so they aren't treated as lead contact info. But it uses substring matching (`"loopnet.com" in domain`), so a real lead with an email like `user@myloopnet.com` would be incorrectly filtered out.

**Fix:** Use exact domain matching. The domain portion of the email (after the `@`) must exactly equal the system domain — `@loopnet.com` matches, `@myloopnet.com` does not.

**Where:** `windmill/f/switchboard/gmail_pubsub_webhook.py` (`parse_email_field()`, around line 450)

**Immediate verification:** Push to Windmill, seed a LoopNet lead where the contact email in the body is `testuser@myloopnet.com`. Verify the email is correctly extracted as the lead's email (NOT filtered out as a system domain). Then seed a normal LoopNet lead with `leads@loopnet.com` in the body and verify that system address IS still filtered. Check the Windmill job output for both.

**E2E coverage:** Happy path covered by Tasks 1-3 (system emails filtered correctly, lead emails parsed correctly). The edge case (similar domain not filtered) is covered by the immediate verification above.

---

## Pre-Test Code Fix: Ignore BCC Copies from teamgotcher@ in leads@ Inbox

**Problem:** The BCC feature sends a copy of every outbound email to leads@. The webhook processes all leads@ inbox messages. If a BCC copy somehow matched a lead notification pattern, it could trigger a new intake flow — creating an infinite loop (send → BCC → re-intake → new draft → send → BCC → ...).

**Fix:** Add an early skip in the webhook's email processing: if the sender is `teamgotcher@gmail.com`, ignore the message before any parsing or categorization happens. These are always our own outbound BCC copies, never lead notifications.

**Where:** `windmill/f/switchboard/gmail_pubsub_webhook.py` (early in the INBOX message processing loop, before `categorize_email()` is called)

**Atomic deploy with BCC change:** This change MUST be pushed to Windmill in the same `wmill sync push` as the "BCC leads@ on All Outbound Emails" change above. See that section for the rationale.

**Immediate verification:** Both changes are verified together in a single test. Seed a Crexi test lead, send the draft (which BCCs leads@). The BCC copy arrives in leads@ inbox. Wait for the next webhook run. Verify in Windmill job output that the BCC message was explicitly skipped (logged as "skipped: sender is teamgotcher@") and no phantom lead_intake flow was triggered.

**E2E coverage:** Naturally exercised every time a draft is sent with BCC during the full test suite. If the skip doesn't work, phantom leads would appear.

---

## Pre-Test Code Fix: Remove Silent Failure on Signal Status Update

**Problem:** Both Module F (lead_intake) and Module D (lead_conversation) call `mark_signal_acted()` to mark the signal as "acted" in jake_signals. If that database update fails, the error is silently ignored (`except: pass`). The signal stays "pending," which can cause duplicate processing.

**Fix:** Remove the `except: pass` and let the exception propagate. `mark_signal_acted()` runs at the very top of `main()`, before any CRM updates or SMS sends. If it crashes, nothing else has happened yet — no side effects to duplicate. Windmill's built-in retry re-runs the whole module from a clean slate. No custom retry logic needed.

**Where:** `windmill/f/switchboard/lead_intake.flow/post_approval_(crm_+_sms).inline_script.py` (`mark_signal_acted()`) and the equivalent in `windmill/f/switchboard/lead_conversation.flow/post_approval_(crm_+_sms).inline_script.py`

**Immediate verification:** Push to Windmill, send a pending test draft. Query jake_signals to confirm the signal is "acted". The failure/retry path cannot be tested without breaking Postgres — verified by code review.

**E2E coverage:** Happy path (signal marked acted) verified by Tasks 17 and 27. Failure path verified by code review only.

---

## Pre-Test Code Fix: Retry and Alert on CRM Post-Approval Update Failure

**Problem:** After Jake sends a draft, Module F updates the lead's CRM record: status change to "Contacted", outreach note, and SMS note. All three WiseAgent API calls are inside a single try/except block (line 181-246). If the first call fails (status update), the entire block is skipped — no outreach note, no SMS note. The error is captured in the result dict but nobody is alerted. The lead shows "Hot Lead" instead of "Contacted" in WiseAgent, and there's no record of the outreach.

**Fix — same 4-layer pattern as the CRM contact creation fix:**

1. **Retry each WiseAgent API call individually** (3 attempts with 2-second pauses). Break the single try/except into separate try blocks for: (a) status update, (b) outreach note, (c) SMS note. Each retries independently — a failed status update shouldn't prevent the outreach note from being attempted.

2. **If all retries fail for any call, let Module F continue.** The email was already sent, SMS was already sent. CRM notes are important but not worth crashing the flow over.

3. **Alert immediately — SMS + email.** Send an SMS to Jake: "CRM update failed for [name] after sending draft. Status may still show Hot Lead." Send an alert email to teamgotcher@gmail.com with the full details (which calls failed, error messages, lead name/email).

4. **Log the failure for recovery with exactly what was supposed to happen.** Add a row to `contact_creation_log` with `status = 'crm_update_failed'` and `raw_lead_data` containing everything needed to manually or programmatically fix it: `client_id`, `lead_name`, `lead_email`, `property_names`, which of the 3 calls failed (`status_update_failed`, `outreach_note_failed`, `sms_note_failed`), and the full text of each note that was supposed to be written. Someone looking at this row can just read what was supposed to go into CRM and do it by hand — or a recovery script can replay the exact API calls. The same future recovery script from the CRM creation fix can pick these up too — query `WHERE status IN ('failed', 'crm_update_failed')` and retry the missing API calls.

**Where:** `windmill/f/switchboard/lead_intake.flow/post_approval_(crm_+_sms).inline_script.py` (CRM update block, lines 181-246)

**Immediate verification:** Push to Windmill. Send a pending test draft. Check Windmill job output for Module F — all 3 CRM calls should succeed on first try (no retries). Verify CRM shows "Contacted" status, outreach note, and SMS note. The retry/alert path cannot be tested without breaking WiseAgent API — verified by code review.

**E2E coverage:** Happy path (CRM updates succeed) verified by Tasks 17, 19, 27. Failure path verified by code review only.

---

## Pre-Test Code Fix: Document draft_id_map Contract Between Module E and Webhook

**Problem:** Module E stores draft data in a specific JSON structure (`draft_id_map` with `{gmail_draft_id: {email, thread_id, draft_index}}`). The webhook queries that exact structure with a JSONB SQL query to match sent emails back to signals. Neither side documents that the other depends on it. If anyone changes the structure in Module E, sent emails silently stop being detected and flows hang forever at the approval step.

**Fix:** Add cross-referencing comments in both locations:
1. In Module E where `draft_id_map` is built: "WARNING: The webhook's `find_and_update_signal_by_thread()` queries this exact structure via JSONB SQL. If you change field names or nesting, update the webhook query too."
2. In the webhook where the SQL query lives: "WARNING: This query depends on the exact structure of `draft_id_map` built by Module E (`approval_gate`). If you change this query, update Module E too."
3. Same for the conversation flow's approval gate.

The E2E tests also serve as an integration check — if the structure breaks, the approval/resume tests fail.

**Where:**
- `windmill/f/switchboard/lead_intake.flow/approval_gate_(draft).inline_script.py` (where `draft_id_map` is built)
- `windmill/f/switchboard/gmail_pubsub_webhook.py` (`find_and_update_signal_by_thread()` SQL query)
- `windmill/f/switchboard/lead_conversation.flow/approval_gate_(reply_draft).inline_script.py` (conversation equivalent)

**Immediate verification:** Comments only — no behavior change. Visual review that the comments are in place.

**E2E coverage:** The contract itself is tested by every approval test (Tasks 17, 18, 19, 27, 28). If the structure ever breaks, those tests fail immediately.

---

## Pre-Test Code Fix: Propagate lead_type as First-Class Field Through Pipeline

**Problem:** UpNest is the only source where one source name maps to two lead types (buyer vs seller). The conversation engine currently infers buyer/seller from `template_used` — an indirect signal passed through 4 modules and a database round-trip. If `template_used` is missing or empty at any point, UpNest buyers silently get seller prompts ("selling your home" instead of "purchasing a home").

**Fix:** Make `lead_type` a first-class field that flows through the entire pipeline, independent of `template_used`:
1. Module D: Add `lead_type` to the draft dict (data is already available from Module C after the bug fix).
2. Module E: `lead_type` is automatically stored in the signal detail (it's part of the draft).
3. `find_outreach_by_thread()`: Return `lead_type` from the matched draft alongside `template_used`.
4. Conversation Module A (`fetch_thread_+_classify_reply`): Read `lead_type` from the incoming `reply_data` and pass it through in its return dict. Without this, `lead_type` enters Module A from the webhook but gets dropped — Module B never sees it. (The webhook already includes it automatically via `**outreach` spread on line 1188.)
5. Conversation Module B: Check `lead_type` directly to select the prompt framework (buyer vs seller), instead of inferring it from `template_used`. `template_used` still determines the signer, but `lead_type` determines the prompt.

This way even if `template_used` is lost, the conversation engine still knows buyer vs seller. Two independent signals, either one is sufficient.

**Where:**
- `windmill/f/switchboard/lead_intake.flow/generate_drafts_+_gmail.inline_script.py` (add `lead_type` to draft dict)
- `windmill/f/switchboard/gmail_pubsub_webhook.py` (`find_outreach_by_thread()` — return `lead_type`)
- `windmill/f/switchboard/lead_conversation.flow/fetch_thread_+_classify_reply.inline_script.py` (read `lead_type` from `reply_data`, include in return dict)
- `windmill/f/switchboard/lead_conversation.flow/generate_response_draft.inline_script.py` (use `lead_type` directly instead of inferring from `template_used`)
- `windmill/f/switchboard/lead_conversation.flow/flow.yaml` (add `lead_type: type: string` to the flow input schema so the field is officially declared, not just silently passed through)

**Immediate verification:** Seed one UpNest buyer lead and one UpNest seller lead. After drafts are created, query the jake_signals table for both — inspect the `detail` JSON to confirm `lead_type` is present (`"buyer"` and `"seller"` respectively). Then send the buyer draft, seed a reply, and verify the conversation engine log shows it selected the residential BUYER prompt framework (not seller). Check Windmill job output for the `lead_type` field at each pipeline step.

**E2E coverage:** Tests 32 (UpNest buyer conversation reply) and 34 (UpNest seller conversation reply) directly prove this fix works end-to-end for both lead_type values.

---

## Pre-Test Code Fix: Proper City Extraction for Residential Sources (UpNest Seller Deferred)

**Problem:** The email templates say things like "selling your home in Ypsilanti" but city extraction is broken or accidental for most residential sources. Module B (property match) never sets `property_address` for non-commercial leads, and the city extraction function gets an empty string.

**Fix per source:**

1. **Seller Hub** — The property address is in the email body (e.g., "Property Address: 1686 Steinbach Rd Ann Arbor MI 48103"). Update the parser to explicitly extract `property_address` from the notification body, and extract the city from that.

2. **Social Connect** — The address is also in the email body (e.g., "604 Brierwood Court, Ann Arbor City, MI, 48103"). Update the parser to explicitly extract `property_address` and city.

3. **UpNest Buyer** — City is in the subject line (e.g., "Lead claimed: Buyer Melina Griswold in Pinckney"). Already working after Module C bug fix that preserves the `city` field.

4. **Realtor.com** — City is always in the notification. Currently works by accident (full address lands in `property_name`). Make the city extraction explicit so it doesn't break if the parser changes.

**Deferred: UpNest Seller geocoding.** UpNest Seller emails have a street address but no city (e.g., "Lead claimed: Seller Samuel at 4025 Persimmon Dr"). Resolving the city requires Google Maps Geocoding API setup (API key, billing, Windmill variable). Deferred to a future session. For now, UpNest Seller drafts will say "selling your home" without a city name — functional but less personalized.

**Where:**
- `windmill/f/switchboard/gmail_pubsub_webhook.py` (parsers for Seller Hub, Social Connect, Realtor.com)
- `windmill/f/switchboard/lead_intake.flow/property_match.inline_script.py` (set `property_address` for non-commercial sources)
- `windmill/f/switchboard/lead_intake.flow/generate_drafts_+_gmail.inline_script.py` (`get_city()` to use the newly available data)

**Immediate verification (per source — test each parser fix individually):**
1. **Seller Hub:** Seed a Seller Hub lead with "Property Address: 456 Test St, Ypsilanti, MI 48197" in the body. Verify draft says "selling your home in Ypsilanti".
2. **Social Connect:** Seed a Social Connect lead with "789 Test Blvd, Saline, MI" in the body. Verify draft says "selling your home in Saline".
3. **UpNest Buyer:** Already working after Module C bug fix. Seed an UpNest buyer lead with "in Pinckney" in the subject. Verify draft says "purchase a home in Pinckney".
4. **Realtor.com:** Seed a Realtor.com lead with "123 Test Ave, Ann Arbor" in the body. Verify draft says city "Ann Arbor".

Check Windmill job output at each pipeline step to confirm `property_address` and `city` fields are populated.

**E2E coverage:** Tests 4, 5, 6, 7 verify city appears correctly in the draft. Test 8 (UpNest Seller) verifies the draft is functional without a city name.

---

## Pre-Test Code Fix: Alert Jake When Conversation Draft Creation Fails

**Problem:** If Gmail API fails during conversation reply draft creation (quota, error, etc), the flow silently terminates with `skipped: True`. The lead's reply was received and classified, a response was generated, but the draft was never created. No alert to Jake, the lead gets ghosted.

**Fix:** If draft creation fails, don't silently terminate. Instead:
1. Create a notification signal in jake_signals: "Draft creation failed for reply from [name] about [property]. Manual reply needed."
2. Send an SMS to Jake's phone with the same message.
3. The flow stops — no draft exists, but Jake is alerted immediately.

**Future:** When auto-send + auto-archive is built, the reply will also naturally stay in the inbox (nothing was sent, so nothing gets archived), providing a second visual reminder. Belt and suspenders.

**Where:** `windmill/f/switchboard/lead_conversation.flow/generate_response_draft.inline_script.py` (draft creation failure path, around line 660-667)

**Immediate verification:** Push to Windmill. The failure path cannot be triggered without breaking Gmail API. Verify by code review that the signal creation + SMS alert code is in place. Then run one normal conversation reply (seed a reply, let it generate a draft) to confirm the happy path still works.

**E2E coverage:** Happy path verified by every Group 5-6 test that creates a draft (Tasks 20, 21, 23, 25, 26, 32, 33). Failure path verified by code review only.

---

## Pre-Test Code Fix: Stop Pipeline and Alert Jake When AI Generation Fails

**Problem:** If Claude fails to generate a tailored conversation response, the system silently substitutes a generic "Thanks for getting back to me!" template and creates a draft. With manual approvals this is risky (Jake might send it without noticing). With future automated sending, it's unacceptable — a meaningless canned reply goes out with no human check.

**Fix:** If AI generation fails, don't create a draft at all. Instead:
1. Create a notification signal in jake_signals: "AI failed on reply from [name] about [property]. Manual reply needed." (Same pattern already used for OFFER classifications.)
2. Send an SMS to Jake's phone with the same message, so he finds out immediately — same channel used for lead intake notifications.
3. The flow stops there. No draft, no auto-send. The lead doesn't get ghosted (Jake is alerted) and doesn't get a bad response.

**Where:** `windmill/f/switchboard/lead_conversation.flow/generate_response_draft.inline_script.py` (the Claude CLI failure fallback, around line 489-490)

**Immediate verification:** Push to Windmill. The failure path cannot be triggered without Claude CLI failing. Verify by code review that the old generic fallback ("Thanks for getting back to me!") is removed and replaced with signal + SMS alert. Then run one normal conversation reply to confirm Claude generates a real response and the happy path still works.

**E2E coverage:** Happy path verified by every Group 5-6 test that generates a response (Tasks 20, 21, 23, 25, 26, 32, 33). Failure path verified by code review only.

---

## Pre-Test Code Fix: Alert Jake on Unrecognized response_type (Code Bug Safety Net)

**Problem:** Module B's `generate_response_with_claude()` has an `else` branch (line 466-467) that fires when `response_type` doesn't match any known value. Instead of alerting anyone, it skips Claude entirely and returns a canned generic response: "Thanks for getting back to me. If you have any questions, don't hesitate to reach out." This gets created as a draft that Jake might send without noticing it's not a real tailored response.

An unrecognized `response_type` means there's a bug in the code — a new classification was added without a matching prompt, or a typo. It should never happen, but if it does, a canned response is the wrong answer.

**Fix:** Replace the `else` return (line 466-467) with the I3 pattern:
1. Create a jake_signals notification: "Unknown response_type '[value]' for reply from [name] about [property]. Manual reply needed. This is a code bug — response_type should always match a known value." Include `thread_id` and `response_type` in the signal detail.
2. Send an SMS to Jake with the same message.
3. No draft created. The reply sits in the Gmail thread waiting for a human to see it and reply manually.
4. Return `skipped: True` to stop the flow.

**Where:** `windmill/f/switchboard/lead_conversation.flow/generate_response_draft.inline_script.py` (`else` branch in `generate_response_with_claude()`, line 466-467)

**Immediate verification:** Push to Windmill. The `else` branch cannot be triggered in normal operation (all `response_type` values are hardcoded in the same function). Verify by code review that the old generic return is removed and replaced with signal + SMS. Then run one normal conversation reply to confirm the happy path still works.

**E2E coverage:** Happy path verified by every Group 5-6 test. Failure path verified by code review only.

---

## Pre-Test Code Fix: SMS Fallback When OFFER Notification Signal Write Fails

**Problem:** When a lead replies with an offer, the OFFER classification is terminal — no draft is created. The only way Jake finds out is via a notification signal written to jake_signals (line 550-561). But `write_notification_signal()` (line 81-103) wraps the entire Postgres INSERT in `except: return None`. If the database write fails, Jake is never notified. The CRM note (line 563-567) is also wrapped in `except: pass`. Both can fail silently, leaving a high-dollar offer completely invisible.

**Fix:** If `write_notification_signal()` returns `None` (signal write failed), send an SMS to Jake's phone as a fallback alert — same pattern as I3 and I4. The SMS gateway is a separate system (pixel-9a), so if Postgres is down, SMS still works.

**Where:** `windmill/f/switchboard/lead_conversation.flow/generate_response_draft.inline_script.py` (OFFER handling path, line 548-567)

**Immediate verification:** Push to Windmill. The failure path cannot be triggered without breaking Postgres. Verify by code review that a `None` return from `write_notification_signal()` triggers the SMS fallback. Then seed one normal OFFER reply and confirm the happy path still works — signal created, CRM note written, flow returns `skipped: True`.

**E2E coverage:** Happy path (signal write succeeds) verified by Task 22 (OFFER classification). Failure path verified by code review only.

---

## Pre-Test Code Fix: Alert Jake When Classification Fails (ERROR Path)

**Problem:** If Claude fails during Module A's reply classification, Module A returns `classification: "ERROR"` to Module B. Module B treats ERROR as terminal (line 533-545): writes a vague CRM note ("Manual review needed") and returns `skipped: True`. No jake_signals notification, no SMS, no draft. The lead's reply disappears into a CRM note nobody checks in real time. The CRM note itself is wrapped in `except: pass`, so it can also silently fail.

**Fix:** Replace the ERROR handling in Module B (line 533-545) with the I3/I4 pattern:
1. Create a jake_signals notification: "Classification failed for reply from [name] about [property]. Manual reply needed." Include `thread_id` in the signal detail so Jake can look up the Gmail thread directly.
2. Send an SMS to Jake with the same message.
3. Remove the "Manual review needed" CRM note — it's redundant. The signal + SMS give Jake the specific details and tell him exactly where to act.
4. Flow stops with `skipped: True` — no draft (we don't know the classification, so we can't generate a response).

**Where:** `windmill/f/switchboard/lead_conversation.flow/generate_response_draft.inline_script.py` (ERROR handling path, line 533-545)

**Immediate verification:** Push to Windmill. The failure path cannot be triggered without Claude CLI failing during classification. Verify by code review that the old CRM note is removed and replaced with signal + SMS alert. Then seed one normal conversation reply to confirm classification succeeds and the happy path still works.

**E2E coverage:** Happy path (classification succeeds) verified by every Group 5-6 test. Failure path verified by code review only.

---

## Pre-Test Code Fix: Fail Webhook When Conversation Trigger Fails

**Problem:** When a lead replies to our outreach, the webhook fires `trigger_lead_conversation()` to start the conversation flow. If that call fails (500, network error), the error is quietly appended to a list and the webhook continues — advancing the history ID past those messages. The reply is labeled "Lead Reply" (looks handled) but no conversation flow ever ran, and the messages can never be re-found.

**Fix:** Check the `trigger_lead_conversation` status code. If it's not a success (200-299), record the failure but let the loop continue processing the rest of the batch. After the message processing loop finishes (all labels applied, all leads staged, all other work done) but BEFORE the history ID advancement at line 1269, check if any conversation trigger failures were recorded. If so, raise an error to crash the webhook job. This prevents the history ID from advancing, so Windmill retries and Pub/Sub redelivers — the webhook re-processes the same history range, re-detects the reply, and re-attempts the trigger. Everything else that already succeeded (labels, lead claims, lead staging) is idempotent and safe to re-run.

**Implementation detail:** The current `except` block on line 1201 catches the error and appends it to `errors`. The fix is: after the loop ends (after line 1231) but before line 1269 (history ID advancement), add a check — if any error in `errors` has `"path": "INBOX_REPLY"`, raise a `RuntimeError` with the details. This crashes the job before the history cursor moves past the failed reply. Do NOT raise inside the inner loop — that would skip processing the rest of the batch.

**Also block history ID on scheduling failures:** The same pattern applies to `schedule_delayed_processing()` exceptions in the per-email scheduling loop (line 1261-1267). Currently, if the scheduling function throws (e.g., Postgres crash during timer lock insertion — distinct from a bad HTTP status, which C3 handles), the error is caught, logged in `schedule_results`, and the webhook continues to advance the history ID. Leads are staged but no job is coming to process them. Fix: after the scheduling loop (line 1267) and before history ID advancement (line 1269), check if any entry in `schedule_results` has an `"error"` key. If so, raise a `RuntimeError` — same as the INBOX_REPLY check. Staging is idempotent, so the retry safely re-stages and re-schedules.

**Where:** `windmill/f/switchboard/gmail_pubsub_webhook.py` (reply detection path around line 1191-1204, scheduling loop at line 1261-1267, new checks between line 1267 and line 1269, and history ID advance at line 1272)

**Immediate verification:** Push to Windmill. Neither failure path can be triggered without breaking the Windmill API or Postgres. Verify by code review that both error checks (INBOX_REPLY and scheduling) are in place before the history ID advancement. Then seed one normal conversation reply and one normal lead to confirm both paths work — check Windmill job output for the status code check logging and scheduling success.

**E2E coverage:** Happy path verified by every Group 5-6 test (conversation triggers) and every Group 1-3 test (lead scheduling). Failure paths verified by code review only.

---

## Pre-Test Code Fix: Hardcoded Signature Fallbacks When Config Breaks

**Problem:** If the `email_signatures` Windmill variable is missing or corrupted, the system silently falls back to empty — emails go out with no name, no phone, no branding. In conversation replies, the default signer is Larry regardless of lead type, so Andrea's residential threads get signed by Larry.

**Fix:** Add hardcoded fallback signatures for when the config can't be loaded:
- Commercial leads: "Talk soon, Larry" with phone (734) 732-3789
- Residential leads: "Talk soon, Andrea" with phone (734) 223-1015

In conversation replies, the fallback signer should follow the same split: Larry for commercial, Andrea for residential — not Larry for everything.

**Where:**
- `windmill/f/switchboard/lead_intake.flow/generate_drafts_+_gmail.inline_script.py` (signature loading fallback)
- `windmill/f/switchboard/lead_conversation.flow/generate_response_draft.inline_script.py` (`determine_signer()` default and signature loading fallback)

**Immediate verification:** This CAN be tested directly. Temporarily rename the `f/switchboard/email_signatures` Windmill variable (e.g., append `_backup`). Seed one commercial lead and one residential lead. Verify:
- Commercial draft signed "Talk soon, Larry" with (734) 732-3789
- Residential draft signed "Talk soon, Andrea" with (734) 223-1015
Then rename the variable back to restore normal config. Seed one more lead to confirm normal signatures resume.

**E2E coverage:** Not tested during the full suite (config is intact for all tests). This is only verified during the immediate post-implementation test above.

---

## Pre-Test Doc Fix: Update Pipeline Documentation to Match Code

**Problem:** `docs/LEAD_INTAKE_PIPELINE.md` is wrong in multiple ways:
- Template signer table says "Jake" for Realtor.com, Seller Hub, and Lead Magnet. Code uses Andrea for all residential and Larry for lead magnets. Jake doesn't sign anything.
- UpNest is completely missing from all documentation tables — categorization, parser list, template table — even though it's fully implemented in code with a dedicated parser, categorization, and template.
- Template count says 8; code has 9 (UpNest buyer template is the missing one).
- The lead source list on line 36 omits UpNest.
- The webhook flow diagram still shows old direct-trigger behavior instead of the current staging/delayed-processing pattern.

Also, `docs/LEAD_CONVERSATION_ENGINE.md` has issues:
- `wants` field documented as a string but code treats it as a list of strings (e.g., `["rent roll", "financials"]` not `"rent roll and financials"`). Fix the doc to show it's a list.
- Lead source list for "Unlabeled" detection omits BizBuySell, Social Connect, and UpNest.

**Fix:** Update both docs to match the code. The code is correct.

**Where:**
- `docs/LEAD_INTAKE_PIPELINE.md`
- `docs/LEAD_CONVERSATION_ENGINE.md`

**Immediate verification:** Visual review. No code change, no runtime test needed.

**E2E coverage:** N/A — documentation only.

---

## Pre-Test Code Fix: Retry and Alert on CRM Contact Creation Failure

**Problem:** When Module A tries to create a new WiseAgent CRM contact (line 179-203), if the API call fails, the code catches the error, sets `wiseagent_client_id = None`, and lets the lead continue through the entire pipeline. The lead gets a draft, gets emailed, gets SMS'd — but has no CRM record. Jake and Larry have no way to track this lead in WiseAgent. The error string is in the Windmill job output but nobody is alerted.

**Fix — 4 layers of resilience:**

1. **Retry the WiseAgent API call** (3 attempts with 2-second pauses). One network blip or WiseAgent hiccup shouldn't lose a CRM record.

2. **If all retries fail, let the lead continue.** Better to email the lead without a CRM record than to ghost them. Set `wiseagent_client_id = None` as today, but now with the retry history logged.

3. **Alert immediately — SMS + email.** Send an SMS to Jake's phone: "CRM creation failed for [name] ([email]) after 3 retries. Lead is still being processed but has no CRM record." Also send an alert email to teamgotcher@gmail.com with the same details plus the full error message, so it's visible in the inbox alongside the drafts.

4. **Log the failure to `contact_creation_log` for recovery.** The `contact_creation_log` table already exists (line 109-138). Currently it only logs successful creations. Add a `status` column to the table:

```sql
ALTER TABLE public.contact_creation_log ADD COLUMN status TEXT DEFAULT 'created';
```

On success: log with `status = 'created'` (same as today, just explicit). On failure after all retries: log with `status = 'failed'` and include the error in `raw_lead_data`. This gives a programmatic recovery path — a future script can query `WHERE status = 'failed'`, retry each CRM creation, and update the status to `'created'` on success. The `raw_lead_data` JSON column already stores the full lead dict, so all the data needed for retry is preserved.

**Recovery script (future, not part of this E2E testing session):** A Windmill script that runs on demand or on a schedule: `SELECT * FROM contact_creation_log WHERE status = 'failed'`. For each row, attempt the WiseAgent `webcontact` API call using the data in `raw_lead_data`. On success, update `status = 'created'` and write the `wiseagent_client_id` back. On failure, leave it for the next run. This is not built now — just noting that the `status` column enables it.

**Where:** `windmill/f/switchboard/lead_intake.flow/wiseagent_lookup_+_create.inline_script.py` (CRM creation block, lines 179-203)

**Prerequisite:** Run the `ALTER TABLE` to add the `status` column before deploying the code change.

**Immediate verification:** Push to Windmill. Seed a test lead with a new email address. Verify:
1. CRM contact created in WiseAgent (normal happy path)
2. `contact_creation_log` row has `status = 'created'`
3. No SMS or email alert sent (success path = silent)
The retry/alert path cannot be tested without breaking the WiseAgent API — verified by code review that the retry loop, SMS, email alert, and `status = 'failed'` logging are in place.

**E2E coverage:** Happy path (CRM creation succeeds) verified by every Group 1-3 test that creates a new contact. Failure path verified by code review only.

---

## Pre-Test Code Fix: Propagate has_nda Into Draft Data

**Problem:** Module C (dedup) carries the `has_nda` field on each grouped lead, but Module D (draft generation) never copies it into the draft dict. When a lead replies later, the conversation engine reads `has_nda` from the signal detail (which came from the draft data) and always sees `False`. NDA holders get told they need to sign an NDA they already signed.

**Fix:** Add `"has_nda": lead.get("has_nda", False)` to Module D's draft dict so the field flows through to the signal and is available for the conversation engine's decision making.

**Where:** `windmill/f/switchboard/lead_intake.flow/generate_drafts_+_gmail.inline_script.py` (draft dict construction, around line 256-269)

**Immediate verification:** Seed one test lead, let the pipeline create a draft. Query the jake_signals table — inspect the signal's `detail` JSON. Confirm the `has_nda` field is present in the draft data (will be `false` for new test contacts, but the field must exist). Check Windmill job output for Module D to confirm it's in the draft dict.

**E2E coverage:** The field presence is implicitly verified by every test that creates a draft. The behavior difference (has_nda=true changes conversation prompts) is NOT tested in E2E because all test contacts are new and have no NDA on file. That behavior is verified by code review — the conversation engine checks `has_nda` and adjusts NDA language accordingly.

---

## Pre-Test Code Fix: Recover From Failed Resume After Signal Marked Acted

**Problem:** When Jake sends a draft, the webhook's `find_and_update_signal_by_thread()` atomically marks the signal as "acted" and then calls the resume URL to trigger Module F (CRM update, SMS, etc). If the resume call fails, the signal is already marked "acted" — so there's no way to retry. CRM never updates, SMS never sends, and nobody knows.

**Why "acted" is marked first:** Duplicate protection. Gmail can send multiple Pub/Sub notifications for the same SENT email. The atomic UPDATE (WHERE status = 'pending') ensures only the first notification processes the signal — the second finds no pending signal and stops. This prevents duplicate CRM updates and SMS messages.

**Fix:** Keep `find_and_update_signal_by_thread()` exactly as-is (marks acted atomically — duplicate protection preserved). After the resume call, check the HTTP response. If resume failed (5xx / timeout), UPDATE the signal back to `pending` and raise an error. Raising the error causes the Windmill job to fail, triggering Windmill's built-in retry — the webhook re-runs, `find_and_update_signal_by_thread()` matches the now-pending signal again, marks acted, and re-attempts the resume. If Windmill exhausts all built-in retries, the signal is left as `pending` and the history ID is NOT advanced (thanks to the I2 fix). The next webhook invocation — triggered by any new Pub/Sub notification (new lead, new reply, anything) — re-processes from the same history ID, finds the same SENT email, matches the pending signal, and tries the resume again. The signal sits as `pending` until a webhook run finally succeeds. Self-healing.

**No new states, no ripple files:** The signal only ever holds `pending` or `acted` — same as today. On failure it rolls back to `pending` (a state everything already handles). No other files need changes.

**Where:** `windmill/f/switchboard/gmail_pubsub_webhook.py` (SENT processing path, after the `trigger_resume()` call)

**Immediate verification:** Push to Windmill. Seed a test lead, let it go through the full pipeline (intake → draft → send). After sending, query jake_signals — signal should be `status = 'acted'`. Verify Module F completed (CRM "Contacted" status, outreach note, SMS). The failure/rollback path cannot be tested without breaking the Windmill API — verified by code review.

**E2E coverage:** Happy path (resume succeeds, signal stays acted) verified by Tasks 17 and 27. Failure path (rollback to pending + retry) verified by code review only.

---

## Pre-Test Code Fix: Roll Back Timer Lock When Scheduling Fails

**Problem:** When a new lead comes in, the webhook inserts a timer lock in the database, then calls the Windmill API to schedule a delayed processing job. If that API call fails (server hiccup, network blip), the timer lock stays in the database, blocking any future scheduling for that email. Leads sit in the staging table forever.

**Fix:** In `schedule_delayed_processing()`, check the HTTP response status after the `requests.post()` call. If it's not a success (status code outside 200-299), delete the timer lock row that was just inserted and raise an error. Raising the error causes the Windmill job itself to fail, which triggers Windmill's built-in retry — so the webhook re-runs and re-attempts the scheduling immediately, rather than waiting for another notification to arrive (which could be days for low-volume sources like BizBuySell).

**Where:** `windmill/f/switchboard/gmail_pubsub_webhook.py` (`schedule_delayed_processing()`)

**Immediate verification:** Push to Windmill. Seed a test lead and watch the webhook's Windmill job output. The scheduling call should succeed and the log should show the status code check passing. Verify in the `staged_leads` and `processed_notifications` tables that the timer lock was inserted and the delayed job was scheduled. After the 30-second delay, the `process_staged_leads` job should fire. The failure/rollback path cannot be tested without breaking the Windmill API — verified by code review.

**E2E coverage:** Happy path (scheduling succeeds) verified by every Group 1-3 test. Failure path (rollback + retry) verified by code review only.

---

## Pre-Test Code Fix: WiseAgent OAuth Token Save Resilience

**Problem:** When the system refreshes the WiseAgent access token, it tries to save the new tokens back to Windmill storage. If that save fails, the error is silently ignored (`except: pass`). WiseAgent may have rotated the refresh token — meaning the old one is now invalid, and the new one was never saved. This exact failure has already caused two full outages.

**Fix (applied to all 4 files that refresh the WiseAgent OAuth token):**
1. **Save first, then use.** After getting new tokens from WiseAgent, save to Windmill storage before using the new access token for API calls.
2. **Retry the save.** Try 2-3 times with a brief pause before giving up. One network blip shouldn't lose the token.
3. **If all retries fail, back up to Postgres.** Write the refreshed token to a dedicated backup table so it can be recovered even if Windmill storage is unreachable.
4. **Log loud on failure.** Replace `except: pass` with an error message visible in Windmill job output so the problem is discovered immediately, not when WiseAgent access is permanently broken.

**Prerequisite — Create the backup table on rrg-server Postgres before implementing this fix:**

```sql
CREATE TABLE public.oauth_token_backup (
    service     TEXT PRIMARY KEY,
    token_data  JSONB NOT NULL,
    saved_at    TIMESTAMPTZ DEFAULT NOW()
);
```

One row per service, always the latest. The code writes to it with an upsert:

```sql
INSERT INTO public.oauth_token_backup (service, token_data, saved_at)
VALUES ('wiseagent', %s::jsonb, NOW())
ON CONFLICT (service) DO UPDATE
SET token_data = EXCLUDED.token_data, saved_at = NOW();
```

This way there's always exactly one `'wiseagent'` row with the most recent token. No old rows accumulate, no cleanup needed. Reading the backup is: `SELECT token_data FROM oauth_token_backup WHERE service = 'wiseagent'`.

**Where (all 4 instances of the same `except: pass` on `wmill.set_resource()`):**
- `windmill/f/switchboard/lead_intake.flow/wiseagent_lookup_+_create.inline_script.py` (`get_token()`, line 29-32) — Module A
- `windmill/f/switchboard/lead_intake.flow/post_approval_(crm_+_sms).inline_script.py` (`get_token()`, line 30-33) — Module F
- `windmill/f/switchboard/lead_conversation.flow/generate_response_draft.inline_script.py` (`get_wa_token()`, line 57-60) — conversation Module B
- `windmill/f/switchboard/lead_conversation.flow/post_approval_(crm_+_sms).inline_script.py` (`get_wa_token()`, line 41-44) — conversation Module D

**Immediate verification:** Push to Windmill. Seed one test lead through lead_intake to exercise Module A (`get_token()`), then send the draft to exercise Module F (`get_token()`). Seed a conversation reply to exercise Module B (`get_wa_token()`), then send the reply draft to exercise Module D (`get_wa_token()`). For each, check Windmill job output to confirm:
1. Token refresh happened (or was skipped because token was still valid)
2. If refreshed: log shows "save first" behavior — save attempted before API calls
3. Verify the Postgres backup table exists and (if a refresh happened) contains the backup token row
The retry/backup failure path cannot be tested without breaking Windmill storage — verified by code review.

**E2E coverage:** Happy path (token works) verified by every test that hits WiseAgent — Module A by all Group 1-3 tests, Module F by Tasks 17, 19, 27, Module B by all Group 5-6 tests, Module D by Tasks 22, 23, 25, 26, 27, 32, 33. The save-first ordering and Postgres backup are verified during the immediate test above.

---

## Pre-Test Bug Fix: Apps Script Can't See Conversation Draft Deletions

**Problem:** The `get_pending_draft_signals` script (called by Google Apps Script to detect deleted drafts) only queries `WHERE source_flow = 'lead_intake'`. Conversation reply drafts created by `lead_conversation` are invisible to it. If Jake deletes a conversation reply draft, the Apps Script never notices — that conversation flow hangs at the approval gate forever (until the 1-year Windmill suspend timeout).

**Fix:** Change the query in `get_pending_draft_signals.py` line 23 from:
```sql
WHERE status = 'pending'
  AND source_flow = 'lead_intake'
  AND detail ? 'draft_id_map'
```
to:
```sql
WHERE status = 'pending'
  AND source_flow IN ('lead_intake', 'lead_conversation')
  AND detail ? 'draft_id_map'
```

Also update the docstring on line 8 from "Get all pending lead_intake signals" to "Get all pending signals" since it now covers both flows.

**Where:** `windmill/f/switchboard/get_pending_draft_signals.py` (line 23 + line 8)

**Immediate verification:** Push to Windmill. Seed one lead through lead_intake (creates a draft → pending signal). Seed one reply through lead_conversation (creates a reply draft → pending signal). Call `get_pending_draft_signals` via the Windmill API. Verify BOTH signals appear in the response — the lead_intake one AND the lead_conversation one. Before this fix, only the lead_intake signal would appear.

**E2E coverage:** Task 28 (delete conversation reply draft) includes an explicit step: call `get_pending_draft_signals` and verify the conversation signal appears in the results before manually resuming. This proves the SQL fix works within the full E2E suite — not just in isolation.

---

## Three-Way Source Classification (Current)

| Category | Sources | Signer | Phone |
|----------|---------|--------|-------|
| Commercial | Crexi, LoopNet, BizBuySell | Larry | (734) 732-3789 |
| Residential Buyer | Realtor.com, UpNest (buyer) | Andrea | (734) 223-1015 |
| Residential Seller | Seller Hub, Social Connect, UpNest (seller) | Andrea | (734) 223-1015 |

---

## Test Matrix

### Group 1: Lead Intake — Source + Template (9 tests)

Each test seeds a fake notification email into leads@, verifies the webhook parses it correctly, the pipeline selects the right template, and the draft appears in teamgotcher@ with the correct content and HTML signature.

| # | Source | Template | Signer | Key Verification |
|---|--------|----------|--------|-----------------|
| 1 | Crexi | commercial_first_outreach_template | Larry | Bare-line parser, OM mention, NDA mention, HTML signature |
| 2 | LoopNet | commercial_first_outreach_template | Larry | Subject-only name extraction |
| 3 | BizBuySell | commercial_first_outreach_template | Larry | Labeled field parser |
| 4 | Realtor.com | realtor_com | Andrea | "Keep in mind sooner the better" language, tour offer |
| 5 | Seller Hub | residential_seller | Andrea | "selling your home" language, city extraction |
| 6 | Social Connect | residential_seller | Andrea | Dedicated parser (alternating label/value lines) |
| 7 | UpNest (buyer) | residential_buyer | Andrea | "purchase a home" language, city from subject |
| 8 | UpNest (seller) | residential_seller | Andrea | Same template as Seller Hub, UpNest attribution. City omitted (geocoding deferred) — verify draft says "selling your home" without city and is otherwise functional. |
| 9 | Lead magnet property | lead_magnet | Larry | "no longer available" language, similar properties offer |

### Group 2: Lead Intake — Commercial Branching (3 tests)

| # | Scenario | Template | Key Verification |
|---|----------|----------|-----------------|
| 10 | Single property, followup (existing contact w/ recent note) | commercial_followup_template | is_followup=true, shorter template |
| 11 | Multi-property, first contact | commercial_multi_property_first_contact | Inline property list formatting |
| 12 | Multi-property, followup | commercial_multi_property_followup | Shortest template |

### Group 3: Lead Intake — Edge Cases (7 tests)

| # | Scenario | Key Verification |
|---|----------|-----------------|
| 13 | Company name (not a person) | "Hey there," greeting |
| 14 | Lead with no email | Module E skipped=true, no zombie flow |
| 15 | Same person, two notifications in 30s batch window | Batched into single flow, multi-property |
| 16 | Fuzzy property dedup ("CMC Transportation" + "CMC Transportation in Ypsilanti") | Single property, longer name kept |
| 29 | Malformed lead (bad email, @ in phone) | validate_lead() rejects, email relabeled "Unlabeled", no draft |
| 30 | Cross-source batch (same person on Crexi + LoopNet, different properties) | Single flow, multi-property template, both properties listed |
| 31 | No-name lead (email and phone only, no name anywhere) | "Hey there," greeting, pipeline processes normally |

### Group 4: Approval Loop (3 tests)

| # | Scenario | Key Verification |
|---|----------|-----------------|
| 17 | Send draft (approve) | Pub/Sub → SENT detect → thread_id match → resume → CRM "Contacted" + note + SMS. **C4 verification:** after Module F completes, query jake_signals — confirm signal is `status = 'acted'`. |
| 18 | Delete draft (reject) | Apps Script → resume → CRM rejection note |
| 19 | Send draft, lead with no phone | CRM note says "No phone number — SMS not sent" |

### Group 5: Lead Conversation — Classifications (5 tests)

Reply to threads from completed Group 4 tests. Replies are seeded into teamgotcher@ inbox.

| # | Reply Text | Classification | Key Verification |
|---|-----------|----------------|-----------------|
| 20 | "Can you send me the rent roll?" | INTERESTED / WANT_SOMETHING | NDA mention (commercial prompt framework) |
| 21 | "Tell me more" | INTERESTED / GENERAL_INTEREST | Follow-up draft |
| 22 | "I'd like to offer $400K" | INTERESTED / OFFER | Terminal — notification signal, no draft |
| 23 | "Not interested, thanks" | NOT_INTERESTED | Gracious apology draft |
| 24 | Out-of-office auto-reply | IGNORE | Terminal — CRM note only |

### Group 6: Lead Conversation — Special Prompts (5 tests)

| # | Scenario | Key Verification |
|---|----------|-----------------|
| 25 | Reply to residential buyer outreach (Realtor.com thread) | Residential buyer prompt framework, Andrea signer |
| 26 | Reply to residential seller outreach (Seller Hub thread) | Residential seller prompt framework, Andrea signer |
| 32 | Reply to UpNest buyer outreach (Task 7 / Lisa Martinez thread) | Residential BUYER prompt (not seller), Andrea signer, "purchase a home" language |
| 33 | Reply to lead magnet outreach (Task 9 / Chris Adams thread) | `lead_magnet_redirect` response type, "no longer available" + redirect to active listings, Larry signer |
| 34 | Reply to UpNest seller outreach (Task 8 thread) | Residential SELLER prompt (not buyer), Andrea signer, "selling your home" language. Proves lead_type "seller" routes correctly through I6 fix — paired with Task 32 which proves "buyer". |

### Group 7: Lead Conversation — Approval Loop (2 tests)

| # | Scenario | Key Verification |
|---|----------|-----------------|
| 27 | Send conversation reply draft | Pub/Sub → resume → CRM note + SMS. **C4 verification:** after Module D completes, query jake_signals — confirm signal is `status = 'acted'`. |
| 28 | Delete conversation reply draft | Call `get_pending_draft_signals` first — verify conversation signal appears in results (proves Apps Script fix). Then manual resume → rejection note |

**Total: 34 test cases**

---

## Execution Flow (per test)

```
1. Seed test email into leads@ (or reply into teamgotcher@)
2. Pub/Sub fires → webhook runs automatically
3. Verify Windmill job completed successfully
4. Jake checks the draft in teamgotcher@ Gmail
5. Verify draft: correct template, signer, BCC, content
6. Jake SENDS the draft (unless this test is specifically held back for rejection/special testing)
7. Verify post-approval: signal status, CRM contact/note, SMS received, BCC copy in leads@
8. CHECKPOINT: Did anything look wrong?
   ├── Yes → Diagnose root cause, fix the code, re-run THIS test case
   └── No → Move to next test
```

**Important:** Groups 1-3 tests each end with Jake sending the draft. This creates the ACTED signals needed for Groups 5-7 (conversation tests). Two exceptions are held back unsent:
- One draft for Task 18 (draft deletion / rejection testing)
- One draft for Task 19 (send with no phone number)

Group 4 covers only the special approval cases (rejection, no-phone). Normal approval is verified as part of every Group 1-3 test.

---

## Cleanup After Testing

- Delete all `TEST -` prefixed contacts from WiseAgent
- Clean up any remaining test drafts in teamgotcher@
- Test signals in jake_signals will be naturally marked as acted
