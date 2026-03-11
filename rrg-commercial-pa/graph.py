"""LangGraph workflow for commercial purchase agreement generation.

11 nodes: entry, start_new, triage, extract, edit, preview, finalize,
save, list_drafts, question, cancel.

Entry point is `build_graph()` which returns a compiled LangGraph.
"""

import json
import logging
import os
import re
from typing import Optional

logger = logging.getLogger(__name__)

from typing_extensions import TypedDict
from langgraph.graph import StateGraph, END
from langchain_core.messages import SystemMessage, HumanMessage

import draft_store as draft_store_module
from draft_store import DraftStore
from pa_handler import (
    extract_pa_data,
    apply_changes,
    classify_action,
    format_remaining_variables,
    format_filled_summary,
    format_exhibit_a_summary,
)
from pa_docx import generate_pa_docx


CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "haiku")


def _get_llm():
    """Return a ChatClaudeCLI instance using CLAUDE_MODEL env var."""
    from claude_llm import ChatClaudeCLI
    return ChatClaudeCLI(model_name=CLAUDE_MODEL)


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

class PaState(TypedDict):
    """State for the PA workflow."""
    command: str               # "create" | "continue"
    user_message: str
    chat_history: list
    draft_id: Optional[str]    # from previous state
    # Outputs:
    response: str
    pa_active: bool
    docx_bytes: Optional[bytes]
    docx_filename: Optional[str]
    pa_action: Optional[str]   # triage result


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_store() -> DraftStore:
    """Create a DraftStore using the current module-level DB_PATH.

    This ensures that patching draft_store.DB_PATH in tests takes effect.
    """
    return DraftStore(draft_store_module.DB_PATH)


def _extract_address_from_message(msg: str) -> str:
    """Try to extract a property address from a user message.

    Looks for text after 'resume' keyword. Returns the address portion
    or empty string if nothing found.
    """
    lower = msg.lower().strip()
    if "resume" in lower:
        # Take everything after 'resume'
        idx = lower.index("resume") + len("resume")
        address = msg[idx:].strip()
        return address
    return ""


# ---------------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------------

def entry_node(state: PaState) -> dict:
    """Route to the correct starting point based on command.

    Routing is done by conditional edges, not this node.
    """
    return {}


def start_new_node(state: PaState) -> dict:
    """Create a new draft or resume an existing one.

    If user message contains 'resume' and an address, tries to load an
    existing draft by address first. Otherwise creates a new draft.
    Extracts any initial variables from the user_message.
    """
    store = _get_store()
    msg = state.get("user_message", "")

    # Check for resume intent
    address = _extract_address_from_message(msg)
    draft = None

    if address:
        draft = store.load_draft_by_address(address)

    if draft:
        # Resumed an existing draft
        draft_id = draft["id"]
        variables = draft.get("variables", {})
        filled_summary = format_filled_summary(variables)
        remaining = format_remaining_variables(variables)
        exhibit_a = format_exhibit_a_summary(variables)

        response_parts = [f"Resumed draft for {draft['property_address']}."]
        if filled_summary:
            response_parts.append(f"Variables on file:\n{filled_summary}")
        if exhibit_a:
            response_parts.append(exhibit_a)
        if remaining:
            response_parts.append(f"Remaining variables to fill:\n{remaining}")

        return {
            "response": "\n\n".join(response_parts),
            "draft_id": draft_id,
            "pa_active": True,
            "docx_bytes": None,
            "docx_filename": None,
        }

    # Try to extract initial variables from user message
    initial_vars = {}
    extracted_address = ""
    try:
        if msg:
            extracted = extract_pa_data(msg)
            if isinstance(extracted, dict):
                initial_vars = {k: v for k, v in extracted.items() if v is not None}
                extracted_address = initial_vars.get("property_address", "")
    except (json.JSONDecodeError, ValueError, Exception):
        pass

    # Use address from extraction or from the message if we had a resume attempt
    prop_address = extracted_address or address or "New Property"

    # Create a new draft
    draft_id = store.create_draft(
        property_address=prop_address,
        variables=initial_vars,
    )

    # Build response
    filled_summary = format_filled_summary(initial_vars)
    remaining = format_remaining_variables(initial_vars)
    exhibit_a = format_exhibit_a_summary(initial_vars)

    response_parts = ["New purchase agreement draft created."]
    if filled_summary:
        response_parts.append(f"Got it, here's what I picked up:\n{filled_summary}")
    if exhibit_a:
        response_parts.append(exhibit_a)
    if remaining:
        response_parts.append(f"Remaining variables to fill:\n{remaining}")
    else:
        response_parts.append(
            "Tell me about the deal: buyer name, property address, "
            "purchase price, and any other terms you know."
        )

    # Pre-generate preview so the download button is instant
    preview_bytes = None
    preview_filename = None
    if initial_vars:
        try:
            preview_bytes = generate_pa_docx(initial_vars)
            preview_filename = f"PA_{prop_address}.docx"
        except Exception:
            pass

    return {
        "response": "\n\n".join(response_parts),
        "draft_id": draft_id,
        "pa_active": True,
        "docx_bytes": preview_bytes,
        "docx_filename": preview_filename,
    }


