"""RRG Router — Streamlit chat UI with worker node orchestration."""

import streamlit as st
from graph import build_graph
from node_client import WorkerNodeClient
from windmill_client import WindmillClient
from signal_client import SignalClient
from config import (
    WORKER_URLS, USE_WINDMILL, WINDMILL_BASE_URL,
    WINDMILL_TOKEN, WINDMILL_WORKSPACE,
)

st.set_page_config(page_title="RRG Assistant", page_icon="R", layout="wide")
st.title("RRG Assistant")

# ---------------------------------------------------------------------------
# Session State Initialization
# ---------------------------------------------------------------------------

if "messages" not in st.session_state:
    st.session_state.messages = []

if "active_node" not in st.session_state:
    st.session_state.active_node = None  # "pnl" | "brochure" | None

if "worker_state" not in st.session_state:
    st.session_state.worker_state = {}

if "debug_data" not in st.session_state:
    st.session_state.debug_data = {}

if "pending_action" not in st.session_state:
    st.session_state.pending_action = None


# ---------------------------------------------------------------------------
# Load Graph and Client (Cached — survives Streamlit reruns)
# ---------------------------------------------------------------------------

@st.cache_resource
def get_graph():
    return build_graph()


@st.cache_resource
def get_client():
    if USE_WINDMILL and WINDMILL_TOKEN:
        return WindmillClient(WINDMILL_BASE_URL, WINDMILL_TOKEN, WINDMILL_WORKSPACE)
    return WorkerNodeClient(WORKER_URLS)


@st.cache_resource
def get_signal_client():
    if USE_WINDMILL and WINDMILL_TOKEN:
        return SignalClient(WINDMILL_BASE_URL, WINDMILL_TOKEN, WINDMILL_WORKSPACE)
    return None


graph = get_graph()
client = get_client()
signal_client = get_signal_client()


# ---------------------------------------------------------------------------
# Chat UI
# ---------------------------------------------------------------------------

chat_tab, signals_tab, debug_tab = st.tabs(["Chat", "Signals", "Debug"])

with chat_tab:
    # Display existing messages
    for idx, msg in enumerate(st.session_state.messages):
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])
            file_data = msg.get("pdf_bytes") or msg.get("docx_bytes")
            file_name = msg.get("pdf_filename") or msg.get("docx_filename") or "output"
            if file_data:
                mime = "application/vnd.openxmlformats-officedocument.wordprocessingml.document" if file_name.endswith(".docx") else "application/pdf"
                st.download_button(
                    label="Download Preview",
                    data=file_data,
                    file_name=file_name,
                    mime=mime,
                    key=f"file_{idx}",
                )


# Chat input at module level — pins to bottom of viewport across all tabs
prompt = st.chat_input("What can I help with?")

# Handle pending actions (e.g., preview button click)
if not prompt and st.session_state.pending_action:
    prompt = st.session_state.pending_action
    st.session_state.pending_action = None

with chat_tab:
    if prompt:
        # Show user message
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        # Build chat history (last 20 messages for context)
        history = [
            {"role": m["role"], "content": m["content"]}
            for m in st.session_state.messages[-20:]
        ]

        with st.chat_message("assistant"):
            with st.spinner("Thinking..."):
                active_node = st.session_state.active_node

                if active_node:
                    # Active worker — skip classification, forward directly
                    response_data = client.call_worker(
                        handler_name=active_node,
                        command="continue",
                        user_message=prompt,
                        chat_history=history,
                        state=st.session_state.worker_state,
                    )
                    st.session_state.debug_data = {
                        "mode": "active_node_forwarding",
                        "active_node": active_node,
                        "command": "continue",
                    }
                else:
                    # No active worker — classify intent
                    result = graph.invoke({
                        "user_message": prompt,
                        "chat_history": history,
                    })

                    st.session_state.debug_data = {
                        "mode": "classification",
                        "intent": result.get("intent"),
                        "route_type": result.get("route_type"),
                        "handler_name": result.get("handler_name"),
                    }

                    if result.get("route_type") == "handler":
                        # Start new worker
                        handler_name = result["handler_name"]
                        response_data = client.call_worker(
                            handler_name=handler_name,
                            command="create",
                            user_message=prompt,
                            chat_history=history,
                            state={},
                        )
                        # Only set active_node if worker accepted (no error)
                        if not response_data.get("error"):
                            st.session_state.active_node = handler_name
                    elif result.get("route_type") == "chat":
                        response_data = {
                            "response": result.get("response", ""),
                            "state": {},
                            "active": False,
                            "pdf_bytes": None,
                            "pdf_filename": None,
                            "error": None,
                        }
                    else:
                        response_data = {
                            "response": "Sorry, I couldn't understand that. Try asking for help!",
                            "state": {},
                            "active": False,
                            "pdf_bytes": None,
                            "pdf_filename": None,
                            "error": "unknown_route_type",
                        }

            # Display response
            st.markdown(response_data["response"])

            # Handle file output (PDF or DOCX)
            file_bytes = response_data.get("pdf_bytes") or response_data.get("docx_bytes")
            file_name = response_data.get("pdf_filename") or response_data.get("docx_filename") or "output"
            if file_bytes:
                mime = "application/vnd.openxmlformats-officedocument.wordprocessingml.document" if file_name.endswith(".docx") else "application/pdf"
                st.download_button(
                    label="Download Preview",
                    data=file_bytes,
                    file_name=file_name,
                    mime=mime,
                )


        # Update session state from worker response
        st.session_state.worker_state = response_data.get("state", {})

        if not response_data.get("active", False):
            # Worker released control — clear active node
            st.session_state.active_node = None
            st.session_state.worker_state = {}

        # Save assistant message to history
        msg_entry = {"role": "assistant", "content": response_data["response"]}
        if response_data.get("pdf_bytes"):
            msg_entry["pdf_bytes"] = response_data["pdf_bytes"]
            msg_entry["pdf_filename"] = response_data.get("pdf_filename", "output.pdf")
        if response_data.get("docx_bytes"):
            msg_entry["docx_bytes"] = response_data["docx_bytes"]
            msg_entry["docx_filename"] = response_data.get("docx_filename", "output.docx")
        st.session_state.messages.append(msg_entry)

