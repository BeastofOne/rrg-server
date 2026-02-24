
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
    
    # Search for recent sent emails to test@example.com
    results = service.users().messages().list(
        userId="me",
        q="to:test@example.com in:sent",
        maxResults=5
    ).execute()
    
    msgs = results.get("messages", [])
    output = []
    
    for m in msgs:
        msg = service.users().messages().get(
            userId="me", id=m["id"], format="metadata",
            metadataHeaders=["Subject", "To", "X-Lead-Intake-Draft-ID", "X-Lead-Intake-Signal-ID", "X-Lead-Intake-Email", "X-Lead-Intake-Phone", "X-Lead-Intake-Name"]
        ).execute()
        headers = {h["name"]: h["value"] for h in msg.get("payload", {}).get("headers", [])}
        labels = msg.get("labelIds", [])
        output.append({
            "id": m["id"],
            "subject": headers.get("Subject", ""),
            "to": headers.get("To", ""),
            "labels": labels,
            "x_draft_id": headers.get("X-Lead-Intake-Draft-ID", "NOT FOUND"),
            "x_signal_id": headers.get("X-Lead-Intake-Signal-ID", "NOT FOUND"),
            "x_email": headers.get("X-Lead-Intake-Email", "NOT FOUND"),
            "x_phone": headers.get("X-Lead-Intake-Phone", "NOT FOUND"),
            "x_name": headers.get("X-Lead-Intake-Name", "NOT FOUND"),
        })
    
    return {"sent_emails": output, "count": len(output)}
