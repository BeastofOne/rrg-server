# Gmail Watch Health Check (Self-Healing, Per-Account)
# Path: f/switchboard/check_gmail_watch_health
#
# Checks gmail_pubsub_webhook freshness PER ACCOUNT (leads@ and teamgotcher@)
# and verifies both renewal schedules are present + enabled in the Windmill DB.
# If any check fails, queues async watch renewals and alerts Jake via SMS.
#
# Why per-account: teamgotcher@ fires constantly for sends/replies, which
# previously masked leads@ going silent (9-day outage April 16-24, 2026).
#
# Why schedule existence probe: after bare `wmill sync push` wipes in Feb 2026,
# the leads@ renewal schedule was deleted from the DB. Local yaml existed,
# but no renewal ran. The schedule probe catches this class of failure.
#
# Monitors:
# - leads@resourcerealtygroupmi.com (INBOX watch)
# - teamgotcher@gmail.com (SENT + INBOX watch)
#
# Schedule: Daily at 10 AM ET

#extra_requirements:
#psycopg2-binary
#requests

import os
import time
import wmill
import requests
import psycopg2
from datetime import datetime, timezone

WM_API_BASE = os.environ.get('BASE_INTERNAL_URL', 'http://localhost:8000')
STALENESS_HOURS = 48

# Hardcoded so bootstrap failures (wmill.get_variable raises) still get signal.
# Matches f/switchboard/sms_gateway_url — Pixel 9a gateway on Tailscale.
FALLBACK_SMS_URL = "http://100.125.176.16:8686/send-sms"
ALERT_PHONE = "+17348960518"

# (script_name, account_key_in_webhook_result, schedule_path, human_label)
WATCH_SCRIPTS = [
    ("setup_gmail_watch", "teamgotcher", "f/switchboard/schedule_gmail_watch_renewal", "teamgotcher@"),
    ("setup_gmail_leads_watch", "leads", "f/switchboard/schedule_gmail_leads_watch_renewal", "leads@"),
]


def main():
    # Fetch Windmill variables up front. If these fail, we still need to alert
    # Jake — fall back to a hardcoded SMS URL so a token/variable issue doesn't
    # silently swallow the health-check failure.
    token = None
    sms_url = None
    try:
        token = wmill.get_variable("f/switchboard/router_token")
        sms_url = wmill.get_variable("f/switchboard/sms_gateway_url")
    except Exception as e:
        delivered = send_alert(sms_url, f"Gmail health check bootstrap failed: {str(e)[:100]}")
        return {"status": "error", "reason": "bootstrap_failed", "error": str(e), "alert_delivered": delivered}

    try:
        return run_checks(token, sms_url)
    except Exception as e:
        # Catch-all so any unexpected runtime error still surfaces via SMS.
        delivered = send_alert(sms_url, f"Gmail health check errored: {str(e)[:120]}")
        return {"status": "error", "error": str(e), "alert_delivered": delivered}


def run_checks(token, sms_url):
    issues = []

    # 1) Schedule existence + enabled check
    try:
        disabled = check_schedules_enabled(token)
        for path in disabled:
            issues.append(f"schedule {path} missing or disabled")
    except Exception as e:
        issues.append(f"schedule check errored: {str(e)[:100]}")

    # 2) Per-account webhook staleness check
    account_status = {}
    try:
        pg = wmill.get_resource("f/switchboard/pg")
        conn = psycopg2.connect(
            host=pg["host"], port=pg.get("port", 5432), dbname=pg["dbname"],
            user=pg["user"], password=pg["password"], sslmode=pg.get("sslmode", "disable"),
        )
        try:
            for _, account_key, _, label in WATCH_SCRIPTS:
                hours_since, last_run = check_account_staleness(conn, account_key)
                account_status[account_key] = {"hours_since": hours_since, "last_run": last_run, "label": label}
                if hours_since is None:
                    issues.append(f"{label} no prior webhook jobs found")
                elif hours_since > STALENESS_HOURS:
                    issues.append(f"{label} webhook stale ({int(hours_since)}h)")
        finally:
            conn.close()
    except Exception as e:
        issues.append(f"staleness check errored: {str(e)[:100]}")

    if not issues:
        return {
            "status": "healthy",
            "alert_delivered": None,
            "accounts": account_status,
        }

    # Something is wrong: queue self-heal + alert
    heal_results = attempt_self_heal(token)
    delivered = send_alert(sms_url, format_alert(issues, heal_results))

    return {
        "status": "alert_sent" if delivered else "alert_failed",
        "alert_delivered": delivered,
        "issues": issues,
        "accounts": account_status,
        "renewals": heal_results,
    }


