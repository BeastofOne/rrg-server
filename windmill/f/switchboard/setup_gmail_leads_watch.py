# Setup Gmail Watch for leads@ Pub/Sub Push Notifications
# Path: f/switchboard/setup_gmail_leads_watch
#
# Sets up Gmail push notifications via the users().watch() API for leads@.
# Watches INBOX label only (leads@ receives notifications, not sends).
# Publishes to the same Pub/Sub topic as teamgotcher@.
# Should be run once, then scheduled every 6 days for renewal (watch expires in ~7 days).
#
# Schedule: 0 0 9 */6 * * (9 AM every 6 days)

#extra_requirements:
#google-api-python-client
#google-auth

import wmill
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
from datetime import datetime, timezone


def main():
    """Set up Gmail watch for INBOX label changes on leads@."""
    # Get Gmail OAuth credentials for leads@
    oauth = wmill.get_resource("f/switchboard/gmail_leads_oauth")
    creds = Credentials(
        token=oauth["access_token"],
        refresh_token=oauth["refresh_token"],
        token_uri="https://oauth2.googleapis.com/token",
        client_id=oauth["client_id"],
        client_secret=oauth["client_secret"]
    )
    service = build("gmail", "v1", credentials=creds)

    # Set up watch on INBOX label only (leads@ only receives, never sends)
    # Same Pub/Sub topic as teamgotcher@ — webhook distinguishes accounts via emailAddress
    watch_response = service.users().watch(
        userId="me",
        body={
            "topicName": "projects/rrg-gmail-automation/topics/gmail-sent-notifications",
            "labelIds": ["INBOX"]
        }
    ).execute()

    # Calculate expiration time (returned as milliseconds since epoch)
    expiration_ms = int(watch_response.get("expiration", 0))
    expiration_dt = datetime.fromtimestamp(expiration_ms / 1000, tz=timezone.utc)

    return {
        "success": True,
        "account": "leads@resourcerealtygroupmi.com",
        "historyId": watch_response.get("historyId"),
        "expiration": watch_response.get("expiration"),
        "expiration_datetime": expiration_dt.isoformat(),
        "topic": "projects/rrg-gmail-automation/topics/gmail-sent-notifications",
        "labels_watched": ["INBOX"],
        "message": "Gmail watch for leads@ set up successfully. Renew before expiration (~7 days)."
    }
