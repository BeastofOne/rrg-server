# Gmail Pub/Sub Webhook — Split Inbox + Dual Account Support
# Path: f/switchboard/gmail_pubsub_webhook
#
# Receives Pub/Sub push notifications from Gmail for both accounts:
# - leads@resourcerealtygroupmi.com: INBOX notifications (lead categorization + parsing)
# - teamgotcher@gmail.com: SENT detection (resume flows) + INBOX reply detection
#
# Each account has its own OAuth resource and history cursor:
# - leads@: gmail_leads_oauth / gmail_leads_last_history_id
# - teamgotcher@: gmail_oauth / gmail_last_history_id
#
# Draft creation always uses teamgotcher@ (gmail_oauth) regardless of which
# account triggered the notification.
#
# ARCHITECTURE: "Hopper" model — one flow per person (not one flow per batch).
# Same-person multi-property leads are grouped before triggering, so each flow
# handles exactly 1 person → 1 draft → 1 signal → 1 suspend → 1 resume.
#
# DEDUP: Uses processed_notifications table (Postgres) to prevent duplicate
# intake triggers when multiple Pub/Sub pushes overlap on the same history range.
#
# Webhook URL: https://rrg-server.tailc01f9b.ts.net:8443/api/w/rrg/webhooks/<webhook_token>/p/f/switchboard/gmail_pubsub_webhook

#extra_requirements:
#psycopg2-binary
#google-api-python-client
#google-auth
#requests

import os
import wmill
import base64
import json
import re
import html
import psycopg2
import requests
from datetime import datetime, timezone, timedelta
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials

# Windmill API base URL — use internal sidecar when available
WM_API_BASE = os.environ.get('BASE_INTERNAL_URL', 'http://localhost:8000')

# Categories that trigger lead parsing
LEAD_CATEGORIES = {"crexi", "loopnet", "realtor_com", "seller_hub", "bizbuysell", "social_connect", "upnest"}

# Account configuration: maps emailAddress to OAuth resource + history variable
ACCOUNT_CONFIG = {
    "leads": {
        "oauth_resource": "f/switchboard/gmail_leads_oauth",
        "history_variable": "f/switchboard/gmail_leads_last_history_id",
        "process_inbox_leads": True,
        "process_sent": False,
        "process_inbox_replies": False,
    },
    "teamgotcher": {
        "oauth_resource": "f/switchboard/gmail_oauth",
        "history_variable": "f/switchboard/gmail_last_history_id",
        "process_inbox_leads": False,
        "process_sent": True,
        "process_inbox_replies": True,
    },
}


# ============================================================
# Gmail helpers
# ============================================================

def get_gmail_service(resource_name="f/switchboard/gmail_oauth"):
    """Build Gmail API service from OAuth credentials."""
    oauth = wmill.get_resource(resource_name)
    creds = Credentials(
        token=oauth["access_token"],
        refresh_token=oauth["refresh_token"],
        token_uri="https://oauth2.googleapis.com/token",
        client_id=oauth["client_id"],
        client_secret=oauth["client_secret"]
    )
    return build('gmail', 'v1', credentials=creds)


def detect_account(email_address):
    """Detect which account from the Pub/Sub emailAddress field."""
    if email_address and 'leads@' in email_address.lower():
        return 'leads'
    return 'teamgotcher'


def strip_html(text):
    """Convert HTML to plain text."""
    text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<script[^>]*>.*?</script>', '', text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<br\s*/?>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'</(p|div|tr|li)>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'<(p|div|tr|li)[^>]*>', '', text, flags=re.IGNORECASE)
    text = re.sub(r'<[^>]+>', '', text)
    text = html.unescape(text)
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def get_body_from_payload(payload):
    """Recursively extract plain text body from a Gmail message payload."""
    mime_type = payload.get("mimeType", "")
    if mime_type == "text/plain" and "body" in payload:
        data = payload["body"].get("data", "")
        if data:
            return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
    # Handle top-level text/html (no multipart wrapper — common in Crexi emails)
    if mime_type == "text/html" and "body" in payload:
        data = payload["body"].get("data", "")
        if data:
            html_text = base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
            return strip_html(html_text)
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
                html_text = base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
                return strip_html(html_text)
    for part in parts:
        if part.get("mimeType", "").startswith("multipart/"):
            result = get_body_from_payload(part)
            if result:
                return result
    return ""


# In-memory label cache (populated once per invocation, per service)
_label_cache = {}


def get_or_create_label(service, label_name):
    """Get a Gmail label ID by name, creating it if it doesn't exist."""
    if label_name in _label_cache:
        return _label_cache[label_name]
    results = service.users().labels().list(userId="me").execute()
    for label in results.get("labels", []):
        _label_cache[label["name"]] = label["id"]
    if label_name in _label_cache:
        return _label_cache[label_name]
    new_label = service.users().labels().create(
        userId="me",
        body={"name": label_name, "labelListVisibility": "labelShow", "messageListVisibility": "show"}
    ).execute()
    _label_cache[new_label["name"]] = new_label["id"]
    return new_label["id"]


def apply_label(service, msg_id, label_name, remove_labels=None):
    """Apply a Gmail label to a message. Optionally remove other labels."""
    add_ids = [get_or_create_label(service, label_name)]
    body = {"addLabelIds": add_ids}
    if remove_labels:
        remove_ids = []
        for name in remove_labels:
            try:
                remove_ids.append(get_or_create_label(service, name))
            except Exception:
                pass
        if remove_ids:
            body["removeLabelIds"] = remove_ids
    service.users().messages().modify(userId="me", id=msg_id, body=body).execute()


