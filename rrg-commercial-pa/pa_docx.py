"""DOCX renderer for commercial purchase agreements.

Uses docxtpl to render the PA template with Jinja2-style variables.
Produces .docx bytes ready for download or attachment.
"""

import io
import os

from docxtpl import DocxTemplate, RichText

from exhibit_a_helpers import normalize_address

TEMPLATE_PATH = os.path.join(os.path.dirname(__file__), "templates", "commercial_pa.docx")

# Boolean fields — default to False when missing/None
_BOOL_FIELDS = frozenset({
    "payment_cash",
    "payment_mortgage",
    "payment_land_contract",
    "title_with_standard_exceptions",
    "dd_financing",
    "dd_physical_inspection",
    "dd_environmental",
    "dd_soil_tests",
    "dd_zoning",
    "dd_site_plan",
    "dd_survey",
    "dd_leases_estoppel",
    "dd_other",
    "dd_governmental",
})

# List fields — default to [] when missing/None
_LIST_FIELDS = frozenset({
    "exhibit_a_entities",
    "additional_provisions",
})


def _normalize_entity(entity: dict) -> dict:
    """Normalize an Exhibit A entity dict for the template.

    The template uses ``entity.legal_description`` (singular) but callers
    may provide ``legal_descriptions`` (plural). This maps the plural key
    to the singular form expected by the template. Also ensures
    ``municipality`` and ``county`` keys exist.
    """
    out = dict(entity)
    if "legal_descriptions" in out and "legal_description" not in out:
        out["legal_description"] = out.pop("legal_descriptions")
    # Ensure municipality and county always present
    out.setdefault("municipality", "")
    out.setdefault("county", "")
    return out


def _multi_value_display(values: list[str]):
    """Return plain string for single value, RichText with bullets for multiple."""
    if not values:
        return ""
    if len(values) == 1:
        return values[0]
    rt = RichText()
    for i, v in enumerate(values):
        if i > 0:
            rt.add("\a")
        rt.add(f"\u2022 {v}")
    return rt


def _group_entities_by_address(entities: list[dict]) -> list[dict]:
    """Group flat entity dicts by address for Exhibit A rendering.

    Each entity represents one parcel. Entities at the same (normalized)
    address are grouped into a single row. Multi-value fields become
    RichText with bullet-point paragraphs; single values stay as strings.
    Entities with empty/missing addresses are skipped.
    """
    from collections import OrderedDict

    groups = OrderedDict()

    for entity in entities:
        raw_addr = entity.get("address", "")
        norm = normalize_address(raw_addr)
        if not norm:
            continue
        if norm not in groups:
            groups[norm] = {
                "display_addr": raw_addr.strip(),
                "municipality": entity.get("municipality", ""),
                "county": entity.get("county", ""),
                "owners": [],
                "parcel_ids": [],
                "legal_descriptions": [],
            }
        g = groups[norm]
        owner = (entity.get("owner") or entity.get("name") or "").strip()
        if owner and owner not in g["owners"]:
            g["owners"].append(owner)
        pid = (entity.get("parcel_ids") or entity.get("parcel_id") or "").strip()
        if pid:
            g["parcel_ids"].append(pid)
        legal = (entity.get("legal_description") or entity.get("legal_descriptions") or "").strip()
        if legal:
            g["legal_descriptions"].append(legal)

    result = []
    for norm, g in groups.items():
        result.append({
            "address": g["display_addr"],
            "municipality": g["municipality"],
            "county": g["county"],
            "owners_display": _multi_value_display(g["owners"]),
            "parcel_ids_display": _multi_value_display(g["parcel_ids"]),
            "legal_descriptions_display": _multi_value_display(g["legal_descriptions"]),
        })
    return result


