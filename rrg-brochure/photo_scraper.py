"""Scrape property photos from listing sites.

Two-phase approach:
  1. Use Claude CLI + WebSearch (haiku, ~30s) to find listing page URLs
  2. Fetch those pages in Python and extract image URLs with regex
  3. HEAD-check each candidate to verify it's a real photo (>15KB)

Works for any property type: commercial buildings, golf courses,
restaurants, duplexes, vacant land, etc.

Returns a list of {url, description, source} dicts for photo_search_pdf.
"""

import json
import re
import subprocess
import requests
from urllib.parse import urljoin, urlparse, unquote
from typing import List
from concurrent.futures import ThreadPoolExecutor, as_completed


_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
}

# ---------------------------------------------------------------------------
# Junk filtering — URL substrings that are never property photos
# ---------------------------------------------------------------------------
_SKIP_PATTERNS = [
    # UI elements
    "logo", "icon", "social", "avatar", "sprite", "nav-", "/nav/",
    "arrow", "chevron", "close", "button", "badge", "rating",
    "flag", "marker", "map-pin", "rss.", "play-btn",
    "placeholder", "loading", "spinner", "default-photo",
    "no-image", "noimage", "blank.", "spacer", "pixel.", "1x1",
    "tracking", "global-nav", "account", "signup", "login",
    # Social media domains embedded in image URLs
    "facebook.com", "twitter.com", "instagram.com",
    "youtube.com", "tiktok.com", "linkedin.com", "pinterest.com",
    # Beer/food/social apps (selfies, food, beer — never property photos)
    "untappd", "untp.beer",
    # Default/placeholder images
    "my-venue-image", "venue-header-temp", "default_avatar",
    "profile_pic", "user-photo", "member-photo",
    "/defaults/", "default@", "default-",
    # Pattern/texture images (decorative, not photos)
    "pattern", "texture", "-bg.", "background-",
    # Stock photo watermarks
    "unsplash", "shutterstock", "gettyimages", "istock",
    # Generic site builders (rarely property-specific)
    "parastorage.com", "wixstatic.com",
    # Ads
    "doubleclick", "googlesyndication", "adservice",
    "/ads/", "/ad-", "advertisement",
]

# Domains to skip entirely (never scrape these pages)
_SKIP_DOMAINS = [
    "untappd.com",       # beer check-in app
    "facebook.com",      # social media, mostly selfies
    "instagram.com",     # social media
    "twitter.com",       # social media
    "x.com",             # social media
    "tiktok.com",        # social media
    "reddit.com",        # forum, mixed content
]

# Minimum image file size in bytes — anything smaller is likely an icon/thumbnail
_MIN_IMAGE_BYTES = 15_000  # 15KB


def _is_junk(url: str) -> bool:
    lower = url.lower()
    if lower.endswith(".svg"):
        return True
    return any(p in lower for p in _SKIP_PATTERNS)


def _is_photo_url(url: str) -> bool:
    """Check if a URL looks like it points to a photo."""
    lower = url.lower()
    exts = (".jpg", ".jpeg", ".png", ".webp")
    # Standard image extensions
    if any(lower.split("?")[0].endswith(e) for e in exts):
        return True
    # CDN URLs with quality/resize params
    if "quality=" in lower or "/resize/" in lower or "/photo/" in lower:
        if any(e in lower for e in exts + ("/photo", "/image")):
            return True
    # Known image CDNs
    cdn_patterns = [
        ("brightspotcdn.com", "/dims"),
        ("imgeng.in", "/image/"),
        ("cloudinary.com", "/image/"),
        ("imgix.net", None),
        ("cloudfront.net", "/photo"),
        ("amazonaws.com", "/photo"),
        ("googleapis.com", "/photo"),
    ]
    for domain, path_hint in cdn_patterns:
        if domain in lower:
            if path_hint is None or path_hint in lower:
                return True
    return False


