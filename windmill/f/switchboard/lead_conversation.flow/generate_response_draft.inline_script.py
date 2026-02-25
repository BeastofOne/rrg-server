# Module B: Generate Response — Route by classification, create Gmail draft
# Part of f/switchboard/lead_conversation flow
#
# Routes based on Module A classification:
# - IGNORE/ERROR → CRM note, skip (terminal)
# - OFFER → notification signal for Jake, skip (terminal)
# - WANT_SOMETHING → look up docs, generate response draft
# - GENERAL_INTEREST → generate follow-up draft
# - NOT_INTERESTED → generate apology draft
#
# stop_after_if: result.skipped == true

#extra_requirements:
#google-api-python-client
#google-auth
#requests
#psycopg2-binary

import wmill
import json
import os
import re
import subprocess
import base64
import requests
import psycopg2
from email.mime.text import MIMEText
from datetime import datetime, timezone
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials

BASE_URL = "https://sync.thewiseagent.com/http/webconnect.asp"
TOKEN_URL = "https://sync.thewiseagent.com/WiseAuth/token"


def get_wa_token(oauth):
    """Get valid WiseAgent access token, refreshing if expired."""
    expires_at = oauth.get("expires_at", "")
    if expires_at:
        try:
            exp = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
            if datetime.now(timezone.utc) < exp.replace(tzinfo=timezone.utc):
                return oauth["access_token"]
        except Exception:
            pass
    resp = requests.post(TOKEN_URL, json={
        "grant_type": "refresh_token",
        "refresh_token": oauth["refresh_token"],
        "client_id": oauth.get("client_id", ""),
        "client_secret": oauth.get("client_secret", "")
    })
    resp.raise_for_status()
    new_tokens = resp.json()
    oauth["access_token"] = new_tokens["access_token"]
    oauth["refresh_token"] = new_tokens.get("refresh_token", oauth["refresh_token"])
    oauth["expires_at"] = new_tokens.get("expires_at", "")
    try:
        wmill.set_resource(oauth, "f/switchboard/wiseagent_oauth")
    except Exception:
        pass
    return oauth["access_token"]


def write_crm_note(client_id, subject, note_text):
    """Write a note to WiseAgent CRM."""
    if not client_id:
        return
    try:
        oauth = wmill.get_resource("f/switchboard/wiseagent_oauth")
        token = get_wa_token(oauth)
        requests.post(
            BASE_URL + "?requestType=addContactNote",
            data={"clientids": str(client_id), "note": note_text, "subject": subject},
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/x-www-form-urlencoded"},
            timeout=15
        )
    except Exception:
        pass


def write_notification_signal(summary, detail):
    """Write an info signal to jake_signals (no approval needed, just notification)."""
    try:
        pg = wmill.get_resource("f/switchboard/pg")
        conn = psycopg2.connect(
            host=pg["host"], port=pg.get("port", 5432),
            user=pg["user"], password=pg["password"],
            dbname=pg["dbname"], sslmode=pg.get("sslmode", "disable")
        )
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO public.jake_signals
            (signal_type, source_flow, summary, detail, actions, status)
            VALUES ('status_update', 'lead_conversation', %s, %s::jsonb, '[]'::jsonb, 'pending')
            RETURNING id
        """, (summary, json.dumps(detail)))
        signal_id = cur.fetchone()[0]
        conn.commit()
        cur.close()
        conn.close()
        return signal_id
    except Exception:
        return None


def create_reply_draft(to_email, subject, body, thread_id, in_reply_to=None):
    """Create a Gmail draft as a reply in an existing thread."""
    oauth = wmill.get_resource("f/switchboard/gmail_oauth")
    creds = Credentials(
        token=oauth["access_token"],
        refresh_token=oauth["refresh_token"],
        token_uri="https://oauth2.googleapis.com/token",
        client_id=oauth["client_id"],
        client_secret=oauth["client_secret"]
    )
    service = build('gmail', 'v1', credentials=creds)

    message = MIMEText(body)
    message['to'] = to_email
    message['subject'] = subject if subject.lower().startswith('re:') else f'Re: {subject}'
    if in_reply_to:
        message['In-Reply-To'] = in_reply_to
        message['References'] = in_reply_to

    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
    draft = service.users().drafts().create(
        userId='me',
        body={'message': {'raw': raw, 'threadId': thread_id}}
    ).execute()

    return {
        "draft_id": draft['id'],
        "thread_id": draft['message']['threadId']
    }


def generate_response_with_claude(classify_result, response_type):
    """Use Claude to generate a contextual email response."""
    lead_name = classify_result.get("lead_name", "")
    first_name = lead_name.split()[0] if lead_name else "there"
    properties = classify_result.get("properties", [])
    source = classify_result.get("source", "")
    source_type = classify_result.get("source_type", "")
    has_nda = classify_result.get("has_nda", False)
    classification = classify_result.get("classification", {})
    wants = classification.get("wants", []) or []
    reply_body = classify_result.get("reply_body", "")

    # Determine signoff based on source
    is_commercial = source_type in ("crexi_om", "crexi_flyer", "loopnet")
    if is_commercial:
        signoff = "Talk soon,\nLarry"
        phone = "(734) 732-3789"
        sender_name = "Larry"
    else:
        signoff = "All The Best,\nJake"
        phone = "(734) 896-0518"
        sender_name = "Jake"

    # Build property context
    prop_details = []
    for p in properties:
        detail = p.get("canonical_name", "")
        if p.get("property_address"):
            detail += f" at {p['property_address']}"
        if p.get("asking_price"):
            detail += f" (Asking: {p['asking_price']})"
        if p.get("brochure_highlights"):
            detail += f"\n    Highlights: {p['brochure_highlights']}"
        prop_details.append(detail)
    prop_text = "\n".join(f"  - {d}" for d in prop_details) if prop_details else "  (property details not available)"

    # Build available docs context
    docs_available = []
    for p in properties:
        docs = p.get("documents", {})
        if docs:
            for doc_type, path in docs.items():
                if path:
                    docs_available.append(f"{doc_type} for {p.get('canonical_name', 'property')}")
    docs_text = "\n".join(f"  - {d}" for d in docs_available) if docs_available else "  (no documents pre-loaded for this property)"

    if response_type == "not_interested":
        prompt = f"""Write a brief, professional email reply to a lead who has indicated they are NOT interested in the property.

