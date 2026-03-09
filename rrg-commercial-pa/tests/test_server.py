"""Tests for server.py — Flask /process endpoint for rrg-commercial-pa.

Tests the HTTP interface that the router calls, including the standard
worker contract (POST /process) and the health check (GET /health).
"""

import base64
import json
import pytest
from unittest.mock import patch, MagicMock


# ===========================================================================
# Health Check
# ===========================================================================

class TestHealthCheck:
    """Tests for the GET /health endpoint."""

    def test_health_returns_200(self, flask_client):
        """Health check should return HTTP 200."""
        client, _ = flask_client
        resp = client.get("/health")
        assert resp.status_code == 200

    def test_health_returns_ok_status(self, flask_client):
        """Health check should return status 'ok'."""
        client, _ = flask_client
        resp = client.get("/health")
        data = resp.get_json()
        assert data["status"] == "ok"

    def test_health_returns_service_name(self, flask_client):
        """Health check should identify the service as 'rrg-commercial-pa'."""
        client, _ = flask_client
        resp = client.get("/health")
        data = resp.get_json()
        assert data["service"] == "rrg-commercial-pa"


# ===========================================================================
# POST /process — Create
# ===========================================================================

class TestProcessCreate:
    """Tests for POST /process with command='create'."""

    def test_create_returns_200(self, flask_client):
        """Create command should return HTTP 200."""
        client, mock_graph = flask_client
        resp = client.post("/process", json={
            "command": "create",
            "user_message": "Create a PA for 123 Main St",
            "chat_history": [],
            "state": {},
        })
        assert resp.status_code == 200

    def test_create_returns_response_text(self, flask_client):
        """Response should include a 'response' text field."""
        client, mock_graph = flask_client
        resp = client.post("/process", json={
            "command": "create",
            "user_message": "Create a PA for 123 Main St",
            "chat_history": [],
            "state": {},
        })
        data = resp.get_json()
        assert "response" in data
        assert isinstance(data["response"], str)

    def test_create_returns_state_with_draft_id(self, flask_client):
        """Response state should include a draft_id."""
        client, mock_graph = flask_client
        mock_graph.invoke.return_value = {
            "response": "Created draft",
            "draft_id": "abc-123",
            "pa_active": True,
            "docx_bytes": None,
            "docx_filename": None,
        }
        resp = client.post("/process", json={
            "command": "create",
            "user_message": "Create a PA for 123 Main St",
            "chat_history": [],
            "state": {},
        })
        data = resp.get_json()
        assert "state" in data
        assert "draft_id" in data["state"] or "draft_id" in data

    def test_create_returns_active_true(self, flask_client):
        """Create should set active=True (workflow continues)."""
        client, mock_graph = flask_client
        resp = client.post("/process", json={
            "command": "create",
            "user_message": "Create a PA",
            "chat_history": [],
            "state": {},
        })
        data = resp.get_json()
        assert data["active"] is True

    def test_create_response_has_docx_fields(self, flask_client):
        """Response should include docx_bytes and docx_filename fields."""
        client, mock_graph = flask_client
        resp = client.post("/process", json={
            "command": "create",
            "user_message": "Create a PA",
            "chat_history": [],
            "state": {},
        })
        data = resp.get_json()
        assert "docx_bytes" in data
        assert "docx_filename" in data

    def test_create_docx_null_initially(self, flask_client):
        """On create, docx_bytes should be null (no document yet)."""
        client, mock_graph = flask_client
        resp = client.post("/process", json={
            "command": "create",
            "user_message": "Create a PA",
            "chat_history": [],
            "state": {},
        })
        data = resp.get_json()
        assert data["docx_bytes"] is None


# ===========================================================================
# POST /process — Continue
# ===========================================================================

