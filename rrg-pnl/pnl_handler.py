"""P&L handler — extract, compute, format, and modify P&L data conversationally."""

import json
import os
from langchain_core.messages import SystemMessage, HumanMessage
from claude_llm import ChatClaudeCLI


CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "haiku")


def _get_llm() -> ChatClaudeCLI:
    return ChatClaudeCLI(model_name=CLAUDE_MODEL)


EXTRACT_PROMPT = """You are a data extraction assistant. Extract structured financial data from the user's message about a property.

Return ONLY valid JSON in this exact format (no markdown, no code fences):
{{
    "property_name": "short name for the property",
    "property_address": "full address if provided, otherwise empty string",
    "period": "Annual",
    "unit_count": total number of units,
    "occupied_units": number of units with rents described,
    "vacant_units": number of units not accounted for,
    "income": {{
        "Gross Rental Income": number
    }},
    "vacancy_rate": decimal between 0 and 1,
    "vacancy_method": "calculated" or "assumed",
    "expenses": {{
        "Property Taxes": number,
        "Insurance": number,
        "Property Management": number,
        "Repairs & Maintenance": number
    }}
}}

Rules:
- Default period is Annual. If the user gives monthly figures, multiply by 12 to convert to annual.
- VACANCY: If the user describes fewer rented units than the total unit count, calculate vacancy from the actual vacant units (e.g., 15 units but only 14 with rents = 1/15 = 6.67% vacancy, vacancy_method: "calculated"). Only use 5% default if you truly cannot determine vacancy from context.
- Gross Rental Income should reflect ONLY the occupied/rented units (annualized).
- REQUIRED EXPENSE LINES: Always include Property Taxes, Insurance, Property Management, and Repairs & Maintenance in the output, even if the user did not mention them. Set them to 0 if not provided — do NOT omit them.
- UTILITIES: If the user provides a single lump "utilities" number, keep it as one "Utilities" line. If they break out individual categories (electric, water, gas, trash, etc.), list each as a separate expense line and do NOT include a combined "Utilities" summary line. Never output both.
- The user may add custom expense categories (landscaping, snow removal, etc.) — include them in expenses too.
- If a value isn't mentioned, use 0.
- Return ONLY the JSON, nothing else.

{existing_context}"""

CHANGE_PROMPT = """You are a data modification assistant. The user wants to change something about an existing P&L.

Current P&L data:
{current_data}

{conversation_context}The user said: "{user_message}"

Apply their requested change to the data and return the COMPLETE updated JSON in the same format.
Return ONLY the JSON, nothing else (no markdown, no code fences).

Rules:
- Only change what the user asked to change
- Keep all other values the same
- Use the recent conversation to understand ambiguous references (e.g., if they were discussing Repairs & Maintenance and then say "let's use 10%", apply 10% to Repairs & Maintenance, not vacancy)
- If a percentage is meant as a percent of gross income, calculate the dollar amount
- If they want to add a new expense category, add it to expenses
- If they want to remove a category, remove it from expenses
- If they change vacancy rate, convert percentage to decimal (e.g. 8% = 0.08)"""

APPROVAL_CHECK_PROMPT = """Does this message indicate the user approves the P&L and wants to finalize it?
Look for phrases like "looks good", "that's perfect", "send it", "email it", "finalize", "done", "approved", "yes", "good to go".

Message: "{user_message}"

Respond with ONLY "yes" or "no"."""


def extract_pnl_data(user_message: str, existing_data: dict = None) -> dict:
    """Extract structured P&L data from a natural language message."""
    llm = _get_llm()

    existing_context = ""
    if existing_data:
        existing_context = f"Existing P&L data (update with new info):\n{json.dumps(existing_data, indent=2)}"

    prompt = EXTRACT_PROMPT.format(existing_context=existing_context)
    response = llm.invoke([
        SystemMessage(content=prompt),
        HumanMessage(content=user_message),
    ])

    text = response.content.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        text = text.rsplit("```", 1)[0]

    return json.loads(text.strip())


def apply_changes(existing_data: dict, user_message: str, chat_history: list = None) -> dict:
    """Apply user-requested changes to existing P&L data."""
    llm = _get_llm()

    # Build conversation context from recent messages so the LLM can resolve ambiguous references
    conversation_context = ""
    if chat_history:
        recent = chat_history[-6:]  # Last 3 exchanges
        context_lines = []
        for msg in recent:
            role = "User" if msg["role"] == "user" else "Assistant"
            context_lines.append(f"{role}: {msg['content']}")
        conversation_context = "Recent conversation:\n" + "\n".join(context_lines) + "\n\n"

    prompt = CHANGE_PROMPT.format(
        current_data=json.dumps(existing_data, indent=2),
        user_message=user_message,
        conversation_context=conversation_context,
    )
    response = llm.invoke([SystemMessage(content=prompt)])

    text = response.content.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        text = text.rsplit("```", 1)[0]

    return json.loads(text.strip())


def is_approval(user_message: str) -> bool:
    """Check if the user's message indicates they approve the P&L."""
    llm = _get_llm()
    response = llm.invoke([
        SystemMessage(content=APPROVAL_CHECK_PROMPT.format(user_message=user_message)),
    ])
    return response.content.strip().lower().startswith("yes")


def compute_pnl(data: dict) -> dict:
    """Compute calculated P&L fields from raw data."""
    total_income = sum(data.get("income", {}).values())
    vacancy_rate = data.get("vacancy_rate", 0.05)
    vacancy_loss = total_income * vacancy_rate
    effective_gross_income = total_income - vacancy_loss
    total_expenses = sum(data.get("expenses", {}).values())
    net_income = effective_gross_income - total_expenses

    return {
        "total_income": total_income,
        "vacancy_rate": vacancy_rate,
        "vacancy_loss": vacancy_loss,
        "effective_gross_income": effective_gross_income,
        "total_expenses": total_expenses,
        "net_income": net_income,
    }


def format_pnl_table(data: dict) -> str:
    """Format P&L data as a markdown table for display."""
    computed = compute_pnl(data)
    lines = []

    # Header
    name = data.get("property_name", "Property")
    period = data.get("period", "Annual")
    lines.append(f"**{name}** — {period} P&L")
    lines.append("")

    # Income section
    lines.append("| **Income** | |")
    lines.append("|:---|---:|")
    for label, amount in data.get("income", {}).items():
        lines.append(f"| {label} | ${amount:,.2f} |")
    lines.append(f"| **Total Income** | **${computed['total_income']:,.2f}** |")
    lines.append("")

    # Vacancy
    lines.append("| **Less: Vacancy** | |")
    lines.append("|:---|---:|")
    lines.append(f"| Vacancy ({computed['vacancy_rate']:.0%}) | (${computed['vacancy_loss']:,.2f}) |")
    lines.append(f"| **Effective Gross Income** | **${computed['effective_gross_income']:,.2f}** |")
    lines.append("")

    # Expenses section
    lines.append("| **Expenses** | |")
    lines.append("|:---|---:|")
    for label, amount in data.get("expenses", {}).items():
        lines.append(f"| {label} | ${amount:,.2f} |")
    lines.append(f"| **Total Expenses** | **${computed['total_expenses']:,.2f}** |")
    lines.append("")

    # Net Income
    lines.append("| | |")
    lines.append("|:---|---:|")
    lines.append(f"| **Net Income** | **${computed['net_income']:,.2f}** |")

    return "\n".join(lines)
