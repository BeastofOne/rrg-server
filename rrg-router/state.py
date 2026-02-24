"""State schema for the Router's intent classification graph."""

from typing import List, Optional
from typing_extensions import TypedDict


class RouterState(TypedDict, total=False):
    # Input
    user_message: str
    chat_history: Optional[List[dict]]  # [{role, content}, ...]

    # Set by detect_intent node
    intent: str
    params: dict

    # Set by route node
    route_type: str  # "handler" | "chat" | "error"
    handler_name: Optional[str]  # "pnl" | "brochure"

    # Set by chat_response node (when route_type == "chat")
    response: str