def _image_key(url: str) -> str:
    """Dedup key: identifies same image at different sizes."""
    lower = url.lower()
    # brightspotcdn hash
    m = re.search(r'/dims4/default/([a-f0-9]+)/', lower)
    if m:
        return m.group(1)
    # bazaarvoice photo ID
    m = re.search(r'bazaarvoice\.com/photo/\d+/([^/]+)', lower)
    if m:
        return m.group(1)
    # Cloudinary: extract the base image path (before transformations)
    m = re.search(r'cloudinary\.com/.+?/image/upload/(?:.*?/)?v\d+/(.+)', lower)
    if m:
        return m.group(1)
    # Strip common resize/quality params for dedup
    parsed = urlparse(url)
    path = re.sub(r'/resize/\d+x\d+', '', parsed.path)
    path = re.sub(r'/(?:thumb|small|medium|large|preview)/', '/', path)
    return parsed.netloc + path


def _fetch(url: str, timeout: int = 10) -> str:
    try:
        r = requests.get(url, headers=_HEADERS, timeout=timeout, allow_redirects=True)
        r.raise_for_status()
        return r.text
    except Exception:
        return ""


def _head_check(url: str) -> bool:
    """Quick HEAD request to verify the URL is a real photo (not a tiny icon)."""
    try:
        r = requests.head(url, headers=_HEADERS, timeout=5, allow_redirects=True)
        if r.status_code >= 400:
            return False
        content_type = r.headers.get("Content-Type", "")
        if content_type and "image" not in content_type:
            return False
        content_length = r.headers.get("Content-Length")
        if content_length and int(content_length) < _MIN_IMAGE_BYTES:
            return False
        return True
    except Exception:
        # If HEAD fails, still include it — the PDF generator will skip bad downloads
        return True


def _extract_imgs(html: str, base_url: str) -> List[str]:
    """Pull image URLs from HTML."""
    urls = set()
    # Standard image attributes
    for attr in ("src", "data-src", "data-original", "data-lazy-src",
                 "data-image", "data-bg", "data-background"):
        for match in re.findall(rf'{attr}=["\']([^"\']+)["\']', html, re.IGNORECASE):
            urls.add(urljoin(base_url, match))
    # CSS background-image
    for match in re.findall(r'url\(["\']?([^"\')\s]+)["\']?\)', html):
        urls.add(urljoin(base_url, match))
    # JSON-LD structured data (many listing sites embed image arrays)
    for match in re.findall(r'"(?:image|photo|contentUrl)"\s*:\s*"(https?://[^"]+)"', html):
        urls.add(match)
    # og:image meta tags
    for match in re.findall(r'content=["\']([^"\']+)["\']', html):
        if _is_photo_url(match):
            urls.add(urljoin(base_url, match))
    # Filter
    out = []
    for u in urls:
        if not _is_photo_url(u) or _is_junk(u):
            continue
        # Skip obviously tiny resize dimensions
        m = re.search(r'/resize/(\d+)x(\d+)', u)
        if m and (int(m.group(1)) < 300 or int(m.group(2)) < 200):
            continue
        # Skip tiny crop dimensions (brightspot CDN)
        m = re.search(r'/crop/(\d+)x(\d+)', u)
        if m and (int(m.group(1)) < 300 or int(m.group(2)) < 200):
            continue
        # Skip tiny dimension hints in URL like ?w=50&h=50
        m = re.search(r'[?&]w(?:idth)?=(\d+)', u)
        if m and int(m.group(1)) < 200:
            continue
        out.append(u)
    return out


def _source_name(url: str) -> str:
    """Human-readable source name from a page URL."""
    host = urlparse(url).netloc.replace("www.", "")
    names = {
        "golfpass.com": "GolfPass",
        "golfmichigan.com": "GolfMichigan",
        "golfnow.com": "GolfNow",
        "crexi.com": "Crexi",
        "loopnet.com": "LoopNet",
        "yelp.com": "Yelp",
        "yelpcdn.com": "Yelp",
        "google.com": "Google",
        "zillow.com": "Zillow",
        "realtor.com": "Realtor.com",
        "redfin.com": "Redfin",
        "apartments.com": "Apartments.com",
        "trulia.com": "Trulia",
        "michigan.org": "Michigan.org",
        "tripadvisor.com": "TripAdvisor",
    }
    for key, name in names.items():
        if key in host:
            return name
    # Fall back to domain name, capitalized
    parts = host.split(".")
    return parts[-2].title() if len(parts) >= 2 else host.title()


