# Commercial Lease Module Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build `rrg-commercial-lease`, a LangGraph worker that generates commercial lease PDFs from a variablized .docx template via conversational Q&A.

**Architecture:** Single Flask container following the rrg-pnl/rrg-brochure worker pattern. docxtpl fills a Jinja2-tagged .docx template, LibreOffice headless converts to PDF. SQLite persists drafts across sessions. Router dispatches via `POST /process`.

**Tech Stack:** Python 3.12, Flask, LangGraph, LangChain, docxtpl, LibreOffice headless, SQLite, Nix (poetry2nix + buildLayeredImage), Claude CLI (haiku)

**Design doc:** `docs/plans/2026-03-05-commercial-lease-design.md`

---

### Task 1: Project Scaffold

**Files:**
- Create: `rrg-commercial-lease/pyproject.toml`
- Create: `rrg-commercial-lease/claude_llm.py`
- Create: `rrg-commercial-lease/server.py`
- Create: `rrg-commercial-lease/CLAUDE.md`

**Step 1: Create pyproject.toml**

```toml
[tool.poetry]
name = "rrg-commercial-lease"
version = "0.1.0"
description = "RRG Commercial Lease Generator — Flask + LangGraph + docxtpl"
authors = ["Jake Phillips"]

[tool.poetry.dependencies]
python = "^3.12"
flask = ">=3.0"
langgraph = ">=0.2"
langchain-core = ">=0.3"
docxtpl = ">=0.18"
python-docx = ">=1.1"
num2words = ">=0.5"

[build-system]
requires = ["poetry-core"]
build-backend = "poetry.core.masonry.api"
```

**Step 2: Copy claude_llm.py from rrg-pnl**

Copy `rrg-pnl/claude_llm.py` → `rrg-commercial-lease/claude_llm.py` (identical file).

**Step 3: Create minimal server.py**

```python
"""RRG Commercial Lease Microservice — persistent Flask container.

Loads the Lease LangGraph once at startup. Container stays warm.
Exposes POST /process (standard worker node contract) and GET /health.
"""

import base64
import os
import traceback
from flask import Flask, request, jsonify

app = Flask(__name__)

# Graph loaded in Task 5 — placeholder for now
graph = None


@app.route("/process", methods=["POST"])
def process():
    """Standard worker node endpoint.

    Request:
        {
            command: str,           # "create" | "continue"
            user_message: str,
            chat_history: [...],
            state: {...}
        }

    Response:
        {
            response: str,
            state: {...},
            active: bool,
            pdf_bytes: str|null,
            pdf_filename: str|null
        }
    """
    data = request.json or {}
    command = data.get("command", "create")
    user_message = data.get("user_message", "")
    chat_history = data.get("chat_history", [])
    prev_state = data.get("state", {})

    graph_input = {
        "command": command,
        "user_message": user_message,
        "chat_history": chat_history,
        "draft_id": prev_state.get("draft_id"),
        "lease_vars": prev_state.get("lease_vars", {}),
        # Output fields
        "response": "",
        "lease_vars_out": None,
        "lease_active_out": True,
        "pdf_bytes": None,
        "pdf_filename": None,
        "draft_id_out": None,
        "lease_action": None,
    }

    try:
        result = graph.invoke(graph_input)
    except Exception as e:
        traceback.print_exc()
        return jsonify({
            "response": f"Error processing lease request: {e}",
            "state": prev_state,
            "active": prev_state.get("lease_active", True),
            "pdf_bytes": None,
            "pdf_filename": None,
        }), 500

    response_text = result.get("response", "")
    lease_vars_out = result.get("lease_vars_out")
    lease_active = result.get("lease_active_out", True)
    pdf_bytes_raw = result.get("pdf_bytes")
    pdf_filename = result.get("pdf_filename")
    draft_id = result.get("draft_id_out") or prev_state.get("draft_id")

    current_vars = lease_vars_out if lease_vars_out is not None else prev_state.get("lease_vars", {})
    if not lease_active:
        current_vars = {}

    pdf_b64 = None
    if pdf_bytes_raw:
        pdf_b64 = base64.b64encode(pdf_bytes_raw).decode("utf-8")

    return jsonify({
        "response": response_text,
        "state": {
            "lease_vars": current_vars,
            "lease_active": lease_active,
            "draft_id": draft_id,
        },
        "active": lease_active,
        "pdf_bytes": pdf_b64,
        "pdf_filename": pdf_filename,
    })


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "service": "rrg-commercial-lease"})


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8102"))
    print(f"rrg-commercial-lease starting on port {port}")
    app.run(host="0.0.0.0", port=port)
```

**Step 4: Create minimal CLAUDE.md**

```markdown
# RRG Commercial Lease Generator

## What
Commercial lease agreement generator. Flask microservice on port 8102.
Uses docxtpl to fill a .docx template with deal variables, LibreOffice headless for PDF.
SQLite for persistent draft storage.

## Tech
- **Language:** Python
- **Build:** Nix flake
- **Framework:** LangGraph + Flask
- **Port:** 8102 (Docker network)
- **Template engine:** docxtpl (Jinja2-in-Word)
- **PDF conversion:** LibreOffice headless
- **Draft storage:** SQLite on Docker volume
- **LLM:** `claude -p` via `ChatClaudeCLI` (env `CLAUDE_MODEL`, default "haiku")
```

**Step 5: Commit**

```bash
git add rrg-commercial-lease/
git commit -m "feat(lease): scaffold rrg-commercial-lease project"
```

---

### Task 2: Draft Store (SQLite)

**Files:**
- Create: `rrg-commercial-lease/draft_store.py`

**Step 1: Write draft_store.py**

```python
"""SQLite-backed persistent draft storage for lease agreements."""

import json
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional


DB_PATH = Path("/data/lease_drafts.db")


def _get_conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE IF NOT EXISTS drafts (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            variables TEXT NOT NULL DEFAULT '{}',
            status TEXT NOT NULL DEFAULT 'in_progress',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    conn.commit()
    return conn


def create_draft(name: str, variables: Optional[dict] = None) -> str:
    """Create a new draft. Returns the draft ID."""
    conn = _get_conn()
    draft_id = str(uuid.uuid4())[:8]
    now = datetime.utcnow().isoformat()
    conn.execute(
        "INSERT INTO drafts (id, name, variables, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
        (draft_id, name, json.dumps(variables or {}), "in_progress", now, now),
    )
    conn.commit()
    conn.close()
    return draft_id


def get_draft(draft_id: str) -> Optional[dict]:
    """Get a draft by ID. Returns None if not found."""
    conn = _get_conn()
    row = conn.execute("SELECT * FROM drafts WHERE id = ?", (draft_id,)).fetchone()
    conn.close()
    if row is None:
        return None
    return {
        "id": row["id"],
        "name": row["name"],
        "variables": json.loads(row["variables"]),
        "status": row["status"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def update_draft(draft_id: str, variables: dict, status: Optional[str] = None) -> None:
    """Update a draft's variables (merges with existing)."""
    conn = _get_conn()
    existing = get_draft(draft_id)
    if existing is None:
        conn.close()
        return
    merged = {**existing["variables"], **variables}
    now = datetime.utcnow().isoformat()
    if status:
        conn.execute(
            "UPDATE drafts SET variables = ?, status = ?, updated_at = ? WHERE id = ?",
            (json.dumps(merged), status, now, draft_id),
        )
    else:
        conn.execute(
            "UPDATE drafts SET variables = ?, updated_at = ? WHERE id = ?",
            (json.dumps(merged), now, draft_id),
        )
    conn.commit()
    conn.close()


def list_drafts(status: Optional[str] = "in_progress") -> list:
    """List all drafts, optionally filtered by status."""
    conn = _get_conn()
    if status:
        rows = conn.execute(
            "SELECT id, name, status, created_at, updated_at FROM drafts WHERE status = ? ORDER BY updated_at DESC",
            (status,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT id, name, status, created_at, updated_at FROM drafts ORDER BY updated_at DESC"
        ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def delete_draft(draft_id: str) -> None:
    """Delete a draft."""
    conn = _get_conn()
    conn.execute("DELETE FROM drafts WHERE id = ?", (draft_id,))
    conn.commit()
    conn.close()
```

**Step 2: Verify manually**

```bash
cd rrg-commercial-lease
python3 -c "
import sys; sys.path.insert(0, '.')
# Override DB_PATH for local testing
import draft_store; draft_store.DB_PATH = __import__('pathlib').Path('/tmp/test_drafts.db')
did = draft_store.create_draft('Test Lease')
print('Created:', did)
draft_store.update_draft(did, {'tenant_name': 'Bilal'})
print('Draft:', draft_store.get_draft(did))
print('List:', draft_store.list_drafts())
draft_store.delete_draft(did)
print('After delete:', draft_store.list_drafts())
"
```

