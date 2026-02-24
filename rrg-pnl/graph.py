"""Self-contained P&L LangGraph for the rrg-pnl microservice.

7 nodes: extract, nudge, triage, edit, approve, question, cancel.
Entry point is `build_graph()` which returns a compiled LangGraph.
"""

import json
import re
import base64
import os
from datetime import date
from typing import TypedDict, Optional

from langgraph.graph import StateGraph, END

from langchain_core.messages import SystemMessage, HumanMessage

from claude_llm import ChatClaudeCLI
from pnl_handler import (
    extract_pnl_data,
    apply_changes,
    is_approval,
    compute_pnl,
    format_pnl_table,
)
from pnl_pdf import generate_pnl_pdf


CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "haiku")


def _get_llm() -> ChatClaudeCLI:
    return ChatClaudeCLI(model_name=CLAUDE_MODEL)


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

class PnlState(TypedDict):
    """State for the P&L workflow."""
    command: str               # "create" | "continue"
    user_message: str
    chat_history: list         # list of {"role": ..., "content": ...}
    pnl_data: Optional[dict]   # current P&L data (from previous state)

    # Outputs (set by nodes)
    response: str
    pnl_data_out: Optional[dict]
    pnl_active_out: bool
    pdf_bytes: Optional[bytes]
    pdf_filename: Optional[str]
    pnl_action: Optional[str]  # triage result: edit/approve/cancel/question


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

PNL_ONBOARDING = (
    "I'll need some numbers to build your P&L. "
    "What can you tell me? For example:\n\n"
    "- **Rental income** (e.g., $5,000/mo or per-unit rents)\n"
    "- **Vacancy rate** (e.g., 5%)\n"
    "- **Expenses** (taxes, insurance, management, utilities, etc.)\n\n"
    "Include an address if you have one. You can give me everything at once "
    "or we can build it up piece by piece."
)

PNL_TRIAGE_PROMPT = """You are triaging a user message during an active P&L (profit and loss) workflow.
The user already has a P&L draft in progress. Classify their message into ONE of these categories:

- "edit" — They want to change/add/remove something in the P&L (e.g., "change vacancy to 8%", "add landscaping at $1200/yr", "remove insurance")
- "question" — They are asking a general question, seeking advice, or asking for information (e.g., "what is a good rule of thumb for repairs?", "how much should I budget for maintenance?", "what does cap rate mean?")

Respond with ONLY one word: edit or question"""


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _message_has_numbers(msg: str) -> bool:
    """Quick check if message contains any dollar amounts or percentages."""
    return bool(re.search(r'[\$\d][\d,]*\.?\d*|[\d]+\s*%', msg))


# ---------------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------------

def entry_node(state: PnlState) -> dict:
    """Route to the correct starting point based on command."""
    # This node just passes through — routing is done by conditional edges
    return {}


def pnl_extract_node(state: PnlState) -> dict:
    """Extract P&L data from the user's initial request."""
    if not _message_has_numbers(state["user_message"]):
        return {
            "response": PNL_ONBOARDING,
            "pnl_data_out": None,
            "pnl_active_out": True,
            "pdf_bytes": None,
            "pdf_filename": None,
        }

    try:
        data = extract_pnl_data(state["user_message"])
        data["date_generated"] = date.today().isoformat()

        has_income = any(v > 0 for v in data.get("income", {}).values())
        if not has_income:
            return {
                "response": (
                    "I'd love to help you create a P&L! Tell me about the property — "
                    "what's the address, monthly rent, vacancy rate, and any expenses "
                    "like taxes, insurance, management fees, etc.?"
                ),
                "pnl_data_out": None,
                "pnl_active_out": True,
                "pdf_bytes": None,
                "pdf_filename": None,
            }

        table = format_pnl_table(data)
        return {
            "response": (
                f"Here's your P&L:\n\n{table}\n\n"
                "Want to make any changes? Or say **looks good** to finalize and get a PDF."
            ),
            "pnl_data_out": data,
            "pnl_active_out": True,
            "pdf_bytes": None,
            "pdf_filename": None,
        }
    except (json.JSONDecodeError, Exception):
        return {
            "response": (
                "I couldn't quite parse those numbers. Could you try again? "
                'For example: "Create a P&L for 123 Main St, rent $5000/mo, '
                'vacancy 5%, taxes $5000/yr, insurance $2400/yr"'
            ),
            "pnl_data_out": None,
            "pnl_active_out": True,
            "pdf_bytes": None,
            "pdf_filename": None,
        }


def pnl_nudge_node(state: PnlState) -> dict:
    """User is in P&L mode but sent a message without financial data."""
    msg = state["user_message"].lower().strip()
    if msg in ("cancel", "nevermind", "never mind", "stop", "quit"):
        return {
            "response": "No problem — P&L cancelled.",
            "pnl_data_out": None,
            "pnl_active_out": False,
            "pdf_bytes": None,
            "pdf_filename": None,
        }
    llm = _get_llm()
    result = llm.invoke([
        SystemMessage(content=(
            "You are a personal assistant helping the user build a P&L (profit and loss) statement. "
            "They've started the P&L workflow but their latest message doesn't contain financial data. "
            "Respond naturally to what they said, then gently steer back to getting the numbers. "
            "Keep it to 1-2 sentences. No emojis. No lists. "
            "They can also say 'cancel' if they changed their mind."
        )),
        HumanMessage(content=state["user_message"]),
    ])
    return {
        "response": result.content,
        "pnl_data_out": None,
        "pnl_active_out": True,
        "pdf_bytes": None,
        "pdf_filename": None,
    }


