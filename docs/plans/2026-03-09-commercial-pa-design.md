# Commercial Purchase Agreement Module — Design Doc

**Date:** 2026-03-09
**Module:** `rrg-commercial-pa`
**Status:** Design approved, pending implementation plan

---

## Overview

A new worker module that generates commercial purchase agreements (PAs) through conversational data extraction via the Streamlit UI in rrg-router. Users describe deal terms in natural language, the system extracts ~55 variables, and renders a `.docx` file using a Jinja2 template.

The module follows the exact same architecture as rrg-pnl and rrg-brochure: Nix-built Docker image, Flask microservice, LangGraph workflow, Claude CLI (`claude -p`) for LLM calls, and the standard `/process` worker contract.

---

## Architecture: Hybrid Stateless/Persistent

The router sees a standard worker (identical `/process` contract to rrg-pnl). Internally, the service uses **SQLite** for draft persistence. The `state` dict returned to the router is lightweight:

```json
{"draft_id": "uuid-here", "pa_active": true}
```

When the router sends the next message, the service loads the full draft from SQLite using that `draft_id`. This enables:
- **Save/resume:** `draft_id` survives across sessions
- **List drafts:** Service queries SQLite directly
- **Minimal router changes:** Router doesn't need to understand PA structure

---

## Template Engine: docxtpl

