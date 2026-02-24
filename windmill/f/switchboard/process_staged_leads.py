# Process Staged Leads — Delayed batch processor
# Path: f/switchboard/process_staged_leads
#
# Called by gmail_pubsub_webhook via a delayed one-shot job (scheduled_for = now + BATCH_DELAY).
# Reads all unprocessed staged_leads for a given email, deduplicates properties,
# fires one lead_intake flow, and marks them processed.
#
# Input: {"email": "someone@example.com"}

#extra_requirements:
#psycopg2-binary
#requests

import os
import wmill
import json
import psycopg2
import requests
from datetime import datetime, timezone

WM_API_BASE = os.environ.get('BASE_INTERNAL_URL', 'http://localhost:8000')


def get_pg_conn():
    pg = wmill.get_resource("f/switchboard/pg")
    return psycopg2.connect(
        host=pg["host"],
        port=pg.get("port", 5432),
        user=pg["user"],
        password=pg["password"],
        dbname=pg["dbname"],
        sslmode=pg.get("sslmode", "disable")
    )


def main(email: str):
    if not email:
        return {"error": "no email provided"}

    email_lower = email.strip().lower()

    # 1. Fetch all unprocessed leads for this email
    conn = get_pg_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, raw_lead
        FROM public.staged_leads
        WHERE lower(email) = %s AND NOT processed
        ORDER BY staged_at ASC
    """, (email_lower,))
    rows = cur.fetchall()

    if not rows:
        # Clean up timer even if no leads (edge case: leads were already processed by another job)
        cur.execute(
            "DELETE FROM public.processed_notifications WHERE message_id = %s",
            (f"timer:{email_lower}",)
        )
        conn.commit()
        cur.close()
        conn.close()
        return {"email": email_lower, "skipped": True, "reason": "no_unprocessed_leads"}

    # 2. Mark them as processed (claim them so a concurrent job doesn't double-process)
    row_ids = [r[0] for r in rows]
    cur.execute("""
        UPDATE public.staged_leads
        SET processed = TRUE, processed_at = NOW()
        WHERE id = ANY(%s) AND NOT processed
        RETURNING id
    """, (row_ids,))
    claimed_ids = {r[0] for r in cur.fetchall()}
    conn.commit()
    cur.close()
    conn.close()

    # Only process rows we actually claimed
    leads = []
    for row_id, raw_lead in rows:
        if row_id in claimed_ids:
            lead = json.loads(raw_lead) if isinstance(raw_lead, str) else raw_lead
            leads.append(lead)

    if not leads:
        return {"email": email_lower, "skipped": True, "reason": "all_already_processed"}

    # 3. Trigger one lead_intake flow with all leads for this person
    token = wmill.get_variable("f/switchboard/router_token")
    try:
        response = requests.post(
            f"{WM_API_BASE}/api/w/rrg/jobs/run/f/f/switchboard/lead_intake",
            json={"leads": leads},
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            timeout=30
        )
        intake_status = response.status_code
    except Exception as e:
        intake_status = f"error: {str(e)}"

    # 4. Clean up batch timer so future leads for this email can schedule new timers
    try:
        conn = get_pg_conn()
        cur = conn.cursor()
        cur.execute(
            "DELETE FROM public.processed_notifications WHERE message_id = %s",
            (f"timer:{email_lower}",)
        )
        conn.commit()
        cur.close()
        conn.close()
    except Exception:
        pass  # Non-critical — timer will expire after 7 days anyway

    return {
        "email": email_lower,
        "leads_count": len(leads),
        "properties": list({l.get("property_name", "") for l in leads if l.get("property_name")}),
        "intake_status": intake_status,
        "staged_ids_processed": list(claimed_ids)
    }
