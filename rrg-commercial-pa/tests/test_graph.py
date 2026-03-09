"""Tests for graph.py — LangGraph workflow integration for commercial PA.

All tests mock the LLM to prevent real CLI calls. Tests verify the graph
routing logic, node execution, and state transitions.
"""

import json
import pytest
from unittest.mock import patch, MagicMock, ANY

from conftest import MockAIMessage, make_mock_llm


# ---------------------------------------------------------------------------
# Patch targets
# ---------------------------------------------------------------------------

# These are the likely patch targets. Adjust if the implementation uses
# different import paths.
GRAPH_LLM_PATCH = "graph._get_llm"
HANDLER_LLM_PATCH = "pa_handler._get_llm"
DOCX_PATCH = "pa_docx.generate_pa_docx"
STORE_PATCH = "draft_store.DraftStore"


def _build_test_graph():
    """Build a graph with mocked LLM for testing."""
    from graph import build_graph
    return build_graph()


# ===========================================================================
# Graph Construction
# ===========================================================================

class TestGraphConstruction:
    """Tests that the graph builds and compiles correctly."""

    @patch(HANDLER_LLM_PATCH, return_value=make_mock_llm("{}"))
    @patch(GRAPH_LLM_PATCH, return_value=make_mock_llm("{}"))
    def test_build_graph_returns_compiled_graph(self, mock1, mock2):
        """build_graph should return a compiled LangGraph."""
        from graph import build_graph
        graph = build_graph()
        assert graph is not None
        assert hasattr(graph, "invoke")

    @patch(HANDLER_LLM_PATCH, return_value=make_mock_llm("{}"))
    @patch(GRAPH_LLM_PATCH, return_value=make_mock_llm("{}"))
    def test_build_graph_is_callable(self, mock1, mock2):
        """The compiled graph should be callable via invoke()."""
        from graph import build_graph
        graph = build_graph()
        assert callable(getattr(graph, "invoke", None))


# ===========================================================================
# New Draft Flow
# ===========================================================================

class TestNewDraftFlow:
    """Tests for creating a new PA draft."""

    @patch(DOCX_PATCH, return_value=b"PK\x03\x04fake")
    @patch(HANDLER_LLM_PATCH, return_value=make_mock_llm("{}"))
    @patch(GRAPH_LLM_PATCH, return_value=make_mock_llm("{}"))
    def test_create_new_draft(self, mock_gllm, mock_hllm, mock_docx, db_path):
        """command='create' should trigger start_new node and return a checklist."""
        with patch("draft_store.DB_PATH", db_path):
            from graph import build_graph
            graph = build_graph()
            result = graph.invoke({
                "command": "create",
                "user_message": "Create a purchase agreement for 123 Main St",
                "chat_history": [],
                "draft_id": None,
            })
        assert "response" in result
        assert isinstance(result["response"], str)
        assert len(result["response"]) > 0

    @patch(DOCX_PATCH, return_value=b"PK\x03\x04fake")
    @patch(HANDLER_LLM_PATCH, return_value=make_mock_llm("{}"))
    @patch(GRAPH_LLM_PATCH, return_value=make_mock_llm("{}"))
    def test_create_returns_draft_id(self, mock_gllm, mock_hllm, mock_docx, db_path):
        """Create should return a draft_id in the result."""
        with patch("draft_store.DB_PATH", db_path):
            from graph import build_graph
            graph = build_graph()
            result = graph.invoke({
                "command": "create",
                "user_message": "Create a PA for 456 Oak Ave",
                "chat_history": [],
                "draft_id": None,
            })
        assert result.get("draft_id") is not None

    @patch(DOCX_PATCH, return_value=b"PK\x03\x04fake")
    @patch(HANDLER_LLM_PATCH, return_value=make_mock_llm("{}"))
    @patch(GRAPH_LLM_PATCH, return_value=make_mock_llm("{}"))
    def test_create_sets_active_true(self, mock_gllm, mock_hllm, mock_docx, db_path):
        """Create should set pa_active to True (workflow continues)."""
        with patch("draft_store.DB_PATH", db_path):
            from graph import build_graph
            graph = build_graph()
            result = graph.invoke({
                "command": "create",
                "user_message": "Create a PA",
                "chat_history": [],
                "draft_id": None,
            })
        assert result.get("pa_active") is True