# ============================================================
# Dedup: prevent duplicate intake triggers
# ============================================================

def get_pg_conn():
    """Get a Postgres connection from Windmill resource."""
    pg = wmill.get_resource("f/switchboard/pg")
    return psycopg2.connect(
        host=pg["host"],
        port=pg.get("port", 5432),
        user=pg["user"],
        password=pg["password"],
        dbname=pg["dbname"],
        sslmode=pg.get("sslmode", "disable")
    )


def claim_message_ids(msg_ids, account, category=None):
    """Atomically claim message IDs. Returns set of IDs that were newly claimed.

    Uses INSERT ... ON CONFLICT DO NOTHING so only the first webhook invocation
    to see a message ID will get it. Concurrent invocations safely get nothing.
    """
    if not msg_ids:
        return set()

    conn = get_pg_conn()
    cur = conn.cursor()

    # Clean up entries older than 7 days (lightweight, runs every call)
    cur.execute("DELETE FROM public.processed_notifications WHERE processed_at < NOW() - INTERVAL '7 days'")

    claimed = set()
    for mid in msg_ids:
        cur.execute("""
            INSERT INTO public.processed_notifications (message_id, account, category)
            VALUES (%s, %s, %s)
            ON CONFLICT (message_id) DO NOTHING
            RETURNING message_id
        """, (mid, account, category))
        row = cur.fetchone()
        if row:
            claimed.add(row[0])

    conn.commit()
    cur.close()
    conn.close()
    return claimed


BATCH_DELAY_SECONDS = 30  # Delay before processing staged leads


def stage_leads(leads):
    """Write parsed leads to staged_leads table for batched processing."""
    if not leads:
        return []

    conn = get_pg_conn()
    cur = conn.cursor()
    staged_ids = []
    for lead in leads:
        cur.execute("""
            INSERT INTO public.staged_leads (email, name, phone, source, source_type, property_name, notification_message_id, raw_lead)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb)
            RETURNING id
        """, (
            lead.get("email", "").strip().lower(),
            lead.get("name", ""),
            lead.get("phone", ""),
            lead.get("source", ""),
            lead.get("source_type", ""),
            lead.get("property_name", ""),
            lead.get("notification_message_id", ""),
            json.dumps(lead)
        ))
        staged_ids.append(cur.fetchone()[0])
    conn.commit()
    cur.close()
    conn.close()
    return staged_ids


def schedule_delayed_processing(email):
    """Schedule a one-shot delayed job to process staged leads for this email.

    Only schedules if no unprocessed leads already exist for this email
    (i.e., this is the first notification — no timer running yet).
    Uses processed_notifications with 'timer:<email>' key for atomic check.
    """
    email_lower = email.strip().lower()
    conn = get_pg_conn()
    cur = conn.cursor()

    # Atomic check: only schedule if no timer is already running for this email
    cur.execute("""
        INSERT INTO public.processed_notifications (message_id, account, category)
        VALUES (%s, %s, %s)
        ON CONFLICT (message_id) DO NOTHING
        RETURNING message_id
    """, (f"timer:{email_lower}", "leads", "batch_timer"))
    row = cur.fetchone()
    conn.commit()
    cur.close()
    conn.close()

    if not row:
        # Timer already running for this email — just stage, don't schedule
        return {"scheduled": False, "reason": "timer_already_running"}

    # Schedule the delayed processing job
    token = wmill.get_variable("f/switchboard/router_token")
    scheduled_for = datetime.now(timezone.utc) + timedelta(seconds=BATCH_DELAY_SECONDS)

    response = requests.post(
        f"{WM_API_BASE}/api/w/rrg/jobs/run/p/f/switchboard/process_staged_leads",
        json={"email": email_lower},
        params={"scheduled_for": scheduled_for.isoformat()},
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        timeout=30
    )

    return {
        "scheduled": True,
        "status_code": response.status_code,
        "scheduled_for": scheduled_for.isoformat(),
        "delay_seconds": BATCH_DELAY_SECONDS
    }


# ============================================================
# Email categorization
# ============================================================

def categorize_email(sender, subject):
    """Categorize an email by sender/subject patterns.

    Returns (category, gmail_label) tuple.
    """
    sender_lower = sender.lower()
    subject_lower = subject.lower()

    if "notifications.crexi.com" in sender_lower:
        return ("crexi", "Crexi")

    if "loopnet.com" in sender_lower and "favorited" in subject_lower:
        return ("loopnet", "LoopNet")

    if subject_lower.startswith("new realtor.com lead"):
        return ("realtor_com", "Realtor.com")

    if "new verified seller lead" in subject_lower and "sellerappointmenthub.com" in sender_lower:
        return ("seller_hub", "Seller Hub")

    if "bizbuysell.com" in sender_lower:
        return ("bizbuysell", "BizBuySell")

    # Social Connect / Top Producer leads
    if "social connect" in subject_lower:
        return ("social_connect", "Social Connect")

    # UpNest leads — "Lead claimed" emails have contact info, others don't
    if "upnest.com" in sender_lower:
        if "lead claimed" in subject_lower:
            return ("upnest", "UpNest")
        return ("upnest_info", "UpNest")

    return ("unlabeled", "Unlabeled")


# ============================================================
# Lead validation (BUG 7C)
# ============================================================

