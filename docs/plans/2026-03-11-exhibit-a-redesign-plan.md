# Exhibit A Table Redesign — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Change Exhibit A from LLC-focused (one row per entity) to address-focused (one row per property address), with bullet-point lists for multi-value cells (Parcel IDs, Owners, Legal Descriptions).

**Architecture:** Keep flat entity extraction (one entity per parcel, LLM unchanged). Add a Python grouping layer in `pa_docx.py` that groups entities by address at render time and produces RichText objects for multi-value cells. Update template columns to: Address | Municipality | County | Parcel ID(s) | Owner(s) | Legal Description(s).

**Tech Stack:** Python, docxtpl (RichText with `\a` for cell paragraph breaks), OOXML template editing.

---

### Task 1: Add `_group_entities_by_address()` to `pa_docx.py`

**Files:**
- Modify: `rrg-commercial-pa/pa_docx.py`
- Test: `rrg-commercial-pa/tests/test_pa_docx.py`

**Step 1: Write the failing tests**

Add a new `TestGroupEntitiesByAddress` class in `test_pa_docx.py`:

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
        # Single values should be plain strings, not RichText
        assert result[0]["address"] == "100 Main"
        assert isinstance(result[0]["owners_display"], str)
        assert result[0]["owners_display"] == "LLC A"
        assert result[0]["parcel_ids_display"] == "001"
        assert result[0]["legal_descriptions_display"] == "Lot 1"

    def test_multiple_parcels_same_address(self):
        """Two entities at same address → one row, bullet points in multi-value cells."""
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
        # Multi-value fields should be RichText objects
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
        """Entities with 'name' key (old format) should work the same as 'owner'."""
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
        # Owner is the same for both → single value, no bullets
        assert isinstance(result[0]["owners_display"], str)
        assert result[0]["owners_display"] == "Same LLC"
```

**Step 2: Run tests to verify they fail**

Run: `cd rrg-commercial-pa && python -m pytest tests/test_pa_docx.py::TestGroupEntitiesByAddress -v`
Expected: ImportError — `_group_entities_by_address` doesn't exist yet.

**Step 3: Write the implementation**

Add to `pa_docx.py`:

```python
from docxtpl import DocxTemplate, RichText

def _group_entities_by_address(entities: list[dict]) -> list[dict]:
    """Group flat entity dicts by address for Exhibit A rendering.

    Each entity represents one parcel. Entities at the same address
    are grouped into a single row. Multi-value fields (owners, parcel IDs,
    legal descriptions) become RichText with bullet-point paragraphs when
    there are multiple values; plain strings when there's only one.

    Returns list of dicts with keys: address, municipality, county,
    owners_display, parcel_ids_display, legal_descriptions_display.
    """
    from collections import OrderedDict

    groups = OrderedDict()  # address → {municipality, county, owners[], parcel_ids[], legal_descriptions[]}

    for entity in entities:
        addr = entity.get("address", "").strip()
        if addr not in groups:
            groups[addr] = {
                "municipality": entity.get("municipality", ""),
                "county": entity.get("county", ""),
                "owners": [],
                "parcel_ids": [],
                "legal_descriptions": [],
            }
        g = groups[addr]
        owner = entity.get("owner", "") or entity.get("name", "")
        if owner and owner not in g["owners"]:
            g["owners"].append(owner)
        pid = entity.get("parcel_ids", "") or entity.get("parcel_id", "")
        if pid:
            g["parcel_ids"].append(pid)
        legal = entity.get("legal_description", "") or entity.get("legal_descriptions", "")
        if legal:
            g["legal_descriptions"].append(legal)

    result = []
    for addr, g in groups.items():
        result.append({
            "address": addr,
            "municipality": g["municipality"],
            "county": g["county"],
            "owners_display": _multi_value_display(g["owners"]),
            "parcel_ids_display": _multi_value_display(g["parcel_ids"]),
            "legal_descriptions_display": _multi_value_display(g["legal_descriptions"]),
        })
    return result


def _multi_value_display(values: list[str]):
    """Return a plain string for single values, RichText with bullets for multiple."""
    if not values:
        return ""
    if len(values) == 1:
        return values[0]
    rt = RichText()
    for i, v in enumerate(values):
        if i > 0:
            rt.add("\a")  # new paragraph within cell
        rt.add(f"\u2022 {v}")  # bullet character
    return rt
