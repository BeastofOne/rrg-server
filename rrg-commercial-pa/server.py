"""RRG Commercial PA Microservice — persistent Flask container.

Loads the PA LangGraph once at startup. Container stays warm.
Exposes POST /process (standard worker node contract) and GET /health.
"""

import base64
import os
import traceback
from flask import Flask, request, jsonify

app = Flask(__name__)

# Import the graph module — build_graph() is called per-request so that
# the mock in test fixtures can swap the return value between tests.
import graph as _graph_module

# Cache the compiled graph in production; tests patch graph.build_graph
# to return a fresh mock each invocation.
_cached_graph = None


def _get_graph():
    """Return the compiled graph, building it on first call."""
    global _cached_graph
    if app.config.get("TESTING"):
        # In test mode, always call build_graph() so fixtures can
        # swap the mock between tests.
        return _graph_module.build_graph()
    if _cached_graph is None:
        _cached_graph = _graph_module.build_graph()
    return _cached_graph


@app.route("/process", methods=["POST"])
def process():
    """Standard worker node endpoint.

    Request:
        {
            command: str,           # "create" | "continue"
            user_message: str,
            chat_history: [...],    # list of {role, content}
            state: {...}            # opaque state from previous invocation
        }

    Response:
        {
            response: str,          # message to display to user
            state: {...},           # updated state (passed back next time)
            active: bool,           # true = node still owns conversation
            docx_bytes: str|null,   # base64-encoded DOCX if generated
            docx_filename: str|null
        }
    """
    data = request.json or {}
    command = data.get("command", "create")
    user_message = data.get("user_message", "")
    chat_history = data.get("chat_history", [])
    prev_state = data.get("state", {})

    # Build graph input from request + previous state
    graph_input = {
        "command": command,
        "user_message": user_message,
        "chat_history": chat_history,
        "draft_id": prev_state.get("draft_id"),
        # Initialize output fields
        "response": "",
        "pa_active": True,
        "docx_bytes": None,
        "docx_filename": None,
        "pa_action": None,
    }

    try:
        compiled_graph = _get_graph()
        result = compiled_graph.invoke(graph_input)
    except Exception as e:
        traceback.print_exc()
        return jsonify({
            "response": f"Error processing PA request: {e}",
            "state": prev_state,
            "active": prev_state.get("pa_active", True),
            "docx_bytes": None,
            "docx_filename": None,
        }), 500

    # Build response
    pa_active = result.get("pa_active", True)
    docx_bytes_raw = result.get("docx_bytes")

    # Encode DOCX as base64 if present
    docx_b64 = None
    if docx_bytes_raw:
        docx_b64 = base64.b64encode(docx_bytes_raw).decode("utf-8")

    return jsonify({
        "response": result.get("response", ""),
        "state": {
            "draft_id": result.get("draft_id"),
            "pa_active": pa_active,
        },
        "active": pa_active,
        "docx_bytes": docx_b64,
        "docx_filename": result.get("docx_filename"),
    })


@app.route("/health", methods=["GET"])
def health():
    """Simple health check — verifies the container is alive and graph is loaded."""
    return jsonify({"status": "ok", "service": "rrg-commercial-pa"})


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8102"))
    print(f"rrg-commercial-pa starting on port {port}")
    app.run(host="0.0.0.0", port=port)
