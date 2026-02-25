# Lead Conversation E2E — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix the deprecated Claude endpoint in the lead_conversation flow and test the full pipeline end-to-end.

**Architecture:** Replace HTTP POST calls to the dead `claude_endpoint_url` with `subprocess.run(["claude", "-p", ...])` in Modules A and B. Claude CLI is already installed in the Windmill worker container at `/usr/local/bin/claude` with teamgotcher OAuth. Then test via manual API trigger followed by live webhook trigger.

**Tech Stack:** Python (Windmill inline scripts), subprocess, Claude CLI, Gmail API, Postgres (jake_signals)

---

### Task 1: Update Module A — Replace HTTP endpoint with subprocess

**Files:**
- Modify: `windmill/f/switchboard/lead_conversation.flow/fetch_thread_+_classify_reply.inline_script.py`

**Step 1: Edit the `#extra_requirements` block**

Remove `requests` since Module A only used it for Claude calls.

Change:
```python
#extra_requirements:
#google-api-python-client
#google-auth
#requests
```

To:
```python
#extra_requirements:
#google-api-python-client
#google-auth
```

**Step 2: Add `import subprocess` at the top**

Add `import subprocess` to the imports (line ~7 area, after `import re`).

Remove the `import requests` from inside `classify_with_claude()` (line 95).

**Step 3: Replace the Claude call in `classify_with_claude()`**

Replace lines 146-171 (the `endpoint_url` fetch through the `except` block) with:

```python
    try:
        result = subprocess.run(
            ["claude", "-p", prompt, "--model", "haiku", "--no-chrome", "--allowedTools", ""],
            capture_output=True,
            text=True,
            timeout=90,
        )

        if result.returncode != 0:
            error_msg = result.stderr.strip() or f"Claude CLI exited with code {result.returncode}"
            raise RuntimeError(error_msg)

        result_text = result.stdout.strip()

        # Parse JSON from response (handle potential markdown wrapping)
        clean = result_text
        if clean.startswith("```"):
            clean = re.sub(r'^```(?:json)?\s*', '', clean)
            clean = re.sub(r'\s*```$', '', clean)

        return json.loads(clean)
    except Exception as e:
        return {
            "classification": "ERROR",
            "sub_classification": None,
            "wants": None,
            "confidence": 0.0,
            "reasoning": f"Classification failed: {str(e)}"
        }
```

**Step 4: Commit**

```bash
git add windmill/f/switchboard/lead_conversation.flow/fetch_thread_+_classify_reply.inline_script.py
git commit -m "fix(lead_conversation): replace deprecated HTTP endpoint with subprocess in Module A"
```

---

### Task 2: Update Module B — Replace HTTP endpoint with subprocess

**Files:**
- Modify: `windmill/f/switchboard/lead_conversation.flow/generate_response_draft.inline_script.py`

**Step 1: Add `import subprocess` to the top-level imports**

Add `import subprocess` after `import re` (line ~16 area). Keep `import requests` since Module B still uses it for WiseAgent CRM calls.

**Step 2: Replace the Claude call in `generate_response_with_claude()`**

Replace lines 249-266 (the `endpoint_url` fetch through the `except` block) with:

```python
    try:
        result = subprocess.run(
            ["claude", "-p", prompt, "--model", "haiku", "--no-chrome", "--allowedTools", ""],
            capture_output=True,
            text=True,
            timeout=90,
        )

        if result.returncode != 0:
            error_msg = result.stderr.strip() or f"Claude CLI exited with code {result.returncode}"
            raise RuntimeError(error_msg)

        body = result.stdout.strip()
        # Remove any markdown fences Claude might add
        if body.startswith("```"):
            body = re.sub(r'^```\w*\s*', '', body)
            body = re.sub(r'\s*```$', '', body)
        return body
    except Exception as e:
        # Fallback to simple template
        return f"Hey {first_name},\n\nThanks for getting back to me! I'd love to help. My direct line is {phone} — feel free to call anytime.\n\n{signoff}"
```

**Step 3: Commit**

```bash
git add windmill/f/switchboard/lead_conversation.flow/generate_response_draft.inline_script.py
git commit -m "fix(lead_conversation): replace deprecated HTTP endpoint with subprocess in Module B"
```

---

### Task 3: Deploy changes to Windmill

**Step 1: Push to GitHub**

```bash
git push origin main
```

**Step 2: Pull on rrg-server and push to Windmill DB**

```bash
ssh andrea@rrg-server
cd ~/rrg-server && git pull
cd windmill
nix-shell -p nodejs_22 --run "npx windmill-cli@latest sync push \
  --base-url http://localhost:8000 \
  --workspace rrg \
  --token $WINDMILL_TOKEN \
  --skip-variables --skip-secrets --skip-resources \
  --yes"
```

Expected: Windmill CLI reports the two updated inline scripts in the lead_conversation flow.

**Step 3: Verify in Windmill UI**

Open `https://rrg-server.tailc01f9b.ts.net:8443` and navigate to `f/switchboard/lead_conversation` flow. Confirm Module A and Module B scripts show `subprocess.run` instead of `requests.post`.

---

### Task 4: Phase 1 — Manual API trigger test

