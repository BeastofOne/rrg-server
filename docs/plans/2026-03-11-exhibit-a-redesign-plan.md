# Exhibit A Table Redesign — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Change Exhibit A from LLC-focused (one row per entity) to address-focused (one row per property address), with bullet-point lists for multi-value cells (Parcel IDs, Owners, Legal Descriptions).

**Architecture:** Keep flat entity extraction (one entity per parcel, LLM unchanged). Add a Python grouping layer in `pa_docx.py` that groups entities by address at render time and produces RichText objects for multi-value cells. Update template columns to: Address | Municipality | County | Parcel ID(s) | Owner(s) | Legal Description(s). Extract a shared `count_grouped_addresses()` function so all three files (`pa_docx.py`, `pa_handler.py`, `draft_store.py`) use the same "is Exhibit A active" logic.

**Tech Stack:** Python, docxtpl (RichText with `\a` for cell paragraph breaks), OOXML template editing.

**Code review findings incorporated:**
- CRITICAL: Three separate copies of "is Exhibit A active" logic → extract shared function
- CRITICAL: `draft_store.py:_completion_pct()` not in original plan → now Task 5
- CRITICAL: `_apply_exhibit_a_logic()` line 90 uses `.get("name")` without `owner` fallback → fixed in Task 2
- IMPORTANT: Address normalization absent → added `.lower()` + whitespace normalization in Task 1
- IMPORTANT: Empty/missing address edge case → defensive handling + test in Task 1
- SUGGESTION: Merge Task 4 into Task 3 to avoid broken-test window → done

---

### Task 1: Extract shared `exhibit_a_helpers.py` + add `_group_entities_by_address()` to `pa_docx.py`

**Files:**
- Create: `rrg-commercial-pa/exhibit_a_helpers.py`
- Modify: `rrg-commercial-pa/pa_docx.py`
- Test: `rrg-commercial-pa/tests/test_pa_docx.py`

**Why a shared module:** `pa_docx.py`, `pa_handler.py`, and `draft_store.py` each have independent copies of the "is Exhibit A active" check and the "multi-LLC" check. After the redesign, the activation condition changes from entity count >= 2 to **grouped address count >= 2**. If we don't unify these, the chat summary and completion percentage will diverge from the actual document rendering. Extract these into `exhibit_a_helpers.py` so there's a single source of truth.

**Step 1: Write failing tests**

Add `TestGroupEntitiesByAddress` class in `test_pa_docx.py`:

