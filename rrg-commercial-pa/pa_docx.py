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


def _build_context(variables: dict) -> dict:
    """Build the template context from user-provided variables.

    - Missing/None string values default to ``""``
    - Missing/None bool values default to ``False``
    - Missing/None list values default to ``[]``
    - All other provided values are passed through as-is
    """
    ctx = {}

    for key, value in variables.items():
        if value is None:
            # Treat None same as missing — will be defaulted below
            continue
        ctx[key] = value

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
