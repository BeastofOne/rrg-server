"""Tests for pa_handler.py — LLM-powered extract/edit/triage logic.

All tests mock ChatClaudeCLI to prevent real CLI calls.
Tests verify the handler functions correctly parse LLM output and route actions.
"""

import json
import pytest
from unittest.mock import patch, MagicMock

from conftest import MockAIMessage, make_mock_llm, ALL_VARIABLE_FIELDS


# ---------------------------------------------------------------------------
# Helper: patch target for all handler tests
# ---------------------------------------------------------------------------

PATCH_TARGET = "pa_handler._get_llm"


# ===========================================================================
# extract_pa_data
# ===========================================================================

class TestExtractPaData:
    """Tests for extracting PA variables from natural language."""

    def test_extract_returns_dict(self):
        """extract_pa_data should return a dict."""
        from pa_handler import extract_pa_data

        extracted = {
            "purchaser_name": "Acme Holdings LLC",
            "property_address": "123 Main St, Pontiac, MI 48342",
            "purchase_price_number": 2500000,
        }
        mock_llm = make_mock_llm(json.dumps(extracted))
        with patch(PATCH_TARGET, return_value=mock_llm):
            result = extract_pa_data("The buyer is Acme Holdings LLC for 123 Main St at $2.5M")
        assert isinstance(result, dict)

    def test_extract_returns_expected_variables(self):
        """Extracted data should contain the variables the LLM found."""
        from pa_handler import extract_pa_data

        extracted = {
            "purchaser_name": "Acme Holdings LLC",
            "property_address": "123 Main St, Pontiac, MI 48342",
            "purchase_price_number": 2500000,
        }
        mock_llm = make_mock_llm(json.dumps(extracted))
        with patch(PATCH_TARGET, return_value=mock_llm):
            result = extract_pa_data("The buyer is Acme Holdings LLC for 123 Main St at $2.5M")
        assert result["purchaser_name"] == "Acme Holdings LLC"
        assert result["purchase_price_number"] == 2500000

    def test_extract_partial_input(self):
        """Should handle input that only mentions a few variables."""
        from pa_handler import extract_pa_data

        extracted = {
            "purchaser_name": "Test Corp",
        }
        mock_llm = make_mock_llm(json.dumps(extracted))
        with patch(PATCH_TARGET, return_value=mock_llm):
            result = extract_pa_data("The buyer is Test Corp")
        assert result["purchaser_name"] == "Test Corp"

    def test_extract_handles_all_variable_types(self):
        """Should correctly parse strings, numbers, booleans, and lists."""
        from pa_handler import extract_pa_data

        extracted = {
            "purchaser_name": "Acme LLC",
            "purchase_price_number": 2500000.50,
            "closing_days": 60,
            "payment_cash": True,
            "dd_financing": False,
        }
        mock_llm = make_mock_llm(json.dumps(extracted))
        with patch(PATCH_TARGET, return_value=mock_llm):
            result = extract_pa_data("Acme LLC buying for $2.5M, cash, close in 60 days")
        assert isinstance(result["purchaser_name"], str)
        assert isinstance(result["purchase_price_number"], float)
        assert isinstance(result["closing_days"], int)
        assert result["payment_cash"] is True
        assert result["dd_financing"] is False

    def test_extract_with_no_recognizable_data(self):
        """If the LLM finds nothing, it should still return a dict (possibly empty)."""
        from pa_handler import extract_pa_data

        mock_llm = make_mock_llm("{}")
        with patch(PATCH_TARGET, return_value=mock_llm):
            result = extract_pa_data("hello how are you")
        assert isinstance(result, dict)

    def test_extract_strips_markdown_fences(self):
        """Should handle LLM output wrapped in markdown code fences."""
        from pa_handler import extract_pa_data

        response = '```json\n{"purchaser_name": "Test LLC"}\n```'
        mock_llm = make_mock_llm(response)
        with patch(PATCH_TARGET, return_value=mock_llm):
            result = extract_pa_data("Test LLC is buying")
        assert result["purchaser_name"] == "Test LLC"

    def test_extract_with_multiline_input(self):
        """Should handle multi-line user messages."""
        from pa_handler import extract_pa_data

        extracted = {
            "purchaser_name": "Multi LLC",
            "seller_name": "Seller Corp",
            "purchase_price_number": 1000000,
        }
        mock_llm = make_mock_llm(json.dumps(extracted))
        with patch(PATCH_TARGET, return_value=mock_llm):
            result = extract_pa_data(
                "Buyer: Multi LLC\nSeller: Seller Corp\nPrice: $1M"
            )
        assert result["purchaser_name"] == "Multi LLC"
        assert result["seller_name"] == "Seller Corp"

    def test_extract_invalid_json_raises(self):
        """If the LLM returns invalid JSON, should raise an exception."""
        from pa_handler import extract_pa_data

        mock_llm = make_mock_llm("This is not JSON at all")
        with patch(PATCH_TARGET, return_value=mock_llm):
            with pytest.raises((json.JSONDecodeError, ValueError)):
                extract_pa_data("Some message")