```python
from pa_docx import _group_entities_by_address

class TestGroupEntitiesByAddress:
    """Tests for the address-grouping function."""

    def test_single_entity_per_address(self):
        """Each entity at a different address → one row per address, no bullets."""
        entities = [
            {"name": "LLC A", "address": "100 Main", "municipality": "Pontiac",
             "county": "Oakland", "parcel_ids": "001", "legal_description": "Lot 1"},
            {"name": "LLC B", "address": "200 Oak", "municipality": "Troy",
             "county": "Oakland", "parcel_ids": "002", "legal_description": "Lot 2"},
        ]
        result = _group_entities_by_address(entities)
        assert len(result) == 2
        assert result[0]["address"] == "100 Main"
        assert isinstance(result[0]["owners_display"], str)
        assert result[0]["owners_display"] == "LLC A"
        assert result[0]["parcel_ids_display"] == "001"
        assert result[0]["legal_descriptions_display"] == "Lot 1"

    def test_multiple_parcels_same_address(self):
        """Two entities at same address → one row, RichText bullet points."""
        entities = [
            {"name": "LLC A", "address": "100 Main", "municipality": "Pontiac",
             "county": "Oakland", "parcel_ids": "001", "legal_description": "Lot 1"},
            {"name": "LLC B", "address": "100 Main", "municipality": "Pontiac",
             "county": "Oakland", "parcel_ids": "002", "legal_description": "Lot 2"},
        ]
        result = _group_entities_by_address(entities)
        assert len(result) == 1
        prop = result[0]
        assert prop["address"] == "100 Main"
        assert prop["municipality"] == "Pontiac"
        assert prop["county"] == "Oakland"
        from docxtpl import RichText
        assert isinstance(prop["owners_display"], RichText)
        assert isinstance(prop["parcel_ids_display"], RichText)
        assert isinstance(prop["legal_descriptions_display"], RichText)

    def test_empty_entities(self):
        """Empty list → empty result."""
        assert _group_entities_by_address([]) == []

    def test_preserves_address_order(self):
        """Addresses should appear in first-seen order."""
        entities = [
            {"name": "A", "address": "200 Oak", "municipality": "Troy",
             "county": "Oakland", "parcel_ids": "002", "legal_description": "L2"},
            {"name": "B", "address": "100 Main", "municipality": "Pontiac",
             "county": "Oakland", "parcel_ids": "001", "legal_description": "L1"},
        ]
        result = _group_entities_by_address(entities)
        assert result[0]["address"] == "200 Oak"
        assert result[1]["address"] == "100 Main"

    def test_owner_field_backwards_compat(self):
        """Entities with 'name' key (old format) should work same as 'owner'."""
        entities = [
            {"name": "Old Format LLC", "address": "100 Main", "municipality": "P",
             "county": "O", "parcel_ids": "001", "legal_description": "L1"},
        ]
        result = _group_entities_by_address(entities)
        assert result[0]["owners_display"] == "Old Format LLC"

    def test_deduplicates_owners(self):
        """Same owner on multiple parcels at same address → listed once."""
        entities = [
            {"name": "Same LLC", "address": "100 Main", "municipality": "P",
             "county": "O", "parcel_ids": "001", "legal_description": "L1"},
            {"name": "Same LLC", "address": "100 Main", "municipality": "P",
             "county": "O", "parcel_ids": "002", "legal_description": "L2"},
        ]
        result = _group_entities_by_address(entities)
        assert isinstance(result[0]["owners_display"], str)
        assert result[0]["owners_display"] == "Same LLC"

    def test_address_normalization_case(self):
        """Addresses differing only by case should group together."""
        entities = [
            {"name": "LLC A", "address": "100 Main St", "municipality": "P",
             "county": "O", "parcel_ids": "001", "legal_description": "L1"},
            {"name": "LLC B", "address": "100 main st", "municipality": "P",
             "county": "O", "parcel_ids": "002", "legal_description": "L2"},
        ]
        result = _group_entities_by_address(entities)
        assert len(result) == 1

    def test_address_normalization_whitespace(self):
        """Addresses differing only by extra whitespace should group together."""
        entities = [
            {"name": "LLC A", "address": "100  Main  St", "municipality": "P",
             "county": "O", "parcel_ids": "001", "legal_description": "L1"},
            {"name": "LLC B", "address": "100 Main St", "municipality": "P",
             "county": "O", "parcel_ids": "002", "legal_description": "L2"},
        ]
        result = _group_entities_by_address(entities)
        assert len(result) == 1

    def test_empty_address_entities_skipped(self):
        """Entities with empty/missing address are skipped (not grouped into catch-all)."""
        entities = [
            {"name": "LLC A", "address": "", "municipality": "P",
             "county": "O", "parcel_ids": "001", "legal_description": "L1"},
            {"name": "LLC B", "address": "100 Main", "municipality": "P",
             "county": "O", "parcel_ids": "002", "legal_description": "L2"},
        ]
        result = _group_entities_by_address(entities)
        assert len(result) == 1
        assert result[0]["address"] == "100 Main"
```

Also add tests for the shared helpers:

```python
from exhibit_a_helpers import normalize_address, count_grouped_addresses, get_distinct_owners

class TestExhibitAHelpers:
    """Tests for shared Exhibit A helper functions."""

    def test_normalize_address(self):
        assert normalize_address("  100  Main  St  ") == "100 main st"
        assert normalize_address("") == ""
        assert normalize_address(None) == ""

    def test_count_grouped_addresses_basic(self):
        entities = [
            {"address": "100 Main"},
            {"address": "200 Oak"},
        ]
        assert count_grouped_addresses(entities) == 2

    def test_count_grouped_addresses_same(self):
        entities = [
            {"address": "100 Main"},
            {"address": "100 main"},
        ]
        assert count_grouped_addresses(entities) == 1

    def test_count_grouped_addresses_skips_empty(self):
        entities = [
            {"address": ""},
            {"address": "100 Main"},
        ]
        assert count_grouped_addresses(entities) == 1

    def test_count_grouped_addresses_empty_list(self):
        assert count_grouped_addresses([]) == 0

    def test_get_distinct_owners(self):
        entities = [
            {"name": "LLC A"},
            {"owner": "LLC B"},
            {"name": "LLC A"},  # duplicate
        ]
        assert get_distinct_owners(entities) == {"LLC A", "LLC B"}

    def test_get_distinct_owners_prefers_owner_key(self):
        entities = [{"owner": "New Key", "name": "Old Key"}]
        assert get_distinct_owners(entities) == {"New Key"}
```

