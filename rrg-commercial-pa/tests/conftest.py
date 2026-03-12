"""Shared fixtures for rrg-commercial-pa test suite."""

import json
import os
import sys
import pytest
from unittest.mock import MagicMock, patch

# Add the parent directory to sys.path so we can import the modules under test.
# When the implementation exists, these imports will resolve.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ---------------------------------------------------------------------------
# Mock LLM fixture — prevents any real subprocess / CLI calls
# ---------------------------------------------------------------------------

class MockAIMessage:
    """Mimics langchain_core.messages.AIMessage for mock returns."""
    def __init__(self, content: str):
        self.content = content


class MockLLMResponse:
    """Wraps MockAIMessage into a ChatResult-like object."""
    def __init__(self, content: str):
        self.content = content


def make_mock_llm(default_response: str = "{}"):
    """Create a mock ChatClaudeCLI that returns a fixed response.

    The mock's `.invoke()` returns an object with a `.content` attribute,
    matching the real ChatClaudeCLI behavior via LangChain.
    """
    mock = MagicMock()
    mock.invoke.return_value = MockAIMessage(default_response)
    return mock


@pytest.fixture
def mock_llm():
    """Provides a mock LLM that returns empty JSON by default.

    Patch target: 'claude_llm.ChatClaudeCLI' or the specific module's
    _get_llm function.
    """
    return make_mock_llm("{}")


# ---------------------------------------------------------------------------
# SQLite fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def db_path(tmp_path):
    """Returns a path to a fresh temporary SQLite database file."""
    return str(tmp_path / "test_drafts.db")


@pytest.fixture
def draft_store(db_path):
    """Creates a DraftStore connected to a temporary database."""
    from draft_store import DraftStore
    store = DraftStore(db_path)
    return store


# ---------------------------------------------------------------------------
# Complete variable sets for PA testing
# ---------------------------------------------------------------------------

@pytest.fixture
def complete_variables():
    """A fully-filled set of PA variables for rendering tests."""
    return {
        # Party — Purchaser
        "effective_date_day": 15,
        "effective_date_month": "March",
        "effective_date_year": 2026,
        "purchaser_name": "Acme Holdings LLC",
        "purchaser_entity_type": "a Michigan limited liability company",
        "purchaser_address": "100 Main St, Ann Arbor, MI 48104",
        "purchaser_phone": "(734) 555-0100",
        "purchaser_email": "buyer@acme.com",
        "purchaser_fax": "(734) 555-0101",
        "purchaser_copy_name": "Bob Smith, Esq.",
        "purchaser_copy_address": "200 Legal Way, Detroit, MI 48226",
        "purchaser_copy_phone": "(313) 555-0200",
        "purchaser_copy_email": "bob@legalway.com",
        # Party — Seller
        "seller_name": "Downtown Properties Inc",
        "seller_entity_type": "a Michigan corporation",
        "seller_address": "500 Commerce Blvd, Pontiac, MI 48342",
        "seller_phone": "(248) 555-0500",
        "seller_email": "seller@downtown.com",
        "seller_fax": "(248) 555-0501",
        "seller_copy_name": "Jane Doe, Attorney",
        "seller_copy_address": "600 Court St, Pontiac, MI 48342",
        "seller_copy_phone": "(248) 555-0600",
        "seller_copy_email": "jane@courtlaw.com",
        # Property
        "property_location_type": "City",
        "property_municipality": "Pontiac",
        "property_county": "Oakland",
        "property_address": "283 Unit Portfolio, 123 Main St, Pontiac, MI 48342",
        "property_parcel_ids": "14-01-234-001, 14-01-234-002",
        "property_legal_description": "Lots 1 and 2 of Supervisor's Plat No. 12",
        # Financial
        "purchase_price_words": "Two Million Five Hundred Thousand",
        "purchase_price_number": 2500000.00,
        "payment_cash": True,
        "payment_mortgage": False,
        "payment_land_contract": False,
        "mortgage_pct": "",
        "mortgage_amount_words": "",
        "mortgage_amount_number": "",
        "lc_pct": "",
        "lc_amount_words": "",
        "lc_amount_number": "",
        "lc_subordinate": False,
        "lc_down_payment": 0,
        "lc_balance": 0,
        "lc_interest_rate": 0,
        "lc_amortization_years": 0,
        "lc_balloon_months": 0,
        "earnest_money_words": "Fifty Thousand",
        "earnest_money_number": 50000.00,
        # Title & Escrow
        "title_company_name": "First American Title",
        "title_company_address": "700 Title Way, Pontiac, MI 48342",
        "title_insurance_paid_by": "Seller",
        "title_with_standard_exceptions": True,
        # Due Diligence
        "dd_financing": True,
        "dd_financing_days": 30,
        "dd_physical_inspection": True,
        "dd_environmental": True,
        "dd_soil_tests": True,
        "dd_zoning": True,
        "dd_site_plan": True,
        "dd_survey": True,
        "dd_leases_estoppel": True,
        "dd_other": True,
        "dd_other_description": "Phase I ESA review",
        "dd_governmental": True,
        "inspection_period_days": 45,
        # Closing
        "closing_days": 60,
        "closing_days_words": "Sixty",
        # Broker
        "broker_name": "Resource Realty Group",
        "broker_commission_description": "3% of the gross purchase price",
        "seller_broker_name": "John Agent",
        "seller_broker_company": "Keller Williams",
        # Offer Expiration
        "offer_expiration_time": "5:00",
        "offer_expiration_ampm": "PM",
        "offer_expiration_day": "Friday, March 20",
        "offer_expiration_year": "2026",
    }