def _desc_from_url(url: str, source: str) -> str:
    path = urlparse(url).path
    fname = unquote(path.split("/")[-1])
    name = re.sub(r'\.(jpg|jpeg|png|webp)$', '', fname, flags=re.IGNORECASE)
    name = re.sub(r'[-_]', ' ', name)
    name = re.sub(r'\d{6,}', '', name).strip()
    if len(name) > 5:
        return name[:80]
    return "Property photo"


def _find_listing_urls(property_name: str, address: str) -> List[str]:
    """Use Claude CLI + WebSearch to find listing page URLs.

    The prompt is intentionally generic — it works for any property type.
    Claude will find whatever listing sites are relevant (Crexi for commercial,
    Zillow for residential, Yelp for businesses, etc.).

    Asks for multiple searches to maximize coverage since web search
    results vary per run.
    """
    prompt = (
        f'I need to find web pages with PHOTOS of this property:\n'
        f'  "{property_name}" at {address}\n\n'
        f'Do MULTIPLE searches to find as many listing pages as possible:\n'
        f'1. Search: "{property_name}" {address}\n'
        f'2. Search: "{property_name}" photos\n'
        f'3. Search: "{property_name}" site:crexi.com OR site:loopnet.com\n\n'
        f'Collect ALL unique page URLs from the results. '
        f'Good sources include: Crexi, LoopNet, Zillow, Realtor.com, Redfin, '
        f'CPIX, CoStar, CBRE, Google Business, Yelp, GolfPass, GolfNow, '
        f'the property own website, local news, directory sites.\n\n'
        f'EXCLUDE: Facebook, Instagram, Twitter/X, TikTok, Untappd, Reddit.\n\n'
        f'Return ONLY a JSON array of page URLs. No other text.\n'
        f'Example: ["https://www.crexi.com/properties/123456/...", '
        f'"https://www.zillow.com/homedetails/..."]'
    )
    urls = []
    try:
        result = subprocess.run(
            ["claude", "-p", prompt, "--model", "haiku",
             "--allowedTools", "WebSearch", "--no-chrome"],
            capture_output=True, text=True, timeout=60,
        )
        if result.returncode == 0:
            raw = result.stdout.strip()
            start = raw.find("[")
            end = raw.rfind("]")
            if start != -1 and end != -1:
                urls = json.loads(raw[start:end + 1])
    except Exception:
        pass
    return [u for u in urls if isinstance(u, str) and u.startswith("http")]


# ---------------------------------------------------------------------------
# Site-specific scrapers for sites that mix in lots of unrelated images
# ---------------------------------------------------------------------------

def _scrape_portal_site(html: str, base_url: str) -> List[str]:
    """For portal sites (GolfPass, GolfMichigan, etc.) that have promotional
    images from OTHER properties mixed in with the target property's photos.

    Strategy: only keep images that are clearly about the target property.
    Be strict — it's better to miss a few than include 20 wrong ones.
    """
    all_imgs = _extract_imgs(html, base_url)
    keepers = []
    for url in all_imgs:
        lower = url.lower()
        # User-submitted content (bazaarvoice, reviews) — always relevant
        if "bazaarvoice" in lower or "ugc" in lower:
            keepers.append(url)
            continue
        # Gallery/slideshow images — these are usually the target property
        if "gallery" in lower or "slideshow" in lower:
            keepers.append(url)
            continue
        # Course/property-specific ID in path (e.g. /courses/image/preview/86662.jpg)
        if re.search(r'/(?:course|prop|property|listing)s?/(?:image/)?(?:preview/)?[\d]+', lower):
            keepers.append(url)
            continue
        # Brightspot: check the CROP dimensions (not resize — resize upscales)
        # Real property photos have crop >= 1000px wide
        # Promotional thumbnails have crop like 526x296, 361x361, 192x108
        if "brightspotcdn" in lower:
            crop_m = re.search(r'/crop/(\d+)x(\d+)', lower)
            if crop_m and int(crop_m.group(1)) >= 1000:
                keepers.append(url)
            elif not crop_m:
                # No crop param — likely the original, keep it
                keepers.append(url)
            continue
        # Images with "original" or "large" in path
        if "/original/" in lower or "/large/" in lower:
            keepers.append(url)
            continue
    # If nothing matched, return nothing (don't fall back to all_imgs
    # on portal sites — too risky)
    return keepers


