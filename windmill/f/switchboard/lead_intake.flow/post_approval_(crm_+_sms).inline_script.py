#extra_requirements:
#requests
#psycopg2-binary

import wmill
import requests
import json
import re
import time
import psycopg2
from datetime import datetime, timezone

BASE_URL = "https://sync.thewiseagent.com/http/webconnect.asp"
TOKEN_URL = "https://sync.thewiseagent.com/WiseAuth/token"


def wa_post(token, request_type, data):
    """Make a WiseAgent API call."""
    resp = requests.post(
        BASE_URL + f"?requestType={request_type}",
        data=data,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/x-www-form-urlencoded"},
        timeout=15
    )
    resp.raise_for_status()
    return resp


def get_token(oauth):
    expires_at = oauth.get("expires_at", "")
    if expires_at:
        try:
            exp = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
            if datetime.now(timezone.utc) < exp.replace(tzinfo=timezone.utc):
                return oauth["access_token"]
        except Exception:
            pass
    resp = requests.post(TOKEN_URL, json={"grant_type": "refresh_token", "refresh_token": oauth["refresh_token"], "client_id": oauth.get("client_id", ""), "client_secret": oauth.get("client_secret", "")})
    resp.raise_for_status()
    new_tokens = resp.json()
    oauth["access_token"] = new_tokens["access_token"]
    oauth["refresh_token"] = new_tokens.get("refresh_token", oauth["refresh_token"])
    oauth["expires_at"] = new_tokens.get("expires_at", "")
    # Save token BEFORE returning — retry up to 3 times
    save_ok = False
    for attempt in range(3):
        try:
            wmill.set_resource(oauth, "f/switchboard/wiseagent_oauth")
            save_ok = True
            break
        except Exception as e:
            print(f"[WiseAgent OAuth] wmill.set_resource failed (attempt {attempt + 1}/3): {e}")
            if attempt < 2:
                time.sleep(1.5)
    if not save_ok:
        # Last resort: backup to Postgres
        print("[WiseAgent OAuth] All 3 save attempts failed — writing backup to Postgres")
        try:
            pg = wmill.get_resource("f/switchboard/pg")
            conn = psycopg2.connect(
                host=pg["host"], port=pg.get("port", 5432),
                user=pg["user"], password=pg["password"],
                dbname=pg["dbname"], sslmode=pg.get("sslmode", "disable")
            )
            try:
                cur = conn.cursor()
                cur.execute("""
                    INSERT INTO public.oauth_token_backup (service, token_data, saved_at)
                    VALUES ('wiseagent', %s::jsonb, NOW())
                    ON CONFLICT (service) DO UPDATE SET token_data = EXCLUDED.token_data, saved_at = NOW()
                """, (json.dumps(oauth),))
                conn.commit()
                cur.close()
                print("[WiseAgent OAuth] Postgres backup saved successfully")
            finally:
                conn.close()
        except Exception as backup_err:
            print(f"[WiseAgent OAuth] CRITICAL — Postgres backup also failed: {backup_err}")
    return oauth["access_token"]


def mark_signal_acted(signal_id, acted_by):
    """Mark signal as acted in jake_signals (BUG 2 fix — both branches)."""
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
        pass  # Non-critical — signal may already be acted


