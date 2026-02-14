---
name: leads
description: Lead intake processing for CRE leads via Windmill pipeline using WiseAgent CRM. Use when processing leads, checking the pipeline, approving signals, or handling lead notifications. Triggers on "lead", "prospect", "intake", "crexi", "loopnet", "realtor.com", "signal", "approve".
---

# Lead Intake System (RRG Server — Windmill Pipeline)

Property mapping data is stored as Windmill variable `property_mapping` (NOT a local file).

## Pipeline Architecture

The lead intake runs as a Windmill flow (`f/switchboard/lead_intake`) with 6 modules:

| Module | What | CRM/Service |
|--------|------|-------------|
| a | Contact lookup by email | **WiseAgent** (OAuth API) |
| b | Property matching | Windmill `property_mapping` variable |
| c | Dedup/grouping | Internal logic |
| d | Generate drafts + Gmail | Gmail OAuth (`f/switchboard/gmail_oauth`) |
| e | Approval gate (suspend) | Signal system (`jake_signals` Postgres table) |
| f | Post-approval: CRM update + SMS | **WiseAgent** notes + SMS Gateway |

## CRM: WiseAgent (NOT HubSpot)

The automated pipeline uses **WiseAgent CRM**, not HubSpot:
- OAuth API: `sync.thewiseagent.com`
- Credentials: Windmill resource `f/switchboard/wiseagent_oauth` (auto-refreshed)
- Operations: contact lookup by email, create contact, add notes, check NDA status
- Client ID/secret: Windmill resource `f/wiseagent/credentials`

## 8-Phase Lead Processing

### Phase 1: SCAN
Search Gmail for leads. **Always use `in:inbox`** to exclude archived:
```
in:inbox from:notifications.crexi.com ("opened offering memorandum" OR "opened flyer" OR "downloaded the flyer")
in:inbox from:notifications.crexi.com "requesting Information"     # MANUAL REVIEW
in:inbox from:loopnet.com "favorited" to:andrea
in:inbox subject:"New realtor.com lead"                            # PRIORITY
in:inbox subject:"New Verified Seller Lead"
in:inbox from:jacob@resourcerealtygroupmi.com subject:"completed"  # DocuSeal NDA
```

### Phase 2: PARSE
Extract from each notification: Name, Email (SOURCE OF TRUTH from notification body), Phone, Property, Source.
**NEVER replace notification email with HubSpot email.**

### Phase 3: HUBSPOT LOOKUP + DEDUP
- Same-batch dedup: group by unique email, combine multi-property into one outreach
- HubSpot search: check `hs_lead_status` for NDA status
- NDA detection: `ATTEMPTED_TO_CONTACT` or `UNQUALIFIED` → has NDA (Version B)
- Pre-Claude contacts (no "outreach sent" note) → treat as NEW

### Phase 4: PROPERTY MATCH
Match against `property_mapping` Windmill variable:
- Get `canonical_name`, `hubspot_deal_id`, `brochure_highlights`
- Check `lead_magnet` flag for buy-box pivot
- Flag unmapped properties for Jake

### Phase 5: GENERATE DRAFTS
Select template: Source × NDA Status × First Contact/Follow-up

**Templates (Crexi/LoopNet):**
- Version A (no NDA): includes NDA offer paragraph
- Version B (has NDA): offers off-market list directly
- Follow-up: shorter, skips intro

**Realtor.com:** "Are you looking to take a tour?"
**Seller Hub:** "I heard you might be interested in selling"

### Phase 6: PRESENT BATCH
Display PRE-FLIGHT CHECKLIST, then present all leads with drafts for Jake's approval.

### Phase 7: EXECUTE
For each approved lead:
1. Create/Update HubSpot Contact
2. Associate with Deal (if mapped)
3. Send Email (CC Jasmin, NEW email never reply to notification)
4. Send SMS
5. Add HubSpot Note

### Phase 8: VERIFY & CLEANUP
Verify all Phase 7 steps completed before archiving notifications.

## Signal-Based Approval

Leads don't send automatically. The flow suspends at module (e) and writes a signal:
1. Check pending: `s/switchboard/get_pending_draft_signals`
2. Review generated drafts in signal payload
3. Approve: `s/switchboard/act_signal`
4. Flow resumes module (f): WiseAgent note + SMS

## Quick Reference

| Lead Type | Gmail Search | Priority | Response |
|-----------|--------------|----------|----------|
| Crexi OM/Flyer | `from:notifications.crexi.com "opened" OR "downloaded"` | Normal | Email + SMS (Version A/B) |
| Crexi Info Request | `from:notifications.crexi.com "requesting Information"` | MANUAL | Custom response |
| LoopNet | `from:loopnet.com "favorited"` | Normal | Email + SMS (Version A/B) |
| Realtor.com | `subject:"New realtor.com lead"` | **HIGH** | Email + SMS (fixed) |
| Seller Hub | `subject:"New Verified Seller Lead"` | Normal | Email + SMS (fixed) |
| DocuSeal NDA | `from:jacob@resourcerealtygroupmi.com subject:"completed"` | Auto | HubSpot update only |

## Key Rules
- ALL lead responses = NEW emails (never reply to notifications)
- ALL initial outreach = Email + SMS
- CC Jasmin on ALL emails
- Email from notification = source of truth (never substitute CRM email)
- Realtor.com = PRIORITY
- Info Request = MANUAL (flag for Jake)