def validate_lead(lead):
    """Cross-type sanity checks so fields can't be confused.

    Returns (is_valid, issues_list).
    """
    issues = []
    email = lead.get("email", "").strip()
    name = lead.get("name", "").strip()
    phone = lead.get("phone", "").strip()

    if not email and not name and not phone:
        return (False, ["no_identifying_fields"])

    if email:
        if not re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', email):
            issues.append("invalid_email_format")
        local = email.split('@')[0] if '@' in email else email
        if re.match(r'^\d+$', local):
            issues.append("email_local_numeric")

    if phone:
        digits = re.sub(r'[^0-9]', '', phone)
        if len(digits) < 7 or len(digits) > 15:
            issues.append("phone_bad_length")
        if '@' in phone:
            issues.append("phone_contains_at")

    if name:
        if not re.search(r'[a-zA-Z]', name):
            issues.append("name_no_letters")
        if '@' in name:
            issues.append("name_is_email")
        if len(re.sub(r'[^0-9]', '', name)) > 5:
            issues.append("name_looks_like_phone")

    return (len(issues) == 0, issues)


# ============================================================
# Lead parsing from notification bodies
# ============================================================


# Specific email addresses to always exclude from lead parsing
EXCLUDED_EMAIL_ADDRESSES = {
    'support@crexi.com', 'noreply@crexi.com',
    'teamgotcher@gmail.com',
}

# Domains whose emails are notification senders, not leads
SYSTEM_DOMAINS = {
    'crexi.com', 'loopnet.com', 'realtor.com', 'resourcerealty.com',
    'resourcerealtygroupmi.com', 'google.com', 'bizbuysell.com',
    'notifications.crexi.com', 'email.realtor.com',
    'sellerappointmenthub.com', 'costar.com', 'topproducer.com', 'upnest.com',
}


def parse_email_field(body):
    """Extract an email address from notification body text."""
    # Look for explicit "Email: xxx" pattern first
    m = re.search(
        r'(?:email|e-mail|email address)\s*[:\-]\s*([a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,})',
        body, re.IGNORECASE
    )
    if m:
        candidate = m.group(1).strip().lower()
        if candidate not in EXCLUDED_EMAIL_ADDRESSES:
            return m.group(1).strip()

    # Fallback: find any email that isn't a known system address
    emails = re.findall(r'[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}', body)
    for email in emails:
        lower = email.lower()
        if lower in EXCLUDED_EMAIL_ADDRESSES:
            continue
        if 'noreply' in lower or 'no-reply' in lower:
            continue
        domain = email.split('@')[1].lower()
        if not any(sd in domain for sd in SYSTEM_DOMAINS):
            return email
    return ""


def parse_name_field(body, subject=""):
    """Extract a person's name from notification body text.

    Tries labeled patterns first (Name: John Doe), then falls back to
    extracting from subject line.
    """
    # "Name: John Doe" pattern (capitalized)
    m = re.search(
        r'(?:name|contact|buyer|seller|lead)\s*[:\-]\s*([A-Z][a-zA-Z\'\-]+(?:\s+[A-Z][a-zA-Z\'\-]+){0,3})',
        body
    )
    if m:
        return m.group(1).strip()
    # Case-insensitive fallback
    m = re.search(
        r'(?:name|contact|buyer|seller|lead)\s*[:\-]\s*([a-zA-Z\'\-]+(?:\s+[a-zA-Z\'\-]+){0,3})',
        body, re.IGNORECASE
    )
    if m:
        name = m.group(1).strip()
        skip = {'the', 'a', 'an', 'your', 'this', 'that', 'none', 'n/a', 'not', 'no'}
        if len(name) > 1 and name.lower() not in skip:
            return name

    # Subject line fallback: try to extract a capitalized name at the start
    if subject:
        m = re.match(
            r'([A-Z][a-zA-Z\'\-]+(?:\s+[A-Z][a-zA-Z\'\-]+){1,3})\s+(?:has\s+)?(?:opened|executed|requesting|downloaded|favorited|clicked|is\s+requesting)',
            subject, re.IGNORECASE
        )
        if m:
            return m.group(1).strip()

    return ""


def parse_phone_field(body):
    """Extract a phone number from notification body text."""
    # Labeled pattern: "Phone: 555-1234"
    m = re.search(
        r'(?:phone|tel|mobile|cell)\s*[:\-]\s*([\(\d\+][\d\s\(\)\-\.]{7,15})',
        body, re.IGNORECASE
    )
    if m:
        return m.group(1).strip()

    # Bare-line fallback: a line that is ONLY a phone number
    for line in body.split('\n'):
        line = line.strip()
        if re.match(r'^[\(\+\d][\d\s\(\)\-\.]{7,15}$', line):
            # Exclude known system phone numbers
            digits = re.sub(r'\D', '', line)
            if digits != '8882730423':  # Crexi support
                return line

    return ""


def parse_property_name(subject, body, category):
    """Extract property name from notification subject/body."""
    if category == "crexi":
        # Crexi subjects: "Someone opened your OM for Property Name"
        m = re.search(r'(?:\bfor\b|\bon\b)\s+(.+?)(?:\s*$)', subject, re.IGNORECASE)
        if m:
            prop = m.group(1).strip().rstrip('.')
            if len(prop) > 2:
                return prop
        m = re.search(r'(?:property|listing)\s*[:\-]\s*(.+?)(?:\n|$)', body, re.IGNORECASE)
        if m:
            return m.group(1).strip()
    elif category == "loopnet":
        m = re.search(r'favorited\s+(.+?)(?:\s+on|\s*$)', subject, re.IGNORECASE)
        if m:
            return m.group(1).strip()
    elif category == "realtor_com":
        # "New realtor.com lead: 123 Main St"
        m = re.search(r'new realtor\.com lead[:\-\s]+(.+?)(?:\s*$)', subject, re.IGNORECASE)
        if m:
            return m.group(1).strip()
    elif category == "seller_hub":
        m = re.search(r'(?:property|address)\s*[:\-]\s*(.+?)(?:\n|$)', body, re.IGNORECASE)
        if m:
            return m.group(1).strip()
    elif category == "bizbuysell":
        m = re.search(r'Your Business-for-sale listing\s+(.+?)(?:\s*$)', subject, re.IGNORECASE)
        if m:
            return m.group(1).strip()
    return ""


