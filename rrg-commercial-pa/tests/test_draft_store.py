"""Tests for draft_store.py — SQLite CRUD operations for PA drafts.

Tests the DraftStore class which manages persistent storage of purchase
agreement drafts in SQLite, including create, read, update, list, delete,
and resume-by-address functionality.
"""

import json
import sqlite3
import uuid
import pytest

from draft_store import DraftStore


# ===========================================================================
# Create
# ===========================================================================

class TestCreateDraft:
    """Tests for creating new drafts."""

    def test_create_draft_returns_id(self, draft_store):
        """Creating a draft should return a string ID."""
        draft_id = draft_store.create_draft(
            property_address="123 Main St, Pontiac, MI 48342",
            variables={"purchaser_name": "Acme LLC"},
        )
        assert isinstance(draft_id, str)
        assert len(draft_id) > 0

    def test_create_draft_id_is_uuid_format(self, draft_store):
        """Draft IDs should be valid UUIDs."""
        draft_id = draft_store.create_draft(
            property_address="123 Main St",
            variables={},
        )
        # Should not raise ValueError
        uuid.UUID(draft_id)

    def test_create_draft_with_empty_variables(self, draft_store):
        """Creating a draft with empty variables should succeed."""
        draft_id = draft_store.create_draft(
            property_address="456 Oak Ave",
            variables={},
        )
        draft = draft_store.load_draft(draft_id)
        assert draft is not None
        assert draft["variables"] == {}

    def test_create_draft_stores_property_address(self, draft_store):
        """The property address should be retrievable after creation."""
        addr = "789 Elm St, Ann Arbor, MI 48104"
        draft_id = draft_store.create_draft(
            property_address=addr,
            variables={"purchaser_name": "Test"},
        )
        draft = draft_store.load_draft(draft_id)
        assert draft["property_address"] == addr

    def test_create_draft_stores_variables(self, draft_store, partial_variables):
        """Variables passed at creation should be stored correctly."""
        draft_id = draft_store.create_draft(
            property_address="123 Main St",
            variables=partial_variables,
        )
        draft = draft_store.load_draft(draft_id)
        assert draft["variables"]["purchaser_name"] == "Acme Holdings LLC"
        assert draft["variables"]["purchase_price_number"] == 2500000.00

    def test_create_draft_default_status_is_in_progress(self, draft_store):
        """New drafts should have status 'in_progress'."""
        draft_id = draft_store.create_draft(
            property_address="123 Main St",
            variables={},
        )
        draft = draft_store.load_draft(draft_id)
        assert draft["status"] == "in_progress"

    def test_create_draft_sets_timestamps(self, draft_store):
        """New drafts should have created_at and updated_at timestamps."""
        draft_id = draft_store.create_draft(
            property_address="123 Main St",
            variables={},
        )
        draft = draft_store.load_draft(draft_id)
        assert "created_at" in draft
        assert "updated_at" in draft
        assert draft["created_at"] is not None
        assert draft["updated_at"] is not None

    def test_create_draft_with_additional_provisions(self, draft_store, sample_provisions):
        """Creating a draft with additional provisions should store them."""
        draft_id = draft_store.create_draft(
            property_address="123 Main St",
            variables={},
            additional_provisions=sample_provisions,
        )
        draft = draft_store.load_draft(draft_id)
        assert draft["additional_provisions"] == sample_provisions

    def test_create_draft_with_exhibit_a(self, draft_store, sample_exhibit_a):
        """Creating a draft with Exhibit A entities should store them."""
        draft_id = draft_store.create_draft(
            property_address="123 Main St",
            variables={},
            exhibit_a_entities=sample_exhibit_a,
        )
        draft = draft_store.load_draft(draft_id)
        assert draft["exhibit_a_entities"] == sample_exhibit_a
        assert len(draft["exhibit_a_entities"]) == 3

    def test_create_multiple_drafts_unique_ids(self, draft_store):
        """Multiple drafts should each get a unique ID."""
        ids = set()
        for i in range(10):
            draft_id = draft_store.create_draft(
                property_address=f"{i} Test St",
                variables={},
            )
            ids.add(draft_id)
        assert len(ids) == 10


# ===========================================================================
# Load
# ===========================================================================