Expected: creates, updates, lists, and deletes a draft successfully.

**Step 3: Commit**

```bash
git add rrg-commercial-lease/draft_store.py
git commit -m "feat(lease): add SQLite draft store"
```

---

### Task 3: Computed Fields — Rent Table & Utilities

**Files:**
- Create: `rrg-commercial-lease/lease_computed.py`

**Step 1: Write lease_computed.py**

This file handles all computed values: rent table generation, numbers-to-words, date math, and dollar formatting.

**Key fixes from code review:**
- `compute_lease_end_date` uses `calendar.monthrange` to handle month-end dates (no Feb 31 crash)
- `_count_months` walks month-by-month inclusively (no day-based approximation)
- CPI escalation: Year 1 shows actual numbers, Year 2+ shows "Per CPI Adjustment"
- Option periods: loop `num_options` times, each chains from prior period end
- Security deposit is user-provided (not computed from rent table)

```python
"""Computed fields for the commercial lease — rent table, date math, currency formatting."""

import calendar
from datetime import date, timedelta
from typing import Optional
from num2words import num2words


def dollars_to_words(amount: float) -> str:
    """Convert a dollar amount to legal written form.

    Example: 4433.33 → "Four Thousand Four Hundred Thirty-Three Dollars and 33/100"
    """
    whole = int(amount)
    cents = round((amount - whole) * 100)
    words = num2words(whole, to="cardinal").replace(",", "")
    # Title-case each word
    words = " ".join(w.capitalize() for w in words.split())
    if cents > 0:
        return f"{words} Dollars and {cents:02d}/100"
    return f"{words} Dollars"


def number_to_words(n: int) -> str:
    """Convert integer to written word. Example: 5 → 'five'."""
    return num2words(n, to="cardinal")


def format_currency(amount: float) -> str:
    """Format as $X,XXX.XX."""
    return f"${amount:,.2f}"


def format_date_legal(d: date) -> str:
    """Format date as 'Month Day, Year' for lease documents. Example: February 1, 2026."""
    return d.strftime("%B %-d, %Y")


def format_date_short(d: date) -> str:
    """Format date as MM/DD/YY for rent table. Example: 02/01/26."""
    return d.strftime("%m/%d/%y")


def _safe_date(year: int, month: int, day: int) -> date:
    """Create a date, clamping day to the max for that month.

    Handles month-end dates safely (e.g., Jan 31 + 1 month = Feb 28).
    """
    while month > 12:
        year += 1
        month -= 12
    max_day = calendar.monthrange(year, month)[1]
    return date(year, month, min(day, max_day))


def _count_months(start: date, end: date) -> int:
    """Count months inclusively by walking from start month to end month.

    March to June = 4 (March, April, May, June).
    """
    count = 0
    current_year = start.year
    current_month = start.month
    while (current_year, current_month) <= (end.year, end.month):
        count += 1
        current_month += 1
        if current_month > 12:
            current_month = 1
            current_year += 1
    return count


def compute_lease_end_date(commencement: date, years: int, months: int) -> date:
    """Compute lease end date from commencement + term.

    End date is the last day of the term (day before the anniversary).
    Example: Feb 1, 2026 + 5 years = Jan 31, 2031
    """
    end_year = commencement.year + years
    end_month = commencement.month + months
    # Normalize month overflow
    while end_month > 12:
        end_year += 1
        end_month -= 12
    # Anniversary date (clamped to valid day for that month)
    anniversary = _safe_date(end_year, end_month, commencement.day)
    return anniversary - timedelta(days=1)


def generate_rent_table(
    premises_sf: int,
    base_rate_psf: float,
    escalation_type: str,  # "none" | "fixed_percentage" | "CPI"
    escalation_rate: float,  # e.g., 0.03 for 3%
    lease_commencement: date,
    rent_commencement: date,
    lease_end: date,
    has_free_rent: bool = False,
    free_rent_end: Optional[date] = None,
    num_options: int = 0,
    option_term_years: int = 0,
    option_start_pct_above_trailing: float = 0.0,
    option_escalation_rate: float = 0.0,
) -> list:
    """Generate the rent schedule table rows.

    Returns list of dicts:
    [
        {
            "term_start": date,
            "term_end": date,
            "lease_rate": float or None,
            "monthly_rent": float or None,
            "term_rent": float or None,
            "is_free_rent": bool,
            "is_cpi": bool,
            "label": str or None,  # e.g., "Option 1 - Year 2"
        },
        ...
    ]
    """
    rows = []

    # Validate free rent doesn't overlap with rent commencement
    if has_free_rent and free_rent_end and free_rent_end >= rent_commencement:
        raise ValueError("Free rent end date must be before rent commencement date")

    # Row 0: Free rent period (if applicable)
    if has_free_rent and free_rent_end:
        rows.append({
            "term_start": lease_commencement,
            "term_end": free_rent_end,
            "lease_rate": None,
            "monthly_rent": None,
            "term_rent": None,
            "is_free_rent": True,
            "is_cpi": False,
            "label": None,
        })

    # Build list of escalation dates (lease anniversaries)
    anniv_month = lease_commencement.month
    anniv_day = lease_commencement.day
    escalation_dates = []
    year = lease_commencement.year
    while True:
        d = _safe_date(year, anniv_month, anniv_day)
        if d > lease_end:
            break
        escalation_dates.append(d)
        year += 1

    # Generate initial term paid periods
    current_rate = base_rate_psf
    period_start = rent_commencement
    is_first_paid = True

    for i, esc_date in enumerate(escalation_dates):
        if esc_date <= rent_commencement:
            if i > 0 and escalation_type == "fixed_percentage":
                current_rate = base_rate_psf * ((1 + escalation_rate) ** i)
                current_rate = round(current_rate, 2)
            continue

        period_end = esc_date - timedelta(days=1)
        if period_end > lease_end:
            period_end = lease_end

        if period_start <= period_end:
            months_in_period = _count_months(period_start, period_end)

            if escalation_type == "CPI" and not is_first_paid:
                rows.append({
                    "term_start": period_start,
                    "term_end": period_end,
                    "lease_rate": None,
                    "monthly_rent": None,
                    "term_rent": None,
                    "is_free_rent": False,
                    "is_cpi": True,
                    "label": None,
                })
            else:
                monthly = round(current_rate * premises_sf / 12, 2)
                term_rent = round(monthly * months_in_period, 2)
                rows.append({
                    "term_start": period_start,
                    "term_end": period_end,
                    "lease_rate": current_rate,
                    "monthly_rent": monthly,
                    "term_rent": term_rent,
                    "is_free_rent": False,
                    "is_cpi": False,
                    "label": None,
                })

            is_first_paid = False

        if escalation_type == "fixed_percentage":
            current_rate = round(current_rate * (1 + escalation_rate), 2)

        period_start = esc_date

    # Final period of initial term
    if period_start <= lease_end:
        months_in_period = _count_months(period_start, lease_end)
        if escalation_type == "CPI" and not is_first_paid:
            rows.append({
                "term_start": period_start,
                "term_end": lease_end,
                "lease_rate": None,
                "monthly_rent": None,
                "term_rent": None,
                "is_free_rent": False,
                "is_cpi": True,
                "label": None,
            })
        else:
            monthly = round(current_rate * premises_sf / 12, 2)
            term_rent = round(monthly * months_in_period, 2)
            rows.append({
                "term_start": period_start,
                "term_end": lease_end,
                "lease_rate": current_rate,
                "monthly_rent": monthly,
                "term_rent": term_rent,
                "is_free_rent": False,
                "is_cpi": False,
                "label": None,
            })

    # Option periods
    trailing_rate = current_rate
    option_period_end = lease_end
    for opt_num in range(1, num_options + 1):
        opt_start = option_period_end + timedelta(days=1)
        opt_end = compute_lease_end_date(opt_start, option_term_years, 0)
        opt_rate = round(trailing_rate * (1 + option_start_pct_above_trailing), 2)

        for opt_year in range(option_term_years):
            year_start = _safe_date(opt_start.year + opt_year, opt_start.month, opt_start.day)
            year_end_candidate = _safe_date(opt_start.year + opt_year + 1, opt_start.month, opt_start.day) - timedelta(days=1)
            year_end = min(year_end_candidate, opt_end)

            if year_start > opt_end:
                break

            months_in_period = _count_months(year_start, year_end)
            monthly = round(opt_rate * premises_sf / 12, 2)
            term_rent = round(monthly * months_in_period, 2)

            rows.append({
                "term_start": year_start,
                "term_end": year_end,
                "lease_rate": opt_rate,
                "monthly_rent": monthly,
                "term_rent": term_rent,
                "is_free_rent": False,
                "is_cpi": False,
                "label": f"Option {opt_num} - Year {opt_year + 1}",
            })

            if option_escalation_rate > 0:
                opt_rate = round(opt_rate * (1 + option_escalation_rate), 2)

        trailing_rate = opt_rate
        option_period_end = opt_end

    return rows
```