def triage_node(state: PaState) -> dict:
    """Load existing draft and classify the user's action intent."""
    store = _get_store()
    draft_id = state.get("draft_id")

    if draft_id:
        draft = store.load_draft(draft_id)
        if draft is None:
            # Draft not found — treat as start_new
            return {
                "response": "Draft not found. Starting a new one.",
                "draft_id": None,
                "pa_active": True,
                "docx_bytes": None,
                "docx_filename": None,
                "pa_action": "edit",
            }

    # Classify the user's action
    action = classify_action(state.get("user_message", ""))
    return {"pa_action": action}


def extract_node(state: PaState) -> dict:
    """Extract variables from user input and update the draft."""
    store = _get_store()
    draft_id = state.get("draft_id")
    msg = state.get("user_message", "")

    if not draft_id:
        return {
            "response": "No active draft. Use 'create' to start one.",
            "pa_active": True,
            "docx_bytes": None,
            "docx_filename": None,
        }

    draft = store.load_draft(draft_id)
    if draft is None:
        return {
            "response": "Draft not found.",
            "pa_active": True,
            "docx_bytes": None,
            "docx_filename": None,
        }

    try:
        extracted = extract_pa_data(msg, draft.get("variables", {}))
        if isinstance(extracted, dict) and extracted:
            store.update_draft(draft_id, extracted)
    except (json.JSONDecodeError, ValueError, Exception):
        pass

    # Reload updated draft
    draft = store.load_draft(draft_id)
    variables = draft.get("variables", {}) if draft else {}

    filled_summary = format_filled_summary(extracted if isinstance(extracted, dict) else {})
    remaining = format_remaining_variables(variables)
    exhibit_a = format_exhibit_a_summary(variables)

    response_parts = []
    if filled_summary:
        response_parts.append(filled_summary)
    if exhibit_a:
        response_parts.append(exhibit_a)
    if remaining:
        response_parts.append(f"Remaining variables to fill:\n{remaining}")
    if not response_parts:
        response_parts.append("Variables updated.")

    return {
        "response": "\n\n".join(response_parts),
        "draft_id": draft_id,
        "pa_active": True,
        "docx_bytes": None,
        "docx_filename": None,
    }


