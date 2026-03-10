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


# ---------------------------------------------------------------------------
# All PA variable field names (canonical list from design doc schema)
# ---------------------------------------------------------------------------

ALL_VARIABLE_FIELDS = [
    # Party — Purchaser
    "effective_date_day", "effective_date_month", "effective_date_year",
    "purchaser_name", "purchaser_entity_type", "purchaser_address",
    "purchaser_phone", "purchaser_email", "purchaser_fax",
    "purchaser_copy_name", "purchaser_copy_address",
    "purchaser_copy_phone", "purchaser_copy_email",
    # Party — Seller
    "seller_name", "seller_address", "seller_phone", "seller_email",
    "seller_fax", "seller_copy_name", "seller_copy_address",
    "seller_copy_phone", "seller_copy_email",
    # Property
    "property_location_type", "property_municipality", "property_county",
    "property_address", "property_parcel_ids", "property_legal_description",
    # Financial
    "purchase_price_words", "purchase_price_number",
    "payment_cash", "payment_mortgage", "payment_land_contract",
    "lc_down_payment", "lc_balance", "lc_interest_rate",
    "lc_amortization_years", "lc_balloon_months",
    "earnest_money_words", "earnest_money_number",
    # Title & Escrow
    "title_company_name", "title_company_address",
    "title_insurance_paid_by", "title_with_standard_exceptions",
    # Due Diligence
    "dd_financing", "dd_financing_days",
    "dd_physical_inspection", "dd_environmental", "dd_soil_tests",
    "dd_zoning", "dd_site_plan", "dd_survey", "dd_leases_estoppel",
    "dd_other", "dd_other_description", "dd_governmental",
    "inspection_period_days",
    # Closing
    "closing_days", "closing_days_words",
    # Broker
    "broker_name", "broker_commission_pct", "broker_commission_amount",
    "seller_broker_name", "seller_broker_company",
    # Offer Expiration
    "offer_expiration_time", "offer_expiration_ampm",
    "offer_expiration_day", "offer_expiration_year",
]


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
    """Remove markdown code fences (```json ... ```) from LLM output."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        # Remove first line (```json or ```) and last line (```)
        text = "\n".join(lines[1:-1]).strip()
    return text


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
    fields_list = ", ".join(ALL_VARIABLE_FIELDS)

    prompt = (
        "You are a commercial real estate purchase agreement assistant. "
        "Extract any purchase agreement variables from the user's message.\n\n"
        f"Known variable fields: {fields_list}\n\n"
        "Also extract 'exhibit_a_entities' (list of entity dicts with name, address, "
        "parcel_ids, legal_descriptions) and 'additional_provisions' (list of dicts "
        "with title and body) if mentioned.\n\n"
    )

    if existing_data:
        prompt += f"Already known data: {json.dumps(existing_data)}\n\n"

    prompt += (
        f"User message: {user_message}\n\n"
        "Return ONLY a JSON object with the extracted variables. "
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
    fields_list = ", ".join(ALL_VARIABLE_FIELDS)

    prompt = (
        "You are a commercial real estate purchase agreement assistant. "
        "The user wants to modify existing purchase agreement variables.\n\n"
        f"Valid variable field names: {fields_list}\n\n"
        f"Current variables: {json.dumps(existing_data)}\n\n"
    )

    if chat_history:
        history_text = "\n".join(
            f"{entry['role']}: {entry['content']}" for entry in chat_history
        )
        prompt += f"Conversation history:\n{history_text}\n\n"

    prompt += (
        f"User instruction: {user_message}\n\n"
        "Return ONLY a complete JSON object with ALL variables — "
        "the unchanged ones plus any modified ones. "
        "Use ONLY the exact field names listed above (snake_case). "
        "Preserve all existing values that were not changed."
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

def format_remaining_variables(variables: dict) -> str:
    """Generate a checklist of PA variables that are still missing/unfilled.

    Args:
        variables: Dict of currently filled variable names to values.

    Returns:
        Formatted string listing missing variables. Empty string or
        completion message if all are filled.
    """
    missing = []
    for field in ALL_VARIABLE_FIELDS:
        if field not in variables or variables[field] is None:
            missing.append(field)

    if not missing:
        return ""

    lines = []
    for field in missing:
        label = field.replace("_", " ").title()
        lines.append(f"- {label}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# format_filled_summary (pure — no LLM)
# ---------------------------------------------------------------------------

def format_filled_summary(extracted: dict) -> str:
    """Format newly extracted variables as a confirmation summary.

    Args:
        extracted: Dict of variable names to their extracted values.

    Returns:
        Formatted string summarizing what was extracted. Skips None values.
    """
    if not extracted:
        return ""

    lines = []
    for key, value in extracted.items():
        if value is None:
            continue
        label = key.replace("_", " ").title()
        lines.append(f"  {label}: {value}")

    if not lines:
        return ""

    header = "Extracted variables:\n"
    return header + "\n".join(lines)
