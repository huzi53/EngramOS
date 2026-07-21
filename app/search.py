"""Hybrid search: pgvector cosine (meaning) + Postgres FTS (keyword), merged by
Reciprocal Rank Fusion. Cosine distance and ts_rank are incomparable scales; RRF fuses
by *rank* so no score normalization is needed.
"""
from fastapi import APIRouter, Depends

from auth import require_access
from db import get_conn
from embed import embed_query, to_pgvector

router = APIRouter()

RRF_K = 60
CANDIDATES = 20  # per-source candidate pool fed into the fusion


def fuse(vector_ids: list[str], fts_ids: list[str]) -> dict[str, float]:
    """Reciprocal Rank Fusion: id -> fused score. rank is 0-based position in each list.
    Pure function (no DB) so it's directly unit-testable.
    """
    scores: dict[str, float] = {}
    for rank, id_ in enumerate(vector_ids):
        scores[id_] = scores.get(id_, 0.0) + 1.0 / (RRF_K + rank)
    for rank, id_ in enumerate(fts_ids):
        scores[id_] = scores.get(id_, 0.0) + 1.0 / (RRF_K + rank)
    return scores


@router.get("/api/v1/search")
def search(q: str = "", limit: int = 10, payload: dict = Depends(require_access)):
    q = q.strip()
    if not q:
        return []
    user_id = payload["sub"]
    qvec = to_pgvector(embed_query(q))

    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, source, kind, content, file_name, created_at
            FROM captures WHERE user_id = %s AND embedding IS NOT NULL
            ORDER BY embedding <=> %s::vector LIMIT %s
            """,
            (user_id, qvec, CANDIDATES),
        )
        cols = [c.name for c in cur.description]
        vector_rows = [dict(zip(cols, row)) for row in cur.fetchall()]

        cur.execute(
            """
            SELECT id, source, kind, content, file_name, created_at
            FROM captures
            WHERE user_id = %s AND search_tsv @@ websearch_to_tsquery('simple', %s)
            ORDER BY ts_rank(search_tsv, websearch_to_tsquery('simple', %s)) DESC LIMIT %s
            """,
            (user_id, q, q, CANDIDATES),
        )
        cols = [c.name for c in cur.description]
        fts_rows = [dict(zip(cols, row)) for row in cur.fetchall()]

    by_id = {str(r["id"]): r for r in vector_rows}
    by_id.update({str(r["id"]): r for r in fts_rows})

    fused = fuse([str(r["id"]) for r in vector_rows], [str(r["id"]) for r in fts_rows])
    ranked_ids = sorted(fused, key=lambda i: fused[i], reverse=True)[:limit]

    results = []
    for id_ in ranked_ids:
        row = dict(by_id[id_])
        row["score"] = fused[id_]
        results.append(row)
    return results
