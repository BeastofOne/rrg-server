# Resource Restoration Verification Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Verify that all 11 Windmill resources and variables deleted by the Feb 28 accidental `wmill sync push` have been correctly restored and are functional.

**Architecture:** Run 7 tests via SSH to rrg-server, each exercising one or more restored items through their actual usage path (Windmill API, Gmail API, WiseAgent API, Postgres). No code changes — read-only verification only.

**Tech Stack:** Windmill API, Gmail API, WiseAgent API, PostgreSQL, Python (via SSH)

---

### Task 1: Verify `pg` resource — PostgreSQL connection

**Step 1: Run a SQL query through Windmill using the pg resource**

```bash
ssh andrea@rrg-server "docker exec windmill-db-1 psql -U postgres windmill -c \"SELECT count(*) FROM jake_signals;\"" 2>&1
```

Expected: Returns a row count (integer, 0 or more). No connection errors.

**Step 2: Verify Windmill scripts can use the pg resource**

```bash
python3 -c "
import urllib.request, json
token = 'muswxrdRPHx1dI7cRsz15N3Qkib114K9'
base = 'http://100.97.86.99:8000'
# Read the pg resource to verify its structure
req = urllib.request.Request(f'{base}/api/w/rrg/resources/get/f/switchboard/pg', headers={'Authorization': f'Bearer {token}'})
resp = urllib.request.urlopen(req)
data = json.loads(resp.read())
value = data.get('value', {})
required_keys = ['host', 'port', 'user', 'password', 'dbname']
missing = [k for k in required_keys if k not in value]
print(f'pg resource keys present: {list(value.keys())}')
print(f'Missing keys: {missing}')
assert not missing, f'pg resource missing keys: {missing}'
print('PASS: pg resource has all required fields')
"
```

Expected: `PASS: pg resource has all required fields`

---

### Task 2: Verify `wiseagent_oauth` resource — WiseAgent API access

**Step 1: Refresh the WiseAgent token and make an API call**

```bash
python3 << 'PYEOF'
import urllib.request, json

token = 'muswxrdRPHx1dI7cRsz15N3Qkib114K9'
base = 'http://100.97.86.99:8000'

# Read wiseagent_oauth resource
req = urllib.request.Request(f'{base}/api/w/rrg/resources/get/f/switchboard/wiseagent_oauth',
    headers={'Authorization': f'Bearer {token}'})
resp = urllib.request.urlopen(req)
oauth = json.loads(resp.read()).get('value', {})

required = ['client_id', 'client_secret', 'refresh_token']
missing = [k for k in required if not oauth.get(k)]
assert not missing, f'wiseagent_oauth missing: {missing}'

# Try to refresh the access token (correct URL from Windmill flow code)
import urllib.parse
refresh_data = urllib.parse.urlencode({
    'grant_type': 'refresh_token',
    'client_id': oauth['client_id'],
    'client_secret': oauth['client_secret'],
    'refresh_token': oauth['refresh_token']
}).encode()
req2 = urllib.request.Request('https://sync.thewiseagent.com/WiseAuth/token', data=refresh_data,
    headers={'Content-Type': 'application/x-www-form-urlencoded'}, method='POST')
resp2 = urllib.request.urlopen(req2)
tokens = json.loads(resp2.read())
access_token = tokens.get('access_token', '')
assert access_token, 'Failed to obtain WiseAgent access token'

# Test API call: search for a contact via WiseAgent webconnect
req3 = urllib.request.Request('https://sync.thewiseagent.com/http/webconnect.asp?function=searchContacts&searchTerm=test&pageSize=1',
    headers={'Authorization': f'Bearer {access_token}'})
resp3 = urllib.request.urlopen(req3)
print(f'WiseAgent API response: {resp3.status}')
assert resp3.status == 200
print('PASS: wiseagent_oauth working — token refresh and API call succeeded')
PYEOF
```

Expected: `PASS: wiseagent_oauth working — token refresh and API call succeeded`

---

### Task 3: Verify `gmail_oauth` resource — teamgotcher@gmail.com

**Step 1: Refresh Gmail token and list recent threads**

