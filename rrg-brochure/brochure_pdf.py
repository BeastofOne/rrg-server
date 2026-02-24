"""Generate a property brochure PDF using Playwright (Chromium) + Jinja2."""

import glob
import os
import tempfile
from jinja2 import Environment, FileSystemLoader
from playwright.sync_api import sync_playwright


TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "templates")
STATIC_DIR = os.path.join(TEMPLATE_DIR, "static")


def _find_chrome_executable():
    """Find the Chrome/Chromium executable, checking env vars and Nix store paths."""
    # 1. Explicit env var
    path = os.environ.get("CHROMIUM_EXECUTABLE_PATH")
    if path and os.path.isfile(path):
        return path
    # 2. Search PLAYWRIGHT_BROWSERS_PATH for chromium-*/chrome-linux64/chrome
    browsers_path = os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "")
    if browsers_path:
        matches = glob.glob(os.path.join(browsers_path, "chromium-*/chrome-linux64/chrome"))
        if matches:
            return matches[0]
    # 3. Fall back to Playwright's default discovery
    return None

# Default static assets — used when the caller doesn't provide explicit paths
_DEFAULT_ASSETS = {
    "logo_path": os.path.join(STATIC_DIR, "rrg-logo.png"),
    "larry_photo_path": os.path.join(STATIC_DIR, "larry-headshot.png"),
    "jake_photo_path": os.path.join(STATIC_DIR, "jake-headshot.png"),
}


def generate_brochure_pdf(data: dict) -> bytes:
    """Render brochure data dict into a multi-page PDF.

    Expected data keys:
        property_name: str          - e.g. "Dairy Queen Grill & Chill"
        address_line1: str          - e.g. "1801 Washtenaw Ave"
        address_line2: str          - e.g. "Ypsilanti, MI 48197"
        price: str                  - e.g. "$850,000"
        highlights: list[str]       - 2-3 bullet points (cover page)
        investment_highlights: list[str]  - bullet points
        property_highlights: list[str]   - bullet points
        location_highlights: list[str]   - bullet points
        map_image_path: str|None    - path to a map screenshot (optional)
        photos: list[str]           - paths to property photos
        financials_pdf_path: str|None - path to P&L PDF image (optional)
        confidentiality_text: str|None  - override default legal text (optional)
        hero_image_path: str|None   - main cover photo path (optional)
        logo_path: str|None         - RRG logo path (optional)
        larry_photo_path: str|None  - Larry headshot path (optional)
        jake_photo_path: str|None   - Jake headshot path (optional)

    Returns raw PDF bytes.
    """
    # Resolve image paths to file:// URIs
    def to_uri(path):
        if path and os.path.isfile(path):
            return "file://" + os.path.abspath(path)
        return path or ""

    context = {
        "property_name": data.get("property_name", "Property"),
        "address_line1": data.get("address_line1", ""),
        "address_line2": data.get("address_line2", ""),
        "price": data.get("price", "$0"),
        "highlights": data.get("highlights", []),
        "investment_highlights": data.get("investment_highlights", []),
        "property_highlights": data.get("property_highlights", []),
        "location_highlights": data.get("location_highlights", []),
        "map_image": to_uri(data.get("map_image_path")),
        "photos": [to_uri(p) for p in data.get("photos", [])],
        "financials_image": to_uri(data.get("financials_pdf_path")),
        "confidentiality_text": data.get("confidentiality_text"),
        "hero_image": to_uri(data.get("hero_image_path")),
        "logo": to_uri(data.get("logo_path") or _DEFAULT_ASSETS["logo_path"]),
        "larry_photo": to_uri(data.get("larry_photo_path") or _DEFAULT_ASSETS["larry_photo_path"]),
        "jake_photo": to_uri(data.get("jake_photo_path") or _DEFAULT_ASSETS["jake_photo_path"]),
    }

    env = Environment(loader=FileSystemLoader(TEMPLATE_DIR))
    template = env.get_template("brochure.html")
    html_content = template.render(**context)

    # Write HTML to a temp file so Playwright can load it with the
    # correct base_url for resolving relative paths (static/, etc.)
    with tempfile.NamedTemporaryFile(
        suffix=".html", dir=TEMPLATE_DIR, delete=False, mode="w"
    ) as tmp:
        tmp.write(html_content)
        tmp_path = tmp.name

    try:
        with sync_playwright() as p:
            exec_path = _find_chrome_executable()
            launch_args = {"executable_path": exec_path} if exec_path else {}
            browser = p.chromium.launch(**launch_args)
            page = browser.new_page()
            page.goto(f"file://{tmp_path}", wait_until="networkidle")
            pdf_bytes = page.pdf(
                width="11in",
                height="8.5in",
                print_background=True,
                margin={"top": "0", "right": "0", "bottom": "0", "left": "0"},
            )
            browser.close()
    finally:
        os.unlink(tmp_path)

    return pdf_bytes
