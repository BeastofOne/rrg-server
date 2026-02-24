
#extra_requirements:
#google-api-python-client
#google-auth

import wmill
import base64
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
    
    # Get the most recent sent email to test@example.com - FULL format
    results = service.users().messages().list(
        userId="me", q="to:test@example.com in:sent", maxResults=1
    ).execute()
    msgs = results.get("messages", [])
    if not msgs:
        return {"error": "no sent emails found"}
    
    msg = service.users().messages().get(
        userId="me", id=msgs[0]["id"], format="full"
    ).execute()
    
    # Extract ALL headers
    headers = msg.get("payload", {}).get("headers", [])
    all_headers = {h["name"]: h["value"] for h in headers}
    
    # Check for any X- headers
    x_headers = {k: v for k, v in all_headers.items() if k.startswith("X-")}
    lead_headers = {k: v for k, v in all_headers.items() if "Lead-Intake" in k}
    
    return {
        "message_id": msgs[0]["id"],
        "thread_id": msg.get("threadId"),
        "total_headers": len(headers),
        "header_names": sorted(all_headers.keys()),
        "x_headers": x_headers,
        "lead_intake_headers": lead_headers,
        "has_lead_headers": len(lead_headers) > 0
    }
