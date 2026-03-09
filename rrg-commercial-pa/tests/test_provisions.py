"""Tests for provisions.py — Clause library for commercial PA additional provisions.

Tests the predefined clause library including listing, retrieval,
and variable rendering of common PA clauses.
"""

import pytest

from provisions import get_clause, list_clauses, render_clause


# ===========================================================================
# List Clauses
# ===========================================================================

class TestListClauses:
    """Tests for listing available predefined clauses."""

    def test_list_clauses_returns_list(self):
        """list_clauses should return a list."""
        clauses = list_clauses()
        assert isinstance(clauses, list)

    def test_list_clauses_not_empty(self):
        """The clause library should have at least some predefined clauses."""
        clauses = list_clauses()
        assert len(clauses) > 0

    def test_list_clauses_each_has_title(self):
        """Each predefined clause should have a title."""
        clauses = list_clauses()
        for clause in clauses:
            assert "title" in clause, f"Clause missing 'title': {clause}"
            assert isinstance(clause["title"], str)
            assert len(clause["title"]) > 0

    def test_list_clauses_each_has_body_template(self):
        """Each predefined clause should have a body template."""
        clauses = list_clauses()
        for clause in clauses:
            assert "body" in clause, f"Clause missing 'body': {clause}"
            assert isinstance(clause["body"], str)
            assert len(clause["body"]) > 0

    def test_list_clauses_contains_expected_presets(self):
        """The clause library should contain at least the clauses mentioned in the design doc."""
        clauses = list_clauses()
        titles = {c["title"].lower() for c in clauses}
        # Design doc mentions: land contract subordination, licensed agent disclosure,
        # processing fee, tax proration
        expected_substrings = [
            "land contract",
            "licensed agent",
            "processing fee",
            "tax proration",
        ]
        for expected in expected_substrings:
            found = any(expected in t for t in titles)
            assert found, f"Expected clause containing '{expected}' not found. Available: {titles}"

    def test_list_clauses_no_duplicates(self):
        """Clause titles should be unique."""
        clauses = list_clauses()
        titles = [c["title"] for c in clauses]
        assert len(titles) == len(set(titles)), f"Duplicate clause titles found: {titles}"


# ===========================================================================
# Get Clause by Name
# ===========================================================================

class TestGetClause:
    """Tests for retrieving a specific clause by name."""

    def test_get_clause_by_exact_name(self):
        """Should retrieve a clause when given its exact title."""
        clauses = list_clauses()
        if clauses:
            first_title = clauses[0]["title"]
            clause = get_clause(first_title)
            assert clause is not None
            assert clause["title"] == first_title

    def test_get_clause_returns_title_and_body(self):
        """Retrieved clause should have both title and body."""
        clauses = list_clauses()
        if clauses:
            clause = get_clause(clauses[0]["title"])
            assert "title" in clause
            assert "body" in clause

    def test_get_clause_unknown_name_returns_none(self):
        """Getting a clause with an unknown name should return None."""
        result = get_clause("Nonexistent Clause That Does Not Exist XYZ")
        assert result is None

    def test_get_clause_empty_string(self):
        """Getting a clause with an empty string should return None."""
        result = get_clause("")
        assert result is None

    def test_get_clause_body_is_nonempty(self):
        """A retrieved clause's body should not be empty."""
        clauses = list_clauses()
        for c in clauses:
            clause = get_clause(c["title"])
            assert clause is not None
            assert len(clause["body"].strip()) > 0


# ===========================================================================
# Render Clause
# ===========================================================================

class TestRenderClause:
    """Tests for rendering a clause with variable substitution."""

    def test_render_clause_basic(self):
        """Rendering a clause should fill in template variables."""
        # The body templates may use Jinja2 or .format() style placeholders.
        # This test creates a clause body with a placeholder and renders it.
        clauses = list_clauses()
        # Find a clause or use a direct test
        # For a basic test, render_clause should accept a body template + variables
        rendered = render_clause(
            "A processing fee of {{ amount }} shall be paid at closing.",
            {"amount": "$395"},
        )
        assert "$395" in rendered
        assert "{{ amount }}" not in rendered

    def test_render_clause_multiple_variables(self):
        """Rendering with multiple variables should fill all of them."""
        template = "{{ buyer_name }} agrees to pay {{ amount }} to {{ seller_name }}."
        rendered = render_clause(
            template,
            {"buyer_name": "Acme LLC", "amount": "$50,000", "seller_name": "Downtown Inc"},
        )
        assert "Acme LLC" in rendered
        assert "$50,000" in rendered
        assert "Downtown Inc" in rendered

    def test_render_clause_missing_variable_does_not_crash(self):
        """If a variable is missing, rendering should not raise an exception."""
        template = "{{ buyer_name }} agrees to the terms. Rate: {{ rate }}%."
        # Only provide one of two variables
        rendered = render_clause(template, {"buyer_name": "Acme LLC"})
        # Should not raise — missing var might be empty or kept as placeholder
        assert "Acme LLC" in rendered

    def test_render_clause_no_variables(self):
        """A clause with no template variables should be returned as-is."""
        body = "This is a static clause with no variables."
        rendered = render_clause(body, {})
        assert rendered == body

    def test_render_clause_empty_body(self):
        """Rendering an empty body should return an empty string."""
        rendered = render_clause("", {})
        assert rendered == ""

    def test_render_predefined_clause_with_variables(self):
        """Render each predefined clause to verify templates are valid."""
        clauses = list_clauses()
        for c in clauses:
            # Should not raise even with empty variables
            rendered = render_clause(c["body"], {})
            assert isinstance(rendered, str)
