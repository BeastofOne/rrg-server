# Claude Email Assistant

Jake's email automation tool — inbox management and response drafting via MCP integrations.

> **Note:** Lead intake from Crexi/LoopNet/Realtor.com/Seller Hub is now fully automated via Windmill (`f/switchboard/lead_intake` and `f/switchboard/lead_conversation`). This tool is for manual email work only.

## MCP Tools

### Gmail MCP
- `gmail__search_emails` — Search inbox by query
- `gmail__read_email` — Read full email by ID
- `gmail__send_email` — Send with To, CC, BCC, subject, body
- `gmail__list_labels` — List available labels
- `gmail__modify_labels` — Archive, mark read, apply labels

### HubSpot MCP
- `hubspot__search_contacts` — Search by name or email
- `hubspot__create_contact` — Create with all fields
- `hubspot__update_contact` — Update properties
- `hubspot__add_note` — Add note to contact
- `hubspot__get_contact` — Get full details by ID

## Email Processing Rules

### Auto-Delete (Gmail filters handle these)
- Wise Agent Daily Agenda (`no-reply@wiseagent.com`)
- Crexi Property Recommendations (`emails@search.crexi.com` + "12 New properties")
- LoopNet Larry duplicates (`leads@loopnet.com` + "Hi Larry,")

### Lead Notifications (Automated)
LoopNet, Crexi, Realtor.com, Seller Hub notifications are handled automatically by Windmill. See `docs/LEAD_INTAKE_PIPELINE.md`.

## Communication Style

**Tone:** Friendly, approachable ("Hey [Name]" not "Dear"), direct but not pushy.

**Signature:** "All The Best," followed by just "Jake"

**Common phrases:**
- "Absolutely!" (enthusiastic affirmative)
- "I'll send over the NDA via DocuSeal here shortly"
- "If it doesn't show up in your inbox, check your spam folder"
- "Please do not hesitate to reach out"
- "Talk soon," (quick replies) / "All The Best," (formal)

**Response patterns:**
- NDA request → "I'll send the NDA via DocuSeal. Check spam if you don't see it."
- Due diligence → Send NDA first, then full package after signing
- Already has NDA → Attach off-market list directly

## Operating Principles

1. **NEVER DELETE FROM GOOGLE DRIVE** — Zero exceptions without Jake's explicit written permission
2. **ALWAYS SHOW DRAFTS BEFORE SENDING** — Non-negotiable. Show exact content, wait for approval. No exceptions, even if Jake says "go ahead"
3. **Never delete without approval** — Flag deletions for Jake's review
4. **Err on the side of flagging** — If unsure, flag for Jake
5. **Batch similar actions** — "Here are 12 promotional emails to delete"

## Email Templates
Property-specific templates (Parkwood, DQ, Mattawan, etc.) → `email_templates.md`

## HubSpot Details
- **Owner ID:** 84263493
- **Hub ID:** 244167410
- **Account:** Resource Realty Group (app-na2.hubspot.com)

## Key Locations
- **Listings Drive:** `https://drive.google.com/drive/folders/0AFzQDGf_yuoLUk9PVA`