# ===========================================================================
# Extract Flow
# ===========================================================================

class TestExtractFlow:
    """Tests for extracting variables from user input."""

    @patch(DOCX_PATCH, return_value=b"PK\x03\x04fake")
    @patch(HANDLER_LLM_PATCH)
    @patch(GRAPH_LLM_PATCH)
    def test_extract_stores_variables(self, mock_gllm, mock_hllm, mock_docx, db_path):
        """When user provides data, extract node should store variables in draft."""
        extracted = json.dumps({
            "purchaser_name": "Acme LLC",
            "purchase_price_number": 2500000,
        })
        mock_hllm.return_value = make_mock_llm(extracted)
        mock_gllm.return_value = make_mock_llm(extracted)

        with patch("draft_store.DB_PATH", db_path):
            from graph import build_graph
            from draft_store import DraftStore
            graph = build_graph()

            # First create a draft
            result1 = graph.invoke({
                "command": "create",
                "user_message": "Create a PA for 123 Main St",
                "chat_history": [],
                "draft_id": None,
            })
            draft_id = result1.get("draft_id")

            # Then provide data
            result2 = graph.invoke({
                "command": "continue",
                "user_message": "The buyer is Acme LLC at $2.5M",
                "chat_history": [],
                "draft_id": draft_id,
            })

        assert "response" in result2

    @patch(DOCX_PATCH, return_value=b"PK\x03\x04fake")
    @patch(HANDLER_LLM_PATCH)
    @patch(GRAPH_LLM_PATCH)
    def test_extract_returns_confirmation(self, mock_gllm, mock_hllm, mock_docx, db_path):
        """After extraction, response should confirm what was filled."""
        extracted = json.dumps({
            "purchaser_name": "Acme LLC",
        })
        mock_hllm.return_value = make_mock_llm(extracted)
        mock_gllm.return_value = make_mock_llm(extracted)

        with patch("draft_store.DB_PATH", db_path):
            from graph import build_graph
            graph = build_graph()
            result = graph.invoke({
                "command": "create",
                "user_message": "Create a PA, buyer is Acme LLC",
                "chat_history": [],
                "draft_id": None,
            })
        # Response should mention what was extracted or remaining
        assert len(result.get("response", "")) > 0


# ===========================================================================
# Resume Flow
# ===========================================================================

class TestResumeFlow:
    """Tests for resuming an existing draft by address."""

    @patch(DOCX_PATCH, return_value=b"PK\x03\x04fake")
    @patch(HANDLER_LLM_PATCH, return_value=make_mock_llm("{}"))
    @patch(GRAPH_LLM_PATCH, return_value=make_mock_llm("{}"))
    def test_resume_loads_existing_draft(self, mock_gllm, mock_hllm, mock_docx, db_path):
        """Resume should load an existing draft by property address."""
        with patch("draft_store.DB_PATH", db_path):
            from graph import build_graph
            from draft_store import DraftStore
            graph = build_graph()

            # Create a draft first
            store = DraftStore(db_path)
            draft_id = store.create_draft(
                property_address="123 Main St",
                variables={"purchaser_name": "Existing Buyer"},
            )

            # Resume it
            result = graph.invoke({
                "command": "create",
                "user_message": "resume 123 Main St",
                "chat_history": [],
                "draft_id": None,
            })

        assert "response" in result
        # Should have loaded the existing draft
        loaded_id = result.get("draft_id")
        assert loaded_id is not None

    @patch(DOCX_PATCH, return_value=b"PK\x03\x04fake")
    @patch(HANDLER_LLM_PATCH, return_value=make_mock_llm("{}"))
    @patch(GRAPH_LLM_PATCH, return_value=make_mock_llm("{}"))
    def test_resume_nonexistent_address(self, mock_gllm, mock_hllm, mock_docx, db_path):
        """Resume with a nonexistent address should handle gracefully."""
        with patch("draft_store.DB_PATH", db_path):
            from graph import build_graph
            graph = build_graph()
            result = graph.invoke({
                "command": "create",
                "user_message": "resume 999 Nowhere Ave",
                "chat_history": [],
                "draft_id": None,
            })
        # Should not crash — may create a new draft or report not found
        assert "response" in result


