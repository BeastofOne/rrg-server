# Lead Parser Fixes Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix three lead parsing bugs: BizBuySell name bleed across lines, incomplete first-name validation list, and Crexi subject line emoji/title prefix handling.

**Architecture:** Three independent fixes in two Windmill scripts. Fix 1 and 3 modify the webhook parser (`gmail_pubsub_webhook.py`). Fix 2 replaces the inline name list with an SSA-sourced dataset in a new data module, referenced by the draft generator script.

**Tech Stack:** Python regex, SSA baby names CSV data, Windmill inline scripts

---

### Task 1: Fix BizBuySell regex line bleed

**Files:**
- Modify: `windmill/f/switchboard/gmail_pubsub_webhook.py:467,474`
- Create: `tests/test_parse_name_field.py`

**Step 1: Create test file with regression tests**

Create `tests/test_parse_name_field.py`. This requires extracting `parse_name_field` from the webhook script. Since the function is standalone (only uses `re`), copy it into the test file for unit testing.

```python
import re
import pytest


def parse_name_field(body, subject=""):
    """Extract a person's name from notification body text.

    Tries labeled patterns first (Name: John Doe), then falls back to
    extracting from subject line.
    """
    # "Name: John Doe" pattern (capitalized)
    m = re.search(
        r'(?:name|contact|buyer|seller|lead)\s*[:\-]\s*([A-Z][a-zA-Z\'\-]+(?:[ \t]+[A-Z][a-zA-Z\'\-]+){0,3})',
        body
    )
    if m:
        return m.group(1).strip()
    # Case-insensitive fallback
    m = re.search(
        r'(?:name|contact|buyer|seller|lead)\s*[:\-]\s*([a-zA-Z\'\-]+(?:[ \t]+[a-zA-Z\'\-]+){0,3})',
        body, re.IGNORECASE
    )
    if m:
        name = m.group(1).strip()
        skip = {'the', 'a', 'an', 'your', 'this', 'that', 'none', 'n/a', 'not', 'no'}
        if len(name) > 1 and name.lower() not in skip:
            return name

    # Subject line fallback: try to extract a capitalized name at the start
    if subject:
        m = re.match(
            r'([A-Z][a-zA-Z\'\-]+(?:\s+[A-Z][a-zA-Z\'\-]+){1,3})\s+(?:has\s+)?(?:opened|executed|requesting|downloaded|favorited|clicked|is\s+requesting)',
            subject, re.IGNORECASE
        )
        if m:
            return m.group(1).strip()

    return ""


class TestParseNameField:
    """Tests for parse_name_field regex fixes."""

    def test_bizbuysell_name_does_not_bleed_across_lines(self):
        """Regression: BizBuySell body with Contact: Jon C followed by
        Contact Email on next line should NOT grab 'Contact Email'."""
        body = "Contact: Jon C\r\n \n\r\n \r\nContact Email: lttc.digital@gmail.com"
        assert parse_name_field(body) == "Jon C"

    def test_bizbuysell_name_single_line(self):
        body = "Contact: Jon C"
        assert parse_name_field(body) == "Jon C"

    def test_standard_name_colon_format(self):
        body = "Name: John Smith"
        assert parse_name_field(body) == "John Smith"

    def test_lead_dash_format(self):
        body = "Lead - Sarah Johnson"
        assert parse_name_field(body) == "Sarah Johnson"

    def test_multiline_body_stops_at_line_break(self):
        body = "Buyer: Jane Doe\nPhone: 555-1234\nEmail: jane@test.com"
        assert parse_name_field(body) == "Jane Doe"

    def test_subject_fallback_when_body_has_no_name(self):
        body = "No name labels here, just text."
        subject = "Glenn Oppenlander has downloaded the OM"
        assert parse_name_field(body, subject) == "Glenn Oppenlander"

    def test_empty_body_empty_subject(self):
        assert parse_name_field("", "") == ""

    def test_case_insensitive_label(self):
        body = "CONTACT: bob smith"
        assert parse_name_field(body) == "bob smith"
```

**Step 2: Run tests to verify the key regression test fails with OLD code, passes with NEW**

First run with the OLD `\s+` version to confirm the regression test fails:

```bash
cd /Users/jacobphillips/rrg-server && python -m pytest tests/test_parse_name_field.py -v
```

Expected: All tests PASS (since the test file already has the fix baked in). This validates the fix works.

To double-check the regression, temporarily change `[ \t]+` back to `\s+` in the test file's function, run again, and confirm `test_bizbuysell_name_does_not_bleed_across_lines` FAILS. Then revert.

