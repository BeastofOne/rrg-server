# PA Field Groups Design

## Problem

The LLM sees 68 field names as a flat list with no semantic context. It doesn't understand that `purchaser_copy_*` fields are for a **separate contact** (e.g., an attorney for notices), not a duplicate of the purchaser. Result: it copies purchaser data into copy fields incorrectly. It also tries to stuff signer info into copy fields since there's no signer field (signature blocks are filled manually at signing).

The UI has the same problem — remaining variables are a flat list where "Purchaser Copy Name" is ambiguous without context.

## Solution

Organize the 68 fields into named groups with descriptions. Use the groups in two places:

1. **LLM prompts** (`extract_pa_data`, `apply_changes`) — so the LLM knows what each section means and doesn't cross-contaminate
2. **UI display** (`format_remaining_variables`, `format_filled_summary`) — so the user sees remaining fields under readable section headers

## Field Groups

| Group | Description (shown to LLM) | Fields |
|-------|---------------------------|--------|
| Effective Date | Date the agreement takes effect | `effective_date_day`, `effective_date_month`, `effective_date_year` |
| Purchaser | The buying entity | `purchaser_name`, `purchaser_entity_type`, `purchaser_address`, `purchaser_phone`, `purchaser_email`, `purchaser_fax` |
| Purchaser Copy | Separate contact who receives copies of notices (e.g. attorney) — NOT the purchaser | `purchaser_copy_name`, `purchaser_copy_address`, `purchaser_copy_phone`, `purchaser_copy_email` |
| Seller | The selling entity | `seller_name`, `seller_address`, `seller_phone`, `seller_email`, `seller_fax` |
| Seller Copy | Separate contact who receives copies of notices — NOT the seller | `seller_copy_name`, `seller_copy_address`, `seller_copy_phone`, `seller_copy_email` |
| Property | The real property being purchased | `property_location_type`, `property_municipality`, `property_county`, `property_address`, `property_parcel_ids`, `property_legal_description` |
| Financial | Purchase price, payment method, earnest money | `purchase_price_words`, `purchase_price_number`, `payment_cash`, `payment_mortgage`, `payment_land_contract`, `lc_down_payment`, `lc_balance`, `lc_interest_rate`, `lc_amortization_years`, `lc_balloon_months`, `earnest_money_words`, `earnest_money_number` |
| Title & Escrow | Title company and insurance details | `title_company_name`, `title_company_address`, `title_insurance_paid_by`, `title_with_standard_exceptions` |
| Due Diligence | Contingencies and inspection terms | `dd_financing`, `dd_financing_days`, `dd_physical_inspection`, `dd_environmental`, `dd_soil_tests`, `dd_zoning`, `dd_site_plan`, `dd_survey`, `dd_leases_estoppel`, `dd_other`, `dd_other_description`, `dd_governmental`, `inspection_period_days` |
| Closing | Closing timeline | `closing_days`, `closing_days_words` |
| Broker | Broker names and commission | `broker_name`, `broker_commission_pct`, `broker_commission_amount`, `seller_broker_name`, `seller_broker_company` |
| Offer Expiration | When the offer expires | `offer_expiration_time`, `offer_expiration_ampm`, `offer_expiration_month`, `offer_expiration_day`, `offer_expiration_year` |

## LLM Prompt Format

The grouped fields are formatted for the LLM like:

```
EFFECTIVE DATE (date the agreement takes effect):
  effective_date_day, effective_date_month, effective_date_year

PURCHASER (the buying entity):
  purchaser_name, purchaser_entity_type, purchaser_address, purchaser_phone, purchaser_email, purchaser_fax

PURCHASER COPY (separate contact who receives copies of notices, e.g. attorney — NOT the purchaser):
  purchaser_copy_name, purchaser_copy_address, purchaser_copy_phone, purchaser_copy_email

...
```

Plus a rule: "Do NOT duplicate values between groups. Signer information (name, title) goes on the physical signature page and has no variable — ignore it."

## UI Display Format

Remaining variables shown grouped:

```
**Purchaser:**
- Fax

**Purchaser Copy (e.g. attorney for notices):**
- Name
- Address
- Phone
- Email

**Seller:**
- Name
- Address
...
```

The group prefix is stripped from field labels (e.g., `purchaser_copy_name` → "Name" under the Purchaser Copy header). Groups with no missing fields are omitted.

Filled variable summaries use the same grouping.

## Files Changed

- `pa_handler.py` — Replace `ALL_VARIABLE_FIELDS` flat list with `FIELD_GROUPS` structure. Derive `ALL_VARIABLE_FIELDS` from it. Update `format_remaining_variables`, `format_filled_summary`, and prompt-building in `extract_pa_data` and `apply_changes`.
- `graph.py` — No changes needed (it calls the formatting functions which handle grouping internally).

## Out of Scope

- Signer fields (By/Its on signature page) — filled manually at signing, not template variables.
- Changes to the `.docx` template itself.
- Changes to `graph.py` node logic or routing.
