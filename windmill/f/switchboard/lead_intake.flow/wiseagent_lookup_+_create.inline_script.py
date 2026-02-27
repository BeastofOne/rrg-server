#extra_requirements:
#requests
#psycopg2-binary

import wmill
import requests
import json
import time
import psycopg2
from datetime import datetime, timezone, timedelta

BASE_URL = "https://sync.thewiseagent.com/http/webconnect.asp"
TOKEN_URL = "https://sync.thewiseagent.com/WiseAuth/token"

def get_token(oauth):
    """Get valid access token, refreshing if expired."""
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

def lookup_contact(token, email):
    resp = requests.get(BASE_URL, params={"requestType": "getContacts", "email": email}, headers={"Authorization": f"Bearer {token}", "Accept": "application/json", "Content-Type": "application/x-www-form-urlencoded"}, timeout=15)
    resp.raise_for_status()
    contacts = json.loads(resp.text, strict=False)
    if not contacts:
        return None
    return contacts[0]

def check_nda_category(contact):
    cats_raw = contact.get("Categories", "[]")
    try:
        cats = json.loads(cats_raw) if isinstance(cats_raw, str) else cats_raw
        return any(c.get("name", "").lower() == "nda signed" for c in cats)
    except Exception:
        return False

def check_followup(token, client_id):
    """Check if contact has a 'Lead Intake' note from the last 7 days."""
    try:
        resp = requests.get(BASE_URL, params={"requestType": "getContactNotes", "ClientID": str(client_id)}, headers={"Authorization": f"Bearer {token}", "Accept": "application/json", "Content-Type": "application/x-www-form-urlencoded"}, timeout=15)
        resp.raise_for_status()
        notes = json.loads(resp.text, strict=False)
        if isinstance(notes, list):
            now = datetime.now(timezone.utc)
            cutoff = now - timedelta(days=7)
            for note in notes:
                subject = note.get("Subject", "")
                if "Lead Intake" not in subject:
                    continue
                # Try multiple date fields (WiseAgent API varies)
                note_date_str = note.get("NoteDate", "") or note.get("DateEntered", "") or note.get("Created", "") or note.get("Date", "")
                if note_date_str:
                    try:
                        note_date = datetime.fromisoformat(note_date_str.replace("Z", "+00:00"))
                        if not note_date.tzinfo:
                            note_date = note_date.replace(tzinfo=timezone.utc)
                        if note_date >= cutoff:
                            return True
                    except Exception:
                        # Can't parse date — skip this note (conservative)
                        continue
        return False
    except Exception:
        return False

def write_lead_intake_note(token, client_id, source, property_name):
    """Write a Lead Intake note to WiseAgent for tracking followups."""
    try:
        today = datetime.now().strftime("%Y-%m-%d")
        note_data = {
            "clientids": str(client_id),
            "note": f"Lead notification received via {source} on {today}. Property: {property_name}.",
            "subject": "Lead Intake"
        }
        resp = requests.post(
            BASE_URL + "?requestType=addContactNote",
            data=note_data,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/x-www-form-urlencoded"},
            timeout=15
        )
        resp.raise_for_status()
    except Exception:
        pass  # Non-critical — don't fail the pipeline

def extract_field(response_data, field_name):
    """Extract a field from WiseAgent API response (handles list or dict)."""
    if isinstance(response_data, list):
        for item in response_data:
            if isinstance(item, dict) and field_name in item:
                return item[field_name]
    elif isinstance(response_data, dict):
        return response_data.get(field_name)
    return None

def log_contact_creation(lead, client_id, status="created"):
    """Log contact creation to contact_creation_log table (BUG 7A)."""
    try:
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
                INSERT INTO public.contact_creation_log
                (email, name, phone, source, source_type, wiseagent_client_id, property_name, raw_lead_data, status)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s)
            """, (
                lead.get("email", ""),
                lead.get("name", ""),
                lead.get("phone", ""),
                lead.get("source", ""),
                lead.get("source_type", ""),
                str(client_id) if client_id else None,
                lead.get("property_name", ""),
                json.dumps(lead),
                status
            ))
            conn.commit()
            cur.close()
        finally:
            conn.close()
    except Exception:
        pass  # Non-critical — don't fail the pipeline over logging

def main(leads: list):
    oauth = wmill.get_resource("f/switchboard/wiseagent_oauth")
    token = get_token(oauth)
    enriched = []
    for lead in leads:
        email = lead.get("email", "").strip().lower()
        result = dict(lead)
        if not email:
            result["wiseagent_client_id"] = None
            result["is_new"] = True
            result["is_followup"] = False
            result["has_nda"] = False
            enriched.append(result)
            continue
        contact = lookup_contact(token, email)
        if contact:
            client_id = contact["ClientID"]
            result["wiseagent_client_id"] = client_id
            result["is_new"] = False
            result["has_nda"] = check_nda_category(contact)
            # Followup = existing contact + has "Lead Intake" note from last 7 days
            result["is_followup"] = check_followup(token, client_id)
            result["wiseagent_status"] = contact.get("Status", "")
            result["wiseagent_rank"] = contact.get("Rank", "")
            # Write lead intake note AFTER followup check (so this note doesn't count for current check)
            write_lead_intake_note(token, client_id, lead.get("source", ""), lead.get("property_name", ""))
        else:
            # ARCHITECTURAL CHANGE: Create contact immediately (moved from Module F)
            # Every lead exits Module A with a valid wiseagent_client_id
            name_parts = lead.get("name", "").split(" ", 1)
            first = name_parts[0] if name_parts else ""
            last = name_parts[1] if len(name_parts) > 1 else ""
            create_data = {
                "CFirst": first, "CLast": last, "CEmail": email,
                "Source": lead.get("source", "Crexi"), "Status": "Hot Lead"
            }
            phone = lead.get("phone", "")
            if phone:
                create_data["MobilePhone"] = phone
            # Retry CRM contact creation up to 3 times
            client_id = None
            last_error = None
            for attempt in range(3):
                try:
                    resp = requests.post(
                        BASE_URL + "?requestType=webcontact", data=create_data,
                        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/x-www-form-urlencoded"},
                        timeout=15
                    )
                    resp.raise_for_status()
                    create_resp = json.loads(resp.text, strict=False)
                    client_id = extract_field(create_resp, "ClientID") or extract_field(create_resp, "clientID")
                    last_error = None
                    break
                except Exception as e:
                    last_error = e
                    print(f"[CRM Create] Attempt {attempt + 1}/3 failed for {email}: {e}")
                    if attempt < 2:
                        time.sleep(2)

            if last_error is None and client_id:
                # Success path
                result["wiseagent_client_id"] = client_id
                result["is_new"] = True
                result["is_followup"] = False
                result["has_nda"] = False
                log_contact_creation(lead, client_id, status="created")
                write_lead_intake_note(token, client_id, lead.get("source", ""), lead.get("property_name", ""))
            else:
                # Final failure — continue without client_id
                result["wiseagent_client_id"] = None
                result["is_new"] = True
                result["is_followup"] = False
                result["has_nda"] = False
                result["crm_create_error"] = str(last_error) if last_error else "no client_id returned"
                # SMS alert to Jake
                try:
                    requests.post(
                        "http://100.125.176.16:8686/send-sms",
                        json={"phone": "+17348960518", "message": f"CRM contact creation failed for {email} after 3 attempts"},
                        timeout=10
                    )
                except Exception:
                    pass  # SMS failure must not crash the pipeline
                # Log failure to DB
                log_contact_creation(lead, None, status="failed")
        enriched.append(result)
    return enriched
