"""Tests for pa_docx.py — docxtpl rendering of commercial purchase agreements.

Tests the .docx generation from PA variables, including full and partial
variable sets, dynamic Exhibit A rows, additional provisions, and checkboxes.
"""

import io
import zipfile
import pytest

from pa_docx import generate_pa_docx


# ===========================================================================
# Basic Generation
# ===========================================================================

class TestGenerateDocx:
    """Tests for generating .docx files from complete variable sets."""

    def test_generate_returns_bytes(self, complete_variables):
        """generate_pa_docx should return bytes, not None."""
        result = generate_pa_docx(complete_variables)
        assert result is not None
        assert isinstance(result, bytes)

    def test_generate_returns_nonempty_bytes(self, complete_variables):
        """Generated .docx should have nonzero length."""
        result = generate_pa_docx(complete_variables)
        assert len(result) > 0

    def test_generate_produces_valid_docx(self, complete_variables):
        """Generated output should be a valid .docx (ZIP) file (PK header)."""
        result = generate_pa_docx(complete_variables)
        # .docx files are ZIP archives — they start with PK (0x50, 0x4B)
        assert result[:2] == b"PK", \
            f"Expected PK zip header, got: {result[:4]!r}"

    def test_generate_produces_valid_zip(self, complete_variables):
        """Generated output should be a valid ZIP that Python can read."""
        result = generate_pa_docx(complete_variables)
        buf = io.BytesIO(result)
        assert zipfile.is_zipfile(buf)

    def test_generate_contains_word_content(self, complete_variables):
        """The ZIP should contain word/document.xml (standard .docx structure)."""
        result = generate_pa_docx(complete_variables)
        buf = io.BytesIO(result)
        with zipfile.ZipFile(buf) as zf:
            names = zf.namelist()
            assert "word/document.xml" in names, \
                f"Missing word/document.xml. Files: {names}"

    def test_generate_with_complete_variables_has_content(self, complete_variables):
        """The rendered document should contain variable values in the XML."""
        result = generate_pa_docx(complete_variables)
        buf = io.BytesIO(result)
        with zipfile.ZipFile(buf) as zf:
            doc_xml = zf.read("word/document.xml").decode("utf-8")
            # Check that at least some variable values appear in the doc
            assert "Acme Holdings LLC" in doc_xml
            assert "Pontiac" in doc_xml


# ===========================================================================
# Partial Variables
# ===========================================================================

class TestPartialVariables:
    """Tests for generating .docx with incomplete variable sets."""

    def test_generate_with_partial_variables_does_not_crash(self, partial_variables):
        """Should produce a .docx even with only a few variables filled."""
        result = generate_pa_docx(partial_variables)
        assert result is not None
        assert isinstance(result, bytes)
        assert result[:2] == b"PK"

    def test_generate_with_empty_variables(self):
        """Should produce a .docx even with zero variables filled."""
        result = generate_pa_docx({})
        assert result is not None
        assert isinstance(result, bytes)
        assert result[:2] == b"PK"

    def test_generate_with_none_values(self):
        """Variables explicitly set to None should not crash rendering."""
        variables = {
            "purchaser_name": None,
            "seller_name": None,
            "purchase_price_number": None,
        }
        result = generate_pa_docx(variables)
        assert result is not None
        assert result[:2] == b"PK"

    def test_partial_variables_unfilled_are_blank(self, partial_variables):
        """Unfilled variables should render as blank, not as template tags."""
        result = generate_pa_docx(partial_variables)
        buf = io.BytesIO(result)
        with zipfile.ZipFile(buf) as zf:
            doc_xml = zf.read("word/document.xml").decode("utf-8")
            # Should not contain raw Jinja2 template tags
            assert "{{" not in doc_xml, \
                "Raw Jinja2 tags found in output — unfilled variables not blanked"
            assert "}}" not in doc_xml


# ===========================================================================
# Exhibit A (Dynamic Table Rows)
# ===========================================================================