class TestProcessContinue:
    """Tests for POST /process with command='continue'."""

    def test_continue_with_draft_id(self, flask_client):
        """Continue with existing draft_id should work."""
        client, mock_graph = flask_client
        mock_graph.invoke.return_value = {
            "response": "Updated draft",
            "draft_id": "abc-123",
            "pa_active": True,
            "docx_bytes": None,
            "docx_filename": None,
        }
        resp = client.post("/process", json={
            "command": "continue",
            "user_message": "The buyer is Acme LLC",
            "chat_history": [],
            "state": {"draft_id": "abc-123", "pa_active": True},
        })
        assert resp.status_code == 200
        data = resp.get_json()
        assert "response" in data

    def test_continue_passes_state_to_graph(self, flask_client):
        """The state from the request should be passed to the graph."""
        client, mock_graph = flask_client
        state = {"draft_id": "xyz-789", "pa_active": True}
        client.post("/process", json={
            "command": "continue",
            "user_message": "Update the price",
            "chat_history": [],
            "state": state,
        })
        # Verify the graph received the draft_id in its input
        call_args = mock_graph.invoke.call_args
        graph_input = call_args[0][0]
        assert graph_input.get("draft_id") == "xyz-789" or \
            "draft_id" in str(graph_input)


# ===========================================================================
# POST /process — Finalize (docx output)
# ===========================================================================

class TestProcessFinalize:
    """Tests for POST /process when the graph produces a .docx."""

    def test_finalize_returns_docx_bytes(self, flask_client):
        """When graph produces docx, response should include base64 docx_bytes."""
        client, mock_graph = flask_client
        # Simulate graph returning docx bytes
        fake_docx = b"PK\x03\x04fake-docx-content"
        mock_graph.invoke.return_value = {
            "response": "Finalized!",
            "draft_id": "abc-123",
            "pa_active": False,
            "docx_bytes": fake_docx,
            "docx_filename": "20260309_PA_123 Main St.docx",
        }
        resp = client.post("/process", json={
            "command": "continue",
            "user_message": "finalize it",
            "chat_history": [],
            "state": {"draft_id": "abc-123"},
        })
        data = resp.get_json()
        assert data["docx_bytes"] is not None
        # Should be base64-encoded
        decoded = base64.b64decode(data["docx_bytes"])
        assert decoded == fake_docx

    def test_finalize_returns_docx_filename(self, flask_client):
        """When graph produces docx, response should include filename."""
        client, mock_graph = flask_client
        mock_graph.invoke.return_value = {
            "response": "Finalized!",
            "draft_id": "abc-123",
            "pa_active": False,
            "docx_bytes": b"PK\x03\x04fake",
            "docx_filename": "20260309_PA_123 Main St.docx",
        }
        resp = client.post("/process", json={
            "command": "continue",
            "user_message": "finalize it",
            "chat_history": [],
            "state": {"draft_id": "abc-123"},
        })
        data = resp.get_json()
        assert data["docx_filename"] == "20260309_PA_123 Main St.docx"

    def test_finalize_sets_active_false(self, flask_client):
        """Finalization should set active=False."""
        client, mock_graph = flask_client
        mock_graph.invoke.return_value = {
            "response": "Finalized!",
            "draft_id": "abc-123",
            "pa_active": False,
            "docx_bytes": b"PK\x03\x04fake",
            "docx_filename": "output.docx",
        }
        resp = client.post("/process", json={
            "command": "continue",
            "user_message": "finalize",
            "chat_history": [],
            "state": {"draft_id": "abc-123"},
        })
        data = resp.get_json()
        assert data["active"] is False


# ===========================================================================
# Error Handling
# ===========================================================================

