"""SQLite draft store for commercial purchase agreement drafts.

Manages persistent storage of PA drafts with CRUD operations,
variable merge semantics, and resume-by-address lookup.
"""

import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone

from exhibit_a_helpers import exhibit_a_active, exhibit_a_multi_owner

DB_PATH = os.getenv("PA_DB_PATH", "/data/pa_drafts.db")

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
    "broker_name", "broker_commission_description",
    "seller_broker_name", "seller_broker_company",
    # Offer Expiration
    "offer_expiration_time", "offer_expiration_ampm",
    "offer_expiration_day", "offer_expiration_year",
]


def _now_iso() -> str:
    """Return current UTC time as ISO 8601 string."""
    return datetime.now(timezone.utc).isoformat()


# Fields covered by Exhibit A when active
_EXHIBIT_A_PROPERTY_FIELDS = frozenset({
    "property_address", "property_parcel_ids", "property_legal_description",
    "property_municipality", "property_county", "property_location_type",
})
_EXHIBIT_A_SELLER_FIELDS = frozenset({
    "seller_name", "seller_address", "seller_entity_type",
})

_MIXED_PAYMENT_FIELDS = frozenset({
    "mortgage_pct", "mortgage_amount_words", "mortgage_amount_number",
    "lc_pct", "lc_amount_words", "lc_amount_number",
})


def _completion_pct(variables: dict) -> float:
    """Calculate percentage of ALL_VARIABLE_FIELDS that have non-None values.

    When Exhibit A is active (2+ entities), covered fields count as filled.
    """
    if not ALL_VARIABLE_FIELDS:
        return 0.0

    # Determine Exhibit A coverage
    entities = variables.get("exhibit_a_entities", [])
    covered = set()
    if exhibit_a_active(entities):
        covered |= _EXHIBIT_A_PROPERTY_FIELDS
        if exhibit_a_multi_owner(entities):
            covered |= _EXHIBIT_A_SELLER_FIELDS

    # Exclude mixed-payment fields when both methods aren't selected
    both_payment = variables.get("payment_mortgage") and variables.get("payment_land_contract")
    excluded = set()
    if not both_payment:
        excluded = _MIXED_PAYMENT_FIELDS

    countable = [f for f in ALL_VARIABLE_FIELDS if f not in excluded]
    if not countable:
        return 0.0
    filled = sum(
        1 for field in countable
        if field in covered or variables.get(field) is not None
    )
    return round(filled / len(countable) * 100, 1)