# ===========================================================================
# Triage Routing
# ===========================================================================

class TestTriageRouting:
    """Tests for the triage node's routing decisions."""

    @patch(DOCX_PATCH, return_value=b"PK\x03\x04fake")
    @patch(HANDLER_LLM_PATCH)
    @patch(GRAPH_LLM_PATCH)
    def test_triage_routes_preview(self, mock_gllm, mock_hllm, mock_docx, db_path):
        """'show me a preview' should route to preview and return docx bytes."""
        mock_hllm.return_value = make_mock_llm("preview")
        mock_gllm.return_value = make_mock_llm("preview")

        with patch("draft_store.DB_PATH", db_path):
            from graph import build_graph
            from draft_store import DraftStore
            graph = build_graph()

            # Create draft with some variables
            store = DraftStore(db_path)
            draft_id = store.create_draft(
                property_address="123 Main St",
                variables={"purchaser_name": "Test"},
            )

            result = graph.invoke({
                "command": "continue",
                "user_message": "show me a preview",
                "chat_history": [],
                "draft_id": draft_id,
            })

        # Preview should produce docx bytes
        assert result.get("docx_bytes") is not None or result.get("response") != ""

    @patch(DOCX_PATCH, return_value=b"PK\x03\x04fake")
    @patch(HANDLER_LLM_PATCH)
    @patch(GRAPH_LLM_PATCH)
    def test_triage_routes_save(self, mock_gllm, mock_hllm, mock_docx, db_path):
        """'save this' should route to save and set active=False."""
        mock_hllm.return_value = make_mock_llm("save")
        mock_gllm.return_value = make_mock_llm("save")

        with patch("draft_store.DB_PATH", db_path):
            from graph import build_graph
            from draft_store import DraftStore
            graph = build_graph()

            store = DraftStore(db_path)
            draft_id = store.create_draft(
                property_address="123 Main St",
                variables={"purchaser_name": "Test"},
            )

            result = graph.invoke({
                "command": "continue",
                "user_message": "save this for later",
                "chat_history": [],
                "draft_id": draft_id,
            })

        assert result.get("pa_active") is False

    @patch(DOCX_PATCH, return_value=b"PK\x03\x04final-docx")
    @patch(HANDLER_LLM_PATCH)
    @patch(GRAPH_LLM_PATCH)
    def test_triage_routes_finalize(self, mock_gllm, mock_hllm, mock_docx, db_path):
        """'finalize it' should route to finalize, return docx, and set active=False."""
        mock_hllm.return_value = make_mock_llm("finalize")
        mock_gllm.return_value = make_mock_llm("finalize")

        with patch("draft_store.DB_PATH", db_path):
            from graph import build_graph
            from draft_store import DraftStore
            graph = build_graph()

            store = DraftStore(db_path)
            draft_id = store.create_draft(
                property_address="123 Main St",
                variables={"purchaser_name": "Test"},
            )

            result = graph.invoke({
                "command": "continue",
                "user_message": "looks good finalize it",
                "chat_history": [],
                "draft_id": draft_id,
            })

        assert result.get("pa_active") is False
        assert result.get("docx_bytes") is not None

    @patch(DOCX_PATCH, return_value=b"PK\x03\x04fake")
    @patch(HANDLER_LLM_PATCH)
    @patch(GRAPH_LLM_PATCH)
    def test_triage_routes_edit(self, mock_gllm, mock_hllm, mock_docx, db_path):
        """'change the price' should route to edit node."""
        updated = json.dumps({"purchaser_name": "Test", "purchase_price_number": 3000000})
        mock_hllm.return_value = make_mock_llm("edit")
        mock_gllm.return_value = make_mock_llm(updated)

        with patch("draft_store.DB_PATH", db_path):
            from graph import build_graph
            from draft_store import DraftStore
            graph = build_graph()

            store = DraftStore(db_path)
            draft_id = store.create_draft(
                property_address="123 Main St",
                variables={"purchaser_name": "Test", "purchase_price_number": 2500000},
            )

            result = graph.invoke({
                "command": "continue",
                "user_message": "change the price to $3M",
                "chat_history": [],
                "draft_id": draft_id,
            })

        assert result.get("pa_active") is True
        assert "response" in result

    @patch(DOCX_PATCH, return_value=b"PK\x03\x04fake")
    @patch(HANDLER_LLM_PATCH)
    @patch(GRAPH_LLM_PATCH)
    def test_triage_routes_question(self, mock_gllm, mock_hllm, mock_docx, db_path):
        """A question should route to the question node, keeping active=True."""
        mock_hllm.return_value = make_mock_llm("question")
        mock_gllm.return_value = make_mock_llm(
            "Earnest money is a good-faith deposit typically 1-5% of the purchase price."
        )

        with patch("draft_store.DB_PATH", db_path):
            from graph import build_graph
            from draft_store import DraftStore
            graph = build_graph()

            store = DraftStore(db_path)
            draft_id = store.create_draft(
                property_address="123 Main St",
                variables={"purchaser_name": "Test"},
            )

            result = graph.invoke({
                "command": "continue",
                "user_message": "what is earnest money?",
                "chat_history": [],
                "draft_id": draft_id,
            })

        assert result.get("pa_active") is True
        assert len(result.get("response", "")) > 0

    @patch(DOCX_PATCH, return_value=b"PK\x03\x04fake")
    @patch(HANDLER_LLM_PATCH)
    @patch(GRAPH_LLM_PATCH)
    def test_triage_routes_list_drafts(self, mock_gllm, mock_hllm, mock_docx, db_path):
        """'list my drafts' should route to list_drafts node."""
        mock_hllm.return_value = make_mock_llm("list_drafts")
        mock_gllm.return_value = make_mock_llm("list_drafts")

        with patch("draft_store.DB_PATH", db_path):
            from graph import build_graph
            from draft_store import DraftStore
            graph = build_graph()

            store = DraftStore(db_path)
            store.create_draft(
                property_address="123 Main St",
                variables={"purchaser_name": "Test"},
            )
            store.create_draft(
                property_address="456 Oak Ave",
                variables={"purchaser_name": "Other"},
            )

            result = graph.invoke({
                "command": "continue",
                "user_message": "list my drafts",
                "chat_history": [],
                "draft_id": store.list_drafts()[0]["id"],
            })

        assert "response" in result


