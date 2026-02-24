#extra_requirements:
#psycopg2-binary

import wmill
import psycopg2
import json


def main(status: str = "pending", limit: int = 20):
    """Read signals from jake_signals table.
    
    Returns pending (or other status) signals ordered by newest first.
    Used by Router UI to poll for action items.
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
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, signal_type, source_flow, summary, detail, actions,
               windmill_job_id, resume_url, cancel_url, status, created_at
        FROM public.jake_signals
        WHERE status = %s
        ORDER BY created_at DESC
        LIMIT %s
        """,
        (status, limit),
    )
    cols = [d[0] for d in cur.description]
    rows = []
    for r in cur.fetchall():
        row = {}
        for i, col in enumerate(cols):
            val = r[i]
            if col == "created_at":
                val = str(val)
            row[col] = val
        rows.append(row)
    cur.close()
    conn.close()
    return rows