@pytest.fixture
def partial_variables():
    """A partially-filled set of PA variables (only a few known)."""
    return {
        "purchaser_name": "Acme Holdings LLC",
        "property_address": "283 Unit Portfolio, 123 Main St, Pontiac, MI 48342",
        "purchase_price_number": 2500000.00,
    }


@pytest.fixture
def sample_provisions():
    """A list of additional provisions for testing."""
    return [
        {
            "title": "Land Contract Subordination",
            "body": "Seller agrees to subordinate the land contract to any first mortgage obtained by Purchaser.",
        },
        {
            "title": "Licensed Agent Disclosure",
            "body": "Purchaser is a licensed real estate agent in the State of Michigan.",
        },
        {
            "title": "Processing Fee",
            "body": "A processing fee of $395 shall be paid by Purchaser at closing.",
        },
    ]


@pytest.fixture
def sample_exhibit_a():
    """Sample Exhibit A entities for multi-entity portfolio deals."""
    return [
        {
            "name": "123 Main Street LLC",
            "address": "123 Main St, Pontiac, MI 48342",
            "municipality": "Pontiac",
            "county": "Oakland",
            "parcel_ids": "14-01-234-001",
            "legal_descriptions": "Lot 1 of Supervisor's Plat No. 12",
        },
        {
            "name": "125 Main Street LLC",
            "address": "125 Main St, Pontiac, MI 48342",
            "municipality": "Pontiac",
            "county": "Oakland",
            "parcel_ids": "14-01-234-002",
            "legal_descriptions": "Lot 2 of Supervisor's Plat No. 12",
        },
        {
            "name": "127 Main Street LLC",
            "address": "127 Main St, Pontiac, MI 48342",
            "municipality": "Troy",
            "county": "Oakland",
            "parcel_ids": "14-01-234-003",
            "legal_descriptions": "Lot 3 of Supervisor's Plat No. 12",
        },
    ]


# ---------------------------------------------------------------------------
# Flask test client fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def flask_client():
    """Create a Flask test client for the PA server."""
    # Patch build_graph before importing server to prevent real graph init
    with patch("graph.build_graph") as mock_build:
        mock_graph = MagicMock()
        mock_graph.invoke.return_value = {
            "response": "Test response",
            "draft_id": "test-uuid",
            "pa_active": True,
            "docx_bytes": None,
            "docx_filename": None,
        }
        mock_build.return_value = mock_graph

        from server import app
        app.config["TESTING"] = True
        with app.test_client() as client:
            yield client, mock_graph


# ---------------------------------------------------------------------------
# All variable field names (from the design doc schema)
# ---------------------------------------------------------------------------

ALL_VARIABLE_FIELDS = [
    # Party — Purchaser
    "effective_date_day", "effective_date_month", "effective_date_year",
    "purchaser_name", "purchaser_entity_type", "purchaser_address",
    "purchaser_phone", "purchaser_email", "purchaser_fax",
    "purchaser_copy_name", "purchaser_copy_address",
    "purchaser_copy_phone", "purchaser_copy_email",
    # Party — Seller
    "seller_name", "seller_entity_type", "seller_address",
    "seller_phone", "seller_email",
    "seller_fax", "seller_copy_name", "seller_copy_address",
    "seller_copy_phone", "seller_copy_email",
    # Property
    "property_location_type", "property_municipality", "property_county",
    "property_address", "property_parcel_ids", "property_legal_description",
    # Financial
    "purchase_price_words", "purchase_price_number",
    "payment_cash", "payment_mortgage", "payment_land_contract",
    "mortgage_pct", "mortgage_amount_words", "mortgage_amount_number",
    "lc_pct", "lc_amount_words", "lc_amount_number",
    "lc_subordinate",
    "lc_down_payment", "lc_balance", "lc_interest_rate",
    "lc_amortization_years", "lc_balloon_months",
    "earnest_money_words", "earnest_money_number",
    # Title & Escrow
    "title_company_name", "title_company_address",
    "title_insurance_paid_by", "title_with_standard_exceptions",
    # Due Diligence
    "dd_financing", "dd_financing_days",
    "dd_physical_inspection", "dd_environmental", "dd_soil_tests",
    "dd_zoning", "dd_site_plan", "dd_survey", "dd_leases_estoppel",
    "dd_other", "dd_other_description", "dd_governmental",
    "inspection_period_days",
    # Closing
    "closing_days", "closing_days_words",
    # Broker
    "broker_name", "broker_commission_pct", "broker_commission_amount",
    "seller_broker_name", "seller_broker_company",
    # Offer Expiration
    "offer_expiration_time", "offer_expiration_ampm",
    "offer_expiration_day", "offer_expiration_year",
]
