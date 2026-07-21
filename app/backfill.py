"""Run-once script: enrich every pre-M2 capture that has no embedding yet.
Run: docker compose exec api python backfill.py
Idempotent (filters on embedding IS NULL) and commits per row so a crash mid-run
just leaves the remaining rows NULL for the next run to pick up.
"""
import os

from capture import enrich
from db import get_conn
from psycopg.types.json import Jsonb

DATA_DIR = os.environ.get("DATA_DIR", "/data")


def run():
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT id, kind, content, file_path, mime_type FROM captures WHERE embedding IS NULL")
        rows = cur.fetchall()

    print(f"{len(rows)} capture(s) to backfill")
    for id_, kind, content, file_path, mime in rows:
        file_bytes = None
        if file_path:
            try:
                with open(f"{DATA_DIR}/{file_path}", "rb") as f:
                    file_bytes = f.read()
            except OSError as e:
                print(f"{id_}: could not read {file_path}: {e}")
        embedding, extracted = enrich(content, kind, file_bytes, mime)
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute(
                "UPDATE captures SET embedding = %s::vector, extracted = %s WHERE id = %s",
                (embedding, Jsonb(extracted), id_),
            )
            conn.commit()
        print(f"{id_}: done (embedding={'yes' if embedding else 'no'})")


if __name__ == "__main__":
    run()
