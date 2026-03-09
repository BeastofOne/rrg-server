# Commercial Purchase Agreement Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build `rrg-commercial-pa`, a conversational purchase agreement generator that extracts ~55 deal variables through chat and renders `.docx` files.

**Architecture:** Nix-built Docker image running Flask + LangGraph, following the same `/process` worker contract as rrg-pnl. Internally uses SQLite for draft persistence and docxtpl for .docx rendering. Router classifies intent and forwards to the container on port 8102.

**Tech Stack:** Python 3.12, Flask, LangGraph, langchain-core, docxtpl, python-docx, SQLite3, Nix (buildLayeredImage), Claude CLI (`claude -p`)

**Design Doc:** `docs/plans/2026-03-09-commercial-pa-design.md`

**Test Suite (pre-written by independent agent):** `rrg-commercial-pa/tests/` — 184 tests across 6 files. Tests were drafted by a separate context to avoid same-LLM bias.

---

## Task 1: Project Scaffolding

**Files:**
- Create: `rrg-commercial-pa/pyproject.toml`
- Create: `rrg-commercial-pa/tests/__init__.py` (already exists)
- Create: `rrg-commercial-pa/tests/conftest.py` (already exists)
- Verify: `rrg-commercial-pa/tests/test_draft_store.py` (already exists)

**Step 1: Create pyproject.toml**

```toml
[tool.poetry]
name = "rrg-commercial-pa"
version = "0.1.0"
description = "RRG Commercial PA Microservice — conversational purchase agreement generator"
authors = ["Jake Phillips"]

[tool.poetry.dependencies]
python = "^3.12"
flask = ">=3.0"
langgraph = ">=0.2"
langchain-core = ">=0.3"
docxtpl = ">=0.18"
python-docx = ">=1.1"

[tool.poetry.group.dev.dependencies]
pytest = ">=8.0"

[build-system]
requires = ["poetry-core"]
build-backend = "poetry.core.masonry.api"
```

**Step 2: Generate poetry.lock**

Run: `cd rrg-commercial-pa && poetry lock`
Expected: `poetry.lock` created

**Step 3: Install dev dependencies**

Run: `cd rrg-commercial-pa && poetry install`
Expected: All deps installed including pytest

**Step 4: Run test suite to verify all tests fail (no implementation yet)**

Run: `cd rrg-commercial-pa && poetry run pytest tests/test_draft_store.py -v --tb=short 2>&1 | head -30`
Expected: All tests FAIL with `ModuleNotFoundError: No module named 'draft_store'`

**Step 5: Commit scaffolding**

```bash
git add rrg-commercial-pa/pyproject.toml rrg-commercial-pa/tests/
git commit -m "feat(commercial-pa): project scaffolding with TDD test suite (184 tests)"
```

---

## Task 2: SQLite Draft Store

**Files:**
- Create: `rrg-commercial-pa/draft_store.py`
- Test: `rrg-commercial-pa/tests/test_draft_store.py` (50 tests, already exists)

**Step 1: Run the tests to confirm they fail**

Run: `cd rrg-commercial-pa && poetry run pytest tests/test_draft_store.py -v --tb=short 2>&1 | tail -5`
Expected: 50 FAILED, `ModuleNotFoundError: No module named 'draft_store'`

**Step 2: Implement draft_store.py**

Reference design doc section "SQLite Schema" and "Implementation Notes" for the single-connection pattern.

The `DraftStore` class needs:
- `__init__(self, db_path)` — creates the table if not exists
- `create_draft(property_address, variables, additional_provisions=None, exhibit_a_entities=None) → str` — returns UUID
- `load_draft(draft_id) → dict|None` — returns full draft dict with deserialized JSON
- `load_draft_by_address(address) → dict|None` — returns most recent in-progress draft
- `update_draft(draft_id, variables, status=None, additional_provisions=None, exhibit_a_entities=None)` — single-connection read-merge-write
- `list_drafts() → list[dict]` — returns id, property_address, status, completion_pct
- `delete_draft(draft_id)` — removes from table

Key requirements from tests:
- Variables must be `dict` after load (not JSON string)
- Types (int, float, bool, str) must survive JSON round-trip
- `load_draft_by_address` returns most recent in-progress draft only
- `update_draft` merges new variables into existing (not replaces)
- `update_draft` uses single SQLite connection for read-merge-write
- `list_drafts` includes `completion_pct` (count of non-None variables / total expected)
- `delete_draft` on nonexistent ID should not crash