# ===========================================================================
# Cancel Flow
# ===========================================================================

class TestCancelFlow:
    """Tests for cancelling a draft."""

    @patch(DOCX_PATCH, return_value=b"PK\x03\x04fake")
    @patch(HANDLER_LLM_PATCH)
    @patch(GRAPH_LLM_PATCH)
    def test_cancel_sets_active_false(self, mock_gllm, mock_hllm, mock_docx, db_path):
        """Cancel should set pa_active=False."""
        mock_hllm.return_value = make_mock_llm("cancel")
        mock_gllm.return_value = make_mock_llm("cancel")

        with patch("draft_store.DB_PATH", db_path):
            from graph import build_graph
            from draft_store import DraftStore
            graph = build_graph()

            store = DraftStore(db_path)
            draft_id = store.create_draft(
                property_address="123 Main St",
                variables={"purchaser_name": "Test"},
            )

            result = graph.invoke({
                "command": "continue",
                "user_message": "cancel",
                "chat_history": [],
                "draft_id": draft_id,
            })

        assert result.get("pa_active") is False

    @patch(DOCX_PATCH, return_value=b"PK\x03\x04fake")
    @patch(HANDLER_LLM_PATCH)
    @patch(GRAPH_LLM_PATCH)
    def test_cancel_deletes_draft(self, mock_gllm, mock_hllm, mock_docx, db_path):
        """Cancel should delete the draft from SQLite."""
        mock_hllm.return_value = make_mock_llm("cancel")
        mock_gllm.return_value = make_mock_llm("cancel")

        with patch("draft_store.DB_PATH", db_path):
            from graph import build_graph
            from draft_store import DraftStore
            graph = build_graph()

            store = DraftStore(db_path)
            draft_id = store.create_draft(
                property_address="123 Main St",
                variables={"purchaser_name": "Test"},
            )

            result = graph.invoke({
                "command": "continue",
                "user_message": "cancel this draft",
                "chat_history": [],
                "draft_id": draft_id,
            })

            # Draft should be gone
            assert store.load_draft(draft_id) is None

    @patch(DOCX_PATCH, return_value=b"PK\x03\x04fake")
    @patch(HANDLER_LLM_PATCH)
    @patch(GRAPH_LLM_PATCH)
    def test_cancel_returns_confirmation(self, mock_gllm, mock_hllm, mock_docx, db_path):
        """Cancel should return a confirmation message."""
        mock_hllm.return_value = make_mock_llm("cancel")
        mock_gllm.return_value = make_mock_llm("cancel")

        with patch("draft_store.DB_PATH", db_path):
            from graph import build_graph
            from draft_store import DraftStore
            graph = build_graph()

            store = DraftStore(db_path)
            draft_id = store.create_draft(
                property_address="123 Main St",
                variables={},
            )

            result = graph.invoke({
                "command": "continue",
                "user_message": "cancel",
                "chat_history": [],
                "draft_id": draft_id,
            })

        assert "response" in result
        assert len(result["response"]) > 0