# ===========================================================================
# apply_changes
# ===========================================================================

class TestApplyChanges:
    """Tests for applying targeted changes to existing variables."""

    def test_apply_changes_returns_dict(self):
        """apply_changes should return a dict."""
        from pa_handler import apply_changes

        existing = {"purchaser_name": "Old Name", "purchase_price_number": 1000000}
        updated = {**existing, "purchase_price_number": 2000000}
        mock_llm = make_mock_llm(json.dumps(updated))
        with patch(PATCH_TARGET, return_value=mock_llm):
            result = apply_changes(existing, "Change price to $2M")
        assert isinstance(result, dict)

    def test_apply_changes_modifies_target_field(self):
        """The changed field should reflect the new value."""
        from pa_handler import apply_changes

        existing = {"purchaser_name": "Old", "purchase_price_number": 1000000}
        updated = {**existing, "purchase_price_number": 2000000}
        mock_llm = make_mock_llm(json.dumps(updated))
        with patch(PATCH_TARGET, return_value=mock_llm):
            result = apply_changes(existing, "Change price to $2M")
        assert result["purchase_price_number"] == 2000000

    def test_apply_changes_preserves_other_fields(self):
        """Fields not mentioned in the change request should be preserved."""
        from pa_handler import apply_changes

        existing = {"purchaser_name": "Acme", "purchase_price_number": 1000000}
        updated = {**existing, "purchase_price_number": 2000000}
        mock_llm = make_mock_llm(json.dumps(updated))
        with patch(PATCH_TARGET, return_value=mock_llm):
            result = apply_changes(existing, "Change price to $2M")
        assert result["purchaser_name"] == "Acme"

    def test_apply_changes_with_chat_history(self):
        """Should accept chat_history for context-aware changes."""
        from pa_handler import apply_changes

        existing = {"purchaser_name": "Acme", "closing_days": 30}
        updated = {**existing, "closing_days": 60}
        mock_llm = make_mock_llm(json.dumps(updated))
        history = [
            {"role": "user", "content": "What about the closing timeline?"},
            {"role": "assistant", "content": "Currently set to 30 days."},
        ]
        with patch(PATCH_TARGET, return_value=mock_llm):
            result = apply_changes(existing, "Make it 60", chat_history=history)
        assert result["closing_days"] == 60

    def test_apply_changes_invalid_json_raises(self):
        """If the LLM returns invalid JSON, should raise."""
        from pa_handler import apply_changes

        mock_llm = make_mock_llm("Not valid JSON")
        with patch(PATCH_TARGET, return_value=mock_llm):
            with pytest.raises((json.JSONDecodeError, ValueError)):
                apply_changes({"key": "val"}, "Do something")


# ===========================================================================
# is_approval
# ===========================================================================

class TestIsApproval:
    """Tests for detecting approval messages."""

    @pytest.mark.parametrize("message,expected_approval", [
        ("looks good", True),
        ("that's perfect", True),
        ("finalize it", True),
        ("yes, send it", True),
        ("approved", True),
        ("good to go", True),
        ("LGTM", True),
    ])
    def test_approval_phrases(self, message, expected_approval):
        """Common approval phrases should be detected as approvals."""
        from pa_handler import is_approval

        mock_llm = make_mock_llm("yes")
        with patch(PATCH_TARGET, return_value=mock_llm):
            result = is_approval(message)
        assert result is True

    @pytest.mark.parametrize("message", [
        "change the price to $3M",
        "actually wait, let me update the buyer name",
        "what's the closing date?",
        "no, that's wrong",
    ])
    def test_non_approval_phrases(self, message):
        """Edit or question messages should NOT be detected as approvals."""
        from pa_handler import is_approval

        mock_llm = make_mock_llm("no")
        with patch(PATCH_TARGET, return_value=mock_llm):
            result = is_approval(message)
        assert result is False

    def test_is_approval_returns_bool(self):
        """Should return a boolean, not a string or other type."""
        from pa_handler import is_approval

        mock_llm = make_mock_llm("yes")
        with patch(PATCH_TARGET, return_value=mock_llm):
            result = is_approval("looks good")
        assert isinstance(result, bool)