```

**Step 4: Run tests to verify they pass**

Run: `cd rrg-commercial-pa && python -m pytest tests/test_pa_docx.py::TestGroupEntitiesByAddress -v`
Expected: All 6 PASS.

**Step 5: Also run the full existing test suite to confirm nothing broke**

Run: `cd rrg-commercial-pa && python -m pytest tests/test_pa_docx.py -v`
Expected: All 37 existing tests still pass + 6 new = 43 total.

**Step 6: Commit**

```bash
git add rrg-commercial-pa/pa_docx.py rrg-commercial-pa/tests/test_pa_docx.py
git commit -m "feat(pa): add _group_entities_by_address for address-focused Exhibit A"
```

---

### Task 2: Wire grouping into `_build_context()` and update `_apply_exhibit_a_logic()`

**Files:**
- Modify: `rrg-commercial-pa/pa_docx.py`
- Test: `rrg-commercial-pa/tests/test_pa_docx.py`

**Step 1: Write the failing tests**

Add tests that verify `exhibit_a_properties` appears in the rendered context:

```python
from pa_docx import _build_context

class TestBuildContextExhibitA:
    """Tests that _build_context produces exhibit_a_properties for the template."""

    def test_two_addresses_produces_exhibit_a_properties(self):
        """Two entities at different addresses → exhibit_a_properties with 2 items."""
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
        """One entity → no Exhibit A, exhibit_a_properties still set but use_exhibit_a False."""
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
        """3 addresses, one with 2 parcels → 3 grouped rows, use_exhibit_a True."""
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
```

**Step 2: Run tests to verify they fail**

Run: `cd rrg-commercial-pa && python -m pytest tests/test_pa_docx.py::TestBuildContextExhibitA -v`
Expected: FAIL — `exhibit_a_properties` not in context yet.

**Step 3: Update `_build_context()` and `_apply_exhibit_a_logic()`**

In `pa_docx.py`, modify `_build_context()` to call `_group_entities_by_address()` after normalizing entities, and set `exhibit_a_properties` in the context. Modify `_apply_exhibit_a_logic()` to use `exhibit_a_properties` count for the `use_exhibit_a` check (grouped addresses >= 2, not raw entities >= 2).

Key changes:
- After normalizing `exhibit_a_entities`, call `_group_entities_by_address(ctx["exhibit_a_entities"])` → set as `ctx["exhibit_a_properties"]`
- `_apply_exhibit_a_logic()` checks `len(ctx.get("exhibit_a_properties", []))` >= 2 for `use_exhibit_a`
- Seller intro multi-LLC check now uses distinct owners across all entities (same logic, just using `owner` or `name` key)

**Step 4: Run tests**

Run: `cd rrg-commercial-pa && python -m pytest tests/test_pa_docx.py -v`
Expected: All pass.

**Step 5: Commit**

```bash
git add rrg-commercial-pa/pa_docx.py rrg-commercial-pa/tests/test_pa_docx.py
git commit -m "feat(pa): wire address grouping into _build_context, use grouped count for Exhibit A"
```

---

### Task 3: Update template to use new columns and `exhibit_a_properties`

**Files:**
- Modify: `rrg-commercial-pa/templates/commercial_pa.docx` (via XML editing)
- Test: `rrg-commercial-pa/tests/test_pa_docx.py`

**Step 1: Write failing tests for new column structure**

```python
class TestExhibitANewColumns:
    """Tests for the redesigned address-focused Exhibit A table."""

    def test_new_column_headers_present(self, complete_variables, sample_exhibit_a):
        """Table should have new column headers."""
        variables = {**complete_variables, "exhibit_a_entities": sample_exhibit_a}
        result = generate_pa_docx(variables)
        buf = io.BytesIO(result)
        with zipfile.ZipFile(buf) as zf:
            doc_xml = zf.read("word/document.xml").decode("utf-8")
            assert "Parcel ID(s)" in doc_xml
            assert "Owner(s)" in doc_xml
            assert "Legal Description(s)" in doc_xml

    def test_multi_parcel_same_address_renders_once(self, complete_variables):
        """Two parcels at same address → one row in table, address appears once."""
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
            # Both addresses should appear
            assert "100 Main" in doc_xml
            assert "200 Oak" in doc_xml
            # Owners should appear
            assert "LLC A" in doc_xml
            assert "LLC B" in doc_xml
            assert "LLC C" in doc_xml

    def test_bullet_character_in_multi_value(self, complete_variables):
        """Multi-value cells should contain bullet character (U+2022)."""
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
            # Bullet character should appear for the multi-parcel address
            assert "\u2022" in doc_xml
```

**Step 2: Edit the template XML**

Unzip `templates/commercial_pa.docx`, modify `word/document.xml`:

1. **Header row**: Change from `Name of LLC | Address | Municipality | County | Parcel Id's it owns | Legal descriptions of Parcels` → `Address | Municipality | County | Parcel ID(s) | Owner(s) | Legal Description(s)`

2. **Loop variable**: Change `{%tr for entity in exhibit_a_entities %}` → `{%tr for prop in exhibit_a_properties %}`