def edit_node(state: PaState) -> dict:
    """Apply user-requested changes to the existing draft variables."""
    store = _get_store()
    draft_id = state.get("draft_id")

    if not draft_id:
        return {
            "response": "No active draft to edit.",
            "pa_active": True,
            "docx_bytes": None,
            "docx_filename": None,
        }

    draft = store.load_draft(draft_id)
    if draft is None:
        return {
            "response": "Draft not found.",
            "pa_active": True,
            "docx_bytes": None,
            "docx_filename": None,
        }

    old_variables = dict(draft.get("variables", {}))
    variables = dict(old_variables)
    try:
        updated = apply_changes(
            variables,
            state.get("user_message", ""),
            state.get("chat_history"),
        )
        if isinstance(updated, dict):
            # Strip None and empty strings — they mean "not filled"
            # Keep False, 0, [] so booleans/numbers/entity lists work
            updated = {k: v for k, v in updated.items() if v is not None and v != ""}
            store.update_draft(draft_id, updated)
            variables = updated
    except Exception as exc:
        logger.warning("apply_changes failed: %s", exc)

    # Show what changed (only real values, not empty/None)
    changed = {}
    for k, v in variables.items():
        if v is not None and v != "" and (k not in old_variables or old_variables.get(k) != v):
            changed[k] = v

    response_parts = []
    if changed:
        count = len(changed)
        filled = format_filled_summary(changed)
        response_parts.append(
            f"Got it — {count} variable{'s' if count != 1 else ''} updated.\n{filled}"
        )
    else:
        response_parts.append("No new variables detected — try rephrasing.")

    exhibit_a = format_exhibit_a_summary(variables)
    if exhibit_a:
        response_parts.append(exhibit_a)

    remaining = format_remaining_variables(variables)
    if remaining:
        response_parts.append(f"We still need:\n{remaining}")
    else:
        response_parts.append("All variables are filled!")

    # Pre-generate preview so the download button is instant
    preview_bytes = None
    preview_filename = None
    try:
        preview_bytes = generate_pa_docx(variables)
        prop_address = draft.get("property_address", "Property") if draft else "Property"
        preview_filename = f"PA_{prop_address}.docx"
    except Exception:
        pass

    return {
        "response": "\n\n".join(response_parts),
        "draft_id": draft_id,
        "pa_active": True,
        "docx_bytes": preview_bytes,
        "docx_filename": preview_filename,
    }


def preview_node(state: PaState) -> dict:
    """Generate a .docx preview from current variables."""
    store = _get_store()
    draft_id = state.get("draft_id")

    if not draft_id:
        return {
            "response": "No active draft to preview.",
            "pa_active": True,
            "docx_bytes": None,
            "docx_filename": None,
        }

    draft = store.load_draft(draft_id)
    if draft is None:
        return {
            "response": "Draft not found.",
            "pa_active": True,
            "docx_bytes": None,
            "docx_filename": None,
        }

    variables = draft.get("variables", {})
    prop_address = draft.get("property_address", "Property")

    try:
        docx_bytes = generate_pa_docx(variables)
        filename = f"PA_{prop_address}.docx"
        return {
            "response": "Here is your preview.",
            "draft_id": draft_id,
            "pa_active": True,
            "docx_bytes": docx_bytes,
            "docx_filename": filename,
        }
    except Exception:
        return {
            "response": "Could not generate preview.",
            "draft_id": draft_id,
            "pa_active": True,
            "docx_bytes": None,
            "docx_filename": None,
        }


def finalize_node(state: PaState) -> dict:
    """Generate final .docx, mark draft as completed, end workflow."""
    store = _get_store()
    draft_id = state.get("draft_id")

    if not draft_id:
        return {
            "response": "No active draft to finalize.",
            "pa_active": False,
            "docx_bytes": None,
            "docx_filename": None,
        }

    draft = store.load_draft(draft_id)
    if draft is None:
        return {
            "response": "Draft not found.",
            "pa_active": False,
            "docx_bytes": None,
            "docx_filename": None,
        }

    variables = draft.get("variables", {})
    prop_address = draft.get("property_address", "Property")

    try:
        docx_bytes = generate_pa_docx(variables)
    except Exception:
        docx_bytes = b""

    # Mark draft as completed
    store.update_draft(draft_id, variables, status="completed")

    filename = f"PA_{prop_address}.docx"
    return {
        "response": "Purchase agreement finalized.",
        "draft_id": draft_id,
        "pa_active": False,
        "docx_bytes": docx_bytes,
        "docx_filename": filename,
    }


def save_node(state: PaState) -> dict:
    """Save and exit the workflow (draft stays in_progress for later)."""
    return {
        "response": "Draft saved. You can resume it later.",
        "draft_id": state.get("draft_id"),
        "pa_active": False,
        "docx_bytes": None,
        "docx_filename": None,
    }