# ============================================================
# Source-specific lead parsers
# ============================================================

def parse_crexi_lead(service, msg_id, sender, subject):
    """Parse lead data from a Crexi notification email.

    Crexi format:
      Subject: [Name] [action] on/for [Property]
      Body:
        [Name] has [action] the [document] for [Property] in [City].
        [email@domain.com]
        [phone.number]

        Click below to access contact information...
    """
    msg = service.users().messages().get(userId='me', id=msg_id, format='full').execute()
    body = get_body_from_payload(msg.get('payload', {}))

    # Name from subject: "Glenn Oppenlander has downloaded..."
    name = ""
    m = re.match(
        r"([A-Z][a-zA-Z'\-]+(?:\s+[A-Z][a-zA-Z'\-]+){1,3})\s+(?:has\s+)?(?:opened|Executed|requesting|downloaded|favorited|clicked|is\s+requesting)",
        subject
    )
    if m:
        name = m.group(1).strip()

    # Split body into lines for line-by-line parsing
    lines = body.split('\n')

    # Find the footer boundary — stop parsing before "Click below" or similar
    footer_idx = len(lines)
    for i, line in enumerate(lines):
        if 'click below' in line.lower() or 'access contact' in line.lower():
            footer_idx = i
            break

    # Email from body: first standalone email before footer
    email = ""
    for line in lines[:footer_idx]:
        line = line.strip()
        em = re.match(r'^([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})$', line)
        if em:
            candidate = em.group(1).lower()
            if candidate not in EXCLUDED_EMAIL_ADDRESSES:
                email = em.group(1)
                break

    # Phone from body: first standalone phone-like pattern before footer
    phone = ""
    for line in lines[:footer_idx]:
        line = line.strip()
        pm = re.match(r'^([\(\+\d][\d\s\(\)\-\.]{7,15})$', line)
        if pm:
            digits = re.sub(r'\D', '', pm.group(1))
            if digits != '8882730423':  # Crexi support number
                phone = pm.group(1).strip()
                break

    # Property from subject
    property_name = ""
    pm = re.search(r'(?:\bfor\b|\bon\b)\s+(.+?)(?:\s*$)', subject, re.IGNORECASE)
    if pm:
        prop = pm.group(1).strip().rstrip('.')
        if len(prop) > 2:
            property_name = prop

    # Source type from subject/body
    source_type = "crexi"

    if not email and not name:
        return None

    return {
        "name": name,
        "email": email,
        "phone": phone,
        "source": "Crexi",
        "source_type": source_type,
        "property_name": property_name,
        "notification_message_id": msg_id
    }


def parse_social_connect_lead(service, msg_id, sender, subject):
    """Parse lead data from a Social Connect / Top Producer email.

    Format (label on one line, value on the next):
      Name
      [Full Name]
      Email
      [email@domain.com]
      Phone
      [+1XXXXXXXXXX]
      Source
      Social Connect
      Property
      [Address]
    """
    msg = service.users().messages().get(userId='me', id=msg_id, format='full').execute()
    body = get_body_from_payload(msg.get('payload', {}))

    lines = [l.strip() for l in body.split('\n') if l.strip()]

    name = ""
    email = ""
    phone = ""
    property_name = ""

    for i, line in enumerate(lines):
        lower = line.lower()
        if lower == 'name' and i + 1 < len(lines):
            candidate = lines[i + 1]
            # Make sure the "value" line isn't another label
            if candidate.lower() not in ('email', 'phone', 'source', 'lead type', 'property'):
                name = candidate
        elif lower == 'email' and i + 1 < len(lines):
            candidate = lines[i + 1]
            if re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', candidate):
                if candidate.lower() not in EXCLUDED_EMAIL_ADDRESSES:
                    email = candidate
        elif lower == 'phone' and i + 1 < len(lines):
            phone = lines[i + 1]
        elif lower == 'property' and i + 1 < len(lines):
            property_name = lines[i + 1]

    # Fallback: try subject "New Lead: [Name] from Social Connect"
    if not name:
        m = re.search(r'New Lead:\s*(.+?)\s+from', subject, re.IGNORECASE)
        if m:
            name = m.group(1).strip()

    if not email and not name:
        return None

    result = {
        "name": name,
        "email": email,
        "phone": phone,
        "source": "Social Connect",
        "source_type": "social_connect",
        "property_name": property_name,
        "notification_message_id": msg_id
    }
    # Social Connect "Property" field contains a street address
    if property_name:
        result["property_address"] = property_name
    return result


