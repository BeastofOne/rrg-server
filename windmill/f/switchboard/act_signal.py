#extra_requirements:
#psycopg2-binary

import wmill
import psycopg2


def main(signal_id: int, action: str, acted_by: str = "jake"):
    """Mark a signal as acted upon.
    
    Updates the signal status to 'acted' and records who took the action.
    Returns the updated signal row.
    """
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
        cur.execute(
            """
            UPDATE public.jake_signals
            SET status = 'acted', acted_at = NOW(), acted_by = %s
            WHERE id = %s AND status = 'pending'
            RETURNING id, signal_type, source_flow, summary, status, acted_at
            """,
            (acted_by, signal_id),
        )
        row = cur.fetchone()
        conn.commit()
        cur.close()
    finally:
        conn.close()
    if row is None:
        return {"error": f"Signal {signal_id} not found or already acted upon"}
    cols = ["id", "signal_type", "source_flow", "summary", "status", "acted_at"]
    return {cols[i]: str(row[i]) if cols[i] == "acted_at" else row[i] for i in range(len(cols))}