def list_drafts_node(state: PaState) -> dict:
    """List all drafts with summary info."""
    store = _get_store()
    drafts = store.list_drafts()

    if not drafts:
        return {
            "response": "No drafts found.",
            "draft_id": state.get("draft_id"),
            "pa_active": True,
            "docx_bytes": None,
            "docx_filename": None,
        }

    lines = ["Your drafts:\n"]
    for d in drafts:
        lines.append(
            f"  - {d['property_address']} ({d['status']}, "
            f"{d['completion_pct']}% complete) [ID: {d['id'][:8]}...]"
        )

    return {
        "response": "\n".join(lines),
        "draft_id": state.get("draft_id"),
        "pa_active": True,
        "docx_bytes": None,
        "docx_filename": None,
    }


def question_node(state: PaState) -> dict:
    """Answer a general question mid-workflow, keeping the draft active."""
    llm = _get_llm()
    response = llm.invoke([
        SystemMessage(content=(
            "You are a helpful commercial real estate assistant. The user is "
            "in the middle of building a purchase agreement and has a question. "
            "Answer concisely. After answering, remind them they can continue "
            "editing or say 'finalize' when ready."
        )),
        HumanMessage(content=state.get("user_message", "")),
    ])
    return {
        "response": response.content,
        "draft_id": state.get("draft_id"),
        "pa_active": True,
        "docx_bytes": None,
        "docx_filename": None,
    }


def cancel_node(state: PaState) -> dict:
    """Cancel and delete the draft."""
    store = _get_store()
    draft_id = state.get("draft_id")

    if draft_id:
        store.delete_draft(draft_id)

    return {
        "response": "Draft cancelled and deleted.",
        "draft_id": draft_id,
        "pa_active": False,
        "docx_bytes": None,
        "docx_filename": None,
    }


# ---------------------------------------------------------------------------
# Routing functions
# ---------------------------------------------------------------------------

def route_entry(state: PaState) -> str:
    """Route from entry based on command and draft_id."""
    command = state.get("command", "")

    if command == "create":
        return "start_new"

    if command == "continue":
        draft_id = state.get("draft_id")
        if draft_id:
            return "triage"
        # No draft_id — treat as new
        return "start_new"

    # Unknown command — default to start_new
    return "start_new"


def route_triage(state: PaState) -> str:
    """Route based on triage classification result."""
    action = state.get("pa_action", "edit")
    valid_routes = {"edit", "preview", "finalize", "save", "list_drafts", "question", "cancel"}
    if action in valid_routes:
        return action
    return "edit"


# ---------------------------------------------------------------------------
# Build graph
# ---------------------------------------------------------------------------

def build_graph():
    """Build and compile the PA LangGraph."""
    graph = StateGraph(PaState)

    # Add nodes
    graph.add_node("entry", entry_node)
    graph.add_node("start_new", start_new_node)
    graph.add_node("triage", triage_node)
    graph.add_node("extract", extract_node)
    graph.add_node("edit", edit_node)
    graph.add_node("preview", preview_node)
    graph.add_node("finalize", finalize_node)
    graph.add_node("save", save_node)
    graph.add_node("list_drafts", list_drafts_node)
    graph.add_node("question", question_node)
    graph.add_node("cancel", cancel_node)

    # Entry point
    graph.set_entry_point("entry")

    # Conditional edges from entry
    graph.add_conditional_edges("entry", route_entry, {
        "start_new": "start_new",
        "triage": "triage",
    })

    # Conditional edges from triage
    graph.add_conditional_edges("triage", route_triage, {
        "edit": "edit",
        "preview": "preview",
        "finalize": "finalize",
        "save": "save",
        "list_drafts": "list_drafts",
        "question": "question",
        "cancel": "cancel",
    })

    # Terminal nodes — all go to END
    graph.add_edge("start_new", END)
    graph.add_edge("extract", END)
    graph.add_edge("edit", END)
    graph.add_edge("preview", END)
    graph.add_edge("finalize", END)
    graph.add_edge("save", END)
    graph.add_edge("list_drafts", END)
    graph.add_edge("question", END)
    graph.add_edge("cancel", END)

    return graph.compile()
