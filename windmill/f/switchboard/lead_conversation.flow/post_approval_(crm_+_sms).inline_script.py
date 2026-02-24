# Module D: Post-Approval — CRM note + SMS after user action
# Part of f/switchboard/lead_conversation flow
#
# Handles both email_sent and draft_deleted paths.
# Same pattern as lead_intake Module F.

#extra_requirements:
#requests
#psycopg2-binary

import wmill
import requests
import json
import re
from datetime import datetime, timezone

BASE_URL = "https://sync.thewiseagent.com/http/webconnect.asp"
TOKEN_URL = "https://sync.thewiseagent.com/WiseAuth/token"


def get_wa_token(oauth):
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


def mark_signal_acted(signal_id, acted_by):
    """Mark signal as acted in jake_signals."""
    try:
        import psycopg2
        pg = wmill.get_resource("f/switchboard/pg")
        conn = psycopg2.connect(
            host=pg["host"], port=pg.get("port", 5432),
            user=pg["user"], password=pg["password"],
            dbname=pg["dbname"], sslmode=pg.get("sslmode", "disable")
        )
        cur = conn.cursor()
        cur.execute("""
            UPDATE public.jake_signals
            SET status = 'acted', acted_by = %s, acted_at = NOW()
            WHERE id = %s AND status = 'pending'
        """, (acted_by, signal_id))
        conn.commit()
        cur.close()
        conn.close()
    except Exception:
        pass


def main(resume_payload: dict, response_data: dict):
    """Handle post-approval actions for lead conversation replies."""

    # Handle rejection/timeout
    if isinstance(resume_payload, dict) and "error" in resume_payload:
        return {
            "status": "rejected",
            "reason": resume_payload.get("error", "disapproved or timed out"),
            "sms_sent": False
        }

    drafts = response_data.get("drafts", [])
    if not drafts:
        return {"status": "no_drafts", "sms_sent": False}

    action = resume_payload.get("action", "")
    draft_id = resume_payload.get("draft_id", "")

    # Mark signal as acted
    signal_id = resume_payload.get("signal_id")
    if signal_id:
        mark_signal_acted(signal_id, resume_payload.get("acted_by", "module_d"))

    # ===== DRAFT DELETED PATH =====
    if action == "draft_deleted":
        deleted_at = resume_payload.get("deleted_at", "")
        oauth = wmill.get_resource("f/switchboard/wiseagent_oauth")
        token = get_wa_token(oauth)

        for draft in drafts:
            client_id = draft.get("wiseagent_client_id")
            props = draft.get("properties", [])
            prop_names = ", ".join(p.get("canonical_name", "") for p in props if p.get("canonical_name"))
            response_type = draft.get("response_type", "")

            if client_id:
                try:
                    requests.post(
                        BASE_URL + "?requestType=addContactNote",
                        data={
                            "clientids": str(client_id),
                            "note": f"Reply draft deleted (rejected) on {deleted_at}. Response type: {response_type}. Property: {prop_names}.",
                            "subject": f"Reply Rejected - {prop_names[:50]}"
                        },
                        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/x-www-form-urlencoded"},
                        timeout=15
                    )
                except Exception:
                    pass

        return {
            "status": "rejected",
            "action": "draft_deleted",
            "deleted_at": deleted_at,
            "sms_sent": False
        }

    # ===== EMAIL SENT PATH =====
    if action == "email_sent":
        sent_at = resume_payload.get("sent_at", "")
        oauth = wmill.get_resource("f/switchboard/wiseagent_oauth")
        token = get_wa_token(oauth)
        today = datetime.now().strftime("%Y-%m-%d")

        # SMS first (so we know outcome for CRM note)
        SMS_GATEWAY_URL = wmill.get_variable("f/switchboard/sms_gateway_url")
        sms_results = []

        for draft in drafts:
            sms_body = draft.get("sms_body")
            phone = draft.get("phone", "")

            if not sms_body or not phone:
                sms_results.append({"sms_sent": False, "reason": "no_phone_or_body"})
                continue

            clean_phone = re.sub(r'[^0-9]', '', phone)
            if len(clean_phone) == 10:
                phone_e164 = f"+1{clean_phone}"
            elif len(clean_phone) == 11 and clean_phone.startswith("1"):
                phone_e164 = f"+{clean_phone}"
            else:
                phone_e164 = phone

            try:
                sms_resp = requests.post(
                    SMS_GATEWAY_URL,
                    json={"phone": phone_e164, "message": sms_body},
                    timeout=30
                )
                sms_data = sms_resp.json()
                sms_results.append({
                    "phone": phone_e164,
                    "sms_sent": sms_data.get("success", False),
                    "error": sms_data.get("error") if not sms_data.get("success") else None
                })
            except Exception as e:
                sms_results.append({"phone": phone_e164, "sms_sent": False, "error": str(e)})

        # CRM notes with accurate SMS outcome
        for i, draft in enumerate(drafts):
            client_id = draft.get("wiseagent_client_id")
            props = draft.get("properties", [])
            prop_names = ", ".join(p.get("canonical_name", "") for p in props if p.get("canonical_name"))
            response_type = draft.get("response_type", "")
            classification = draft.get("classification", "")

            if not client_id:
                continue

            note_text = f"Reply sent on {today}. Type: {response_type} (classification: {classification}). Property: {prop_names}."
            sms = sms_results[i] if i < len(sms_results) else {}
            if sms.get("sms_sent"):
                note_text += f" SMS notification sent to {sms.get('phone', '')}."
            elif sms.get("reason") == "no_phone_or_body":
                note_text += " No phone — SMS not sent."
            else:
                note_text += " SMS attempted but failed."

            try:
                requests.post(
                    BASE_URL + "?requestType=addContactNote",
                    data={
                        "clientids": str(client_id),
                        "note": note_text,
                        "subject": f"Reply Sent - {prop_names[:50]}"
                    },
                    headers={"Authorization": f"Bearer {token}", "Content-Type": "application/x-www-form-urlencoded"},
                    timeout=15
                )
            except Exception:
                pass

        sms_sent_count = sum(1 for r in sms_results if r.get("sms_sent"))

        return {
            "status": "approved",
            "action": "email_sent",
            "sent_at": sent_at,
            "sms_sent": sms_sent_count > 0,
            "sms_sent_count": sms_sent_count,
            "sms_results": sms_results
        }

    return {
        "status": "error",
        "reason": f"Unknown action: {action}",
        "sms_sent": False
    }