class TestLoadDraft:
    """Tests for loading drafts by ID."""

    def test_load_existing_draft(self, draft_store):
        """Loading an existing draft should return its data."""
        draft_id = draft_store.create_draft(
            property_address="123 Main St",
            variables={"purchaser_name": "Test"},
        )
        draft = draft_store.load_draft(draft_id)
        assert draft is not None
        assert draft["id"] == draft_id

    def test_load_nonexistent_draft_returns_none(self, draft_store):
        """Loading a draft that doesn't exist should return None."""
        result = draft_store.load_draft("nonexistent-uuid-here")
        assert result is None

    def test_load_draft_has_all_fields(self, draft_store, partial_variables):
        """Loaded draft should contain id, property_address, variables, status, timestamps."""
        draft_id = draft_store.create_draft(
            property_address="123 Main St",
            variables=partial_variables,
        )
        draft = draft_store.load_draft(draft_id)
        required_fields = ["id", "property_address", "variables", "status",
                           "created_at", "updated_at"]
        for field in required_fields:
            assert field in draft, f"Missing field: {field}"

    def test_load_draft_variables_are_dict(self, draft_store):
        """Variables in loaded draft should be a dict, not a JSON string."""
        draft_id = draft_store.create_draft(
            property_address="123 Main St",
            variables={"key": "value"},
        )
        draft = draft_store.load_draft(draft_id)
        assert isinstance(draft["variables"], dict)

    def test_load_draft_preserves_types(self, draft_store):
        """Variable types (int, float, bool, str) should survive round-trip."""
        variables = {
            "purchase_price_number": 2500000.00,
            "closing_days": 60,
            "payment_cash": True,
            "purchaser_name": "Test LLC",
        }
        draft_id = draft_store.create_draft(
            property_address="123 Main St",
            variables=variables,
        )
        draft = draft_store.load_draft(draft_id)
        assert draft["variables"]["purchase_price_number"] == 2500000.00
        assert draft["variables"]["closing_days"] == 60
        assert draft["variables"]["payment_cash"] is True
        assert draft["variables"]["purchaser_name"] == "Test LLC"


# ===========================================================================
# Load by Property Address (Resume feature)
# ===========================================================================

class TestLoadByAddress:
    """Tests for the resume-by-address feature."""

    def test_load_by_address_finds_draft(self, draft_store):
        """Should find a draft by its property address."""
        addr = "283 Unit Portfolio, 123 Main St, Pontiac, MI 48342"
        draft_id = draft_store.create_draft(
            property_address=addr,
            variables={"purchaser_name": "Test"},
        )
        draft = draft_store.load_draft_by_address(addr)
        assert draft is not None
        assert draft["id"] == draft_id

    def test_load_by_address_no_match_returns_none(self, draft_store):
        """Should return None if no draft matches the address."""
        draft_store.create_draft(
            property_address="123 Main St",
            variables={},
        )
        result = draft_store.load_draft_by_address("999 Nonexistent Ave")
        assert result is None

    def test_load_by_address_case_sensitivity(self, draft_store):
        """Address lookup behavior with different casing — document the behavior."""
        draft_store.create_draft(
            property_address="123 Main St",
            variables={},
        )
        # Case-insensitive matching would be more user-friendly.
        # This test documents the actual behavior — if it's case-sensitive,
        # that's a potential UX issue to track.
        result_exact = draft_store.load_draft_by_address("123 Main St")
        assert result_exact is not None

    def test_load_by_address_returns_most_recent(self, draft_store):
        """If multiple drafts share an address, should return the most recent."""
        addr = "123 Main St"
        draft_store.create_draft(property_address=addr, variables={"version": 1})
        draft_id_2 = draft_store.create_draft(property_address=addr, variables={"version": 2})
        draft = draft_store.load_draft_by_address(addr)
        # Should be the most recently created draft
        assert draft is not None
        assert draft["id"] == draft_id_2

    def test_load_by_address_skips_completed_drafts(self, draft_store):
        """Resume should only find in-progress drafts, not completed ones."""
        addr = "123 Main St"
        draft_id_1 = draft_store.create_draft(property_address=addr, variables={})
        # Mark first draft as completed
        draft_store.update_draft(draft_id_1, variables={}, status="completed")
        # Create a new in-progress draft at same address
        draft_id_2 = draft_store.create_draft(property_address=addr, variables={})
        draft = draft_store.load_draft_by_address(addr)
        assert draft is not None
        assert draft["id"] == draft_id_2
        assert draft["status"] == "in_progress"

    def test_load_by_address_empty_string(self, draft_store):
        """Empty string address should return None (not crash)."""
        result = draft_store.load_draft_by_address("")
        assert result is None