**Step 2: Verify rent table computation**

```bash
cd rrg-commercial-lease
python3 -c "
from datetime import date
from lease_computed import generate_rent_table, dollars_to_words, format_currency

# Match the example from the lease image: 1400 SF, \$19/SF, 3% escalation
rows = generate_rent_table(
    premises_sf=1400,
    base_rate_psf=19.00,
    escalation_type='fixed_percentage',
    escalation_rate=0.03,
    lease_commencement=date(2025, 12, 1),
    rent_commencement=date(2026, 2, 1),
    lease_end=date(2030, 1, 31),
    has_free_rent=True,
    free_rent_end=date(2026, 1, 1),
)
for r in rows:
    if r['is_free_rent']:
        print(f\"{r['term_start']} – {r['term_end']}: Free Base Rent\")
    else:
        print(f\"{r['term_start']} – {r['term_end']}: \${r['lease_rate']}/SF, {format_currency(r['monthly_rent'])}/mo, {format_currency(r['term_rent'])} term\")

print()
print(dollars_to_words(4433.33))
print(dollars_to_words(2216.67))
"
```

Expected output should closely match the rent table image:
- Free rent row: 2025-12-01 – 2026-01-01
- $19.00/SF → $2,216.67/mo
- $19.57/SF → $2,283.17/mo (3% escalation)
- Continuing through $21.38/SF
- dollars_to_words should produce "Four Thousand Four Hundred Thirty-Three Dollars and 33/100"

**Step 3: Iterate on rent table if numbers don't match the image exactly**

The rent table computation is the most critical piece — the numbers MUST match the image. Debug any discrepancies in `_months_between` or the escalation date logic.

**Step 4: Commit**

```bash
git add rrg-commercial-lease/lease_computed.py
git commit -m "feat(lease): add rent table computation and currency formatting"
```

---

### Task 4: Lease Variable Handler

**Files:**
- Create: `rrg-commercial-lease/lease_handler.py`

**Step 1: Write lease_handler.py**

This handles LLM-driven variable extraction, the variable checklist, and validation.

```python
"""Lease variable extraction, validation, and status display."""

import json
import os
from typing import Optional

from langchain_core.messages import SystemMessage, HumanMessage
from claude_llm import ChatClaudeCLI

CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "haiku")


# ---------------------------------------------------------------------------
# Variable definitions — required vs optional, with display names
# ---------------------------------------------------------------------------

REQUIRED_VARIABLES = {
    # Parties
    "landlord_name": "Landlord name",
    "landlord_address": "Landlord address",
    "tenant_name": "Tenant name",
    "tenant_address": "Tenant address",
    # Premises
    "premises_address": "Premises address",
    "premises_county": "Premises county",
    "premises_state": "Premises state",
    "premises_size_sf": "Premises size (SF)",
    # Term
    "lease_term_years": "Lease term (years)",
    "lease_commencement_date": "Lease commencement date",
    "rent_commencement_date": "Rent commencement date",
    # Rent
    "base_lease_rate_psf": "Base lease rate ($/SF/yr)",
    "lease_type": "Lease type (NNN/Modified Gross/Gross)",
    "rent_payment_address": "Rent payment address",
    # Use
    "permitted_use": "Permitted use of premises",
    # Signatures
    "tenant_signer_name": "Tenant signer name",
    "landlord_signer_name": "Landlord signer name",
    "landlord_signer_title": "Landlord signer title",
}

OPTIONAL_VARIABLES = {
    # Parties
    "landlord_is_llc": "Landlord is LLC?",
    "landlord_entity_type": "Landlord entity type",
    "landlord_llc_state": "Landlord LLC state",
    "tenant_is_llc": "Tenant is LLC?",
    "tenant_entity_type": "Tenant entity type",
    "tenant_llc_state": "Tenant LLC state",
    "tenant_entity_to_be_formed": "Entity to be formed?",
    # Term
    "lease_term_months": "Lease term (additional months)",
    "num_options": "Number of option periods",
    "option_term_years": "Option term (years)",
    "option_rent_basis": "Option rent basis",
    "option_notice_days": "Option notice period (days)",
    # Rent
    "rent_escalation_type": "Rent escalation type",
    "rent_escalation_rate": "Rent escalation rate (%)",
    "has_free_rent": "Free rent period?",
    "free_rent_end_date": "Free rent end date",
    "additional_rent_psf": "Additional rent ($/SF)",
    "tax_share_pct": "Tax share (%)",
    "insurance_share_pct": "Insurance share (%)",
    "late_fee_grace_days": "Late fee grace period (days)",
    "late_fee_pct": "Late fee (%)",
    "nsf_fee": "NSF fee ($)",
    # Security deposit
    "has_security_deposit": "Security deposit?",
    "security_deposit_total": "Security deposit total ($)",
    # Tenant responsibilities
    "hvac_repair_threshold": "HVAC repair threshold ($/yr)",
    # Taxes
    "tax_prorate_pct": "Tax prorate share (%)",
    # Insurance
    "liability_per_person": "Liability per person ($)",
    "liability_per_casualty": "Liability per casualty ($)",
    "property_damage_limit": "Property damage limit ($)",
    # Guaranty
    "has_personal_guaranty": "Personal guaranty?",
    "guarantor_name": "Guarantor name",
    # Optional clauses
    "has_ti_allowance": "Tenant improvement allowance?",
    "ti_allowance_psf": "TI allowance ($/SF)",
    "has_cam_cap": "CAM cap?",
    "cam_cap_pct": "CAM cap (%)",
    "has_early_termination": "Early termination clause?",
    "has_exclusive_use": "Exclusive use clause?",
    "exclusive_use_description": "Exclusive use description",
    "delivery_condition": "Delivery condition",
    "landlord_notice_address": "Landlord notice address",
    "governing_law_state": "Governing law state",
    "holdover_rent_multiplier": "Holdover rent multiplier",
    "landlord_entity_name": "Landlord entity name (for signature block)",
    "sic_number": "SIC number",
}


def _get_llm() -> ChatClaudeCLI:
    return ChatClaudeCLI(model_name=CLAUDE_MODEL)


EXTRACT_PROMPT = """You are a lease variable extractor. The user is building a commercial lease agreement.

Given the user's message, extract any lease-related variables you can identify. Return ONLY valid JSON with the variable names as keys.

Available variables and their types:
- landlord_name (string): Name of the landlord/property owner
- landlord_address (string): Landlord's full address
- landlord_is_llc (boolean): Whether landlord is an LLC
- landlord_entity_type (string): "LLC", "Corporation", "Partnership", "Trust", or "Individual"
- landlord_llc_state (string): State where LLC is incorporated
- tenant_name (string): Name of the tenant
- tenant_address (string): Tenant's full address
- tenant_is_llc (boolean): Whether tenant is an LLC
- tenant_entity_type (string): Same options as landlord
- tenant_llc_state (string): State where tenant LLC is incorporated
- tenant_entity_to_be_formed (boolean): Tenant signing for an entity to be formed
- premises_address (string): Full address of the leased space
- premises_county (string): County
- premises_state (string): State
- premises_size_sf (integer): Square footage
- lease_term_years (integer): Number of years in initial term
- lease_term_months (integer): Additional months beyond full years (0 if exact years)
- lease_commencement_date (string, YYYY-MM-DD): When lease obligations start
- rent_commencement_date (string, YYYY-MM-DD): When rent payments start
- base_lease_rate_psf (number): Starting rent in $/SF/year
- rent_escalation_type (string): "none", "fixed_percentage", or "CPI"
- rent_escalation_rate (number): Annual escalation as decimal (e.g. 0.03 for 3%)
- lease_type (string): "NNN", "Modified Gross", or "Gross"
- has_free_rent (boolean): Whether there's a free rent period
- free_rent_end_date (string, YYYY-MM-DD): End of free rent
- additional_rent_psf (number): Additional rent in $/SF (NNN/MG)
- tax_share_pct (number): Tenant's tax share as decimal (e.g. 0.50)
- insurance_share_pct (number): Tenant's insurance share as decimal
- rent_payment_address (string): Where rent checks are sent
- permitted_use (string): What the space can be used for
- num_options (integer): Number of renewal options
- option_term_years (integer): Years per option
- option_rent_basis (string): How option rent is determined
- has_security_deposit (boolean)
- security_deposit_total (number)
- has_personal_guaranty (boolean)
- guarantor_name (string)
- tenant_signer_name (string)
- landlord_signer_name (string)
- landlord_signer_title (string)
- landlord_entity_name (string)
- hvac_repair_threshold (number): Annual cap before landlord pays
- tax_prorate_pct (number): Tax prorate share as decimal
- liability_per_person (number)
- liability_per_casualty (number)
- property_damage_limit (number)
- delivery_condition (string): "as-is", "vanilla_shell", "turnkey", or custom
- has_ti_allowance (boolean)
- ti_allowance_psf (number)
- has_cam_cap (boolean)
- cam_cap_pct (number)
- has_early_termination (boolean)
- has_exclusive_use (boolean)
- exclusive_use_description (string)
- governing_law_state (string)
- holdover_rent_multiplier (number)
- landlord_notice_address (string)
- sic_number (string)
- late_fee_grace_days (integer)
- late_fee_pct (number)
- nsf_fee (number)
- option_notice_days (integer)

Current lease state (already filled):
{current_state}

Extract ONLY variables present in the user's message. Do not guess or infer values not stated.
Return JSON only — no explanation, no markdown."""


def extract_variables(user_message: str, current_vars: dict) -> dict:
    """Use LLM to extract lease variables from user's natural language input.

    Returns dict of extracted variable key-value pairs.
    """
    llm = _get_llm()
    state_str = json.dumps(current_vars, indent=2, default=str) if current_vars else "{}"

    response = llm.invoke([
        SystemMessage(content=EXTRACT_PROMPT.format(current_state=state_str)),
        HumanMessage(content=user_message),
    ])

    try:
        text = response.content.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
            text = text.rsplit("```", 1)[0]
        return json.loads(text.strip())
    except (json.JSONDecodeError, AttributeError):
        return {}