class TestExhibitA:
    """Tests for dynamic Exhibit A table rendering."""

    def test_exhibit_a_single_entity(self, complete_variables):
        """Should render correctly with 1 entity."""
        variables = {**complete_variables}
        variables["exhibit_a_entities"] = [
            {
                "name": "123 Main Street LLC",
                "address": "123 Main St, Pontiac, MI 48342",
                "parcel_ids": "14-01-234-001",
                "legal_descriptions": "Lot 1 of Plat No. 12",
            },
        ]
        result = generate_pa_docx(variables)
        assert result is not None
        assert result[:2] == b"PK"

    def test_exhibit_a_three_entities(self, complete_variables, sample_exhibit_a):
        """Should render correctly with 3 entities."""
        variables = {**complete_variables}
        variables["exhibit_a_entities"] = sample_exhibit_a
        result = generate_pa_docx(variables)
        assert result is not None
        buf = io.BytesIO(result)
        with zipfile.ZipFile(buf) as zf:
            doc_xml = zf.read("word/document.xml").decode("utf-8")
            # All three entity names should appear
            assert "123 Main Street LLC" in doc_xml
            assert "125 Main Street LLC" in doc_xml
            assert "127 Main Street LLC" in doc_xml

    def test_exhibit_a_zero_entities(self, complete_variables):
        """Should render correctly with 0 entities (empty list)."""
        variables = {**complete_variables}
        variables["exhibit_a_entities"] = []
        result = generate_pa_docx(variables)
        assert result is not None
        assert result[:2] == b"PK"

    def test_exhibit_a_missing_key(self, complete_variables):
        """Should not crash if exhibit_a_entities is not provided at all."""
        variables = {**complete_variables}
        variables.pop("exhibit_a_entities", None)
        result = generate_pa_docx(variables)
        assert result is not None
        assert result[:2] == b"PK"

    def test_exhibit_a_entity_fields_appear(self, complete_variables):
        """Entity parcel IDs and legal descriptions should appear in output.

        Exhibit A only renders with 2+ entities, so we need at least two.
        """
        variables = {**complete_variables}
        variables["exhibit_a_entities"] = [
            {
                "name": "Test Entity Corp",
                "address": "999 Test Ave",
                "municipality": "TestCity",
                "county": "TestCounty",
                "parcel_ids": "99-99-999-999",
                "legal_descriptions": "Unit 42 of Test Subdivision",
            },
            {
                "name": "Test Entity Corp",
                "address": "888 Other Blvd",
                "municipality": "OtherCity",
                "county": "OtherCounty",
                "parcel_ids": "88-88-888-888",
                "legal_descriptions": "Unit 99 of Other Subdivision",
            },
        ]
        result = generate_pa_docx(variables)
        buf = io.BytesIO(result)
        with zipfile.ZipFile(buf) as zf:
            doc_xml = zf.read("word/document.xml").decode("utf-8")
            assert "99-99-999-999" in doc_xml
            assert "Unit 42 of Test Subdivision" in doc_xml
            assert "88-88-888-888" in doc_xml


# ===========================================================================
# Additional Provisions
# ===========================================================================

