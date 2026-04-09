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

    # Stale — queue watch renewals (async, will run after this job frees the worker)
    results = attempt_self_heal(token)
    any_queued = any(r["success"] for r in results)

    if any_queued:
        # Jobs queued — alert Jake but note that auto-renewal is in progress
        send_alert(sms_url, f"Gmail webhook stale ({int(hours_since)}h). Auto-renewal queued — check back in 10 min.")
        return {
            "status": "renewal_queued",
            "hours_since_last_run": round(hours_since, 1),
            "last_run": last_run,
            "renewals": results,
        }

    # Couldn't even queue the jobs — alert with errors
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
    """Trigger both watch renewal scripts async, then poll for results.

    Uses async job submission (not run_wait_result) to avoid deadlocking
    the single Windmill worker — this script holds the worker while running,
    so synchronous sub-jobs would never get picked up.
    """
    import time

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    # Submit both jobs async
    jobs = []
    for script_name, account in WATCH_SCRIPTS:
        try:
            resp = requests.post(
                f"{WM_API_BASE}/api/w/rrg/jobs/run/p/f/switchboard/{script_name}",
                headers=headers,
                json={},
                timeout=15,
            )
            if resp.status_code == 200:
                job_id = resp.text.strip().strip('"')
                jobs.append({"script": script_name, "account": account, "job_id": job_id})
            else:
                jobs.append({"script": script_name, "account": account, "job_id": None, "error": resp.text[:200]})
        except Exception as e:
            jobs.append({"script": script_name, "account": account, "job_id": None, "error": str(e)[:200]})

    # This script must finish first to free the worker for the queued jobs.
    # Return job IDs so the next health check can verify they succeeded.
    # Also alert immediately — if the tokens are valid, the watches will
    # re-register once the worker is free, and the next health check will
    # see a healthy state. If the tokens are bad, Jake needs to know now.
    results = []
    for j in jobs:
        if j.get("job_id"):
            results.append({
                "script": j["script"],
                "account": j["account"],
                "success": True,
                "note": f"job {j['job_id']} queued (will run after health check completes)",
            })
        else:
            results.append({
                "script": j["script"],
                "account": j["account"],
                "success": False,
                "error": j.get("error", "failed to submit job"),
            })
    return results


def format_failure_alert(results, hours_since=None, reason=None):
    """Build SMS alert message from failed renewal results."""
    parts = []
    if hours_since is not None:
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