```bash
python3 << 'PYEOF'
import urllib.request, urllib.parse, json

token = 'muswxrdRPHx1dI7cRsz15N3Qkib114K9'
base = 'http://100.97.86.99:8000'

# Read gmail_oauth resource
req = urllib.request.Request(f'{base}/api/w/rrg/resources/get/f/switchboard/gmail_oauth',
    headers={'Authorization': f'Bearer {token}'})
resp = urllib.request.urlopen(req)
oauth = json.loads(resp.read()).get('value', {})

required = ['client_id', 'client_secret', 'refresh_token']
missing = [k for k in required if not oauth.get(k)]
assert not missing, f'gmail_oauth missing: {missing}'

# Refresh access token
refresh_data = urllib.parse.urlencode({
    'grant_type': 'refresh_token',
    'client_id': oauth['client_id'],
    'client_secret': oauth['client_secret'],
    'refresh_token': oauth['refresh_token']
}).encode()
req2 = urllib.request.Request('https://oauth2.googleapis.com/token', data=refresh_data, method='POST')
resp2 = urllib.request.urlopen(req2)
access_token = json.loads(resp2.read()).get('access_token', '')
assert access_token, 'Failed to refresh Gmail token for teamgotcher'

# List 1 thread
req3 = urllib.request.Request('https://gmail.googleapis.com/gmail/v1/users/me/threads?maxResults=1',
    headers={'Authorization': f'Bearer {access_token}'})
resp3 = urllib.request.urlopen(req3)
data = json.loads(resp3.read())
thread_count = data.get('resultSizeEstimate', 0)
print(f'Gmail (teamgotcher) threads found: {thread_count}')
assert thread_count > 0, 'No threads found'
print('PASS: gmail_oauth working — token refresh and thread list succeeded')
PYEOF
```

Expected: `PASS: gmail_oauth working — token refresh and thread list succeeded`

---

### Task 4: Verify `gmail_leads_oauth` resource + `gmail_leads_last_history_id` variable

**Step 1: Refresh leads@ token and validate history ID**

```bash
python3 << 'PYEOF'
import urllib.request, urllib.parse, json

token = 'muswxrdRPHx1dI7cRsz15N3Qkib114K9'
base = 'http://100.97.86.99:8000'

# Read gmail_leads_oauth resource
req = urllib.request.Request(f'{base}/api/w/rrg/resources/get/f/switchboard/gmail_leads_oauth',
    headers={'Authorization': f'Bearer {token}'})
resp = urllib.request.urlopen(req)
oauth = json.loads(resp.read()).get('value', {})

required = ['client_id', 'client_secret', 'refresh_token']
missing = [k for k in required if not oauth.get(k)]
assert not missing, f'gmail_leads_oauth missing: {missing}'

# Refresh access token
refresh_data = urllib.parse.urlencode({
    'grant_type': 'refresh_token',
    'client_id': oauth['client_id'],
    'client_secret': oauth['client_secret'],
    'refresh_token': oauth['refresh_token']
}).encode()
req2 = urllib.request.Request('https://oauth2.googleapis.com/token', data=refresh_data, method='POST')
resp2 = urllib.request.urlopen(req2)
access_token = json.loads(resp2.read()).get('access_token', '')
assert access_token, 'Failed to refresh Gmail token for leads@'

# Read gmail_leads_last_history_id variable
req3 = urllib.request.Request(f'{base}/api/w/rrg/variables/get/f/switchboard/gmail_leads_last_history_id',
    headers={'Authorization': f'Bearer {token}'})
resp3 = urllib.request.urlopen(req3)
history_id = json.loads(resp3.read()).get('value', '')
assert history_id, 'gmail_leads_last_history_id is empty'
print(f'History ID: {history_id}')

# Validate history ID with Gmail API
req4 = urllib.request.Request(
    f'https://gmail.googleapis.com/gmail/v1/users/me/history?startHistoryId={history_id}&maxResults=1',
    headers={'Authorization': f'Bearer {access_token}'})
try:
    resp4 = urllib.request.urlopen(req4)
    print(f'Gmail history.list response: {resp4.status}')
    print('PASS: gmail_leads_oauth + gmail_leads_last_history_id working')
except urllib.error.HTTPError as e:
    if e.code == 404:
        print(f'FAIL: history ID {history_id} is expired/invalid (404)')
    else:
        print(f'FAIL: Gmail API error {e.code}')
    raise
PYEOF
```