Lead's name: {first_name}
Their reply: {reply_body[:500]}

Rules:
- Be gracious and brief (2-3 sentences max)
- Don't be pushy or try to change their mind
- Leave the door open for future contact
- Sign off as {sender_name}
- Use signoff: {signoff}
- Do NOT include a subject line — just the body

Write ONLY the email body text, nothing else."""

    elif response_type == "general_interest":
        prompt = f"""Write a brief, professional email reply to a lead who has shown general interest but hasn't asked for anything specific.

Lead's name: {first_name}
Property:
{prop_text}
Their reply: {reply_body[:500]}

Rules:
- Acknowledge their interest warmly
- Ask what specific information they'd like (tour, OM, financials, etc.)
- Mention your direct line: {phone}
- Keep it brief (3-4 sentences)
- Sign off as {sender_name}
- Use signoff: {signoff}
- Do NOT include a subject line — just the body

Write ONLY the email body text, nothing else."""

    elif response_type == "want_something":
        # Build what they want vs what we have
        wants_text = ", ".join(wants) if wants else "unspecified information"

        prompt = f"""Write a brief, professional email reply to a lead who has asked for specific information.

Lead's name: {first_name}
Property:
{prop_text}
What they asked for: {wants_text}
Their reply: {reply_body[:500]}
NDA on file: {has_nda}
Documents we have available:
{docs_text}

Rules:
- Address what they asked for directly
- If they want financials/rent_roll/t12 and DON'T have NDA: mention that financials require an NDA and offer to send one
- If they want financials and DO have NDA: say you'll send them over (the actual docs will be attached separately)
- If they want a tour: offer to schedule, ask for preferred date/time
- If they want info we have (OM, brochure, price, zoning, size): provide it or say you'll send it
- If they want info we DON'T have: say you'll check and get back to them
- Mention your direct line: {phone}
- Keep it concise (3-5 sentences)
- Sign off as {sender_name}
- Use signoff: {signoff}
- Do NOT include a subject line — just the body

