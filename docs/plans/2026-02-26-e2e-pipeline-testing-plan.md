# E2E Pipeline Testing — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Execute 33 end-to-end tests (+ 3 setup tasks) covering every branch of lead_intake and lead_conversation, fixing issues as they're found.

**Architecture:** Seed real notification emails into leads@ via Gmail API `messages.import`, let Pub/Sub naturally trigger the webhook, verify drafts in teamgotcher@, Jake manually approves/rejects, verify CRM + SMS. One test at a time, fix before moving on.

**Tech Stack:** Gmail API (messages.import), Windmill API (job verification), WiseAgent API (CRM verification), Postgres (signal verification)

---

## Prerequisites

**Credentials (from `~/.secrets/jake-system.json`):**
- Gmail OAuth for leads@: `google_oauth.claude_connector` project + `gmail.accounts.leads.refresh_token`
- Gmail OAuth for teamgotcher@: `google_oauth.rrg_gmail_automation` project + `gmail.accounts.teamgotcher.refresh_token`
- Windmill API token: `windmill.api_token`
- WiseAgent OAuth: via Windmill resource `f/switchboard/wiseagent_oauth`

**Test contact naming:** All test contacts use `TEST - [Name]` prefix in WiseAgent.

**Test email recipient:** `jacob@resourcerealtygroupmi.com` for all drafts.

**Test SMS recipient:** `(734) 896-0518` for all leads with phone numbers.

**Property for commercial tests:** `1480 Parkwood Ave - Ypsilanti` (canonical name, exists in property_mapping).

**Second property for multi-property tests:** `CMC Transportation - Ypsilanti` (exists in property_mapping).

---

## Pre-Flight Checks (Before Any Tests)

Run these before starting Task 1:

1. **Verify `messages.import` triggers Pub/Sub:** Seed a throwaway email into leads@ and confirm the webhook fires within ~15 seconds. If it doesn't, switch to `messages.insert` with `internalDateSource=receivedTime` and explicit `INBOX` label ID.

2. **Verify SMS gateway is reachable:** `curl -s http://100.125.176.16:8686/` — if unreachable, SMS tests will fail.

3. **Verify WiseAgent OAuth token:** Make a test API call to WiseAgent via Windmill to confirm the token refreshes correctly. Module A depends on this for every test.

4. **Refresh Gmail tokens:** Get fresh access tokens for both leads@ and teamgotcher@ accounts. Tokens expire every hour — refresh again if the session runs long.

---

## Cleanup Helpers (Between Test Re-Runs)

If a test fails and needs to be re-run, clean up stale state first:

```sql
-- Clear staged leads for the test email
DELETE FROM staged_leads WHERE lower(email) = 'jacob@resourcerealtygroupmi.com' AND NOT processed;

-- Clear batch timer for the test email
DELETE FROM processed_notifications WHERE key LIKE 'timer:%jacob@resourcerealtygroupmi.com%';
```

Also delete any orphaned drafts in teamgotcher@ and pending signals in jake_signals for the test contact.

---

## Task 0: Pre-Test Code Change — BCC leads@ on All Outbound Emails

**Why:** Larry wants all office agents to see outbound lead emails. leads@ is a shared inbox.

**Files:**
- Modify: `windmill/f/switchboard/lead_intake.flow/generate_drafts_+_gmail.inline_script.py` (the `create_gmail_draft` function)
- Modify: `windmill/f/switchboard/lead_conversation.flow/generate_response_draft.inline_script.py` (the `create_reply_draft` function)

**Step 1: Add BCC to lead_intake's create_gmail_draft**

In `generate_drafts_+_gmail.inline_script.py`, find the `create_gmail_draft` function. After the line `if cc:` / `message['cc'] = cc`, add:

```python
    message['bcc'] = 'leads@resourcerealtygroupmi.com'
```

**Step 2: Add BCC to lead_conversation's create_reply_draft**

