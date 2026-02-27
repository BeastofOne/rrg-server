#extra_requirements:
#psycopg2-binary

import wmill
import psycopg2

def main():
    """Get all pending lead_intake signals that have draft_id_map."""
    pg = wmill.get_resource("f/switchboard/pg")
    conn = psycopg2.connect(
        host=pg["host"],
        port=pg.get("port", 5432),
        user=pg["user"],
        password=pg["password"],
        dbname=pg["dbname"],
        sslmode=pg.get("sslmode", "disable"),
    )
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, resume_url, cancel_url, detail
            FROM public.jake_signals
            WHERE status = 'pending'
              AND source_flow = 'lead_intake'
              AND detail ? 'draft_id_map'
            ORDER BY created_at DESC
        """)
        signals = []
        for row in cur.fetchall():
            signals.append({
                "id": row[0],
                "resume_url": row[1],
                "cancel_url": row[2],
                "detail": row[3]
            })
        cur.close()
    finally:
        conn.close()
    return {"signals": signals}
