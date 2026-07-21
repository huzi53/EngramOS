import hashlib
import os
import re
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from psycopg.types.json import Jsonb

from auth import require_access
from db import get_conn

router = APIRouter()

DATA_DIR = os.environ.get("DATA_DIR", "/data")
CAPTURES_DIR = f"{DATA_DIR}/captures"
MAX_BYTES = 25 * 1024 * 1024  # Telegram's ~20MB getFile cap + margin; disk-fill guard

URL_RE = re.compile(r"^https?://\S+$")


def canonical_hash(data: bytes) -> bytes:
    return hashlib.blake2b(data).digest()


def infer_kind(text, filename, mime) -> str:
    if filename:
        if mime and mime.startswith("image/"):
            return "photo"
        if mime and mime.startswith("audio/"):
            return "audio"
        return "file"
    if text and URL_RE.match(text.strip()):
        # ponytail: naive URL detection; good enough for exact-dedup, real URL
        # normalization is M2 extraction.
        return "url"
    return "text"


def safe_ext(filename: str) -> str:
    # NEVER build the storage path from the client filename (path-traversal guard).
    ext = os.path.splitext(os.path.basename(filename or ""))[1]
    return re.sub(r"[^a-zA-Z0-9.]", "", ext)


def store_capture(user_id, source, *, text=None, file_bytes=None, file_name=None, mime=None, meta=None) -> dict:
    if not text and not file_bytes:
        raise ValueError("capture needs text or a file")
    if file_bytes and len(file_bytes) > MAX_BYTES:
        raise ValueError("too large")

    kind = infer_kind(text, file_name, mime)
    digest = canonical_hash(file_bytes if file_bytes else text.strip().encode())

    file_path = None
    content = text.strip() if text else None
    stored_full_path = None
    if file_bytes:
        ext = safe_ext(file_name)
        stored_name = f"{uuid.uuid4().hex}{ext}"
        stored_full_path = f"{CAPTURES_DIR}/{stored_name}"
        os.makedirs(CAPTURES_DIR, exist_ok=True)
        with open(stored_full_path, "wb") as f:
            f.write(file_bytes)
        file_path = f"captures/{stored_name}"

    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO captures (user_id, source, kind, content, file_path, file_name, mime_type,
                                   content_hash, meta)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (user_id, content_hash) DO NOTHING
            RETURNING id, created_at
            """,
            (user_id, source, kind, content, file_path, file_name, mime, digest, Jsonb(meta or {})),
        )
        row = cur.fetchone()
        if row is None:
            cur.execute(
                "SELECT id, created_at FROM captures WHERE user_id = %s AND content_hash = %s",
                (user_id, digest),
            )
            row = cur.fetchone()
            conn.commit()
            if stored_full_path:
                os.remove(stored_full_path)  # orphan file from a duplicate write
            return {"id": str(row[0]), "kind": kind, "duplicate": True}
        conn.commit()
        return {"id": str(row[0]), "kind": kind, "duplicate": False}


@router.post("/api/v1/capture", status_code=201)
async def capture(
    text: str | None = Form(None),
    source: str = Form("api"),
    file: UploadFile | None = File(None),
    payload: dict = Depends(require_access),
):
    file_bytes = await file.read(MAX_BYTES + 1) if file else None
    if file_bytes and len(file_bytes) > MAX_BYTES:
        raise HTTPException(status_code=413, detail="too large")
    try:
        result = store_capture(
            payload["sub"],
            source,
            text=text,
            file_bytes=file_bytes,
            file_name=file.filename if file else None,
            mime=file.content_type if file else None,
        )
    except ValueError as e:
        status = 413 if str(e) == "too large" else 400
        raise HTTPException(status_code=status, detail=str(e))
    return result


@router.get("/api/v1/captures")
def list_captures(limit: int = 50, payload: dict = Depends(require_access)):
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, source, kind, content, file_name, mime_type, created_at
            FROM captures WHERE user_id = %s ORDER BY created_at DESC LIMIT %s
            """,
            (payload["sub"], limit),
        )
        cols = [c.name for c in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]