def main(resume_payload: dict, draft_data: dict):
    if isinstance(resume_payload, dict) and "error" in resume_payload:
        return {
            "status": "rejected",
            "reason": resume_payload.get("error", "disapproved or timed out"),
            "drafts_processed": [],
            "wiseagent_results": [],
            "sms_sent": False
        }

    drafts = draft_data.get("drafts", [])
    if not drafts:
        return {
            "status": "no_drafts",
            "drafts_processed": [],
            "wiseagent_results": [],
            "sms_sent": False
        }

    action = resume_payload.get("action", "")
    draft_id = resume_payload.get("draft_id", "")

    # BUG 2 fix: Mark signal as acted immediately (both branches)
    signal_id = resume_payload.get("signal_id")
    if signal_id:
        mark_signal_acted(signal_id, resume_payload.get("acted_by", "module_f"))

    # ===== DRAFT DELETED PATH (BUG 2 fix — now reachable) =====
    if action == "draft_deleted":
        deleted_at = resume_payload.get("deleted_at", "")

        # Add rejection note to EXISTING contacts (created in Module A)
        oauth = wmill.get_resource("f/switchboard/wiseagent_oauth")
        token = get_token(oauth)

        wiseagent_results = []
        for draft in drafts:
            client_id = draft.get("wiseagent_client_id")
            props = draft.get("properties", [])
            prop_names = ", ".join(p.get("canonical_name", "") for p in props if p.get("canonical_name"))

            if client_id:
                try:
                    note_data = {
                        "clientids": str(client_id),
                        "note": f"Lead rejected — draft deleted on {deleted_at}. Property: {prop_names}.",
                        "subject": f"Lead Rejected - {prop_names[:50]}"
                    }
                    wa_post(token, "addContactNote", note_data)
                    wiseagent_results.append({"email": draft.get("email"), "action": "rejection_note_added", "success": True})
                except Exception as e:
                    wiseagent_results.append({"email": draft.get("email"), "action": "rejection_note_failed", "error": str(e)})

        return {
            "status": "rejected",
            "action": "draft_deleted",
            "draft_id": draft_id,
            "deleted_at": deleted_at,
            "reason": "User deleted the draft (rejection)",
            "sms_sent": False,
            "wiseagent_results": wiseagent_results
        }

    # ===== EMAIL SENT PATH =====
    if action == "email_sent":
        sent_at = resume_payload.get("sent_at", "")
        oauth = wmill.get_resource("f/switchboard/wiseagent_oauth")
        token = get_token(oauth)
        today = datetime.now().strftime("%Y-%m-%d")

        wiseagent_results = []

        # BUG 10 fix: Run SMS loop FIRST so we know outcomes before writing CRM notes
        SMS_GATEWAY_URL = wmill.get_variable("f/switchboard/sms_gateway_url")
        sms_results = []

        for draft in drafts:
            sms_body = draft.get("sms_body")
            phone = draft.get("phone", "")

            if not sms_body or not phone:
                sms_results.append({"email": draft.get("email"), "sms_sent": False, "reason": "no_phone_or_body"})
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
                if sms_data.get("success"):
                    sms_results.append({"email": draft.get("email"), "phone": phone_e164, "sms_sent": True})
                else:
                    sms_results.append({"email": draft.get("email"), "phone": phone_e164, "sms_sent": False, "error": sms_data.get("error", "unknown")})
            except Exception as e:
                sms_results.append({"email": draft.get("email"), "phone": phone_e164, "sms_sent": False, "error": str(e)})

        # NOW write CRM notes with accurate SMS outcome (BUG 10 fix)
        for i, draft in enumerate(drafts):
            email = draft.get("email", "")
            client_id = draft.get("wiseagent_client_id")  # Always populated (Module A creates)
            props = draft.get("properties", [])
            prop_names = ", ".join(p.get("canonical_name", "") for p in props if p.get("canonical_name"))

            result = {"email": email, "actions": []}

            try:
                # Module A already created contacts — just update status to "Contacted"
                if client_id:
                    update_data = {"clientID": str(client_id), "Status": "Contacted"}
                    wa_post(token, "updateContact", update_data)
                    result["actions"].append({"action": "updated_status", "client_id": client_id})

                    # Build accurate CRM note based on actual SMS outcome
                    note_text = f"Email sent via Gmail draft on {today}. Property: {prop_names}."
                    sms = sms_results[i] if i < len(sms_results) else {}
                    if sms.get("sms_sent"):
                        note_text += f" SMS sent to {sms.get('phone', '')}."
                    elif sms.get("reason") == "no_phone_or_body":
                        note_text += " No phone number — SMS not sent."
                    else:
                        note_text += " SMS attempted but failed."

                    # Append email body to outreach note
                    email_body = draft.get("email_body", "")
                    if email_body:
                        note_text += f"\n\n--- Email Body ---\n{email_body}"

                    note_data = {
                        "clientids": str(client_id),
                        "note": note_text,
                        "subject": f"Outreach - {prop_names[:50]}"
                    }
                    wa_post(token, "addContactNote", note_data)
                    result["actions"].append({"action": "note_added"})

                    # Separate SMS note with body
                    if sms.get("sms_sent"):
                        sms_body = draft.get("sms_body", "")
                        sms_note_text = f"SMS sent to {sms.get('phone', '')} on {today}. Property: {prop_names}."
                        if sms_body:
                            sms_note_text += f"\n\n--- SMS Body ---\n{sms_body}"
                        sms_note_data = {
                            "clientids": str(client_id),
                            "note": sms_note_text,
                            "subject": f"SMS Outreach - {prop_names[:50]}"
                        }
                        wa_post(token, "addContactNote", sms_note_data)
                        result["actions"].append({"action": "sms_note_added"})

                result["success"] = True
            except Exception as e:
                result["success"] = False
                result["error"] = str(e)

            wiseagent_results.append(result)

        sms_sent_count = sum(1 for r in sms_results if r.get("sms_sent"))

        return {
            "status": "approved",
            "action": "email_sent",
            "draft_id": draft_id,
            "sent_at": sent_at,
            "drafts_processed": len(drafts),
            "sms_sent": sms_sent_count > 0,
            "sms_sent_count": sms_sent_count,
            "sms_results": sms_results,
            "wiseagent_results": wiseagent_results
        }

    return {
        "status": "error",
        "reason": f"Unknown action: {action}",
        "resume_payload": resume_payload
    }
