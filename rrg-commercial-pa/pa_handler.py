"""PA Handler — LLM-powered extract/edit/triage logic for purchase agreements.

Provides functions for:
- Extracting PA variables from natural language
- Applying targeted changes to existing variables
- Detecting approval/finalize intent
- Classifying user messages into action types
- Formatting variable status summaries
"""

import json
import os
from typing import Optional

from exhibit_a_helpers import (
    exhibit_a_active, exhibit_a_multi_owner,
    compute_payment_excluded_fields, MIXED_PAYMENT_FIELDS,
)


# ---------------------------------------------------------------------------
# Field groups — each group has (name, description, [fields])
# Description is shown to the LLM so it understands what each section means.
# ---------------------------------------------------------------------------

FIELD_GROUPS = [
    ("Effective Date", "date the agreement takes effect. "
     "effective_date_day must be ordinal (e.g. '10th', '1st', '23rd'). "
     "effective_date_month must be the full month name (e.g. 'March', not '3' or '03')", [
        "effective_date_day", "effective_date_month", "effective_date_year",
    ]),
    ("Purchaser", "the buying entity. "
     "purchaser_entity_type MUST be the full legal form with state, e.g. "
     "'a Michigan limited liability company' or 'a Delaware corporation'. "
     "If the name contains LLC/Inc/Corp but no state is given, set entity_type to 'LLC' or 'Inc' "
     "(the system will ask the user about the state)", [
        "purchaser_name", "purchaser_entity_type", "purchaser_address",
        "purchaser_phone", "purchaser_email", "purchaser_fax",
    ]),
    ("Purchaser Copy", "separate contact who receives copies of notices, e.g. attorney — NOT the purchaser", [
        "purchaser_copy_name", "purchaser_copy_address",
        "purchaser_copy_phone", "purchaser_copy_email",
    ]),
    ("Seller", "the selling entity. "
     "seller_entity_type MUST be the full legal form with state, e.g. "
     "'a Michigan limited liability company' or 'a Delaware corporation'. "
     "If the name contains LLC/Inc/Corp but no state is given, set entity_type to 'LLC' or 'Inc' "
     "(the system will ask the user about the state)", [
        "seller_name", "seller_entity_type", "seller_address",
        "seller_phone", "seller_email", "seller_fax",
    ]),
    ("Seller Copy", "separate contact who receives copies of notices — NOT the seller", [
        "seller_copy_name", "seller_copy_address",
        "seller_copy_phone", "seller_copy_email",
    ]),
    ("Property", "the real property being purchased", [
        "property_location_type", "property_municipality", "property_county",
        "property_address", "property_parcel_ids", "property_legal_description",
    ]),
    ("Financial", "purchase price, payment method, earnest money. "
     "purchase_price_words and purchase_price_number are the SAME value in different formats — "
     "fill BOTH from a single price (words = 'One Million Dollars', number = '$1,000,000.00'). "
     "Number fields MUST include $ sign and .00 cents. "
     "Same for earnest_money_words and earnest_money_number. "
     "mortgage_pct, mortgage_amount_words, mortgage_amount_number, lc_pct, "
     "lc_amount_words, lc_amount_number are ONLY needed when BOTH payment_mortgage "
     "AND payment_land_contract are true — they describe each method's share. "
     "pct = just the number (e.g. '60'), amount_words = English, "
     "amount_number includes $ and .00. "
     "lc_subordinate (bool) = whether the land contract is subordinate to the mortgage", [
        "purchase_price_words", "purchase_price_number",
        "payment_cash", "payment_mortgage", "payment_land_contract",
        "mortgage_pct", "mortgage_amount_words", "mortgage_amount_number",
        "lc_pct", "lc_amount_words", "lc_amount_number",
        "lc_subordinate",
        "lc_down_payment", "lc_balance", "lc_interest_rate",
        "lc_amortization_years", "lc_balloon_months",
        "earnest_money_words", "earnest_money_number",
    ]),
    ("Title & Escrow", "title company and insurance details", [
        "title_company_name", "title_company_address",
        "title_insurance_paid_by", "title_with_standard_exceptions",
    ]),
    ("Due Diligence", "contingencies and inspection terms", [
        "dd_financing", "dd_financing_days",
        "dd_physical_inspection", "dd_environmental", "dd_soil_tests",
        "dd_zoning", "dd_site_plan", "dd_survey", "dd_leases_estoppel",
        "dd_other", "dd_other_description", "dd_governmental",
        "inspection_period_days",
    ]),
    ("Closing", "closing timeline", [
        "closing_days", "closing_days_words",
    ]),
    ("Broker", "broker names and commission. "
     "broker_commission_description is the EXACT commission text as stated by the user "
     "(e.g. '3% of the gross purchase price' or '$25,000'). Do NOT compute or reformat — use their words", [
        "broker_name", "broker_commission_description",
        "seller_broker_name", "seller_broker_company",
    ]),
    ("Offer Expiration", "when the offer expires. "
     "offer_expiration_month must be the full month name (e.g. 'March', not '3' or '03'). "
     "offer_expiration_day should be ordinal (e.g. '20th', '1st')", [
        "offer_expiration_time", "offer_expiration_ampm",
        "offer_expiration_month", "offer_expiration_day", "offer_expiration_year",
    ]),
]

