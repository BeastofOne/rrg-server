"""LangGraph for Router Node — intent classification only.

This graph is used when NO worker node is active. It classifies the user's
intent and routes to either a worker container or a local chat response.

Entry: detect_intent → route → (chat_response | END)
"""

import json
from langgraph.graph import StateGraph, END
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage

from state import RouterState
from config import CLAUDE_MODEL, INTENTS
from claude_llm import ChatClaudeCLI


# ---------------------------------------------------------------------------
# Shared LLM
# ---------------------------------------------------------------------------

_llm = None


def _get_llm() -> ChatClaudeCLI:
    global _llm
    if _llm is None:
        _llm = ChatClaudeCLI(model_name=CLAUDE_MODEL)
    return _llm


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

CLASSIFY_PROMPT = """You are an intent classifier for a personal assistant.

Given the user's message and conversation history, classify it into one of the available intents.
Use the conversation history to resolve ambiguous references like "let's do that", "yes", "sure", etc.

Available intents:
{intents}

Respond ONLY with valid JSON in this exact format:
{{"intent": "intent_name", "params": {{}}}}

If you can't determine the intent, use: {{"intent": "help", "params": {{}}}}
"""


# ---------------------------------------------------------------------------
# Helper Functions
# ---------------------------------------------------------------------------

def _get_available_intents() -> str:
    """Format INTENTS as a string for the classification prompt."""
    lines = []
    for name, info in INTENTS.items():
        lines.append(f"- {name}: {info['description']}")
    return "\n".join(lines)


def _get_capability_intents() -> str:
    """List capabilities (intents with handlers) for help response."""
    lines = []
    for name, info in INTENTS.items():
        if info.get("handler") is not None:
            label = info.get("help_text", info["description"])
            lines.append(f"- {label}")
    return "\n".join(lines)


def _build_help_response() -> str:
    """Generate the help message listing available capabilities."""
    capabilities = _get_capability_intents()
    if not capabilities:
        return "I'm still getting set up — no workflows available yet!"
    return f"Here's what I can help with:\n\n{capabilities}\n\nJust ask me in plain English."


# ---------------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------------

def detect_intent_node(state: RouterState) -> dict:
    """Classify user message into intent via LLM."""
    llm = _get_llm()
    intents_str = _get_available_intents()
    system = CLASSIFY_PROMPT.format(intents=intents_str)

    messages = [SystemMessage(content=system)]
    for msg in (state.get("chat_history") or []):
        if msg["role"] == "user":
            messages.append(HumanMessage(content=msg["content"]))
        elif msg["role"] == "assistant":
            messages.append(AIMessage(content=msg["content"]))
    messages.append(HumanMessage(content=state["user_message"]))

    response = llm.invoke(messages)

    try:
        text = response.content.strip()
        # Strip markdown code blocks if present
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
            text = text.rsplit("```", 1)[0]
        parsed = json.loads(text.strip())
        return {
            "intent": parsed.get("intent", "help"),
            "params": parsed.get("params", {}),
        }
    except (json.JSONDecodeError, AttributeError):
        return {"intent": "help", "params": {}}


def route_node(state: RouterState) -> dict:
    """Determine routing based on classified intent."""
    intent = state.get("intent", "help")

    if intent not in INTENTS:
        return {"route_type": "error", "handler_name": None}

    intent_config = INTENTS[intent]
    handler = intent_config.get("handler")

    if handler:
        return {"route_type": "handler", "handler_name": handler}
    else:
        return {"route_type": "chat", "handler_name": None}


def chat_response_node(state: RouterState) -> dict:
    """Handle greeting and help intents locally."""
    intent = state.get("intent", "help")

    if intent == "help":
        response = _build_help_response()
    elif intent == "greeting":
        llm = _get_llm()
        capabilities = _get_capability_intents()
        result = llm.invoke([
            SystemMessage(content=(
                "You are a personal assistant. Respond to the user's greeting in one short sentence. "
                "Be casual and friendly but not over-the-top. No emojis. No lists. "
                "If it makes sense, briefly mention you can help with:\n"
                f"{capabilities}"
            )),
            HumanMessage(content=state["user_message"]),
        ])
        response = result.content
    else:
        response = _build_help_response()

    return {"response": response}


# ---------------------------------------------------------------------------
# Routing Function
# ---------------------------------------------------------------------------

def route_from_route_node(state: RouterState) -> str:
    """Conditional edge: chat intents → chat_response, everything else → END."""
    route_type = state.get("route_type", "error")
    if route_type == "chat":
        return "chat_response"
    return END


# ---------------------------------------------------------------------------
# Build Graph
# ---------------------------------------------------------------------------

def build_graph():
    """Build and compile the Router's intent classification graph."""
    graph = StateGraph(RouterState)

    graph.add_node("detect_intent", detect_intent_node)
    graph.add_node("route", route_node)
    graph.add_node("chat_response", chat_response_node)

    graph.set_entry_point("detect_intent")
    graph.add_edge("detect_intent", "route")

    graph.add_conditional_edges("route", route_from_route_node, {
        "chat_response": "chat_response",
        END: END,
    })

    graph.add_edge("chat_response", END)

    return graph.compile()