In `generate_response_draft.inline_script.py`, find the `create_reply_draft` function. After the `In-Reply-To` / `References` headers, add:

```python
    message['bcc'] = 'leads@resourcerealtygroupmi.com'
```

**Step 3: Push to Windmill**

```bash
wmill sync push --skip-variables --skip-secrets --skip-resources
```

**Step 4: Commit**

```bash
git add windmill/f/switchboard/lead_intake.flow/generate_drafts_+_gmail.inline_script.py \
        windmill/f/switchboard/lead_conversation.flow/generate_response_draft.inline_script.py
git commit -m "feat: BCC leads@ on all outbound lead emails"
```

---

## Task 0A: Fix UpNest lead_type and city Fields Lost at Module C

**Why:** Module C (dedup_and_group) builds a group dict per email but doesn't copy `lead_type` or `city` from the raw lead. This means ALL UpNest leads hit the `residential_seller` template regardless of buyer/seller type, and city extraction fails. This is a production bug.

**Files:**
- Modify: `windmill/f/switchboard/lead_intake.flow/dedup_and_group.inline_script.py` line 27

**Fix:** Add `"lead_type": lead.get("lead_type", ""), "city": lead.get("city", ""),` to the group dict on line 27.

**Already done in this worktree.** Commit with the BCC change.

---

## Task 0B: Add Temporary Lead Magnet Property for Test 9

**Why:** No properties in `property_mapping` currently have `lead_magnet: true`. Test 9 needs one.

**Step 1: Add a lead_magnet entry to property_mapping via Windmill API**

Add a test property like `"TEST Lead Magnet Property"` with `lead_magnet: true` and a `response_override`. Use the Windmill API to update the variable.

**Step 2: After all testing, remove it**

---

## Helper: How to Seed a Test Email

Every test in Groups 1-3 follows this pattern. Get an access token for leads@, then use `messages.import`:

```python
# 1. Get access token for leads@
curl -s -X POST https://oauth2.googleapis.com/token \
  -d "client_id={claude_connector.client_id}" \
  -d "client_secret={claude_connector.client_secret}" \
  -d "refresh_token={leads.refresh_token}" \
  -d "grant_type=refresh_token"

# 2. Import email into leads@ inbox
# messages.import places the message as if received, triggers Pub/Sub
curl -X POST "https://gmail.googleapis.com/upload/gmail/v1/users/me/messages/import?internalDateSource=receivedTime" \
  -H "Authorization: Bearer {access_token}" \
  -H "Content-Type: message/rfc822" \
  --data-binary @- <<'MIME'
From: {fake_sender}
To: leads@resourcerealtygroupmi.com
Subject: {subject}
Content-Type: text/plain; charset=utf-8

{body}
MIME
```

---

## Helper: How to Verify After Webhook Runs

After seeding an email, wait ~10-15 seconds for Pub/Sub + webhook + pipeline, then:

```bash
# 1. Check most recent webhook run
curl -s "http://100.97.86.99:8000/api/w/rrg/jobs/list?script_path_exact=f/switchboard/gmail_pubsub_webhook&order_desc=true&per_page=1" \
  -H "Authorization: Bearer {windmill_token}"
# Look for: completed, no errors

# 2. Check most recent lead_intake run (or process_staged_leads)
curl -s "http://100.97.86.99:8000/api/w/rrg/jobs/list?script_path_exact=f/switchboard/lead_intake&order_desc=true&per_page=1" \
  -H "Authorization: Bearer {windmill_token}"
# Look for: running (suspended at approval gate)

# 3. Check draft appeared in teamgotcher@
# List drafts, find the new one, verify subject/body/signer/BCC
```

---

## Helper: How to Verify After Approval

After Jake sends a draft:

```bash
# 1. Check signal status in Postgres (via Windmill)
# Signal should be 'acted', acted_by='gmail_pubsub'

# 2. Check lead_intake job completed (Module F ran)
# Look for completed status

# 3. Verify WiseAgent contact: status="Contacted", notes contain outreach
# Use WiseAgent API to search by email

# 4. Verify SMS received on Jake's phone

# 5. Verify BCC copy arrived in leads@ inbox
```

---

## Group 1: Lead Intake — Source + Template

### Task 1: Crexi — Commercial First Outreach

**Seed email:**
- From: `notifications@notifications.crexi.com`
- Subject: `TEST David Johnson has opened your OM for 1480 Parkwood Ave - Ypsilanti`
- Body:
  ```
  TEST David Johnson has opened the Offering Memorandum for 1480 Parkwood Ave - Ypsilanti in Ypsilanti.
  jacob@resourcerealtygroupmi.com
  (734) 896-0518

  Click below to access contact information for this buyer.
  ```

**Verify draft:**
- Subject: `RE: Your Interest in 1480 Parkwood Ave - Ypsilanti`
- Body contains: "Hey David", "I got your information off of Crexi", "1480 Parkwood Ave, Ypsilanti, MI", OM mention, NDA mention
- Signer: Larry, phone (734) 732-3789
- HTML signature: Larry's signature block
- To: jacob@resourcerealtygroupmi.com
- BCC: leads@resourcerealtygroupmi.com

**After Jake sends draft:**
- WiseAgent: `TEST - David Johnson` contact created, status=Contacted, note with "Outreach" + "1480 Parkwood"
- SMS received on (734) 896-0518
- BCC copy in leads@ inbox
- Signal status: acted

---

### Task 2: LoopNet — Commercial First Outreach

**Seed email:**
- From: `leads@loopnet.com`
- Subject: `TEST Mark Thompson favorited 1480 Parkwood Ave - Ypsilanti`
- Body:
  ```
  A LoopNet user has favorited your listing.

  Contact Name: TEST Mark Thompson
  Email: jacob@resourcerealtygroupmi.com
  Phone: (734) 896-0518
  ```

**Verify draft:**
- Subject: `RE: Your Interest in 1480 Parkwood Ave - Ypsilanti`
- Body: "Hey Mark", "I got your information off of LoopNet", OM mention, NDA mention
- Signer: Larry
- To: jacob@resourcerealtygroupmi.com

**Note:** Real LoopNet leads often have name only (no email/phone). This test includes email/phone to verify the full template path. A no-email LoopNet lead would be silently dropped at Module C dedup — same behavior as Task 14.

---

### Task 3: BizBuySell — Commercial First Outreach

**Seed email:**
- From: `notifications@bizbuysell.com`
- Subject: `Your Business-for-sale listing 1480 Parkwood Ave - Ypsilanti`
- Body:
  ```
  You have received a new inquiry about your listing.

  Contact Name: TEST Sarah Williams
  Contact Email: jacob@resourcerealtygroupmi.com
  Contact Phone: (734) 896-0518

  Message: I'm interested in learning more about this property.
  ```

**Verify draft:**
- Subject: `RE: Your Interest in 1480 Parkwood Ave - Ypsilanti`
- Body: "Hey Sarah", "I got your information off of BizBuySell", OM mention, NDA mention
- Signer: Larry

---

### Task 4: Realtor.com — Residential Buyer

**Seed email:**
- From: `leads@email.realtor.com`
- Subject: `New realtor.com lead: 123 Test Ave, Ann Arbor`
- Body:
  ```
  You have a new lead from Realtor.com.

  First Name: TEST
  Last Name: Emily
  Name: TEST Emily Carter
  Email Address: jacob@resourcerealtygroupmi.com
  Phone Number: (734) 896-0518
  Property: 123 Test Ave, Ann Arbor
  ```