class DraftStore:
    """SQLite-backed CRUD store for purchase agreement drafts.

    Each draft has:
    - id: UUID string
    - property_address: text
    - variables: JSON dict of PA template variables
    - status: 'in_progress' | 'completed'
    - additional_provisions: JSON list of provision dicts
    - exhibit_a_entities: JSON list of entity dicts
    - created_at: ISO 8601 timestamp
    - updated_at: ISO 8601 timestamp
    """

    def __init__(self, db_path: str | None = None):
        self.db_path = db_path or DB_PATH
        self._init_table()

    def _connect(self) -> sqlite3.Connection:
        """Create a new SQLite connection."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_table(self):
        """Create the drafts table if it doesn't exist."""
        conn = self._connect()
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS drafts (
                    id TEXT PRIMARY KEY,
                    property_address TEXT NOT NULL,
                    variables TEXT NOT NULL DEFAULT '{}',
                    status TEXT NOT NULL DEFAULT 'in_progress',
                    additional_provisions TEXT,
                    exhibit_a_entities TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)
            conn.commit()
        finally:
            conn.close()

    def _row_to_dict(self, row: sqlite3.Row) -> dict:
        """Convert a sqlite3.Row to a plain dict with deserialized JSON fields."""
        d = dict(row)
        d["variables"] = json.loads(d["variables"]) if d["variables"] else {}
        d["additional_provisions"] = (
            json.loads(d["additional_provisions"])
            if d.get("additional_provisions")
            else None
        )
        d["exhibit_a_entities"] = (
            json.loads(d["exhibit_a_entities"])
            if d.get("exhibit_a_entities")
            else None
        )
        return d

    def create_draft(
        self,
        property_address: str,
        variables: dict,
        additional_provisions: list | None = None,
        exhibit_a_entities: list | None = None,
    ) -> str:
        """Create a new draft and return its UUID."""
        draft_id = str(uuid.uuid4())
        now = _now_iso()
        conn = self._connect()
        try:
            conn.execute(
                """
                INSERT INTO drafts
                    (id, property_address, variables, status,
                     additional_provisions, exhibit_a_entities,
                     created_at, updated_at)
                VALUES (?, ?, ?, 'in_progress', ?, ?, ?, ?)
                """,
                (
                    draft_id,
                    property_address,
                    json.dumps(variables),
                    json.dumps(additional_provisions) if additional_provisions is not None else None,
                    json.dumps(exhibit_a_entities) if exhibit_a_entities is not None else None,
                    now,
                    now,
                ),
            )
            conn.commit()
        finally:
            conn.close()
        return draft_id

    def load_draft(self, draft_id: str) -> dict | None:
        """Load a draft by ID. Returns None if not found."""
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT * FROM drafts WHERE id = ?", (draft_id,)
            ).fetchone()
            if row is None:
                return None
            return self._row_to_dict(row)
        finally:
            conn.close()

    def load_draft_by_address(self, address: str) -> dict | None:
        """Load the most recent in-progress draft for a property address.

        Returns None if no in-progress draft matches.
        """
        if not address:
            return None
        conn = self._connect()
        try:
            row = conn.execute(
                """
                SELECT * FROM drafts
                WHERE property_address = ? AND status = 'in_progress'
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (address,),
            ).fetchone()
            if row is None:
                return None
            return self._row_to_dict(row)
        finally:
            conn.close()

    def update_draft(
        self,
        draft_id: str,
        variables: dict,
        status: str | None = None,
        additional_provisions: list | None = None,
        exhibit_a_entities: list | None = None,
    ):
        """Update a draft's variables (merge), status, provisions, or exhibit A.

        Uses a single connection for read-merge-write to ensure atomicity.
        """
        conn = self._connect()
        try:
            # Read current state
            row = conn.execute(
                "SELECT * FROM drafts WHERE id = ?", (draft_id,)
            ).fetchone()
            if row is None:
                return

            # Merge variables
            existing_vars = json.loads(row["variables"]) if row["variables"] else {}
            existing_vars.update(variables)

            now = _now_iso()
            new_status = status if status is not None else row["status"]

            # Build update
            new_provisions = (
                json.dumps(additional_provisions)
                if additional_provisions is not None
                else row["additional_provisions"]
            )
            new_exhibit_a = (
                json.dumps(exhibit_a_entities)
                if exhibit_a_entities is not None
                else row["exhibit_a_entities"]
            )

            conn.execute(
                """
                UPDATE drafts
                SET variables = ?,
                    status = ?,
                    additional_provisions = ?,
                    exhibit_a_entities = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    json.dumps(existing_vars),
                    new_status,
                    new_provisions,
                    new_exhibit_a,
                    now,
                    draft_id,
                ),
            )
            conn.commit()
        finally:
            conn.close()

    def list_drafts(self) -> list[dict]:
        """List all drafts with summary info including completion percentage."""
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT id, property_address, variables, status FROM drafts ORDER BY created_at DESC"
            ).fetchall()
            result = []
            for row in rows:
                variables = json.loads(row["variables"]) if row["variables"] else {}
                result.append({
                    "id": row["id"],
                    "property_address": row["property_address"],
                    "status": row["status"],
                    "completion_pct": _completion_pct(variables),
                })
            return result
        finally:
            conn.close()

    def delete_draft(self, draft_id: str):
        """Delete a draft by ID. No-op if draft doesn't exist."""
        conn = self._connect()
        try:
            conn.execute("DELETE FROM drafts WHERE id = ?", (draft_id,))
            conn.commit()
        finally:
            conn.close()