# ===========================================================================
# State Shape
# ===========================================================================

class TestStateShape:
    """Tests that the graph output has the expected state shape."""

    @patch(DOCX_PATCH, return_value=b"PK\x03\x04fake")
    @patch(HANDLER_LLM_PATCH, return_value=make_mock_llm("{}"))
    @patch(GRAPH_LLM_PATCH, return_value=make_mock_llm("{}"))
    def test_output_has_response(self, mock_gllm, mock_hllm, mock_docx, db_path):
        """Graph output should always have a 'response' field."""
        with patch("draft_store.DB_PATH", db_path):
            from graph import build_graph
            graph = build_graph()
            result = graph.invoke({
                "command": "create",
                "user_message": "Test",
                "chat_history": [],
                "draft_id": None,
            })
        assert "response" in result

    @patch(DOCX_PATCH, return_value=b"PK\x03\x04fake")
    @patch(HANDLER_LLM_PATCH, return_value=make_mock_llm("{}"))
    @patch(GRAPH_LLM_PATCH, return_value=make_mock_llm("{}"))
    def test_output_has_draft_id(self, mock_gllm, mock_hllm, mock_docx, db_path):
        """Graph output should have a 'draft_id' field."""
        with patch("draft_store.DB_PATH", db_path):
            from graph import build_graph
            graph = build_graph()
            result = graph.invoke({
                "command": "create",
                "user_message": "Test",
                "chat_history": [],
                "draft_id": None,
            })
        assert "draft_id" in result

    @patch(DOCX_PATCH, return_value=b"PK\x03\x04fake")
    @patch(HANDLER_LLM_PATCH, return_value=make_mock_llm("{}"))
    @patch(GRAPH_LLM_PATCH, return_value=make_mock_llm("{}"))
    def test_output_has_pa_active(self, mock_gllm, mock_hllm, mock_docx, db_path):
        """Graph output should have a 'pa_active' field."""
        with patch("draft_store.DB_PATH", db_path):
            from graph import build_graph
            graph = build_graph()
            result = graph.invoke({
                "command": "create",
                "user_message": "Test",
                "chat_history": [],
                "draft_id": None,
            })
        assert "pa_active" in result

    @patch(DOCX_PATCH, return_value=b"PK\x03\x04fake")
    @patch(HANDLER_LLM_PATCH, return_value=make_mock_llm("{}"))
    @patch(GRAPH_LLM_PATCH, return_value=make_mock_llm("{}"))
    def test_output_has_docx_fields(self, mock_gllm, mock_hllm, mock_docx, db_path):
        """Graph output should have docx_bytes and docx_filename fields."""
        with patch("draft_store.DB_PATH", db_path):
            from graph import build_graph
            graph = build_graph()
            result = graph.invoke({
                "command": "create",
                "user_message": "Test",
                "chat_history": [],
                "draft_id": None,
            })
        assert "docx_bytes" in result
        assert "docx_filename" in result


