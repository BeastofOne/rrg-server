# Lead Pipeline Fixes & Residential Expansion — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix existing lead pipeline bugs, rigidify conversation prompts, add full residential pipeline with Andrea Gotcher signing all residential leads.

**Architecture:** Windmill flow scripts (Python) running on rrg-server. Changes are made to local Windmill flow files, committed to git, synced to rrg-server, then pushed to Windmill via `wmill sync push`. Testing = triggering real pipeline runs via Windmill API or webhook.

**Tech Stack:** Python 3 (Windmill scripts), Gmail API, WiseAgent API, PostgreSQL (jake_signals), Claude CLI (subprocess), Windmill variables/resources.

**Design doc:** `docs/plans/2026-02-25-lead-pipeline-fixes-design.md`

---

## Prerequisites

Before starting any task:
1. Read `~/.secrets/jake-system.json` for credentials
2. Verify SSH access: `ssh andrea@rrg-server 'echo ok'`
3. Pull latest: `cd ~/rrg-server && git pull`
4. Sync Windmill flows: `cd ~/rrg-server && wmill sync pull`

---

## Phase 1: Validate & Fix (Issues 1, 5)

### Task 1: Verify `source` field survives the full pipeline chain

**Files:**
- Read: `windmill/f/switchboard/gmail_pubsub_webhook.py:846-858` (find_outreach_by_thread return)
- Read: `windmill/f/switchboard/lead_conversation.flow/fetch_thread_+_classify_reply.inline_script.py:186-220` (source passthrough)
- Read: `windmill/f/switchboard/lead_conversation.flow/generate_response_draft.inline_script.py:151-159` (is_commercial check)

**Step 1: Read the source field chain**

Trace the `source` field from webhook parser → lead_intake signal → reply detection → lead_conversation Module A → Module B. Confirm it's the same value at each step.

**Step 2: Check a real signal in Postgres**

```bash
ssh andrea@rrg-server "docker exec windmill-db-1 psql -U postgres windmill -c \"SELECT id, detail->>'drafts' FROM public.jake_signals WHERE source_flow = 'lead_intake' AND status = 'acted' ORDER BY acted_at DESC LIMIT 1;\""
```

Expected: Signal has `source` and `source_type` in each draft object. Note the actual values.

**Step 3: Document findings**

If source chain is intact, note it. If broken anywhere, fix before proceeding.

**Step 4: Commit**

No code changes expected — just verification. If fixes needed, commit them.

---

### Task 2: Validate `is_commercial` fix with Crexi test run

**Files:**
- Read: `windmill/f/switchboard/lead_conversation.flow/generate_response_draft.inline_script.py:151` (`source.lower()` check)

**Step 1: Trigger a Crexi lead conversation test**

Use the same approach from the earlier E2E session — trigger lead_conversation via Windmill API with a test reply to an existing Crexi thread.

```bash
ssh andrea@rrg-server "curl -s -X POST 'http://localhost:8000/api/w/rrg/jobs/run/f/f/switchboard/lead_conversation' \
  -H 'Authorization: Bearer <WINDMILL_TOKEN>' \
  -H 'Content-Type: application/json' \
  -d '{...test payload with source: \"Crexi\"...}'"
```

(Exact payload TBD — use data from existing acted signal)

**Step 2: Check the draft in Gmail**

Open teamgotcher@gmail.com, find the draft. Verify:
- Signature says "Larry" (not Jake)
- Phone number is (734) 732-3789

**Step 3: Visual check HTML rendering**

Confirm the email renders as HTML in Gmail — no raw `<br>` tags or HTML source showing.

**Step 4: Document results**

Note pass/fail for: is_commercial ✓/✗, signature ✓/✗, HTML rendering ✓/✗

---

### Task 3: Validate `is_commercial` fix with LoopNet and BizBuySell values

**Files:**
- Same as Task 2

**Step 1: Check if LoopNet/BizBuySell signals exist**

```bash
ssh andrea@rrg-server "docker exec windmill-db-1 psql -U postgres windmill -c \"SELECT id, summary FROM public.jake_signals WHERE source_flow = 'lead_intake' AND detail::text LIKE '%LoopNet%' ORDER BY created_at DESC LIMIT 3;\""
```