Module-level constant: `DB_PATH = os.getenv("PA_DB_PATH", "/data/pa_drafts.db")`

Import `ALL_VARIABLE_FIELDS` list for completion percentage calculation, or define it in `draft_store.py`.

**Step 3: Run tests**

Run: `cd rrg-commercial-pa && poetry run pytest tests/test_draft_store.py -v`
Expected: 50 PASSED

**Step 4: Commit**

```bash
git add rrg-commercial-pa/draft_store.py
git commit -m "feat(commercial-pa): SQLite draft store with CRUD operations"
```

---

## Task 3: Clause Library (provisions.py)

**Files:**
- Create: `rrg-commercial-pa/provisions.py`
- Test: `rrg-commercial-pa/tests/test_provisions.py` (17 tests, already exists)

**Step 1: Run the tests to confirm they fail**

Run: `cd rrg-commercial-pa && poetry run pytest tests/test_provisions.py -v --tb=short 2>&1 | tail -5`
Expected: 17 FAILED

**Step 2: Implement provisions.py**

Three functions:
- `list_clauses() → list[dict]` — returns predefined clauses, each with `title` and `body`
- `get_clause(name) → dict|None` — returns clause by exact title, None if not found
- `render_clause(body_template, variables) → str` — Jinja2-renders body with variables

Predefined clauses (from the template analysis):
1. **Land Contract Subordination** — subordination of LC to primary mortgage
2. **Licensed Agent Disclosure** — principal is a licensed agent
3. **Processing Fee** — `{{ amount }}` processing fee at closing
4. **Tax Proration Waiver** — seller waives tax proration
5. **Management Holdover** — `{{ days }}` day holdover period

Use `jinja2.Template` for `render_clause`. Missing variables should render as empty string (use `jinja2.Undefined` or `undefined=''`).

**Step 3: Run tests**

Run: `cd rrg-commercial-pa && poetry run pytest tests/test_provisions.py -v`
Expected: 17 PASSED

**Step 4: Commit**

```bash
git add rrg-commercial-pa/provisions.py
git commit -m "feat(commercial-pa): clause library with predefined provisions + Jinja2 rendering"
```

---

## Task 4: Claude LLM Wrapper

**Files:**
- Create: `rrg-commercial-pa/claude_llm.py` (copy from rrg-pnl)

**Step 1: Copy from rrg-pnl**

```bash
cp rrg-pnl/claude_llm.py rrg-commercial-pa/claude_llm.py
```

No tests needed — this is a direct copy of a proven module. The test suite mocks this entirely.

**Step 2: Commit**

```bash
git add rrg-commercial-pa/claude_llm.py
git commit -m "feat(commercial-pa): copy claude_llm.py from rrg-pnl"
```

---

## Task 5: PA Handler (extract/edit/triage logic)

**Files:**
- Create: `rrg-commercial-pa/pa_handler.py`
- Test: `rrg-commercial-pa/tests/test_pa_handler.py` (34 tests, already exists)

**Step 1: Run the tests to confirm they fail**

Run: `cd rrg-commercial-pa && poetry run pytest tests/test_pa_handler.py -v --tb=short 2>&1 | tail -5`
Expected: 34 FAILED

**Step 2: Implement pa_handler.py**

Functions to implement (mirrors `rrg-pnl/pnl_handler.py` pattern):

- `_get_llm() → ChatClaudeCLI` — returns LLM instance from env CLAUDE_MODEL
- `extract_pa_data(user_message, existing_data=None) → dict` — LLM extracts PA variables from natural language. Strip markdown fences from response. Parse JSON. Raise on invalid JSON.
- `apply_changes(existing_data, user_message, chat_history=None) → dict` — LLM applies targeted changes. Include recent chat context for ambiguity resolution. Return complete updated dict.
- `is_approval(user_message) → bool` — LLM checks if message means "finalize". Returns bool.
- `classify_action(user_message) → str` — LLM classifies into: edit/preview/finalize/save/list_drafts/question/cancel. Unknown responses default to "edit".
- `format_remaining_variables(variables) → str` — Pure function. Compares filled variables against ALL_VARIABLE_FIELDS. Returns formatted checklist of missing ones grouped by category.
- `format_filled_summary(extracted) → str` — Pure function. Formats newly extracted variables as confirmation text. Skips None values.