# Flat list derived from groups — single source of truth
ALL_VARIABLE_FIELDS = [f for _, _, fields in FIELD_GROUPS for f in fields]

# Paired fields: when both are missing, display as a single item.
# Maps (words_field, number_field) → display label used in remaining list.
DISPLAY_PAIRS = {
    ("purchase_price_words", "purchase_price_number"): "Purchase Price",
    ("earnest_money_words", "earnest_money_number"): "Earnest Money",
    ("closing_days", "closing_days_words"): "Closing Days",
    ("mortgage_amount_words", "mortgage_amount_number"): "Mortgage Amount",
    ("lc_amount_words", "lc_amount_number"): "Land Contract Amount",
}

# Custom display labels for fields whose auto-generated labels are ambiguous
_DISPLAY_LABELS = {
    "mortgage_pct": "Mortgage Percentage",
    "lc_pct": "Land Contract Percentage",
    "lc_subordinate": "Land Contract Subordinate to Mortgage?",
}

# Fields covered by Exhibit A when active (2+ entities)
EXHIBIT_A_PROPERTY_FIELDS = frozenset({
    "property_address", "property_parcel_ids", "property_legal_description",
    "property_municipality", "property_county", "property_location_type",
})
EXHIBIT_A_SELLER_FIELDS = frozenset({
    "seller_name", "seller_address", "seller_entity_type",
})

# Re-export for backwards compat (used by tests)
_MIXED_PAYMENT_FIELDS = MIXED_PAYMENT_FIELDS




def _format_fields_for_llm() -> str:
    """Format field groups for LLM prompts with descriptions."""
    lines = []
    for name, desc, fields in FIELD_GROUPS:
        lines.append(f"{name.upper()} ({desc}):")
        lines.append(f"  {', '.join(fields)}")
        lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# LLM accessor (mockable in tests)
# ---------------------------------------------------------------------------

def _get_llm():
    """Return a ChatClaudeCLI instance using CLAUDE_MODEL env var."""
    from claude_llm import ChatClaudeCLI
    model = os.getenv("CLAUDE_MODEL", "haiku")
    return ChatClaudeCLI(model_name=model)


# ---------------------------------------------------------------------------
# Helper: strip markdown code fences from LLM responses
# ---------------------------------------------------------------------------