**Step 3: Apply the fix to the actual webhook script**

In `windmill/f/switchboard/gmail_pubsub_webhook.py`:

Line 467 — change:
```
r'(?:name|contact|buyer|seller|lead)\s*[:\-]\s*([A-Z][a-zA-Z\'\-]+(?:\s+[A-Z][a-zA-Z\'\-]+){0,3})',
```
to:
```
r'(?:name|contact|buyer|seller|lead)\s*[:\-]\s*([A-Z][a-zA-Z\'\-]+(?:[ \t]+[A-Z][a-zA-Z\'\-]+){0,3})',
```

Line 474 — change:
```
r'(?:name|contact|buyer|seller|lead)\s*[:\-]\s*([a-zA-Z\'\-]+(?:\s+[a-zA-Z\'\-]+){0,3})',
```
to:
```
r'(?:name|contact|buyer|seller|lead)\s*[:\-]\s*([a-zA-Z\'\-]+(?:[ \t]+[a-zA-Z\'\-]+){0,3})',
```

Both changes: `\s+` → `[ \t]+` in the word-separator capture group only.

**Step 4: Commit**

```bash
git add tests/test_parse_name_field.py windmill/f/switchboard/gmail_pubsub_webhook.py
git commit -m "fix: prevent BizBuySell name regex from bleeding across lines

Replace \\s+ with [ \\t]+ in parse_name_field() word separators
so the regex only matches horizontal whitespace between name words,
not newlines/carriage returns."
```

---

### Task 2: Generate SSA first-names dataset

**Files:**
- Create: `scripts/generate_ssa_names.py` (one-time generator script)
- Create: `windmill/f/switchboard/data/ssa_first_names.py` (generated output)

**Step 1: Download SSA baby names data**

```bash
cd /Users/jacobphillips/rrg-server
mkdir -p /tmp/ssa-names
curl -o /tmp/ssa-names/names.zip https://www.ssa.gov/oact/babynames/names.zip
cd /tmp/ssa-names && unzip -o names.zip
```

Verify: `ls /tmp/ssa-names/yob*.txt | head -5` should show year-of-birth files.

**Step 2: Create the generator script**

Create `scripts/generate_ssa_names.py`:

```python
#!/usr/bin/env python3
"""Generate a Python set of common US first names from SSA baby names data.

Filters to names with 100+ occurrences in any year since 1960.
Output: windmill/f/switchboard/data/ssa_first_names.py

Usage:
    # Download SSA data first:
    curl -o /tmp/ssa-names/names.zip https://www.ssa.gov/oact/babynames/names.zip
    cd /tmp/ssa-names && unzip -o names.zip

    # Then run:
    python scripts/generate_ssa_names.py
"""
import os
import glob

SSA_DIR = "/tmp/ssa-names"
MIN_COUNT = 100
MIN_YEAR = 1960
OUTPUT = os.path.join(os.path.dirname(__file__), "..",
                      "windmill", "f", "switchboard", "data", "ssa_first_names.py")

names = set()

for filepath in sorted(glob.glob(os.path.join(SSA_DIR, "yob*.txt"))):
    filename = os.path.basename(filepath)
    year = int(filename[3:7])
    if year < MIN_YEAR:
        continue
    with open(filepath) as f:
        for line in f:
            parts = line.strip().split(",")
            if len(parts) == 3:
                name, gender, count = parts[0], parts[1], int(parts[2])
                if count >= MIN_COUNT:
                    names.add(name.lower())

# Sort for stable output
sorted_names = sorted(names)

os.makedirs(os.path.dirname(OUTPUT), exist_ok=True)
with open(OUTPUT, "w") as f:
    f.write(f'# Auto-generated from US SSA baby names data (years >= {MIN_YEAR}, count >= {MIN_COUNT})\n')
    f.write(f'# Source: https://www.ssa.gov/oact/babynames/names.zip\n')
    f.write(f'# Total names: {len(sorted_names)}\n')
    f.write(f'# To regenerate: python scripts/generate_ssa_names.py\n\n')
    f.write('SSA_FIRST_NAMES = {\n')
    # Write 10 names per line for readability
    for i in range(0, len(sorted_names), 10):
        chunk = sorted_names[i:i+10]
        line = ", ".join(f'"{n}"' for n in chunk)
        f.write(f'    {line},\n')
    f.write('}\n')

print(f"Generated {len(sorted_names)} names to {OUTPUT}")
```

**Step 3: Run the generator**

```bash
cd /Users/jacobphillips/rrg-server && python scripts/generate_ssa_names.py
```