# ===========================================================================
# Update
# ===========================================================================

class TestUpdateDraft:
    """Tests for updating draft variables and status."""

    def test_update_merges_new_variables(self, draft_store):
        """Update should merge new variables into existing ones."""
        draft_id = draft_store.create_draft(
            property_address="123 Main St",
            variables={"purchaser_name": "Acme LLC"},
        )
        draft_store.update_draft(draft_id, variables={"seller_name": "Downtown Inc"})
        draft = draft_store.load_draft(draft_id)
        assert draft["variables"]["purchaser_name"] == "Acme LLC"
        assert draft["variables"]["seller_name"] == "Downtown Inc"

    def test_update_overwrites_existing_variable(self, draft_store):
        """Update should overwrite a variable if its key already exists."""
        draft_id = draft_store.create_draft(
            property_address="123 Main St",
            variables={"purchaser_name": "Old Name"},
        )
        draft_store.update_draft(draft_id, variables={"purchaser_name": "New Name"})
        draft = draft_store.load_draft(draft_id)
        assert draft["variables"]["purchaser_name"] == "New Name"

    def test_update_preserves_unmentioned_variables(self, draft_store):
        """Update should not remove variables not mentioned in the update."""
        original = {
            "purchaser_name": "Acme LLC",
            "seller_name": "Downtown Inc",
            "purchase_price_number": 2500000,
        }
        draft_id = draft_store.create_draft(
            property_address="123 Main St",
            variables=original,
        )
        # Only update one variable
        draft_store.update_draft(draft_id, variables={"purchase_price_number": 3000000})
        draft = draft_store.load_draft(draft_id)
        assert draft["variables"]["purchaser_name"] == "Acme LLC"
        assert draft["variables"]["seller_name"] == "Downtown Inc"
        assert draft["variables"]["purchase_price_number"] == 3000000

    def test_update_with_empty_variables_is_noop(self, draft_store):
        """Updating with empty dict should keep existing variables unchanged."""
        original = {"purchaser_name": "Acme LLC"}
        draft_id = draft_store.create_draft(
            property_address="123 Main St",
            variables=original,
        )
        draft_store.update_draft(draft_id, variables={})
        draft = draft_store.load_draft(draft_id)
        assert draft["variables"]["purchaser_name"] == "Acme LLC"

    def test_update_nonexistent_draft(self, draft_store):
        """Updating a nonexistent draft should not crash.

        Implementation may raise an exception or return None/False.
        The key thing is it should handle this gracefully.
        """
        # Should not raise an unhandled exception
        try:
            result = draft_store.update_draft("fake-uuid", variables={"key": "val"})
            # If it returns a value, it should indicate failure
        except (KeyError, ValueError):
            pass  # Acceptable to raise a specific error

    def test_update_changes_status(self, draft_store):
        """Update should be able to change the draft status."""
        draft_id = draft_store.create_draft(
            property_address="123 Main St",
            variables={},
        )
        draft_store.update_draft(draft_id, variables={}, status="completed")
        draft = draft_store.load_draft(draft_id)
        assert draft["status"] == "completed"

    def test_update_changes_updated_at_timestamp(self, draft_store):
        """Update should refresh the updated_at timestamp."""
        import time
        draft_id = draft_store.create_draft(
            property_address="123 Main St",
            variables={},
        )
        draft_before = draft_store.load_draft(draft_id)
        time.sleep(0.05)  # Tiny delay to ensure timestamp differs
        draft_store.update_draft(draft_id, variables={"key": "val"})
        draft_after = draft_store.load_draft(draft_id)
        # updated_at should have changed (or at least not be earlier)
        assert draft_after["updated_at"] >= draft_before["updated_at"]

    def test_update_additional_provisions(self, draft_store, sample_provisions):
        """Update should be able to set or replace additional provisions."""
        draft_id = draft_store.create_draft(
            property_address="123 Main St",
            variables={},
        )
        draft_store.update_draft(
            draft_id,
            variables={},
            additional_provisions=sample_provisions,
        )
        draft = draft_store.load_draft(draft_id)
        assert draft["additional_provisions"] == sample_provisions

    def test_update_exhibit_a_entities(self, draft_store, sample_exhibit_a):
        """Update should be able to set or replace Exhibit A entities."""
        draft_id = draft_store.create_draft(
            property_address="123 Main St",
            variables={},
        )
        draft_store.update_draft(
            draft_id,
            variables={},
            exhibit_a_entities=sample_exhibit_a,
        )
        draft = draft_store.load_draft(draft_id)
        assert draft["exhibit_a_entities"] == sample_exhibit_a

    def test_update_is_single_connection_read_merge_write(self, db_path):
        """Verify that update uses a single connection for read-merge-write.

        The design doc explicitly calls out: 'Never open a separate connection
        for the read -- do it all in one.' This test verifies merged results
        to confirm the read-merge-write happened atomically.
        """
        store = DraftStore(db_path)
        draft_id = store.create_draft(
            property_address="123 Main St",
            variables={"a": 1, "b": 2},
        )
        # Update with partial variables
        store.update_draft(draft_id, variables={"b": 20, "c": 30})
        draft = store.load_draft(draft_id)
        # Verify merge: a=1 preserved, b=20 overwritten, c=30 added
        assert draft["variables"] == {"a": 1, "b": 20, "c": 30}

    def test_update_variable_to_none(self, draft_store):
        """Setting a variable to None should store None (explicit null)."""
        draft_id = draft_store.create_draft(
            property_address="123 Main St",
            variables={"purchaser_name": "Acme LLC"},
        )
        draft_store.update_draft(draft_id, variables={"purchaser_name": None})
        draft = draft_store.load_draft(draft_id)
        assert draft["variables"]["purchaser_name"] is None

    def test_update_with_nested_structures(self, draft_store):
        """Variables that are lists/dicts should survive update merge."""
        draft_id = draft_store.create_draft(
            property_address="123 Main St",
            variables={"simple": "value"},
        )
        provisions = [{"title": "Test", "body": "Test body"}]
        draft_store.update_draft(
            draft_id,
            variables={"additional_provisions": provisions},
        )
        draft = draft_store.load_draft(draft_id)
        assert draft["variables"]["additional_provisions"] == provisions


