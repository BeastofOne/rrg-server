"""Self-contained Brochure LangGraph for the rrg-brochure microservice.

10 nodes: extract, nudge, triage, edit, approve, preview, question, cancel, photo_search.
Entry point is `build_graph()` which returns a compiled LangGraph.
"""

import json
import re
import os
from datetime import date
from typing import TypedDict, Optional

from langgraph.graph import StateGraph, END

from langchain_core.messages import SystemMessage, HumanMessage

from claude_llm import ChatClaudeCLI
from brochure_pdf import generate_brochure_pdf
from photo_scraper import search_property_photos
from photo_search_pdf import generate_photo_search_pdf


CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "haiku")


def _get_llm() -> ChatClaudeCLI:
    return ChatClaudeCLI(model_name=CLAUDE_MODEL)


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

class BrochureState(TypedDict):
    """State for the Brochure workflow."""
    command: str               # "create" | "continue"
    user_message: str
    chat_history: list         # list of {"role": ..., "content": ...}
    brochure_data: Optional[dict]   # current brochure data (from previous state)

    # Outputs (set by nodes)
    response: str
    brochure_data_out: Optional[dict]
    brochure_active_out: bool
    pdf_bytes: Optional[bytes]
    pdf_filename: Optional[str]
    brochure_action: Optional[str]  # triage result: edit/approve/preview/cancel/question/search


# ---------------------------------------------------------------------------
# Zone completeness
# ---------------------------------------------------------------------------

BROCHURE_ZONES = [
    ("Cover", ["property_name", "address_line1", "price", "hero_image_path"],
     lambda d: bool(d.get("property_name")) and bool(d.get("address_line1")) and bool(d.get("price"))),
    ("Hero Photo", ["hero_image_path"],
     lambda d: bool(d.get("hero_image_path"))),
    ("Investment Highlights", ["investment_highlights"],
     lambda d: len(d.get("investment_highlights") or []) >= 3),
    ("Property Highlights", ["property_highlights"],
     lambda d: len(d.get("property_highlights") or []) >= 3),
    ("Location Highlights", ["location_highlights"],
     lambda d: len(d.get("location_highlights") or []) >= 3),
    ("Map Image", ["map_image_path"],
     lambda d: bool(d.get("map_image_path"))),
    ("Photos", ["photos"],
     lambda d: len(d.get("photos") or []) >= 5),
    ("Financials (P&L)", ["financials_pdf_path"],
     lambda d: bool(d.get("financials_pdf_path"))),
]


def _brochure_zone_status(data: dict) -> tuple:
    """Return (complete_zones, missing_zones, nudge_message)."""
    if not data:
        return [], [z[0] for z in BROCHURE_ZONES], ""

    complete = []
    missing = []
    for label, _keys, checker in BROCHURE_ZONES:
        if checker(data):
            complete.append(label)
        else:
            missing.append(label)

    if not missing:
        nudge = "All zones are filled in. Say **looks good** to finalize, or **show me** to preview."
    else:
        next_zone = missing[0]
        nudge_map = {
            "Cover": "I still need the **property name**, **address**, and **asking price**.",
            "Hero Photo": (
                "Next up: **hero photo** for the cover page.\n\n"
                "Do you have one you can share (file path), or should I **search online** "
                "for photos of this property? I'll check Crexi, LoopNet, Google Business, Yelp, etc."
            ),
            "Investment Highlights": "I need **3-4 investment highlights** (e.g., NOI, cap rate, tenant strength). These should focus on why this is a good investment.",
            "Property Highlights": "I need **3-4 property highlights** about the building itself (e.g., size, build-out, drive-thru, condition).",
            "Location Highlights": "I need **3-4 location highlights** about the area (e.g., traffic, visibility, nearby institutions).",
            "Map Image": (
                "Next up: **map image** of the property location.\n\n"
                "Do you have a screenshot you can share (file path), or should I **search online** "
                "for a map of this address?"
            ),
            "Photos": (
                "I need **5 property photos** for the Photos page.\n\n"
                "Do you have photos you can share (file paths), or should I **search online** "
                "for photos of this property? I'll check Crexi, LoopNet, Google Business, Yelp, etc."
            ),
            "Financials (P&L)": "Do you have a **P&L or financial statement** for this property? You can share the file path, or we can **create one together**.",
        }
        nudge = nudge_map.get(next_zone, f"Next up: **{next_zone}**.")

    return complete, missing, nudge


