#extra_requirements:
#psycopg2-binary

import wmill
import psycopg2
import json


def main(
    signal_type: str,
    source_flow: str,
    summary: str,
    detail: dict = {},
    actions: list = [],
    windmill_job_id: str = "",
    resume_url: str = "",
    cancel_url: str = "",
):
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
        INSERT INTO public.jake_signals (
            signal_type, source_flow, summary, detail, actions,
            windmill_job_id, resume_url, cancel_url, status
        ) VALUES (%s, %s, %s, %s::jsonb, %s::jsonb, %s, %s, %s, 'pending')
        RETURNING id, created_at
        """,
        (
            signal_type,
            source_flow,
            summary,
            json.dumps(detail),
            json.dumps(actions),
            windmill_job_id,
            resume_url,
            cancel_url,
        ),
    )
    row = cur.fetchone()
    conn.commit()
    cur.close()
    conn.close()
    return {"signal_id": row[0], "created_at": str(row[1])}