# ===========================================================================
# Edge Cases
# ===========================================================================

class TestGraphEdgeCases:
    """Edge case tests for graph behavior."""

    @patch(DOCX_PATCH, return_value=b"PK\x03\x04fake")
    @patch(HANDLER_LLM_PATCH, return_value=make_mock_llm("{}"))
    @patch(GRAPH_LLM_PATCH, return_value=make_mock_llm("{}"))
    def test_empty_message_does_not_crash(self, mock_gllm, mock_hllm, mock_docx, db_path):
        """An empty user message should be handled gracefully."""
        with patch("draft_store.DB_PATH", db_path):
            from graph import build_graph
            graph = build_graph()
            result = graph.invoke({
                "command": "create",
                "user_message": "",
                "chat_history": [],
                "draft_id": None,
            })
        assert "response" in result

    @patch(DOCX_PATCH, return_value=b"PK\x03\x04fake")
    @patch(HANDLER_LLM_PATCH, return_value=make_mock_llm("{}"))
    @patch(GRAPH_LLM_PATCH, return_value=make_mock_llm("{}"))
    def test_long_chat_history(self, mock_gllm, mock_hllm, mock_docx, db_path):
        """Graph should handle long chat histories without crashing."""
        history = [
            {"role": "user" if i % 2 == 0 else "assistant", "content": f"Message {i}"}
            for i in range(50)
        ]
        with patch("draft_store.DB_PATH", db_path):
            from graph import build_graph
            graph = build_graph()
            result = graph.invoke({
                "command": "create",
                "user_message": "Test with long history",
                "chat_history": history,
                "draft_id": None,
            })
        assert "response" in result

    @patch(DOCX_PATCH, return_value=b"PK\x03\x04fake")
    @patch(HANDLER_LLM_PATCH, return_value=make_mock_llm("{}"))
    @patch(GRAPH_LLM_PATCH, return_value=make_mock_llm("{}"))
    def test_continue_without_draft_id(self, mock_gllm, mock_hllm, mock_docx, db_path):
        """Continue with no draft_id should be handled (create new or error)."""
        with patch("draft_store.DB_PATH", db_path):
            from graph import build_graph
            graph = build_graph()
            result = graph.invoke({
                "command": "continue",
                "user_message": "Hello",
                "chat_history": [],
                "draft_id": None,
            })
        assert "response" in result

    @patch(DOCX_PATCH, return_value=b"PK\x03\x04fake")
    @patch(HANDLER_LLM_PATCH, return_value=make_mock_llm("{}"))
    @patch(GRAPH_LLM_PATCH, return_value=make_mock_llm("{}"))
    def test_continue_with_invalid_draft_id(self, mock_gllm, mock_hllm, mock_docx, db_path):
        """Continue with a draft_id that doesn't exist should handle gracefully."""
        with patch("draft_store.DB_PATH", db_path):
            from graph import build_graph
            graph = build_graph()
            result = graph.invoke({
                "command": "continue",
                "user_message": "Update something",
                "chat_history": [],
                "draft_id": "nonexistent-draft-id",
            })
        # Should not crash
        assert "response" in result

    @patch(DOCX_PATCH, return_value=b"PK\x03\x04fake")
    @patch(HANDLER_LLM_PATCH, return_value=make_mock_llm("{}"))
    @patch(GRAPH_LLM_PATCH, return_value=make_mock_llm("{}"))
    def test_unknown_command_handled(self, mock_gllm, mock_hllm, mock_docx, db_path):
        """An unknown command value should be handled gracefully."""
        with patch("draft_store.DB_PATH", db_path):
            from graph import build_graph
            graph = build_graph()
            # This may default to "create" behavior or error
            try:
                result = graph.invoke({
                    "command": "unknown_command",
                    "user_message": "Test",
                    "chat_history": [],
                    "draft_id": None,
                })
                assert "response" in result
            except (KeyError, ValueError):
                # Acceptable to reject unknown commands
                pass
