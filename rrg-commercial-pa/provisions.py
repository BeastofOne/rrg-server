"""Clause library for commercial purchase agreement additional provisions.

Provides predefined clauses commonly used in Michigan commercial real estate
purchase agreements, with Jinja2 template rendering for variable substitution.
"""

from jinja2 import ChainableUndefined, Template

# ---------------------------------------------------------------------------
# Predefined clause library
# ---------------------------------------------------------------------------

_CLAUSES: list[dict] = [
    {
        "title": "Land Contract Subordination",
        "body": (
            "Seller agrees to subordinate the land contract to any primary "
            "mortgage obtained by Purchaser for the purpose of financing the "
            "acquisition of the Property, provided that the mortgage amount "
            "does not exceed the purchase price stated herein."
        ),
    },
    {
        "title": "Licensed Agent Disclosure",
        "body": (
            "The parties acknowledge that the Purchaser (or a principal of "
            "the Purchaser) is a licensed real estate agent in the State of "
            "Michigan and is acting as a principal in this transaction, not "
            "as an agent for any other party."
        ),
    },
    {
        "title": "Processing Fee",
        "body": (
            "A processing fee of {{ amount }} shall be charged to and paid "
            "by the Purchaser at closing."
        ),
    },
    {
        "title": "Tax Proration Waiver",
        "body": (
            "Seller hereby waives the right to any proration of real property "
            "taxes at closing. Purchaser shall be responsible for all real "
            "property taxes due and payable from and after the date of closing."
        ),
    },
    {
        "title": "Management Holdover",
        "body": (
            "Seller shall be permitted a holdover period of {{ days }} days "
            "following closing for the purpose of transitioning property "
            "management responsibilities to Purchaser or Purchaser's designee."
        ),
    },
]


def list_clauses() -> list[dict]:
    """Return all predefined clauses.

    Each clause is a dict with 'title' (str) and 'body' (str) keys.
    Body may contain Jinja2 template variables (e.g. ``{{ amount }}``).
    """
    return [dict(c) for c in _CLAUSES]


def get_clause(name: str) -> dict | None:
    """Return a clause by exact title, or None if not found.

    Parameters
    ----------
    name : str
        The exact title of the clause to retrieve.

    Returns
    -------
    dict | None
        A dict with 'title' and 'body' keys, or None if *name* is empty
        or does not match any predefined clause.
    """
    if not name:
        return None
    for clause in _CLAUSES:
        if clause["title"] == name:
            return dict(clause)
    return None


def render_clause(body_template: str, variables: dict) -> str:
    """Render a clause body template with variable substitution.

    Uses Jinja2 templating.  Missing variables render as empty strings
    rather than raising an exception.

    Parameters
    ----------
    body_template : str
        The clause body, possibly containing ``{{ variable }}`` placeholders.
    variables : dict
        Mapping of variable names to their values.

    Returns
    -------
    str
        The rendered clause body.
    """
    template = Template(body_template, undefined=ChainableUndefined)
    return template.render(**variables)