def format_status_checklist(current_vars: dict) -> str:
    """Generate a markdown checklist showing filled vs unfilled variables."""
    lines = ["**Lease Status:**\n"]

    # Required
    filled_req = 0
    total_req = len(REQUIRED_VARIABLES)
    lines.append("**Required:**")
    for key, label in REQUIRED_VARIABLES.items():
        val = current_vars.get(key)
        if val is not None and val != "":
            lines.append(f"  - [x] {label}: {val}")
            filled_req += 1
        else:
            lines.append(f"  - [ ] {label}")
    lines.append(f"\n*{filled_req}/{total_req} required fields filled*\n")

    # Show optional only if set or relevant
    set_optional = []
    for key, label in OPTIONAL_VARIABLES.items():
        val = current_vars.get(key)
        if val is not None and val != "":
            set_optional.append(f"  - {label}: {val}")
    if set_optional:
        lines.append("**Optional (set):**")
        lines.extend(set_optional)
        lines.append("")

    if filled_req == total_req:
        lines.append("**All required fields filled!** Say **finalize** to generate the final lease PDF, or **preview** to see a draft.")
    else:
        lines.append("Tell me more about this deal, or ask me anything about commercial leasing.")

    return "\n".join(lines)


def is_all_required_filled(current_vars: dict) -> bool:
    """Check if all required variables are filled."""
    for key in REQUIRED_VARIABLES:
        val = current_vars.get(key)
        if val is None or val == "":
            return False
    return True
```

**Step 2: Commit**

```bash
git add rrg-commercial-lease/lease_handler.py
git commit -m "feat(lease): add variable extraction and status checklist"
```

---

### Task 5: PDF Generation (docxtpl + LibreOffice)

**Files:**
- Create: `rrg-commercial-lease/lease_pdf.py`
- Create: `rrg-commercial-lease/templates/commercial_lease.docx` (placeholder — full template is Task 8)

**Step 1: Write lease_pdf.py**

```python
"""Generate lease PDF: docxtpl fills .docx template → LibreOffice headless converts to PDF."""

import os
import subprocess
import tempfile
from datetime import date
from pathlib import Path
from typing import Optional

from docxtpl import DocxTemplate

from lease_computed import (
    dollars_to_words,
    number_to_words,
    format_currency,
    format_date_legal,
    format_date_short,
    compute_lease_end_date,
    generate_rent_table,
)

TEMPLATE_PATH = Path(__file__).parent / "templates" / "commercial_lease.docx"