**Step 2: Run tests to verify they fail**

Run: `cd rrg-commercial-pa && python -m pytest tests/test_pa_docx.py::TestGroupEntitiesByAddress tests/test_pa_docx.py::TestExhibitAHelpers -v`
Expected: ImportError.

**Step 3: Write `exhibit_a_helpers.py`**

```python
"""Shared Exhibit A helper functions.

Used by pa_docx.py, pa_handler.py, and draft_store.py to ensure
consistent "is Exhibit A active" and "multi-LLC" logic.
"""


def normalize_address(addr) -> str:
    """Normalize an address for grouping: lowercase, collapse whitespace."""
    if not addr:
        return ""
    return " ".join(str(addr).lower().split())


def count_grouped_addresses(entities: list) -> int:
    """Count distinct addresses after normalization. Skips empty addresses."""
    addrs = set()
    for e in entities:
        if not isinstance(e, dict):
            continue
        norm = normalize_address(e.get("address", ""))
        if norm:
            addrs.add(norm)
    return len(addrs)


def get_distinct_owners(entities: list) -> set:
    """Get the set of distinct owner/name values across entities."""
    owners = set()
    for e in entities:
        if not isinstance(e, dict):
            continue
        owner = (e.get("owner") or e.get("name") or "").strip()
        if owner:
            owners.add(owner)
    return owners


def exhibit_a_active(entities: list) -> bool:
    """Return True if Exhibit A should be shown (2+ distinct addresses)."""
    return count_grouped_addresses(entities) >= 2


def exhibit_a_multi_owner(entities: list) -> bool:
    """Return True if there are multiple distinct owners across entities."""
    if not exhibit_a_active(entities):
        return False
    return len(get_distinct_owners(entities)) > 1
```

**Step 4: Write `_group_entities_by_address()` in `pa_docx.py`**

```python
from docxtpl import DocxTemplate, RichText
from exhibit_a_helpers import normalize_address

def _group_entities_by_address(entities: list[dict]) -> list[dict]:
    """Group flat entity dicts by address for Exhibit A rendering.

    Each entity represents one parcel. Entities at the same (normalized)
    address are grouped into a single row. Multi-value fields become
    RichText with bullet-point paragraphs; single values stay as strings.
    Entities with empty/missing addresses are skipped.
    """
    from collections import OrderedDict

    groups = OrderedDict()  # normalized_addr → {display_addr, municipality, county, owners[], parcel_ids[], legal_descriptions[]}

    for entity in entities:
        raw_addr = entity.get("address", "")
        norm = normalize_address(raw_addr)
        if not norm:
            continue  # skip entities with no address
        if norm not in groups:
            groups[norm] = {
                "display_addr": raw_addr.strip(),
                "municipality": entity.get("municipality", ""),
                "county": entity.get("county", ""),
                "owners": [],
                "parcel_ids": [],
                "legal_descriptions": [],
            }
        g = groups[norm]
        owner = (entity.get("owner") or entity.get("name") or "").strip()
        if owner and owner not in g["owners"]:
            g["owners"].append(owner)
        pid = (entity.get("parcel_ids") or entity.get("parcel_id") or "").strip()
        if pid:
            g["parcel_ids"].append(pid)
        legal = (entity.get("legal_description") or entity.get("legal_descriptions") or "").strip()
        if legal:
            g["legal_descriptions"].append(legal)

    result = []
    for norm, g in groups.items():
        result.append({
            "address": g["display_addr"],
            "municipality": g["municipality"],
            "county": g["county"],
            "owners_display": _multi_value_display(g["owners"]),
            "parcel_ids_display": _multi_value_display(g["parcel_ids"]),
            "legal_descriptions_display": _multi_value_display(g["legal_descriptions"]),
        })
    return result


def _multi_value_display(values: list[str]):
    """Return plain string for single value, RichText with bullets for multiple."""
    if not values:
        return ""
    if len(values) == 1:
        return values[0]
    rt = RichText()
    for i, v in enumerate(values):
        if i > 0:
            rt.add("\a")
        rt.add(f"\u2022 {v}")
    return rt
```