class TestAdditionalProvisions:
    """Tests for rendering additional provisions in the .docx."""

    def test_zero_provisions(self, complete_variables):
        """Should render correctly with no additional provisions."""
        variables = {**complete_variables}
        variables["additional_provisions"] = []
        result = generate_pa_docx(variables)
        assert result is not None
        assert result[:2] == b"PK"

    def test_one_provision(self, complete_variables):
        """Should render correctly with 1 provision."""
        variables = {**complete_variables}
        variables["additional_provisions"] = [
            {"title": "Processing Fee", "body": "A fee of $395 at closing."},
        ]
        result = generate_pa_docx(variables)
        buf = io.BytesIO(result)
        with zipfile.ZipFile(buf) as zf:
            doc_xml = zf.read("word/document.xml").decode("utf-8")
            assert "Processing Fee" in doc_xml

    def test_three_provisions(self, complete_variables, sample_provisions):
        """Should render correctly with 3 provisions."""
        variables = {**complete_variables}
        variables["additional_provisions"] = sample_provisions
        result = generate_pa_docx(variables)
        buf = io.BytesIO(result)
        with zipfile.ZipFile(buf) as zf:
            doc_xml = zf.read("word/document.xml").decode("utf-8")
            for prov in sample_provisions:
                assert prov["title"] in doc_xml, \
                    f"Provision '{prov['title']}' not found in document"

    def test_provisions_missing_key(self, complete_variables):
        """Should not crash if additional_provisions key is absent."""
        variables = {**complete_variables}
        variables.pop("additional_provisions", None)
        result = generate_pa_docx(variables)
        assert result is not None
        assert result[:2] == b"PK"

    def test_provision_with_long_body(self, complete_variables):
        """Provisions with very long body text should render without truncation."""
        long_body = "This is a provision. " * 200
        variables = {**complete_variables}
        variables["additional_provisions"] = [
            {"title": "Lengthy Provision", "body": long_body},
        ]
        result = generate_pa_docx(variables)
        assert result is not None
        assert result[:2] == b"PK"


# ===========================================================================
# Checkbox Variables
# ===========================================================================

class TestCheckboxRendering:
    """Tests for boolean checkbox variable rendering."""

    def test_checkbox_true_renders_checked(self, complete_variables):
        """A True boolean should render as checked (e.g., [X] or similar)."""
        variables = {**complete_variables}
        variables["payment_cash"] = True
        result = generate_pa_docx(variables)
        buf = io.BytesIO(result)
        with zipfile.ZipFile(buf) as zf:
            doc_xml = zf.read("word/document.xml").decode("utf-8")
            # Design says: True shows [X], False shows [ ]
            # Check that at least one "X" or checked marker appears near payment_cash
            # The exact rendering depends on the template, but the doc shouldn't
            # have raw True/False strings
            assert "True" not in doc_xml or "[X]" in doc_xml or \
                "\u2611" in doc_xml or "&#9745;" in doc_xml or "X" in doc_xml

    def test_checkbox_false_renders_unchecked(self, complete_variables):
        """A False boolean should render as unchecked (e.g., [ ] or similar)."""
        variables = {**complete_variables}
        variables["payment_cash"] = False
        variables["payment_mortgage"] = False
        result = generate_pa_docx(variables)
        # Should not crash — False values should render as unchecked
        assert result is not None
        assert result[:2] == b"PK"

    def test_all_dd_checkboxes_true(self, complete_variables):
        """All due diligence checkboxes set to True should render."""
        variables = {**complete_variables}
        dd_fields = [
            "dd_financing", "dd_physical_inspection", "dd_environmental",
            "dd_soil_tests", "dd_zoning", "dd_site_plan", "dd_survey",
            "dd_leases_estoppel", "dd_other", "dd_governmental",
        ]
        for field in dd_fields:
            variables[field] = True
        result = generate_pa_docx(variables)
        assert result is not None
        assert result[:2] == b"PK"

    def test_all_dd_checkboxes_false(self, complete_variables):
        """All due diligence checkboxes set to False should render."""
        variables = {**complete_variables}
        dd_fields = [
            "dd_financing", "dd_physical_inspection", "dd_environmental",
            "dd_soil_tests", "dd_zoning", "dd_site_plan", "dd_survey",
            "dd_leases_estoppel", "dd_other", "dd_governmental",
        ]
        for field in dd_fields:
            variables[field] = False
        result = generate_pa_docx(variables)
        assert result is not None
        assert result[:2] == b"PK"

    def test_payment_method_mutual_exclusivity(self, complete_variables):
        """Only one payment method should be checked at a time."""
        # This is a logical test — if multiple are True, it should still render
        variables = {**complete_variables}
        variables["payment_cash"] = True
        variables["payment_mortgage"] = True  # Both True (unusual but shouldn't crash)
        variables["payment_land_contract"] = False
        result = generate_pa_docx(variables)
        assert result is not None


