# Realtor.com Dedicated Parser Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the broken generic parsing of Realtor.com leads with a dedicated parser that correctly extracts name, email, phone, and property address.

**Architecture:** New `parse_realtor_com_lead()` function in `gmail_pubsub_webhook.py`, routed from `parse_lead_from_notification()` alongside Crexi, Social Connect, and UpNest. Dead `realtor_com` branches in the generic path are cleaned up.

**Tech Stack:** Python 3.12, regex, Gmail API (message fetch)

**Design doc:** `docs/plans/2026-02-28-realtor-com-parser-design.md`

---

### Task 1: Write and test the dedicated parser

**Files:**
- Modify: `windmill/f/switchboard/gmail_pubsub_webhook.py:692` (insert after `parse_upnest_lead`, before `parse_lead_from_notification`)

**Step 1: Write the test**

Create a standalone test script that exercises the parsing logic against the real email body format. No Gmail API dependency — extract the body-parsing logic.

```bash
cat > /tmp/test_realtor_parser.py << 'PYEOF'
import re

EXCLUDED_EMAIL_ADDRESSES = {
    'support@crexi.com', 'noreply@crexi.com',
    'teamgotcher@gmail.com',
}

def parse_realtor_com_lead_body(body, subject, msg_id="test_msg"):
    """Extracted parsing logic (no Gmail API dependency)."""
    first_name = ""
    last_name = ""
    email = ""
    phone = ""
    property_address = ""

    m = re.search(r'First Name:\s*(.+)', body)
    if m:
        first_name = m.group(1).strip()

    m = re.search(r'Last Name:\s*(.+)', body)
    if m:
        last_name = m.group(1).strip()

    name = (first_name + " " + last_name).strip()

    m = re.search(r'Email Address:\s*([a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,})', body)
    if m:
        candidate = m.group(1).strip()
        if candidate.lower() not in EXCLUDED_EMAIL_ADDRESSES:
            email = candidate

    m = re.search(r'Phone Number:\s*([\d\-\(\)\+\s\.]+)', body)
    if m:
        phone = m.group(1).strip()

    # Multi-line property address: collect lines after "Property Address:" until MLSID or blank
    lines = body.split('\n')
    in_address = False
    addr_lines = []
    for line in lines:
        stripped = line.strip()
        if stripped.lower().startswith('property address'):
            in_address = True
            continue
        if in_address:
            if not stripped or stripped.upper().startswith('MLSID'):
                break
            addr_lines.append(stripped)
    if addr_lines:
        property_address = ", ".join(addr_lines)

    if not email and not name:
        return None

    return {
        "name": name,
        "email": email,
        "phone": phone,
        "source": "Realtor.com",
        "source_type": "realtor_com",
        "lead_type": "buyer",
        "property_name": property_address,
        "property_address": property_address,
        "notification_message_id": msg_id
    }

# === TESTS ===

passed = 0
failed = 0

def test(label, actual, expected):
    global passed, failed
    if actual == expected:
        print(f"  PASS: {label}")
        passed += 1
    else:
        print(f"  FAIL: {label}")
        print(f"    Expected: {expected}")
        print(f"    Got:      {actual}")
        failed += 1

print("=== Test 1: Rebecca Sutton (real email body) ===")
body1 = """First Name: Rebecca
Last Name: Sutton
Email Address: kpfarms@yahoo.com
Phone Number: 517-881-7829

Comment:
I would like to request a private tour of 15 Pinewood Dr, Grass Lake, MI 49240.

This consumer inquired about:

Property Address:
15 Pinewood Dr
Grass Lake, MI 49240
MLSID # 26003866"""

r1 = parse_realtor_com_lead_body(body1, "New realtor.com lead - Rebecca Sutton", "19ca20243e08730f")
test("name", r1["name"], "Rebecca Sutton")
test("email", r1["email"], "kpfarms@yahoo.com")
test("phone", r1["phone"], "517-881-7829")
test("property_name", r1["property_name"], "15 Pinewood Dr, Grass Lake, MI 49240")
test("property_address", r1["property_address"], "15 Pinewood Dr, Grass Lake, MI 49240")
test("source", r1["source"], "Realtor.com")
test("source_type", r1["source_type"], "realtor_com")
test("lead_type", r1["lead_type"], "buyer")
test("notification_message_id", r1["notification_message_id"], "19ca20243e08730f")

print()
print("=== Test 2: Missing phone ===")
body2 = """First Name: John
Last Name: Doe
Email Address: john@example.com
Phone Number:

Property Address:
100 Main St
Ann Arbor, MI 48103
MLSID # 12345"""

r2 = parse_realtor_com_lead_body(body2, "New realtor.com lead - John Doe")
test("name", r2["name"], "John Doe")
test("email", r2["email"], "john@example.com")
test("phone", r2["phone"], "")
test("property_address", r2["property_address"], "100 Main St, Ann Arbor, MI 48103")

print()
print("=== Test 3: No email AND no name returns None ===")
body3 = """Comment:
Some comment here

Property Address:
123 Oak St
City, MI 48000
MLSID # 99999"""

r3 = parse_realtor_com_lead_body(body3, "New realtor.com lead - ")
test("returns None", r3, None)

print()
print("=== Test 4: Subject name not used as property ===")
test("property is address not name", r1["property_name"] != "Rebecca Sutton", True)

print()
print(f"{'='*50}")
print(f"Results: {passed} passed, {failed} failed")
PYEOF
python3 /tmp/test_realtor_parser.py
```