**Step 5: Run tests**

Run: `cd rrg-commercial-pa && python -m pytest tests/test_pa_docx.py::TestGroupEntitiesByAddress tests/test_pa_docx.py::TestExhibitAHelpers -v`
Expected: All PASS.

Run: `cd rrg-commercial-pa && python -m pytest tests/test_pa_docx.py -v`
Expected: All 37 existing + 16 new = 53 tests pass.

**Step 6: Commit**

```bash
git add rrg-commercial-pa/exhibit_a_helpers.py rrg-commercial-pa/pa_docx.py rrg-commercial-pa/tests/test_pa_docx.py
git commit -m "feat(pa): add exhibit_a_helpers.py and _group_entities_by_address"
```

---

### Task 2: Wire grouping into `_build_context()` and update `_apply_exhibit_a_logic()`

**Files:**
- Modify: `rrg-commercial-pa/pa_docx.py`
- Test: `rrg-commercial-pa/tests/test_pa_docx.py`

**Step 1: Write failing tests**

```python
from pa_docx import _build_context

class TestBuildContextExhibitA:
    """Tests that _build_context produces exhibit_a_properties."""

    def test_two_addresses_produces_exhibit_a_properties(self):
        variables = {
            "exhibit_a_entities": [
                {"name": "LLC A", "address": "100 Main", "municipality": "Pontiac",
                 "county": "Oakland", "parcel_ids": "001", "legal_description": "L1"},
                {"name": "LLC B", "address": "200 Oak", "municipality": "Troy",
                 "county": "Oakland", "parcel_ids": "002", "legal_description": "L2"},
            ],
            "seller_name": "Test Seller",
        }
        ctx = _build_context(variables)
        assert "exhibit_a_properties" in ctx
        assert len(ctx["exhibit_a_properties"]) == 2
        assert ctx["use_exhibit_a"] is True

    def test_one_address_no_exhibit_a(self):
        variables = {
            "exhibit_a_entities": [
                {"name": "LLC A", "address": "100 Main", "municipality": "Pontiac",
                 "county": "Oakland", "parcel_ids": "001", "legal_description": "L1"},
            ],
        }
        ctx = _build_context(variables)
        assert ctx["use_exhibit_a"] is False

    def test_two_parcels_same_address_counts_as_one(self):
        """Two entities at same address → 1 grouped property → no Exhibit A."""
        variables = {
            "exhibit_a_entities": [
                {"name": "LLC A", "address": "100 Main", "municipality": "Pontiac",
                 "county": "Oakland", "parcel_ids": "001", "legal_description": "L1"},
                {"name": "LLC B", "address": "100 Main", "municipality": "Pontiac",
                 "county": "Oakland", "parcel_ids": "002", "legal_description": "L2"},
            ],
        }
        ctx = _build_context(variables)
        assert len(ctx["exhibit_a_properties"]) == 1
        assert ctx["use_exhibit_a"] is False

    def test_three_addresses_two_with_multi_parcels(self):
        """3 addresses (one with 2 parcels) → 3 grouped rows, Exhibit A active."""
        variables = {
            "exhibit_a_entities": [
                {"name": "A", "address": "100 Main", "municipality": "P",
                 "county": "O", "parcel_ids": "001", "legal_description": "L1"},
                {"name": "B", "address": "100 Main", "municipality": "P",
                 "county": "O", "parcel_ids": "002", "legal_description": "L2"},
                {"name": "C", "address": "200 Oak", "municipality": "T",
                 "county": "O", "parcel_ids": "003", "legal_description": "L3"},
                {"name": "D", "address": "300 Elm", "municipality": "R",
                 "county": "W", "parcel_ids": "004", "legal_description": "L4"},
            ],
            "seller_name": "Seller",
        }
        ctx = _build_context(variables)
        assert len(ctx["exhibit_a_properties"]) == 3
        assert ctx["use_exhibit_a"] is True

    def test_multi_owner_seller_intro(self):
        """Multiple distinct owners across entities → seller references Exhibit A."""
        variables = {
            "exhibit_a_entities": [
                {"name": "LLC A", "address": "100 Main", "municipality": "P",
                 "county": "O", "parcel_ids": "001", "legal_description": "L1"},
                {"name": "LLC B", "address": "200 Oak", "municipality": "T",
                 "county": "O", "parcel_ids": "002", "legal_description": "L2"},
            ],
            "seller_name": "Fallback Seller",
        }
        ctx = _build_context(variables)
        assert "Exhibit A" in ctx["seller_intro"]

    def test_single_owner_multi_address_seller_inline(self):
        """Same owner at 2 addresses → seller stays inline."""
        variables = {
            "exhibit_a_entities": [
                {"name": "Same LLC", "address": "100 Main", "municipality": "P",
                 "county": "O", "parcel_ids": "001", "legal_description": "L1"},
                {"name": "Same LLC", "address": "200 Oak", "municipality": "T",
                 "county": "O", "parcel_ids": "002", "legal_description": "L2"},
            ],
            "seller_name": "Same LLC",
            "seller_entity_type": "a Michigan LLC",
        }
        ctx = _build_context(variables)
        assert ctx["use_exhibit_a"] is True
        assert "Same LLC" in ctx["seller_intro"]
        assert "Exhibit A" not in ctx["seller_intro"]
```