**Verify draft:**
- Subject: `RE: Your Realtor.com inquiry in 123 Test Ave, Ann Arbor`
- Body: "Hey Emily" (or "Hey there" if first name validation fails on "TEST"), "Realtor.com inquiry", "sooner the better", "(734) 223-1015"
- Signer: Andrea
- HTML signature: Andrea's signature block

**Note:** The `TEST` prefix in the name may cause first-name validation to use "there" since "TEST" isn't in the SSA name list. Observe this — it may be acceptable or we may want to handle it.

---

### Task 5: Seller Hub — Residential Seller

**Seed email:**
- From: `notifications@sellerappointmenthub.com`
- Subject: `New Verified Seller Lead - TEST Robert Davis`
- Body:
  ```
  New Verified Seller Lead

  Seller Name: TEST Robert Davis
  Email: jacob@resourcerealtygroupmi.com
  Phone Number: (734) 896-0518
  Property Address: 456 Test St, Ypsilanti, MI 48197
  ```

**Verify draft:**
- Subject: `Introductions, Selling your home?`
- Body: "Hey Robert" (or "Hey there"), "selling your home in Ypsilanti", "I got your information off of Seller Hub", "(734) 223-1015"
- Signer: Andrea

---

### Task 6: Social Connect — Residential Seller

**Seed email:**
- From: `leads@topproducer.com`
- Subject: `New Lead: TEST Jennifer Brown from Social Connect`
- Body:
  ```
  Name
  TEST Jennifer Brown
  Email
  jacob@resourcerealtygroupmi.com
  Phone
  (734) 896-0518
  Source
  Social Connect
  Property
  789 Test Blvd, Saline, MI
  ```

**Verify draft:**
- Subject: `Introductions, Selling your home?`
- Body: "Hey Jennifer" (or "Hey there"), "selling your home", "Social Connect", "(734) 223-1015"
- Signer: Andrea

---

### Task 7: UpNest Buyer — Residential Buyer

**Seed email:**
- From: `notifications@upnest.com`
- Subject: `Lead claimed: Buyer TEST Lisa Martinez in Pinckney`
- Body:
  ```
  TEST Lisa Martinez
  City:
  Pinckney
  Phone:
  (734) 896-0518
  Email:
  jacob@resourcerealtygroupmi.com
  ```

**Verify draft:**
- Subject: `Introductions, Buying a home?`
- Body: "Hey Lisa" (or "Hey there"), "purchase a home in Pinckney", "UpNest", "(734) 223-1015"
- Signer: Andrea
- lead_type: buyer

---

### Task 8: UpNest Seller — Residential Seller

**Seed email:**
- From: `notifications@upnest.com`
- Subject: `Lead claimed: Seller TEST Kevin Wilson in Dexter`
- Body:
  ```
  TEST Kevin Wilson
  City:
  Dexter
  Phone:
  (734) 896-0518
  Email:
  jacob@resourcerealtygroupmi.com
  ```

**Verify draft:**
- Subject: `Introductions, Selling your home?`
- Body: "Hey Kevin" (or "Hey there"), "selling your home in Dexter", "UpNest", "(734) 223-1015"
- Signer: Andrea
- lead_type: seller

---

### Task 9: Lead Magnet Property

**Prerequisite:** Task 0B (temporary lead_magnet property in property_mapping).

**Seed email:** Crexi notification referencing the test lead_magnet property name.
- From: `notifications@notifications.crexi.com`
- Subject: `TEST Chris Adams has opened your OM for TEST Lead Magnet Property`
- Body:
  ```
  TEST Chris Adams has opened the Offering Memorandum for TEST Lead Magnet Property.
  jacob@resourcerealtygroupmi.com
  (734) 896-0518

  Click below to access contact information for this buyer.
  ```

**Verify draft:**
- Subject: `RE: Your Interest in TEST Lead Magnet Property`
- Body: "no longer available", "similar properties", NDA mention, "(734) 732-3789"
- Signer: Larry (lead magnets are commercial, signed Larry)
- Template: lead_magnet