Do the same for BizBuySell. If no signals exist, we can't test conversation replies for these sources yet — note it and move on. Phase 4 covers this.

**Step 2: If signals exist, trigger test conversation**

Same approach as Task 2 but with `source: "LoopNet"` and `source: "BizBuySell"`.

**Step 3: Document results**

---

### Task 4: Commit Phase 1 findings

**Step 1: Create a verification log**

If any fixes were needed, commit them. If everything passed, commit a note in the design doc updating Phase 1 status.

**Step 2: Sync to rrg-server**

```bash
git add docs/plans/2026-02-25-lead-pipeline-fixes-design.md
git commit -m "docs: Phase 1 validation results for lead pipeline fixes"
git push origin main
ssh andrea@rrg-server 'cd ~/rrg-server && git pull'
```

---

## Phase 2: Rigid Lead Conversation Prompts + Lead Magnets (Issues 6, 4, 8)

### Task 5: Rewrite `not_interested` prompt with rigid framework

**Files:**
- Modify: `windmill/f/switchboard/lead_conversation.flow/generate_response_draft.inline_script.py:184-198`

**Step 1: Read current `not_interested` prompt**

Read lines 184-198 of `generate_response_draft.inline_script.py`.

**Step 2: Rewrite the prompt**

Replace the current loose prompt with a rigid framework:

```python
    if response_type == "not_interested":
        prompt = f"""Write a brief email reply to a lead who is not interested.

SENDER IDENTITY:
- You are {sender_name} from Resource Realty Group
- Signoff: {signoff}

LEAD CONTEXT:
- Lead's first name: {first_name}
- Their reply: {reply_body[:500]}

STRUCTURE (follow exactly):
1. Greeting: "Hey {{first_name}},"
2. Body: 2-3 sentences max. Be gracious, don't be pushy, don't try to change their mind. Leave the door open for future contact.
3. Signoff: Use exactly: {signoff}

RULES:
- Do NOT include a subject line
- Do NOT mention any property details or pricing
- Do NOT suggest alternative properties
- Write ONLY the email body text"""
```

**Step 3: Test with a live run**

Trigger a lead_conversation run with a NOT_INTERESTED classification. Check the draft in Gmail.

**Step 4: Commit**

```bash
git add windmill/f/switchboard/lead_conversation.flow/generate_response_draft.inline_script.py
git commit -m "feat(lead_conversation): rigidify not_interested prompt framework"
```

---

### Task 6: Rewrite `general_interest` prompt with rigid framework

**Files:**
- Modify: `windmill/f/switchboard/lead_conversation.flow/generate_response_draft.inline_script.py:200-217`

**Step 1: Read current `general_interest` prompt**

Read lines 200-217.

**Step 2: Rewrite the prompt**

```python
    elif response_type == "general_interest":
        prompt = f"""Write a brief email reply to a lead who has shown general interest but hasn't asked for anything specific.

SENDER IDENTITY:
- You are {sender_name} from Resource Realty Group
- Your direct line: {phone}
- Signoff: {signoff}

LEAD CONTEXT:
- Lead's first name: {first_name}
- Their reply: {reply_body[:500]}

PROPERTY DATA (from fact sheet — use ONLY this data, do NOT invent any facts):
{prop_text}

STRUCTURE (follow exactly):
1. Greeting: "Hey {{first_name}},"
2. Body: 3-4 sentences. Acknowledge their interest warmly. Ask what specific information they'd like (tour, OM, financials, etc.). Mention your direct line.
3. Signoff: Use exactly: {signoff}

RULES:
- Do NOT include a subject line
- Do NOT invent property details not listed above
- Stay on topic — respond to what they said
- Write ONLY the email body text"""
```

**Step 3: Test with a live run**

**Step 4: Commit**

```bash
git add windmill/f/switchboard/lead_conversation.flow/generate_response_draft.inline_script.py
git commit -m "feat(lead_conversation): rigidify general_interest prompt framework"
```

---

### Task 7: Rewrite `want_something` prompt with rigid framework + NDA logic

**Files:**
- Modify: `windmill/f/switchboard/lead_conversation.flow/generate_response_draft.inline_script.py:219-247`

