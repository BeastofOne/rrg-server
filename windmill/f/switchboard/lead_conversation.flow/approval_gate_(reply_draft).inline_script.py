# Module C: Approval Gate — Write signal + suspend
# Part of f/switchboard/lead_conversation flow
#
# Same pattern as lead_intake Module E.
# Creates a jake_signal with draft info, then suspends.
# Resumes when user sends or deletes the draft.
#
# stop_after_if: result.skipped == true

#extra_requirements:
#psycopg2-binary

import wmill
import psycopg2
import json


def main(response_data: dict):
    """Write approval signal and suspend flow."""
    drafts = response_data.get("drafts", [])
    classification = response_data.get("classification", "")
    sub_classification = response_data.get("sub_classification", "")
    response_type = response_data.get("response_type", "")
    lead_email = response_data.get("lead_email", "")
    lead_name = response_data.get("lead_name", "")

    if not drafts:
        return {"signal_id": None, "skipped": True, "reason": "no_drafts"}

    urls = wmill.get_resume_urls()
    resume_url = urls.get("resume", "")
    cancel_url = urls.get("cancel", "")

    # Build draft_id_map (same structure as lead_intake for SENT matching)
    draft_id_map = {}
    for i, draft in enumerate(drafts):
        draft_id = draft.get("gmail_draft_id")
        thread_id = draft.get("gmail_thread_id")
        email = draft.get("email", "")
        if draft_id:
            draft_id_map[draft_id] = {
                "email": email,
                "thread_id": thread_id,
                "draft_index": i
            }

    summary = f"Reply to {lead_name or lead_email}: {response_type} ({classification}/{sub_classification})"

    detail = {
        "drafts": drafts,
        "draft_id_map": draft_id_map,
        "classification": classification,
        "sub_classification": sub_classification,
        "response_type": response_type,
        "resume_url": resume_url,
        "cancel_url": cancel_url,
        "summary": summary
    }

    actions = ["Approve", "Reject"]

    pg = wmill.get_resource("f/switchboard/pg")
    conn = psycopg2.connect(
        host=pg["host"],
        port=pg.get("port", 5432),
        user=pg["user"],
        password=pg["password"],
        dbname=pg["dbname"],
        sslmode=pg.get("sslmode", "disable")
    )
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO public.jake_signals
        (signal_type, source_flow, summary, detail, actions, windmill_job_id, resume_url, cancel_url, status)
        VALUES (%s, %s, %s, %s::jsonb, %s::jsonb, %s, %s, %s, 'pending')
        RETURNING id, created_at
    """, (
        "approval_needed",
        "lead_conversation",
        summary,
        json.dumps(detail),
        json.dumps(actions),
        "",
        resume_url,
        cancel_url
    ))

    row = cur.fetchone()
    conn.commit()
    cur.close()
    conn.close()

    return {
        "signal_id": row[0],
        "created_at": str(row[1]),
        "resume_url": resume_url,
        "cancel_url": cancel_url,
        "draft_count": len(draft_id_map),
        "skipped": False
    }
