# E2E Pipeline Testing Design

> **Date:** 2026-02-26
> **Scope:** Exhaustive end-to-end testing of lead_intake and lead_conversation pipelines

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

---

## Pre-Test Code Change: BCC leads@ on All Outbound Emails

**What:** Add `bcc: leads@resourcerealtygroupmi.com` to every outgoing email draft so all office agents have visibility into outbound lead communication.

**Where:**
- `lead_intake` Module D: `create_gmail_draft()` — add BCC header to MIMEText
- `lead_conversation` Module B: `create_reply_draft()` — add BCC header to MIMEText

**Verification:** Every test case naturally verifies this — check that leads@ receives a copy of each sent email.

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
| 8 | UpNest (seller) | residential_seller | Andrea | Same template as Seller Hub, UpNest attribution |
| 9 | Lead magnet property | lead_magnet | Larry | "no longer available" language, similar properties offer |

### Group 2: Lead Intake — Commercial Branching (3 tests)

| # | Scenario | Template | Key Verification |
|---|----------|----------|-----------------|
| 10 | Single property, followup (existing contact w/ recent note) | commercial_followup_template | is_followup=true, shorter template |
| 11 | Multi-property, first contact | commercial_multi_property_first_contact | Inline property list formatting |
| 12 | Multi-property, followup | commercial_multi_property_followup | Shortest template |

### Group 3: Lead Intake — Edge Cases (4 tests)

| # | Scenario | Key Verification |
|---|----------|-----------------|
| 13 | Company name (not a person) | "Hey there," greeting |
| 14 | Lead with no email | Module E skipped=true, no zombie flow |
| 15 | Same person, two notifications in 30s batch window | Batched into single flow, multi-property |
| 16 | Fuzzy property dedup ("CMC Transportation" + "CMC Transportation in Ypsilanti") | Single property, longer name kept |

### Group 4: Approval Loop (3 tests)

| # | Scenario | Key Verification |
|---|----------|-----------------|
| 17 | Send draft (approve) | Pub/Sub → SENT detect → thread_id match → resume → CRM "Contacted" + note + SMS |
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

### Group 6: Lead Conversation — Residential Prompts (2 tests)

| # | Scenario | Key Verification |
|---|----------|-----------------|
| 25 | Reply to residential buyer outreach (Realtor.com thread) | Residential buyer prompt framework, Andrea signer |
| 26 | Reply to residential seller outreach (Seller Hub thread) | Residential seller prompt framework, Andrea signer |

### Group 7: Lead Conversation — Approval Loop (2 tests)

| # | Scenario | Key Verification |
|---|----------|-----------------|
| 27 | Send conversation reply draft | Pub/Sub → resume → CRM note + SMS |
| 28 | Delete conversation reply draft | Resume → rejection note |

**Total: 28 test cases**

---

## Execution Flow (per test)

```
1. Seed test email into leads@ (or reply into teamgotcher@)
2. Pub/Sub fires → webhook runs automatically
3. Verify Windmill job completed successfully
4. Jake checks the draft in teamgotcher@ Gmail
5. Jake sends or deletes the draft
6. Verify: signal status, CRM contact/note, SMS received, BCC in leads@
7. CHECKPOINT: Did anything look wrong?
   ├── Yes → Diagnose root cause, fix the code, re-run THIS test case
   └── No → Move to next test
```

---

## Cleanup After Testing

- Delete all `TEST -` prefixed contacts from WiseAgent
- Clean up any remaining test drafts in teamgotcher@
- Test signals in jake_signals will be naturally marked as acted