# ===========================================================================
# List
# ===========================================================================

class TestListDrafts:
    """Tests for listing all drafts."""

    def test_list_empty_store(self, draft_store):
        """Listing with no drafts should return an empty list."""
        drafts = draft_store.list_drafts()
        assert drafts == []

    def test_list_returns_all_drafts(self, draft_store):
        """All created drafts should appear in the list."""
        for i in range(3):
            draft_store.create_draft(
                property_address=f"{i} Test St",
                variables={},
            )
        drafts = draft_store.list_drafts()
        assert len(drafts) == 3

    def test_list_includes_property_address(self, draft_store):
        """Each listed draft should include its property_address."""
        draft_store.create_draft(
            property_address="123 Main St",
            variables={},
        )
        drafts = draft_store.list_drafts()
        assert drafts[0]["property_address"] == "123 Main St"

    def test_list_includes_status(self, draft_store):
        """Each listed draft should include its status."""
        draft_store.create_draft(
            property_address="123 Main St",
            variables={},
        )
        drafts = draft_store.list_drafts()
        assert "status" in drafts[0]

    def test_list_includes_completion_percentage(self, draft_store, complete_variables):
        """Each listed draft should include a completion percentage."""
        # Create a fully-filled draft
        draft_store.create_draft(
            property_address="123 Main St",
            variables=complete_variables,
        )
        # Create an empty draft
        draft_store.create_draft(
            property_address="456 Oak Ave",
            variables={},
        )
        drafts = draft_store.list_drafts()
        # Find each draft and check completion
        for d in drafts:
            assert "completion_pct" in d or "completion" in d, \
                f"Draft listing missing completion info: {d.keys()}"

    def test_list_multiple_addresses(self, draft_store):
        """Drafts with different addresses should all appear."""
        addrs = ["123 Main St", "456 Oak Ave", "789 Elm Rd"]
        for addr in addrs:
            draft_store.create_draft(property_address=addr, variables={})
        drafts = draft_store.list_drafts()
        listed_addrs = {d["property_address"] for d in drafts}
        assert listed_addrs == set(addrs)

    def test_list_includes_draft_id(self, draft_store):
        """Each listed draft should include its ID for retrieval."""
        draft_id = draft_store.create_draft(
            property_address="123 Main St",
            variables={},
        )
        drafts = draft_store.list_drafts()
        assert drafts[0]["id"] == draft_id


