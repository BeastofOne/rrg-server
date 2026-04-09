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
    new_tokens = json.loads(resp.text, strict=False)
    oauth["access_token"] = new_tokens["access_token"]
    oauth["refresh_token"] = new_tokens.get("refresh_token", oauth["refresh_token"])
    oauth["expires_at"] = new_tokens.get("expires_at", "")
    # Save token BEFORE returning — retry up to 3 times
    save_ok = False
    for attempt in range(3):
        try:
            wmill.set_resource("f/switchboard/wiseagent_oauth", oauth)
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
    """Mark signal as acted in jake_signals."""
    import psycopg2
    pg = wmill.get_resource("f/switchboard/pg")
    conn = psycopg2.connect(
        host=pg["host"], port=pg.get("port", 5432),
        user=pg["user"], password=pg["password"],
        dbname=pg["dbname"], sslmode=pg.get("sslmode", "disable")
    )
    try:
        cur = conn.cursor()
        cur.execute("""
            UPDATE public.jake_signals
            SET status = 'acted', acted_by = %s, acted_at = NOW()
            WHERE id = %s AND status = 'pending'
        """, (acted_by, signal_id))
        conn.commit()
        cur.close()
    finally:
        conn.close()


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
                    wa_post(token, "addContactNote", {
                        "clientids": str(client_id),
                        "note": f"Reply draft deleted (rejected) on {deleted_at}. Response type: {response_type}. Property: {prop_names}.",
                        "subject": f"Reply Rejected - {prop_names[:50]}"
                    })
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
        SMS_GATEWAY_COMMERCIAL = wmill.get_variable("f/switchboard/sms_gateway_url")
        SMS_GATEWAY_RESIDENTIAL = wmill.get_variable("f/switchboard/sms_gateway_url_residential") or ""
        SMS_RESIDENTIAL_PASSWORD = wmill.get_variable("f/switchboard/sms_gateway_residential_password") if SMS_GATEWAY_RESIDENTIAL else ""
        # Keep in sync with lead_intake.flow/post_approval
        RESIDENTIAL_SOURCES = {"realtor_com", "seller_hub", "social_connect", "upnest"}
        sms_results = []

        def send_sms_commercial(url, phone_e164, body):
            """Pixel 9a — Termux+Flask API."""
            resp = requests.post(url, json={"phone": phone_e164, "message": body}, timeout=30)
            try:
                data = resp.json()
            except Exception:
                return False, f"HTTP {resp.status_code}: {resp.text[:200]}"
            return data.get("success", False), data.get("error", "unknown")

        def send_sms_residential(url, phone_e164, body):
            """SM-S918U — SMSGate API (Basic Auth, different payload)."""
            resp = requests.post(
                url,
                json={"textMessage": {"text": body}, "phoneNumbers": [phone_e164]},
                auth=("sms", SMS_RESIDENTIAL_PASSWORD),
                timeout=30
            )
            if resp.status_code in (200, 201, 202):
                return True, None
            try:
                data = resp.json()
                return False, data.get("message", f"HTTP {resp.status_code}")
            except Exception:
                return False, f"HTTP {resp.status_code}: {resp.text[:200]}"

        for draft in drafts:
            sms_body = draft.get("sms_body")
            phone = draft.get("phone", "")
            source_type = draft.get("source_type", "")
            use_residential = source_type in RESIDENTIAL_SOURCES and SMS_GATEWAY_RESIDENTIAL

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
                if use_residential:
                    success, error = send_sms_residential(SMS_GATEWAY_RESIDENTIAL, phone_e164, sms_body)
                else:
                    success, error = send_sms_commercial(SMS_GATEWAY_COMMERCIAL, phone_e164, sms_body)

                if success:
                    sms_results.append({"phone": phone_e164, "sms_sent": True})
                else:
                    sms_results.append({"phone": phone_e164, "sms_sent": False, "error": error})
            except Exception as e:
                sms_results.append({"phone": phone_e164, "sms_sent": False, "error": str(e)})
                # Alert Jake via commercial gateway (Pixel 9a) if residential gateway fails
                if use_residential:
                    try:
                        requests.post(
                            SMS_GATEWAY_COMMERCIAL,
                            json={"phone": "+17348960518", "message": f"Residential SMS gateway error: failed to send SMS to {phone_e164} for {draft.get('email', 'unknown')}. Error: {str(e)}"},
                            timeout=10
                        )
                    except Exception:
                        pass  # alert failure must not crash pipeline

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
                wa_post(token, "addContactNote", {
                    "clientids": str(client_id),
                    "note": note_text,
                    "subject": f"Reply Sent - {prop_names[:50]}"
                })
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