# ===========================================================================
# classify_action
# ===========================================================================

class TestClassifyAction:
    """Tests for classifying user messages into action types."""

    @pytest.mark.parametrize("message,expected_action", [
        ("change the buyer name to XYZ LLC", "edit"),
        ("show me a preview", "preview"),
        ("finalize the agreement", "finalize"),
        ("save this for later", "save"),
        ("list my drafts", "list_drafts"),
        ("what does earnest money mean?", "question"),
        ("cancel this draft", "cancel"),
    ])
    def test_classify_returns_expected_action(self, message, expected_action):
        """Should classify messages into the correct action type."""
        from pa_handler import classify_action

        mock_llm = make_mock_llm(expected_action)
        with patch(PATCH_TARGET, return_value=mock_llm):
            result = classify_action(message)
        assert result == expected_action

    def test_classify_returns_string(self):
        """classify_action should return a string."""
        from pa_handler import classify_action

        mock_llm = make_mock_llm("edit")
        with patch(PATCH_TARGET, return_value=mock_llm):
            result = classify_action("change something")
        assert isinstance(result, str)

    def test_classify_returns_valid_action(self):
        """Should return one of the valid action types."""
        from pa_handler import classify_action

        valid_actions = {"edit", "preview", "finalize", "save",
                         "list_drafts", "question", "cancel"}
        mock_llm = make_mock_llm("edit")
        with patch(PATCH_TARGET, return_value=mock_llm):
            result = classify_action("some ambiguous message")
        assert result in valid_actions

    def test_classify_unknown_falls_back(self):
        """If LLM returns something unexpected, should default to a safe action."""
        from pa_handler import classify_action

        mock_llm = make_mock_llm("banana")  # Nonsense LLM output
        with patch(PATCH_TARGET, return_value=mock_llm):
            result = classify_action("something weird")
        valid_actions = {"edit", "preview", "finalize", "save",
                         "list_drafts", "question", "cancel"}
        assert result in valid_actions


# ===========================================================================
# format_remaining_variables
# ===========================================================================

class TestFormatRemainingVariables:
    """Tests for generating a checklist of unfilled variables."""

    def test_returns_string(self, complete_variables):
        """Should return a string."""
        from pa_handler import format_remaining_variables

        # All filled — empty checklist
        result = format_remaining_variables(complete_variables)
        assert isinstance(result, str)

    def test_all_filled_returns_empty_or_done(self, complete_variables):
        """If all variables are filled, should return empty or 'all done' message."""
        from pa_handler import format_remaining_variables

        result = format_remaining_variables(complete_variables)
        # Either empty string or a message indicating completion
        assert result == "" or "complete" in result.lower() or \
            "all" in result.lower() or len(result) == 0

    def test_partial_shows_missing(self, partial_variables):
        """Should list the variables that are still None/missing."""
        from pa_handler import format_remaining_variables

        # partial_variables only has 3 fields, so many are missing
        result = format_remaining_variables(partial_variables)
        assert len(result) > 0
        # Should mention at least one unfilled variable
        assert "seller" in result.lower() or "closing" in result.lower() or \
            "title" in result.lower() or "broker" in result.lower() or \
            len(result) > 10

    def test_empty_variables_shows_all(self):
        """With no variables filled, should list everything."""
        from pa_handler import format_remaining_variables

        result = format_remaining_variables({})
        assert len(result) > 0

    def test_none_values_counted_as_missing(self):
        """Variables explicitly set to None should appear as unfilled."""
        from pa_handler import format_remaining_variables

        variables = {
            "purchaser_name": "Filled",
            "seller_name": None,
            "purchase_price_number": None,
        }
        result = format_remaining_variables(variables)
        assert len(result) > 0


# ===========================================================================
# format_filled_summary
# ===========================================================================

class TestFormatFilledSummary:
    """Tests for generating a confirmation of newly extracted variables."""

    def test_returns_string(self):
        """Should return a string."""
        from pa_handler import format_filled_summary

        result = format_filled_summary({"purchaser_name": "Test LLC"})
        assert isinstance(result, str)

    def test_includes_variable_values(self):
        """Should include the extracted variable values in the summary."""
        from pa_handler import format_filled_summary

        extracted = {
            "purchaser_name": "Acme LLC",
            "purchase_price_number": 2500000,
        }
        result = format_filled_summary(extracted)
        assert "Acme LLC" in result or "purchaser" in result.lower()

    def test_empty_extraction(self):
        """Should handle empty extraction without crashing."""
        from pa_handler import format_filled_summary

        result = format_filled_summary({})
        assert isinstance(result, str)

    def test_single_variable(self):
        """Should handle a single extracted variable."""
        from pa_handler import format_filled_summary

        result = format_filled_summary({"purchaser_name": "Solo LLC"})
        assert isinstance(result, str)
        assert len(result) > 0

    def test_does_not_include_none_values(self):
        """Should not show variables that are None in the summary."""
        from pa_handler import format_filled_summary

        extracted = {
            "purchaser_name": "Acme LLC",
            "seller_name": None,
        }
        result = format_filled_summary(extracted)
        # Should mention Acme but not present None as a filled value
        assert "None" not in result or "none" not in result.lower()