Write ONLY the email body text, nothing else."""

    else:
        return f"Hey {first_name},\n\nThanks for getting back to me. If you have any questions about the property, don't hesitate to reach out. My direct line is {phone}.\n\n{signoff}"

    try:
        result = subprocess.run(
            ["claude", "-p", prompt, "--model", "haiku", "--no-chrome", "--allowedTools", ""],
            capture_output=True,
            text=True,
            timeout=90,
            env=os.environ.copy(),
        )

        if result.returncode != 0:
            error_msg = result.stderr.strip() or f"Claude CLI exited with code {result.returncode}"
            raise RuntimeError(error_msg)

        body = result.stdout.strip()
        # Remove any markdown fences Claude might add
        if body.startswith("```"):
            body = re.sub(r'^```\w*\s*', '', body)
            body = re.sub(r'\s*```$', '', body)
        return body
    except Exception as e:
        # Fallback to simple template
        return f"Hey {first_name},\n\nThanks for getting back to me! I'd love to help. My direct line is {phone} — feel free to call anytime.\n\n{signoff}"


def main(classify_result: dict):
    """Route based on classification and generate response if needed."""
    classification = classify_result.get("classification", {})
    cls = classification.get("classification", "ERROR")
    sub = classification.get("sub_classification")
    wants = classification.get("wants", []) or []
    reasoning = classification.get("reasoning", "")

    thread_id = classify_result.get("thread_id", "")
    lead_email = classify_result.get("lead_email", "")
    lead_name = classify_result.get("lead_name", "")
    lead_phone = classify_result.get("lead_phone", "")
    source = classify_result.get("source", "")
    source_type = classify_result.get("source_type", "")
    wiseagent_client_id = classify_result.get("wiseagent_client_id")
    has_nda = classify_result.get("has_nda", False)
    properties = classify_result.get("properties", [])
    reply_subject = classify_result.get("reply_subject", "")
    in_reply_to = classify_result.get("latest_message_id_header", "")
    original_signal_id = classify_result.get("original_signal_id")

    today = datetime.now().strftime("%Y-%m-%d")
    prop_names = ", ".join(p.get("canonical_name", "") for p in properties if p.get("canonical_name"))

    # ===== TERMINAL: IGNORE =====
    if cls == "IGNORE":
        write_crm_note(
            wiseagent_client_id,
            f"Lead Reply - Ignored",
            f"Automated/empty reply received on {today}. Classification: IGNORE. Reasoning: {reasoning}. Property: {prop_names}. No action taken."
        )
        return {
            "skipped": True,
            "reason": "ignore",
            "classification": cls,
            "reasoning": reasoning,
            "lead_email": lead_email
        }

    # ===== TERMINAL: ERROR =====
    if cls == "ERROR":
        write_crm_note(
            wiseagent_client_id,
            f"Lead Reply - Error",
            f"Reply received on {today} but could not be classified. Reasoning: {reasoning}. Property: {prop_names}. Manual review needed."
        )
        return {
            "skipped": True,
            "reason": "error",
            "classification": cls,
            "reasoning": reasoning,
            "lead_email": lead_email
        }

    # ===== TERMINAL: OFFER =====
    if cls == "INTERESTED" and sub == "OFFER":
        # Don't auto-respond to offers — notify Jake immediately
        signal_id = write_notification_signal(
            f"OFFER received from {lead_name or lead_email} on {prop_names}",
            {
                "lead_name": lead_name,
                "lead_email": lead_email,
                "lead_phone": lead_phone,
                "properties": properties,
                "reply_body": classify_result.get("reply_body", "")[:500],
                "reasoning": reasoning,
                "thread_id": thread_id,
                "original_signal_id": original_signal_id
            }
        )
        write_crm_note(
            wiseagent_client_id,
            f"Lead Reply - Offer Received",
            f"Lead replied with what appears to be an offer/negotiation on {today}. Property: {prop_names}. Signal #{signal_id} created for manual handling."
        )
        return {
            "skipped": True,
            "reason": "offer_received",
            "classification": cls,
            "sub_classification": sub,
            "reasoning": reasoning,
            "notification_signal_id": signal_id,
            "lead_email": lead_email,
            "lead_name": lead_name
        }

    # ===== ACTIONABLE: Generate response draft =====

    # Determine response type
    if cls == "NOT_INTERESTED":
        response_type = "not_interested"
    elif sub == "WANT_SOMETHING":
        response_type = "want_something"
    else:
        response_type = "general_interest"

    # Generate response body with Claude
    response_body = generate_response_with_claude(classify_result, response_type)

    # Create Gmail draft as reply in the same thread
    try:
        draft_result = create_reply_draft(
            to_email=lead_email,
            subject=reply_subject,
            body=response_body,
            thread_id=thread_id,
            in_reply_to=in_reply_to
        )

        draft = {
            "gmail_draft_id": draft_result["draft_id"],
            "gmail_thread_id": draft_result["thread_id"],
            "email_subject": reply_subject if reply_subject.lower().startswith('re:') else f'Re: {reply_subject}',
            "email_body": response_body,
            "to_email": lead_email,
            "name": lead_name,
            "email": lead_email,
            "phone": lead_phone,
            "source": source,
            "source_type": source_type,
            "wiseagent_client_id": wiseagent_client_id,
            "has_nda": has_nda,
            "properties": properties,
            "classification": cls,
            "sub_classification": sub,
            "wants": wants,
            "response_type": response_type,
            "draft_created_at": datetime.now(timezone.utc).isoformat(),
            "draft_creation_success": True,
            "original_signal_id": original_signal_id
        }

        # Determine SMS body for INTERESTED replies
        sms_body = None
        if cls == "INTERESTED" and lead_phone:
            is_commercial = source_type in ("crexi_om", "crexi_flyer", "loopnet")
            sender = "Larry" if is_commercial else "Jake"
            phone_num = "(734) 732-3789" if is_commercial else "(734) 896-0518"
            first_name = lead_name.split()[0] if lead_name else "there"
            sms_body = f"Hey {first_name}, {sender} from Resource Realty Group here. Just sent you a reply about {prop_names}. My direct line is {phone_num} if you'd rather chat by phone."
        draft["sms_body"] = sms_body

        return {
            "skipped": False,
            "drafts": [draft],
            "classification": cls,
            "sub_classification": sub,
            "response_type": response_type,
            "lead_email": lead_email,
            "lead_name": lead_name
        }

    except Exception as e:
        return {
            "skipped": True,
            "reason": "draft_creation_failed",
            "error": str(e),
            "classification": cls,
            "lead_email": lead_email
        }