---

### Task 9B: Crexi Info Request (Separated Path)

**Why:** `crexi_info_request` leads are separated from standard leads at Module C — they go into a separate `info_requests` list. No draft is created, but they're logged in the signal payload. This tests that the separation works and doesn't break the flow.

**Seed email:**
- From: `notifications@notifications.crexi.com`
- Subject: `TEST Alex Rivera is requesting information for 1480 Parkwood Ave - Ypsilanti`
- Body:
  ```
  TEST Alex Rivera is requesting information about 1480 Parkwood Ave - Ypsilanti.
  jacob@resourcerealtygroupmi.com
  (734) 896-0518

  Click below to access contact information for this buyer.
  ```

**Verify:**
- `determine_crexi_source_type()` returns `crexi_info_request` (contains "requesting information")
- Module C separates this into `info_requests` list (not `standard_leads`)
- Module D: `info_request_count: 1` in summary, no draft created for this lead
- If this is the ONLY lead in the batch: Module E should get `skipped: true` (no drafts to approve) and flow completes without suspension
- If combined with another lead: info_request appears in signal detail but doesn't generate its own draft

**Note:** Seed this alone (not combined with another lead) to test the clean "no-draft" completion path.

---

## Group 2: Commercial Branching

### Task 10: Commercial Single Property — Followup

**Prerequisite:** Task 1 must be completed (David Johnson exists in WiseAgent with "Lead Intake" note).

**Seed email:** Another Crexi notification for the SAME contact (David Johnson) but DIFFERENT property.
- From: `notifications@notifications.crexi.com`
- Subject: `TEST David Johnson has opened your OM for CMC Transportation in Ypsilanti`
- Body:
  ```
  TEST David Johnson has opened the Offering Memorandum for CMC Transportation in Ypsilanti.
  jacob@resourcerealtygroupmi.com
  (734) 896-0518

  Click below to access contact information for this buyer.
  ```

**Verify draft:**
- Template: `commercial_followup_template` (NOT first outreach)
- Body: "I see you checked out another property", shorter than first outreach, NO NDA mention
- is_followup=true in the pipeline output

---

### Task 11: Commercial Multi-Property — First Contact

**Seed TWO emails within 30 seconds** for the same new contact, different properties. The batch window (30s) should group them.

**Email 1:**
- From: `notifications@notifications.crexi.com`
- Subject: `TEST Amanda Garcia has opened your OM for 1480 Parkwood Ave - Ypsilanti`
- Body: standard Crexi format with `jacob@resourcerealtygroupmi.com` and `(734) 896-0518`

**Email 2 (within 30 seconds):**
- From: `notifications@notifications.crexi.com`
- Subject: `TEST Amanda Garcia has downloaded the flyer for CMC Transportation in Ypsilanti`
- Body: standard Crexi format with same email/phone

**Verify draft:**
- Template: `commercial_multi_property_first_contact`
- Body: "you checked out 1480 Parkwood Ave in Ypsilanti and CMC Transportation - Ypsilanti" (inline property list)
- Single draft (not two separate drafts)

---

### Task 12: Commercial Multi-Property — Followup

**Prerequisite:** Task 11 must be completed (Amanda Garcia exists with "Lead Intake" note).

**Seed TWO more emails for Amanda Garcia**, different properties.

**Verify draft:**
- Template: `commercial_multi_property_followup`
- Body: "you checked out a few more of my listings"
- Shortest template

---

## Group 3: Edge Cases

### Task 13: Company Name (Not a Person)

**Seed email:** Crexi notification with a company name instead of a person name.
- From: `notifications@notifications.crexi.com`
- Subject: `TEST Bridgerow Blinds has opened your OM for 1480 Parkwood Ave - Ypsilanti`
- Body:
  ```
  TEST Bridgerow Blinds has opened the Offering Memorandum for 1480 Parkwood Ave - Ypsilanti in Ypsilanti.
  jacob@resourcerealtygroupmi.com
  (734) 896-0518

  Click below to access contact information for this buyer.
  ```