def _build_template_context(variables: dict, preview: bool = False) -> dict:
    """Build the full Jinja2 context dict for the docx template.

    In preview mode, unfilled fields render as [FIELD NAME] placeholder text.
    In final mode, all required fields must be present.
    """
    v = variables

    def get(key, default=None, label=None):
        """Get a variable, returning a red placeholder in preview mode if missing."""
        val = v.get(key, default)
        if val is None or val == "":
            if preview and label:
                return f"[{label}]"
            return default
        return val

    # Dates
    lease_commencement = _parse_date(v.get("lease_commencement_date"))
    rent_commencement = _parse_date(v.get("rent_commencement_date"))
    lease_term_years = int(v.get("lease_term_years", 0))
    lease_term_months = int(v.get("lease_term_months", 0))

    lease_end = None
    if lease_commencement:
        lease_end = compute_lease_end_date(lease_commencement, lease_term_years, lease_term_months)

    # Rent table
    rent_rows = []
    if all([v.get("premises_size_sf"), v.get("base_lease_rate_psf"), lease_commencement, rent_commencement, lease_end]):
        rent_rows = generate_rent_table(
            premises_sf=int(v["premises_size_sf"]),
            base_rate_psf=float(v["base_lease_rate_psf"]),
            escalation_type=v.get("rent_escalation_type", "none"),
            escalation_rate=float(v.get("rent_escalation_rate", 0)),
            lease_commencement=lease_commencement,
            rent_commencement=rent_commencement,
            lease_end=lease_end,
            has_free_rent=bool(v.get("has_free_rent")),
            free_rent_end=_parse_date(v.get("free_rent_end_date")),
        )

    # Format rent rows for template
    formatted_rows = []
    for row in rent_rows:
        if row["is_free_rent"]:
            formatted_rows.append({
                "term": f"{format_date_short(row['term_start'])} – {format_date_short(row['term_end'])}",
                "lease_rate": "",
                "monthly_rent": "Free Base Rent",
                "term_rent": "",
                "is_free_rent": True,
            })
        else:
            formatted_rows.append({
                "term": f"{format_date_short(row['term_start'])} – {format_date_short(row['term_end'])}",
                "lease_rate": format_currency(row["lease_rate"]),
                "monthly_rent": format_currency(row["monthly_rent"]),
                "term_rent": format_currency(row["term_rent"]),
                "is_free_rent": False,
            })

    # Security deposit computation
    first_month_rent = rent_rows[1]["monthly_rent"] if len(rent_rows) > 1 else 0
    deposit_total = float(v.get("security_deposit_total", first_month_rent * 2))
    first_month_prepay = first_month_rent
    deposit_amount = deposit_total - first_month_prepay

    # Option periods
    num_options = int(v.get("num_options", 0))
    option_start = None
    option_end = None
    if num_options > 0 and lease_end:
        option_start = lease_end + __import__("datetime").timedelta(days=1)
        option_years = int(v.get("option_term_years", 5))
        option_end = compute_lease_end_date(option_start, option_years, 0)

    context = {
        # Preview mode flag
        "preview": preview,

        # Lease date
        "lease_date": format_date_legal(date.today()),

        # Parties
        "landlord_name": get("landlord_name", label="LANDLORD NAME"),
        "landlord_is_llc": bool(v.get("landlord_is_llc")),
        "landlord_entity_type": get("landlord_entity_type", "LLC"),
        "landlord_llc_state": get("landlord_llc_state", label="LLC STATE"),
        "landlord_address": get("landlord_address", label="LANDLORD ADDRESS"),
        "tenant_name": get("tenant_name", label="TENANT NAME"),
        "tenant_is_llc": bool(v.get("tenant_is_llc")),
        "tenant_entity_type": get("tenant_entity_type", "LLC"),
        "tenant_llc_state": get("tenant_llc_state", label="LLC STATE"),
        "tenant_entity_to_be_formed": bool(v.get("tenant_entity_to_be_formed")),
        "tenant_address": get("tenant_address", label="TENANT ADDRESS"),

        # Premises
        "premises_county": get("premises_county", label="COUNTY"),
        "premises_state": get("premises_state", "Michigan"),
        "premises_address": get("premises_address", label="PREMISES ADDRESS"),
        "premises_size_sf": get("premises_size_sf", label="SIZE SF"),

        # Term
        "lease_term_years": lease_term_years,
        "lease_term_years_words": number_to_words(lease_term_years) if lease_term_years else "",
        "lease_term_months": lease_term_months,
        "lease_term_months_words": number_to_words(lease_term_months) if lease_term_months else "",
        "lease_commencement_date": format_date_legal(lease_commencement) if lease_commencement else get("lease_commencement_date", label="COMMENCEMENT DATE"),
        "rent_commencement_date": format_date_legal(rent_commencement) if rent_commencement else get("rent_commencement_date", label="RENT START DATE"),
        "lease_end_date": format_date_legal(lease_end) if lease_end else "[LEASE END DATE]",

        # Options
        "num_options": num_options,
        "num_options_words": number_to_words(num_options) if num_options else "zero",
        "option_term_years": int(v.get("option_term_years", 5)),
        "option_term_years_words": number_to_words(int(v.get("option_term_years", 5))),
        "option_start_date": format_date_legal(option_start) if option_start else "",
        "option_end_date": format_date_legal(option_end) if option_end else "",
        "option_rent_basis": get("option_rent_basis", "market rate"),
        "option_notice_days": int(v.get("option_notice_days", 90)),

        # Rent table
        "rent_rows": formatted_rows,

        # Rent details
        "lease_type": get("lease_type", "NNN"),
        "has_free_rent": bool(v.get("has_free_rent")),
        "free_rent_end_date": format_date_legal(_parse_date(v.get("free_rent_end_date"))) if v.get("free_rent_end_date") else "",
        "space_delivery_deadline": get("space_delivery_deadline", label="DELIVERY DEADLINE"),
        "free_rent_proration_month": get("free_rent_proration_month", label="PRORATION MONTH"),
        "additional_rent_psf": float(v.get("additional_rent_psf", 0)),
        "additional_rent_psf_words": dollars_to_words(float(v.get("additional_rent_psf", 0))) if v.get("additional_rent_psf") else "",
        "tax_share_pct": float(v.get("tax_share_pct", 0.5)),
        "insurance_share_pct": float(v.get("insurance_share_pct", 0)),
        "rent_payment_address": get("rent_payment_address", label="PAYMENT ADDRESS"),
        "late_fee_grace_days": int(v.get("late_fee_grace_days", 7)),
        "late_fee_pct": float(v.get("late_fee_pct", 0.05)),
        "consecutive_late_threshold": int(v.get("consecutive_late_threshold", 3)),
        "nsf_fee": float(v.get("nsf_fee", 40)),

        # Security deposit
        "has_security_deposit": v.get("has_security_deposit", True),
        "security_deposit_total": deposit_total,
        "security_deposit_total_words": dollars_to_words(deposit_total),
        "security_deposit_total_formatted": format_currency(deposit_total),
        "first_month_prepay": first_month_prepay,
        "first_month_prepay_words": dollars_to_words(first_month_prepay),
        "first_month_prepay_formatted": format_currency(first_month_prepay),
        "security_deposit_amount": deposit_amount,
        "security_deposit_amount_words": dollars_to_words(deposit_amount),
        "security_deposit_amount_formatted": format_currency(deposit_amount),
        "deposit_replenishment_days": int(v.get("deposit_replenishment_days", 10)),

        # Use
        "permitted_use": get("permitted_use", label="PERMITTED USE"),

        # Tenant responsibilities
        "hvac_repair_threshold": float(v.get("hvac_repair_threshold", 2000)),
        "hvac_repair_threshold_formatted": format_currency(float(v.get("hvac_repair_threshold", 2000))),
        "has_plumbing_clause": bool(v.get("has_plumbing_clause", True)),
        "has_window_glass_clause": bool(v.get("has_window_glass_clause", True)),
        "hvac_contract_days": int(v.get("hvac_contract_days", 30)),

        # Taxes
        "tax_prorate_pct": float(v.get("tax_prorate_pct", 0.5)),
        "tax_payment_days": int(v.get("tax_payment_days", 30)),

        # Insurance
        "liability_per_person": float(v.get("liability_per_person", 1000000)),
        "liability_per_person_formatted": format_currency(float(v.get("liability_per_person", 1000000))),
        "liability_per_person_words": dollars_to_words(float(v.get("liability_per_person", 1000000))),
        "liability_per_casualty": float(v.get("liability_per_casualty", 2000000)),
        "liability_per_casualty_formatted": format_currency(float(v.get("liability_per_casualty", 2000000))),
        "liability_per_casualty_words": dollars_to_words(float(v.get("liability_per_casualty", 2000000))),
        "property_damage_limit": float(v.get("property_damage_limit", 500000)),
        "property_damage_limit_formatted": format_currency(float(v.get("property_damage_limit", 500000))),
        "property_damage_limit_words": dollars_to_words(float(v.get("property_damage_limit", 500000))),

        # Environmental
        "sic_number": get("sic_number", ""),

        # Entry & inspections
        "landlord_entry_notice_hours": int(v.get("landlord_entry_notice_hours", 24)),
        "for_rent_sign_days": int(v.get("for_rent_sign_days", 60)),

        # Holding over
        "holdover_rent_multiplier": get("holdover_rent_multiplier", "double"),

        # Notification
        "landlord_notice_address": get("landlord_notice_address") or get("landlord_address", label="NOTICE ADDRESS"),

        # Applicable law
        "governing_law_state": get("governing_law_state") or get("premises_state", "Michigan"),

        # Estoppel
        "estoppel_notice_days": int(v.get("estoppel_notice_days", 15)),

        # Personal guaranty
        "has_personal_guaranty": bool(v.get("has_personal_guaranty", True)),
        "guarantor_name": get("guarantor_name") or get("tenant_signer_name", label="GUARANTOR"),

        # Signature block
        "tenant_signer_name": get("tenant_signer_name", label="TENANT SIGNER"),
        "landlord_signer_name": get("landlord_signer_name", label="LANDLORD SIGNER"),
        "landlord_signer_title": get("landlord_signer_title", label="TITLE"),
        "landlord_entity_name": get("landlord_entity_name") or get("landlord_name", label="LANDLORD ENTITY"),

        # Optional clauses
        "has_ti_allowance": bool(v.get("has_ti_allowance")),
        "ti_allowance_psf": float(v.get("ti_allowance_psf", 0)),
        "ti_allowance_total": float(v.get("ti_allowance_psf", 0)) * int(v.get("premises_size_sf", 0)),
        "has_cam_cap": bool(v.get("has_cam_cap")),
        "cam_cap_pct": float(v.get("cam_cap_pct", 0)),
        "has_early_termination": bool(v.get("has_early_termination")),
        "has_exclusive_use": bool(v.get("has_exclusive_use")),
        "exclusive_use_description": get("exclusive_use_description", ""),
        "delivery_condition": get("delivery_condition", "as-is"),
    }

    return context


def _parse_date(val) -> Optional[date]:
    """Parse a date from string (YYYY-MM-DD) or return as-is if already a date."""
    if val is None:
        return None
    if isinstance(val, date):
        return val
    try:
        parts = str(val).split("-")
        return date(int(parts[0]), int(parts[1]), int(parts[2]))
    except (ValueError, IndexError):
        return None


def generate_lease_pdf(variables: dict, preview: bool = False) -> bytes:
    """Generate a lease PDF from variables.

    Args:
        variables: Dict of lease variable key-value pairs.
        preview: If True, unfilled fields show as [FIELD NAME] placeholders.

    Returns:
        Raw PDF bytes.
    """
    context = _build_template_context(variables, preview=preview)

    # Fill the docx template
    doc = DocxTemplate(str(TEMPLATE_PATH))
    doc.render(context)

    # Write filled docx to temp file
    with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as tmp:
        doc.save(tmp.name)
        docx_path = tmp.name

    # Convert to PDF via LibreOffice headless
    pdf_path = docx_path.replace(".docx", ".pdf")
    try:
        subprocess.run(
            [
                "libreoffice", "--headless", "--norestore",
                "--convert-to", "pdf",
                "--outdir", os.path.dirname(docx_path),
                docx_path,
            ],
            capture_output=True,
            timeout=30,
            check=True,
        )

        with open(pdf_path, "rb") as f:
            pdf_bytes = f.read()

        return pdf_bytes

    finally:
        # Clean up temp files
        for p in [docx_path, pdf_path]:
            try:
                os.unlink(p)
            except OSError:
                pass


def get_lease_filename(variables: dict) -> str:
    """Generate the PDF filename from lease variables."""
    today = date.today().strftime("%Y%m%d")
    address = variables.get("premises_address", "").strip()
    if not address:
        address = "Commercial Lease"
    parts = [p.strip() for p in address.split(",")]
    short_address = " ".join(parts[:2]) if len(parts) >= 2 else parts[0]
    return f"{today}_Commercial Lease_{short_address}.pdf"