def _strip_fences(text: str) -> str:
    """Extract JSON from LLM output, handling fences and trailing text."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(lines[1:-1]).strip()
    # Extract just the JSON object — LLM sometimes appends explanations
    start = text.find("{")
    if start == -1:
        return text
    depth = 0
    for i, ch in enumerate(text[start:], start):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    return text[start:]


# ---------------------------------------------------------------------------
# extract_pa_data
# ---------------------------------------------------------------------------

def extract_pa_data(user_message: str, existing_data: Optional[dict] = None) -> dict:
    """Extract PA variables from natural language using the LLM.

    Args:
        user_message: Free-text description of deal terms.
        existing_data: Optional dict of already-known variables for context.

    Returns:
        Dict of extracted PA variable names to values.

    Raises:
        json.JSONDecodeError or ValueError: If LLM returns invalid JSON.
    """
    grouped_fields = _format_fields_for_llm()

    prompt = (
        "You are a commercial real estate purchase agreement assistant. "
        "Extract any purchase agreement variables from the user's message.\n\n"
        f"Variable fields by section:\n{grouped_fields}\n"
        "IMPORTANT: Do NOT duplicate values between sections. "
        "Purchaser Copy and Seller Copy are for SEPARATE contacts (e.g. attorneys), "
        "not copies of the purchaser/seller info. "
        "Signer information (who signs the document) has no variable — ignore it.\n\n"
        "Also extract 'exhibit_a_entities' (list of entity dicts with keys: "
        "owner, address, municipality, county, parcel_ids, legal_description) "
        "and 'additional_provisions' (list of dicts with title and body) if mentioned.\n"
        "Create one entity per parcel. If a property has multiple parcels "
        "(e.g. building + parking lot on separate parcels), create separate entities "
        "with the same address. If the same LLC owns multiple properties, "
        "repeat the LLC name in each entity. When exhibit_a_entities has 2+ entries, "
        "do NOT set scalar property fields (property_address, property_parcel_ids, etc). "
        "When multiple distinct LLC names exist, do NOT set scalar seller fields "
        "(seller_name, seller_address, seller_entity_type).\n\n"
    )

    if existing_data:
        context_lines = []
        for k, v in existing_data.items():
            if v is None or v == "" or v == []:
                continue
            if k in ("exhibit_a_entities", "additional_provisions"):
                continue
            val_str = str(v)
            if len(val_str) > 100:
                val_str = val_str[:100] + "..."
            context_lines.append(f"{k}={val_str}")
        context_block = "\n".join(context_lines)
        # Hard cap to stay within prompt size budget (~1500 chars)
        if len(context_block) > 1500:
            context_block = context_block[:1500].rsplit("\n", 1)[0]
        prompt += f"Already known data:\n{context_block}\n\n"

    from datetime import date
    today = date.today()
    prompt += f"Today's date is {today.strftime('%A, %B %d, %Y')}.\n\n"

    if "[Context: assistant just asked:" in user_message:
        prompt += (
            "The user message includes the prior assistant question for context. "
            "Extract variables ONLY from the user's reply, using the assistant "
            "question only to understand which field is being answered.\n\n"
        )

    prompt += (
        f"User message: {user_message}\n\n"
        "Return ONLY a JSON object with the extracted variables. "
        "Use ONLY the exact field names listed above (snake_case). "
        "Only include variables that are clearly mentioned or implied. "
        "Do not include variables you cannot determine from the message."
    )

    from langchain_core.messages import HumanMessage

    llm = _get_llm()
    msg = HumanMessage(content=prompt)
    response = llm.invoke([msg])
    text = _strip_fences(response.content)

    return json.loads(text)


# ---------------------------------------------------------------------------
# apply_changes
# ---------------------------------------------------------------------------

def apply_changes(
    existing_data: dict,
    user_message: str,
    chat_history: Optional[list] = None,
) -> dict:
    """Apply targeted changes to existing PA variables using the LLM.

    Args:
        existing_data: Current variable values.
        user_message: User instruction describing changes.
        chat_history: Optional conversation history for context.

    Returns:
        Complete updated dict (existing merged with changes).

    Raises:
        json.JSONDecodeError or ValueError: If LLM returns invalid JSON.
    """
    grouped_fields = _format_fields_for_llm()

    prompt = (
        "You are a commercial real estate purchase agreement assistant. "
        "The user wants to modify existing purchase agreement variables.\n\n"
        f"Variable fields by section:\n{grouped_fields}\n"
        "IMPORTANT: Do NOT duplicate values between sections. "
        "Purchaser Copy and Seller Copy are for SEPARATE contacts (e.g. attorneys), "
        "not copies of the purchaser/seller info. "
        "Signer information (who signs the document) has no variable — ignore it.\n\n"
        "The 'exhibit_a_entities' field is a list of entity dicts with keys: "
        "owner, address, municipality, county, parcel_ids, legal_description. "
        "Create one entity per parcel. If adding/removing/editing entities, "
        "return the complete updated list. When exhibit_a_entities has 2+ entries, "
        "do NOT set scalar property fields. When multiple distinct LLC names, "
        "do NOT set scalar seller fields. If user switches from multiple to single "
        "property, clear exhibit_a_entities (set to []) and use scalar fields.\n\n"
        f"Current variables: {json.dumps(existing_data)}\n\n"
    )

    if chat_history:
        history_text = "\n".join(
            f"{entry['role']}: {entry['content']}" for entry in chat_history
        )
        prompt += f"Conversation history:\n{history_text}\n\n"

    prompt += (
        f"User instruction: {user_message}\n\n"
        "ENTITY TYPE RESOLUTION: If the user confirms a state of incorporation "
        "(e.g. 'yes' meaning Michigan, or 'Utah', or 'it's a Delaware LLC'), "
        "update the relevant entity_type to the full form: "
        "'a {State} limited liability company' for LLC, "
        "'a {State} corporation' for Inc/Corp. "
        "Check chat history for which entity was being asked about.\n\n"
        "Return ONLY a JSON object with the variables that are NEW or CHANGED. "
        "Do NOT include unchanged variables. "
        "Use ONLY the exact field names listed above (snake_case). "
        "If the user provides exhibit_a_entities changes, return the complete "
        "updated list (since it replaces the old list entirely)."
    )

    from langchain_core.messages import HumanMessage

    llm = _get_llm()
    msg = HumanMessage(content=prompt)
    response = llm.invoke([msg])
    text = _strip_fences(response.content)

    updated = json.loads(text)

    # Merge: ensure existing fields are preserved even if LLM omits them
    result = dict(existing_data)
    result.update(updated)
    return result


# ---------------------------------------------------------------------------
# is_approval
# ---------------------------------------------------------------------------

def is_approval(user_message: str) -> bool:
    """Check if a user message indicates approval/finalize intent.

    Args:
        user_message: The user's message.

    Returns:
        True if the message means approve/finalize, False otherwise.
    """
    prompt = (
        "Does the following message indicate that the user wants to approve, "
        "finalize, or confirm a document? Answer with exactly 'yes' or 'no'.\n\n"
        f"Message: {user_message}"
    )

    from langchain_core.messages import HumanMessage

    llm = _get_llm()
    msg = HumanMessage(content=prompt)
    response = llm.invoke([msg])
    answer = response.content.strip().lower()

    return answer == "yes"


# ---------------------------------------------------------------------------
# classify_action
# ---------------------------------------------------------------------------

VALID_ACTIONS = {"edit", "preview", "finalize", "save", "list_drafts", "question", "cancel"}


def classify_action(user_message: str) -> str:
    """Classify a user message into an action type.

    Args:
        user_message: The user's message.

    Returns:
        One of: edit, preview, finalize, save, list_drafts, question, cancel.
        Defaults to "edit" for unrecognized responses.
    """
    prompt = (
        "You are classifying a user message in a purchase agreement workflow. "
        "The user has an active draft and is providing input.\n\n"
        "Action types:\n"
        "- edit: User is providing deal information (names, addresses, dates, prices, "
        "terms, phone numbers, emails, entity types, etc.) or asking to change/update values\n"
        "- preview: User wants to see or download a preview of the document\n"
        "- finalize: User wants to finalize, approve, or complete the agreement\n"
        "- save: User wants to save progress and come back later\n"
        "- list_drafts: User wants to see their saved drafts\n"
        "- question: User is asking a general question NOT related to filling in deal terms\n"
        "- cancel: User wants to cancel or delete the draft\n\n"
        "IMPORTANT: If the message contains ANY deal information (names, addresses, dates, "
        "prices, phone numbers, emails, entity names, terms), classify as 'edit'.\n\n"
        f"Message: {user_message}\n\n"
        "Reply with ONLY the action type, nothing else."
    )

    from langchain_core.messages import HumanMessage

    llm = _get_llm()
    msg = HumanMessage(content=prompt)
    response = llm.invoke([msg])
    action = response.content.strip().lower()

    if action not in VALID_ACTIONS:
        return "edit"

    return action


# ---------------------------------------------------------------------------
# format_remaining_variables (pure — no LLM)
# ---------------------------------------------------------------------------

def _strip_group_prefix(field: str, group_name: str) -> str:
    """Strip the group prefix from a field name for display.

    E.g., 'purchaser_copy_name' under group 'Purchaser Copy' → 'Name'.
    """
    prefix = group_name.lower().replace(" & ", "_").replace(" ", "_") + "_"
    if field.startswith(prefix):
        short = field[len(prefix):]
    elif field.startswith("dd_"):
        short = field[3:]
    elif field.startswith("lc_"):
        short = field[3:]
    else:
        short = field
    return short.replace("_", " ").title()


def format_remaining_variables(variables: dict) -> str:
    """Generate a grouped checklist of PA variables that are still missing.

    Args:
        variables: Dict of currently filled variable names to values.

    Returns:
        Formatted string listing missing variables grouped by section.
        Empty string if all are filled.
    """
    # Determine which fields are covered by Exhibit A
    entities = variables.get("exhibit_a_entities", [])
    skip_fields = set()
    if exhibit_a_active(entities):
        skip_fields |= EXHIBIT_A_PROPERTY_FIELDS
        if exhibit_a_multi_owner(entities):
            skip_fields |= EXHIBIT_A_SELLER_FIELDS

    # Hide payment-related fields based on selected methods
    skip_fields |= compute_payment_excluded_fields(variables)

    # Build set of paired fields for collapsing
    paired_fields = {}  # field → (partner_field, display_label)
    for (f1, f2), label in DISPLAY_PAIRS.items():
        paired_fields[f1] = (f2, label)
        paired_fields[f2] = (f1, label)

    sections = []
    for group_name, group_desc, fields in FIELD_GROUPS:
        missing = [f for f in fields if f not in skip_fields and not variables.get(f)]
        if not missing:
            continue
        # Short description for copy groups to help the user
        if "copy" in group_name.lower():
            header = f"**{group_name}** (e.g. attorney for notices):"
        else:
            header = f"**{group_name}:**"
        lines = [header]
        already_shown = set()
        for field in missing:
            if field in already_shown:
                continue
            if field in paired_fields:
                partner, pair_label = paired_fields[field]
                if partner in missing:
                    # Both missing — show as single item
                    lines.append(f"- {pair_label}")
                    already_shown.add(partner)
                    continue
            label = _DISPLAY_LABELS.get(field) or _strip_group_prefix(field, group_name)
            lines.append(f"- {label}")
        sections.append("\n".join(lines))

    return "\n\n".join(sections)


# ---------------------------------------------------------------------------
# format_filled_summary (pure — no LLM)
# ---------------------------------------------------------------------------

def format_filled_summary(extracted: dict) -> str:
    """Format newly extracted variables as a grouped confirmation summary.

    Args:
        extracted: Dict of variable names to their extracted values.

    Returns:
        Formatted string summarizing what was extracted. Skips None/empty values.
    """
    if not extracted:
        return ""

    # Build a set of filled keys for quick lookup
    filled = {k for k, v in extracted.items() if v}
    if not filled:
        return ""

    sections = []
    for group_name, _, fields in FIELD_GROUPS:
        group_filled = [f for f in fields if f in filled]
        if not group_filled:
            continue
        lines = [f"**{group_name}:**"]
        for field in group_filled:
            label = _strip_group_prefix(field, group_name)
            lines.append(f"- **{label}:** {extracted[field]}")
        sections.append("\n".join(lines))

    # Handle any keys not in FIELD_GROUPS (e.g. exhibit_a_entities)
    known_fields = set(ALL_VARIABLE_FIELDS)
    extras = [k for k in filled if k not in known_fields]
    if extras:
        lines = ["**Other:**"]
        for key in extras:
            lines.append(f"- **{key.replace('_', ' ').title()}:** {extracted[key]}")
        sections.append("\n".join(lines))

    return "\n\n".join(sections)


# ---------------------------------------------------------------------------
# format_exhibit_a_summary (pure — no LLM)
# ---------------------------------------------------------------------------

def format_exhibit_a_summary(variables: dict) -> str:
    """Format Exhibit A entity data for display in conversation.

    Returns empty string if Exhibit A is not active.
    """
    entities = variables.get("exhibit_a_entities", [])
    if not exhibit_a_active(entities):
        return ""
    lines = [f"**Exhibit A** ({len(entities)} entities):"]
    for i, entity in enumerate(entities, 1):
        if not isinstance(entity, dict):
            continue
        name = entity.get("owner") or entity.get("name", "Unknown")
        addr = entity.get("address", "")
        municipality = entity.get("municipality", "")
        county = entity.get("county", "")
        parcel = entity.get("parcel_ids", "")
        legal = entity.get("legal_description", entity.get("legal_descriptions", ""))
        parts = [f"  {i}. **{name}**"]
        if addr:
            parts.append(f"     Address: {addr}")
        if municipality or county:
            loc_parts = []
            if municipality:
                loc_parts.append(municipality)
            if county:
                loc_parts.append(f"{county} County")
            parts.append(f"     Location: {', '.join(loc_parts)}")
        if parcel:
            parts.append(f"     Parcels: {parcel}")
        if legal:
            parts.append(f"     Legal: {legal}")
        lines.append("\n".join(parts))

    return "\n".join(lines)