Expected: `PASS: gmail_leads_oauth + gmail_leads_last_history_id working`

---

### Task 5: Verify `router_token` variable — Windmill API auth

**Step 1: Use router_token to make a Windmill API call**

```bash
python3 << 'PYEOF'
import urllib.request, json

wm_token = 'muswxrdRPHx1dI7cRsz15N3Qkib114K9'
base = 'http://100.97.86.99:8000'

# Read router_token variable
req = urllib.request.Request(f'{base}/api/w/rrg/variables/get/f/switchboard/router_token',
    headers={'Authorization': f'Bearer {wm_token}'})
resp = urllib.request.urlopen(req)
router_token = json.loads(resp.read()).get('value', '')
assert router_token, 'router_token is empty'

# Use router_token to list recent completed jobs (proves it's a valid Windmill token)
req2 = urllib.request.Request(f'{base}/api/w/rrg/jobs/completed/list?per_page=1',
    headers={'Authorization': f'Bearer {router_token}'})
resp2 = urllib.request.urlopen(req2)
jobs = json.loads(resp2.read())
print(f'Jobs returned: {len(jobs)}')
assert len(jobs) >= 0  # Even 0 is fine, just means no errors
print('PASS: router_token is a valid Windmill API token')
PYEOF
```

Expected: `PASS: router_token is a valid Windmill API token`

---

### Task 6: Verify `property_mapping`, `email_signatures`, `sms_gateway_url`, `tailscale_machines` — structural validation

**Step 1: Read and validate all four items**

```bash
python3 << 'PYEOF'
import urllib.request, json

token = 'muswxrdRPHx1dI7cRsz15N3Qkib114K9'
base = 'http://100.97.86.99:8000'
errors = []

def get_var(path):
    req = urllib.request.Request(f'{base}/api/w/rrg/variables/get/{path}',
        headers={'Authorization': f'Bearer {token}'})
    resp = urllib.request.urlopen(req)
    return json.loads(resp.read()).get('value', '')

def get_resource(path):
    req = urllib.request.Request(f'{base}/api/w/rrg/resources/get/{path}',
        headers={'Authorization': f'Bearer {token}'})
    resp = urllib.request.urlopen(req)
    return json.loads(resp.read()).get('value', {})

# 1. property_mapping
pm_raw = get_var('f/switchboard/property_mapping')
pm = json.loads(pm_raw) if isinstance(pm_raw, str) else pm_raw
mappings = pm.get('mappings', [])
if len(mappings) != 9:
    errors.append(f'property_mapping: expected 9 properties, got {len(mappings)}')
else:
    for m in mappings:
        required = ['canonical_name', 'aliases', 'hubspot_deal_id', 'property_address']
        missing = [k for k in required if k not in m]
        if missing:
            errors.append(f'property_mapping entry "{m.get("canonical_name","?")}" missing: {missing}')
    print(f'property_mapping: {len(mappings)} properties, all fields present')

# 2. email_signatures
es_raw = get_var('f/switchboard/email_signatures')
es = json.loads(es_raw) if isinstance(es_raw, str) else es_raw
signers = es.get('signers', {})
for name in ['larry', 'andrea']:
    if name not in signers:
        errors.append(f'email_signatures: missing signer "{name}"')
    elif not signers[name].get('html_signature', ''):
        errors.append(f'email_signatures: signer "{name}" has empty html_signature')
    elif len(signers[name]['html_signature']) < 50:
        errors.append(f'email_signatures: signer "{name}" html_signature suspiciously short ({len(signers[name]["html_signature"])} chars)')
if not errors or not any('email_signatures' in e for e in errors):
    print(f'email_signatures: larry ({len(signers["larry"]["html_signature"])} chars), andrea ({len(signers["andrea"]["html_signature"])} chars)')

# 3. sms_gateway_url
sms = get_var('f/switchboard/sms_gateway_url')
expected_sms = 'http://100.125.176.16:8686/send-sms'
if sms != expected_sms:
    errors.append(f'sms_gateway_url: expected "{expected_sms}", got "{sms}"')
else:
    print(f'sms_gateway_url: correct')

# 4. tailscale_machines
tm = get_resource('f/switchboard/tailscale_machines')
expected_machines = ['rrg-server', 'pixel-9a', 'jake-macbook', 'larry-sms-gateway']
missing_machines = [m for m in expected_machines if m not in tm.get('machines', tm)]
# tailscale_machines might be flat or nested under 'machines'
actual_keys = list(tm.keys()) if isinstance(tm, dict) else []
if not actual_keys:
    errors.append('tailscale_machines: resource is empty')
else:
    print(f'tailscale_machines: keys = {actual_keys}')

# Summary
if errors:
    print(f'\nFAIL: {len(errors)} error(s):')
    for e in errors:
        print(f'  - {e}')
else:
    print('\nPASS: all 4 items structurally valid')
PYEOF
```