```

**Step 2: Commit**

```bash
git add rrg-commercial-lease/lease_pdf.py
git commit -m "feat(lease): add PDF generation with docxtpl + LibreOffice"
```

---

### Task 6: LangGraph Workflow

**Files:**
- Create: `rrg-commercial-lease/graph.py`

**Step 1: Write graph.py**

```python
"""LangGraph workflow for the commercial lease generator.

Nodes: entry, list_drafts, create_new, resume_draft, extract, triage,
       edit, preview, finalize, question, status, cancel.
"""

import json
import os
from typing import TypedDict, Optional

from langgraph.graph import StateGraph, END
from langchain_core.messages import SystemMessage, HumanMessage

from claude_llm import ChatClaudeCLI
from lease_handler import (
    extract_variables,
    format_status_checklist,
    is_all_required_filled,
)
from lease_pdf import generate_lease_pdf, get_lease_filename
from draft_store import create_draft, get_draft, update_draft, list_drafts

CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "haiku")


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

class LeaseState(TypedDict):
    command: str               # "create" | "continue"
    user_message: str
    chat_history: list
    draft_id: Optional[str]
    lease_vars: Optional[dict]

    # Outputs
    response: str
    lease_vars_out: Optional[dict]
    lease_active_out: bool
    pdf_bytes: Optional[bytes]
    pdf_filename: Optional[str]
    draft_id_out: Optional[str]
    lease_action: Optional[str]


def _get_llm() -> ChatClaudeCLI:
    return ChatClaudeCLI(model_name=CLAUDE_MODEL)


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

TRIAGE_PROMPT = """You are triaging a user message during an active commercial lease drafting workflow.
The user has a lease draft in progress. Classify their message into ONE of these categories:

- "edit" — They are providing lease information or changing a variable (names, dates, amounts, addresses, etc.)
- "preview" — They want to see a preview PDF of the current lease draft
- "finalize" — They want to generate the final lease PDF (says "finalize", "looks good", "done", "generate", etc.)
- "status" — They want to see what's filled and what's missing
- "question" — They are asking a research question about commercial leasing
- "cancel" — They want to stop working on this lease

Respond with ONLY one word: edit, preview, finalize, status, question, or cancel"""


# ---------------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------------

def entry_node(state: LeaseState) -> dict:
    return {}


def list_drafts_node(state: LeaseState) -> dict:
    """Show existing in-progress drafts when entering the module."""
    drafts = list_drafts(status="in_progress")
    if not drafts:
        # No existing drafts — create a new one
        return {
            "response": (
                "Welcome to the Commercial Lease Generator. "
                "What would you like to name this lease draft? "
                '(e.g., "Bilal - Main St" or "DQ Washtenaw")'
            ),
            "lease_active_out": True,
        }

    lines = ["**Existing lease drafts:**\n"]
    for d in drafts:
        lines.append(f"- **{d['name']}** (ID: {d['id']}, updated {d['updated_at'][:10]})")
    lines.append("\nSay a draft name to resume it, or **new** to start a new lease.")

    return {
        "response": "\n".join(lines),
        "lease_active_out": True,
    }


def create_new_node(state: LeaseState) -> dict:
    """Create a new draft from the user's first message."""
    msg = state["user_message"].strip()

    # Check if they're resuming an existing draft
    drafts = list_drafts(status="in_progress")
    for d in drafts:
        if d["name"].lower() in msg.lower() or d["id"] in msg:
            draft = get_draft(d["id"])
            checklist = format_status_checklist(draft["variables"])
            return {
                "response": f'Resuming draft **{draft["name"]}**.\n\n{checklist}',
                "lease_vars_out": draft["variables"],
                "draft_id_out": draft["id"],
                "lease_active_out": True,
            }

    # Create new draft
    name = msg if len(msg) < 60 else msg[:60]
    if name.lower() == "new":
        name = "Untitled Lease"

    # Try to extract any variables from the first message
    extracted = extract_variables(msg, {})
    draft_id = create_draft(name, extracted)

    checklist = format_status_checklist(extracted)
    if extracted:
        update_draft(draft_id, extracted)
        response = f'Created draft **{name}**. I found some info in your message.\n\n{checklist}'
    else:
        response = (
            f'Created draft **{name}**.\n\n'
            "Tell me about this deal. You can give me everything at once or one thing at a time:\n\n"
            "- Landlord and tenant names/addresses\n"
            "- Premises address and size (SF)\n"
            "- Lease term and commencement date\n"
            "- Rent ($/SF/year) and lease type (NNN, Modified Gross, or Gross)\n"
            "- Any other deal terms you know"
        )

    return {
        "response": response,
        "lease_vars_out": extracted,
        "draft_id_out": draft_id,
        "lease_active_out": True,
    }


def resume_draft_node(state: LeaseState) -> dict:
    """Resume an existing draft."""
    draft_id = state.get("draft_id")
    if not draft_id:
        return {
            "response": "No draft to resume. Say **new** to start a new lease.",
            "lease_active_out": True,
        }
    draft = get_draft(draft_id)
    if not draft:
        return {
            "response": f"Draft {draft_id} not found. Say **new** to start a new lease.",
            "lease_active_out": True,
        }
    checklist = format_status_checklist(draft["variables"])
    return {
        "response": f'Resuming **{draft["name"]}**.\n\n{checklist}',
        "lease_vars_out": draft["variables"],
        "draft_id_out": draft_id,
        "lease_active_out": True,
    }


def extract_node(state: LeaseState) -> dict:
    """Extract variables from user message and update draft."""
    current_vars = state.get("lease_vars") or {}
    extracted = extract_variables(state["user_message"], current_vars)

    if not extracted:
        # Nothing extracted — nudge
        llm = _get_llm()
        result = llm.invoke([
            SystemMessage(content=(
                "You are helping a user build a commercial lease agreement. "
                "Their latest message didn't contain recognizable lease information. "
                "Respond naturally, then gently steer back to getting lease details. "
                "Keep it to 1-2 sentences. No emojis."
            )),
            HumanMessage(content=state["user_message"]),
        ])
        return {
            "response": result.content,
            "lease_vars_out": current_vars,
            "lease_active_out": True,
        }

    merged = {**current_vars, **extracted}

    # Persist to SQLite
    draft_id = state.get("draft_id")
    if draft_id:
        update_draft(draft_id, extracted)

    checklist = format_status_checklist(merged)
    extracted_names = ", ".join(extracted.keys())

    return {
        "response": f"Got it — updated: {extracted_names}\n\n{checklist}",
        "lease_vars_out": merged,
        "draft_id_out": draft_id,
        "lease_active_out": True,
    }


def triage_node(state: LeaseState) -> dict:
    """Classify what the user wants to do with their active lease draft."""
    msg = state["user_message"].lower().strip()
    if msg in ("cancel", "nevermind", "never mind", "stop", "quit"):
        return {"lease_action": "cancel"}
    if msg in ("preview", "show me", "show preview", "let me see"):
        return {"lease_action": "preview"}
    if msg in ("status", "checklist", "what's left", "what is left", "show status"):
        return {"lease_action": "status"}
    if any(w in msg for w in ("finalize", "looks good", "done", "generate", "final", "complete")):
        return {"lease_action": "finalize"}

    llm = _get_llm()
    response = llm.invoke([
        SystemMessage(content=TRIAGE_PROMPT),
        HumanMessage(content=state["user_message"]),
    ])
    action = response.content.strip().lower()
    if action in ("edit", "preview", "finalize", "status", "question", "cancel"):
        return {"lease_action": action}
    return {"lease_action": "edit"}


def preview_node(state: LeaseState) -> dict:
    """Generate a preview PDF with highlighted blanks."""
    current_vars = state.get("lease_vars") or {}
    try:
        pdf_bytes = generate_lease_pdf(current_vars, preview=True)
        filename = get_lease_filename(current_vars).replace(".pdf", "_PREVIEW.pdf")
        return {
            "response": "Here's a preview of your lease draft. Unfilled fields are shown as [FIELD NAME].",
            "lease_vars_out": current_vars,
            "lease_active_out": True,
            "pdf_bytes": pdf_bytes,
            "pdf_filename": filename,
        }
    except Exception as e:
        return {
            "response": f"Couldn't generate preview: {e}",
            "lease_vars_out": current_vars,
            "lease_active_out": True,
            "pdf_bytes": None,
            "pdf_filename": None,
        }


