# Setup Gmail Watch for Pub/Sub Push Notifications
# Path: f/switchboard/setup_gmail_watch
#
# Sets up Gmail push notifications via the users().watch() API.
# Watches SENT and INBOX labels and publishes to Pub/Sub topic.
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
    """Set up Gmail watch for SENT and INBOX label changes."""
    # Get Gmail OAuth credentials
    oauth = wmill.get_resource("f/switchboard/gmail_oauth")
    creds = Credentials(
        token=oauth["access_token"],
        refresh_token=oauth["refresh_token"],
        token_uri="https://oauth2.googleapis.com/token",
        client_id=oauth["client_id"],
        client_secret=oauth["client_secret"]
    )
    service = build('gmail', 'v1', credentials=creds)

    # Set up watch on SENT and INBOX labels
    # Topic must be in the same GCP project as the OAuth client.
    # OAuth client must be from rrg-gmail-automation (TeamGotcher project).
    # Topic needs gmail-api-push@system.gserviceaccount.com with Pub/Sub Publisher permission.
    watch_response = service.users().watch(
        userId='me',
        body={
            'topicName': 'projects/rrg-gmail-automation/topics/gmail-sent-notifications',
            'labelIds': ['SENT', 'INBOX']
        }
    ).execute()

    # Calculate expiration time (returned as milliseconds since epoch)
    expiration_ms = int(watch_response.get('expiration', 0))
    expiration_dt = datetime.fromtimestamp(expiration_ms / 1000, tz=timezone.utc)

    return {
        "success": True,
        "historyId": watch_response.get('historyId'),
        "expiration": watch_response.get('expiration'),
        "expiration_datetime": expiration_dt.isoformat(),
        "topic": "projects/rrg-gmail-automation/topics/gmail-sent-notifications",
        "labels_watched": ["SENT", "INBOX"],
        "message": "Gmail watch set up successfully. Renew before expiration (~7 days)."
    }
