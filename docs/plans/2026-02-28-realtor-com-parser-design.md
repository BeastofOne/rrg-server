# Realtor.com Dedicated Parser

**Date:** 2026-02-28
**Problem:** The generic parser misparses Realtor.com lead notifications — person's name ends up as property address, phone number missed, first/last name mangled across line breaks.

## Root Cause

Realtor.com's email format doesn't match the generic parser's assumptions:

1. **Subject has person's name, not property:** `"New realtor.com lead - Rebecca Sutton"`. The `parse_property_name` regex captures "Rebecca Sutton" as the property.
2. **Name split across two labeled fields:** `First Name: Rebecca` / `Last Name: Sutton`. The generic `parse_name_field` matches `"Name: Rebecca"` then grabs across the `\r\n` into "Last Name" on the next line → `"Rebecca\r\r\nLast Name"`.
3. **Phone uses `Phone Number:` label:** Generic parser only matches `phone:`, `tel:`, `mobile:`, `cell:` — misses `Phone Number:` (space before "Number").
4. **Property address is multi-line in the body**, not in the subject.

## Actual Realtor.com Email Format

Subject: `New realtor.com lead - Rebecca Sutton`

Body (plain text, standard across all Realtor.com leads):
```
First Name: Rebecca
Last Name: Sutton
Email Address: kpfarms@yahoo.com
Phone Number: 517-881-7829

Comment:
I would like to request a private tour of 15 Pinewood Dr, Grass Lake, MI 49240.

This consumer inquired about:

Property Address:
15 Pinewood Dr
Grass Lake, MI 49240
MLSID # 26003866
```

## Design

Create `parse_realtor_com_lead()` in `gmail_pubsub_webhook.py` — a dedicated parser following the same pattern as `parse_crexi_lead`, `parse_social_connect_lead`, and `parse_upnest_lead`.

### Parsing rules

| Field | Label in email | Regex pattern | Notes |
|-------|---------------|---------------|-------|
| first_name | `First Name:` | `First Name:\s*(.+)` | Single line |
| last_name | `Last Name:` | `Last Name:\s*(.+)` | Single line |
| name | Derived | `first_name + " " + last_name` | Combined, stripped |
| email | `Email Address:` | `Email Address:\s*(.+)` | Validate format, check EXCLUDED_EMAIL_ADDRESSES |
| phone | `Phone Number:` | `Phone Number:\s*([\d\-\(\)\+\s\.]+)` | Strip whitespace |
| property_address | `Property Address:` | Multi-line: collect non-empty lines after label until `MLSID` or blank line | Join street + city/state/zip with `, ` |
| property_name | Derived | Same as property_address | |

### Property address parsing detail

`Property Address:` is on its own line. The address spans the next 1-2 non-empty lines:
```
Property Address:
15 Pinewood Dr            ← line 1 (street)
Grass Lake, MI 49240      ← line 2 (city, state zip)
MLSID # 26003866          ← stop here
```

Collect lines after `Property Address:` until hitting a line that starts with `MLSID`, is empty, or is another label. Join with `, `.

### Routing change

In `parse_lead_from_notification()` (line 769), add `realtor_com` to the dedicated parser block:
```python
if category == "realtor_com":
    return parse_realtor_com_lead(service, msg_id, sender, subject)
```

This removes Realtor.com from the generic parsing path entirely. The `realtor_com` branches in `parse_property_name` (line 523-527) and the property_address extraction (lines 809-813) become dead code for Realtor.com — they can be cleaned up.

### Generic parser cleanup

Remove the now-dead `realtor_com` branches from:
- `parse_property_name()` (line 523-527) — realtor_com subject extraction
- `parse_lead_from_notification()` (lines 784-786) — realtor_com source/source_type assignment
- `parse_lead_from_notification()` (lines 809-813) — realtor_com property_address from subject

### Files to modify

1. **`windmill/f/switchboard/gmail_pubsub_webhook.py`**
   - Add `parse_realtor_com_lead()` function (after `parse_upnest_lead`, before `parse_lead_from_notification`)
   - Add routing in `parse_lead_from_notification()`
   - Clean up dead realtor_com branches in generic path
2. **`docs/LEAD_INTAKE_PIPELINE.md`**
   - Update parser table: Realtor.com now uses dedicated parser
   - Update parser architecture description

### No template changes needed

The Realtor.com template in `generate_drafts` (line 292-297) already uses `prop.get("property_address")` and `prop.get("canonical_name")` correctly. With a real address instead of a person's name, it will produce:
- Subject: `"RE: Your Realtor.com inquiry in 15 Pinewood Dr in Grass Lake"` (via `get_city` which now correctly handles 4-part addresses)
- Body: `"I received your Realtor.com inquiry about 15 Pinewood Dr, Grass Lake, MI 49240"`

## Verification

Run the new parser against the actual Rebecca Sutton notification email (msg_id `19ca20243e08730f` in leads@) and confirm:
- name = `"Rebecca Sutton"`
- email = `"kpfarms@yahoo.com"`
- phone = `"517-881-7829"`
- property_address = `"15 Pinewood Dr, Grass Lake, MI 49240"`
- source = `"Realtor.com"`, source_type = `"realtor_com"`