def finalize_node(state: LeaseState) -> dict:
    """Generate the final lease PDF."""
    current_vars = state.get("lease_vars") or {}

    if not is_all_required_filled(current_vars):
        checklist = format_status_checklist(current_vars)
        return {
            "response": f"Can't finalize yet — some required fields are still missing:\n\n{checklist}",
            "lease_vars_out": current_vars,
            "lease_active_out": True,
            "pdf_bytes": None,
            "pdf_filename": None,
        }

    try:
        pdf_bytes = generate_lease_pdf(current_vars, preview=False)
        filename = get_lease_filename(current_vars)

        # Mark draft as complete
        draft_id = state.get("draft_id")
        if draft_id:
            update_draft(draft_id, current_vars, status="complete")

        return {
            "response": "Lease finalized! Here's your PDF.",
            "lease_vars_out": None,
            "lease_active_out": False,
            "pdf_bytes": pdf_bytes,
            "pdf_filename": filename,
        }
    except Exception as e:
        return {
            "response": f"Error generating lease: {e}",
            "lease_vars_out": current_vars,
            "lease_active_out": True,
            "pdf_bytes": None,
            "pdf_filename": None,
        }


def status_node(state: LeaseState) -> dict:
    """Show the current variable checklist."""
    current_vars = state.get("lease_vars") or {}
    checklist = format_status_checklist(current_vars)
    return {
        "response": checklist,
        "lease_vars_out": current_vars,
        "lease_active_out": True,
    }


def question_node(state: LeaseState) -> dict:
    """Answer a research question about commercial leasing."""
    llm = _get_llm()
    current_vars = state.get("lease_vars") or {}
    vars_context = json.dumps(current_vars, indent=2, default=str) if current_vars else "No data yet"

    response = llm.invoke([
        SystemMessage(content=(
            "You are a knowledgeable commercial real estate assistant. "
            "The user is building a commercial lease and has a question. "
            "Answer concisely. If it relates to their current lease, reference their data.\n\n"
            f"Current lease variables:\n{vars_context}\n\n"
            "After answering, remind them they can continue adding lease info or say 'preview' to see the draft."
        )),
        HumanMessage(content=state["user_message"]),
    ])
    return {
        "response": response.content,
        "lease_vars_out": current_vars,
        "lease_active_out": True,
    }


def cancel_node(state: LeaseState) -> dict:
    """Cancel the lease workflow."""
    return {
        "response": "Lease draft saved. You can resume it later.",
        "lease_vars_out": None,
        "lease_active_out": False,
    }


# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------

def route_entry(state: LeaseState) -> str:
    if state.get("command") == "create":
        if state.get("draft_id"):
            return "resume_draft"
        # Check if there are existing drafts
        drafts = list_drafts(status="in_progress")
        if drafts:
            return "list_drafts"
        return "create_new"

    # "continue" command
    if state.get("lease_vars"):
        return "triage"
    return "create_new"


def route_triage(state: LeaseState) -> str:
    action = state.get("lease_action", "edit")
    return {
        "edit": "extract",
        "preview": "preview",
        "finalize": "finalize",
        "status": "status",
        "question": "question",
        "cancel": "cancel",
    }.get(action, "extract")


# ---------------------------------------------------------------------------
# Build graph
# ---------------------------------------------------------------------------

def build_graph():
    graph = StateGraph(LeaseState)

    graph.add_node("entry", entry_node)
    graph.add_node("list_drafts", list_drafts_node)
    graph.add_node("create_new", create_new_node)
    graph.add_node("resume_draft", resume_draft_node)
    graph.add_node("extract", extract_node)
    graph.add_node("triage", triage_node)
    graph.add_node("preview", preview_node)
    graph.add_node("finalize", finalize_node)
    graph.add_node("status", status_node)
    graph.add_node("question", question_node)
    graph.add_node("cancel", cancel_node)

    graph.set_entry_point("entry")

    graph.add_conditional_edges("entry", route_entry, {
        "list_drafts": "list_drafts",
        "create_new": "create_new",
        "resume_draft": "resume_draft",
        "triage": "triage",
    })

    graph.add_conditional_edges("triage", route_triage, {
        "extract": "extract",
        "preview": "preview",
        "finalize": "finalize",
        "status": "status",
        "question": "question",
        "cancel": "cancel",
    })

    # Terminal edges
    for node in ["list_drafts", "create_new", "resume_draft", "extract",
                 "preview", "finalize", "status", "question", "cancel"]:
        graph.add_edge(node, END)

    return graph.compile()
```

**Step 2: Wire up server.py**

Update the `graph = None` line in `server.py` to:

```python
from graph import build_graph
graph = build_graph()
```

**Step 3: Commit**

```bash
git add rrg-commercial-lease/graph.py rrg-commercial-lease/server.py
git commit -m "feat(lease): add LangGraph workflow with all nodes"
```

---

### Task 7: Nix Flake & Docker Build

**Files:**
- Create: `rrg-commercial-lease/flake.nix`

**Step 1: Write flake.nix**

Model after `rrg-pnl/flake.nix` but replace WeasyPrint deps with LibreOffice + docxtpl. Key differences:
- LibreOffice headless instead of WeasyPrint
- No WeasyPrint system deps (pango, cairo, etc.)
- SQLite volume mount (handled in docker-compose, not flake)
- `num2words` and `docxtpl` in poetry deps

```nix
{
  description = "RRG Commercial Lease Generator — Flask + LangGraph + docxtpl + LibreOffice";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    poetry2nix = {
      url = "github:nix-community/poetry2nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { self, nixpkgs, poetry2nix, flake-utils }:
    let
      lib = nixpkgs.lib;
      linuxSystem = "x86_64-linux";
      linuxPkgs = import nixpkgs {
        system = linuxSystem;
        config.allowUnfreePredicate = pkg:
          builtins.elem (lib.getName pkg) [ "claude-code" ];
      };

      p2nix = poetry2nix.lib.mkPoetry2Nix { pkgs = linuxPkgs; };

      pythonEnv = p2nix.mkPoetryEnv {
        projectDir = self;
        python = linuxPkgs.python312;
        preferWheels = true;
      };

      appSrc = linuxPkgs.runCommand "rrg-commercial-lease-src" {} ''
        mkdir -p $out/app/templates
        cp ${./server.py} $out/app/server.py
        cp ${./graph.py} $out/app/graph.py
        cp ${./lease_handler.py} $out/app/lease_handler.py
        cp ${./lease_pdf.py} $out/app/lease_pdf.py
        cp ${./lease_computed.py} $out/app/lease_computed.py
        cp ${./draft_store.py} $out/app/draft_store.py
        cp ${./claude_llm.py} $out/app/claude_llm.py
        cp ${./templates/commercial_lease.docx} $out/app/templates/commercial_lease.docx
      '';

      fontConfig = linuxPkgs.makeFontsConf {
        fontDirectories = [
          linuxPkgs.liberation_ttf
          linuxPkgs.noto-fonts
        ];
      };

    in
    {
      packages.x86_64-linux.dockerImage = linuxPkgs.dockerTools.buildLayeredImage {
        name = "rrg-commercial-lease";
        tag = "latest";

        contents = [
          pythonEnv
          linuxPkgs.claude-code
          linuxPkgs.libreoffice
          linuxPkgs.coreutils
          linuxPkgs.bashInteractive
          linuxPkgs.cacert
          linuxPkgs.liberation_ttf
          linuxPkgs.noto-fonts
          appSrc
        ];

        config = {
          Cmd = [ "${pythonEnv}/bin/python" "/app/server.py" ];
          ExposedPorts = { "8102/tcp" = {}; };
          WorkingDir = "/app";
          Env = [
            "PORT=8102"
            "CLAUDE_MODEL=haiku"
            "HOME=/root"
            "SSL_CERT_FILE=${linuxPkgs.cacert}/etc/ssl/certs/ca-bundle.crt"
            "NIX_SSL_CERT_FILE=${linuxPkgs.cacert}/etc/ssl/certs/ca-bundle.crt"
            "FONTCONFIG_FILE=${fontConfig}"
            "PYTHONPATH=/app"
          ];
        };
      };

      packages.x86_64-linux.default = self.packages.x86_64-linux.dockerImage;
      packages.x86_64-darwin.dockerImage = self.packages.x86_64-linux.dockerImage;
      packages.x86_64-darwin.default = self.packages.x86_64-linux.dockerImage;

    } // flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = import nixpkgs {
          inherit system;
          config.allowUnfreePredicate = pkg:
            builtins.elem (lib.getName pkg) [ "claude-code" ];
        };
        p2nixDev = poetry2nix.lib.mkPoetry2Nix { inherit pkgs; };
      in {
        devShells.default = pkgs.mkShell {
          buildInputs = [
            (p2nixDev.mkPoetryEnv {
              projectDir = self;
              python = pkgs.python312;
              preferWheels = true;
            })
            pkgs.claude-code
            pkgs.libreoffice
          ];
          shellHook = ''
            echo "RRG Commercial Lease dev shell"
            echo "Run: python server.py"
          '';
        };
      }
    );
}
```

**Step 2: Generate poetry.lock**

```bash
cd rrg-commercial-lease
poetry lock
```

**Step 3: Commit**

```bash
git add rrg-commercial-lease/flake.nix rrg-commercial-lease/poetry.lock
git commit -m "feat(lease): add Nix flake for Docker image build"
```

**Note:** LibreOffice is a large package. The Docker image will be significantly larger than rrg-pnl. If this becomes a problem, investigate `libreoffice-minimal` or a two-stage approach where the conversion is done by a shared sidecar. Address only if image size is actually problematic.

---

### Task 8: Variablize the .docx Template

**Files:**
- Create: `rrg-commercial-lease/templates/commercial_lease.docx`

This is the most labor-intensive task. It requires:

1. Copy the original template from `~/Downloads/2026_0305_Commercial Lease Template.docx`
2. Open in Word/LibreOffice Writer
3. Replace ALL hard-coded values with Jinja2 tags following the variable inventory in the design doc
4. Add conditional blocks (`{% if %}`) for optional sections
5. Add the rent table loop (`{% tr for row in rent_rows %}`)
6. Test by running docxtpl fill with sample data

**Step 1: Copy template**

```bash
cp ~/Downloads/"2026_0305_Commercial Lease Template.docx" rrg-commercial-lease/templates/commercial_lease.docx
```

**Step 2: Variablize the template**

This must be done by editing the .docx in a word processor. Use `python-docx` to do programmatic replacement where possible, manual editing for structural changes (conditionals, table loop).

Key transformations (section by section — see design doc for full variable inventory):

**Preamble:** Replace party names, addresses, LLC language with Jinja2 tags.
**Section 1.0:** Replace county, state, address, SF.
**Section 2.0:** Replace all term/option values; add conditionals for zero months, zero options, multiple options.
**Section 3.0:** Replace rent schedule table with `{% tr for row in rent_rows %}` loop; replace all dollar amounts and percentages; add lease_type conditionals for 3.2.
**Section 4.0:** Replace deposit amounts; add conditional for no-deposit.
**Section 5.0:** Replace permitted use.
**Sections 6-33:** Replace remaining hard-coded values per design doc.
**Signature block:** Replace all names/titles.
**Guaranty section:** Wrap in `{% if has_personal_guaranty %}`.

**Step 3: Test template rendering**

```bash
cd rrg-commercial-lease
python3 -c "
from docxtpl import DocxTemplate
from datetime import date