Key patterns from tests:
- All LLM functions use `_get_llm()` (mockable via `pa_handler._get_llm`)
- JSON responses: strip markdown fences (```` ```json ... ``` ````)
- `classify_action` returns valid action string; unknown LLM output defaults to "edit"
- `format_remaining_variables({})` should return non-empty string (all variables missing)
- `format_filled_summary` should never include "None" in output

**Step 3: Run tests**

Run: `cd rrg-commercial-pa && poetry run pytest tests/test_pa_handler.py -v`
Expected: 34 PASSED

**Step 4: Commit**

```bash
git add rrg-commercial-pa/pa_handler.py
git commit -m "feat(commercial-pa): PA handler with extract, edit, triage, and formatting"
```

---

## Task 6: Template Conversion

**Files:**
- Create: `rrg-commercial-pa/templates/commercial_pa.docx`

**Step 1: Convert the prefilled .docx to a blank Jinja2 template**

Source: `~/Downloads/2026_0306_Commercial_PA_283 Unit Portfolio_Pontiac.docx`

This is a manual + scripted task. Open the .docx and replace all deal-specific values with `{{ variable_name }}` Jinja2 placeholders. Use `docxtpl` syntax for:

- Simple variables: `{{ purchaser_name }}`
- Checkboxes: `{% if payment_cash %}[X]{% else %}[ ]{% endif %}`
- Conditionals: `{% if payment_land_contract %}...land contract section...{% endif %}`
- Exhibit A loop: `{% for entity in exhibit_a_entities %}...{% endfor %}`
- Additional provisions loop: `{% for prov in additional_provisions %}{{ loop.index }}. {{ prov.title }}.\n{{ prov.body }}{% endfor %}`
- Missing values default to blank: use `{{ variable_name|default('_______________') }}`

Key replacements from the template analysis (paragraph numbers from extraction):
- P1: effective date, purchaser name/entity/address, seller name
- P3: property location type checkboxes, municipality, county, address, parcel IDs
- P4: legal description
- P8: purchase price (words + number)
- P11-P13: payment method checkboxes + land contract details
- P15-P16: earnest money, title company
- P18: inspection period days
- P19-P28: due diligence checkboxes
- P32: title insurance paid by, standard exceptions
- P41: closing days
- P79-P105: notice addresses (purchaser, seller, copies)
- P117: broker info, commission
- P151: offer expiration
- P153-P163: additional provisions (loop)
- Exhibit A table: entity loop
- Signature blocks: left as blank lines (not filled by system)

**Step 2: Verify template loads with docxtpl**

```python
python3 -c "
from docxtpl import DocxTemplate
doc = DocxTemplate('rrg-commercial-pa/templates/commercial_pa.docx')
print('Variables found:', doc.get_undeclared_template_variables())
print('Template loaded successfully')
"
```
Expected: Lists Jinja2 variable names, no errors

**Step 3: Commit**

```bash
git add rrg-commercial-pa/templates/commercial_pa.docx
git commit -m "feat(commercial-pa): blank Jinja2 template from source PA document"
```

---

## Task 7: DOCX Renderer (pa_docx.py)

**Files:**
- Create: `rrg-commercial-pa/pa_docx.py`
- Test: `rrg-commercial-pa/tests/test_pa_docx.py` (31 tests, already exists)

**Step 1: Run the tests to confirm they fail**

Run: `cd rrg-commercial-pa && poetry run pytest tests/test_pa_docx.py -v --tb=short 2>&1 | tail -5`
Expected: 31 FAILED

**Step 2: Implement pa_docx.py**

Single function:
- `generate_pa_docx(variables) → bytes` — renders template with docxtpl, returns .docx bytes

Implementation:
```python
import io
import os
from docxtpl import DocxTemplate

TEMPLATE_PATH = os.path.join(os.path.dirname(__file__), "templates", "commercial_pa.docx")

def generate_pa_docx(variables: dict) -> bytes:
    """Render the PA template with the given variables, return .docx bytes."""
    doc = DocxTemplate(TEMPLATE_PATH)

    # Build context: default all missing variables to empty/blank
    context = _build_context(variables)

    doc.render(context)

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()
```