def _apply_exhibit_a_logic(ctx: dict) -> None:
    """Set seller_intro, seller_address_intro, and use_exhibit_a based on entity count.

    Mutates *ctx* in place.

    Rules:
    - 0-1 entities: seller inline, no Exhibit A
    - 2+ entities, one distinct LLC name: seller inline, use_exhibit_a = True
    - 2+ entities, multiple distinct LLC names: seller = Exhibit A ref, use_exhibit_a = True
    """
    entities = ctx.get("exhibit_a_entities", [])

    if len(entities) < 2:
        # Single or no entities — inline seller info
        seller_name = ctx.get("seller_name", "")
        seller_entity_type = ctx.get("seller_entity_type", "")
        if seller_name and seller_entity_type:
            ctx["seller_intro"] = f"{seller_name}, {seller_entity_type}"
        elif seller_name:
            ctx["seller_intro"] = seller_name
        seller_addr = ctx.get("seller_address", "")
        if seller_addr:
            ctx["seller_address_intro"] = f"whose address is {seller_addr}"
        else:
            ctx["seller_address_intro"] = ""
        ctx["use_exhibit_a"] = False
        return

    # 2+ entities — Exhibit A is active
    ctx["use_exhibit_a"] = True

    # Check if multiple distinct LLC names
    distinct_names = set()
    for e in entities:
        name = e.get("name", "").strip()
        if name:
            distinct_names.add(name)

    if len(distinct_names) > 1:
        # Multiple LLCs — seller references Exhibit A
        ctx["seller_intro"] = "those entities set forth in Exhibit A"
        ctx["seller_address_intro"] = "whose addresses are also set forth in Exhibit A"
    else:
        # Single LLC, multiple properties — seller stays inline
        seller_name = ctx.get("seller_name", "")
        seller_entity_type = ctx.get("seller_entity_type", "")
        if seller_name and seller_entity_type:
            ctx["seller_intro"] = f"{seller_name}, {seller_entity_type}"
        elif seller_name:
            ctx["seller_intro"] = seller_name
        seller_addr = ctx.get("seller_address", "")
        if seller_addr:
            ctx["seller_address_intro"] = f"whose address is {seller_addr}"
        else:
            ctx["seller_address_intro"] = ""


_MONTH_NAMES = {
    "1": "January", "01": "January", "2": "February", "02": "February",
    "3": "March", "03": "March", "4": "April", "04": "April",
    "5": "May", "05": "May", "6": "June", "06": "June",
    "7": "July", "07": "July", "8": "August", "08": "August",
    "9": "September", "09": "September", "10": "October",
    "11": "November", "12": "December",
}


def _ordinal(n: str) -> str:
    """Convert a day number string to ordinal (e.g., '10' → '10th')."""
    n = n.strip().rstrip("stndrdth")
    try:
        num = int(n)
    except ValueError:
        return n
    if 11 <= (num % 100) <= 13:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(num % 10, "th")
    return f"{num}{suffix}"


def _build_context(variables: dict) -> dict:
    """Build the template context from user-provided variables.

    - Missing/None string values default to ``""``
    - Missing/None bool values default to ``False``
    - Missing/None list values default to ``[]``
    - Effective date day → ordinal, month → full name
    - All other provided values are passed through as-is
    """
    ctx = {}

    for key, value in variables.items():
        if value is None:
            continue
        ctx[key] = value

    # Normalize effective date formats
    if "effective_date_day" in ctx:
        ctx["effective_date_day"] = _ordinal(str(ctx["effective_date_day"]))
    if "effective_date_month" in ctx:
        month = str(ctx["effective_date_month"]).strip()
        ctx["effective_date_month"] = _MONTH_NAMES.get(month, month)

    # Default booleans
    for field in _BOOL_FIELDS:
        if field not in ctx:
            ctx[field] = False

    # Default lists
    for field in _LIST_FIELDS:
        if field not in ctx:
            ctx[field] = []

    # Normalize Exhibit A entities (legal_descriptions -> legal_description)
    if "exhibit_a_entities" in ctx and isinstance(ctx["exhibit_a_entities"], list):
        ctx["exhibit_a_entities"] = [
            _normalize_entity(e) if isinstance(e, dict) else e
            for e in ctx["exhibit_a_entities"]
        ]

    # Set safe fallback defaults before Exhibit A logic
    ctx.setdefault("seller_intro", ctx.get("seller_name", ""))
    ctx.setdefault("seller_address_intro", f"whose address is {ctx.get('seller_address', '')}" if ctx.get("seller_address") else "")
    ctx.setdefault("use_exhibit_a", False)

    # Apply conditional Exhibit A logic (overrides defaults above)
    _apply_exhibit_a_logic(ctx)

    return ctx


def generate_pa_docx(variables: dict) -> bytes:
    """Render the PA template with the given variables, return .docx bytes.

    Args:
        variables: Dict of PA field names to values. Missing fields are
            defaulted (strings to ``""``, booleans to ``False``, lists to ``[]``).

    Returns:
        Raw .docx file content as bytes.
    """
    doc = DocxTemplate(TEMPLATE_PATH)
    context = _build_context(variables)
    doc.render(context)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()
