# E2E Pipeline Testing — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Execute 28 end-to-end tests covering every branch of lead_intake and lead_conversation, fixing issues as they're found.

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
  ```

**Verify draft:**
- Subject: `RE: Your Interest in 1480 Parkwood Ave - Ypsilanti`
- Body: "Hey Mark", "I got your information off of LoopNet", OM mention, NDA mention
- Signer: Larry
- To: jacob@resourcerealtygroupmi.com

**Note:** LoopNet leads often have name only (no email/phone). The parser extracts name from subject. Email falls back to generic parser — this test uses Contact Name label in body. If no email is parsed, the draft can't be created (no recipient). Verify parser behavior.

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
- Subject: `Bridgerow Blinds has opened your OM for 1480 Parkwood Ave - Ypsilanti`
- Body: standard Crexi format with `jacob@resourcerealtygroupmi.com` and `(734) 896-0518`

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

**Use:** One of the remaining unsent drafts from Group 1.

**Jake action:** Delete the draft in Gmail.

**Verify:**
- Apps Script daily poll would normally detect this. For testing, manually trigger the Apps Script (`?action=run`) or POST to resume_url with `{ "action": "draft_deleted" }`.
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

## Group 5: Lead Conversation — Classifications

**Prerequisites:** Tests from Group 4 must be completed (need ACTED signals with matching thread_ids).

For each test, seed a reply into teamgotcher@ inbox using `messages.import` with the correct `threadId` and `In-Reply-To` headers so the webhook's reply detection matches it.

### Task 20: INTERESTED / WANT_SOMETHING

**Reply text:** "Can you send me the rent roll and financials?"

**Verify:**
- Claude classifies as INTERESTED / WANT_SOMETHING
- Response draft mentions NDA requirement (commercial framework)
- Signer: Larry (continues from original commercial outreach)
- Draft created in same thread

---

### Task 21: INTERESTED / GENERAL_INTEREST

**Reply text:** "Thanks for reaching out! Tell me more about this property."

**Verify:**
- Claude classifies as INTERESTED / GENERAL_INTEREST
- Response draft is a general follow-up
- Signer matches original outreach

---

### Task 22: INTERESTED / OFFER (Terminal)

**Reply text:** "I'd like to make an offer. Would you accept $400,000?"

**Verify:**
- Claude classifies as INTERESTED / OFFER
- NO draft created (terminal)
- Notification signal created in jake_signals
- CRM note: "Offer received"
- Flow stops at Module B (skipped=true)

---

### Task 23: NOT_INTERESTED

**Reply text:** "Thanks but I'm not interested. Already found something."

**Verify:**
- Claude classifies as NOT_INTERESTED
- Gracious apology draft created
- Short, not pushy, leaves door open
- Signer matches original outreach

---

### Task 24: IGNORE (Auto-Reply)

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

**Prerequisite:** Task 4 (Realtor.com) must be sent and completed.

**Seed reply in teamgotcher@** to the Realtor.com thread.

**Reply text:** "Yes! I'd love to schedule a tour. What times are available this weekend?"

**Verify:**
- Residential BUYER prompt framework used (not commercial)
- Response mentions scheduling, home-buying language
- Signer: Andrea, phone (734) 223-1015
- No CRE jargon (no OM, no NDA)

---

### Task 26: Residential Seller Reply (Seller Hub Thread)

**Prerequisite:** Task 5 (Seller Hub) must be sent and completed.

**Seed reply in teamgotcher@** to the Seller Hub thread.

**Reply text:** "I'm thinking about selling but I'm not sure what my home is worth. Can you help?"

**Verify:**
- Residential SELLER prompt framework used
- Response mentions home value/CMA, selling process
- Signer: Andrea, phone (734) 223-1015
- No CRE jargon

---

## Group 7: Lead Conversation — Approval Loop

### Task 27: Send Conversation Reply Draft

**Use:** One of the reply drafts from Group 5/6.

**Jake action:** Send the draft in Gmail.

**Verify:**
- Pub/Sub → SENT detect → thread_id match → resume
- Module D runs: CRM note ("Lead conversation reply sent"), SMS if applicable
- Signal acted

---

### Task 28: Delete Conversation Reply Draft

**Use:** One of the remaining reply drafts.

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
