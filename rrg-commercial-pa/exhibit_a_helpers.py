"""Shared helper functions for commercial PA.

Used by pa_docx.py, pa_handler.py, and draft_store.py to ensure
consistent Exhibit A, payment visibility, and field-exclusion logic.
"""


def normalize_address(addr) -> str:
    """Normalize an address for grouping: lowercase, collapse whitespace."""
    if not addr:
        return ""
    return " ".join(str(addr).lower().split())


def count_grouped_addresses(entities: list) -> int:
    """Count distinct addresses after normalization. Skips empty addresses."""
    addrs = set()
    for e in entities:
        if not isinstance(e, dict):
            continue
        norm = normalize_address(e.get("address", ""))
        if norm:
            addrs.add(norm)
    return len(addrs)


def get_distinct_owners(entities: list) -> set:
    """Get the set of distinct owner/name values across entities."""
    owners = set()
    for e in entities:
        if not isinstance(e, dict):
            continue
        owner = (e.get("owner") or e.get("name") or "").strip()
        if owner:
            owners.add(owner)
    return owners


def exhibit_a_active(entities: list) -> bool:
    """Return True if Exhibit A should be shown (2+ distinct addresses)."""
    return count_grouped_addresses(entities) >= 2


def exhibit_a_multi_owner(entities: list) -> bool:
    """Return True if there are multiple distinct owners across entities."""
    if not exhibit_a_active(entities):
        return False
    return len(get_distinct_owners(entities)) > 1


# ---------------------------------------------------------------------------
# Payment method field constants
# ---------------------------------------------------------------------------

LC_SUB_FIELDS = frozenset({
    "lc_down_payment", "lc_balance", "lc_interest_rate", "lc_interest_rate_words",
    "lc_amortization_years", "lc_balloon_months",
})

MIXED_PAYMENT_FIELDS = frozenset({
    "mortgage_pct", "mortgage_amount_words", "mortgage_amount_number",
    "lc_pct", "lc_amount_words", "lc_amount_number",
    "lc_subordinate",
})


def compute_payment_excluded_fields(variables: dict) -> set:
    """Compute which payment-related fields to exclude from remaining/completion.

    Uses `is True` checks (not truthiness) so that None (not yet answered)
    is treated differently from False (explicitly declined).

    Rules:
    - When any payment method is True, hide the booleans for unselected methods
    - When LC is not selected, hide all LC sub-fields
    - Mixed-payment fields only shown when BOTH mortgage AND LC are True
    - In mixed mode, lc_down_payment hidden (mortgage IS the down payment)
    - When nothing is selected, only mixed-payment fields are hidden
    """
    excluded = set()

    cash = variables.get("payment_cash")
    mortgage = variables.get("payment_mortgage")
    lc = variables.get("payment_land_contract")

    any_selected = cash is True or mortgage is True or lc is True

    if any_selected:
        # Hide payment booleans for methods not selected
        if cash is not True:
            excluded.add("payment_cash")
        if mortgage is not True:
            excluded.add("payment_mortgage")
        if lc is not True:
            excluded.add("payment_land_contract")

        # Hide LC sub-fields when LC is not selected
        if lc is not True:
            excluded |= LC_SUB_FIELDS

        # Mixed-payment fields only relevant when BOTH mortgage AND LC
        if not (mortgage is True and lc is True):
            excluded |= MIXED_PAYMENT_FIELDS

        # In mixed mode, down payment and balance are not used
        # (the mixed clause uses lc_amount_words/lc_amount_number instead)
        if mortgage is True and lc is True:
            excluded.add("lc_down_payment")
            excluded.add("lc_balance")
    else:
        # No method selected yet — only hide mixed fields (structurally
        # irrelevant until both mortgage+LC are explicitly selected)
        excluded |= MIXED_PAYMENT_FIELDS

    return excluded
