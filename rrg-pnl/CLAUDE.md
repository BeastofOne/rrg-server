# RRG P&L Worker

## What
P&L analysis worker for CRE deals. Flask microservice on port 8100, part of the jake-deploy Docker stack on rrg-server (100.97.86.99). Called by the message router (`f/switchboard/message_router`).

## LangGraph Workflow (7 nodes)

```
entry → [route_entry] → extract  → END   (new request with numbers)
                       → nudge    → END   (new request, no numbers)
                       → triage   → [route_triage] → edit     → END
                                                    → approve  → END (generates PDF)
                                                    → question → END
                                                    → cancel   → END
```

**Nodes:**
| Node | What it does |
|------|-------------|
| `entry` | Pass-through — routing handled by `route_entry` conditional edge |
| `extract` | LLM extracts P&L data from user message → JSON. Shows formatted table or asks for more info |
| `nudge` | User is in P&L mode but sent non-financial message. LLM steers back to data collection |
| `triage` | Has existing P&L data. LLM classifies message as edit/approve/question/cancel |
| `edit` | LLM applies user's changes to existing P&L JSON. Shows updated table |
| `approve` | Generates finalized PDF via `generate_pnl_pdf()`. Ends workflow (`active=false`) |
| `question` | LLM answers a general question mid-workflow, preserving active P&L |
| `cancel` | Ends workflow with no output |

## State Shape (`PnlState` TypedDict)

```python
class PnlState(TypedDict):
    command: str               # "create" | "continue"
    user_message: str
    chat_history: list         # [{"role": ..., "content": ...}]
    pnl_data: Optional[dict]   # current P&L data from previous state
    # Outputs:
    response: str
    pnl_data_out: Optional[dict]
    pnl_active_out: bool
    pdf_bytes: Optional[bytes]
    pdf_filename: Optional[str]
    pnl_action: Optional[str]  # triage result: edit/approve/cancel/question
```

## Key Functions (`pnl_handler.py`)

| Function | Signature | What |
|----------|-----------|------|
| `extract_pnl_data` | `(user_message, existing_data=None) → dict` | LLM extracts structured JSON from natural language |
| `apply_changes` | `(existing_data, user_message, chat_history=None) → dict` | LLM applies edits to existing P&L JSON |
| `is_approval` | `(user_message) → bool` | LLM checks if message means "finalize" |
| `compute_pnl` | `(data) → dict` | Pure math: total income, vacancy loss, EGI, expenses, NOI |
| `format_pnl_table` | `(data) → str` | Renders data as markdown table for display |

## Endpoint Contract

**`POST /process`**

Request:
```json
{
  "command": "create",
  "user_message": "Create a P&L for 123 Main St, rent $5000/mo, vacancy 5%, taxes $5000/yr",
  "chat_history": [],
  "state": {}
}
```

Response:
```json
{
  "response": "Here's your P&L:\n\n...",
  "state": {"pnl_data": {...}, "pnl_active": true},
  "active": true,
  "pdf_bytes": null,
  "pdf_filename": null
}
```

When approved, `pdf_bytes` contains base64 PDF, `active` becomes `false`.

## PDF Generation
`pnl_pdf.py`: `generate_pnl_pdf(data) → bytes`
- Jinja2 renders `templates/pnl.html` with computed P&L fields
- WeasyPrint converts HTML → PDF
- Filename: `YYYYMMDD_Profit and Loss_<address>.pdf`

## Tech
- **Language:** Python
- **Build:** Nix flake
- **Framework:** LangGraph + Flask
- **Port:** 8100 (Docker network)
- **LLM:** `claude -p` via `ChatClaudeCLI` (env `CLAUDE_MODEL`, default "haiku")
- **Env vars:** `CLAUDE_CODE_OAUTH_TOKEN`, `CLAUDE_MODEL` (from `jake-deploy/.env`)

## Deploy
```bash
nix build .#docker
scp result andrea@100.97.86.99:~/jake-images/rrg-pnl.tar.gz
ssh andrea@100.97.86.99 'docker load < ~/jake-images/rrg-pnl.tar.gz && cd ~/jake-deploy && docker compose -f docker-compose.jake.yml up -d'
```

## Local Dev
```bash
nix develop
python graph.py
```