3. **Data row cells**: Change from:
   - `{{ entity.name }}` | `{{ entity.address }}` | `{{ entity.municipality }}` | `{{ entity.county }}` | `{{ entity.parcel_ids }}` | `{{ entity.legal_description }}`

   To:
   - `{{ prop.address }}` | `{{ prop.municipality }}` | `{{ prop.county }}` | `{{r prop.parcel_ids_display }}` | `{{r prop.owners_display }}` | `{{r prop.legal_descriptions_display }}`

   Note: `{{r ... }}` is required for RichText objects. For single-value cells (address, municipality, county), plain `{{ }}` is fine since they're always strings.

4. **Endfor**: Change `{%tr endfor %}` (no variable reference needed, stays the same).

5. **Column widths**: Adjust `<w:tblGrid>` gridCol values. Address-focused layout needs wider Address column. Suggested widths (total ~10653 DXA):
   - Address: 2200
   - Municipality: 1400
   - County: 1400
   - Parcel ID(s): 1600
   - Owner(s): 1800
   - Legal Description(s): 2253

**Step 3: Repackage template**

Rezip with modified XML, preserving all other ZIP entries exactly.

**Step 4: Run all tests**

Run: `cd rrg-commercial-pa && python -m pytest tests/test_pa_docx.py -v`
Expected: All pass (existing + new).

**Step 5: Commit**

```bash
git add rrg-commercial-pa/templates/commercial_pa.docx rrg-commercial-pa/tests/test_pa_docx.py
git commit -m "feat(pa): update Exhibit A template to address-focused columns with RichText"
```

---

### Task 4: Update existing tests to match new column structure

**Files:**
- Modify: `rrg-commercial-pa/tests/test_pa_docx.py`
- Modify: `rrg-commercial-pa/tests/conftest.py`

**Step 1: Update `conftest.py` sample fixtures**

The `sample_exhibit_a` fixture entities should also have `owner` key (in addition to `name` for backwards compat):

No changes needed — the grouping function handles `name` → `owner` backwards compat.

**Step 2: Update existing tests that check for old column content**

Tests to review and update:
- `test_exhibit_a_three_entities`: Currently checks for LLC names in doc_xml. These should still appear (as owners in the Owner(s) column).
- `test_exhibit_a_entity_fields_appear`: Checks parcel_ids and legal_descriptions — still valid.
- `test_exhibit_a_table_has_six_columns`: Currently checks for "Municipality" and "County" — add checks for "Owner(s)" and "Parcel ID(s)".
- `test_exhibit_a_municipality_county_rendered`: Still valid.
- `test_multi_llc_exhibit_a_seller_reference`: Still valid — multi-LLC detection unchanged.
- `test_same_llc_multi_property_seller_inline`: Still valid.

**Step 3: Run full test suite**

Run: `cd rrg-commercial-pa && python -m pytest tests/test_pa_docx.py -v`
Expected: All pass.

**Step 4: Commit**

```bash
git add rrg-commercial-pa/tests/test_pa_docx.py rrg-commercial-pa/tests/conftest.py
git commit -m "test(pa): update Exhibit A tests for address-focused columns"
```

---

### Task 5: Update `pa_handler.py` prompts (rename `name` → `owner`)

**Files:**
- Modify: `rrg-commercial-pa/pa_handler.py`
- Test: `rrg-commercial-pa/tests/test_pa_handler.py`

**Step 1: Update extraction prompt**

In `extract_pa_data()`:
- Change entity key description: `name, address, municipality, county, parcel_ids, legal_description` → `owner, address, municipality, county, parcel_ids, legal_description`
- Change "Create one entity per property" → "Create one entity per parcel. If a property has multiple parcels (e.g. building + parking lot on separate parcels), create separate entities with the same address."
- Keep backwards note: "The 'owner' field is the LLC or company that owns the parcel (previously called 'name')."

In `apply_changes()`:
- Same key rename in entity description.

In `format_exhibit_a_summary()`:
- Change `entity.get("name", "Unknown")` → `entity.get("owner", "") or entity.get("name", "Unknown")`

In `_exhibit_a_multi_seller()`:
- Change `e.get("name", "")` → `e.get("owner", "") or e.get("name", "")`

**Step 2: Run tests**

Run: `cd rrg-commercial-pa && python -m pytest tests/ -v`
Expected: All pass.

**Step 3: Commit**

```bash
git add rrg-commercial-pa/pa_handler.py
git commit -m "feat(pa): rename entity 'name' to 'owner' in LLM prompts"
```

---

### Task 6: Update memory and docs

**Files:**
- Modify: `~/.claude/projects/-Users-jacobphillips-rrg-server/memory/pa-docx-tests.md`
- Modify: `rrg-commercial-pa/CLAUDE.md`

**Step 1: Update test baseline**

Update `pa-docx-tests.md` with the new test count and new test names.

**Step 2: Update CLAUDE.md**

In the DOCX Generation section, note that Exhibit A uses address-focused grouping with RichText bullet points for multi-value cells.

**Step 3: Commit**

```bash
git add rrg-commercial-pa/CLAUDE.md
git commit -m "docs(pa): update CLAUDE.md for address-focused Exhibit A"
```