**Step 1: Read current `want_something` prompt**

Read lines 219-247.

**Step 2: Rewrite the prompt with fact sheet data and NDA rules**

```python
    elif response_type == "want_something":
        wants_text = ", ".join(wants) if wants else "unspecified information"

        # Build NDA context
        nda_context = ""
        if not has_nda:
            nda_context = "The lead has NOT signed an NDA. If they ask for financials, rent roll, or T12, tell them these require an NDA and offer to send one."
        else:
            nda_context = "The lead HAS signed an NDA. Financials can be shared."

        # Build market status context per property
        market_context = []
        for p in properties:
            status = p.get("market_status", "unknown")
            has_fin = p.get("brochure_has_financials", False)
            name = p.get("canonical_name", "the property")
            if status == "off-market":
                if has_nda:
                    market_context.append(f"- {name}: Off-market. NDA signed — can share full brochure and financials.")
                else:
                    market_context.append(f"- {name}: Off-market. No NDA — can share redacted brochure only. Financials require NDA.")
            elif status == "on-market":
                if has_fin and not has_nda:
                    market_context.append(f"- {name}: On-market. Brochure contains financials — NDA required to share.")
                else:
                    market_context.append(f"- {name}: On-market. Brochure can be shared freely.")
            else:
                market_context.append(f"- {name}: Market status unknown.")
        market_text = "\n".join(market_context) if market_context else "  (no market status data)"

        prompt = f"""Write a brief email reply to a lead who has asked for specific information.

SENDER IDENTITY:
- You are {sender_name} from Resource Realty Group
- Your direct line: {phone}
- Signoff: {signoff}

LEAD CONTEXT:
- Lead's first name: {first_name}
- What they asked for: {wants_text}
- Their reply: {reply_body[:500]}

PROPERTY DATA (from fact sheet — use ONLY this data, do NOT invent any facts):
{prop_text}

AVAILABLE DOCUMENTS:
{docs_text}

NDA STATUS:
{nda_context}

MARKET STATUS & BROCHURE ACCESS:
{market_text}

STRUCTURE (follow exactly):
1. Greeting: "Hey {{first_name}},"
2. Body: 3-5 sentences. Address ONLY what they asked for. If the data is in the property info above, include it. If it's NOT above, say "Let me check on that and get back to you."
3. Signoff: Use exactly: {signoff}

RULES:
- Do NOT include a subject line
- Do NOT invent numbers, prices, or facts not listed in PROPERTY DATA
- Stay on topic — if they asked about price, don't talk about tours
- If they want a tour, offer to schedule and ask for preferred date/time
- If they want financials and don't have NDA, mention NDA requirement
- If they want documents we have, say you'll send them over
- Write ONLY the email body text"""
```

**Step 3: Test with a live run — lead asking for price (data available)**

**Step 4: Test with a live run — lead asking for financials (no NDA)**

**Step 5: Commit**

```bash
git add windmill/f/switchboard/lead_conversation.flow/generate_response_draft.inline_script.py
git commit -m "feat(lead_conversation): rigidify want_something prompt with NDA/fact sheet logic"
```

---

### Task 8: Add three-way source branching structure

**Files:**
- Modify: `windmill/f/switchboard/lead_conversation.flow/generate_response_draft.inline_script.py:150-159`
- Modify: `windmill/f/switchboard/lead_intake.flow/generate_drafts_+_gmail.inline_script.py:199`

**Step 1: Update source classification in lead_conversation Module B**

Replace the simple `is_commercial` with a three-way split that's ready for residential:

```python
    # Source classification
    is_commercial = source.lower() in ("crexi", "loopnet", "bizbuysell")
    is_residential_buyer = source.lower() in ("realtor.com", "homes.com")
    is_residential_seller = source.lower() in ("upnest", "seller_hub", "top_producer")

    # Determine signer — check template_used for in-flight thread continuity
    template_used = classify_result.get("template_used", "")
    if template_used.startswith("commercial_") or template_used == "lead_magnet":
        # In-flight thread — keep Larry
        signoff = "Talk soon,\nLarry"
        phone = "(734) 732-3789"
        sender_name = "Larry"
    elif template_used.startswith("residential_"):
        # In-flight thread — keep Andrea
        signoff = "ANDREA_SIGNOFF_TBD"
        phone = "ANDREA_PHONE_TBD"
        sender_name = "Andrea"
    elif is_commercial:
        signoff = "Talk soon,\nLarry"
        phone = "(734) 732-3789"
        sender_name = "Larry"
    elif is_residential_buyer or is_residential_seller:
        # Placeholder — will be filled in Phase 3 with Andrea's details
        signoff = "ANDREA_SIGNOFF_TBD"
        phone = "ANDREA_PHONE_TBD"
        sender_name = "Andrea"
    else:
        # Unknown source — default to Larry for now
        signoff = "Talk soon,\nLarry"
        phone = "(734) 732-3789"
        sender_name = "Larry"
```

**Step 2: Update source classification in lead_intake**

Add the same three-way awareness to `generate_drafts_+_gmail.inline_script.py`. The existing `is_commercial` check at line 199 stays. Add residential flags below it:

```python
        is_commercial = source.lower() in ("crexi", "loopnet", "bizbuysell")
        is_residential_buyer = source.lower() in ("realtor.com", "homes.com")
        is_residential_seller = source.lower() in ("upnest", "seller_hub", "top_producer")
```

Don't change the template selection logic yet — just add the flags. Phase 3 fills in the residential branch.

**Step 3: Verify commercial still works**

Run a Crexi test to confirm the three-way split didn't break existing behavior.

**Step 4: Commit**

```bash
git add windmill/f/switchboard/lead_conversation.flow/generate_response_draft.inline_script.py \
        windmill/f/switchboard/lead_intake.flow/generate_drafts_+_gmail.inline_script.py
git commit -m "feat: add three-way source classification (commercial/residential buyer/residential seller)"
```

---

### Task 9: Update lead magnet template to use Larry's signature + standard variables

**Files:**
- Modify: `windmill/f/switchboard/lead_intake.flow/generate_drafts_+_gmail.inline_script.py:237-244`

**Step 1: Read current lead magnet template**

Read lines 237-244.

**Step 2: Rewrite with Larry's signature and standard variables**

```python
        # 3. Lead magnet — all properties are lead_magnet (signed Larry for commercial)
        elif has_lead_magnet and not non_magnet_props:
            magnet = properties[0]
            canonical = magnet.get("canonical_name", "")
            addr = magnet.get("property_address") or canonical
            draft["email_subject"] = f"RE: Your Interest in {canonical}"
            draft["email_body"] = f"Hey {first_name},\n\nI got your information when you checked out my listing for {addr}. That property is no longer available, but we have some similar properties that might be a good fit depending on what you're looking for.\n\nIf you'd like to check out what we have, just let me know and I can send over some information. We also have some off-market properties that would require an NDA to be signed.\n\nIf you'd rather talk over the phone, my direct line is (734) 732-3789. Please do not hesitate to reach out with any questions or concerns.\n\nTalk soon,\nLarry"
            draft["sms_body"] = f"Hey {first_name}, this is Larry from Resource Realty Group. I saw you checked out {canonical}. That one's no longer available, but I have some similar properties. Let me know if you're interested! My direct line is (734) 732-3789." if phone else None
            draft["template_used"] = "lead_magnet"
```

**Step 3: Commit**

```bash
git add windmill/f/switchboard/lead_intake.flow/generate_drafts_+_gmail.inline_script.py
git commit -m "fix(lead_intake): lead magnet template now signed Larry with standard variables"
```

---

### Task 10: Add lead magnet handling to lead_conversation prompts

**Files:**
- Modify: `windmill/f/switchboard/lead_conversation.flow/generate_response_draft.inline_script.py`

**Step 1: Add lead magnet check before response generation**

In the `main()` function, after determining `response_type` (around line 370), add a check:

```python
    # Check if this is a lead magnet property — redirect toward active listings
    is_lead_magnet = any(p.get("lead_magnet", False) for p in properties)
    if is_lead_magnet:
        response_type = "lead_magnet_redirect"
```

**Step 2: Add `lead_magnet_redirect` prompt to `generate_response_with_claude()`**