def pnl_triage_node(state: PnlState) -> dict:
    """Determine what the user wants to do with their existing P&L."""
    msg = state["user_message"].lower().strip()
    if msg in ("cancel", "nevermind", "never mind", "stop", "quit"):
        return {"pnl_action": "cancel"}
    if is_approval(state["user_message"]):
        return {"pnl_action": "approve"}

    # Use LLM to distinguish questions from edit requests
    llm = _get_llm()
    response = llm.invoke([
        SystemMessage(content=PNL_TRIAGE_PROMPT),
        HumanMessage(content=state["user_message"]),
    ])
    action = response.content.strip().lower()
    if action in ("question", "edit"):
        return {"pnl_action": action}
    return {"pnl_action": "edit"}


def pnl_edit_node(state: PnlState) -> dict:
    """Apply user-requested changes to the existing P&L."""
    try:
        updated = apply_changes(state["pnl_data"], state["user_message"], state.get("chat_history"))
        updated["date_generated"] = date.today().isoformat()
        table = format_pnl_table(updated)
        return {
            "response": (
                f"Updated:\n\n{table}\n\n"
                "Anything else to change? Or say **looks good** to finalize."
            ),
            "pnl_data_out": updated,
            "pdf_bytes": None,
            "pdf_filename": None,
        }
    except (json.JSONDecodeError, Exception):
        return {
            "response": (
                "I couldn't apply that change. Could you rephrase? "
                'For example: "Change vacancy to 8%" or "Add landscaping at $1200/yr"'
            ),
            "pnl_data_out": state.get("pnl_data"),
            "pdf_bytes": None,
            "pdf_filename": None,
        }


def pnl_approve_node(state: PnlState) -> dict:
    """Generate the finalized PDF."""
    pnl_data = state["pnl_data"]
    pdf_bytes = generate_pnl_pdf(pnl_data)

    # Build filename: YYYYMMDD_Profit and Loss_Address.pdf
    today = date.today().strftime("%Y%m%d")
    address = pnl_data.get("property_address", "").strip()
    if not address:
        address = pnl_data.get("property_name", "Property")
    parts = [p.strip() for p in address.split(",")]
    short_address = " ".join(parts[:2]) if len(parts) >= 2 else parts[0]
    pdf_filename = f"{today}_Profit and Loss_{short_address}.pdf"

    return {
        "response": "P&L finalized! Generating your PDF now...",
        "pnl_data_out": None,
        "pnl_active_out": False,
        "pdf_bytes": pdf_bytes,
        "pdf_filename": pdf_filename,
    }


def pnl_question_node(state: PnlState) -> dict:
    """Answer a general question mid-workflow, preserving the active P&L."""
    llm = _get_llm()
    pnl_context = json.dumps(state.get("pnl_data", {}), indent=2)
    response = llm.invoke([
        SystemMessage(content=(
            "You are a helpful real estate assistant. The user is in the middle of building "
            "a P&L (profit and loss statement) and has asked a general question. "
            "Answer their question concisely. If it relates to the P&L they're working on, "
            "you can reference the current data.\n\n"
            f"Current P&L data:\n{pnl_context}\n\n"
            "After answering, remind them they can continue editing their P&L or say "
            "'looks good' to finalize."
        )),
        HumanMessage(content=state["user_message"]),
    ])
    return {
        "response": response.content,
        "pnl_data_out": state.get("pnl_data"),
        "pdf_bytes": None,
        "pdf_filename": None,
    }


def pnl_cancel_node(state: PnlState) -> dict:
    """Cancel the P&L workflow."""
    return {
        "response": "No problem — P&L cancelled.",
        "pnl_data_out": None,
        "pnl_active_out": False,
        "pdf_bytes": None,
        "pdf_filename": None,
    }


# ---------------------------------------------------------------------------
# Routing functions
# ---------------------------------------------------------------------------

def route_entry(state: PnlState) -> str:
    """Route from entry: create goes to extract, continue goes to triage or nudge."""
    if state.get("command") == "create":
        return "extract"

    # "continue" — user has an active P&L
    if state.get("pnl_data"):
        return "triage"

    # No existing data yet (still collecting) — check if message has numbers
    if _message_has_numbers(state.get("user_message", "")):
        return "extract"
    return "nudge"


def route_triage(state: PnlState) -> str:
    """Route based on triage result."""
    action = state.get("pnl_action", "edit")
    if action == "approve":
        return "approve"
    elif action == "cancel":
        return "cancel"
    elif action == "question":
        return "question"
    return "edit"


# ---------------------------------------------------------------------------
# Build graph
# ---------------------------------------------------------------------------

def build_graph() -> StateGraph:
    """Build and compile the P&L LangGraph."""
    graph = StateGraph(PnlState)

    # Add nodes
    graph.add_node("entry", entry_node)
    graph.add_node("extract", pnl_extract_node)
    graph.add_node("nudge", pnl_nudge_node)
    graph.add_node("triage", pnl_triage_node)
    graph.add_node("edit", pnl_edit_node)
    graph.add_node("approve", pnl_approve_node)
    graph.add_node("question", pnl_question_node)
    graph.add_node("cancel", pnl_cancel_node)

    # Entry point
    graph.set_entry_point("entry")

    # Conditional edges from entry
    graph.add_conditional_edges("entry", route_entry, {
        "extract": "extract",
        "triage": "triage",
        "nudge": "nudge",
    })

    # Conditional edges from triage
    graph.add_conditional_edges("triage", route_triage, {
        "edit": "edit",
        "approve": "approve",
        "question": "question",
        "cancel": "cancel",
    })

    # Terminal nodes — all go to END
    graph.add_edge("extract", END)
    graph.add_edge("nudge", END)
    graph.add_edge("edit", END)
    graph.add_edge("approve", END)
    graph.add_edge("question", END)
    graph.add_edge("cancel", END)

    return graph.compile()