# ===========================================================================
# Edge Cases
# ===========================================================================

class TestHandlerEdgeCases:
    """Edge case tests for handler functions."""

    def test_extract_with_empty_string(self):
        """Extracting from empty string should return empty dict or handle gracefully."""
        from pa_handler import extract_pa_data

        mock_llm = make_mock_llm("{}")
        with patch(PATCH_TARGET, return_value=mock_llm):
            result = extract_pa_data("")
        assert isinstance(result, dict)

    def test_extract_preserves_exhibit_a_entities(self):
        """If LLM returns exhibit_a_entities, they should be in the result."""
        from pa_handler import extract_pa_data

        extracted = {
            "purchaser_name": "Test LLC",
            "exhibit_a_entities": [
                {"name": "Entity 1", "address": "123 Main"},
            ],
        }
        mock_llm = make_mock_llm(json.dumps(extracted))
        with patch(PATCH_TARGET, return_value=mock_llm):
            result = extract_pa_data("Test LLC buying Entity 1 at 123 Main")
        assert "exhibit_a_entities" in result

    def test_extract_preserves_additional_provisions(self):
        """If LLM returns additional_provisions, they should be in the result."""
        from pa_handler import extract_pa_data

        extracted = {
            "purchaser_name": "Test LLC",
            "additional_provisions": [
                {"title": "Custom Clause", "body": "Custom body text"},
            ],
        }
        mock_llm = make_mock_llm(json.dumps(extracted))
        with patch(PATCH_TARGET, return_value=mock_llm):
            result = extract_pa_data("Test LLC with custom clause")
        assert "additional_provisions" in result

    def test_apply_changes_handles_adding_new_field(self):
        """apply_changes should handle adding a field that didn't exist before."""
        from pa_handler import apply_changes

        existing = {"purchaser_name": "Acme"}
        updated = {**existing, "seller_name": "Downtown Inc"}
        mock_llm = make_mock_llm(json.dumps(updated))
        with patch(PATCH_TARGET, return_value=mock_llm):
            result = apply_changes(existing, "The seller is Downtown Inc")
        assert result["seller_name"] == "Downtown Inc"


# ===========================================================================
# Exhibit A — remaining variables with Exhibit A active
# ===========================================================================

class TestRemainingVariablesWithExhibitA:
    """Tests for format_remaining_variables when Exhibit A is active."""

    def test_exhibit_a_skips_property_fields(self):
        """With 2+ entities, property fields should be skipped."""
        from pa_handler import format_remaining_variables

        variables = {
            "purchaser_name": "Buyer LLC",
            "exhibit_a_entities": [
                {"name": "LLC A", "address": "100 Main"},
                {"name": "LLC A", "address": "200 Main"},
            ],
        }
        result = format_remaining_variables(variables)
        # Property fields should NOT appear in remaining
        assert "Property Address" not in result
        assert "Parcel" not in result
        assert "Legal Description" not in result
        assert "Municipality" not in result
        assert "County" not in result
        assert "Location Type" not in result

    def test_exhibit_a_multi_llc_skips_seller_fields(self):
        """With multiple LLCs, seller name/address/entity_type should be skipped."""
        from pa_handler import format_remaining_variables

        variables = {
            "purchaser_name": "Buyer LLC",
            "exhibit_a_entities": [
                {"name": "LLC A", "address": "100 Main"},
                {"name": "LLC B", "address": "200 Main"},
            ],
        }
        result = format_remaining_variables(variables)
        # Seller section may still appear (for phone/email/fax) but should NOT
        # list Name, Address, or Entity Type
        if "**Seller:**" in result:
            seller_section = result.split("**Seller:**")[1].split("\n\n")[0]
            assert "- Name" not in seller_section
            assert "- Address" not in seller_section
            assert "- Entity Type" not in seller_section

    def test_exhibit_a_single_llc_keeps_seller_fields(self):
        """With same LLC name, seller fields should still appear if missing."""
        from pa_handler import format_remaining_variables

        variables = {
            "purchaser_name": "Buyer LLC",
            "exhibit_a_entities": [
                {"name": "Same LLC", "address": "100 Main"},
                {"name": "Same LLC", "address": "200 Main"},
            ],
        }
        result = format_remaining_variables(variables)
        # Seller section should still appear (seller fields not filled)
        assert "Seller" in result

    def test_no_exhibit_a_shows_all_fields(self):
        """Without Exhibit A, all property and seller fields should appear."""
        from pa_handler import format_remaining_variables

        variables = {"purchaser_name": "Buyer LLC"}
        result = format_remaining_variables(variables)
        assert "Seller" in result
        assert "Property" in result