Add a new branch before the `else` fallback:

```python
    elif response_type == "lead_magnet_redirect":
        prompt = f"""Write a brief email reply to a lead who is responding about a property that is no longer available (lead magnet listing).

SENDER IDENTITY:
- You are {sender_name} from Resource Realty Group
- Your direct line: {phone}
- Signoff: {signoff}

LEAD CONTEXT:
- Lead's first name: {first_name}
- Property they asked about: {prop_text}
- Their reply: {reply_body[:500]}

STRUCTURE (follow exactly):
1. Greeting: "Hey {{first_name}},"
2. Body: 3-4 sentences. Acknowledge their interest. Let them know that property is no longer available. Mention you have similar properties and off-market opportunities. Offer to send info or set up a call.
3. Signoff: Use exactly: {signoff}

RULES:
- Do NOT include a subject line
- Do NOT make up details about other properties
- Do NOT apologize excessively — keep it positive and forward-looking
- Write ONLY the email body text"""
```

**Step 3: Commit**

```bash
git add windmill/f/switchboard/lead_conversation.flow/generate_response_draft.inline_script.py
git commit -m "feat(lead_conversation): add lead magnet redirect prompt for conversation replies"
```

---

### Task 11: Pass `template_used` through to lead_conversation

**Files:**
- Read: `windmill/f/switchboard/gmail_pubsub_webhook.py:846-858` (already returns template_used)
- Modify: `windmill/f/switchboard/lead_conversation.flow/fetch_thread_+_classify_reply.inline_script.py`

**Step 1: Verify webhook already passes `template_used`**

Read `gmail_pubsub_webhook.py:857`. Confirm `template_used` is in the `find_outreach_by_thread()` return dict. (It is — line 857.)

**Step 2: Pass `template_used` through Module A**

In `fetch_thread_+_classify_reply.inline_script.py`, add `template_used` to the input reading (around line 188) and the return dict (around line 219):

```python
    template_used = reply_data.get("template_used", "")
```

And in the return dict:
```python
        "template_used": template_used,
```

**Step 3: Read `template_used` in Module B**

In `generate_response_draft.inline_script.py`, add to the variable extraction in `main()` (around line 291):

```python
    template_used = classify_result.get("template_used", "")
```

This is already used by the three-way signer logic from Task 8.

**Step 4: Commit**

```bash
git add windmill/f/switchboard/lead_conversation.flow/fetch_thread_+_classify_reply.inline_script.py \
        windmill/f/switchboard/lead_conversation.flow/generate_response_draft.inline_script.py
git commit -m "feat(lead_conversation): pass template_used through for signer continuity"
```

---

### Task 12: Deploy and test Phase 2 changes

**Step 1: Push to GitHub and sync**

```bash
git push origin main
ssh andrea@rrg-server 'cd ~/rrg-server && git pull'
```

**Step 2: Push to Windmill**

```bash
cd ~/rrg-server && wmill sync push
```

**Step 3: Run E2E test — Crexi WANT_SOMETHING (price question)**

Trigger lead_conversation with a test reply asking about price. Verify:
- Draft references actual fact sheet data (not made up)
- If data missing, says "let me check on that"
- Signed Larry
- HTML renders correctly

**Step 4: Run E2E test — NOT_INTERESTED**

Verify gracious close, no pushiness, Larry signature.

**Step 5: Run E2E test — GENERAL_INTEREST**

Verify asks what they need, mentions phone, Larry signature.

**Step 6: Document results and commit**

```bash
git commit -m "docs: Phase 2 E2E test results"
```

---

## CHECKPOINT: Get Jake's input before Phase 3

Phase 3 requires materials from Jake:
1. Andrea's template text
2. Andrea's signoff, phone number, contact details
3. Realtor.com-specific template variation
4. Sample emails from UpNest, Seller Hub, Top Producer

**Do not proceed to Phase 3 until Jake provides these.**

---

## Phase 3: Residential Pipeline (Issue 7)

### Task 13: Add Andrea's contact info and residential templates to lead_intake

**Files:**
- Modify: `windmill/f/switchboard/lead_intake.flow/generate_drafts_+_gmail.inline_script.py`

