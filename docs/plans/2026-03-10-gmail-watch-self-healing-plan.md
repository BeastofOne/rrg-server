# Gmail Watch Self-Healing Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make the Gmail watch health check self-healing so expired watches auto-renew instead of requiring manual intervention.

**Architecture:** Modify `check_gmail_watch_health.py` to attempt watch renewal via Windmill's `run_wait_result` API before alerting Jake. Only alert on renewal failure (e.g., revoked OAuth token).

**Tech Stack:** Python, Windmill API, requests

---

### Task 1: Update health check script with self-healing logic

**Files:**
- Modify: `windmill/f/switchboard/check_gmail_watch_health.py`

**Step 1: Replace the full script with self-healing version**

Replace the contents of `windmill/f/switchboard/check_gmail_watch_health.py` with:

```python
# Gmail Watch Health Check (Self-Healing)
# Path: f/switchboard/check_gmail_watch_health
#
# Checks that gmail_pubsub_webhook has run recently (within 48 hours).
# If stale, ATTEMPTS to re-register both Gmail watches before alerting.
# Only alerts Jake if the self-heal fails (e.g., revoked OAuth token).
#
# Monitors BOTH accounts:
# - teamgotcher@gmail.com (SENT + INBOX watch)
# - leads@resourcerealtygroupmi.com (INBOX watch)
#
# Schedule: Daily at 10 AM ET

#extra_requirements:
#requests

import os
import wmill
import requests
from datetime import datetime, timezone

WM_API_BASE = os.environ.get('BASE_INTERNAL_URL', 'http://localhost:8000')

WATCH_SCRIPTS = [
    ("setup_gmail_watch", "teamgotcher@"),
    ("setup_gmail_leads_watch", "leads@"),
]


def main():
    token = wmill.get_variable("f/switchboard/router_token")
    sms_url = wmill.get_variable("f/switchboard/sms_gateway_url")

    try:
        hours_since, last_run = check_webhook_staleness(token)
    except Exception as e:
        try:
            send_alert(sms_url, f"Gmail health check failed: {str(e)[:100]}")
        except Exception:
            pass
        return {"status": "error", "error": str(e)}

    if hours_since is None:
        # No successful webhook jobs ever
        results = attempt_self_heal(token)
        if all(r["success"] for r in results):
            return {"status": "self_healed", "reason": "no_jobs_found", "renewals": results}
        send_alert(sms_url, format_failure_alert(results, reason="no prior webhook jobs"))
        return {"status": "alert_sent", "reason": "no_jobs_found", "renewals": results}

    if hours_since <= 48:
        return {
            "status": "healthy",
            "hours_since_last_run": round(hours_since, 1),
            "last_run": last_run,
        }

    # Stale — attempt self-heal before alerting
    results = attempt_self_heal(token)
    if all(r["success"] for r in results):
        return {
            "status": "self_healed",
            "hours_since_last_run": round(hours_since, 1),
            "last_run": last_run,
            "renewals": results,
        }

    # Self-heal failed — alert with specific errors
    send_alert(sms_url, format_failure_alert(results, hours_since=int(hours_since)))
    return {
        "status": "alert_sent",
        "reason": "self_heal_failed",
        "hours_since_last_run": round(hours_since, 1),
        "last_run": last_run,
        "renewals": results,
    }


def check_webhook_staleness(token):
    """Returns (hours_since, last_run_iso) or (None, None) if no jobs found."""
    resp = requests.get(
        f"{WM_API_BASE}/api/w/rrg/jobs/list",
        params={
            "script_path_exact": "f/switchboard/gmail_pubsub_webhook",
            "per_page": "1",
            "order_desc": "true",
            "success": "true",
        },
        headers={"Authorization": f"Bearer {token}"},
        timeout=15,
    )
    resp.raise_for_status()
    jobs = resp.json()

    if not jobs:
        return None, None

    created_at = jobs[0].get("created_at", "")
    if not created_at:
        return None, None

    last_run = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    now = datetime.now(timezone.utc)
    hours_since = (now - last_run).total_seconds() / 3600
    return hours_since, created_at


def attempt_self_heal(token):
    """Trigger both watch renewal scripts. Returns list of result dicts."""
    results = []
    for script_name, account in WATCH_SCRIPTS:
        try:
            resp = requests.post(
                f"{WM_API_BASE}/api/w/rrg/jobs/run_wait_result/p/f/switchboard/{script_name}",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
                json={},
                timeout=60,
            )
            if resp.status_code == 200:
                results.append({"script": script_name, "account": account, "success": True})
            else:
                body = resp.json()
                error_msg = body.get("error", {}).get("message", resp.text[:200])
                results.append({"script": script_name, "account": account, "success": False, "error": error_msg})
        except Exception as e:
            results.append({"script": script_name, "account": account, "success": False, "error": str(e)[:200]})
    return results


def format_failure_alert(results, hours_since=None, reason=None):
    """Build SMS alert message from failed renewal results."""
    parts = []
    if hours_since:
        parts.append(f"Gmail webhook stale ({hours_since}h). Self-heal failed:")
    elif reason:
        parts.append(f"Gmail watch issue ({reason}). Self-heal failed:")

    for r in results:
        status = "OK" if r["success"] else f"FAILED: {r.get('error', 'unknown')[:80]}"
        parts.append(f"  {r['account']} {status}")

    return " ".join(parts)


def send_alert(sms_url, message):
    """Send SMS alert to Jake via pixel-9a gateway."""
    try:
        requests.post(
            sms_url,
            json={"phone": "+17348960518", "message": f"[RRG Alert] {message}"},
            timeout=30,
        )
    except Exception as e:
        print(f"Failed to send SMS alert: {e}")
```