def parse_upnest_lead(service, msg_id, sender, subject):
    """Parse lead data from an UpNest 'Lead claimed' email.

    Subject format: 'Lead claimed: Buyer Melina Griswold in Pinckney'
    Body has label-value pairs:
      [Name]
      City:
      [City]
      Phone:
      [Phone]
      Email:
      [Email]
    """
    # Extract lead_type (Buyer/Seller), name, and city from subject
    lead_type = ""
    name = ""
    city = ""
    m = re.match(r'Lead claimed:\s*(Buyer|Seller)\s+(.+?)\s+in\s+(.+)', subject, re.IGNORECASE)
    if m:
        lead_type = m.group(1).lower()
        name = m.group(2).strip()
        city = m.group(3).strip()
    else:
        # Fallback: subject without city (e.g. "Lead claimed: Buyer John Doe")
        m2 = re.match(r'Lead claimed:\s*(Buyer|Seller)\s+(.+)', subject, re.IGNORECASE)
        if m2:
            lead_type = m2.group(1).lower()
            name = m2.group(2).strip()

    # Parse email and phone from body
    msg = service.users().messages().get(userId='me', id=msg_id, format='full').execute()
    body = get_body_from_payload(msg.get('payload', {}))

    lines = [l.strip() for l in body.split('\n') if l.strip()]

    email = ""
    phone = ""

    for i, line in enumerate(lines):
        lower = line.lower()
        if lower.startswith('email') and i + 1 < len(lines):
            candidate = lines[i + 1]
            if re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', candidate):
                if candidate.lower() not in EXCLUDED_EMAIL_ADDRESSES:
                    email = candidate
        elif lower.startswith('phone') and i + 1 < len(lines):
            candidate = lines[i + 1]
            if re.search(r'\d', candidate):
                phone = candidate
        elif lower.startswith('city') and i + 1 < len(lines) and not city:
            city = lines[i + 1]

    if not email and not name:
        return None

    return {
        "name": name,
        "email": email,
        "phone": phone,
        "source": "UpNest",
        "source_type": "upnest",
        "lead_type": lead_type,
        "city": city,
        "notification_message_id": msg_id
    }


def parse_lead_from_notification(service, msg_id, sender, subject, category):
    """Fetch full message body and parse lead data from a notification email.

    Routes to source-specific parsers for known formats, falls back to
    generic label-based parsing for others.

    Returns a lead dict or None if lead data could not be extracted.
    """
    # Source-specific parsers (handle non-standard formats)
    if category == "crexi":
        return parse_crexi_lead(service, msg_id, sender, subject)
    if category == "social_connect":
        return parse_social_connect_lead(service, msg_id, sender, subject)
    if category == "upnest":
        return parse_upnest_lead(service, msg_id, sender, subject)

    # Generic parsing for label-based formats (Realtor.com, Seller Hub, BizBuySell, LoopNet)
    msg = service.users().messages().get(userId='me', id=msg_id, format='full').execute()
    body = get_body_from_payload(msg.get('payload', {}))

    if category == "loopnet":
        source = "LoopNet"
        source_type = "loopnet"
    elif category == "realtor_com":
        source = "Realtor.com"
        source_type = "realtor_com"
    elif category == "seller_hub":
        source = "Seller Hub"
        source_type = "seller_hub"
    elif category == "bizbuysell":
        source = "BizBuySell"
        source_type = "bizbuysell"
    else:
        return None

    email = parse_email_field(body)
    name = parse_name_field(body, subject)
    phone = parse_phone_field(body)
    property_name = parse_property_name(subject, body, category)

    # Extract property_address for residential sources where property_name
    # is actually a street address (Seller Hub body, Realtor.com subject)
    property_address = ""
    if category == "seller_hub":
        # Seller Hub: "Property Address: 123 Main St, City, MI 48103"
        m = re.search(r'(?:property\s*address|address)\s*[:\-]\s*(.+?)(?:\n|$)', body, re.IGNORECASE)
        if m:
            property_address = m.group(1).strip()
    elif category == "realtor_com":
        # Realtor.com: property_name from subject is already an address
        # e.g. "New realtor.com lead: 123 Main St, City, MI 48103"
        if property_name:
            property_address = property_name

    # Need at least an email or name to create a lead
    if not email and not name:
        return None

    result = {
        "name": name,
        "email": email,
        "phone": phone,
        "source": source,
        "source_type": source_type,
        "property_name": property_name,
        "notification_message_id": msg_id
    }
    if property_address:
        result["property_address"] = property_address
    return result


# ============================================================
# SENT path helpers
# ============================================================
# Gmail strips X-Lead-Intake-* headers when drafts are sent.
# Instead, we match sent emails to signals by thread_id, which is
# preserved and stored in the signal's draft_id_map by Module E.

def find_and_update_signal_by_thread(thread_id):
    """Find pending signal where draft_id_map contains a draft with matching thread_id.

    Returns signal info + matched draft_id, or None if no match.
    """
    conn = get_pg_conn()
    cur = conn.cursor()
    # Search through draft_id_map values for matching thread_id
    cur.execute("""
        UPDATE public.jake_signals
        SET status = 'acted', acted_by = 'gmail_pubsub', acted_at = NOW()
        WHERE status = 'pending'
          AND source_flow IN ('lead_intake', 'lead_conversation')
          AND id = (
            SELECT s.id FROM public.jake_signals s,
            jsonb_each(s.detail->'draft_id_map') AS kv
            WHERE s.status = 'pending'
              AND s.source_flow IN ('lead_intake', 'lead_conversation')
              AND kv.value->>'thread_id' = %s
            LIMIT 1
          )
        RETURNING id, resume_url, detail
    """, (thread_id,))
    row = cur.fetchone()
    conn.commit()
    cur.close()
    conn.close()
    if row:
        # Find the matched draft_id from the map
        detail = row[2]
        draft_id_map = detail.get('draft_id_map', {}) if detail else {}
        matched_draft_id = ''
        for did, info in draft_id_map.items():
            if isinstance(info, dict) and info.get('thread_id') == thread_id:
                matched_draft_id = did
                break
        return {
            "signal_id": row[0],
            "resume_url": row[1],
            "detail": detail,
            "matched_draft_id": matched_draft_id
        }
    return None