def _zone_status_summary(data: dict) -> str:
    """Build a markdown checklist of zone completion."""
    if not data:
        return ""
    lines = []
    for label, _keys, checker in BROCHURE_ZONES:
        mark = "x" if checker(data) else " "
        lines.append(f"- [{mark}] {label}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

BROCHURE_ONBOARDING = (
    "I'll help you create a property brochure. Here's what we need to fill in:\n\n"
    "1. **Cover info** — property name, address, asking price\n"
    "2. **Hero photo** — main image for the cover page\n"
    "3. **Investment highlights** — 3-4 bullets on why it's a good investment\n"
    "4. **Property highlights** — 3-4 bullets about the building/site\n"
    "5. **Location highlights** — 3-4 bullets about the area\n"
    "6. **Map image** — screenshot of the property location\n"
    "7. **5 property photos** — for the Photos page\n"
    "8. **Financials** — P&L statement or proforma\n\n"
    "Let's start with the basics — what's the **property name, address, and asking price**?"
)

BROCHURE_EXTRACT_PROMPT = """You are extracting property brochure data from the user's message.
Extract as much as you can from what they provide. Return ONLY valid JSON with these fields
(use empty string or empty list if not provided):

{{
    "property_name": "string",
    "address_line1": "string (street address)",
    "address_line2": "string (city, state zip)",
    "price": "string (formatted like $850,000)",
    "highlights": ["cover bullet point 1", "cover bullet point 2"],
    "investment_highlights": ["point 1", "point 2", "point 3"],
    "property_highlights": ["point 1", "point 2", "point 3"],
    "location_highlights": ["point 1", "point 2", "point 3"],
    "hero_image_path": "",
    "map_image_path": "",
    "photos": [],
    "financials_pdf_path": ""
}}

IMPORTANT: investment_highlights, property_highlights, and location_highlights
should each have 3-4 bullets and MUST NOT repeat each other. Each category covers
a distinct angle:
- investment_highlights: why it's a good investment (NOI, cap rate, tenant, franchise)
- property_highlights: the building/site itself (SF, condition, build-out, drive-thru)
- location_highlights: the area (traffic, visibility, nearby institutions, demographics)"""

BROCHURE_CHANGE_PROMPT = """You are updating property brochure data based on the user's request.

Current brochure data:
{current_data}

The user's change request: {user_message}

Conversation context (recent messages):
{history}

Apply the requested changes and return the COMPLETE updated JSON with ALL fields
(not just the changed ones). Return ONLY valid JSON.

IMPORTANT:
- If the user provides file paths for images, set the corresponding field
  (hero_image_path, map_image_path, photos, financials_pdf_path).
- investment_highlights, property_highlights, and location_highlights should
  each have 3-4 bullets and MUST NOT repeat each other.
- Each highlight category covers a distinct angle:
  * investment_highlights: why it's a good investment (NOI, cap rate, tenant)
  * property_highlights: the building/site itself (SF, condition, build-out)
  * location_highlights: the area (traffic, visibility, demographics)"""

BROCHURE_TRIAGE_PROMPT = """You are triaging a user message during an active brochure workflow.
The user already has brochure data in progress. Classify their message into ONE of these categories:

- "edit" — They want to change/add/remove something in the brochure data (text, highlights, price, name, etc.)
- "preview" — They want to see/download/view what the brochure looks like so far (e.g., "show me", "let me see it", "generate the pdf", "what does it look like")
- "search" — They want to search the web for property photos (e.g., "search for photos", "find photos online", "look for images")
- "question" — They are asking a general question

Respond with ONLY one word: edit, preview, search, or question"""


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _message_has_numbers(msg: str) -> bool:
    """Quick check if message contains any dollar amounts or percentages."""
    return bool(re.search(r'[\$\d][\d,]*\.?\d*|[\d]+\s*%', msg))


def is_approval(msg: str) -> bool:
    """Check if the user's message is an approval/finalization."""
    approvals = [
        "looks good", "look good", "lgtm", "approved", "approve",
        "finalize", "generate", "done", "perfect", "great",
        "that's good", "thats good", "good to go", "ship it",
        "yes", "yep", "yeah", "yup", "sure", "ok", "okay",
    ]
    lower = msg.lower().strip().rstrip("!.").strip()
    return lower in approvals


# ---------------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------------

def entry_node(state: BrochureState) -> dict:
    """Route to the correct starting point based on command."""
    return {}


def brochure_extract_node(state: BrochureState) -> dict:
    """Extract brochure data from the user's message or show onboarding."""
    if not _message_has_numbers(state["user_message"]) and len(state["user_message"].split()) < 15:
        return {
            "response": BROCHURE_ONBOARDING,
            "brochure_data_out": None,
            "brochure_active_out": True,
            "pdf_bytes": None,
            "pdf_filename": None,
        }

    llm = _get_llm()
    response = llm.invoke([
        SystemMessage(content=BROCHURE_EXTRACT_PROMPT),
        HumanMessage(content=state["user_message"]),
    ])

    try:
        text = response.content.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
            text = text.rsplit("```", 1)[0]
        data = json.loads(text.strip())

        summary_parts = []
        if data.get("property_name"):
            summary_parts.append(f"**Property:** {data['property_name']}")
        if data.get("address_line1"):
            summary_parts.append(f"**Address:** {data['address_line1']}, {data.get('address_line2', '')}")
        if data.get("price"):
            summary_parts.append(f"**Price:** {data['price']}")

        summary = "\n".join(summary_parts) if summary_parts else "Got some data"
        zone_checklist = _zone_status_summary(data)
        _complete, missing, nudge = _brochure_zone_status(data)

        return {
            "response": (
                f"Here's what I have so far:\n\n{summary}\n\n"
                f"**Brochure checklist:**\n{zone_checklist}\n\n"
                f"{nudge}\n\n"
                "You can also say **show me** to preview the PDF at any point."
            ),
            "brochure_data_out": data,
            "brochure_active_out": True,
            "pdf_bytes": None,
            "pdf_filename": None,
        }
    except (json.JSONDecodeError, Exception):
        return {
            "response": (
                "I couldn't parse that into brochure data. Could you try again with "
                "the property name, address, price, and highlights?"
            ),
            "brochure_data_out": None,
            "brochure_active_out": True,
            "pdf_bytes": None,
            "pdf_filename": None,
        }


def brochure_triage_node(state: BrochureState) -> dict:
    """Determine what the user wants to do with their existing brochure."""
    msg = state["user_message"].lower().strip()
    if msg in ("cancel", "nevermind", "never mind", "stop", "quit"):
        return {"brochure_action": "cancel"}
    if is_approval(state["user_message"]):
        return {"brochure_action": "approve"}

    llm = _get_llm()
    response = llm.invoke([
        SystemMessage(content=BROCHURE_TRIAGE_PROMPT),
        HumanMessage(content=state["user_message"]),
    ])
    action = response.content.strip().lower()
    if action in ("question", "edit", "preview", "search"):
        return {"brochure_action": action}
    return {"brochure_action": "edit"}


def brochure_edit_node(state: BrochureState) -> dict:
    """Apply user-requested changes to the existing brochure data."""
    llm = _get_llm()
    history_str = ""
    for msg in (state.get("chat_history") or [])[-6:]:
        history_str += f"{msg['role']}: {msg['content']}\n"

    response = llm.invoke([
        SystemMessage(content=BROCHURE_CHANGE_PROMPT.format(
            current_data=json.dumps(state["brochure_data"], indent=2),
            user_message=state["user_message"],
            history=history_str,
        )),
        HumanMessage(content="Apply the changes and return the updated JSON."),
    ])

    try:
        text = response.content.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
            text = text.rsplit("```", 1)[0]
        updated = json.loads(text.strip())

        _complete, missing, nudge = _brochure_zone_status(updated)
        zone_checklist = _zone_status_summary(updated)

        return {
            "response": (
                f"Updated.\n\n"
                f"**Brochure checklist:**\n{zone_checklist}\n\n"
                f"{nudge}\n\n"
                "Say **show me** to preview the PDF."
            ),
            "brochure_data_out": updated,
            "pdf_bytes": None,
            "pdf_filename": None,
        }
    except (json.JSONDecodeError, Exception):
        return {
            "response": "I couldn't apply that change. Could you rephrase?",
            "brochure_data_out": state.get("brochure_data"),
            "pdf_bytes": None,
            "pdf_filename": None,
        }


def brochure_approve_node(state: BrochureState) -> dict:
    """Generate the finalized brochure PDF."""
    data = state["brochure_data"]
    pdf_bytes = generate_brochure_pdf(data)

    today = date.today().strftime("%Y%m%d")
    name = data.get("property_name", "Property").strip()
    pdf_filename = f"{today}_Brochure_{name}.pdf"

    return {
        "response": "Brochure generated! Download your PDF below.",
        "brochure_data_out": None,
        "brochure_active_out": False,
        "pdf_bytes": pdf_bytes,
        "pdf_filename": pdf_filename,
    }


def brochure_cancel_node(state: BrochureState) -> dict:
    """Cancel the brochure workflow."""
    return {
        "response": "No problem — brochure cancelled.",
        "brochure_data_out": None,
        "brochure_active_out": False,
        "pdf_bytes": None,
        "pdf_filename": None,
    }


def brochure_question_node(state: BrochureState) -> dict:
    """Answer a question mid-brochure workflow."""
    llm = _get_llm()
    brochure_context = json.dumps(state.get("brochure_data", {}), indent=2)
    response = llm.invoke([
        SystemMessage(content=(
            "You are a helpful real estate assistant. The user is in the middle of building "
            "a property brochure and has asked a question. Answer concisely. "
            "After answering, remind them they can continue editing or say 'looks good' to generate.\n\n"
            f"Current brochure data:\n{brochure_context}"
        )),
        HumanMessage(content=state["user_message"]),
    ])
    return {
        "response": response.content,
        "brochure_data_out": state.get("brochure_data"),
        "pdf_bytes": None,
        "pdf_filename": None,
    }


def brochure_preview_node(state: BrochureState) -> dict:
    """Generate a preview PDF without finalizing."""
    data = state["brochure_data"]
    pdf_bytes = generate_brochure_pdf(data)

    today = date.today().strftime("%Y%m%d")
    name = data.get("property_name", "Property").strip()
    pdf_filename = f"{today}_Brochure_{name}_preview.pdf"

    _complete, missing, nudge = _brochure_zone_status(data)
    if missing:
        zone_checklist = _zone_status_summary(data)
        msg = (
            f"Here's your preview.\n\n"
            f"**Brochure checklist:**\n{zone_checklist}\n\n"
            f"{nudge}"
        )
    else:
        msg = "Here's your preview — all zones are filled in. Say **looks good** to finalize, or make any changes."

    return {
        "response": msg,
        "brochure_data_out": data,
        "brochure_active_out": True,
        "pdf_bytes": pdf_bytes,
        "pdf_filename": pdf_filename,
    }


def brochure_nudge_node(state: BrochureState) -> dict:
    """User is in brochure mode but sent a non-data message."""
    msg = state["user_message"].lower().strip()
    if msg in ("cancel", "nevermind", "never mind", "stop", "quit"):
        return {
            "response": "No problem — brochure cancelled.",
            "brochure_data_out": None,
            "brochure_active_out": False,
            "pdf_bytes": None,
            "pdf_filename": None,
        }
    llm = _get_llm()
    result = llm.invoke([
        SystemMessage(content=(
            "You are a personal assistant helping the user build a property brochure. "
            "They've started the brochure workflow but their latest message doesn't contain "
            "property data. Respond naturally, then steer back to getting the details. "
            "Keep it to 1-2 sentences. No emojis."
        )),
        HumanMessage(content=state["user_message"]),
    ])
    return {
        "response": result.content,
        "brochure_data_out": None,
        "brochure_active_out": True,
        "pdf_bytes": None,
        "pdf_filename": None,
    }


def brochure_photo_search_node(state: BrochureState) -> dict:
    """Search the web for photos of the property, download them, and output a numbered PDF.

    Two-phase approach via photo_scraper:
      1. Claude CLI + WebSearch (haiku, ~30s) finds listing page URLs
      2. Python requests fetches pages and extracts image URLs via regex
    """
    data = state.get("brochure_data", {})
    prop_name = data.get("property_name", "")
    address = f"{data.get('address_line1', '')} {data.get('address_line2', '')}".strip()

    # Run the two-phase scraper
    try:
        photos = search_property_photos(prop_name, address)
    except Exception:
        photos = []

    # Generate the numbered PDF if we got images
    pdf_bytes = None
    pdf_filename = None
    if photos:
        pdf_bytes = generate_photo_search_pdf(
            photos=photos,
            property_name=prop_name,
            address=address,
        )
        if pdf_bytes:
            today = date.today().strftime("%Y%m%d")
            safe_name = prop_name.replace("/", "-").strip() or "Property"
            pdf_filename = f"{today}_Photo_Search_{safe_name}.pdf"
            search_result_text = (
                f"Found {len(photos)} property photos and downloaded them into a numbered PDF.\n\n"
                f"Download the PDF below and tell me which photos to use. For example:\n"
                f"- \"Use photo 3 as the hero\"\n"
                f"- \"Use photos 5, 8, 12, 15, 18 for the photos page\""
            )
        else:
            search_result_text = (
                f"Found {len(photos)} image URLs but couldn't download any of them. "
                f"The images may be behind authentication or blocking direct downloads.\n\n"
                f"You may need to download the photos manually from these sources."
            )
    else:
        search_result_text = (
            "Couldn't find property photos online. This can happen if the property "
            "doesn't have public listing pages with photos.\n\n"
            "You can provide photos directly by uploading them."
        )

    _complete, missing, nudge = _brochure_zone_status(data)
    zone_checklist = _zone_status_summary(data)

    return {
        "response": (
            f"{search_result_text}\n\n---\n\n"
            f"**Brochure checklist:**\n{zone_checklist}\n\n"
            f"{nudge}"
        ),
        "brochure_data_out": data,
        "brochure_active_out": True,
        "pdf_bytes": pdf_bytes,
        "pdf_filename": pdf_filename,
    }


# ---------------------------------------------------------------------------
# Routing functions
# ---------------------------------------------------------------------------

def route_entry(state: BrochureState) -> str:
    """Route from entry: create goes to extract, continue goes to triage or nudge."""
    if state.get("command") == "create":
        return "extract"

    # "continue" — user has an active brochure
    if state.get("brochure_data"):
        return "triage"

    # No existing data yet (still collecting) — check if message has data
    if _message_has_numbers(state.get("user_message", "")) or len(state.get("user_message", "").split()) >= 15:
        return "extract"
    return "nudge"


def route_triage(state: BrochureState) -> str:
    """Route based on triage result."""
    action = state.get("brochure_action", "edit")
    if action == "approve":
        return "approve"
    elif action == "cancel":
        return "cancel"
    elif action == "preview":
        return "preview"
    elif action == "question":
        return "question"
    elif action == "search":
        return "photo_search"
    return "edit"


# ---------------------------------------------------------------------------
# Build graph
# ---------------------------------------------------------------------------

def build_graph() -> StateGraph:
    """Build and compile the Brochure LangGraph."""
    graph = StateGraph(BrochureState)

    # Add nodes
    graph.add_node("entry", entry_node)
    graph.add_node("extract", brochure_extract_node)
    graph.add_node("nudge", brochure_nudge_node)
    graph.add_node("triage", brochure_triage_node)
    graph.add_node("edit", brochure_edit_node)
    graph.add_node("approve", brochure_approve_node)
    graph.add_node("preview", brochure_preview_node)
    graph.add_node("question", brochure_question_node)
    graph.add_node("cancel", brochure_cancel_node)
    graph.add_node("photo_search", brochure_photo_search_node)

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
        "preview": "preview",
        "question": "question",
        "cancel": "cancel",
        "photo_search": "photo_search",
    })

    # Terminal nodes — all go to END
    for node in ["extract", "nudge", "edit", "approve", "preview",
                  "question", "cancel", "photo_search"]:
        graph.add_edge(node, END)

    return graph.compile()