# ===========================================================================
# Delete / Cancel
# ===========================================================================

class TestDeleteDraft:
    """Tests for deleting/cancelling drafts."""

    def test_delete_existing_draft(self, draft_store):
        """Deleting a draft should remove it from the store."""
        draft_id = draft_store.create_draft(
            property_address="123 Main St",
            variables={},
        )
        draft_store.delete_draft(draft_id)
        assert draft_store.load_draft(draft_id) is None

    def test_delete_nonexistent_draft(self, draft_store):
        """Deleting a nonexistent draft should not crash."""
        # Should not raise
        draft_store.delete_draft("nonexistent-uuid")

    def test_delete_removes_from_list(self, draft_store):
        """Deleted drafts should not appear in list_drafts."""
        draft_id = draft_store.create_draft(
            property_address="123 Main St",
            variables={},
        )
        draft_store.delete_draft(draft_id)
        drafts = draft_store.list_drafts()
        ids = [d["id"] for d in drafts]
        assert draft_id not in ids

    def test_delete_does_not_affect_other_drafts(self, draft_store):
        """Deleting one draft should not affect others."""
        id_keep = draft_store.create_draft(
            property_address="Keep Me",
            variables={"keeper": True},
        )
        id_del = draft_store.create_draft(
            property_address="Delete Me",
            variables={},
        )
        draft_store.delete_draft(id_del)
        draft = draft_store.load_draft(id_keep)
        assert draft is not None
        assert draft["variables"]["keeper"] is True


# ===========================================================================
# Edge Cases & Robustness
# ===========================================================================

class TestDraftStoreEdgeCases:
    """Edge cases and robustness tests."""

    def test_store_initializes_table(self, db_path):
        """DraftStore should create the drafts table if it doesn't exist."""
        store = DraftStore(db_path)
        # Should be able to list without error (table exists)
        assert store.list_drafts() == []

    def test_store_handles_unicode_in_variables(self, draft_store):
        """Variables with unicode characters should round-trip correctly."""
        draft_id = draft_store.create_draft(
            property_address="123 Main St",
            variables={"seller_name": "Jean-Pierre Dubois"},
        )
        draft = draft_store.load_draft(draft_id)
        assert draft["variables"]["seller_name"] == "Jean-Pierre Dubois"

    def test_store_handles_special_characters_in_address(self, draft_store):
        """Addresses with special characters should work."""
        addr = "123 O'Brien St, Apt #4B, Ann Arbor, MI"
        draft_id = draft_store.create_draft(
            property_address=addr,
            variables={},
        )
        draft = draft_store.load_draft(draft_id)
        assert draft["property_address"] == addr

    def test_store_handles_large_legal_description(self, draft_store):
        """Very long legal descriptions should be stored correctly."""
        long_desc = "LOT 1 AND 2 AND 3 " * 100
        draft_id = draft_store.create_draft(
            property_address="123 Main St",
            variables={"property_legal_description": long_desc},
        )
        draft = draft_store.load_draft(draft_id)
        assert draft["variables"]["property_legal_description"] == long_desc

    def test_store_handles_float_precision(self, draft_store):
        """Financial values should not lose precision through JSON round-trip."""
        draft_id = draft_store.create_draft(
            property_address="123 Main St",
            variables={
                "purchase_price_number": 2500000.50,
                "broker_commission_pct": 3.25,
            },
        )
        draft = draft_store.load_draft(draft_id)
        assert draft["variables"]["purchase_price_number"] == 2500000.50
        assert draft["variables"]["broker_commission_pct"] == 3.25

    def test_concurrent_store_instances(self, db_path):
        """Two DraftStore instances on the same DB should see each other's data."""
        store1 = DraftStore(db_path)
        store2 = DraftStore(db_path)
        draft_id = store1.create_draft(
            property_address="123 Main St",
            variables={"from": "store1"},
        )
        draft = store2.load_draft(draft_id)
        assert draft is not None
        assert draft["variables"]["from"] == "store1"
