# RRG Commercial PA Worker

## What
Conversational purchase agreement generator for commercial real estate deals. Flask microservice on port 8102, part of the jake-deploy Docker stack on rrg-server (100.97.86.99). Called by the message router (`f/switchboard/message_router`).

Extracts ~55 deal variables through conversation, persists drafts in SQLite, and renders `.docx` files via docxtpl.

## LangGraph Workflow (11 nodes)

```
entry → [route_entry] → start_new  → END   (new request or resume)
                       → triage     → [route_triage] → edit        → END
                                                      → preview     → END (generates .docx)
                                                      → finalize    → END (generates .docx, active=false)
                                                      → save        → END
                                                      → list_drafts → END
                                                      → question    → END
                                                      → cancel      → END
```

**Nodes:**
| Node | What it does |
|------|-------------|
| `entry` | Pass-through — routing handled by `route_entry` conditional edge |
| `start_new` | Creates new draft in SQLite (or resumes by address). Extracts initial variables from message |
| `triage` | Has existing draft. LLM classifies message as edit/preview/finalize/save/list_drafts/question/cancel |
| `edit` | LLM applies user's changes to existing draft variables. Shows updated summary |
| `preview` | Generates preview `.docx` via `generate_pa_docx()`. Draft stays active |
| `finalize` | Generates final `.docx`. Ends workflow (`pa_active=false`) |
| `save` | Saves current state, confirms to user |
| `list_drafts` | Lists all saved drafts with addresses |
| `question` | LLM answers a general question mid-workflow, preserving active draft |
| `cancel` | Ends workflow with no output |

## State Shape (`PaState` TypedDict)

```python
class PaState(TypedDict):
    command: str               # "create" | "continue"
    user_message: str
    chat_history: list         # [{"role": ..., "content": ...}]
    draft_id: Optional[str]    # from previous state
    # Outputs:
    response: str
    pa_active: bool
    docx_bytes: Optional[bytes]
    docx_filename: Optional[str]
    pa_action: Optional[str]   # triage result: edit/preview/finalize/save/list_drafts/question/cancel
```

## Key Functions

### pa_handler.py
| Function | Signature | What |
|----------|-----------|------|
| `extract_pa_data` | `(user_message, existing_data=None) → dict` | LLM extracts structured JSON from natural language |
| `apply_changes` | `(existing_data, user_message, chat_history=None) → dict` | LLM applies edits to existing variable dict |
| `classify_action` | `(user_message, chat_history=None) → str` | LLM classifies message into action type |
| `format_remaining_variables` | `(variables) → str` | Lists unfilled variables |
| `format_filled_summary` | `(variables) → str` | Shows current filled values |

### draft_store.py
| Function | Signature | What |
|----------|-----------|------|
| `create_draft` | `(property_address, variables) → str` | Creates new SQLite row, returns draft_id |
| `load_draft` | `(draft_id) → dict` | Loads draft by ID |
| `load_draft_by_address` | `(address) → dict\|None` | Loads draft by property address |
| `update_draft` | `(draft_id, variables) → None` | Merges variables into existing draft |
| `list_drafts` | `() → list[dict]` | Lists all drafts |
| `delete_draft` | `(draft_id) → None` | Deletes a draft |

### provisions.py
| Function | Signature | What |
|----------|-----------|------|
| `list_clauses` | `() → list[str]` | Returns names of all predefined clauses |
| `get_clause` | `(name) → dict\|None` | Returns clause dict (name, body, description) |
| `render_clause` | `(body_template, variables) → str` | Renders clause body with Jinja2 variables |

## Endpoint Contract

**`POST /process`**

Request:
```json
{
  "command": "create",
  "user_message": "Create a PA for 123 Main St, seller is ABC Corp",
  "chat_history": [],
  "state": {}
}
```

Response:
```json
{
  "response": "New purchase agreement draft created.\n\n...",
  "state": {"draft_id": "abc123", "pa_active": true},
  "active": true,
  "docx_bytes": null,
  "docx_filename": null
}
```

When previewed or finalized, `docx_bytes` contains base64 .docx data. On finalize, `active` becomes `false`.

## DOCX Generation
`pa_docx.py`: `generate_pa_docx(variables) → bytes`
- docxtpl renders `templates/commercial_pa.docx` with ~70 Jinja2 template variables
- Supports loops (exhibit_a_entities, additional_provisions) and conditionals (checkboxes)
- Filename: `YYYYMMDD_Commercial_PA_<address>.docx`

## Tech
- **Language:** Python
- **Build:** Nix flake (poetry2nix)
- **Framework:** LangGraph + Flask
- **Port:** 8102 (Docker network)
- **LLM:** `claude -p` via `ChatClaudeCLI` (env `CLAUDE_MODEL`, default "haiku")
- **Storage:** SQLite at `/data/pa_drafts.db` (Docker volume `pa-data`)
- **Env vars:** `CLAUDE_CODE_OAUTH_TOKEN`, `CLAUDE_MODEL`, `PA_DB_PATH` (from `jake-deploy/.env`)

## Deploy
```bash
nix build .#docker
scp result andrea@100.97.86.99:~/jake-images/rrg-commercial-pa.tar.gz
ssh andrea@100.97.86.99 'docker load < ~/jake-images/rrg-commercial-pa.tar.gz && cd ~/jake-deploy && docker compose -f docker-compose.jake.yml up -d'
```

## Local Dev
```bash
nix develop
python server.py
```