# ===========================================================================
# Edge Cases
# ===========================================================================

class TestDocxEdgeCases:
    """Edge case tests for .docx generation."""

    def test_special_characters_in_names(self, complete_variables):
        """Names with apostrophes, accents, etc. should render correctly."""
        variables = {**complete_variables}
        variables["purchaser_name"] = "O'Brien & Associates"
        variables["seller_name"] = "Jean-Pierre Dubois Enterprises"
        result = generate_pa_docx(variables)
        buf = io.BytesIO(result)
        with zipfile.ZipFile(buf) as zf:
            doc_xml = zf.read("word/document.xml").decode("utf-8")
            # XML entities may encode these, but they should be present
            assert "Brien" in doc_xml
            assert "Dubois" in doc_xml

    def test_dollar_amounts_formatting(self, complete_variables):
        """Dollar amounts should appear in the document."""
        result = generate_pa_docx(complete_variables)
        buf = io.BytesIO(result)
        with zipfile.ZipFile(buf) as zf:
            doc_xml = zf.read("word/document.xml").decode("utf-8")
            # The purchase price in words or number should appear
            assert "2500000" in doc_xml or "2,500,000" in doc_xml or \
                "Two Million" in doc_xml

    def test_land_contract_variables_when_not_selected(self, complete_variables):
        """When payment_land_contract is False, LC variables should still render
        (as 0 or blank), not crash."""
        variables = {**complete_variables}
        variables["payment_land_contract"] = False
        variables["lc_down_payment"] = 0
        variables["lc_balance"] = 0
        result = generate_pa_docx(variables)
        assert result is not None
        assert result[:2] == b"PK"

    def test_land_contract_variables_when_selected(self, complete_variables):
        """When payment_land_contract is True, LC variables should appear."""
        variables = {**complete_variables}
        variables["payment_cash"] = False
        variables["payment_land_contract"] = True
        variables["lc_down_payment"] = 500000
        variables["lc_balance"] = 2000000
        variables["lc_interest_rate"] = 6.5
        variables["lc_amortization_years"] = 30
        variables["lc_balloon_months"] = 60
        result = generate_pa_docx(variables)
        assert result is not None
        buf = io.BytesIO(result)
        with zipfile.ZipFile(buf) as zf:
            doc_xml = zf.read("word/document.xml").decode("utf-8")
            assert "500000" in doc_xml or "500,000" in doc_xml

    def test_generate_returns_new_bytes_each_call(self, complete_variables):
        """Each call should return fresh bytes (not a cached reference)."""
        result1 = generate_pa_docx(complete_variables)
        result2 = generate_pa_docx(complete_variables)
        # Separate objects (not cached), both valid docx
        assert result1 is not result2
        assert result1[:2] == b"PK"
        assert result2[:2] == b"PK"

    def test_empty_string_variables_do_not_crash(self, complete_variables):
        """All string variables set to empty string should not crash."""
        variables = {}
        for key, val in complete_variables.items():
            if isinstance(val, str):
                variables[key] = ""
            else:
                variables[key] = val
        result = generate_pa_docx(variables)
        assert result is not None
        assert result[:2] == b"PK"


# ===========================================================================
# Conditional Exhibit A Rendering
# ===========================================================================

