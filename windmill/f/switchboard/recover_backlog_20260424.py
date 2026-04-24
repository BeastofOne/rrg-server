# Backlog Recovery — One-shot script (delete after backlog processed)
# Path: f/switchboard/recover_backlog_20260424
#
# Recovers leads missed during the April 16 → April 24, 2026 outage where
# the leads@ Gmail watch expired and no webhook pushes fired.
#
# Reuses the production webhook's own parsing + staging functions so the
# output is identical to what Pub/Sub would have produced.
#
# Usage:
#   dry_run=true  → list candidate messages, no side effects
#   dry_run=false → parse + stage + trigger lead_intake per unique email

#extra_requirements:
#psycopg2-binary
#google-api-python-client
#google-auth
#requests

import os
import wmill
import psycopg2
import requests
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials

# Import the webhook's own helpers — keeps parsing identical to production
from f.switchboard.gmail_pubsub_webhook import (  # type: ignore
    categorize_email,
    parse_lead_from_notification,
    validate_lead,
    stage_leads,
    schedule_delayed_processing,
    apply_label,
    LEAD_CATEGORIES,
)

# Start window: last successful leads@ webhook was 2026-04-16 04:46 UTC.
# Use 2026-04-16 00:00 UTC (= 1776297600) for a small lookback buffer —
# dedup via staged_leads.notification_message_id skips anything already
# staged, so widening the window is safe but slightly wasteful on API calls.
AFTER_EPOCH = 1776297600


def _get_leads_service():
    oauth = wmill.get_resource("f/switchboard/gmail_leads_oauth")
    creds = Credentials(
        token=oauth["access_token"],
        refresh_token=oauth["refresh_token"],
        token_uri="https://oauth2.googleapis.com/token",
        client_id=oauth["client_id"],
        client_secret=oauth["client_secret"],
    )
    return build("gmail", "v1", credentials=creds)


def _list_inbox_messages(service):
    """Page through all INBOX messages after AFTER_EPOCH."""
    query = f"in:inbox after:{AFTER_EPOCH}"
    out = []
    token = None
    while True:
        resp = service.users().messages().list(
            userId="me", q=query, maxResults=500, pageToken=token,
        ).execute()
        out.extend(resp.get("messages", []))
        token = resp.get("nextPageToken")
        if not token:
            break
    return out


def _already_staged(message_ids):
    if not message_ids:
        return set()
    pg = wmill.get_resource("f/switchboard/pg")
    conn = psycopg2.connect(
        host=pg["host"], port=pg.get("port", 5432), dbname=pg["dbname"],
        user=pg["user"], password=pg["password"], sslmode=pg.get("sslmode", "disable"),
    )
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT notification_message_id FROM staged_leads "
                "WHERE notification_message_id = ANY(%s)",
                (list(message_ids),),
            )
            return {row[0] for row in cur.fetchall()}
    finally:
        conn.close()


def main(dry_run: bool = True):
    service = _get_leads_service()
    raw = _list_inbox_messages(service)

    # Enumerate + categorize
    candidates = []
    for m in raw:
        msg = service.users().messages().get(
            userId="me", id=m["id"], format="metadata",
            metadataHeaders=["From", "Subject", "Date"],
        ).execute()
        headers = {h["name"]: h["value"] for h in msg.get("payload", {}).get("headers", [])}
        sender = headers.get("From", "")
        subject = headers.get("Subject", "")
        # categorize_email returns (category_key, gmail_label); "unlabeled" for non-leads
        cat_key, label_name = categorize_email(sender, subject)
        if cat_key not in LEAD_CATEGORIES:
            continue
        candidates.append({
            "message_id": m["id"],
            "from": sender,
            "subject": subject,
            "date": headers.get("Date", ""),
            "category": cat_key,
            "label_name": label_name,
        })

    # Filter out already-staged
    staged_ids = _already_staged(c["message_id"] for c in candidates)
    missed = [c for c in candidates if c["message_id"] not in staged_ids]

    result = {
        "dry_run": dry_run,
        "window_start_utc": "2026-04-16T00:00:00Z",
        "total_inbox_messages_in_window": len(raw),
        "total_lead_candidates": len(candidates),
        "already_staged_skipped": len(candidates) - len(missed),
        "missed_count": len(missed),
        "by_category": {},
    }
    for c in missed:
        result["by_category"][c["category"]] = result["by_category"].get(c["category"], 0) + 1

    # Parse + validate each missed candidate. In dry-run this preview lets Jake
    # see exactly how many will be staged vs skipped before any writes. Both
    # parse_lead_from_notification and validate_lead are read-only.
    processed = []
    emails_to_process = set()
    for c in missed:
        outcome = {
            "message_id": c["message_id"],
            "category": c["category"],
            "subject": c["subject"],
            "from": c["from"],
        }
        try:
            lead = parse_lead_from_notification(
                service, c["message_id"], c["from"], c["subject"], c["category"],
            )
            # parse_lead_from_notification returns dict | None (never list).
            # None on messages that don't yield extractable lead data (e.g. upnest_info).
            if not lead:
                outcome["disposition"] = "would_skip_parser_none"
            else:
                is_valid, issues = validate_lead(lead)
                if not is_valid:
                    outcome["disposition"] = "would_skip_validation_failed"
                    outcome["validation_issues"] = issues
                else:
                    outcome["disposition"] = "would_stage"
                    outcome["lead_email"] = lead.get("email", "")
                    outcome["lead_name"] = lead.get("name", "")
        except Exception as e:
            outcome["disposition"] = "would_error"
            outcome["error"] = str(e)[:200]
            lead = None

        processed.append(outcome)

        # Wet-run side effects — mirror production webhook's labeling +
        # staging + delayed-processing logic byte-for-byte.
        if not dry_run:
            label_name = c["label_name"]
            try:
                if outcome["disposition"] == "would_stage":
                    lead.setdefault("notification_message_id", c["message_id"])
                    ids = stage_leads([lead])
                    outcome["staged_ids"] = ids
                    # Production: apply source label on success (remove Unlabeled)
                    apply_label(service, c["message_id"], label_name, remove_labels=["Unlabeled"])
                    email = (lead.get("email") or "").strip().lower()
                    if email:
                        emails_to_process.add(email)
                elif outcome["disposition"] in ("would_skip_parser_none", "would_skip_validation_failed"):
                    # Production: downgrade to Unlabeled + remove source label
                    apply_label(service, c["message_id"], "Unlabeled", remove_labels=[label_name])
            except Exception as e:
                outcome["wet_run_error"] = str(e)[:200]

    # Aggregate preview counts
    disposition_counts = {}
    for o in processed:
        d = o["disposition"]
        disposition_counts[d] = disposition_counts.get(d, 0) + 1
    result["dispositions"] = disposition_counts

    if dry_run:
        result["preview"] = processed
        return result

    # Trigger delayed processing once per unique email
    triggered = []
    for email in sorted(emails_to_process):
        try:
            schedule_delayed_processing(email)
            triggered.append({"email": email, "scheduled": True})
        except Exception as e:
            triggered.append({"email": email, "error": str(e)[:200]})

    result["processed"] = processed
    result["triggered"] = triggered
    result["unique_emails"] = len(emails_to_process)
    return result