**Verify draft:**
- Greeting: "Hey there," (NOT "Hey Bridgerow,")
- Rest of template is normal commercial first outreach

---

### Task 14: Lead with No Email

**Seed email:** LoopNet notification with name but no email in body.
- From: `leads@loopnet.com`
- Subject: `TEST NoEmail Person favorited 1480 Parkwood Ave - Ypsilanti`
- Body:
  ```
  A LoopNet user has favorited your listing.
  ```

**Verify:**
- Pipeline runs but Module E returns `skipped: true`
- No draft created, no zombie flow
- Windmill job completes cleanly (not suspended)

---

### Task 15: Batch Window — Same Person, Two Notifications

This is the same mechanism as Task 11 (multi-property). Verify the staging + 30s batch window works.

**Seed TWO emails rapidly** for the same new contact to the same property (e.g., OM view + phone click).

**Verify:**
- Both notifications staged in `staged_leads`
- Only ONE `lead_intake` flow triggered
- Single draft created (not two)

---

### Task 16: Fuzzy Property Dedup

**Seed TWO emails for the same contact** with property name variants:
- Email 1: subject contains `CMC Transportation`
- Email 2: subject contains `CMC Transportation in Ypsilanti`

**Verify:**
- Module C deduplicates to a single property
- Longer name kept (`CMC Transportation in Ypsilanti` or mapped `CMC Transportation - Ypsilanti`)
- Single-property template selected (NOT multi-property)

---

## Group 4: Approval Loop

### Task 17: Send Draft — Full Approval

**Use:** One of the drafts from Group 1 that hasn't been sent yet.

**Jake action:** Open draft in Gmail, click Send.

**Verify (within ~10 seconds):**
1. Pub/Sub fires webhook
2. Webhook detects SENT, matches thread_id to pending signal
3. Signal marked `acted` in jake_signals
4. Module F runs:
   - WiseAgent contact status updated to "Contacted"
   - CRM note added: "Outreach" + property name + "SMS sent to..."
   - SMS CRM note added separately
5. SMS received on (734) 896-0518
6. BCC copy received in leads@ inbox
7. Email received at jacob@resourcerealtygroupmi.com

---

### Task 18: Delete Draft — Rejection

**Use:** One of the remaining unsent drafts from Group 1 (e.g., Task 6 / Jennifer Brown / Social Connect).

**Jake action:** Delete the draft in Gmail.

**Manual resume:** The Apps Script daily poll normally detects deleted drafts. For testing, use the "How to Look Up resume_url for Manual Resume" helper above to find the pending signal's resume_url, then POST to it with `{ "action": "draft_deleted" }`.

**Verify:**
- Module F runs the rejection path
- CRM note: "Lead rejected — draft deleted"
- No SMS sent
- Signal marked acted

---

### Task 19: Send Draft — Lead with No Phone

**Use:** A test that had a lead with phone stripped out (or seed a new Crexi lead without phone).

**Verify after sending:**
- Module F runs
- CRM note says "No phone number — SMS not sent"
- No SMS attempt

---

## Helper: How to Seed a Conversation Reply

Group 5-7 tests require seeding a "reply" into teamgotcher@ that looks like a prospect responding to our outreach. The webhook's reply detection works by checking unlabeled inbox messages on teamgotcher@ against ACTED signals' thread_ids.

