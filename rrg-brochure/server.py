"""RRG Brochure Microservice — persistent Flask container.

Loads the Brochure LangGraph once at startup. Container stays warm.
Exposes POST /process (standard worker node contract) and GET /health.
"""

import base64
import os
import traceback
from flask import Flask, request, jsonify

app = Flask(__name__)

# Load graph once at startup — no cold start per request
from graph import build_graph
graph = build_graph()


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
            pdf_bytes: str|null,    # base64-encoded PDF if generated
            pdf_filename: str|null
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
        "brochure_data": prev_state.get("brochure_data"),
        # Initialize output fields
        "response": "",
        "brochure_data_out": None,
        "brochure_active_out": True,
        "pdf_bytes": None,
        "pdf_filename": None,
        "brochure_action": None,
    }

    try:
        result = graph.invoke(graph_input)
    except Exception as e:
        traceback.print_exc()
        return jsonify({
            "response": f"Error processing brochure request: {e}",
            "state": prev_state,
            "active": prev_state.get("brochure_active", True),
            "pdf_bytes": None,
            "pdf_filename": None,
        }), 500

    # Build response
    response_text = result.get("response", "")
    brochure_data_out = result.get("brochure_data_out")
    brochure_active = result.get("brochure_active_out", True)
    pdf_bytes_raw = result.get("pdf_bytes")
    pdf_filename = result.get("pdf_filename")

    # Determine current brochure data for state persistence
    # If node produced new data, use it; otherwise keep previous
    current_brochure_data = brochure_data_out if brochure_data_out is not None else prev_state.get("brochure_data")

    # If workflow ended (active=False), clear the data
    if not brochure_active:
        current_brochure_data = None

    # Encode PDF as base64 if present
    pdf_b64 = None
    if pdf_bytes_raw:
        pdf_b64 = base64.b64encode(pdf_bytes_raw).decode("utf-8")

    return jsonify({
        "response": response_text,
        "state": {
            "brochure_data": current_brochure_data,
            "brochure_active": brochure_active,
        },
        "active": brochure_active,
        "pdf_bytes": pdf_b64,
        "pdf_filename": pdf_filename,
    })


@app.route("/health", methods=["GET"])
def health():
    """Simple health check — verifies the container is alive and graph is loaded."""
    return jsonify({"status": "ok", "service": "rrg-brochure"})


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8101"))
    print(f"rrg-brochure starting on port {port}")
    app.run(host="0.0.0.0", port=port)