# Generate Preview button — rendered AFTER all messages (history + new response)
with chat_tab:
    if (
        st.session_state.active_node in ("commercial_pa", "pnl", "brochure")
        and st.session_state.messages
        and not (st.session_state.messages[-1].get("pdf_bytes") or st.session_state.messages[-1].get("docx_bytes"))
    ):
        if st.button("Generate Preview", key="gen_preview_bottom"):
            st.session_state.pending_action = "preview"
            st.rerun()


with signals_tab:
    st.subheader("Action Items")

    if signal_client is None:
        st.info("Signal queue requires Windmill. Enable USE_WINDMILL to see signals.")
    else:
        if st.button("Refresh", key="refresh_signals"):
            pass  # Button click triggers Streamlit rerun

        signals = signal_client.get_pending_signals()

        if not signals:
            st.success("No pending action items.")
        else:
            st.caption(f"{len(signals)} pending signal(s)")

            for sig in signals:
                with st.expander(
                    f"[{sig['signal_type']}] {sig['summary']}",
                    expanded=True,
                ):
                    col_meta, col_actions = st.columns([3, 1])

                    with col_meta:
                        st.caption(
                            f"From: {sig['source_flow']} | "
                            f"Created: {sig['created_at']}"
                        )
                        if sig.get("detail") and sig["detail"] != {}:
                            st.json(sig["detail"])

                    with col_actions:
                        actions = sig.get("actions") or []
                        for act in actions:
                            # actions can be strings or dicts
                            if isinstance(act, str):
                                act_action = act.lower().replace(" ", "_")
                                act_label = act
                            else:
                                act_action = act["action"]
                                act_label = act["label"]
                            btn_key = f"sig_{sig['id']}_{act_action}"
                            if st.button(act_label, key=btn_key):
                                # Mark signal as acted
                                result = signal_client.act_on_signal(
                                    sig["id"], act_action
                                )
                                # Resume suspended flow if URL present
                                if sig.get("resume_url"):
                                    signal_client.resume_flow(
                                        sig["resume_url"],
                                        {"action": act_action},
                                    )
                                st.success(f"Done: {act_label}")
                                st.rerun()

                        if not actions:
                            btn_key = f"sig_{sig['id']}_dismiss"
                            if st.button("Dismiss", key=btn_key):
                                signal_client.act_on_signal(
                                    sig["id"], "dismiss"
                                )
                                st.rerun()


with debug_tab:
    st.subheader("Debug Panel")

    st.write("**Last Request:**")
    st.json(st.session_state.debug_data)

    st.write("**Session State:**")
    st.json({
        "active_node": st.session_state.active_node,
        "worker_state_keys": list(st.session_state.worker_state.keys()),
        "message_count": len(st.session_state.messages),
    })

    st.write("**Routing Mode:**")
    if USE_WINDMILL and WINDMILL_TOKEN:
        st.json({"mode": "windmill", "base_url": WINDMILL_BASE_URL, "workspace": WINDMILL_WORKSPACE})
    else:
        st.json({"mode": "direct", "worker_urls": WORKER_URLS})
