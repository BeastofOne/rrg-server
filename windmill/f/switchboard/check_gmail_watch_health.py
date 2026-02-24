# Gmail Watch Health Check
# Path: f/switchboard/check_gmail_watch_health
#
# Checks that gmail_pubsub_webhook has run recently (within 48 hours).
# If stale, both Gmail watches may have expired and emails aren't being processed.
# Sends SMS alert to Jake via pixel-9a gateway.
#
# Monitors BOTH accounts:
# - teamgotcher@gmail.com (SENT + INBOX watch)
# - leads@resourcerealtygroupmi.com (INBOX watch)
#
# Schedule: Daily at 10 AM ET

#extra_requirements:
#requests

import wmill
import requests
from datetime import datetime, timezone, timedelta


def main():
    # Get the current history ID variable metadata
    # We check if ANY webhook has run recently by looking at Windmill job history
    token = wmill.get_variable("f/switchboard/router_token")
    sms_url = wmill.get_variable("f/switchboard/sms_gateway_url")

    # Check recent jobs for gmail_pubsub_webhook
    try:
        resp = requests.get(
            "http://localhost:8000/api/w/rrg/jobs/list",
            params={
                "script_path_exact": "f/switchboard/gmail_pubsub_webhook",
                "per_page": "1",
                "order_desc": "true",
                "success": "true"
            },
            headers={"Authorization": f"Bearer {token}"},
            timeout=15
        )
        resp.raise_for_status()
        jobs = resp.json()

        if not jobs:
            # No successful webhook jobs ever — definitely broken
            send_alert(sms_url, "No Gmail webhook jobs found. Gmail watches may never have been set up. Run setup_gmail_watch AND setup_gmail_leads_watch.")
            return {"status": "alert_sent", "reason": "no_jobs_found"}

        last_job = jobs[0]
        created_at = last_job.get("created_at", "")

        # Parse the timestamp
        if created_at:
            # Windmill timestamps are ISO format
            last_run = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
            now = datetime.now(timezone.utc)
            hours_since = (now - last_run).total_seconds() / 3600

            if hours_since > 48:
                send_alert(
                    sms_url,
                    f"Gmail webhook hasn't run in {int(hours_since)} hours. "
                    f"Gmail watches may have expired. Run setup_gmail_watch (teamgotcher@) AND setup_gmail_leads_watch (leads@) to fix."
                )
                return {
                    "status": "alert_sent",
                    "reason": "stale_webhook",
                    "hours_since_last_run": round(hours_since, 1),
                    "last_run": created_at
                }
            else:
                return {
                    "status": "healthy",
                    "hours_since_last_run": round(hours_since, 1),
                    "last_run": created_at
                }
        else:
            send_alert(sms_url, "Gmail webhook health check: couldn't parse last job timestamp.")
            return {"status": "alert_sent", "reason": "parse_error"}

    except Exception as e:
        # If we can't even check, that's also worth alerting about
        try:
            send_alert(sms_url, f"Gmail health check failed: {str(e)[:100]}")
        except Exception:
            pass
        return {"status": "error", "error": str(e)}


def send_alert(sms_url, message):
    """Send SMS alert to Jake via pixel-9a gateway."""
    try:
        requests.post(
            sms_url,
            json={"phone": "+17348960518", "message": f"[RRG Alert] {message}"},
            timeout=30
        )
    except Exception as e:
        print(f"Failed to send SMS alert: {e}")