The `_build_context` helper should:
- Default missing string variables to `"_______________"` (blank line)
- Default missing bool variables to `False` (unchecked)
- Default missing numeric variables to `0`
- Convert bools to checkbox strings if needed by template: `"[X]"` / `"[ ]"`
- Handle `exhibit_a_entities` defaulting to `[]`
- Handle `additional_provisions` defaulting to `[]`
- Handle `None` values same as missing

Key requirements from tests:
- Output starts with `PK` (ZIP header)
- Valid ZIP containing `word/document.xml`
- No raw `{{` or `}}` in output XML (all placeholders resolved)
- Works with empty dict, partial variables, None values
- Exhibit A with 0, 1, or 3 entities
- Additional provisions with 0, 1, or 3 items
- Special characters (apostrophes, accents) don't crash

**Step 3: Run tests**

Run: `cd rrg-commercial-pa && poetry run pytest tests/test_pa_docx.py -v`
Expected: 31 PASSED

**Step 4: Commit**

```bash
git add rrg-commercial-pa/pa_docx.py
git commit -m "feat(commercial-pa): docxtpl renderer producing .docx from variables"
```

---

## Task 8: LangGraph Workflow (graph.py)

**Files:**
- Create: `rrg-commercial-pa/graph.py`
- Test: `rrg-commercial-pa/tests/test_graph.py` (27 tests, already exists)

**Step 1: Run the tests to confirm they fail**

Run: `cd rrg-commercial-pa && poetry run pytest tests/test_graph.py -v --tb=short 2>&1 | tail -5`
Expected: 27 FAILED

**Step 2: Implement graph.py**

Follow the design doc's 11-node graph structure. Mirror `rrg-pnl/graph.py` pattern exactly.

State TypedDict:
```python
class PaState(TypedDict):
    command: str               # "create" | "continue"
    user_message: str
    chat_history: list
    draft_id: Optional[str]    # from previous state
    # Outputs:
    response: str
    pa_active: bool
    docx_bytes: Optional[bytes]
    docx_filename: Optional[str]
    pa_action: Optional[str]   # triage result
```

Nodes: `entry`, `start_new`, `load_draft`, `extract`, `triage`, `edit`, `preview`, `finalize`, `save`, `list_drafts`, `question`, `cancel`

Routing:
- `route_entry`: create → start_new (or load_draft if "resume" detected); continue with draft_id → triage (or extract if no draft data yet)
- `route_triage`: based on `pa_action`

Each node interacts with `DraftStore` for persistence. The store is initialized at module level with `DB_PATH`.

Key requirements from tests:
- `build_graph()` returns object with `.invoke()` method
- Create returns `draft_id` and `pa_active=True`
- Resume loads existing draft by address
- Triage routes correctly: preview→docx_bytes, save→active=False, finalize→docx_bytes+active=False, cancel→active=False+delete
- All outputs have: `response`, `draft_id`, `pa_active`, `docx_bytes`, `docx_filename`
- Edge cases: empty message, long history, missing draft_id, invalid draft_id, unknown command

**Step 3: Run tests**

Run: `cd rrg-commercial-pa && poetry run pytest tests/test_graph.py -v`
Expected: 27 PASSED

**Step 4: Commit**

```bash
git add rrg-commercial-pa/graph.py
git commit -m "feat(commercial-pa): LangGraph workflow with 11 nodes and triage routing"
```

---

## Task 9: Flask Server (server.py)

**Files:**
- Create: `rrg-commercial-pa/server.py`
- Test: `rrg-commercial-pa/tests/test_server.py` (25 tests, already exists)

**Step 1: Run the tests to confirm they fail**

Run: `cd rrg-commercial-pa && poetry run pytest tests/test_server.py -v --tb=short 2>&1 | tail -5`
Expected: 25 FAILED

**Step 2: Implement server.py**

Mirror `rrg-pnl/server.py` exactly but with PA-specific state fields.