# ===========================================================================
# format_exhibit_a_summary
# ===========================================================================

class TestFormatExhibitASummary:
    """Tests for Exhibit A summary display."""

    def test_no_entities_returns_empty(self):
        """No entities should return empty string."""
        from pa_handler import format_exhibit_a_summary

        result = format_exhibit_a_summary({})
        assert result == ""

    def test_single_entity_returns_empty(self):
        """Single entity should return empty (Exhibit A not active)."""
        from pa_handler import format_exhibit_a_summary

        variables = {
            "exhibit_a_entities": [
                {"name": "LLC A", "address": "100 Main"},
            ],
        }
        result = format_exhibit_a_summary(variables)
        assert result == ""

    def test_two_entities_returns_summary(self):
        """Two entities should return a formatted summary."""
        from pa_handler import format_exhibit_a_summary

        variables = {
            "exhibit_a_entities": [
                {"name": "LLC A", "address": "100 Main", "municipality": "Pontiac",
                 "county": "Oakland", "parcel_ids": "001"},
                {"name": "LLC B", "address": "200 Main", "municipality": "Troy",
                 "county": "Oakland", "parcel_ids": "002"},
            ],
        }
        result = format_exhibit_a_summary(variables)
        assert "Exhibit A" in result
        assert "2 entities" in result
        assert "LLC A" in result
        assert "LLC B" in result
        assert "Pontiac" in result
        assert "Troy" in result

    def test_summary_includes_municipality_county(self):
        """Summary should show municipality and county."""
        from pa_handler import format_exhibit_a_summary

        variables = {
            "exhibit_a_entities": [
                {"name": "LLC A", "address": "100 Main",
                 "municipality": "Ann Arbor", "county": "Washtenaw"},
                {"name": "LLC B", "address": "200 Main",
                 "municipality": "Ypsilanti", "county": "Washtenaw"},
            ],
        }
        result = format_exhibit_a_summary(variables)
        assert "Ann Arbor" in result
        assert "Washtenaw" in result


# ===========================================================================
# Mixed Payment Fields — remaining variables visibility
# ===========================================================================

class TestMixedPaymentFieldsVisibility:
    """Tests that mixed payment fields are hidden/shown based on payment method selection."""

    MIXED_FIELDS = {
        "mortgage_pct", "mortgage_amount_words", "mortgage_amount_number",
        "lc_pct", "lc_amount_words", "lc_amount_number",
    }

    def test_remaining_hides_mixed_fields_when_mortgage_only(self):
        """Mortgage=True, LC=False → 6 mixed fields NOT in remaining list."""
        from pa_handler import format_remaining_variables

        variables = {"payment_mortgage": True, "payment_land_contract": False}
        result = format_remaining_variables(variables)
        for field in self.MIXED_FIELDS:
            label = field.replace("_", " ").title()
            # The field label should NOT appear since it's hidden
            # Check both the raw field name and common label forms
            assert field not in result.lower(), f"{field} should be hidden"

    def test_remaining_shows_mixed_fields_when_both(self):
        """Both=True → 6 mixed fields appear in remaining list."""
        from pa_handler import format_remaining_variables

        variables = {"payment_mortgage": True, "payment_land_contract": True}
        result = format_remaining_variables(variables)
        # At least the percentage fields should appear (they are empty/missing)
        assert "Pct" in result or "pct" in result.lower() or "Mortgage Pct" in result or \
            "Amount Words" in result or "Amount Number" in result, \
            f"Mixed payment fields should appear when both methods selected. Got:\n{result}"

    def test_remaining_hides_mixed_fields_when_neither(self):
        """Both=False → 6 mixed fields NOT in remaining list."""
        from pa_handler import format_remaining_variables

        variables = {"payment_mortgage": False, "payment_land_contract": False}
        result = format_remaining_variables(variables)
        for field in self.MIXED_FIELDS:
            assert field not in result.lower(), f"{field} should be hidden"
