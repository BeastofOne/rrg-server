"""Configuration for Router Node — intents and worker registry."""

import os
from dotenv import load_dotenv

load_dotenv()

# Claude CLI settings
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "haiku")

# Worker node registry — URLs from env (Docker service names on windmill_default network)
WORKER_URLS = {
    "pnl": os.getenv("WORKER_PNL_URL", "http://rrg-pnl:8100"),
    "brochure": os.getenv("WORKER_BROCHURE_URL", "http://rrg-brochure:8101"),
}

# Windmill settings — when enabled, worker calls route through Windmill flow
USE_WINDMILL = os.getenv("USE_WINDMILL", "true").lower() == "true"
WINDMILL_BASE_URL = os.getenv("WINDMILL_BASE_URL", "http://windmill-windmill_server-1:8000")
WINDMILL_TOKEN = os.getenv("WINDMILL_TOKEN", "")
WINDMILL_WORKSPACE = os.getenv("WINDMILL_WORKSPACE", "rrg")

# Intent definitions
INTENTS = {
    "greeting": {
        "description": "User says hello or asks how the assistant is doing",
        "handler": None,
    },
    "help": {
        "description": "User asks what the assistant can do",
        "handler": None,
    },
    "create_pnl": {
        "description": "User wants to create a profit and loss statement for a property",
        "help_text": "Create a profit and loss (P&L) statement for a property",
        "handler": "pnl",
    },
    "create_brochure": {
        "description": "User wants to create a property marketing brochure or offering memorandum",
        "help_text": "Create a property marketing brochure (offering memorandum)",
        "handler": "brochure",
    },
}