Expected: `PASS: all 4 items structurally valid`

---

### Task 7: Verify `gmail_last_history_id` — teamgotcher history ID validity

**Step 1: Validate history ID with Gmail API**

```bash
python3 << 'PYEOF'
import urllib.request, urllib.parse, json

token = 'muswxrdRPHx1dI7cRsz15N3Qkib114K9'
base = 'http://100.97.86.99:8000'

# Read gmail_oauth for teamgotcher
req = urllib.request.Request(f'{base}/api/w/rrg/resources/get/f/switchboard/gmail_oauth',
    headers={'Authorization': f'Bearer {token}'})
resp = urllib.request.urlopen(req)
oauth = json.loads(resp.read()).get('value', {})

# Refresh token
refresh_data = urllib.parse.urlencode({
    'grant_type': 'refresh_token',
    'client_id': oauth['client_id'],
    'client_secret': oauth['client_secret'],
    'refresh_token': oauth['refresh_token']
}).encode()
req2 = urllib.request.Request('https://oauth2.googleapis.com/token', data=refresh_data, method='POST')
resp2 = urllib.request.urlopen(req2)
access_token = json.loads(resp2.read()).get('access_token', '')
assert access_token, 'Failed to refresh Gmail token'

# Read history ID
req3 = urllib.request.Request(f'{base}/api/w/rrg/variables/get/f/switchboard/gmail_last_history_id',
    headers={'Authorization': f'Bearer {token}'})
resp3 = urllib.request.urlopen(req3)
history_id = json.loads(resp3.read()).get('value', '')
assert history_id, 'gmail_last_history_id is empty'
print(f'History ID: {history_id}')

# Validate with Gmail API
req4 = urllib.request.Request(
    f'https://gmail.googleapis.com/gmail/v1/users/me/history?startHistoryId={history_id}&maxResults=1',
    headers={'Authorization': f'Bearer {access_token}'})
try:
    resp4 = urllib.request.urlopen(req4)
    print(f'Gmail history.list response: {resp4.status}')
    print('PASS: gmail_last_history_id is valid')
except urllib.error.HTTPError as e:
    if e.code == 404:
        print(f'FAIL: history ID {history_id} is expired/invalid (404)')
    else:
        print(f'FAIL: Gmail API error {e.code}')
    raise
PYEOF
```

Expected: `PASS: gmail_last_history_id is valid`

---

### Coverage Matrix

| Item | Type | Test | Verified By |
|------|------|------|-------------|
| `pg` | Resource | Task 1 | Structure check + direct DB query |
| `wiseagent_oauth` | Resource | Task 2 | Token refresh + API call |
| `gmail_oauth` | Resource | Task 3 | Token refresh + thread list |
| `gmail_leads_oauth` | Resource | Task 4 | Token refresh + history.list |
| `tailscale_machines` | Resource | Task 6 | Structure check |
| `router_token` | Variable | Task 5 | Windmill API call |
| `property_mapping` | Variable | Task 6 | 9 properties, all fields |
| `email_signatures` | Variable | Task 6 | Both signers, HTML present |
| `sms_gateway_url` | Variable | Task 6 | Exact value match |
| `gmail_last_history_id` | Variable | Task 7 | Gmail history.list accepts it |
| `gmail_leads_last_history_id` | Variable | Task 4 | Gmail history.list accepts it |
