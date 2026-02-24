"""Generate a professional PDF P&L statement using WeasyPrint + Jinja2."""

import os
from datetime import date
from jinja2 import Environment, FileSystemLoader
from weasyprint import HTML
from pnl_handler import compute_pnl


TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "templates")


def generate_pnl_pdf(data: dict) -> bytes:
    """Render a P&L data dict into a professional PDF.

    Returns raw PDF bytes.
    """
    computed = compute_pnl(data)

    # Build period range string (default: prior calendar year)
    year = date.today().year - 1
    period_range = f"January 1st, {year} - December 31st, {year}"

    # Merge raw data with computed fields for the template
    context = {
        "property_name": data.get("property_name", "Property"),
        "property_address": data.get("property_address", ""),
        "period_range": period_range,
        "income": data.get("income", {}),
        "vacancy_rate": computed["vacancy_rate"],
        "vacancy_loss": computed["vacancy_loss"],
        "total_income": computed["total_income"],
        "effective_gross_income": computed["effective_gross_income"],
        "expenses": data.get("expenses", {}),
        "total_expenses": computed["total_expenses"],
        "net_income": computed["net_income"],
    }

    env = Environment(loader=FileSystemLoader(TEMPLATE_DIR))
    template = env.get_template("pnl.html")
    html_content = template.render(**context)

    pdf_bytes = HTML(string=html_content).write_pdf()
    return pdf_bytes