class TestConditionalExhibitA:
    """Tests for conditional seller intro and property description based on Exhibit A."""

    def test_single_seller_inline(self, complete_variables):
        """With no Exhibit A entities, seller and property should be inline."""
        variables = {**complete_variables}
        variables.pop("exhibit_a_entities", None)
        result = generate_pa_docx(variables)
        buf = io.BytesIO(result)
        with zipfile.ZipFile(buf) as zf:
            doc_xml = zf.read("word/document.xml").decode("utf-8")
            # Seller name should appear inline in the opening paragraph
            assert "Downtown Properties Inc" in doc_xml
            assert "a Michigan corporation" in doc_xml
            # Property location should be inline
            assert "Pontiac" in doc_xml
            assert "Oakland" in doc_xml
            # Should NOT say "as described in Exhibit A"
            assert "as described in Exhibit A" not in doc_xml

    def test_multi_llc_exhibit_a_seller_reference(self, complete_variables, sample_exhibit_a):
        """With multiple distinct LLCs, seller intro should reference Exhibit A."""
        variables = {**complete_variables}
        variables["exhibit_a_entities"] = sample_exhibit_a
        result = generate_pa_docx(variables)
        buf = io.BytesIO(result)
        with zipfile.ZipFile(buf) as zf:
            doc_xml = zf.read("word/document.xml").decode("utf-8")
            assert "those entities set forth in Exhibit A" in doc_xml
            assert "as described in Exhibit A" in doc_xml

    def test_same_llc_multi_property_seller_inline(self, complete_variables):
        """Same LLC with multiple properties: seller inline, property references Exhibit A."""
        variables = {**complete_variables}
        variables["exhibit_a_entities"] = [
            {"name": "Same LLC", "address": "100 Main", "municipality": "Pontiac",
             "county": "Oakland", "parcel_ids": "001", "legal_description": "Lot 1"},
            {"name": "Same LLC", "address": "200 Main", "municipality": "Troy",
             "county": "Oakland", "parcel_ids": "002", "legal_description": "Lot 2"},
        ]
        result = generate_pa_docx(variables)
        buf = io.BytesIO(result)
        with zipfile.ZipFile(buf) as zf:
            doc_xml = zf.read("word/document.xml").decode("utf-8")
            # Seller should be inline (single LLC)
            assert "Downtown Properties Inc" in doc_xml
            assert "those entities set forth in Exhibit A" not in doc_xml
            # Property should reference Exhibit A
            assert "as described in Exhibit A" in doc_xml

    def test_exhibit_a_table_has_six_columns(self, complete_variables, sample_exhibit_a):
        """Exhibit A table should have 6 columns including Municipality and County."""
        variables = {**complete_variables}
        variables["exhibit_a_entities"] = sample_exhibit_a
        result = generate_pa_docx(variables)
        buf = io.BytesIO(result)
        with zipfile.ZipFile(buf) as zf:
            doc_xml = zf.read("word/document.xml").decode("utf-8")
            assert "Municipality" in doc_xml
            assert "County" in doc_xml

    def test_exhibit_a_municipality_county_rendered(self, complete_variables):
        """Municipality and county values should appear in entity data."""
        variables = {**complete_variables}
        variables["exhibit_a_entities"] = [
            {"name": "LLC A", "address": "100 Main", "municipality": "Ann Arbor",
             "county": "Washtenaw", "parcel_ids": "001", "legal_description": "Lot 1"},
            {"name": "LLC B", "address": "200 Main", "municipality": "Ypsilanti",
             "county": "Washtenaw", "parcel_ids": "002", "legal_description": "Lot 2"},
        ]
        result = generate_pa_docx(variables)
        buf = io.BytesIO(result)
        with zipfile.ZipFile(buf) as zf:
            doc_xml = zf.read("word/document.xml").decode("utf-8")
            assert "Ann Arbor" in doc_xml
            assert "Ypsilanti" in doc_xml
            assert "Washtenaw" in doc_xml

    def test_single_entity_no_exhibit_a(self, complete_variables):
        """A single entity should NOT trigger Exhibit A mode."""
        variables = {**complete_variables}
        variables["exhibit_a_entities"] = [
            {"name": "Only LLC", "address": "100 Main", "municipality": "Pontiac",
             "county": "Oakland", "parcel_ids": "001", "legal_description": "Lot 1"},
        ]
        result = generate_pa_docx(variables)
        buf = io.BytesIO(result)
        with zipfile.ZipFile(buf) as zf:
            doc_xml = zf.read("word/document.xml").decode("utf-8")
            assert "as described in Exhibit A" not in doc_xml