**Step 1: Get Andrea's details from Jake**

Need: full name, phone, signoff text, email template text.

**Step 2: Update existing `realtor_com` template**

Replace Jake's signature with Andrea's. Replace Jake's phone with Andrea's. Use the Realtor.com-specific template Jake provides.

**Step 3: Update existing `seller_hub` template**

Replace Jake's signature with Andrea's.

**Step 4: Add new residential seller templates**

Add `upnest` and `top_producer` template branches using Andrea's generic seller template.

**Step 5: Update template selection to use three-way split**

Restructure the if/elif chain:

```python
        # --- Template selection ---

        # Residential buyer
        if source_type == "realtor_com":
            # Realtor.com template (Andrea, more official)
            ...

        # Residential seller
        elif is_residential_seller:
            if source_type == "seller_hub":
                ...
            elif source_type == "upnest":
                ...
            elif source_type == "top_producer":
                ...

        # Lead magnet
        elif has_lead_magnet and not non_magnet_props:
            ...

        # Commercial (Crexi/LoopNet/BizBuySell)
        elif is_commercial:
            ...

        else:
            continue
```

**Step 6: Commit**

```bash
git add windmill/f/switchboard/lead_intake.flow/generate_drafts_+_gmail.inline_script.py
git commit -m "feat(lead_intake): add residential templates signed by Andrea Gotcher"
```

---

### Task 14: Add residential source parsing to webhook

**Files:**
- Modify: `windmill/f/switchboard/gmail_pubsub_webhook.py`

**Step 1: Review current source detection**

Read the `categorize_leads_email()` function to understand how sources are detected from email headers/body.

**Step 2: Add parsers for UpNest and Top Producer**

Using sample emails Jake provides, add parsing logic for each new source. Extract: name, email, phone (when available), property address (when available).

**Step 3: Verify Realtor.com parser extracts property data**

The current parser already handles `realtor_com` source_type. Enhance it to also extract:
- Property availability status (active, pending, under contract)
- Property address from the email body snapshot
- What the buyer is asking for (tour, info, etc.)

**Step 4: Add Realtor.com fast-path (no batching)**

When source is Realtor.com, process immediately as single-lead instead of batching:
- Skip the staging table / batch collection
- Trigger lead_intake directly with the single lead

**Step 5: Commit**

```bash
git add windmill/f/switchboard/gmail_pubsub_webhook.py
git commit -m "feat(webhook): add residential source parsers and Realtor.com fast-path"
```

---

### Task 15: Add residential conversation prompts to lead_conversation

**Files:**
- Modify: `windmill/f/switchboard/lead_conversation.flow/fetch_thread_+_classify_reply.inline_script.py`
- Modify: `windmill/f/switchboard/lead_conversation.flow/generate_response_draft.inline_script.py`

**Step 1: Add source-branched classification prompt in Module A**

In `classify_with_claude()`, select the classification prompt based on source:

```python
    if source.lower() in ("crexi", "loopnet", "bizbuysell"):
        # Commercial buyer classification prompt (existing)
        ...
    elif source.lower() in ("realtor.com", "homes.com"):
        # Residential buyer classification prompt
        # Same categories but tuned for buyer context
        ...
    elif source.lower() in ("upnest", "seller_hub", "top_producer"):
        # Residential seller classification prompt
        # Same categories but tuned for seller context
        # ("what's your commission?" = WANT_SOMETHING, "I listed with someone else" = NOT_INTERESTED)
        ...
```

**Step 2: Add residential prompt frameworks in Module B**

Add Andrea's prompt variants for each response type when source is residential.

**Step 3: Commit**

```bash
git add windmill/f/switchboard/lead_conversation.flow/fetch_thread_+_classify_reply.inline_script.py \
        windmill/f/switchboard/lead_conversation.flow/generate_response_draft.inline_script.py
git commit -m "feat(lead_conversation): add residential buyer/seller prompt frameworks"
```

---

### Task 16: Deploy and test Phase 3

**Step 1: Push and sync**

```bash
git push origin main
ssh andrea@rrg-server 'cd ~/rrg-server && git pull'
cd ~/rrg-server && wmill sync push
```

**Step 2: Test residential seller lead (Seller Hub)**