**Step 2: Commit**

```bash
git add windmill/f/switchboard/check_gmail_watch_health.py
git commit -m "feat: self-healing Gmail watch health check

When webhook is stale (>48h), attempts to re-register both watches
via Windmill API before alerting Jake. Only sends SMS if renewal
fails (e.g., revoked OAuth token requiring manual re-auth)."
```

---

### Task 2: Re-authorize both Gmail accounts (Manual — Jake)

These are manual steps Jake performs in Google Cloud Console + Windmill UI. Not automatable.

**Step 1: Re-auth teamgotcher@ with rrg-gmail-automation**

1. Go to Google Cloud Console → project `rrg-gmail-automation`
2. APIs & Services → Credentials → OAuth 2.0 Client (client ID `38784890226-...`)
3. Run OAuth consent flow for teamgotcher@gmail.com with scopes: `gmail.readonly`, `gmail.compose`, `gmail.modify`, `gmail.send`
4. Copy the new refresh_token
5. In Windmill UI → Resources → `f/switchboard/gmail_oauth` → update `refresh_token` field

**Step 2: Re-auth leads@ with rrg-gmail-automation**

1. Same GCP project `rrg-gmail-automation`, same OAuth client
2. Run OAuth consent flow for leads@resourcerealtygroupmi.com with same scopes
3. Copy the new refresh_token
4. In Windmill UI → Resources → `f/switchboard/gmail_leads_oauth` → update `refresh_token` AND verify `client_id` and `client_secret` match `rrg-gmail-automation` (not claude-connector)

---

### Task 3: Sync script to Windmill and restore service

**Step 1: Push the updated health check to Windmill**

```bash
cd ~/rrg-server && wmill sync push --skip-variables --skip-secrets --skip-resources
```

**Step 2: Run both watch setup scripts to restore service**

Run in Windmill UI or via API:
```bash
curl -s -X POST "http://100.97.86.99:8000/api/w/rrg/jobs/run_wait_result/p/f/switchboard/setup_gmail_watch" \
  -H "Authorization: Bearer muswxrdRPHx1dI7cRsz15N3Qkib114K9" \
  -H "Content-Type: application/json" -d '{}'

curl -s -X POST "http://100.97.86.99:8000/api/w/rrg/jobs/run_wait_result/p/f/switchboard/setup_gmail_leads_watch" \
  -H "Authorization: Bearer muswxrdRPHx1dI7cRsz15N3Qkib114K9" \
  -H "Content-Type: application/json" -d '{}'
```

Expected: both return `{"success": true, "historyId": ..., "expiration": ...}`

**Step 3: Verify webhook is receiving pushes**

Wait 5-10 minutes, then check:
```bash
curl -s "http://100.97.86.99:8000/api/w/rrg/jobs/list?script_path_exact=f/switchboard/gmail_pubsub_webhook&per_page=3&order_desc=true&success=true" \
  -H "Authorization: Bearer muswxrdRPHx1dI7cRsz15N3Qkib114K9" | python3 -m json.tool
```

Expected: new successful webhook jobs appearing.

---

### Task 4: Test self-healing by running the health check

**Step 1: Run the health check manually**

```bash
curl -s -X POST "http://100.97.86.99:8000/api/w/rrg/jobs/run_wait_result/p/f/switchboard/check_gmail_watch_health" \
  -H "Authorization: Bearer muswxrdRPHx1dI7cRsz15N3Qkib114K9" \
  -H "Content-Type: application/json" -d '{}'
```

After Task 3, this should return `{"status": "healthy", ...}` since the webhook will be running again.

**Step 2: Verify self-heal path works (after watches naturally expire)**

After the next 7-day watch expiry, if the scheduled renewal fails for any reason, the daily health check will attempt self-heal. Verify by checking the health check job results in Windmill for `"status": "self_healed"` entries.
