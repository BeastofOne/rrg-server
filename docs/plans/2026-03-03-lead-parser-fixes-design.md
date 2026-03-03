# Lead Parser Fixes Design

Date: 2026-03-03

## Problem

Three parsing issues found during review of 8 property drafts in teamgotcher@gmail.com:

1. **BizBuySell name bleed** — `parse_name_field()` regex uses `\s+` between word captures, matching across newlines. Result: `"Jon C\r\n \n\r\n \r\n Contact Email"` instead of `"Jon C"`.

2. **COMMON_FIRST_NAMES list incomplete** — `get_first_name()` validates against a hand-typed 500-name whitelist. "Cassandra" is missing, causing "Hey there" instead of "Hey Cassandra". The list will always have gaps.

3. **Crexi emoji + title prefix** — Subject `"✅ Principal Mario Aljarbo opened flyer on..."` fails the `re.match(r"([A-Z]...")` regex because the string starts with a unicode emoji, and "Principal" is a title word that shouldn't be part of the name.

## Fixes

### Fix 1: BizBuySell regex line bleed

**File:** `windmill/f/switchboard/gmail_pubsub_webhook.py`, `parse_name_field()` (lines 467, 474)

**Change:** Replace `\s+` with `[ \t]+` in the word-separator groups of both regex patterns. This prevents matching across newlines while still matching spaces and tabs within a single line.

- Line 467: `(?:\s+[A-Z][a-zA-Z\'\-]+)` → `(?:[ \t]+[A-Z][a-zA-Z\'\-]+)`
- Line 474: `(?:\s+[a-zA-Z\'\-]+)` → `(?:[ \t]+[a-zA-Z\'\-]+)`

### Fix 2: Replace COMMON_FIRST_NAMES with SSA dataset

**Files:**
- New: `windmill/f/switchboard/data/ssa_first_names.py` (generated set)
- Modified: `windmill/f/switchboard/lead_intake.flow/generate_drafts_+_gmail.inline_script.py`

**Change:**
1. Download SSA baby names data (national, 1880-present) from ssa.gov
2. Filter to names with 100+ occurrences in any year since 1960
3. Generate a Python set (~10-20K names) and save as a module
4. Replace the inline `COMMON_FIRST_NAMES` set with an import from the new module
5. `get_first_name()` logic stays the same — just swap the data source

### Fix 3: Crexi emoji + title prefix

**File:** `windmill/f/switchboard/gmail_pubsub_webhook.py`, `parse_crexi_lead()` (lines 553-560)

**Change:** Add a preprocessing step before the existing `re.match`:
1. Strip leading non-ASCII characters (emojis, checkmarks)
2. Strip known Crexi title/role prefixes: Principal, Agent, Broker, Associate, Director, Manager, VP, CEO, CFO, President, Owner

The existing regex stays unchanged — we just clean the subject string before it runs.

## Out of Scope

- **Chris Scheer dedup across sources** — Same person, different emails (Crexi vs LoopNet). Dedup by email won't catch this. Not fixing now.
- **Unmapped properties** — Hartwick Pines MHP and Dairy Queen not in property_mapping. Not a bug, just missing inventory data.