```python
"""RRG Commercial PA Microservice — persistent Flask container."""
import base64
import os
import traceback
from flask import Flask, request, jsonify

app = Flask(__name__)

from graph import build_graph
graph = build_graph()

@app.route("/process", methods=["POST"])
def process():
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
        "response": "",
        "pa_active": True,
        "docx_bytes": None,
        "docx_filename": None,
        "pa_action": None,
    }

    try:
        result = graph.invoke(graph_input)
    except Exception as e:
        traceback.print_exc()
        return jsonify({
            "response": f"Error processing PA request: {e}",
            "state": prev_state,
            "active": prev_state.get("pa_active", True),
            "docx_bytes": None,
            "docx_filename": None,
        }), 500

    pa_active = result.get("pa_active", True)
    docx_bytes_raw = result.get("docx_bytes")
    docx_b64 = None
    if docx_bytes_raw:
        docx_b64 = base64.b64encode(docx_bytes_raw).decode("utf-8")

    return jsonify({
        "response": result.get("response", ""),
        "state": {
            "draft_id": result.get("draft_id"),
            "pa_active": pa_active,
        },
        "active": pa_active,
        "docx_bytes": docx_b64,
        "docx_filename": result.get("docx_filename"),
    })

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "service": "rrg-commercial-pa"})

if __name__ == "__main__":
    port = int(os.getenv("PORT", "8102"))
    print(f"rrg-commercial-pa starting on port {port}")
    app.run(host="0.0.0.0", port=port)
```

Key requirements from tests:
- Response contract: always has `response`, `state`, `active`, `docx_bytes`, `docx_filename`
- `state` is always dict, `active` is always bool
- Error responses return 500 but still have all required fields
- Missing command defaults to "create", missing user_message defaults to ""
- `docx_bytes` is base64-encoded when present
- Health check returns `{"status": "ok", "service": "rrg-commercial-pa"}`

**Step 3: Run tests**

Run: `cd rrg-commercial-pa && poetry run pytest tests/test_server.py -v`
Expected: 25 PASSED

**Step 4: Run full test suite**

Run: `cd rrg-commercial-pa && poetry run pytest tests/ -v --tb=short`
Expected: 184 PASSED

**Step 5: Commit**

```bash
git add rrg-commercial-pa/server.py
git commit -m "feat(commercial-pa): Flask server with /process and /health endpoints"
```

---

## Task 10: Router Integration

**Files:**
- Modify: `rrg-router/config.py:12-15` (add worker URL + intent)
- Modify: `rrg-router/state.py:18` (add handler_name option)
- Modify: `rrg-router/node_client.py:46-65` (add docx_bytes handling)
- Modify: `rrg-router/windmill_client.py:64-78` (add docx_bytes handling)
- Modify: `rrg-router/app.py:72-79,164-175,187-193` (docx download support + "Download Preview" label)

**Step 1: Update config.py**

Add to WORKER_URLS dict:
```python
"commercial_pa": os.getenv("WORKER_PA_URL", "http://rrg-commercial-pa:8102"),
```

Add to INTENTS dict:
```python
"create_commercial_pa": {
    "description": "User wants to create or resume a commercial purchase agreement",
    "help_text": "Create a commercial purchase agreement (PA)",
    "handler": "commercial_pa",
},
```

**Step 2: Update node_client.py**

After the `pdf_bytes` decode block (line ~56), add:
```python
docx_bytes = None
if data.get("docx_bytes"):
    try:
        docx_bytes = base64.b64decode(data["docx_bytes"])
    except Exception:
        pass
```

Add `"docx_bytes": docx_bytes, "docx_filename": data.get("docx_filename")` to all three return dicts (success, timeout, error).

**Step 3: Update windmill_client.py**

Same changes as node_client.py — add docx_bytes decode and include in all return dicts.

**Step 4: Update app.py**

Replace the download button logic. Where it currently says:
```python
if response_data.get("pdf_bytes"):
    fname = response_data.get("pdf_filename", "output.pdf")
    if "Brochure" in fname:
        pdf_label = "Download Brochure PDF"
    else:
        pdf_label = "Download P&L PDF"
    st.download_button(
        label=pdf_label,
        data=response_data["pdf_bytes"],
        file_name=fname,
        mime="application/pdf",
    )
```

Replace with generic file download that handles both PDF and DOCX:
```python
# Determine file data and metadata
file_bytes = response_data.get("pdf_bytes") or response_data.get("docx_bytes")
file_name = response_data.get("pdf_filename") or response_data.get("docx_filename") or "output"

if file_bytes:
    # Detect MIME type from extension
    if file_name.endswith(".docx"):
        mime = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    else:
        mime = "application/pdf"
    st.download_button(
        label="Download Preview",
        data=file_bytes,
        file_name=file_name,
        mime=mime,
    )
```

Apply the same pattern to the message history replay section (~lines 187-193).

