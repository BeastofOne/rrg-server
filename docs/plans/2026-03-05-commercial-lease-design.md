# Commercial Lease Module — Design Document

**Date:** 2026-03-05
**Author:** Jake Phillips + Claude

## Goal

Build `rrg-commercial-lease`, a new worker module that generates commercial lease agreements from a variablized .docx template via conversational Q&A in the RRG Router Streamlit UI.

## Architecture

Single LangGraph worker container (same pattern as rrg-pnl and rrg-brochure). Flask microservice on port 8102. Uses `docxtpl` (Jinja2-in-Word) to fill a .docx template, then LibreOffice headless to convert to PDF. SQLite on a Docker volume for persistent draft storage.

## Tech Stack

- Python 3.12, Flask, LangGraph, LangChain
- docxtpl (python-docx-template) for .docx variable filling
- LibreOffice headless for .docx → PDF conversion
- SQLite for draft persistence
- Nix flake + poetry2nix for Docker image build
- Claude CLI (haiku) via ChatClaudeCLI for LLM calls

## Template Approach

The .docx lease template is the source of truth. It uses Jinja2 syntax inside Word:
- `{{ variable }}` for simple substitution
- `{% if condition %}...{% endif %}` for conditional sections
- `{% tr for row in rent_schedule %}...{% endfor %}` for the rent table rows
- Unfilled fields render as `[FIELD NAME]` in red for preview PDFs

## Variable Inventory (~70 variables)

### Parties & Preamble
| Variable | Type | Conditional? |
|----------|------|-------------|
| `lease_date` | date | |
| `landlord_name` | string | |
| `landlord_is_llc` | bool | yes — LLC language |
| `landlord_entity_type` | enum (LLC/Corp/Partnership/Trust/Individual) | yes — entity description |
| `landlord_llc_state` | string | only if LLC |
| `landlord_address` | string | |
| `tenant_name` | string | |
| `tenant_is_llc` | bool | yes — LLC language |
| `tenant_entity_type` | enum | yes — entity description |
| `tenant_llc_state` | string | only if LLC |
| `tenant_entity_to_be_formed` | bool | yes — adds signer-for-entity language |
| `tenant_address` | string | |

### Premises (Section 1.0)
| Variable | Type |
|----------|------|
| `premises_county` | string |
| `premises_state` | string |
| `premises_address` | string |
| `premises_size_sf` | int |

### Term & Option (Section 2.0)
| Variable | Type | Notes |
|----------|------|-------|
| `lease_term_years` | int | 0 = months-only term |
| `lease_term_months` | int | 0 = years-only term; conditional wording |
| `lease_commencement_date` | date | Obligations start |
| `rent_commencement_date` | date | Payments start (may differ for build-out) |
| `lease_end_date` | date | Computed from commencement + term |
| `num_options` | int | 0 = no option section; conditional |
| `option_term_years` | int | Per option period |
| `option_start_date` | date | Computed |
| `option_end_date` | date | Computed |
| `option_rent_basis` | string | "market rate", fixed amount, etc. |
| `option_notice_days` | int | Default 90 |

### Rent (Section 3.0) — Computed Rent Table
| Variable | Type | Notes |
|----------|------|-------|
| `base_lease_rate_psf` | float | Starting $/SF/year |
| `rent_escalation_type` | enum | none/fixed_percentage/CPI/CPI_with_cap |
| `rent_escalation_rate` | float | Annual % increase |
| `has_free_rent` | bool | Conditional — free rent row + proration paragraph |
| `free_rent_end_date` | date | End of free rent period |
| `space_delivery_deadline` | date | Proration trigger date |
| `free_rent_proration_month` | string | Month free rent credit applies |
| `lease_type` | enum | NNN/Modified_Gross/Gross — changes Section 3.2 entirely |
| `additional_rent_psf` | float | NNN/MG only |
| `tax_share_pct` | float | NNN/MG only |
| `insurance_share_pct` | float | NNN/MG only |
| `rent_payment_address` | string | Where checks go |
| `late_fee_grace_days` | int | Default 7 |
| `late_fee_pct` | float | Default 5% |
| `consecutive_late_threshold` | int | Default 3 |
| `nsf_fee` | float | Default $40 |

**Rent table is COMPUTED from:** `premises_size_sf`, `base_lease_rate_psf`, `rent_escalation_type`, `rent_escalation_rate`, `lease_commencement_date`, `rent_commencement_date`, `lease_end_date`, `has_free_rent`, `free_rent_end_date`.

**Table columns:** Term | Lease Rate | Monthly Rent | Term Rent
**Row logic:**
1. Free rent row (if applicable): commencement → free_rent_end, "Free Base Rent" spanning columns
2. First paid period: rent_commencement → day before next lease anniversary (may be short)
3. Full-year rows: each anniversary, rate escalates
4. Final row: last anniversary → lease_end (may be short)
5. Monthly Rent = rate × SF / 12; Term Rent = monthly × months in period

### Security Deposit (Section 4.0)
| Variable | Type | Notes |
|----------|------|-------|
| `has_security_deposit` | bool | Conditional — entire section reworded if false |
| `security_deposit_total` | float | Computed or manual |
| `first_month_prepay` | float | Often = first month's rent from rent table |
| `security_deposit_amount` | float | = total - prepay |
| `deposit_replenishment_days` | int | Default 10 |

### Use (Section 5.0)
| Variable | Type |
|----------|------|
| `permitted_use` | string |