Expected output: `Generated NNNNN names to windmill/f/switchboard/data/ssa_first_names.py`

**Step 4: Verify "cassandra" is in the output**

```bash
grep -c '"cassandra"' windmill/f/switchboard/data/ssa_first_names.py
```

Expected: `1`

**Step 5: Commit the generator and generated data**

```bash
git add scripts/generate_ssa_names.py windmill/f/switchboard/data/ssa_first_names.py
git commit -m "feat: generate SSA first-names dataset for draft greeting validation

10-20K names from US SSA baby names data (1960+, 100+ occurrences).
Replaces the hand-typed 500-name COMMON_FIRST_NAMES list."
```

---

### Task 3: Wire SSA names into draft generator

**Files:**
- Modify: `windmill/f/switchboard/lead_intake.flow/generate_drafts_+_gmail.inline_script.py:21-110`
- Create: `tests/test_get_first_name.py`

**Step 1: Create test for get_first_name with SSA data**

Create `tests/test_get_first_name.py`:

```python
import sys
import os
import pytest

# Add the data module to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..",
                                "windmill", "f", "switchboard", "data"))
from ssa_first_names import SSA_FIRST_NAMES


def get_first_name(full_name):
    """Extract and validate first name from lead name."""
    if not full_name or not full_name.strip():
        return "there"
    first_word = full_name.strip().split()[0]
    if first_word.lower() in SSA_FIRST_NAMES:
        return first_word.capitalize()
    return "there"


class TestGetFirstName:
    """Tests for get_first_name with SSA dataset."""

    def test_cassandra_is_recognized(self):
        """Regression: Cassandra Clark should greet as Cassandra."""
        assert get_first_name("Cassandra Clark") == "Cassandra"

    def test_common_names(self):
        assert get_first_name("John Smith") == "John"
        assert get_first_name("Mario Aljarbo") == "Mario"
        assert get_first_name("Troy Sanabria") == "Troy"
        assert get_first_name("Joyce Bressler") == "Joyce"

    def test_empty_name(self):
        assert get_first_name("") == "there"
        assert get_first_name(None) == "there"

    def test_company_name_fallback(self):
        """Company-like names should still fall back to 'there'."""
        # These first words shouldn't be in SSA data
        assert get_first_name("Novaltus Holdings") == "there"
        assert get_first_name("Bridgerow Blinds") == "there"

    def test_preserves_capitalization(self):
        assert get_first_name("christopher Scheer") == "Christopher"
```

**Step 2: Run tests**

```bash
cd /Users/jacobphillips/rrg-server && python -m pytest tests/test_get_first_name.py -v
```

Expected: All PASS (especially `test_cassandra_is_recognized`).

**Step 3: Update the inline script**

In `windmill/f/switchboard/lead_intake.flow/generate_drafts_+_gmail.inline_script.py`:

Replace lines 21-96 (the `COMMON_FIRST_NAMES` set definition) with:

```python
# SSA first names dataset (~10-20K names, generated from US SSA baby names data)
# To regenerate: python scripts/generate_ssa_names.py
import importlib.util, os
_spec = importlib.util.spec_from_file_location(
    "ssa_first_names",
    os.path.join(os.path.dirname(__file__), "..", "data", "ssa_first_names.py")
)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
COMMON_FIRST_NAMES = _mod.SSA_FIRST_NAMES
```

**Important note:** Windmill inline scripts may not support relative imports. If the above doesn't work in Windmill's sandbox, the fallback is to inline the full SSA set directly in the script (replacing lines 22-96 with the generated set contents). Check by testing the flow in Windmill after deployment.

**Alternative (safer for Windmill):** Copy the contents of `ssa_first_names.py` directly into the inline script, replacing lines 22-96. This avoids any import issues in Windmill's sandbox. The set is large but the script still works.

**Step 4: Commit**

```bash
git add windmill/f/switchboard/lead_intake.flow/generate_drafts_+_gmail.inline_script.py tests/test_get_first_name.py
git commit -m "feat: replace 500-name whitelist with SSA dataset in draft greeting

Cassandra, Mario, and thousands of other names now recognized.
get_first_name() logic unchanged — just the data source."
```

---

### Task 4: Fix Crexi emoji + title prefix

**Files:**
- Modify: `windmill/f/switchboard/gmail_pubsub_webhook.py:553-560`
- Modify: `tests/test_parse_name_field.py` (add Crexi-specific tests)

**Step 1: Add Crexi subject parsing tests**

Add to `tests/test_parse_name_field.py` — a new function that mirrors the Crexi parser's subject-line logic:

```python
def parse_crexi_name_from_subject(subject):
    """Extract name from Crexi notification subject line.

    Mirrors the logic in parse_crexi_lead() for the subject-line name regex.
    """
    # Strip leading non-ASCII (emojis, checkmarks) and whitespace
    cleaned = re.sub(r'^[^\x00-\x7F\s]+\s*', '', subject).strip()

    # Strip known title/role prefixes
    title_pattern = r'^(?:Principal|Agent|Broker|Associate|Director|Manager|VP|CEO|CFO|President|Owner|Partner)\s+'
    cleaned = re.sub(title_pattern, '', cleaned, flags=re.IGNORECASE).strip()

    m = re.match(
        r"([A-Z][a-zA-Z'\-]+(?:\s+[A-Z][a-zA-Z'\-]+){1,3})\s+(?:has\s+)?(?:opened|Executed|requesting|downloaded|favorited|clicked|is\s+requesting)",
        cleaned
    )
    if m:
        return m.group(1).strip()
    return ""


class TestCrexiSubjectParsing:
    """Tests for Crexi subject line name extraction."""

    def test_emoji_and_title_prefix(self):
        """Regression: ✅ Principal Mario Aljarbo opened flyer on ..."""
        subject = "✅ Principal Mario Aljarbo opened flyer on Dairy Queen Grill & Chill in Ypsilanti"
        assert parse_crexi_name_from_subject(subject) == "Mario Aljarbo"

    def test_standard_crexi_subject(self):
        subject = "Glenn Oppenlander has downloaded the OM for Parkwood Multi-Family"
        assert parse_crexi_name_from_subject(subject) == "Glenn Oppenlander"

    def test_emoji_no_title(self):
        subject = "✅ Chris Johnson has downloaded the OM for 1480 Parkwood"
        assert parse_crexi_name_from_subject(subject) == "Chris Johnson"

    def test_title_no_emoji(self):
        subject = "Broker Sarah Chen is requesting info on Hartwick Pines"
        assert parse_crexi_name_from_subject(subject) == "Sarah Chen"

    def test_no_prefix(self):
        subject = "Troy Sanabria has downloaded the OM for Hartwick Pines"
        assert parse_crexi_name_from_subject(subject) == "Troy Sanabria"

    def test_multiple_emojis(self):
        subject = "✅✅ Agent Bob Smith has clicked on Dairy Queen"
        assert parse_crexi_name_from_subject(subject) == "Bob Smith"
```

**Step 2: Run tests**

```bash
cd /Users/jacobphillips/rrg-server && python -m pytest tests/test_parse_name_field.py::TestCrexiSubjectParsing -v
```

Expected: All PASS.

**Step 3: Apply the fix to the Crexi parser**

In `windmill/f/switchboard/gmail_pubsub_webhook.py`, replace lines 553-560:

```python
    # Name from subject: "Glenn Oppenlander has downloaded..."
    # Strip leading emojis/non-ASCII and title prefixes first
    name = ""
    cleaned_subject = re.sub(r'^[^\x00-\x7F\s]+\s*', '', subject).strip()
    cleaned_subject = re.sub(
        r'^(?:Principal|Agent|Broker|Associate|Director|Manager|VP|CEO|CFO|President|Owner|Partner)\s+',
        '', cleaned_subject, flags=re.IGNORECASE
    ).strip()
    m = re.match(
        r"([A-Z][a-zA-Z'\-]+(?:\s+[A-Z][a-zA-Z'\-]+){1,3})\s+(?:has\s+)?(?:opened|Executed|requesting|downloaded|favorited|clicked|is\s+requesting)",
        cleaned_subject
    )
    if m:
        name = m.group(1).strip()
```

**Step 4: Commit**

```bash
git add windmill/f/switchboard/gmail_pubsub_webhook.py tests/test_parse_name_field.py
git commit -m "fix: handle Crexi subject emojis and title prefixes

Strip leading non-ASCII characters (✅) and role titles (Principal,
Broker, Agent, etc.) before name regex matching."
```

---

### Task 5: Push to Windmill and verify

**Step 1: Push changes to Windmill**

```bash
cd /Users/jacobphillips/rrg-server/windmill
wmill sync push --skip-variables --skip-secrets --skip-resources
```

**Step 2: Verify in Windmill UI**

Open `https://rrg-server.tailc01f9b.ts.net:8443` and check:
- `f/switchboard/gmail_pubsub_webhook` script updated
- `f/switchboard/lead_intake` flow's module D script updated (if SSA data was inlined)

**Step 3: Final commit with any adjustments**

```bash
git add -A
git commit -m "chore: windmill sync after parser fixes"
```