**Requirements for reply detection to work:**
1. The original outreach draft must have been **sent** (creating an ACTED signal with the thread_id)
2. The seeded reply must land in **teamgotcher@** inbox (not leads@)
3. The reply must be on the **same Gmail thread** (use the same `threadId`)
4. The reply must have proper threading headers (`In-Reply-To` and `References` matching the sent message's `Message-ID`)

**Steps:**

```bash
# 1. Find the thread_id from the ACTED signal for the test you want to reply to
#    Query jake_signals for the test contact's signal:
curl -s "http://100.97.86.99:8000/api/w/rrg/scripts/run_sync/f/switchboard/pg_query" \
  -H "Authorization: Bearer {windmill_token}" \
  -H "Content-Type: application/json" \
  -d '{"query": "SELECT id, detail->>'thread_id' as thread_id, detail->>'message_id' as message_id FROM jake_signals WHERE status='acted' AND summary LIKE '%TEST David%' ORDER BY created_at DESC LIMIT 1"}'

# 2. Get a fresh access token for teamgotcher@
curl -s -X POST https://oauth2.googleapis.com/token \
  -d "client_id={rrg_gmail_automation.client_id}" \
  -d "client_secret={rrg_gmail_automation.client_secret}" \
  -d "refresh_token={teamgotcher.refresh_token}" \
  -d "grant_type=refresh_token"

# 3. Seed the reply into teamgotcher@ inbox with correct threading
curl -X POST "https://gmail.googleapis.com/upload/gmail/v1/users/me/messages/import?internalDateSource=receivedTime" \
  -H "Authorization: Bearer {teamgotcher_access_token}" \
  -H "Content-Type: message/rfc822" \
  --data-binary @- <<'MIME'
From: jacob@resourcerealtygroupmi.com
To: teamgotcher@gmail.com
Subject: RE: Your Interest in 1480 Parkwood Ave - Ypsilanti
In-Reply-To: <{message_id_from_step_1}>
References: <{message_id_from_step_1}>
Content-Type: text/plain; charset=utf-8

{reply_text}
MIME
```

**Important:** The `threadId` returned by Gmail is NOT set via MIME headers — Gmail auto-threads based on `In-Reply-To`/`References` + subject. If Gmail doesn't auto-thread, you may need to use the `messages.insert` endpoint with an explicit `threadId` parameter in the JSON metadata.

---

## Helper: How to Look Up resume_url for Manual Resume

For Task 18 (draft deletion/rejection), the Apps Script daily poll normally detects deleted drafts. For testing, manually resume the suspended flow:

```bash
# 1. Find the pending signal for the test contact
curl -s "http://100.97.86.99:8000/api/w/rrg/scripts/run_sync/f/switchboard/pg_query" \
  -H "Authorization: Bearer {windmill_token}" \
  -H "Content-Type: application/json" \
  -d '{"query": "SELECT id, resume_url FROM jake_signals WHERE status='pending' AND summary LIKE '%TEST%' ORDER BY created_at DESC LIMIT 5"}'

# 2. POST to the resume_url with draft_deleted action
curl -X POST "{resume_url}" \
  -H "Content-Type: application/json" \
  -d '{"action": "draft_deleted"}'
```

---

## Group 5: Lead Conversation — Classifications

**Prerequisites:** Tests from Group 4 must be completed (need ACTED signals with matching thread_ids). Use the "How to Seed a Conversation Reply" helper above.

For each test below, seed a reply into teamgotcher@ inbox using the helper. The reply MUST be threaded to a specific completed outreach thread — see the "Thread source" note on each task.

### Task 20: INTERESTED / WANT_SOMETHING

**Thread source:** Reply to Task 1 (Crexi / David Johnson / commercial) thread.

**Reply text:** "Can you send me the rent roll and financials?"

**Verify:**
- Claude classifies as INTERESTED / WANT_SOMETHING
- Response draft mentions NDA requirement (commercial framework)
- Signer: Larry (continues from original commercial outreach)
- Draft created in same thread

---

### Task 21: INTERESTED / GENERAL_INTEREST

**Thread source:** Reply to Task 2 (LoopNet / Mark Thompson / commercial) thread.

**Reply text:** "Thanks for reaching out! Tell me more about this property."

**Verify:**
- Claude classifies as INTERESTED / GENERAL_INTEREST
- Response draft is a general follow-up
- Signer: Larry (continues from original commercial outreach)

---

### Task 22: INTERESTED / OFFER (Terminal)

**Thread source:** Reply to Task 3 (BizBuySell / Sarah Williams / commercial) thread.

**Reply text:** "I'd like to make an offer. Would you accept $400,000?"

**Verify:**
- Claude classifies as INTERESTED / OFFER
- NO draft created (terminal)
- Notification signal created in jake_signals
- CRM note: "Offer received"
- Flow stops at Module B (skipped=true)

---

### Task 23: NOT_INTERESTED

**Thread source:** Reply to Task 10 (Crexi followup / David Johnson / commercial) thread. This tests conversation on a followup-originated thread.

**Reply text:** "Thanks but I'm not interested. Already found something."

**Verify:**
- Claude classifies as NOT_INTERESTED
- Gracious apology draft created
- Short, not pushy, leaves door open
- Signer: Larry (continues from original commercial outreach)

---

### Task 24: IGNORE (Auto-Reply)

**Thread source:** Reply to Task 11 (Crexi multi-property / Amanda Garcia / commercial) thread. Tests conversation on a multi-property-originated thread.

**Reply text:**
```
I am currently out of the office and will return on March 3rd.
For urgent matters, please contact my assistant.
This is an automated reply.
```

**Verify:**
- Claude classifies as IGNORE
- NO draft created (terminal)
- CRM note: "Automated/empty reply received" + IGNORE
- Flow stops at Module B (skipped=true)

---

## Group 6: Lead Conversation — Residential Prompts

### Task 25: Residential Buyer Reply (Realtor.com Thread)

**Thread source:** Reply to Task 4 (Realtor.com / Emily Carter / residential buyer) thread.

**Seed reply in teamgotcher@** using the conversation reply helper. Thread to Emily Carter's Realtor.com outreach.

**Reply text:** "Yes! I'd love to schedule a tour. What times are available this weekend?"

**Verify:**
- Residential BUYER prompt framework used (not commercial)
- Response mentions scheduling, home-buying language
- Signer: Andrea, phone (734) 223-1015
- No CRE jargon (no OM, no NDA)

---

### Task 26: Residential Seller Reply (Seller Hub Thread)

**Thread source:** Reply to Task 5 (Seller Hub / Robert Davis / residential seller) thread.

**Seed reply in teamgotcher@** using the conversation reply helper. Thread to Robert Davis's Seller Hub outreach.

**Reply text:** "I'm thinking about selling but I'm not sure what my home is worth. Can you help?"

**Verify:**
- Residential SELLER prompt framework used
- Response mentions home value/CMA, selling process
- Signer: Andrea, phone (734) 223-1015
- No CRE jargon

---

## Group 7: Lead Conversation — Approval Loop

### Task 27: Send Conversation Reply Draft

**Use:** The reply draft from Task 20 (WANT_SOMETHING / David Johnson commercial thread).

**Jake action:** Send the draft in Gmail.

**Verify:**
- Pub/Sub → SENT detect → thread_id match → resume
- Module D runs: CRM note ("Lead conversation reply sent"), SMS if applicable
- Signal acted

---

### Task 28: Delete Conversation Reply Draft

**Use:** The reply draft from Task 21 (GENERAL_INTEREST / Mark Thompson commercial thread).

**Jake action:** Delete the draft.

**Verify:**
- Resume with draft_deleted
- Module D: rejection note in CRM
- No SMS

---

## Cleanup

### After All Tests Complete

1. **WiseAgent:** Search for all contacts with `TEST -` prefix, delete them
2. **Drafts:** Delete any remaining test drafts in teamgotcher@
3. **Property mapping:** Remove the temporary lead_magnet test property (Task 0B)
4. **Signals:** Test signals in jake_signals are already marked as acted — no cleanup needed