### Tenant Responsibilities (Section 10.0)
| Variable | Type | Notes |
|----------|------|-------|
| `hvac_repair_threshold` | float | Annual cap before landlord pays |
| `has_plumbing_clause` | bool | Conditional — custom plumbing responsibility paragraph |
| `has_window_glass_clause` | bool | Conditional — exterior window/HVAC exclusion |
| `hvac_contract_days` | int | Default 30 |

### Taxes (Section 11.0)
| Variable | Type | Notes |
|----------|------|-------|
| `tax_prorate_pct` | float | Pro rata share |
| `tax_payment_days` | int | Default 30 |

### Insurance (Section 14.0)
| Variable | Type |
|----------|------|
| `liability_per_person` | float |
| `liability_per_casualty` | float |
| `property_damage_limit` | float |

### Environmental (Section 9.0)
| Variable | Type |
|----------|------|
| `sic_number` | string |

### Entry & Inspections (Section 19.0)
| Variable | Type |
|----------|------|
| `landlord_entry_notice_hours` | int |
| `for_rent_sign_days` | int |

### Holding Over (Section 20.0)
| Variable | Type |
|----------|------|
| `holdover_rent_multiplier` | float |

### Notification (Section 23.0)
| Variable | Type |
|----------|------|
| `landlord_notice_address` | string |

### Applicable Law (Section 27.0)
| Variable | Type |
|----------|------|
| `governing_law_state` | string |

### Estoppel (Section 32.0)
| Variable | Type |
|----------|------|
| `estoppel_notice_days` | int |

### Personal Guaranty (Section 33.0)
| Variable | Type | Notes |
|----------|------|-------|
| `has_personal_guaranty` | bool | Conditional — entire section + guaranty page |
| `guarantor_name` | string | |

### Signature Block
| Variable | Type |
|----------|------|
| `tenant_signer_name` | string |
| `landlord_signer_name` | string |
| `landlord_signer_title` | string |
| `landlord_entity_name` | string |

### Optional Clauses (conditional sections)
| Clause | Toggle | Key Variables |
|--------|--------|--------------|
| Rent Escalation | `rent_escalation_type != none` | rate, CPI floor/cap |
| Tenant Improvement Allowance | `has_ti_allowance` | `ti_allowance_psf`, total computed |
| CAM Cap | `has_cam_cap` | `cam_cap_pct` |
| Early Termination | `has_early_termination` | date, fee, notice_days |
| Right of First Refusal | `has_rofr` | scope description |
| Exclusive Use | `has_exclusive_use` | use description |
| Delivery Condition | `delivery_condition` | as-is/vanilla_shell/turnkey/custom |

## Workflow

### LangGraph Nodes
```
entry → [route_entry] → list_drafts    → END
                       → create_new     → END
                       → resume_draft   → END
                       → extract        → END
                       → triage  → [route_triage] → edit     → END
                                                   → preview  → END
                                                   → finalize → END
                                                   → question → END
                                                   → status   → END
                                                   → cancel   → END
```

### Chat Flow
1. User enters module via router ("I need to create a lease")
2. Module checks SQLite for existing drafts → shows list or starts new
3. User provides info (1 variable or 20 at once) → LLM extracts, updates state
4. After each extraction, show: what was filled, what's still required, what's optional
5. Preview PDF generated on demand with `[FIELD NAME]` in red for unfilled fields
6. Research questions ("what's a typical HVAC cap?") answered via Claude CLI
7. When all required fields filled, user says "finalize" → clean PDF generated
8. Draft marked complete in SQLite

### Variable Extraction
- LLM receives current lease state (filled/unfilled) + user message
- Extracts any variables it can identify from natural language
- Returns structured JSON update to merge into draft state
- Handles: "tenant is Bilal Alghazaly, he's an LLC in Michigan" → sets tenant_name, tenant_is_llc, tenant_llc_state, tenant_entity_type

### Computed Fields
These are calculated, never asked for:
- `lease_end_date` = commencement + term
- `option_start_date` = lease_end_date + 1 day
- `option_end_date` = option_start + option_term
- Rent table rows (all periods, rates, monthly/term amounts)
- Security deposit amounts (from first month's rent)
- Numbers-to-words (e.g., 4433.33 → "Four Thousand Four Hundred Thirty-Three Dollars and 33/100")
- Date formatting (e.g., "March 1, 2026")

## Container & Files
```
rrg-commercial-lease/
├── flake.nix
├── pyproject.toml
├── poetry.lock
├── server.py              # Flask: POST /process, GET /health
├── graph.py               # LangGraph workflow
├── lease_handler.py        # Variable extraction, validation, computed fields
├── lease_pdf.py            # docxtpl fill + LibreOffice → PDF
├── lease_computed.py       # Rent table generation, numbers-to-words, date math
├── draft_store.py          # SQLite CRUD
├── claude_llm.py           # ChatClaudeCLI (copied from rrg-pnl)
├── templates/
│   └── commercial_lease.docx
└── CLAUDE.md
```

- **Port:** 8102
- **Docker volume:** `/data/lease_drafts.db`
- **Nix deps:** python312, flask, langgraph, docxtpl, libreoffice (headless), claude-code

## Router Integration
- New intent: `create_lease` → handler `"lease"`
- New worker URL: `WORKER_LEASE_URL=http://rrg-commercial-lease:8102`
- PDF label: "Download Lease PDF"
- Docker Compose: new service block in `deploy/docker-compose.yml`

## Draft Persistence (SQLite)
```sql
CREATE TABLE drafts (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    variables JSON NOT NULL,
    status TEXT DEFAULT 'in_progress',  -- in_progress | complete
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```
