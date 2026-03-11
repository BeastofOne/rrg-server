"""Shared Exhibit A helper functions.

Used by pa_docx.py, pa_handler.py, and draft_store.py to ensure
consistent "is Exhibit A active" and "multi-owner" logic.
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