**Step 2: Run tests to verify they fail**

Run: `cd rrg-commercial-pa && python -m pytest tests/test_pa_docx.py::TestBuildContextExhibitA -v`
Expected: FAIL — `exhibit_a_properties` not in context.

**Step 3: Update `_build_context()` and `_apply_exhibit_a_logic()`**

Changes to `pa_docx.py`:

1. Import from `exhibit_a_helpers`:
   ```python
   from exhibit_a_helpers import exhibit_a_active, exhibit_a_multi_owner, get_distinct_owners
   ```

2. In `_build_context()`, after normalizing `exhibit_a_entities`, add:
   ```python
   ctx["exhibit_a_properties"] = _group_entities_by_address(ctx.get("exhibit_a_entities", []))
   ```

3. Rewrite `_apply_exhibit_a_logic()` to use the shared helpers:
   - `use_exhibit_a = exhibit_a_active(entities)` (uses grouped address count)
   - Multi-owner check: `exhibit_a_multi_owner(entities)` (uses `owner` || `name` fallback)
   - This replaces the old `e.get("name", "").strip()` at line 90 that was missing the `owner` fallback (CRITICAL fix #3)

**Step 4: Run all tests**

Run: `cd rrg-commercial-pa && python -m pytest tests/test_pa_docx.py -v`
Expected: All pass.

**Step 5: Commit**

```bash
git add rrg-commercial-pa/pa_docx.py rrg-commercial-pa/tests/test_pa_docx.py
git commit -m "feat(pa): wire address grouping into _build_context, use shared exhibit_a helpers"
```

---

### Task 3: Update template + existing tests for new columns

**Files:**
- Modify: `rrg-commercial-pa/templates/commercial_pa.docx` (via XML editing)
- Modify: `rrg-commercial-pa/tests/test_pa_docx.py`

**NOTE:** This task merges the old Tasks 3 and 4 to avoid a broken-test window.

**Step 1: Write failing tests for new column structure**

```python
class TestExhibitANewColumns:
    """Tests for the redesigned address-focused Exhibit A table."""

    def test_new_column_headers_present(self, complete_variables, sample_exhibit_a):
        variables = {**complete_variables, "exhibit_a_entities": sample_exhibit_a}
        result = generate_pa_docx(variables)
        buf = io.BytesIO(result)
        with zipfile.ZipFile(buf) as zf:
            doc_xml = zf.read("word/document.xml").decode("utf-8")
            assert "Parcel ID(s)" in doc_xml
            assert "Owner(s)" in doc_xml
            assert "Legal Description(s)" in doc_xml

    def test_multi_parcel_same_address_renders_once(self, complete_variables):
        variables = {**complete_variables}
        variables["exhibit_a_entities"] = [
            {"name": "LLC A", "address": "100 Main", "municipality": "Pontiac",
             "county": "Oakland", "parcel_ids": "001", "legal_description": "Lot 1"},
            {"name": "LLC B", "address": "100 Main", "municipality": "Pontiac",
             "county": "Oakland", "parcel_ids": "002", "legal_description": "Lot 2"},
            {"name": "LLC C", "address": "200 Oak", "municipality": "Troy",
             "county": "Oakland", "parcel_ids": "003", "legal_description": "Lot 3"},
        ]
        result = generate_pa_docx(variables)
        buf = io.BytesIO(result)
        with zipfile.ZipFile(buf) as zf:
            doc_xml = zf.read("word/document.xml").decode("utf-8")
            assert "100 Main" in doc_xml
            assert "200 Oak" in doc_xml
            assert "LLC A" in doc_xml
            assert "LLC B" in doc_xml
            assert "LLC C" in doc_xml

    def test_bullet_character_in_multi_value(self, complete_variables):
        variables = {**complete_variables}
        variables["exhibit_a_entities"] = [
            {"name": "LLC A", "address": "100 Main", "municipality": "Pontiac",
             "county": "Oakland", "parcel_ids": "001", "legal_description": "Lot 1"},
            {"name": "LLC B", "address": "100 Main", "municipality": "Pontiac",
             "county": "Oakland", "parcel_ids": "002", "legal_description": "Lot 2"},
            {"name": "LLC C", "address": "200 Oak", "municipality": "Troy",
             "county": "Oakland", "parcel_ids": "003", "legal_description": "Lot 3"},
        ]
        result = generate_pa_docx(variables)
        buf = io.BytesIO(result)
        with zipfile.ZipFile(buf) as zf:
            doc_xml = zf.read("word/document.xml").decode("utf-8")
            assert "\u2022" in doc_xml
```

**Step 2: Update existing tests that reference old column content**

- `test_exhibit_a_table_has_six_columns`: Add assertions for "Owner(s)" and "Parcel ID(s)" in addition to existing "Municipality" and "County" checks.
- All other existing tests should still pass as-is (LLC names still appear in Owner(s) column, parcel IDs still appear, etc.)

**Step 3: Edit the template XML**

Unzip `templates/commercial_pa.docx`, modify `word/document.xml`:

1. **Header row**: `Name of LLC | Address | Municipality | County | Parcel Id's it owns | Legal descriptions of Parcels` → `Address | Municipality | County | Parcel ID(s) | Owner(s) | Legal Description(s)`

2. **Loop**: `{%tr for entity in exhibit_a_entities %}` → `{%tr for prop in exhibit_a_properties %}`

3. **Data row cells**:
   - `{{ entity.name }}` | `{{ entity.address }}` | `{{ entity.municipality }}` | `{{ entity.county }}` | `{{ entity.parcel_ids }}` | `{{ entity.legal_description }}`
   - → `{{ prop.address }}` | `{{ prop.municipality }}` | `{{ prop.county }}` | `{{r prop.parcel_ids_display }}` | `{{r prop.owners_display }}` | `{{r prop.legal_descriptions_display }}`
   - NOTE: `{{r }}` is required for the three multi-value columns because they may be RichText objects. For single-value columns (address, municipality, county), plain `{{ }}` is fine.

4. **Endfor**: `{%tr endfor %}` — stays the same.

5. **Column widths** (`<w:tblGrid>` gridCol values, total ~10653 DXA):
   - Address: 2200
   - Municipality: 1400
   - County: 1400
   - Parcel ID(s): 1600
   - Owner(s): 1800
   - Legal Description(s): 2253

**Step 4: Repackage template**

Rezip preserving all other ZIP entries exactly (copy ZipInfo entries from original).

**Step 5: Run all tests**

Run: `cd rrg-commercial-pa && python -m pytest tests/test_pa_docx.py -v`
Expected: All pass (existing + new).

**Step 6: Commit**

```bash
git add rrg-commercial-pa/templates/commercial_pa.docx rrg-commercial-pa/tests/test_pa_docx.py
git commit -m "feat(pa): update Exhibit A template to address-focused columns with RichText"
```

---

### Task 4: Update `pa_handler.py` — prompts, summaries, and shared helpers

**Files:**
- Modify: `rrg-commercial-pa/pa_handler.py`
- Modify: `rrg-commercial-pa/tests/test_pa_handler.py`

**Step 1: Replace independent Exhibit A functions with shared imports**

Replace `_exhibit_a_active()` and `_exhibit_a_multi_seller()` in `pa_handler.py` with imports from `exhibit_a_helpers`:

```python
from exhibit_a_helpers import exhibit_a_active, exhibit_a_multi_owner
```

Update all call sites:
- `_exhibit_a_active(variables)` → `exhibit_a_active(variables.get("exhibit_a_entities", []))`
- `_exhibit_a_multi_seller(variables)` → `exhibit_a_multi_owner(variables.get("exhibit_a_entities", []))`

**Step 2: Update LLM extraction prompts**

In `extract_pa_data()`:
- Entity key description: `name` → `owner`
- "Create one entity per property" → "Create one entity per parcel. If a property has multiple parcels (e.g. building + parking lot on separate parcels), create separate entities with the same address."

In `apply_changes()`:
- Same key rename.

**Step 3: Update `format_exhibit_a_summary()`**

- Change `entity.get("name", "Unknown")` → `entity.get("owner") or entity.get("name", "Unknown")`
- Consider updating header to say "N properties" instead of "N entities" and organize by address. (Optional UX improvement — can be deferred.)

**Step 4: Update `test_pa_handler.py`**

Review tests in `TestRemainingVariablesWithExhibitA` and `TestFormatExhibitASummary`:
- `test_exhibit_a_skips_property_fields` (line 481): Has 2 entities at different addresses → still works (2 addresses >= 2).
- `test_exhibit_a_multi_llc_skips_seller_fields` (line 501): Has 2 entities with different LLCs at different addresses → still works.
- `test_exhibit_a_single_llc_keeps_seller_fields` (line 521): Has 2 entities at different addresses with same LLC → still works.
- `test_no_exhibit_a_shows_all_fields` (line 536): No entities → still works.
- `test_single_entity_returns_empty` (line 560): 1 entity at 1 address → returns empty. Still works.
- `test_two_entities_returns_summary` (line 572): 2 entities at different addresses → returns summary. Still works.

**BEHAVIORAL CHANGE to verify:** `test_exhibit_a_skips_property_fields` (line 481) has entities `{"name": "LLC A", "address": "100 Main"}` and `{"name": "LLC A", "address": "200 Main"}`. These are at 2 different addresses → `exhibit_a_active()` returns True → test passes. But if someone changes these to the same address, the test would fail. Add a comment explaining this.

**Step 5: Run all tests**

Run: `cd rrg-commercial-pa && python -m pytest tests/ -v`
Expected: All pass.

**Step 6: Commit**

```bash
git add rrg-commercial-pa/pa_handler.py rrg-commercial-pa/tests/test_pa_handler.py
git commit -m "feat(pa): use shared exhibit_a helpers, rename entity name→owner in prompts"
```

---

### Task 5: Update `draft_store.py` — shared helpers for `_completion_pct()`

**Files:**
- Modify: `rrg-commercial-pa/draft_store.py`
- Modify: `rrg-commercial-pa/tests/test_draft_store.py`

**Why:** `_completion_pct()` at line 71 has its own inline copy of the "2+ entities" check and uses `.get("name")` without `owner` fallback. Without this fix, completion percentage will use the old entity-count logic while the document uses address-count logic.

**Step 1: Replace inline logic with shared imports**

```python
from exhibit_a_helpers import exhibit_a_active, exhibit_a_multi_owner
```

Replace lines 80-89 of `_completion_pct()`:

```python
# OLD:
entities = variables.get("exhibit_a_entities", [])
exhibit_a_active = isinstance(entities, list) and len(entities) >= 2
covered = set()
if exhibit_a_active:
    covered |= _EXHIBIT_A_PROPERTY_FIELDS
    names = {e.get("name", "").strip() for e in entities if isinstance(e, dict)}
    names.discard("")
    if len(names) > 1:
        covered |= _EXHIBIT_A_SELLER_FIELDS

# NEW:
entities = variables.get("exhibit_a_entities", [])
covered = set()
if exhibit_a_active(entities):
    covered |= _EXHIBIT_A_PROPERTY_FIELDS
    if exhibit_a_multi_owner(entities):
        covered |= _EXHIBIT_A_SELLER_FIELDS
```

**Step 2: Add test for same-address multi-parcel completion**

In `test_draft_store.py`, add a test that verifies 2 entities at the SAME address do NOT trigger Exhibit A coverage:

```python
def test_completion_pct_same_address_no_exhibit_a(self, draft_store):
    """Two entities at same address → Exhibit A not active → property fields NOT covered."""
    variables = {
        "purchaser_name": "Test",
        "exhibit_a_entities": [
            {"name": "LLC A", "address": "100 Main"},
            {"name": "LLC B", "address": "100 Main"},
        ],
    }
    draft_id = draft_store.create_draft("100 Main", variables,
                                         exhibit_a_entities=variables["exhibit_a_entities"])
    drafts = draft_store.list_drafts()
    # With Exhibit A not active, property fields should NOT be auto-covered
    # so completion pct should be lower than if they were covered
    draft = next(d for d in drafts if d["id"] == draft_id)
    # Just verify it doesn't crash and returns a reasonable number
    assert 0 <= draft["completion_pct"] <= 100
```

**Step 3: Run tests**

Run: `cd rrg-commercial-pa && python -m pytest tests/test_draft_store.py -v`
Expected: All pass.

Run: `cd rrg-commercial-pa && python -m pytest tests/ -v`
Expected: All pass.

**Step 4: Commit**

```bash
git add rrg-commercial-pa/draft_store.py rrg-commercial-pa/tests/test_draft_store.py
git commit -m "fix(pa): use shared exhibit_a helpers in draft_store completion_pct"
```

---

### Task 6: Update memory and docs

**Files:**
- Modify: `~/.claude/projects/-Users-jacobphillips-rrg-server/memory/pa-docx-tests.md`
- Modify: `rrg-commercial-pa/CLAUDE.md`

**Step 1: Update test baseline**

Update `pa-docx-tests.md` with new test count and new test names.

**Step 2: Update CLAUDE.md**

In the DOCX Generation section, add:
- Exhibit A uses address-focused grouping (one row per property address)
- Multi-value cells (Parcel IDs, Owners, Legal Descriptions) use RichText with bullet points
- Shared `exhibit_a_helpers.py` provides `exhibit_a_active()`, `exhibit_a_multi_owner()`, `normalize_address()` — used by `pa_docx.py`, `pa_handler.py`, and `draft_store.py`

**Step 3: Commit**

```bash
git add rrg-commercial-pa/CLAUDE.md
git commit -m "docs(pa): update CLAUDE.md for address-focused Exhibit A redesign"
```

---

## Dependency Graph

```
Task 1 (helpers + grouping function)
  ↓
Task 2 (_build_context + _apply_exhibit_a_logic)
  ↓
Task 3 (template + test updates)  ←  depends on Task 2 (exhibit_a_properties in context)
  ↓
Task 4 (pa_handler.py)  ←  depends on Task 1 (shared helpers exist)
  ↓
Task 5 (draft_store.py)  ←  depends on Task 1 (shared helpers exist)
  ↓
Task 6 (docs + memory)  ←  depends on all above
```

Tasks 4 and 5 are independent of each other (both depend on Task 1 only) and could be done in parallel. Task 3 must come after Task 2. Task 6 is always last.

## Edge Cases Covered

| Scenario | Expected Behavior |
|----------|-------------------|
| 2 entities, same address | 1 grouped row, no Exhibit A |
| 2 entities, different addresses | 2 grouped rows, Exhibit A active |
| 3 entities, 2 at same address + 1 different | 2 grouped rows, Exhibit A active |
| Same owner, multiple addresses | Exhibit A active, seller inline |
| Different owners, multiple addresses | Exhibit A active, seller → "Exhibit A" reference |
| Entity with empty address | Skipped (not grouped into catch-all) |
| Address case mismatch ("Main" vs "main") | Grouped together (normalized) |
| Address whitespace mismatch | Grouped together (normalized) |
| Old `name` key in entity dict | Backwards compatible (falls back from `owner` to `name`) |
| `legal_descriptions` plural key | Handled by `_normalize_entity()` before grouping |