Expected: All tests PASS.

**Step 2: Add the function to `gmail_pubsub_webhook.py`**

Insert after line 691 (end of `parse_upnest_lead`), before `parse_lead_from_notification`:

```python
def parse_realtor_com_lead(service, msg_id, sender, subject):
    """Parse lead data from a Realtor.com notification email.

    Format (labeled fields):
      First Name: [first]
      Last Name: [last]
      Email Address: [email]
      Phone Number: [phone]

      Property Address:
      [street]
      [city, state zip]
      MLSID # [id]
    """
    msg = service.users().messages().get(userId='me', id=msg_id, format='full').execute()
    body = get_body_from_payload(msg.get('payload', {}))

    first_name = ""
    last_name = ""
    email = ""
    phone = ""
    property_address = ""

    m = re.search(r'First Name:\s*(.+)', body)
    if m:
        first_name = m.group(1).strip()

    m = re.search(r'Last Name:\s*(.+)', body)
    if m:
        last_name = m.group(1).strip()

    name = (first_name + " " + last_name).strip()

    m = re.search(r'Email Address:\s*([a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,})', body)
    if m:
        candidate = m.group(1).strip()
        if candidate.lower() not in EXCLUDED_EMAIL_ADDRESSES:
            email = candidate

    m = re.search(r'Phone Number:\s*([\d\-\(\)\+\s\.]+)', body)
    if m:
        phone = m.group(1).strip()

    # Multi-line property address: collect lines after "Property Address:" until MLSID or blank
    lines = body.split('\n')
    in_address = False
    addr_lines = []
    for line in lines:
        stripped = line.strip()
        if stripped.lower().startswith('property address'):
            in_address = True
            continue
        if in_address:
            if not stripped or stripped.upper().startswith('MLSID'):
                break
            addr_lines.append(stripped)
    if addr_lines:
        property_address = ", ".join(addr_lines)

    if not email and not name:
        return None

    result = {
        "name": name,
        "email": email,
        "phone": phone,
        "source": "Realtor.com",
        "source_type": "realtor_com",
        "lead_type": "buyer",
        "property_name": property_address,
        "property_address": property_address,
        "notification_message_id": msg_id
    }
    return result
```

**Step 3: Commit**

```bash
git add windmill/f/switchboard/gmail_pubsub_webhook.py
git commit -m "feat: add dedicated Realtor.com parser

Extracts First Name + Last Name, Email Address, Phone Number,
and multi-line Property Address from body instead of subject."
```

---

### Task 2: Route Realtor.com to dedicated parser and clean up dead code

**Files:**
- Modify: `windmill/f/switchboard/gmail_pubsub_webhook.py:769-813`

**Step 1: Add routing**

At line 775 (after the `upnest` route), add:

```python
    if category == "realtor_com":
        return parse_realtor_com_lead(service, msg_id, sender, subject)
```

**Step 2: Remove dead `realtor_com` branch from `parse_property_name`**

At lines 523-527, remove:

```python
    elif category == "realtor_com":
        # "New realtor.com lead: 123 Main St"
        m = re.search(r'new realtor\.com lead[:\-\s]+(.+?)(?:\s*$)', subject, re.IGNORECASE)
        if m:
            return m.group(1).strip()
```

**Step 3: Remove dead `realtor_com` branches from `parse_lead_from_notification`**