**Step 1: Build test payload from existing signal data**

Use signal #58 (acted lead_intake for Jacob Phillips / 0 Brown Dr in Chelsea, thread_id `19c9041dc7e9ff91`):

```json
{
  "thread_id": "19c9041dc7e9ff91",
  "message_id": "test_manual_001",
  "reply_body": "Hey Larry, sounds interesting. Can you send me the OM? Thanks, Jacob",
  "reply_subject": "RE: Your Interest in 0 Brown Dr in Chelsea",
  "reply_from": "jake.phillips@resourcerealty.com",
  "lead_email": "jake.phillips@resourcerealty.com",
  "lead_name": "Jacob Phillips",
  "lead_phone": "(734) 896-0518",
  "source": "Crexi",
  "source_type": "crexi_om",
  "wiseagent_client_id": 118730472,
  "has_nda": false,
  "properties": [
    {
      "canonical_name": "0 Brown Dr in Chelsea",
      "property_address": "",
      "asking_price": "",
      "lead_magnet": false
    }
  ],
  "signal_id": 58,
  "template_used": "commercial_first_outreach_template"
}
```

**Step 2: Trigger the flow via Windmill API**

```bash
ssh andrea@rrg-server
curl -s -X POST \
  "http://localhost:8000/api/w/rrg/jobs/run/f/f/switchboard/lead_conversation" \
  -H "Authorization: Bearer $WINDMILL_TOKEN" \
  -H "Content-Type: application/json" \
  -d '<payload from step 1>'
```

Expected: Returns a job UUID.

**Step 3: Monitor job execution**

Check the Windmill UI or use:

```bash
curl -s "http://localhost:8000/api/w/rrg/jobs_u/get/<job_uuid>" \
  -H "Authorization: Bearer $WINDMILL_TOKEN" | python3 -m json.tool
```

**Expected results per module:**
- **Module A:** Classification result — should return `INTERESTED` / `WANT_SOMETHING` / `wants: ["om"]` for the test reply body
- **Module B:** Gmail draft created in teamgotcher@gmail.com, `skipped: false`
- **Module C:** Signal written to jake_signals (status: pending), flow suspended
- **Module D:** Not yet — flow is suspended waiting for approval

**Step 4: Troubleshoot any failures**

If a module fails, check the Windmill job logs in the UI. Common issues:
- subprocess not found → check claude CLI path in worker
- OAuth expired → check gmail_oauth resource token freshness
- Timeout → Claude CLI taking too long (increase timeout)

---

### Task 5: Phase 1 — Complete the suspended flow

**Step 1: Verify the draft and signal exist**

Check jake_signals for the new pending signal:

```bash
ssh andrea@rrg-server "docker exec windmill-db-1 psql -U postgres -d windmill -t -c \
  \"SELECT id, summary, status FROM public.jake_signals WHERE source_flow = 'lead_conversation' AND status = 'pending' ORDER BY created_at DESC LIMIT 3;\""
```

Check Gmail for the draft in teamgotcher@gmail.com.

**Step 2: Approve by sending the draft (or delete to reject)**

Jake sends or deletes the draft in Gmail. Sending triggers:
1. Pub/Sub push → webhook → SENT detection → resume URL hit → Module D runs

**Step 3: Verify Module D execution**

- CRM note written to WiseAgent for client 118730472
- SMS sent (if phone was available and classification was INTERESTED)
- Signal marked as `acted`

---

### Task 6: Phase 2 — Live webhook trigger test

**Step 1: Jake replies to a test outreach email**

Reply to one of the test emails from yesterday from jake.phillips@resourcerealty.com. Use a clear reply like "Can you send me the OM?" to get a predictable classification.

**Step 2: Watch the webhook fire**

Monitor Windmill for a new `lead_conversation` job triggered by the webhook. The webhook should:
1. Detect the reply as "Unlabeled" in teamgotcher@ INBOX
2. Match thread_id to an acted signal via `find_outreach_by_thread`
3. Apply "Lead Reply" label
4. Trigger `lead_conversation` flow

**Step 3: Verify full pipeline**

Same verification as Task 4 — classification, draft creation, signal, suspend. Then approve/delete draft to test Module D.

**Step 4: Confirm SMS delivery**

If the lead has a phone number and classification is INTERESTED, verify the SMS was sent through the Pixel gateway (100.125.176.16:8686).

---

### Task 7: Update docs and commit

**Files:**
- Modify: `docs/LEAD_CONVERSATION_ENGINE.md`

**Step 1: Update the Claude endpoint reference**

In the Module A section, change the "Claude endpoint" description from:
> Uses `f/switchboard/claude_endpoint_url` (jake-macbook proxy at `http://100.108.74.112:8787`)

To:
> Uses `subprocess.run(["claude", "-p", ...])` calling the Claude CLI installed in the Windmill worker container (`/usr/local/bin/claude`, teamgotcher account).

Remove `f/switchboard/claude_endpoint_url` from the "Windmill Resources and Variables" section.

**Step 2: Commit**

```bash
git add docs/LEAD_CONVERSATION_ENGINE.md
git commit -m "docs: update lead conversation engine for subprocess Claude CLI"
```