doc = DocxTemplate('templates/commercial_lease.docx')
# Minimal test context
context = {
    'landlord_name': 'Test Landlord LLC',
    'tenant_name': 'Test Tenant',
    'premises_address': '123 Main St, Ann Arbor, MI',
    'rent_rows': [
        {'term': '01/01/26 – 12/31/26', 'lease_rate': '\$20.00', 'monthly_rent': '\$2,000.00', 'term_rent': '\$24,000.00', 'is_free_rent': False}
    ],
    'preview': True,
    # ... add remaining required context vars
}
doc.render(context)
doc.save('/tmp/test_lease.docx')
print('Template rendered successfully')
"
```

**Step 4: Convert test docx to PDF**

```bash
libreoffice --headless --convert-to pdf --outdir /tmp /tmp/test_lease.docx
echo "Check /tmp/test_lease.pdf"
```

**Step 5: Commit**

```bash
git add rrg-commercial-lease/templates/commercial_lease.docx
git commit -m "feat(lease): add variablized commercial lease template"
```

---

### Task 9: Router Integration

**Files:**
- Modify: `rrg-router/config.py:24-43` (add lease intent + worker URL)
- Modify: `rrg-router/app.py:164-175` (add Lease PDF label)
- Modify: `deploy/docker-compose.yml` (add lease service)

**Step 1: Add lease intent to router config**

In `rrg-router/config.py`, add to `WORKER_URLS`:

```python
WORKER_URLS = {
    "pnl": os.getenv("WORKER_PNL_URL", "http://rrg-pnl:8100"),
    "brochure": os.getenv("WORKER_BROCHURE_URL", "http://rrg-brochure:8101"),
    "lease": os.getenv("WORKER_LEASE_URL", "http://rrg-commercial-lease:8102"),
}
```

Add to `INTENTS`:

```python
"create_lease": {
    "description": "User wants to create or work on a commercial lease agreement",
    "help_text": "Create a commercial lease agreement",
    "handler": "lease",
},
```

**Step 2: Add Lease PDF label in router app.py**

Update the PDF label logic around line 166:

```python
if "Brochure" in fname:
    pdf_label = "Download Brochure PDF"
elif "Lease" in fname:
    pdf_label = "Download Lease PDF"
else:
    pdf_label = "Download P&L PDF"
```

Same pattern for the label around line 189.

**Step 3: Add lease service to docker-compose.yml**

Add to `deploy/docker-compose.yml`:

```yaml
  rrg-commercial-lease:
    image: rrg-commercial-lease:latest
    container_name: rrg-commercial-lease
    restart: unless-stopped
    expose:
      - "8102"
    environment:
      - CLAUDE_CODE_OAUTH_TOKEN=${CLAUDE_CODE_OAUTH_TOKEN}
      - CLAUDE_MODEL=${CLAUDE_MODEL:-haiku}
    volumes:
      - lease-data:/data
    tmpfs:
      - /root/.claude:rw,size=50m
      - /tmp:rw
    networks:
      - windmill_default
```

Add to the volumes section at the bottom:

```yaml
volumes:
  lease-data:
```

Add `WORKER_LEASE_URL` to the router service environment:

```yaml
  rrg-router:
    environment:
      - WORKER_LEASE_URL=http://rrg-commercial-lease:8102
```

**Step 4: Commit**

```bash
git add rrg-router/config.py rrg-router/app.py deploy/docker-compose.yml
git commit -m "feat(lease): integrate lease module into router and docker-compose"
```

---

### Task 10: Documentation Updates

**Files:**
- Modify: `CLAUDE.md` (root — add lease to overview)
- Modify: `rrg-commercial-lease/CLAUDE.md` (flesh out with full docs)
- Modify: `rrg-router/CLAUDE.md` (add lease handler reference)

**Step 1: Update root CLAUDE.md**

Add `rrg-commercial-lease` to the directory tree and code map. Add port 8102 reference. Add `create_lease` to the intents list.

**Step 2: Flesh out rrg-commercial-lease/CLAUDE.md**

Follow the pattern from rrg-pnl/CLAUDE.md: document the LangGraph workflow, state shape, key functions, endpoint contract, PDF generation, deploy commands.

**Step 3: Update rrg-router/CLAUDE.md**

Add lease to the handler list.

**Step 4: Commit**

```bash
git add CLAUDE.md rrg-commercial-lease/CLAUDE.md rrg-router/CLAUDE.md
git commit -m "docs: add commercial lease module documentation"
```

---

### Task 11: Build, Deploy & Smoke Test

**Step 1: Build Docker image**

```bash
cd rrg-commercial-lease
nix build .#dockerImage
```

If build fails, debug Nix issues (likely LibreOffice deps or poetry2nix overrides). Common issues:
- LibreOffice may need `fontconfig` in contents
- `docxtpl` or `num2words` may need poetry2nix overrides
- LibreOffice binary path may differ — check with `nix-store --query --references`

**Step 2: Transfer to server**

```bash
scp result andrea@rrg-server:~/jake-images/rrg-commercial-lease.tar.gz
ssh andrea@rrg-server 'docker load < ~/jake-images/rrg-commercial-lease.tar.gz'
```

**Step 3: Deploy**

```bash
ssh andrea@rrg-server 'cd ~/rrg-server/deploy && docker compose up -d'
```

**Step 4: Smoke test via curl**

```bash
# Health check
curl http://rrg-server:8102/health

# Create a lease
curl -X POST http://rrg-server:8102/process \
  -H 'Content-Type: application/json' \
  -d '{"command":"create","user_message":"New lease for Bilal Alghazaly at 123 Main St, Ann Arbor MI, 1400 SF, 5 year term, $19/SF NNN","chat_history":[],"state":{}}'
```

Expected: JSON response with extracted variables and status checklist.

**Step 5: Test via Streamlit UI**

Open `http://rrg-server:8501` and say "I want to create a commercial lease". Verify:
- Intent routes to lease handler
- Draft is created
- Variables are extracted from messages
- Preview PDF generates
- Finalize produces complete PDF

**Step 6: Commit any fixes**

```bash
git add -A
git commit -m "fix(lease): address deployment issues from smoke test"
```