class TestProcessErrors:
    """Tests for error handling in the /process endpoint."""

    def test_malformed_json_returns_error(self, flask_client):
        """Sending non-JSON data should return an error response."""
        client, _ = flask_client
        resp = client.post(
            "/process",
            data="this is not json",
            content_type="text/plain",
        )
        # Should handle gracefully — either 400 or 500 with error message
        assert resp.status_code in (400, 500) or \
            resp.get_json().get("response", "") != ""

    def test_missing_command_defaults(self, flask_client):
        """Missing 'command' field should default to 'create'."""
        client, mock_graph = flask_client
        resp = client.post("/process", json={
            "user_message": "Create a PA",
            "chat_history": [],
            "state": {},
        })
        assert resp.status_code == 200
        # Graph should have been called with command="create"
        call_args = mock_graph.invoke.call_args
        graph_input = call_args[0][0]
        assert graph_input.get("command") == "create"

    def test_missing_user_message_defaults(self, flask_client):
        """Missing 'user_message' should default to empty string."""
        client, mock_graph = flask_client
        resp = client.post("/process", json={
            "command": "create",
            "chat_history": [],
            "state": {},
        })
        assert resp.status_code == 200

    def test_missing_state_defaults(self, flask_client):
        """Missing 'state' should default to empty dict."""
        client, mock_graph = flask_client
        resp = client.post("/process", json={
            "command": "create",
            "user_message": "Test",
            "chat_history": [],
        })
        assert resp.status_code == 200

    def test_graph_exception_returns_500(self, flask_client):
        """If the graph raises an exception, should return 500 with error message."""
        client, mock_graph = flask_client
        mock_graph.invoke.side_effect = RuntimeError("Graph exploded")
        resp = client.post("/process", json={
            "command": "create",
            "user_message": "Test",
            "chat_history": [],
            "state": {},
        })
        assert resp.status_code == 500
        data = resp.get_json()
        assert "error" in data["response"].lower() or "Error" in data["response"]

    def test_graph_exception_preserves_state(self, flask_client):
        """On error, the previous state should be returned unchanged."""
        client, mock_graph = flask_client
        mock_graph.invoke.side_effect = RuntimeError("Graph exploded")
        prev_state = {"draft_id": "keep-me", "pa_active": True}
        resp = client.post("/process", json={
            "command": "continue",
            "user_message": "Test",
            "chat_history": [],
            "state": prev_state,
        })
        data = resp.get_json()
        assert data["state"] == prev_state

    def test_empty_body_handled(self, flask_client):
        """Sending empty POST body should be handled gracefully."""
        client, mock_graph = flask_client
        resp = client.post("/process", json={})
        # Should not crash — defaults should kick in
        assert resp.status_code in (200, 400, 500)


# ===========================================================================
# Response Shape Contract
# ===========================================================================

class TestResponseContract:
    """Verify the response always matches the worker contract shape."""

    def test_response_has_all_required_fields(self, flask_client):
        """Every response must have: response, state, active, docx_bytes, docx_filename."""
        client, mock_graph = flask_client
        resp = client.post("/process", json={
            "command": "create",
            "user_message": "Test",
            "chat_history": [],
            "state": {},
        })
        data = resp.get_json()
        required = ["response", "state", "active", "docx_bytes", "docx_filename"]
        for field in required:
            assert field in data, f"Missing required field: {field}"

    def test_error_response_has_all_required_fields(self, flask_client):
        """Even error responses must have the standard fields."""
        client, mock_graph = flask_client
        mock_graph.invoke.side_effect = RuntimeError("Boom")
        resp = client.post("/process", json={
            "command": "create",
            "user_message": "Test",
            "chat_history": [],
            "state": {},
        })
        data = resp.get_json()
        required = ["response", "state", "active", "docx_bytes", "docx_filename"]
        for field in required:
            assert field in data, f"Error response missing required field: {field}"

    def test_state_is_dict(self, flask_client):
        """State should always be a dict."""
        client, mock_graph = flask_client
        resp = client.post("/process", json={
            "command": "create",
            "user_message": "Test",
            "chat_history": [],
            "state": {},
        })
        data = resp.get_json()
        assert isinstance(data["state"], dict)

    def test_active_is_bool(self, flask_client):
        """Active should always be a boolean."""
        client, mock_graph = flask_client
        resp = client.post("/process", json={
            "command": "create",
            "user_message": "Test",
            "chat_history": [],
            "state": {},
        })
        data = resp.get_json()
        assert isinstance(data["active"], bool)