**Step 5: Update state.py**

Add `"commercial_pa"` to the handler_name comment:
```python
handler_name: Optional[str]  # "pnl" | "brochure" | "commercial_pa"
```

**Step 6: Verify router starts**

Run: `cd rrg-router && python -c "from config import WORKER_URLS, INTENTS; print(WORKER_URLS); print(list(INTENTS.keys()))"`
Expected: Shows `commercial_pa` in both

**Step 7: Commit**

```bash
git add rrg-router/config.py rrg-router/state.py rrg-router/node_client.py rrg-router/windmill_client.py rrg-router/app.py
git commit -m "feat(router): add commercial_pa worker support with .docx downloads"
```

---

## Task 11: Windmill Flow Update

**Files:**
- Modify: `windmill/f/switchboard/message_router.flow/flow.yaml`
- Create: `windmill/f/switchboard/message_router.flow/post_to_rrg-commercial-pa.inline_script.py`
- Create: `windmill/f/switchboard/message_router.flow/post_to_rrg-commercial-pa.inline_script.lock`

**Step 1: Create the inline script**

Copy from `post_to_rrg-pnl.inline_script.py`, change URL:
```python
#extra_requirements:
#requests

import requests as req

def main(
    target_node: str,
    command: str,
    user_message: str,
    chat_history: list,
    state: dict,
):
    url = "http://rrg-commercial-pa:8102/process"
    payload = {
        "command": command,
        "user_message": user_message,
        "chat_history": chat_history,
        "state": state,
    }
    resp = req.post(url, json=payload, timeout=120)
    resp.raise_for_status()
    return resp.json()
```

**Step 2: Copy the lock file**

```bash
cp windmill/f/switchboard/message_router.flow/post_to_rrg-pnl.inline_script.lock \
   windmill/f/switchboard/message_router.flow/post_to_rrg-commercial-pa.inline_script.lock
```

**Step 3: Update flow.yaml**

Add a new branch after the Brochure Worker branch (after line 66). The new branch follows the exact same structure as PNL and Brochure, with:
- `id: e` (next available letter)
- `summary: Commercial PA Worker`
- `content: '!inline post_to_rrg-commercial-pa.inline_script.py'`
- `lock: '!inline post_to_rrg-commercial-pa.inline_script.lock'`
- `expr: flow_input.target_node === 'commercial_pa'`

Also update the schema description (line 99) from `'Worker node name: pnl or brochure'` to `'Worker node name: pnl, brochure, or commercial_pa'`.

**Step 4: Verify YAML is valid**

Run: `python3 -c "import yaml; yaml.safe_load(open('windmill/f/switchboard/message_router.flow/flow.yaml'))" && echo "Valid YAML"`
Expected: "Valid YAML"

**Step 5: Commit**

```bash
git add windmill/f/switchboard/message_router.flow/
git commit -m "feat(windmill): add commercial_pa branch to message_router flow"
```

**Step 6: Push to Windmill (on rrg-server)**

**IMPORTANT: Must be done on rrg-server after git pull delivers the changes.**

```bash
ssh andrea@rrg-server 'cd ~/rrg-server && git pull && cd windmill && wmill sync push --skip-variables --skip-secrets --skip-resources'
```

---

## Task 12: Nix Flake

**Files:**
- Create: `rrg-commercial-pa/flake.nix`

**Step 1: Write flake.nix**

Mirror `rrg-pnl/flake.nix` but simpler (no WeasyPrint deps, no font config needed):

```nix
{
  description = "RRG Commercial PA Microservice — Flask + LangGraph + docxtpl";

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

      appSrc = linuxPkgs.runCommand "rrg-commercial-pa-src" {} ''
        mkdir -p $out/app/templates
        cp ${./server.py} $out/app/server.py
        cp ${./graph.py} $out/app/graph.py
        cp ${./pa_handler.py} $out/app/pa_handler.py
        cp ${./pa_docx.py} $out/app/pa_docx.py
        cp ${./draft_store.py} $out/app/draft_store.py
        cp ${./claude_llm.py} $out/app/claude_llm.py
        cp ${./provisions.py} $out/app/provisions.py
        cp ${./templates/commercial_pa.docx} $out/app/templates/commercial_pa.docx
      '';

    in
    {
      packages.x86_64-linux.dockerImage = linuxPkgs.dockerTools.buildLayeredImage {
        name = "rrg-commercial-pa";
        tag = "latest";
        contents = [
          pythonEnv
          linuxPkgs.claude-code
          linuxPkgs.coreutils
          linuxPkgs.bashInteractive
          linuxPkgs.cacert
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
            "PYTHONPATH=/app"
            "PA_DB_PATH=/data/pa_drafts.db"
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
          ];
          shellHook = ''
            echo "RRG Commercial PA dev shell"
            echo "Run: python server.py"
          '';
        };
      }
    );
}
```

