# Lead Pipeline Fixes & Residential Expansion — Design

*Date: February 25, 2026*
*Approach: Fix-first, then build (Approach A)*

---

## Issue Board

| # | Issue | Category | Phase |
|---|-------|----------|-------|
| 1 | Three premature fixes on `main` need validation | Troubleshooting | 1 |
| 4 | WANT_SOMETHING path doesn't look up property data | Absorbed by #6 | 2 |
| 5 | Wrong signature on commercial leads | Bug fix | 1 |
| 6 | Lead conversation templates need rigid prompt framework | Redesign | 2 |
| 7 | Full residential pipeline (Andrea signs all) | New feature | 3 |
| 3 | LoopNet & BizBuySell untested | Testing | 4 |
| 8 | Lead magnet template updates | Fix | 2 |

**Parked:**
- Issue 2: SMS inbound reply detection (separate infrastructure project)
- Homes.com (unknown buyer/seller classification)
- Residential SMS (no device for Andrea yet)
- Residential NDA logic (not needed unless rental property)
- Property fact sheet creation (separate full-day project)

---

## Phase 1: Validate & Fix (Issues 1, 5)

### 1a. Three premature fixes validation

Already committed to `main` via auto-sync. Need real pipeline test runs to verify:

- **`is_commercial` fix** — `source.lower() in ("crexi", "loopnet", "bizbuysell")` replacing old `source_type` check. Test with each source.
- **HTML email fix** — `MIMEText(html_body, 'html')` in both lead_conversation and lead_intake. Visual check in Gmail.
- **Reply channel detection** — `reply_channel == "sms"` gate. Currently a no-op (defaults to "email"). Safe as-is, untestable until SMS inbound exists.

### 1b. Signature fix (Issue 5)

Code at lines 151-159 of `generate_response_draft.inline_script.py` already has Larry/Jake split based on `is_commercial`. Verify with a real test run that commercial leads actually get Larry's signature.

---

## Phase 2: Rigid Lead Conversation Prompts + Lead Magnets (Issues 6, 4, 8)

### Architecture: Tighter Claude prompts, not f-string replacement

Keep `generate_response_with_claude()`. Claude handles natural language flexibility. The prompts constrain what Claude can say.

**Why keep Claude:** The scope of what someone could ask or how they word it is too vast for simple f-string branching. Claude handles the variance; rigid prompts handle the rules.

### Property Fact Sheet as Single Source of Truth

Each property has a fact sheet in `property_mapping` — the master data record. All variables live here (price, address, NOI, cap rate, square footage, zoning, tenant info, etc.).

**Five documents per property** (all derived from fact sheet data):
1. **Property Fact Sheet** — the database, source of truth
2. **Brochure** — marketing document, generated from fact sheet
3. **Listing** — the Crexi/LoopNet/etc. listing
4. **Proforma** — financial projections (can be generated on the fly)
5. **Financials** — actual financial data (rent roll, T12, etc.)

The fact sheets themselves are a separate full-day project. This design assumes the structure exists; population comes later.

### Prompt Framework Principles

1. Every piece of data Claude can reference must come from the property fact sheet
2. Claude is told: "use ONLY the data from the property fact sheet below" — no making stuff up
3. Prompt defines exact structure: greeting, body, closing, signoff
4. Must stay on topic — if they ask about financing, don't talk about tours
5. Claude's job: make it sound natural and respond to the lead's specific wording, within these constraints

### NDA / Brochure Logic (Commercial Only)

**Off-market property:**
- Lead asks for brochure → Check WiseAgent for NDA category on contact
  - NDA signed → Send clean (unredacted) brochure
  - No NDA → Send redacted brochure + note: "financials require an NDA, I can send one over"

**On-market property:**
- Brochure has financials → NDA required. Don't send redacted version either.
- Brochure has no financials → Send freely.

**Key variables on fact sheet:**
- `market_status`: on-market vs off-market
- `brochure_has_financials`: boolean
- `redacted_brochure_path`: path to redacted version (off-market only)
- `clean_brochure_path`: path to full version

NDA status comes from WiseAgent contact record (category field), not from the fact sheet.

### Lead Magnet Handling (Issue 8)

- `lead_magnet` flag on fact sheet drives template selection
- **Lead intake:** Standard lead magnet template with variables, signed Larry for commercial. Replace current per-property `response_override` blobs. Can overhaul individual properties later if standard template isn't satisfactory.
- **Lead conversation:** When someone replies to a lead magnet outreach, redirect toward active listings ("thanks for your interest in {property}, that one is no longer available, but we have similar properties...")
- Which properties are lead magnets — determined during the separate fact sheet project

### Response Types (unchanged structure, tighter prompts)

- `not_interested` — gracious close, leave door open
- `general_interest` — acknowledge interest, ask what they need
- `want_something` — answer from fact sheet data, NDA rules apply, stay on topic

---

## Phase 3: Residential Pipeline (Issue 7)

### Andrea Gotcher Signs All Residential

Jake is fully out of the residential pipeline. All residential leads signed by Andrea Gotcher.