# ============================================================
# Reply detection helpers (Lead Conversation Engine)
# ============================================================

def find_outreach_by_thread(thread_id):
    """Check if thread_id matches any ACTED lead_intake signal (our sent outreach).

    Used to detect when a lead replies to an email we sent.
    Returns outreach context if match found, None otherwise.
    """
    conn = get_pg_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT s.id, s.detail
        FROM public.jake_signals s,
             jsonb_each(s.detail->'draft_id_map') AS kv
        WHERE s.status = 'acted'
          AND s.source_flow IN ('lead_intake', 'lead_conversation')
          AND kv.value->>'thread_id' = %s
        ORDER BY s.acted_at DESC
        LIMIT 1
    """, (thread_id,))
    row = cur.fetchone()
    cur.close()
    conn.close()

    if not row:
        return None

    signal_id = row[0]
    detail = row[1] if row[1] else {}
    draft_id_map = detail.get('draft_id_map', {})

    # Find the matched draft info
    matched_email = ''
    for did, info in draft_id_map.items():
        if isinstance(info, dict) and info.get('thread_id') == thread_id:
            matched_email = info.get('email', '')
            break

    # Get full draft data from detail
    drafts = detail.get('drafts', [])
    matched_draft = None
    for draft in drafts:
        if draft.get('email', '').lower() == matched_email.lower():
            matched_draft = draft
            break

    if not matched_draft and drafts:
        # Fallback: use first draft if email match fails
        matched_draft = drafts[0]
        matched_email = matched_draft.get('email', '')

    if not matched_draft:
        return None

    return {
        "signal_id": signal_id,
        "lead_email": matched_email,
        "lead_name": matched_draft.get("name", ""),
        "lead_phone": matched_draft.get("phone", ""),
        "source": matched_draft.get("source", ""),
        "source_type": matched_draft.get("source_type", ""),
        "wiseagent_client_id": matched_draft.get("wiseagent_client_id"),
        "has_nda": matched_draft.get("has_nda", False),
        "properties": matched_draft.get("properties", []),
        "template_used": matched_draft.get("template_used", ""),
        "lead_type": matched_draft.get("lead_type", "")
    }


def trigger_lead_conversation(reply_data):
    """Trigger the lead_conversation flow with reply context."""
    token = wmill.get_variable("f/switchboard/router_token")
    response = requests.post(
        f"{WM_API_BASE}/api/w/rrg/jobs/run/f/f/switchboard/lead_conversation",
        json=reply_data,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        timeout=30
    )
    return {"status_code": response.status_code, "response": response.text[:500] if response.text else ""}


def trigger_resume(resume_url, signal_id, draft_id):
    """Call Windmill resume URL to trigger Module F."""
    token = wmill.get_variable("f/switchboard/router_token")
    payload = {
        "signal_id": signal_id,
        "action": "email_sent",
        "acted_by": "gmail_pubsub",
        "draft_id": draft_id,
        "sent_at": datetime.now(timezone.utc).isoformat()
    }
    response = requests.post(
        resume_url,
        json=payload,
        headers={"Authorization": f"Bearer {token}"},
        timeout=30
    )
    return {"status_code": response.status_code, "response": response.text[:500] if response.text else ""}


# ============================================================
# Lead intake trigger
# ============================================================

def trigger_lead_intake(leads_batch):
    """Trigger the lead_intake flow with parsed leads."""
    token = wmill.get_variable("f/switchboard/router_token")
    response = requests.post(
        f"{WM_API_BASE}/api/w/rrg/jobs/run/f/f/switchboard/lead_intake",
        json={"leads": leads_batch},
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        timeout=30
    )
    return {"status_code": response.status_code, "response": response.text[:500] if response.text else ""}


# ============================================================
# Main
# ============================================================

def main(message: dict = None):
    """
    Handle Gmail Pub/Sub push notification.

    Pub/Sub delivers: {"message": {"data": "<base64>", "messageId": "...", "publishTime": "..."}}
    The data contains: {"emailAddress": "...", "historyId": "..."}

    Split inbox architecture:
    - leads@resourcerealtygroupmi.com: receives lead notifications → categorize, parse, trigger intake
    - teamgotcher@gmail.com: sends drafts, receives replies → SENT detection, reply detection

    HOPPER ARCHITECTURE: Groups leads by email, fires one flow per person.

    DEDUP: Before triggering intake, claims notification_message_ids in Postgres.
    Only leads with newly claimed IDs proceed. This prevents duplicate drafts
    when multiple Pub/Sub pushes overlap on the same history range.
    """
    sent_processed = []
    inbox_processed = []
    leads_batch = []
    replies_triggered = []
    errors = []

    # Handle both direct dict and nested message format
    if message and 'message' in message:
        message = message['message']

    if not message or 'data' not in message:
        return {"error": "No message data", "processed": 0}

    # 1. Decode Pub/Sub message
    try:
        data = json.loads(base64.urlsafe_b64decode(message['data']).decode())
    except Exception as e:
        return {"error": f"Failed to decode message: {str(e)}", "processed": 0}

    new_history_id = str(data.get('historyId', ''))
    email_address = data.get('emailAddress')

    # 2. Detect which account this notification is for
    source_account = detect_account(email_address)
    config = ACCOUNT_CONFIG[source_account]

    # 3. Get last processed history ID for this account
    try:
        last_history = wmill.get_variable(config["history_variable"])
        last_history = str(last_history) if last_history else "0"
    except Exception:
        last_history = "0"

    if last_history == "0":
        # First run — just store the history ID and return
        wmill.set_variable(config["history_variable"], new_history_id)
        return {
            "first_run": True,
            "account": source_account,
            "history_id_stored": new_history_id,
            "processed": 0
        }

    # 4. Skip stale retried messages (Pub/Sub redelivers old messages with old historyIds)
    try:
        if int(new_history_id) <= int(last_history):
            return {
                "skipped": True,
                "reason": "stale_history_id",
                "account": source_account,
                "message_history_id": new_history_id,
                "current_cursor": last_history
            }
    except (ValueError, TypeError):
        pass  # Non-numeric IDs — proceed normally

    # 5. Get Gmail service for the source account and fetch history
    service = get_gmail_service(config["oauth_resource"])

    try:
        history = service.users().history().list(
            userId='me',
            startHistoryId=last_history,
            historyTypes=['messageAdded']
        ).execute()
    except Exception as e:
        if 'notFound' in str(e) or '404' in str(e):
            wmill.set_variable(config["history_variable"], new_history_id)
            return {
                "error": "History expired, reset to current",
                "account": source_account,
                "new_history_id": new_history_id
            }
        raise

    # 6. Process each new message
    for record in history.get('history', []):
        for msg_added in record.get('messagesAdded', []):
            msg_id = msg_added['message']['id']
            labels = msg_added['message'].get('labelIds', [])

            # --- SENT path: detect lead intake drafts being sent ---
            # Only process SENT for teamgotcher@ (leads@ never sends)
            if 'SENT' in labels and config["process_sent"]:
                try:
                    msg = service.users().messages().get(
                        userId='me', id=msg_id, format='minimal'
                    ).execute()
                    thread_id = msg.get('threadId', '')

                    if thread_id:
                        signal = find_and_update_signal_by_thread(thread_id)

                        if signal:
                            try:
                                resume_result = trigger_resume(
                                    signal['resume_url'],
                                    signal['signal_id'],
                                    signal['matched_draft_id']
                                )
                                status_code = resume_result.get("status_code", 0)
                            except Exception as resume_err:
                                print(f"[C4] trigger_resume() exception: {resume_err}")
                                status_code = 0

                            # If resume failed (5xx or timeout/no response), roll back
                            # signal to pending so next webhook run retries
                            if status_code >= 500 or status_code == 0:
                                try:
                                    conn = get_pg_conn()
                                    cur = conn.cursor()
                                    cur.execute("""
                                        UPDATE public.jake_signals
                                        SET status = 'pending', acted_by = NULL, acted_at = NULL
                                        WHERE id = %s AND status = 'acted'
                                    """, (signal['signal_id'],))
                                    conn.commit()
                                    cur.close()
                                    conn.close()
                                except Exception as e:
                                    print(f"[C4] Signal rollback failed: {e}")
                                raise RuntimeError(
                                    f"Resume failed with status {status_code} for signal {signal['signal_id']}"
                                )

                            sent_processed.append({
                                "thread_id": thread_id,
                                "draft_id": signal['matched_draft_id'],
                                "signal_id": signal['signal_id'],
                                "resume_status": resume_result['status_code']
                            })

                except Exception as e:
                    errors.append({"message_id": msg_id, "path": "SENT", "error": str(e)})

            # --- INBOX path: categorize, label, parse leads, detect replies ---
            elif 'INBOX' in labels:
                try:
                    # Fetch sender + subject (metadata only, fast)
                    msg = service.users().messages().get(
                        userId='me',
                        id=msg_id,
                        format='metadata',
                        metadataHeaders=['From', 'Subject']
                    ).execute()

                    hdrs = {h['name'].lower(): h['value']
                            for h in msg.get('payload', {}).get('headers', [])}
                    sender = hdrs.get('from', '')
                    subject = hdrs.get('subject', '')

                    # Skip BCC copies of our own outbound emails (leads@ receives
                    # BCC copies from teamgotcher@ drafts — not new leads)
                    if source_account == 'leads' and 'teamgotcher@gmail.com' in sender.lower():
                        continue

                    # Categorize
                    category, label_name = categorize_email(sender, subject)

                    entry = {
                        "message_id": msg_id,
                        "account": source_account,
                        "category": category,
                        "label": label_name,
                        "subject": subject[:80]
                    }

                    # --- Lead notification processing (leads@ account only) ---
                    if category in LEAD_CATEGORIES and config["process_inbox_leads"]:
                        lead = parse_lead_from_notification(
                            service, msg_id, sender, subject, category
                        )

                        # BUG 7B+C: Validate parsed lead before accepting
                        if lead:
                            is_valid, issues = validate_lead(lead)
                            if is_valid:
                                leads_batch.append(lead)
                                entry["lead_parsed"] = True
                                entry["lead_email"] = lead.get("email", "")
                            else:
                                # Validation failed — downgrade to Unlabeled
                                apply_label(service, msg_id, "Unlabeled", remove_labels=[label_name])
                                entry["lead_parsed"] = False
                                entry["downgraded_to_unlabeled"] = True
                                entry["original_category"] = category
                                entry["validation_issues"] = issues
                        else:
                            # Parsing failed — downgrade to Unlabeled
                            apply_label(service, msg_id, "Unlabeled", remove_labels=[label_name])
                            entry["lead_parsed"] = False
                            entry["downgraded_to_unlabeled"] = True
                            entry["original_category"] = category

                    # --- Reply detection (teamgotcher@ account only) ---
                    elif category == "unlabeled" and config["process_inbox_replies"]:
                        thread_id = msg.get('threadId', '')
                        outreach = find_outreach_by_thread(thread_id) if thread_id else None

                        if outreach:
                            # Reply to our outreach detected!
                            apply_label(service, msg_id, "Lead Reply", remove_labels=["Unlabeled"])

                            # Fetch full reply body for the conversation flow
                            reply_msg = service.users().messages().get(
                                userId='me', id=msg_id, format='full'
                            ).execute()
                            reply_body = get_body_from_payload(reply_msg.get('payload', {}))

                            reply_data = {
                                "thread_id": thread_id,
                                "message_id": msg_id,
                                "reply_body": reply_body,
                                "reply_subject": subject,
                                "reply_from": sender,
                                **outreach
                            }

                            try:
                                conv_result = trigger_lead_conversation(reply_data)
                                entry["is_lead_reply"] = True
                                entry["original_signal_id"] = outreach["signal_id"]
                                entry["conversation_trigger_status"] = conv_result.get("status_code")
                                replies_triggered.append({
                                    "thread_id": thread_id,
                                    "lead_email": outreach["lead_email"],
                                    "trigger_status": conv_result.get("status_code")
                                })
                            except Exception as e:
                                entry["is_lead_reply"] = True
                                entry["conversation_trigger_error"] = str(e)
                                errors.append({"message_id": msg_id, "path": "INBOX_REPLY", "error": str(e)})
                        else:
                            # Not a reply to our outreach — apply Unlabeled
                            apply_label(service, msg_id, "Unlabeled")

                    elif category == "unlabeled":
                        # Unlabeled on leads@ — just label it
                        apply_label(service, msg_id, "Unlabeled")

                    else:
                        # Known category but wrong account, or non-lead category — apply label
                        if category in LEAD_CATEGORIES and not config["process_inbox_leads"]:
                            # Lead notification landed in teamgotcher@ (shouldn't happen with split inbox)
                            apply_label(service, msg_id, label_name, remove_labels=["Unlabeled"])
                            entry["skipped_wrong_account"] = True
                        else:
                            apply_label(service, msg_id, label_name, remove_labels=["Unlabeled"])

                    # Apply source label for successfully parsed leads
                    if category in LEAD_CATEGORIES and entry.get("lead_parsed"):
                        remove = ["Unlabeled"] if category != "unlabeled" else []
                        apply_label(service, msg_id, label_name, remove)

                    inbox_processed.append(entry)

                except Exception as e:
                    errors.append({"message_id": msg_id, "path": "INBOX", "error": str(e)})

    # 7. DEDUP: Claim notification_message_ids before triggering intake
    # Only leads whose message_ids are newly claimed will be processed.
    # This prevents duplicate intake triggers from overlapping Pub/Sub pushes.
    deduped_batch = []
    dedup_skipped = 0

    if leads_batch:
        all_msg_ids = [lead["notification_message_id"] for lead in leads_batch]
        claimed_ids = claim_message_ids(all_msg_ids, source_account, "lead")

        for lead in leads_batch:
            if lead["notification_message_id"] in claimed_ids:
                deduped_batch.append(lead)
            else:
                dedup_skipped += 1

    # 8. Stage leads + schedule delayed processing
    # Instead of triggering intake immediately, write leads to staged_leads table
    # and schedule a one-shot delayed job per unique email. The delayed job collects
    # all notifications that arrived during the batch window (BATCH_DELAY_SECONDS)
    # and fires one intake flow per person with all their properties combined.
    staged_ids = []
    schedule_results = []

    if deduped_batch:
        # Stage all deduped leads
        staged_ids = stage_leads(deduped_batch)

        # Schedule delayed processing for each unique email (only first call per email schedules)
        unique_emails = list({lead.get("email", "").strip().lower() for lead in deduped_batch if lead.get("email")})
        for email in unique_emails:
            try:
                result = schedule_delayed_processing(email)
                schedule_results.append({"email": email, **result})
            except Exception as e:
                schedule_results.append({"email": email, "error": str(e)})

    # 9. Update last history ID
    # Always advance — staging never fails in a way that should block progress
    try:
        if int(new_history_id) > int(last_history):
            wmill.set_variable(config["history_variable"], new_history_id)
    except (ValueError, TypeError):
        wmill.set_variable(config["history_variable"], new_history_id)

    return {
        "account": source_account,
        "email_address": email_address,
        "sent_processed": len(sent_processed),
        "inbox_processed": len(inbox_processed),
        "leads_found": len(leads_batch),
        "leads_after_dedup": len(deduped_batch),
        "dedup_skipped": dedup_skipped,
        "leads_staged": len(staged_ids),
        "replies_triggered": len(replies_triggered),
        "sent_emails": sent_processed if sent_processed else None,
        "inbox_emails": inbox_processed if inbox_processed else None,
        "leads_batch": deduped_batch if deduped_batch else None,
        "schedule_results": schedule_results if schedule_results else None,
        "reply_triggers": replies_triggered if replies_triggered else None,
        "errors": errors if errors else None,
        "history_id": new_history_id,
        "history_id_advanced": True
    }