# Site tiers — determines how much we trust the images
# Tier 1: Listing sites — photos are specifically of the target property
_LISTING_SITES = [
    "crexi.com", "loopnet.com", "cpix.net", "costar.com",
    "zillow.com", "realtor.com", "redfin.com", "trulia.com",
    "apartments.com", "coldwellbanker.com", "cbre.com",
    "cushmanwakefield.com", "jll.com", "marcusmillichap.com",
    "berkshire.com", "century21.com", "kw.com",
]

# Tier 2: Portal/directory sites — have lots of unrelated promotional images
_PORTAL_SITES = [
    "golfpass.com", "golfmichigan.com", "golfnow.com",
    "golfdigest.com", "coursefinder.golf.com",
    "michigan.org", "tripadvisor.com", "yelp.com",
]


def search_property_photos(
    property_name: str,
    address: str,
) -> List[dict]:
    """Find photos of a property online.

    Phase 1: Use Claude + WebSearch to find listing URLs (~30s).
    Phase 2: Fetch each page and extract image URLs (~5-10s).
    Phase 3: HEAD-check each candidate to filter out icons/tiny images (~2-5s).

    Returns list of {url, description, source} dicts.
    """
    results = []
    seen_keys = {}

    def _add(url: str, desc: str, source: str):
        key = _image_key(url)
        # For resized images, prefer the largest version
        size = 0
        m = re.search(r'/resize/(\d+)x(\d+)', url)
        if m:
            size = int(m.group(1)) * int(m.group(2))
        if key in seen_keys:
            idx = seen_keys[key]
            old_m = re.search(r'/resize/(\d+)x(\d+)', results[idx]["url"])
            old_size = int(old_m.group(1)) * int(old_m.group(2)) if old_m else 0
            if size > old_size:
                results[idx] = {"url": url, "description": desc, "source": source}
            return
        seen_keys[key] = len(results)
        results.append({"url": url, "description": desc, "source": source})

    # Phase 1: Find listing URLs
    listing_urls = _find_listing_urls(property_name, address)

    # Phase 2: Scrape each URL (skip blocked domains)
    # Limit per source to avoid any single site flooding results
    _MAX_PER_SOURCE = 10
    source_counts = {}

    for page_url in listing_urls:
        if any(d in page_url for d in _SKIP_DOMAINS):
            continue
        html = _fetch(page_url)
        if not html:
            continue

        source = _source_name(page_url)
        is_listing = any(site in page_url for site in _LISTING_SITES)

        # Portal sites need special filtering to avoid cross-promoted images
        if any(site in page_url for site in _PORTAL_SITES):
            imgs = _scrape_portal_site(html, page_url)
        else:
            imgs = _extract_imgs(html, page_url)

        for img_url in imgs:
            # Enforce per-source limit (listing sites get more allowance)
            limit = _MAX_PER_SOURCE * 2 if is_listing else _MAX_PER_SOURCE
            if source_counts.get(source, 0) >= limit:
                break
            _add(img_url, _desc_from_url(img_url, source), source)
            source_counts[source] = source_counts.get(source, 0) + 1

    # Phase 3: HEAD-check all candidates in parallel to filter out tiny icons
    if results:
        verified = []
        with ThreadPoolExecutor(max_workers=10) as pool:
            futures = {
                pool.submit(_head_check, r["url"]): r
                for r in results
            }
            for future in as_completed(futures):
                r = futures[future]
                try:
                    if future.result():
                        verified.append(r)
                except Exception:
                    pass
        results = verified

    # Sort: listing-site photos first, then property websites, then portals
    def _sort_key(r):
        src = r["source"].lower()
        for site in _LISTING_SITES:
            if site.split(".")[0] in src:
                return 0  # listing sites first
        for site in _PORTAL_SITES:
            if site.split(".")[0] in src:
                return 2  # portal sites last
        return 1  # everything else in the middle

    results.sort(key=_sort_key)

    return results
