
#extra_requirements:
#google-api-python-client
#google-auth

import wmill
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials

def main():
    oauth = wmill.get_resource("f/switchboard/gmail_oauth")
    creds = Credentials(
        token=oauth["access_token"],
        refresh_token=oauth["refresh_token"],
        token_uri="https://oauth2.googleapis.com/token",
        client_id=oauth["client_id"],
        client_secret=oauth["client_secret"]
    )
    service = build("gmail", "v1", credentials=creds)
    
    # Get recent sent emails to test@example.com with thread IDs
    results = service.users().messages().list(
        userId="me", q="to:test@example.com in:sent", maxResults=5
    ).execute()
    
    output = []
    for m in results.get("messages", []):
        msg = service.users().messages().get(
            userId="me", id=m["id"], format="metadata",
            metadataHeaders=["Subject", "To", "Message-ID"]
        ).execute()
        headers = {h["name"]: h["value"] for h in msg.get("payload", {}).get("headers", [])}
        output.append({
            "message_id": m["id"],
            "thread_id": msg.get("threadId"),
            "subject": headers.get("Subject", ""),
            "message_id_header": headers.get("Message-ID", ""),
            "labels": msg.get("labelIds", [])
        })
    
    # Also check: what thread_id does draft signal #14 reference?
    # thread_id from signal: 19c72b42a273cdf1
    return {"sent_emails": output}