Uses [docxtpl](https://docxtpl.readthedocs.io/) (python-docx-template), which embeds Jinja2 syntax directly inside `.docx` files. This:
- Preserves all formatting/styles from the original Word document
- Supports dynamic table rows (Exhibit A with variable entity count)
- Supports conditional sections (checkboxes, payment method blocks)
- Outputs native `.docx` — no PDF conversion needed

The source template (`2026_0306_Commercial_PA_283 Unit Portfolio_Pontiac.docx`) will be converted into a blank Jinja2 template with `{{ variable_name }}` placeholders.

---

## Variable Schema (~55 variables)

### Party Variables
| Variable | Type | Description |
|----------|------|-------------|
| `effective_date_day` | int | Day of month |
| `effective_date_month` | str | Full month name |
| `effective_date_year` | int | Year |
| `purchaser_name` | str | Buyer entity name |
| `purchaser_entity_type` | str | e.g., "a Utah limited liability company" |
| `purchaser_address` | str | Full address |
| `purchaser_phone` | str | Phone number |
| `purchaser_email` | str | Email |
| `purchaser_fax` | str | Fax (blank if none) |
| `purchaser_copy_name` | str | CC recipient name |
| `purchaser_copy_address` | str | CC address |
| `purchaser_copy_phone` | str | CC phone |
| `purchaser_copy_email` | str | CC email |
| `seller_name` | str | Seller entity name |
| `seller_address` | str | Full address |
| `seller_phone` | str | Phone |
| `seller_email` | str | Email |
| `seller_fax` | str | Fax |
| `seller_copy_name` | str | CC recipient |
| `seller_copy_address` | str | CC address |
| `seller_copy_phone` | str | CC phone |
| `seller_copy_email` | str | CC email |

### Property Variables
| Variable | Type | Description |
|----------|------|-------------|
| `property_location_type` | enum | "City" / "Township" / "Village" |
| `property_municipality` | str | e.g., "Pontiac" |
| `property_county` | str | e.g., "Oakland" |
| `property_address` | str | Full street address with zip |
| `property_parcel_ids` | str | Tax parcel ID(s) |
| `property_legal_description` | str | Legal description |

### Financial Variables
| Variable | Type | Description |
|----------|------|-------------|
| `purchase_price_words` | str | Price in words |
| `purchase_price_number` | float | Numeric price |
| `payment_cash` | bool | Cash payment selected |
| `payment_mortgage` | bool | New mortgage selected |
| `payment_land_contract` | bool | Land contract selected |
| `lc_down_payment` | float | Land contract down payment |
| `lc_balance` | float | Land contract balance |
| `lc_interest_rate` | float | Interest rate (%) |
| `lc_amortization_years` | int | Amortization period |
| `lc_balloon_months` | int | Balloon payment months |
| `earnest_money_words` | str | Deposit in words |
| `earnest_money_number` | float | Numeric deposit |

### Title & Escrow
| Variable | Type | Description |
|----------|------|-------------|
| `title_company_name` | str | Title company |
| `title_company_address` | str | Title company address |
| `title_insurance_paid_by` | enum | "Seller" / "Purchaser" |
| `title_with_standard_exceptions` | bool | With/without standard exceptions |

### Due Diligence (checkboxes)
| Variable | Type | Description |
|----------|------|-------------|
| `dd_financing` | bool | Financing contingency |
| `dd_financing_days` | int | Days for financing |
| `dd_physical_inspection` | bool | Physical inspection |
| `dd_environmental` | bool | Environmental assessment |
| `dd_soil_tests` | bool | Soil/engineering tests |
| `dd_zoning` | bool | Zoning satisfaction |
| `dd_site_plan` | bool | Site plan approval |
| `dd_survey` | bool | Property survey |
| `dd_leases_estoppel` | bool | Leases and estoppel |
| `dd_other` | bool | Other due diligence |
| `dd_other_description` | str | Description of other DD |
| `dd_governmental` | bool | Governmental approvals |
| `inspection_period_days` | int | Inspection period length |

### Closing & Timeline
| Variable | Type | Description |
|----------|------|-------------|
| `closing_days` | int | Days to close |
| `closing_days_words` | str | Days in words |

### Broker
| Variable | Type | Description |
|----------|------|-------------|
| `broker_name` | str | Buyer's brokerage |
| `broker_commission_pct` | float | Commission percentage |
| `broker_commission_amount` | float | Commission dollar amount |
| `seller_broker_name` | str | Seller's agent name |
| `seller_broker_company` | str | Seller's brokerage |

### Offer Expiration
| Variable | Type | Description |
|----------|------|-------------|
| `offer_expiration_time` | str | Hour |
| `offer_expiration_ampm` | str | AM/PM |
| `offer_expiration_day` | str | Day and date |
| `offer_expiration_year` | str | Year |

### Additional Provisions
| Variable | Type | Description |
|----------|------|-------------|
| `additional_provisions` | list[dict] | Each: `{"title": str, "body": str}` |

Provisions are handled via a **clause library** (common predefined clauses like land contract subordination, licensed agent disclosure, processing fee, tax proration) **plus freeform LLM-drafted clauses** described in plain English.

### Exhibit A (dynamic rows)
| Variable | Type | Description |
|----------|------|-------------|
| `exhibit_a_entities` | list[dict] | Each: `{"name", "address", "parcel_ids", "legal_descriptions"}` |

Table grows dynamically to support multi-entity/multi-parcel portfolio deals.

---

## SQLite Schema

```sql
CREATE TABLE drafts (
    id TEXT PRIMARY KEY,
    property_address TEXT,
    variables JSON NOT NULL,
    additional_provisions JSON,
    exhibit_a_entities JSON,
    status TEXT DEFAULT 'in_progress',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

- Single table, JSON blob for variable values (null for unfilled)
- File at `/data/pa_drafts.db`, backed by a Docker named volume
- Drafts keyed by property address for listing/resuming
- Read-merge-write operations use a single SQLite connection to avoid race conditions

---

## LangGraph Workflow (11 nodes)

```
entry → [route_entry] → start_new    → END   (new draft, lists all variables)
                       → load_draft   → END   (resume existing draft, lists remaining)
                       → extract      → END   (user provided variable data)
                       → triage       → [route_triage] → edit       → END
                                                        → preview    → END (.docx)
                                                        → finalize   → END (final .docx)
                                                        → save       → END (pause)
                                                        → list_drafts→ END
                                                        → question   → END
                                                        → cancel     → END
```

### Nodes
| Node | What it does |
|------|-------------|
| `entry` | Pass-through — routing by `route_entry` conditional edge |
| `start_new` | Creates SQLite draft, returns full variable checklist |
| `load_draft` | Loads existing draft by property address, returns remaining variables |
| `extract` | LLM extracts variable values from natural language, updates draft in SQLite |
| `triage` | Classifies user message: edit/preview/finalize/save/list_drafts/question/cancel |
| `edit` | LLM applies targeted changes to specific variables |
| `preview` | Renders current draft into .docx via docxtpl, returns as base64 bytes |
| `finalize` | Renders final .docx, marks draft complete, returns bytes, sets `active=false` |
| `save` | Keeps draft in SQLite, sets `active=false` (router releases). Draft persists for later resume. |
| `list_drafts` | Returns all saved drafts with property addresses and completion percentage |
| `question` | Answers questions mid-workflow (e.g., "what's a typical earnest money?") |
| `cancel` | Deletes draft, sets `active=false` |

### Smart extraction behavior
The `extract` node accepts anything from a dump of 10 variables at once to "hi" (nudges for more info). After each extraction it returns:
1. Confirmation of what was filled
2. Remaining unfilled variables list (shrinks as info is provided)
3. Conversational prompt for the next most important missing info

---

## File Structure

```
rrg-commercial-pa/
├── CLAUDE.md
├── flake.nix
├── flake.lock
├── pyproject.toml
├── poetry.lock
├── server.py               # Flask: POST /process, GET /health
├── graph.py                # LangGraph: build_graph()
├── pa_handler.py           # Extract/edit/triage logic
├── pa_docx.py              # docxtpl rendering: generate_pa_docx(variables) → bytes
├── draft_store.py          # SQLite CRUD: create/load/update/list/delete
├── claude_llm.py           # Shared LLM wrapper (copied from rrg-pnl)
├── provisions.py           # Clause library: predefined + freeform
└── templates/
    └── commercial_pa.docx  # Blank Jinja2 template (docxtpl format)
```

---

## Nix Build

Mirrors rrg-pnl `flake.nix`:
- `poetry2nix` for Python deps (flask, langgraph, langchain-core, docxtpl, python-docx, lxml)
- `buildLayeredImage` for Docker
- `claude-code` binary included
- No WeasyPrint/LibreOffice — docxtpl produces .docx directly (pure Python)
- Port 8102

---

## Router Integration Changes

### rrg-router/config.py
- Add worker URL: `"commercial_pa": os.getenv("WORKER_PA_URL", "http://rrg-commercial-pa:8102")`
- Add intent: `"create_commercial_pa"` with handler `"commercial_pa"`

### rrg-router/app.py
- Support `.docx` file downloads alongside PDFs
- Detect MIME type from file extension (`.pdf` → `application/pdf`, `.docx` → `application/vnd.openxmlformats-officedocument.wordprocessingml.document`)
- Download button label: **"Download Preview"** (universal, no file-type mention)
- Capture handler name for label logic before `active_node` is cleared

### rrg-router/node_client.py (lines 46-65)
Currently only decodes `pdf_bytes` from worker responses. Add parallel handling for `docx_bytes`/`docx_filename`:

```python
# Existing (keep):
pdf_bytes = None
if data.get("pdf_bytes"):
    try:
        pdf_bytes = base64.b64decode(data["pdf_bytes"])
    except Exception:
        pass

# New — add after pdf_bytes block:
docx_bytes = None
if data.get("docx_bytes"):
    try:
        docx_bytes = base64.b64decode(data["docx_bytes"])
    except Exception:
        pass

return {
    "response": data.get("response", ""),
    "state": data.get("state", {}),
    "active": data.get("active", False),
    "pdf_bytes": pdf_bytes,
    "pdf_filename": data.get("pdf_filename"),
    "docx_bytes": docx_bytes,                  # new
    "docx_filename": data.get("docx_filename"), # new
    "error": None,
}
```

Also update the error/timeout return dicts to include `"docx_bytes": None, "docx_filename": None`.

### rrg-router/windmill_client.py
Same change: forward `docx_bytes`/`docx_filename` fields in response parsing, mirroring the node_client.py pattern above.

---

## Windmill Integration

### windmill/f/switchboard/message_router.flow/
- Add `commercial_pa` branch in `flow.yaml` (same pattern as `pnl` and `brochure` branches)
- Create `post_to_rrg-commercial-pa.inline_script.py` (copies pnl pattern)
- Update flow schema description to include `commercial_pa`
- Push with safe flags: `wmill sync push --skip-variables --skip-secrets --skip-resources`

---

## Docker Compose Changes

### deploy/docker-compose.yml
```yaml
rrg-commercial-pa:
    image: rrg-commercial-pa:latest
    container_name: rrg-commercial-pa
    restart: unless-stopped
    expose:
      - "8102"
    environment:
      - CLAUDE_CODE_OAUTH_TOKEN=${CLAUDE_CODE_OAUTH_TOKEN}
      - CLAUDE_MODEL=${CLAUDE_MODEL:-haiku}
    volumes:
      - pa-data:/data
    tmpfs:
      - /root/.claude:rw,size=50m
      - /tmp:rw
    networks:
      - windmill_default

# Add top-level volumes section (new — doesn't exist in current file):
volumes:
  pa-data:
```

Add `WORKER_PA_URL=http://rrg-commercial-pa:8102` to rrg-router's environment.

---

## Implementation Notes

- **Date formatting:** Use `f"{d.day}"` instead of `strftime("%-d")` for cross-platform safety (%-d is Linux-only, breaks on macOS dev)
- **claude_llm.py:** Fourth copy (pnl, brochure, router, pa). Matches existing pattern. Tech debt noted.
- **Flask dev server:** Single-threaded `app.run()` — SQLite concurrency is not an issue
- **Draft store:** All read-merge-write operations must use a single SQLite connection and transaction. Example pattern for `update_draft`:
  ```python
  conn = sqlite3.connect(DB_PATH)
  row = conn.execute("SELECT variables FROM drafts WHERE id = ?", (draft_id,)).fetchone()
  merged = {**json.loads(row[0]), **new_values}
  conn.execute("UPDATE drafts SET variables = ? WHERE id = ?", (json.dumps(merged), draft_id))
  conn.commit()
  conn.close()
  ```
  Never open a separate connection for the read — do it all in one.

---

## Decisions Log

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Architecture | Hybrid (standard /process, internal SQLite) | Clean encapsulation, no router changes beyond URL/intent |
| Template engine | docxtpl | Jinja2 in .docx, preserves formatting, supports loops/conditionals |
| Storage | SQLite | Embedded, zero-config, file-based, Docker volume for persistence |
| Draft key | Property address | Natural for CRE workflows |
| Additional provisions | Library + freeform LLM | Common clauses as toggles, plus describe custom ones in English |
| Exhibit A | Dynamic rows | Supports multi-entity portfolio deals |
| Windmill routing | Add branch to message_router flow | Consistent with pnl/brochure pattern |
| Download button label | "Download Preview" | Universal, no file-type detection needed in label |
| File output | .docx only (no PDF) | Brokers use Word; docxtpl outputs .docx directly |
