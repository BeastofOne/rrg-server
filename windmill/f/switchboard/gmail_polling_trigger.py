# DEPRECATED: Gmail Polling Trigger
# Path: f/switchboard/gmail_polling_trigger
#
# ⚠️ DEPRECATED as of Feb 23, 2026 — replaced by Pub/Sub push delivery.
# Pub/Sub push subscription delivers notifications directly to gmail_pubsub_webhook
# via Tailscale Funnel (https://rrg-server.tailc01f9b.ts.net:8443).
# Kept as emergency fallback only. Schedule (gmail_polling_schedule) is DISABLED.
#
# Original purpose: Polled Gmail for changes by getting current profile historyId.
# If changes detected, dispatched webhook asynchronously (no worker deadlock).
# Was scheduled every 1 minute.

#extra_requirements:
#google-api-python-client
#google-auth
#requests

import wmill
import base64
import json
import requests
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials


def main():
    """Poll Gmail and trigger webhook if there are changes.

    DEPRECATED: Use Pub/Sub push delivery instead. This script is kept
    as an emergency fallback if push delivery fails.
    """
    # Get current historyId from Gmail
    oauth = wmill.get_resource("f/switchboard/gmail_oauth")
    creds = Credentials(
        token=oauth["access_token"],
        refresh_token=oauth["refresh_token"],
        token_uri="https://oauth2.googleapis.com/token",
        client_id=oauth["client_id"],
        client_secret=oauth["client_secret"]
    )
    service = build('gmail', 'v1', credentials=creds)
    profile = service.users().getProfile(userId='me').execute()
    current_history_id = profile.get('historyId')
    email_address = profile.get('emailAddress')

    # Check if history has changed
    last_history = wmill.get_variable("f/switchboard/gmail_last_history_id")
    if str(last_history) == str(current_history_id):
        return {"skipped": True, "reason": "no_changes", "history_id": current_history_id}

    # Build simulated Pub/Sub message
    data = json.dumps({"emailAddress": email_address, "historyId": str(current_history_id)})
    encoded = base64.urlsafe_b64encode(data.encode()).decode()
    message = {"data": encoded, "messageId": f"poll-{current_history_id}"}

    # Dispatch webhook ASYNC via Windmill REST API (avoids worker deadlock)
    job_id = wmill.run_script_async(
        "f/switchboard/gmail_pubsub_webhook",
        args={"message": message}
    )

    return {
        "triggered": True,
        "history_id": current_history_id,
        "previous_history_id": last_history,
        "webhook_job_id": job_id
    }
