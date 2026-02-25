# Module A: Fetch Thread + Classify Reply Intent
# Part of f/switchboard/lead_conversation flow
#
# Fetches full Gmail thread, sends to Claude for intent classification.
# Returns classification + all context needed for downstream modules.

#extra_requirements:
#google-api-python-client
#google-auth

import wmill
import json
import os
import re
import subprocess
import base64
import html
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials


def get_gmail_service():
    oauth = wmill.get_resource("f/switchboard/gmail_oauth")
    creds = Credentials(
        token=oauth["access_token"],
        refresh_token=oauth["refresh_token"],
        token_uri="https://oauth2.googleapis.com/token",
        client_id=oauth["client_id"],
        client_secret=oauth["client_secret"]
    )
    return build('gmail', 'v1', credentials=creds)


def strip_html(text):
    text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<script[^>]*>.*?</script>', '', text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<br\s*/?>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'</(p|div|tr|li)>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'<[^>]+>', '', text)
    text = html.unescape(text)
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def get_body_from_payload(payload):
    mime_type = payload.get("mimeType", "")
    if mime_type == "text/plain" and "body" in payload:
        data = payload["body"].get("data", "")
        if data:
            return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
    parts = payload.get("parts", [])
    for part in parts:
        if part.get("mimeType") == "text/plain":
            data = part.get("body", {}).get("data", "")
            if data:
                return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
    for part in parts:
        if part.get("mimeType") == "text/html":
            data = part.get("body", {}).get("data", "")
            if data:
                return strip_html(base64.urlsafe_b64decode(data).decode("utf-8", errors="replace"))
    for part in parts:
        if part.get("mimeType", "").startswith("multipart/"):
            result = get_body_from_payload(part)
            if result:
                return result
    return ""


def fetch_thread_context(service, thread_id):
    """Fetch all messages in a thread, formatted chronologically."""
    thread = service.users().threads().get(userId='me', id=thread_id, format='full').execute()
    messages = thread.get('messages', [])

    formatted = []
    for msg in messages:
        headers = {h['name'].lower(): h['value']
                   for h in msg.get('payload', {}).get('headers', [])}
        body = get_body_from_payload(msg.get('payload', {}))

        formatted.append({
            "from": headers.get('from', ''),
            "to": headers.get('to', ''),
            "subject": headers.get('subject', ''),
            "date": headers.get('date', ''),
            "message_id_header": headers.get('message-id', ''),
            "body": body[:3000]  # Truncate very long bodies
        })

    return formatted


def classify_with_claude(thread_messages, reply_body, lead_name, properties, has_nda):
    """Use Claude to classify the lead's reply intent."""

    property_info = []
    for p in properties:
        info = p.get("canonical_name", "")
        if p.get("property_address"):
            info += f" ({p['property_address']})"
        if p.get("asking_price"):
            info += f" - Asking: {p['asking_price']}"
        property_info.append(info)
    property_text = "\n".join(f"  - {p}" for p in property_info) if property_info else "  (unknown property)"

    thread_text = ""
    for i, msg in enumerate(thread_messages):
        thread_text += f"\n--- Message {i+1} ---\n"
        thread_text += f"From: {msg['from']}\n"
        thread_text += f"Date: {msg['date']}\n"
        thread_text += f"Body:\n{msg['body']}\n"

    prompt = f"""You are classifying a reply in a commercial real estate email thread.

Context:
- Properties involved:
{property_text}
- Lead name: {lead_name}
- Lead has NDA on file: {has_nda}

Full email thread (chronological):
{thread_text}

Latest reply from the lead:
{reply_body[:2000]}

Classify this reply into exactly ONE category:

1. INTERESTED — They want more information, want a tour, are asking questions about the property, or engaging positively in any way
2. IGNORE — Automated response (out-of-office, delivery receipt), spam, generic "thanks" with no substance, or completely empty/no meaningful content
3. NOT_INTERESTED — They explicitly decline, say they're the wrong person, not looking, already found something, or ask to stop contacting them
4. ERROR — Cannot determine intent, garbled/unreadable text, or completely unrelated to real estate

If INTERESTED, also determine the sub-category:
- OFFER — They're making or discussing a purchase offer, price negotiation, specific deal terms, LOI, or closing conditions
- WANT_SOMETHING — They're asking for specific information, documents, or services (tour, OM, financials, etc.)
- GENERAL_INTEREST — They're interested but haven't asked for anything specific yet (e.g., "sounds great", "tell me more", "I'm interested")

If WANT_SOMETHING, list what they want. Pick ALL that apply from:
tour, brochure, om, financials, rent_roll, t12, proforma, price, zoning, size, units, hoa, broker_coop, still_available, why_selling, seller_terms, nda, other

Respond with ONLY valid JSON (no markdown fences, no explanation outside the JSON):
{{"classification": "INTERESTED", "sub_classification": "OFFER" or "WANT_SOMETHING" or "GENERAL_INTEREST", "wants": ["tour", "om"] or null, "confidence": 0.85, "reasoning": "brief 1-sentence explanation"}}"""

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

        result_text = result.stdout.strip()

        # Parse JSON from response (handle potential markdown wrapping)
        clean = result_text
        if clean.startswith("```"):
            clean = re.sub(r'^```(?:json)?\s*', '', clean)
            clean = re.sub(r'\s*```$', '', clean)

        return json.loads(clean)
    except Exception as e:
        return {
            "classification": "ERROR",
            "sub_classification": None,
            "wants": None,
            "confidence": 0.0,
            "reasoning": f"Classification failed: {str(e)}"
        }


def main(reply_data: dict):
    """Fetch thread context and classify the lead's reply."""
    thread_id = reply_data.get("thread_id", "")
    message_id = reply_data.get("message_id", "")
    reply_body = reply_data.get("reply_body", "")
    reply_from = reply_data.get("reply_from", "")
    reply_subject = reply_data.get("reply_subject", "")
    lead_email = reply_data.get("lead_email", "")
    lead_name = reply_data.get("lead_name", "")
    lead_phone = reply_data.get("lead_phone", "")
    source = reply_data.get("source", "")
    source_type = reply_data.get("source_type", "")
    wiseagent_client_id = reply_data.get("wiseagent_client_id")
    has_nda = reply_data.get("has_nda", False)
    properties = reply_data.get("properties", [])
    original_signal_id = reply_data.get("signal_id")

    # 1. Fetch full thread from Gmail
    service = get_gmail_service()
    thread_messages = fetch_thread_context(service, thread_id)

    # Get the Message-ID header of the latest message (for In-Reply-To)
    latest_message_id_header = ""
    if thread_messages:
        latest_message_id_header = thread_messages[-1].get("message_id_header", "")

    # 2. Classify with Claude
    classification = classify_with_claude(
        thread_messages, reply_body, lead_name, properties, has_nda
    )

    return {
        "thread_id": thread_id,
        "message_id": message_id,
        "reply_body": reply_body[:1000],
        "reply_from": reply_from,
        "reply_subject": reply_subject,
        "latest_message_id_header": latest_message_id_header,
        "lead_email": lead_email,
        "lead_name": lead_name,
        "lead_phone": lead_phone,
        "source": source,
        "source_type": source_type,
        "wiseagent_client_id": wiseagent_client_id,
        "has_nda": has_nda,
        "properties": properties,
        "original_signal_id": original_signal_id,
        "classification": classification,
        "thread_message_count": len(thread_messages)
    }
