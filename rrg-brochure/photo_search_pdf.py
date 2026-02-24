"""Generate a numbered contact sheet PDF from photo search results.

Downloads images from URLs and lays them out in a numbered grid so the user
can reference photos by number (e.g., "use photo 3 as the hero").
"""

import glob
import io
import os
import tempfile
import base64
import requests
from typing import List, Optional
from playwright.sync_api import sync_playwright


def _find_chrome_executable():
    """Find the Chrome/Chromium executable, checking env vars and Nix store paths."""
    path = os.environ.get("CHROMIUM_EXECUTABLE_PATH")
    if path and os.path.isfile(path):
        return path
    browsers_path = os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "")
    if browsers_path:
        matches = glob.glob(os.path.join(browsers_path, "chromium-*/chrome-linux64/chrome"))
        if matches:
            return matches[0]
    return None


def _download_image(url: str, timeout: int = 15) -> Optional[bytes]:
    """Download an image from a URL. Returns bytes or None on failure."""
    try:
        resp = requests.get(url, timeout=timeout, headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) "
                          "Chrome/120.0.0.0 Safari/537.36",
        })
        resp.raise_for_status()
        content_type = resp.headers.get("content-type", "")
        if "image" in content_type or url.lower().endswith((".jpg", ".jpeg", ".png", ".webp", ".gif")):
            return resp.content
        # Some CDNs don't set content-type properly — accept if body looks like an image
        if resp.content[:4] in (b"\xff\xd8\xff", b"\x89PNG", b"RIFF", b"GIF8"):
            return resp.content
        return None
    except Exception:
        return None


def _image_to_data_uri(image_bytes: bytes) -> str:
    """Convert raw image bytes to a base64 data URI."""
    b64 = base64.b64encode(image_bytes).decode("ascii")
    # Detect format from magic bytes
    if image_bytes[:4] == b"\x89PNG":
        mime = "image/png"
    elif image_bytes[:2] == b"\xff\xd8":
        mime = "image/jpeg"
    elif image_bytes[:4] == b"RIFF":
        mime = "image/webp"
    elif image_bytes[:4] == b"GIF8":
        mime = "image/gif"
    else:
        mime = "image/jpeg"  # fallback
    return f"data:{mime};base64,{b64}"


def generate_photo_search_pdf(
    photos: List[dict],
    property_name: str = "",
    address: str = "",
) -> Optional[bytes]:
    """Generate a numbered contact sheet PDF from photo search results.

    Args:
        photos: List of dicts with keys:
            - url: str (image URL)
            - description: str (caption, e.g. "Exterior - front entrance")
            - source: str (where it was found, e.g. "Crexi", "LoopNet")
        property_name: Property name for the header.
        address: Property address for the header.

    Returns:
        PDF bytes, or None if no images could be downloaded.
    """
    # Download all images
    downloaded = []
    for i, photo in enumerate(photos):
        url = photo.get("url", "")
        if not url:
            continue
        img_bytes = _download_image(url)
        if img_bytes:
            downloaded.append({
                "number": len(downloaded) + 1,
                "data_uri": _image_to_data_uri(img_bytes),
                "description": photo.get("description", ""),
                "source": photo.get("source", ""),
                "url": url,
            })

    if not downloaded:
        return None

    # Build HTML
    photo_cards = []
    for p in downloaded:
        caption = f"<strong>#{p['number']}</strong>"
        if p["source"]:
            caption += f" &mdash; {p['source']}"
        if p["description"]:
            caption += f"<br>{p['description']}"

        photo_cards.append(f"""
        <div class="photo-card">
            <div class="photo-img">
                <img src="{p['data_uri']}" alt="Photo {p['number']}" />
            </div>
            <div class="photo-caption">{caption}</div>
        </div>
        """)

    header = property_name
    if address:
        header += f" &mdash; {address}"

    html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
    @page {{
        size: 8.5in 11in;
        margin: 0.5in;
    }}
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    body {{
        font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
        font-size: 10pt;
        color: #333;
        background: white;
    }}
    .header {{
        text-align: center;
        padding: 12pt 0 8pt 0;
        border-bottom: 2pt solid #1a3a5c;
        margin-bottom: 12pt;
    }}
    .header h1 {{
        font-size: 16pt;
        color: #1a3a5c;
        margin-bottom: 4pt;
    }}
    .header p {{
        font-size: 10pt;
        color: #666;
    }}
    .grid {{
        display: grid;
        grid-template-columns: 1fr 1fr;
        gap: 12pt;
    }}
    .photo-card {{
        border: 1pt solid #ddd;
        border-radius: 4pt;
        overflow: hidden;
        break-inside: avoid;
    }}
    .photo-img {{
        width: 100%;
        height: 200pt;
        overflow: hidden;
        background: #f5f5f5;
        display: flex;
        align-items: center;
        justify-content: center;
    }}
    .photo-img img {{
        width: 100%;
        height: 100%;
        object-fit: cover;
    }}
    .photo-caption {{
        padding: 6pt 8pt;
        font-size: 9pt;
        line-height: 1.3;
        background: #fafafa;
        border-top: 1pt solid #eee;
    }}
    .photo-caption strong {{
        font-size: 11pt;
        color: #1a3a5c;
    }}
    .footer {{
        text-align: center;
        font-size: 8pt;
        color: #999;
        padding-top: 8pt;
        margin-top: 12pt;
        border-top: 1pt solid #eee;
    }}
</style>
</head>
<body>
    <div class="header">
        <h1>Photo Search Results</h1>
        <p>{header} &mdash; {len(downloaded)} photos found</p>
    </div>
    <div class="grid">
        {"".join(photo_cards)}
    </div>
    <div class="footer">
        Reference photos by number. E.g., "Use photo 3 as the hero, photos 5, 8, 12 for the gallery."
    </div>
</body>
</html>"""

    # Render to PDF with Playwright
    with tempfile.NamedTemporaryFile(suffix=".html", delete=False, mode="w") as tmp:
        tmp.write(html)
        tmp_path = tmp.name

    try:
        with sync_playwright() as p:
            exec_path = _find_chrome_executable()
            launch_args = {"executable_path": exec_path} if exec_path else {}
            browser = p.chromium.launch(**launch_args)
            page = browser.new_page()
            page.goto(f"file://{tmp_path}", wait_until="networkidle")
            pdf_bytes = page.pdf(
                format="Letter",
                print_background=True,
                margin={"top": "0.5in", "right": "0.5in", "bottom": "0.5in", "left": "0.5in"},
            )
            browser.close()
    finally:
        os.unlink(tmp_path)

    return pdf_bytes
