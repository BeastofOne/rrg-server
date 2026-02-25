# Lead Conversation Flow — Endpoint Fix + E2E Test

> **Date:** 2026-02-25
> **Flow:** `f/switchboard/lead_conversation`
> **Status:** Design approved

## Problem

The `lead_conversation` flow has never run end-to-end successfully. Two issues:

1. **Deprecated Claude endpoint:** Modules A and B call `f/switchboard/claude_endpoint_url` (the old jake-macbook HTTP proxy at `:8787`). This endpoint no longer exists — Claude CLI now runs inside the Windmill worker container via the teamgotcher account.
2. **Never tested E2E:** The flow was attempted once (2026-02-24) and failed due to the endpoint issue, which led to a larger infrastructure fix (Nix-built Docker image with Claude CLI, account switch to teamgotcher).

## Part 1: Claude CLI Migration (Modules A & B)

### What Changes

**Module A** (`fetch_thread_+_classify_reply.inline_script.py`):
- Replace `requests.post(endpoint_url, json={"prompt": ..., "model": "haiku"}, ...)` with `subprocess.run(["claude", "-p", prompt, "--model", "haiku", "--no-chrome", "--allowedTools", ""], ...)`
- Remove `wmill.get_variable("f/switchboard/claude_endpoint_url")`
- Remove `import requests` (only used for Claude calls in this module)

**Module B** (`generate_response_draft.inline_script.py`):
- Same subprocess replacement in `generate_response_with_claude()`
- Remove `wmill.get_variable("f/switchboard/claude_endpoint_url")`
- Keep `import requests` (still needed for WiseAgent CRM calls)

**Modules C and D:** No changes — they don't call Claude.

### Subprocess Pattern

Match the existing `claude_llm.py` pattern used by rrg-pnl/brochure:

```python
import subprocess

result = subprocess.run(
    ["claude", "-p", prompt, "--model", "haiku", "--no-chrome", "--allowedTools", ""],
    capture_output=True,
    text=True,
    timeout=90,
)

if result.returncode != 0:
    # handle error
    ...

response_text = result.stdout.strip()
```

### Verified Infrastructure

- `claude` at `/usr/local/bin/claude` in windmill worker (v2.1.50)
- `CLAUDE_CODE_OAUTH_TOKEN` set (teamgotcher account)
- `CLAUDE_MODEL=haiku` set via env
- `subprocess.run` from Python confirmed working inside the container

## Part 2: End-to-End Testing

### Phase 1 — Manual API Trigger

1. Query `jake_signals` for an `acted` signal from yesterday's testing to get valid thread_id + lead context
2. Call `lead_conversation` flow via Windmill API with that data + a test reply_body
3. Verify each module: classification (A), draft creation (B), signal write + suspend (C)
4. Troubleshoot failures as they arise

### Phase 2 — Live Webhook Trigger

1. Jake replies to one of yesterday's test outreach emails
2. Pub/Sub fires -> webhook detects reply -> `find_outreach_by_thread` matches -> `trigger_lead_conversation` fires
3. Verify full pipeline from natural trigger
4. Approve or delete the resulting draft to test Module D (CRM note + SMS)

## Files to Modify

| File | Change |
|------|--------|
| `windmill/f/switchboard/lead_conversation.flow/fetch_thread_+_classify_reply.inline_script.py` | Replace HTTP endpoint with subprocess |
| `windmill/f/switchboard/lead_conversation.flow/generate_response_draft.inline_script.py` | Replace HTTP endpoint with subprocess |

## Out of Scope

- Automated follow-up scheduling (day 3/7/14)
- Property document population (all `documents` fields still null)
- Changes to Modules C or D
- Changes to the webhook trigger logic
