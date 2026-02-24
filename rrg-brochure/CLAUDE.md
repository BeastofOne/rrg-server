# RRG Brochure Generator

## What
CRE property brochure generator. Flask microservice on port 8101, part of the jake-deploy Docker stack on rrg-server (100.97.86.99). Called by the message router (`f/switchboard/message_router`).

## LangGraph Workflow (10 nodes)

```
entry → [route_entry] → extract      → END   (new request with data)
                       → nudge        → END   (new request, no data)
                       → triage       → [route_triage] → edit         → END
                                                        → approve      → END (final PDF)
                                                        → preview      → END (draft PDF)
                                                        → question     → END
                                                        → cancel       → END
                                                        → photo_search → END
```

**Nodes:**
| Node | What it does |
|------|-------------|
| `entry` | Pass-through — routing via `route_entry` conditional edge |
| `extract` | LLM extracts brochure data from user message → JSON. Shows checklist |
| `nudge` | User in brochure mode but sent non-data message. LLM steers back |
| `triage` | Has existing data. LLM classifies: edit/approve/preview/question/cancel/search |
| `edit` | LLM applies changes to brochure JSON. Shows updated checklist |
| `approve` | Generates final PDF via `generate_brochure_pdf()`. Ends workflow |
| `preview` | Generates draft PDF without ending workflow (keeps `active=true`) |
| `question` | LLM answers question mid-workflow, preserves data |
| `cancel` | Ends workflow with no output |
| `photo_search` | Searches web for property photos → downloads → numbered contact sheet PDF |

## 8-Zone Completion Tracking (`BROCHURE_ZONES`)

Each zone has required fields and a checker function:

| Zone | Required fields | Complete when |
|------|----------------|---------------|
| Cover | `property_name`, `address_line1`, `price` | All three populated |
| Hero Photo | `hero_image_path` | Path set |
| Investment Highlights | `investment_highlights` | >= 3 items |
| Property Highlights | `property_highlights` | >= 3 items |
| Location Highlights | `location_highlights` | >= 3 items |
| Map Image | `map_image_path` | Path set |
| Photos | `photos` | >= 5 items |
| Financials (P&L) | `financials_pdf_path` | Path set |

The checklist is shown after every interaction so the user knows what's left.

## State Shape (`BrochureState` TypedDict)

```python
class BrochureState(TypedDict):
    command: str               # "create" | "continue"
    user_message: str
    chat_history: list         # [{"role": ..., "content": ...}]
    brochure_data: Optional[dict]
    # Outputs:
    response: str
    brochure_data_out: Optional[dict]
    brochure_active_out: bool
    pdf_bytes: Optional[bytes]
    pdf_filename: Optional[str]
    brochure_action: Optional[str]  # edit/approve/preview/cancel/question/search
```

## Photo Scraper (`photo_scraper.py`)

Three-phase approach:
1. **Find listing URLs** — `claude -p` with `--allowedTools WebSearch` (haiku, ~30s) finds Crexi, LoopNet, Zillow, Yelp, etc.
2. **Extract images** — Python `requests` fetches each page, regex extracts `src`/`data-src`/`background-image` URLs, filters junk (logos, icons, social media, ads)
3. **HEAD-check** — Parallel HEAD requests verify each URL is a real photo (>15KB, image content-type)

Key functions:
- `search_property_photos(name, address) → [{url, description, source}]`
- `_find_listing_urls()` — Claude CLI + WebSearch
- `_extract_imgs()` — Regex image URL extraction
- `_scrape_portal_site()` — Strict filtering for portal sites (GolfPass, Yelp, TripAdvisor)
- `_head_check()` — Verifies image is real (not icon/tiny)

Site tiers: listing sites (Crexi, LoopNet → trust all images) vs portal sites (Yelp, GolfPass → strict filter).

## Endpoint Contract

**`POST /process`** — Same contract as rrg-pnl (see root CLAUDE.md).

Request example:
```json
{
  "command": "create",
  "user_message": "Create a brochure for Dairy Queen at 1801 Washtenaw Ave, Ypsilanti MI 48197, asking $850,000",
  "chat_history": [],
  "state": {}
}
```

## PDF Generation

Two PDF generators:

**`brochure_pdf.py`** — `generate_brochure_pdf(data) → bytes`
- Jinja2 renders `templates/brochure.html`
- Playwright/Chromium renders to PDF (11"×8.5" landscape, zero margins)
- Resolves local file paths to `file://` URIs
- Default assets: RRG logo, Larry headshot, Jake headshot from `templates/static/`
- Filename: `YYYYMMDD_Brochure_<name>.pdf`

**`photo_search_pdf.py`** — `generate_photo_search_pdf(photos, name, address) → bytes`
- Downloads images from URLs to base64 data URIs
- Renders 2-column numbered grid via Playwright (Letter size)
- Users reference photos by number: "Use photo 3 as the hero"
- Filename: `YYYYMMDD_Photo_Search_<name>.pdf`

## Design Principles

Core rules for brochure layout/CSS:
- Two font families max (serif headings, sans-serif body)
- 2-3 brand colors + black/white
- Generous white space (min 0.6in margins for print)
- Consistent grid alignment across all pages
- One focal point per page

## Tech
- **Language:** Python
- **Build:** Nix flake
- **Framework:** LangGraph + Flask
- **Port:** 8101 (Docker network)
- **PDF renderer:** Playwright + Chromium (landscape 11"×8.5")
- **LLM:** `claude -p` via `ChatClaudeCLI` (env `CLAUDE_MODEL`, default "haiku")
- **Env vars:** `CLAUDE_CODE_OAUTH_TOKEN`, `CLAUDE_MODEL`, `CHROMIUM_EXECUTABLE_PATH`, `PLAYWRIGHT_BROWSERS_PATH`

## Deploy
```bash
nix build .#docker
scp result andrea@100.97.86.99:~/jake-images/rrg-brochure.tar.gz
ssh andrea@100.97.86.99 'docker load < ~/jake-images/rrg-brochure.tar.gz && cd ~/jake-deploy && docker compose -f docker-compose.jake.yml up -d'
```

## Local Dev
```bash
nix develop
python graph.py
```