Trigger lead_intake with a test Seller Hub notification. Verify:
- Template signed Andrea
- Correct template text
- Draft appears in teamgotcher@gmail.com

**Step 3: Test Realtor.com fast-path**

Trigger with a Realtor.com notification. Verify:
- Processed immediately (no batching)
- Property data parsed from email
- Availability status extracted
- Template adapted to availability
- Signed Andrea

**Step 4: Test residential conversation reply**

Reply to a residential outreach draft. Verify:
- Classification uses residential-appropriate prompt
- Response uses Andrea's framework
- Signed Andrea

**Step 5: Test in-flight thread continuity**

Reply to an OLD thread that was signed by Jake. Verify:
- lead_conversation reads `template_used` from signal
- Response keeps Jake's signature for continuity (not Andrea)

**Step 6: Document results and commit**

```bash
git commit -m "docs: Phase 3 E2E test results"
```

---

## Phase 4: LoopNet & BizBuySell Testing (Issue 3)

### Task 17: Trigger LoopNet test leads

**Step 1: Create a test lead on LoopNet**

Jake manually triggers a LoopNet inquiry to generate a real lead notification email.

**Step 2: Verify full pipeline**

Watch the lead flow through: webhook parse → lead_intake → signal → draft in Gmail.
Check: template, signature (Larry), HTML rendering, property data.

**Step 3: Test conversation reply**

Reply to the LoopNet draft. Verify lead_conversation handles it correctly with rigid prompts.

---

### Task 18: Trigger BizBuySell test leads

Same as Task 17 but for BizBuySell source.

---

### Task 19: Final documentation update

**Files:**
- Modify: `docs/LEAD_CONVERSATION_ENGINE.md`
- Modify: `docs/LEAD_INTAKE_PIPELINE.md`
- Modify: `CLAUDE.md` (root)

**Step 1: Update LEAD_CONVERSATION_ENGINE.md**

- Document rigid prompt framework
- Document three-way source classification
- Document residential conversation prompts
- Document signer continuity via template_used

**Step 2: Update LEAD_INTAKE_PIPELINE.md**

- Document residential templates (Andrea signs)
- Document new sources (UpNest, Top Producer)
- Document Realtor.com fast-path
- Document lead magnet template update

**Step 3: Update root CLAUDE.md**

- Add residential sources to lead sources list
- Update template signing info (Andrea for residential)
- Note Realtor.com fast-path

**Step 4: Commit**

```bash
git add docs/ CLAUDE.md
git commit -m "docs: update all docs for residential pipeline and rigid prompts"
git push origin main
ssh andrea@rrg-server 'cd ~/rrg-server && git pull'
```

---

## Task Summary

| Task | Phase | Description | Depends on |
|------|-------|-------------|------------|
| 1 | 1 | Verify source field chain | — |
| 2 | 1 | Validate is_commercial with Crexi | 1 |
| 3 | 1 | Validate is_commercial with LoopNet/BizBuySell | 1 |
| 4 | 1 | Commit Phase 1 findings | 2, 3 |
| 5 | 2 | Rigidify not_interested prompt | 4 |
| 6 | 2 | Rigidify general_interest prompt | 4 |
| 7 | 2 | Rigidify want_something prompt + NDA logic | 4 |
| 8 | 2 | Add three-way source branching | 4 |
| 9 | 2 | Update lead magnet template (Larry signs) | 8 |
| 10 | 2 | Add lead magnet conversation prompt | 7 |
| 11 | 2 | Pass template_used for signer continuity | 8 |
| 12 | 2 | Deploy and test Phase 2 | 5-11 |
| **CHECKPOINT** | — | **Jake provides Andrea's templates + details** | 12 |
| 13 | 3 | Add residential intake templates | checkpoint |
| 14 | 3 | Add residential webhook parsers + Realtor.com fast-path | checkpoint |
| 15 | 3 | Add residential conversation prompts | 13 |
| 16 | 3 | Deploy and test Phase 3 | 13-15 |
| 17 | 4 | LoopNet E2E test | 12 |
| 18 | 4 | BizBuySell E2E test | 12 |
| 19 | — | Final documentation update | 16-18 |