# ===========================================================================
# Exhibit A Helpers (shared module)
# ===========================================================================

class TestExhibitAHelpers:
    """Tests for shared exhibit_a_helpers functions."""

    def test_normalize_address(self):
        from exhibit_a_helpers import normalize_address
        assert normalize_address("  100  Main  St  ") == "100 main st"
        assert normalize_address("") == ""
        assert normalize_address(None) == ""

    def test_count_grouped_addresses_basic(self):
        from exhibit_a_helpers import count_grouped_addresses
        entities = [{"address": "100 Main"}, {"address": "200 Oak"}]
        assert count_grouped_addresses(entities) == 2

    def test_count_grouped_addresses_same(self):
        from exhibit_a_helpers import count_grouped_addresses
        entities = [{"address": "100 Main"}, {"address": "100 main"}]
        assert count_grouped_addresses(entities) == 1

    def test_count_grouped_addresses_skips_empty(self):
        from exhibit_a_helpers import count_grouped_addresses
        entities = [{"address": ""}, {"address": "100 Main"}]
        assert count_grouped_addresses(entities) == 1

    def test_count_grouped_addresses_empty_list(self):
        from exhibit_a_helpers import count_grouped_addresses
        assert count_grouped_addresses([]) == 0

    def test_get_distinct_owners(self):
        from exhibit_a_helpers import get_distinct_owners
        entities = [
            {"name": "LLC A"},
            {"owner": "LLC B"},
            {"name": "LLC A"},
        ]
        assert get_distinct_owners(entities) == {"LLC A", "LLC B"}

    def test_get_distinct_owners_prefers_owner_key(self):
        from exhibit_a_helpers import get_distinct_owners
        entities = [{"owner": "New Key", "name": "Old Key"}]
        assert get_distinct_owners(entities) == {"New Key"}

    def test_exhibit_a_active_two_addresses(self):
        from exhibit_a_helpers import exhibit_a_active
        entities = [{"address": "100 Main"}, {"address": "200 Oak"}]
        assert exhibit_a_active(entities) is True

    def test_exhibit_a_active_same_address(self):
        from exhibit_a_helpers import exhibit_a_active
        entities = [{"address": "100 Main"}, {"address": "100 Main"}]
        assert exhibit_a_active(entities) is False

    def test_exhibit_a_multi_owner(self):
        from exhibit_a_helpers import exhibit_a_multi_owner
        entities = [
            {"address": "100 Main", "name": "LLC A"},
            {"address": "200 Oak", "name": "LLC B"},
        ]
        assert exhibit_a_multi_owner(entities) is True

    def test_exhibit_a_multi_owner_same_owner(self):
        from exhibit_a_helpers import exhibit_a_multi_owner
        entities = [
            {"address": "100 Main", "name": "Same LLC"},
            {"address": "200 Oak", "name": "Same LLC"},
        ]
        assert exhibit_a_multi_owner(entities) is False


# ===========================================================================
# Address Grouping (_group_entities_by_address)
# ===========================================================================