**Step 2: Generate flake.lock**

Run: `cd rrg-commercial-pa && nix flake lock`
Expected: `flake.lock` created

**Step 3: Test dev shell**

Run: `cd rrg-commercial-pa && nix develop --command python -c "import flask; import docxtpl; print('OK')"`
Expected: "OK"

**Step 4: Commit**

```bash
git add rrg-commercial-pa/flake.nix rrg-commercial-pa/flake.lock
git commit -m "feat(commercial-pa): Nix flake for Docker image and dev shell"
```

---

## Task 13: Docker Compose & Deploy

**Files:**
- Modify: `deploy/docker-compose.yml`

**Step 1: Add the service and volume**

Add to `services:` section (after rrg-brochure):
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
```

Add `WORKER_PA_URL=http://rrg-commercial-pa:8102` to the rrg-router service environment.

Add top-level `volumes:` section (new — does not exist in current file):
```yaml
volumes:
  pa-data:
```

**Step 2: Validate compose file**

Run: `cd deploy && docker compose config --quiet && echo "Valid"`
Expected: "Valid"

**Step 3: Commit**

```bash
git add deploy/docker-compose.yml
git commit -m "feat(deploy): add rrg-commercial-pa service with SQLite volume"
```

---

## Task 14: CLAUDE.md Documentation

**Files:**
- Create: `rrg-commercial-pa/CLAUDE.md`
- Modify: `CLAUDE.md` (root — add to directory tree, worker contract, key ports)

**Step 1: Write rrg-commercial-pa/CLAUDE.md**

Follow the pattern of `rrg-pnl/CLAUDE.md`:
- What: description, port, how it's called
- LangGraph workflow diagram (11 nodes)
- State shape
- Key functions
- Endpoint contract
- DOCX generation
- Tech stack
- Deploy commands

**Step 2: Update root CLAUDE.md**

- Add `rrg-commercial-pa/` to directory tree with description
- Update worker contract: "rrg-pnl, rrg-brochure, and rrg-commercial-pa expose identical POST /process..."
- Note: rrg-commercial-pa returns `docx_bytes` instead of `pdf_bytes`

**Step 3: Commit**

```bash
git add rrg-commercial-pa/CLAUDE.md CLAUDE.md
git commit -m "docs: add CLAUDE.md for commercial-pa module, update root docs"
```

---

## Task 15: Build, Deploy, and Smoke Test

**Step 1: Build Docker image on rrg-server**

```bash
ssh andrea@rrg-server 'cd ~/rrg-server/rrg-commercial-pa && nix build .#dockerImage'
```

**Step 2: Load image**

```bash
ssh andrea@rrg-server 'docker load < ~/rrg-server/rrg-commercial-pa/result'
```

**Step 3: Start the stack**

```bash
ssh andrea@rrg-server 'cd ~/rrg-server/deploy && docker compose up -d'
```

**Step 4: Health check**

```bash
ssh andrea@rrg-server 'curl -s http://localhost:8102/health | python3 -m json.tool'
```
Expected: `{"status": "ok", "service": "rrg-commercial-pa"}`

**Step 5: Smoke test via /process**

```bash
ssh andrea@rrg-server 'curl -s -X POST http://localhost:8102/process \
  -H "Content-Type: application/json" \
  -d "{\"command\": \"create\", \"user_message\": \"Create a PA for 123 Main St, Pontiac\", \"chat_history\": [], \"state\": {}}" \
  | python3 -m json.tool | head -20'
```
Expected: JSON with `response`, `state.draft_id`, `active: true`

**Step 6: Test through router UI**

Open Streamlit at `http://100.97.86.99:8501`, type "Create a purchase agreement for 123 Main St", verify it routes to the PA workflow.

**Step 7: Commit any fixes**

```bash
git add -A && git commit -m "fix(commercial-pa): smoke test fixes"
```
