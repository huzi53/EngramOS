import hashlib
import os
import re
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from psycopg.types.json import Jsonb

from auth import require_access
from db import clamp_limit, get_conn
from embed import embed_passage, to_pgvector
from extract import extract_amounts, extract_dates, extract_emails, extract_phones, extract_url_metadata, ocr_image

router = APIRouter()

DATA_DIR = os.environ.get("DATA_DIR", "/data")
CAPTURES_DIR = f"{DATA_DIR}/captures"
MAX_BYTES = 25 * 1024 * 1024  # Telegram's ~20MB getFile cap + margin; disk-fill guard

URL_RE = re.compile(r"^https?://\S+$")


def canonical_hash(*parts: bytes) -> bytes:
    # Length-framed so parts can't ambiguously merge (b"a"+b"bc" must differ from b"ab"+b"c").
    h = hashlib.blake2b()
    for p in parts:
        h.update(len(p).to_bytes(8, "big"))
        h.update(p)
    return h.digest()


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


def enrich(text, kind, file_bytes, mime) -> tuple[str | None, dict]:
    """Tier-1 extraction + embedding for a NEW capture. Fails soft field-by-field
    (each extractor already fails soft internally) — enrichment must never crash a capture.
    """
    extracted = {}
    if kind == "url" and text:
        extracted |= extract_url_metadata(text)
    if kind == "photo" and file_bytes:
        ocr_text = ocr_image(file_bytes)
        if ocr_text:
            extracted["ocr_text"] = ocr_text

    doc_parts = [text or "", extracted.get("ocr_text", ""), extracted.get("url_title", ""), extracted.get("url_description", "")]
    scan_text = " ".join(p for p in doc_parts if p)

    emails = extract_emails(scan_text)
    if emails:
        extracted["emails"] = emails
    phones = extract_phones(scan_text)
    if phones:
        extracted["phones"] = phones
    amounts = extract_amounts(scan_text)
    if amounts:
        extracted["amounts"] = amounts
    dates = extract_dates(scan_text)
    if dates:
        extracted["dates"] = dates

    embedding = None
    if scan_text.strip():
        try:
            embedding = to_pgvector(embed_passage(scan_text))
        except Exception:
            pass  # fail soft like every extractor above; backfill.py fills NULL embeddings later
    return embedding, extracted


def store_capture(user_id, source, *, text=None, file_bytes=None, file_name=None, mime=None, meta=None) -> dict:
    if not text and not file_bytes:
        raise ValueError("capture needs text or a file")
    if file_bytes and len(file_bytes) > MAX_BYTES:
        raise ValueError("too large")

    kind = infer_kind(text, file_name, mime)
    content = text.strip() if text else None
    # Content-address over everything that makes a capture distinct — kind, note text, AND
    # file bytes — not the file bytes alone. Otherwise the same photo re-sent with a changed
    # or added note is silently dropped as a "duplicate" (its new note lost at HTTP 201), and
    # a photo dedups against any unrelated capture that merely shares bytes. Re-sending an
    # identical kind+text+file is still a true duplicate, so idempotency is preserved.
    digest = canonical_hash(kind.encode(), (content or "").encode(), file_bytes or b"")

    file_path = None
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

        # NEW row only — never enrich the duplicate-hit path above.
        embedding, extracted = enrich(content, kind, file_bytes, mime)
        cur.execute(
            "UPDATE captures SET embedding = %s::vector, extracted = %s WHERE id = %s",
            (embedding, Jsonb(extracted), row[0]),
        )
        conn.commit()
        return {"id": str(row[0]), "kind": kind, "duplicate": False}


@router.post("/api/v1/capture", status_code=201)
def capture(
    text: str | None = Form(None),
    source: str = Form("api"),
    file: UploadFile | None = File(None),
    payload: dict = Depends(require_access),
):
    # plain def (not async): store_capture does blocking DB/embedding/OCR/URL-fetch work,
    # so FastAPI runs this in its threadpool instead of the event loop (matches
    # list_captures/search below). file.file.read() is the sync counterpart of await file.read().
    file_bytes = file.file.read(MAX_BYTES + 1) if file else None
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
    limit = clamp_limit(limit)
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