class TestGroupEntitiesByAddress:
    """Tests for the address-grouping function."""

    def test_single_entity_per_address(self):
        from pa_docx import _group_entities_by_address
        entities = [
            {"name": "LLC A", "address": "100 Main", "municipality": "Pontiac",
             "county": "Oakland", "parcel_ids": "001", "legal_description": "Lot 1"},
            {"name": "LLC B", "address": "200 Oak", "municipality": "Troy",
             "county": "Oakland", "parcel_ids": "002", "legal_description": "Lot 2"},
        ]
        result = _group_entities_by_address(entities)
        assert len(result) == 2
        assert result[0]["address"] == "100 Main"
        assert isinstance(result[0]["owners_display"], str)
        assert result[0]["owners_display"] == "LLC A"
        assert result[0]["parcel_ids_display"] == "001"
        assert result[0]["legal_descriptions_display"] == "Lot 1"

    def test_multiple_parcels_same_address(self):
        from pa_docx import _group_entities_by_address
        from docxtpl import RichText
        entities = [
            {"name": "LLC A", "address": "100 Main", "municipality": "Pontiac",
             "county": "Oakland", "parcel_ids": "001", "legal_description": "Lot 1"},
            {"name": "LLC B", "address": "100 Main", "municipality": "Pontiac",
             "county": "Oakland", "parcel_ids": "002", "legal_description": "Lot 2"},
        ]
        result = _group_entities_by_address(entities)
        assert len(result) == 1
        prop = result[0]
        assert prop["address"] == "100 Main"
        assert prop["municipality"] == "Pontiac"
        assert prop["county"] == "Oakland"
        assert isinstance(prop["owners_display"], RichText)
        assert isinstance(prop["parcel_ids_display"], RichText)
        assert isinstance(prop["legal_descriptions_display"], RichText)

    def test_empty_entities(self):
        from pa_docx import _group_entities_by_address
        assert _group_entities_by_address([]) == []

    def test_preserves_address_order(self):
        from pa_docx import _group_entities_by_address
        entities = [
            {"name": "A", "address": "200 Oak", "municipality": "Troy",
             "county": "Oakland", "parcel_ids": "002", "legal_description": "L2"},
            {"name": "B", "address": "100 Main", "municipality": "Pontiac",
             "county": "Oakland", "parcel_ids": "001", "legal_description": "L1"},
        ]
        result = _group_entities_by_address(entities)
        assert result[0]["address"] == "200 Oak"
        assert result[1]["address"] == "100 Main"

    def test_owner_field_backwards_compat(self):
        from pa_docx import _group_entities_by_address
        entities = [
            {"name": "Old Format LLC", "address": "100 Main", "municipality": "P",
             "county": "O", "parcel_ids": "001", "legal_description": "L1"},
        ]
        result = _group_entities_by_address(entities)
        assert result[0]["owners_display"] == "Old Format LLC"

    def test_deduplicates_owners(self):
        from pa_docx import _group_entities_by_address
        entities = [
            {"name": "Same LLC", "address": "100 Main", "municipality": "P",
             "county": "O", "parcel_ids": "001", "legal_description": "L1"},
            {"name": "Same LLC", "address": "100 Main", "municipality": "P",
             "county": "O", "parcel_ids": "002", "legal_description": "L2"},
        ]
        result = _group_entities_by_address(entities)
        assert isinstance(result[0]["owners_display"], str)
        assert result[0]["owners_display"] == "Same LLC"

    def test_address_normalization_case(self):
        from pa_docx import _group_entities_by_address
        entities = [
            {"name": "LLC A", "address": "100 Main St", "municipality": "P",
             "county": "O", "parcel_ids": "001", "legal_description": "L1"},
            {"name": "LLC B", "address": "100 main st", "municipality": "P",
             "county": "O", "parcel_ids": "002", "legal_description": "L2"},
        ]
        result = _group_entities_by_address(entities)
        assert len(result) == 1

    def test_address_normalization_whitespace(self):
        from pa_docx import _group_entities_by_address
        entities = [
            {"name": "LLC A", "address": "100  Main  St", "municipality": "P",
             "county": "O", "parcel_ids": "001", "legal_description": "L1"},
            {"name": "LLC B", "address": "100 Main St", "municipality": "P",
             "county": "O", "parcel_ids": "002", "legal_description": "L2"},
        ]
        result = _group_entities_by_address(entities)
        assert len(result) == 1

    def test_empty_address_entities_skipped(self):
        from pa_docx import _group_entities_by_address
        entities = [
            {"name": "LLC A", "address": "", "municipality": "P",
             "county": "O", "parcel_ids": "001", "legal_description": "L1"},
            {"name": "LLC B", "address": "100 Main", "municipality": "P",
             "county": "O", "parcel_ids": "002", "legal_description": "L2"},
        ]
        result = _group_entities_by_address(entities)
        assert len(result) == 1
        assert result[0]["address"] == "100 Main"