- Email sent from: teamgotcher@gmail.com (same as commercial)
- Approval gate: Same as commercial — draft lands in teamgotcher, office staff review
- SMS: None for now (no device for Andrea — fully parked)
- NDA: None for residential (parked unless it becomes a bottleneck)

### Residential Source Classification

| Source | Type | Data in email | Status |
|--------|------|---------------|--------|
| Realtor.com | Buyer | Rich — property snapshot with availability status | Fast-path, no batching |
| Homes.com | Unknown (possibly seller) | Unknown | Parked |
| UpNest | Seller | Varies — need sample emails | Needs parsing |
| Seller Hub | Seller | Varies — need sample emails | Needs parsing |
| Top Producer | Seller | Varies — need sample emails | Needs parsing |

### Source Classification Logic

```python
is_commercial = source.lower() in ("crexi", "loopnet", "bizbuysell")
is_residential_buyer = source.lower() in ("realtor.com", "homes.com")
is_residential_seller = source.lower() in ("upnest", "seller_hub", "top_producer")
```

### Realtor.com — Fast-Path Buyer Leads

Fundamentally different from all other lead types:

1. **Lead email contains property data** — snapshot/iframe of listing with address, status, details
2. **Parse email for:** what the buyer wants (tour, info) AND property availability (active, pending, under contract)
3. **Availability check is step one** — drives the entire response
4. **No batching** — ~5 second delay max. Email sent ASAP.
5. **Still goes through approval gate** (for now — will be removed when fully automated)
6. **Response adapts to availability:**
   - Available → respond to what they asked for
   - Under contract/pending → tell them honestly, offer alternatives
   - Other issues → flag in response
7. **Own template** — more official-looking than standard residential, still Andrea's framework
8. **Own email + SMS template** (SMS parked until Andrea has device)

### Seller Leads (UpNest, Seller Hub, Top Producer)

- **No property lookup** — they're selling THEIR property, not asking about ours
- **Generic outreach template** via email, signed Andrea
- **Each source has own email format** — need sample emails to build parsers
- **Simple flow:** Parse lead info from email → generic template → approval gate

### Lead Conversation for Residential (Option C Architecture)

Same `lead_conversation` flow, not a separate workflow. Branched by `lead_type`:

- **Module A (classify):** Picks classification prompt based on `lead_type` (commercial buyer vs residential buyer vs residential seller)
- **Module B (generate response):** Picks template/prompt framework based on `lead_type`
- **Everything else shared:** Draft creation, approval gate, CRM notes, post-approval

Seller conversation categories still map to same structure (INTERESTED, WANT_SOMETHING, NOT_INTERESTED, etc.) but the prompt is tuned for seller context ("what's your commission?" vs "send me the OM").

### What's Needed From Jake During Implementation

1. Andrea's template text (Jake has it)
2. Andrea's signoff, phone number, contact details
3. Realtor.com-specific template variation
4. Sample emails from UpNest, Seller Hub, Top Producer for parser design

---

## Phase 4: LoopNet & BizBuySell Testing (Issue 3)

Trigger real test leads from LoopNet and BizBuySell through the full pipeline after Phases 1-2 are complete. Same E2E testing approach as the Crexi testing done earlier today. No code changes expected — just test runs and bug fixing whatever comes up.

---

## Cross-Phase Dependencies & Mitigations

| Risk | Mitigation |
|------|------------|
| Old threads signed by Jake, new replies come from Andrea | In-flight threads keep original signer. Store signer in signal at outreach time; lead_conversation reads signer from signal for thread continuity. |
| Phase 2 prompts reference fact sheet data that barely exists | Option B: prompts gracefully handle missing data ("I'll check on that and get back to you"). Point at online master sheet as interim data source. Gets richer as fact sheets are populated. |
| Phase 2 and Phase 3 both touch template selection branching | Design three-way split (commercial / residential / unknown) from the start in Phase 2, even if residential branch is empty. Phase 3 fills it in. |
| `lead_type` derivation needs `source` to survive webhook → intake → signal → conversation | Verify source field preservation during Phase 1 testing. Currently stored in jake_signals and passed through. |
| Realtor.com fast-path changes the webhook architecture | Design in Phase 3, be aware it touches webhook code that Phase 1 validates. |
| Source classification logic (`is_commercial`) duplicated across multiple files | Centralize into shared Windmill variable or utility. Single source of truth for which sources are commercial, residential buyer, residential seller. |

### Interim Data Source for Property Facts

Until full fact sheets are built, the online master sheet serves as the data source. The master sheet URL and Google Drive file paths for brochures, financials, etc. will be stored in `property_mapping` or as a Windmill variable. Full fact sheet population is a separate project.

---

## Parked Items (Future Sessions)

| Item | Reason |
|------|--------|
| SMS inbound reply detection (Issue 2) | Separate infrastructure project, needs Pixel 9a investigation |
| Homes.com | Unknown classification (buyer/seller), awkward format |
| Residential SMS | No device for Andrea |
| Residential NDA | Not needed unless rental property |
| Property fact sheet population | Full-day project to create sheets for every property |
| Lead magnet property identification | Part of fact sheet project |