def check_account_staleness(conn, account_key):
    """Return (hours_since_last_run, last_run_iso) for a specific account,
    or (None, None) if no successful webhook jobs found for that account."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT created_at
            FROM v2_as_completed_job
            WHERE script_path = 'f/switchboard/gmail_pubsub_webhook'
              AND success = true
              AND result->>'account' = %s
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (account_key,),
        )
        row = cur.fetchone()
    if not row:
        return None, None
    last_run = row[0]
    if last_run.tzinfo is None:
        last_run = last_run.replace(tzinfo=timezone.utc)
    hours_since = (datetime.now(timezone.utc) - last_run).total_seconds() / 3600
    return hours_since, last_run.isoformat()


def check_schedules_enabled(token):
    """Return a list of schedule paths that are missing or disabled.

    Retries transient errors once (1s backoff) so a blip on localhost:8000
    doesn't produce a false-positive SMS on the daily run.
    """
    problems = []
    for _, _, schedule_path, _ in WATCH_SCRIPTS:
        last_err = None
        for attempt in range(2):
            try:
                resp = requests.get(
                    f"{WM_API_BASE}/api/w/rrg/schedules/get/{schedule_path}",
                    headers={"Authorization": f"Bearer {token}"},
                    timeout=15,
                )
                if resp.status_code == 404:
                    problems.append(schedule_path)
                    last_err = None
                    break
                resp.raise_for_status()
                data = resp.json()
                if not data.get("enabled", False):
                    problems.append(schedule_path)
                last_err = None
                break
            except Exception as e:
                last_err = e
                if attempt == 0:
                    time.sleep(1)
        if last_err is not None:
            problems.append(f"{schedule_path} (check failed: {str(last_err)[:80]})")
    return problems


def attempt_self_heal(token):
    """Queue both watch renewal scripts as async jobs.

    Uses async job submission (not run_wait_result) to avoid deadlocking
    the single Windmill worker — this script holds the worker while running,
    so synchronous sub-jobs would never get picked up.

    Both scripts are queued regardless of which account is stale, because
    (a) renewal is idempotent and cheap, and (b) they don't interfere.
    """
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    results = []
    for script_name, _, _, label in WATCH_SCRIPTS:
        try:
            resp = requests.post(
                f"{WM_API_BASE}/api/w/rrg/jobs/run/p/f/switchboard/{script_name}",
                headers=headers,
                json={},
                timeout=15,
            )
            if resp.status_code == 200:
                job_id = resp.text.strip().strip('"')
                results.append({
                    "script": script_name, "account": label, "success": True,
                    "note": f"job {job_id} queued",
                })
            else:
                results.append({
                    "script": script_name, "account": label, "success": False,
                    "error": resp.text[:200],
                })
        except Exception as e:
            results.append({
                "script": script_name, "account": label, "success": False,
                "error": str(e)[:200],
            })
    return results


def format_alert(issues, heal_results):
    """Build SMS alert text from issues + self-heal outcome."""
    parts = ["Gmail health:"]
    for i in issues:
        parts.append(f"- {i}")
    any_queued = any(r["success"] for r in heal_results)
    if any_queued:
        parts.append("Auto-renewal queued; check back in 10 min.")
    else:
        parts.append("Self-heal FAILED:")
        for r in heal_results:
            if not r["success"]:
                parts.append(f"  {r['account']}: {r.get('error', '')[:80]}")
    return " ".join(parts)


def send_alert(sms_url, message):
    """Send SMS alert to Jake via pixel-9a gateway. Returns True only if the
    gateway reports the SMS as actually sent (not just accepted by HTTP).
    Falls back to FALLBACK_SMS_URL if sms_url is empty. Never raises.

    Pixel 9a gateway contract (matches lead_intake post_approval script):
    returns JSON {"success": bool, "error": str} on HTTP 200. A 200 with
    {"success": false} means the SMS failed to send (bad number, carrier
    rejection, etc.) — must be reported as NOT delivered.
    """
    if not sms_url:
        sms_url = FALLBACK_SMS_URL
    try:
        resp = requests.post(
            sms_url,
            json={"phone": ALERT_PHONE, "message": f"[RRG Alert] {message}"},
            timeout=30,
        )
    except Exception as e:
        print(f"SMS gateway request failed: {e}")
        return False

    if not resp.ok:
        print(f"SMS gateway returned HTTP {resp.status_code}: {resp.text[:200]}")
        return False

    try:
        data = resp.json()
    except Exception:
        # Gateway returned 2xx but non-JSON — treat as delivered since we
        # can't inspect the body. Logs the response for post-mortem.
        print(f"SMS gateway returned non-JSON 2xx: {resp.text[:200]}")
        return True

    if not data.get("success", False):
        print(f"SMS gateway reported failure: {data.get('error', 'unknown')}")
        return False
    return True
