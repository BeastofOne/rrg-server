"""DOCX renderer for commercial purchase agreements.

Uses docxtpl to render the PA template with Jinja2-style variables.
Produces .docx bytes ready for download or attachment.
"""

import io
import os

from docxtpl import DocxTemplate

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
    to the singular form expected by the template.
    """
    out = dict(entity)
    if "legal_descriptions" in out and "legal_description" not in out:
        out["legal_description"] = out.pop("legal_descriptions")
    return out


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
