# Realtor.com Dedicated Parser

**Date:** 2026-02-28
**Problem:** The generic parser misparses Realtor.com lead notifications — person's name ends up as property address, phone number missed, first/last name mangled across line breaks.

## Root Cause

Realtor.com's email format doesn't match the generic parser's assumptions:
- Subject contains lead name, not property: `"New realtor.com lead - Rebecca Sutton"`
- Name split across two fields: `First Name: Rebecca` / `Last Name: Sutton`
- Phone labeled `Phone Number:` (not `Phone:`)
- Property address on separate lines after `Property Address:` label

## Design

Create `parse_realtor_com_lead()` in `gmail_pubsub_webhook.py` — a dedicated parser like Crexi, Social Connect, and UpNest already have.

### Parsing rules

| Field | Source | Pattern |
|-------|--------|---------|
| name | Body | `First Name:` + `Last Name:` combined |
| email | Body | `Email Address:` value |
| phone | Body | `Phone Number:` value |
| property_address | Body | Lines after `Property Address:` label (multi-line: street on one line, city/state/zip on next) |
| property_name | Derived | Same as property_address |

### Routing change

In `parse_lead_from_notification()`, add `realtor_com` to the dedicated parser block (alongside crexi, social_connect, upnest). Remove it from the generic path.

### Files to modify

1. `windmill/f/switchboard/gmail_pubsub_webhook.py` — Add `parse_realtor_com_lead()`, route to it
2. `docs/LEAD_INTAKE_PIPELINE.md` — Update parser table description for Realtor.com

### No template changes needed

The template in `generate_drafts` already uses `prop.get("property_address")` correctly — it just needs a real address instead of a person's name.

## Verification

Run the parser against the actual Rebecca Sutton notification email (msg_id `19ca20243e08730f` in leads@) and confirm:
- name = "Rebecca Sutton"
- email = "kpfarms@yahoo.com"
- phone = "517-881-7829"
- property_address = "15 Pinewood Dr, Grass Lake, MI 49240"