Remove lines 784-786:
```python
    elif category == "realtor_com":
        source = "Realtor.com"
        source_type = "realtor_com"
```

Remove lines 809-813:
```python
    elif category == "realtor_com":
        # Realtor.com: property_name from subject is already an address
        # e.g. "New realtor.com lead: 123 Main St, City, MI 48103"
        if property_name:
            property_address = property_name
```

**Step 4: Update stale comments**

Line 777: Change `(Realtor.com, Seller Hub, BizBuySell, LoopNet)` to `(Seller Hub, BizBuySell, LoopNet)`.

Lines 801-802: Change `(Seller Hub body, Realtor.com subject)` to `(Seller Hub body)`.

**Step 5: Run the test again to confirm nothing broke**

```bash
python3 /tmp/test_realtor_parser.py
```

Expected: All tests PASS.

**Step 6: Commit**

```bash
git add windmill/f/switchboard/gmail_pubsub_webhook.py
git commit -m "refactor: route Realtor.com to dedicated parser, remove dead generic branches"
```

---

### Task 3: Test against real email from leads@

**Files:** None (read-only verification)

**Step 1: Run the parser against the actual Rebecca Sutton email on rrg-server**

Write a script that fetches msg_id `19ca20243e08730f` from leads@ via Gmail API, runs the body through the parser, and prints all fields.

Expected output:
```
name: Rebecca Sutton
email: kpfarms@yahoo.com
phone: 517-881-7829
property_name: 15 Pinewood Dr, Grass Lake, MI 49240
property_address: 15 Pinewood Dr, Grass Lake, MI 49240
source: Realtor.com
source_type: realtor_com
lead_type: buyer
notification_message_id: 19ca20243e08730f
```

---

### Task 4: Update docs

**Files:**
- Modify: `docs/LEAD_INTAKE_PIPELINE.md:109,117`

**Step 1: Update parser table**

Line 109, change:
```
| Realtor.com | — | Starts with "New realtor.com lead" | "Realtor.com" | Yes — generic parser (labeled: `First Name:`, `Email Address:`, `Phone Number:`) |
```
To:
```
| Realtor.com | — | Starts with "New realtor.com lead" | "Realtor.com" | Yes — dedicated parser (`First Name:` + `Last Name:`, `Email Address:`, `Phone Number:`, multi-line `Property Address:`) |
```

**Step 2: Update parser architecture description**

Line 117, change:
```
- **Dedicated parsers** (`parse_crexi_lead`, `parse_social_connect_lead`): Handle non-standard formats that don't use label prefixes
```
To:
```
- **Dedicated parsers** (`parse_crexi_lead`, `parse_social_connect_lead`, `parse_realtor_com_lead`): Handle non-standard formats that don't use label prefixes
```

**Step 3: Update last-updated footer**

**Step 4: Commit**

```bash
git add docs/LEAD_INTAKE_PIPELINE.md
git commit -m "docs: update parser table for Realtor.com dedicated parser"
```

---

### Task 5: Push to rrg-server and Windmill

**Step 1: Push to GitHub**

```bash
git push origin main
```

**Step 2: Pull on rrg-server**

```bash
ssh andrea@rrg-server "cd ~/rrg-server && git pull"
```

**Step 3: Push to Windmill**

```bash
ssh andrea@rrg-server "export PATH=/nix/var/nix/profiles/default/bin:\$PATH && nix-shell -p nodejs --run 'cd ~/rrg-server/windmill && /home/andrea/.npm/_npx/613db052ef48345b/node_modules/.bin/wmill sync push --skip-variables --skip-secrets --skip-resources --base-url http://localhost:8000 --token TOKEN --workspace rrg --yes'"
```

Expected: 1 change pushed (gmail_pubsub_webhook script).

---

### Task 6: Reprocess Rebecca Sutton lead

**Step 1: Fire lead_intake flow with correct lead data**

Use the Windmill API to fire `f/switchboard/lead_intake` with the correctly parsed lead data from the Rebecca Sutton email.

**Step 2: Verify flow completes through Module E**

Check that all modules A-E succeed and the flow is WaitingForEvents with a draft in teamgotcher@gmail.com.

**Step 3: Verify draft content**

Confirm the draft subject is `"RE: Your Realtor.com inquiry in 15 Pinewood Dr, Grass Lake, MI 49240"` and the body references the property address, not the person's name.
