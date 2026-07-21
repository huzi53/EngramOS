# 004 — M1 Capture works (endpoint + Telegram bot + minimal dashboard)

## Goal
Capture anything (text, URL, photo, file, audio) from the phone in <10s via a Telegram
long-polling bot or a private dashboard quick-note, exact-dedup it with blake2b, and see
it in a newest-first captures list.

## Context (verified against the repo, not assumed)
- Current app: `app/main.py` (FastAPI, lifespan upserts single user, `/health`), `app/auth.py`
  (JWT via `Authorization: Bearer`, `require_access` dependency, `get_user_by_username`),
  `app/db.py` (`get_conn()` = per-request `psycopg.connect(DATABASE_URL)`). One table `users`.
- `db/init.sql` runs **only on first boot of an empty pgdata volume**. The M0 stack is already
  running with data, so a new table must be applied to the live DB, not just added to init.sql.
- `docker-compose.yml`: `db` (pgvector/pg16, healthcheck), `api` (build ./app, `127.0.0.1:8000`),
  `caddy` (`:80 { reverse_proxy api:8000 }`, bound `127.0.0.1:8080`, Tailscale fronts TLS).
  **No worker/bot service exists** (M0 deferred it here). No `/data` volume yet.
- `app/requirements.txt`: fastapi, uvicorn[standard], psycopg[binary], pyjwt, bcrypt, pytest,
  httpx. **`httpx` is already present** (test dep) — the bot reuses it, no Telegram library.
  **`python-multipart` is missing** and is required for FastAPI `Form`/`File` parsing — must add.
- `scripts/backup.sh` has a commented `/data` restic line ready to enable (per plans/002 Cut).
- `.env.example`: Postgres, single-user auth, restic/B2, commented M3 LLM block. **No Telegram
  token yet** — must add.

## Key decisions (ladder-checked)
- **No migration tool (Alembic).** M1 adds exactly ONE table (`captures`); users+captures = 2
  tables — "tables don't multiply" until M4 (entities + capture_entities + capture_relations).
  Use a plain idempotent `db/migrations/001_captures.sql` applied by a documented `psql` one-liner.
  `ponytail:` add a real migration tool at M4 when dependent tables + ordering actually appear.
- **No Next.js / Pages deploy / Actions frontend build.** M1 UI = one static `index.html` +
  `app.js` served by FastAPI (rung 4/6). The real glass dashboard is M3.5 and is a full rewrite
  per plan.md — standing up a framework + build pipeline now is scaffolding for two throwaway
  widgets. Task explicitly blesses "a couple static pages / vanilla JS."
- **Bot calls the shared `store_capture()` function directly, not the HTTP endpoint.** One
  capture pipeline (dedup + storage + insert) in `app/capture.py`; the HTTP endpoint is a thin
  JWT-guarded wrapper, the bot is another caller inside the compose network. Avoids a second
  auth path on the endpoint and duplicated dedup logic. Bot service reuses the `./app` image
  (`command: python bot.py`), holds DATABASE_URL + bot token.
- **Bot trust boundary = a chat-id allowlist** (`TELEGRAM_ALLOWED_CHAT_ID`). Without it anyone
  who finds the bot can inject captures / upload files. Bot drops every update from another id.
- **Raw httpx `getUpdates` poll loop**, not python-telegram-bot. `ponytail:` add the library
  only if inline keyboards / commands / conversation state land (V3 in-bot search).
- **Files live on a `./data` bind mount** (WSL filesystem side, per plan.md risk note), stored
  flat as `data/captures/<uuid>.<ext>`, relative path in the DB row. Bind (not named volume) so
  `scripts/backup.sh` can `restic backup ./data` directly from the host.

## Cut (deferred, with reason)
- PWA share target · IndexedDB retry queue · chunked upload — V3 per plan.md v1.4 (confirmed).
- Next.js dashboard / Cloudflare Pages / GitHub Actions frontend build — M3.5 (glass UI port,
  a full rewrite anyway). M1 serves static HTML+JS from FastAPI.
- Migration tool (Alembic/dbmate) — M4 (raw SQL migration file suffices for one table).
- Media-serving / inline photo+audio playback endpoint — M3.5 real dashboard. Inline `<img>`
  needs auth-on-media (cookie/signed URL) not worth building twice. M1 list shows metadata rows;
  blobs are stored for M2 OCR + M3.5 gallery. Exit test ("all four appear in the list") still passes.
- Quick-note file/photo upload — M3.5. M1 quick-note is **text-only** (the private text path);
  media goes via Telegram.
- `embedding vector(384)` column + classification — M2/M3. `captures` ships without it; M2 does
  `ALTER TABLE captures ADD COLUMN embedding vector(384)` cleanly.
- URL extraction (oEmbed / yt-dlp / thumbnail / caption) — M2 (that milestone = extraction).
  M1 stores the raw URL string as-is (matches plan.md "honest expectation": M1 = link, metadata later).
- Bot offset persistence across restarts — not needed; blake2b dedup makes any reprocessed
  update idempotent (`ON CONFLICT DO NOTHING`). Offset kept in memory. `ponytail:` note in bot.py.

## Files touched
- `db/migrations/001_captures.sql` — **new**, the captures table + indexes.
- `app/capture.py` — **new**, `store_capture()` shared fn + helpers + the APIRouter (mirrors auth.py).
- `app/bot.py` — **new**, Telegram getUpdates poll loop → `store_capture()`.
- `app/main.py` — edit: `include_router(capture)`, `mkdir data/captures`, mount static UI.
- `app/static/index.html`, `app/static/app.js` — **new**, minimal login + quick-note + list.
- `app/requirements.txt` — edit: add `python-multipart`.
- `app/test_capture.py` — **new**, assert-based self-check (hashing, kind inference, path-traversal).
- `docker-compose.yml` — edit: add `bot` service; add `./data:/data` mount to `api` and `bot`.
- `.env.example` — edit: add `TELEGRAM_BOT_TOKEN`, `TELEGRAM_ALLOWED_CHAT_ID`, `DATA_DIR=/data`.
- `.gitignore` — edit: add `data/`.
- `scripts/backup.sh` — edit: enable the `/data` restic line.
- `README.md` — edit: add `## M1 — Capture` run section.

## Steps

### 1. DB schema — `db/migrations/001_captures.sql`
New file, idempotent (single-quoted literals, correct syntax per Appendix A fix #3):
```sql
CREATE TABLE IF NOT EXISTS captures (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id       uuid NOT NULL REFERENCES users(id),
    source        text NOT NULL,              -- 'telegram' | 'quicknote' | 'api'
    kind          text NOT NULL,              -- 'text' | 'url' | 'photo' | 'file' | 'audio'
    content       text,                       -- text body / URL / media caption (nullable)
    file_path     text,                       -- relative path under DATA_DIR, e.g. captures/<uuid>.jpg
    file_name     text,                       -- original filename (display only, never a storage path)
    mime_type     text,
    content_hash  bytea NOT NULL,             -- blake2b of canonical bytes (dedup key)
    meta          jsonb NOT NULL DEFAULT '{}',-- telegram msg/chat id, forward info, etc.
    created_at    timestamptz NOT NULL DEFAULT now()
);
-- dedup: same content for the same user = one capture
CREATE UNIQUE INDEX IF NOT EXISTS captures_hash_uidx ON captures (user_id, content_hash);
-- list view: newest first
CREATE INDEX IF NOT EXISTS captures_created_idx ON captures (user_id, created_at DESC);
-- ponytail: no embedding/vector column yet — M2 ALTER TABLE ADD COLUMN embedding vector(384).
-- ponytail: raw SQL migration; add Alembic at M4 when entity/relation tables + ordering appear.
```
Apply to the live DB (documented in README):
`docker compose exec -T db psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" < db/migrations/001_captures.sql`
Do NOT duplicate this DDL into `init.sql` (init.sql = M0 baseline; migrations layer on top; a
pg_dump restore already carries the table). Fresh empty boots apply migrations in numeric order.
Check: after applying, `\dt` shows `captures`; `\d captures` shows both indexes.

### 2. Capture core + endpoint — `app/capture.py`
Mirror `auth.py`'s module shape (module-level `router = APIRouter()`, reuse `get_conn`,
`require_access` from auth, `get_user_by_username`). Contents:

- `DATA_DIR = os.environ.get("DATA_DIR", "/data")`, `CAPTURES_DIR = f"{DATA_DIR}/captures"`.
- `MAX_BYTES = 25 * 1024 * 1024` (aligns with Telegram's ~20MB getFile cap; disk-fill guard).
- Pure helpers (unit-tested in step 7):
  - `canonical_hash(data: bytes) -> bytes` → `hashlib.blake2b(data).digest()` (stdlib, rung 3).
    For text/url callers pass `text.strip().encode()`; for media pass the raw file bytes.
  - `infer_kind(text, filename, mime) -> str`: file + `image/*`→'photo', `audio/*`→'audio',
    else file→'file'; no file + text matches `^https?://\S+$`→'url', else 'text'.
    `ponytail: naive URL detection; good enough for exact-dedup, real URL normalization is M2 extraction.`
  - `safe_ext(filename) -> str`: take only `os.path.splitext(os.path.basename(filename))[1]`,
    strip anything non-alphanumeric — NEVER build the storage path from the client filename
    (path-traversal guard). Storage name = `f"{uuid4().hex}{ext}"`.
- `store_capture(user_id, source, *, text=None, file_bytes=None, file_name=None, mime=None, meta=None) -> dict`:
  1. Validate: require `text` or `file_bytes` (raise `ValueError` if neither). If `file_bytes`
     and `len > MAX_BYTES` → raise `ValueError` (endpoint maps to 413).
  2. `kind = infer_kind(...)`; `digest = canonical_hash(file_bytes or text.strip().encode())`.
  3. If file: write bytes to `CAPTURES_DIR/<uuid>.<ext>` (mkdir exist_ok at startup), set
     `file_path = "captures/<uuid>.<ext>"`, `content = text` (caption, may be None).
     If text-only: `content = text.strip()`, `file_path = None`.
  4. Dedup insert (DB constraint does the work, rung 4):
     `INSERT INTO captures (user_id, source, kind, content, file_path, file_name, mime_type,
     content_hash, meta) VALUES (...) ON CONFLICT (user_id, content_hash) DO NOTHING
     RETURNING id, created_at`.
     If a row returns → new capture. If none → duplicate: `SELECT id, created_at FROM captures
     WHERE user_id=%s AND content_hash=%s`; return `{"id":..., "duplicate": True}`.
     For a duplicate that WROTE a file, delete the orphan file (os.remove) before returning.
  5. Return `{"id": str(id), "kind": kind, "duplicate": bool}`.
- HTTP endpoints on `router`:
  - `POST /api/v1/capture` — `Depends(require_access)`; multipart Form:
    `text: str | None = Form(None)`, `kind: str | None = Form(None)` (accepted but inference wins
    if absent), `source: str = Form("api")`, `file: UploadFile | None = File(None)`.
    Resolve `user_id = payload["sub"]` (JWT sub is the users.id, per auth.py). Read `await file.read()`
    if present. Call `store_capture(...)`; map `ValueError("too large")`→413, other `ValueError`→400.
    Return 201 with the dict.
  - `GET /api/v1/captures?limit=50` — `Depends(require_access)`; `SELECT id, source, kind, content,
    file_name, mime_type, created_at FROM captures WHERE user_id=%s ORDER BY created_at DESC LIMIT %s`.
    Return list of dicts. (No file bytes — metadata only, see Cut.)
Check: `curl -F text='hi' -H "Authorization: Bearer $TOKEN" localhost:8000/api/v1/capture` → 201;
same text again → `duplicate:true`; `GET /api/v1/captures` lists it newest-first; `/capture`
without a bearer → 401.

### 3. main.py wiring — `app/main.py`
- `from capture import router as capture_router`; `app.include_router(capture_router)`.
- In lifespan (or at import), `os.makedirs(f"{os.environ.get('DATA_DIR','/data')}/captures", exist_ok=True)`.
- Mount static UI **after** routers/health so API routes win: 
  `from fastapi.staticfiles import StaticFiles; app.mount("/", StaticFiles(directory="static", html=True))`.
Check: `docker compose up api` boots; `/health` and `/api/v1/*` still respond; `GET /` serves index.html.

### 4. Telegram bot — `app/bot.py`
Raw httpx long-poll loop, reuses `store_capture`, `get_conn`. No new dependency.
- Env: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_ALLOWED_CHAT_ID` (int). `API = f"https://api.telegram.org/bot{token}"`.
- Resolve the single `user_id` once at startup: `SELECT id FROM users WHERE username=%s` (env
  `AUTH_USERNAME`) — same user every capture (single-user system).
- Loop: `httpx.get(f"{API}/getUpdates", params={"offset": offset, "timeout": 50}, timeout=60)`.
  For each update (advance `offset = update_id + 1` **always**, even on error — a poison message
  must not wedge the loop; Telegram keeps it in the user's chat, re-forward recovers, per plan.md risk):
  - `msg = update.get("message")`; skip if none.
  - **Allowlist gate**: if `msg["chat"]["id"] != ALLOWED_CHAT_ID` → ignore silently (trust boundary).
  - Determine payload:
    - `text`/forwarded text → `store_capture(user_id, "telegram", text=msg["text"], meta={...})`.
    - `photo` → largest `photo[-1]["file_id"]`; `document` → `document`; `voice`/`audio` → that
      object. For media: `getFile` → download from `file_path` URL → bytes; `store_capture(...,
      file_bytes=bytes, file_name=..., mime=..., text=msg.get("caption"), meta={...})`.
    - `meta` carries `telegram_message_id`, `chat_id`, and `forward_from` when present.
  - Reply via `sendMessage`: "Saved ✅" or "Already saved" (feedback for the <10s exit test);
    on exception log + reply "Save failed, resend".
- `ponytail:` in-memory offset — dedup makes reprocessing after a restart idempotent, so no
  offset persistence needed; add a stored offset only if duplicate replies ever annoy.
Check (needs a real token + your chat id): forward a link, a photo, a voice note to the bot →
three "Saved ✅" replies in <10s each; they appear in `GET /api/v1/captures`; forward the same
link twice → second reply is "Already saved" and no new row.

### 5. Minimal dashboard — `app/static/index.html` + `app/static/app.js`
Vanilla JS, no framework, no build. Served from step 3's mount.
- `index.html`: a login form (username + password, shown when no token in localStorage); when
  logged in, a `<textarea>` + "Save note" button (quick-note) and a `<ul id="list">`. Tiny inline
  `<style>` (dark, readable) — no CSS framework. This is the **private path**: quick-note posts
  `source=quicknote`, never transits Telegram.
- `app.js`:
  - `login()` → `POST /api/v1/auth/login` → store `access_token`+`refresh_token` in localStorage.
  - `save()` → `FormData` with `text` + `source=quicknote` → `POST /api/v1/capture` with
    `Authorization: Bearer <access>`; on 401 try `/auth/refresh` once then retry; on success clear
    the box and reload the list.
  - `loadList()` → `GET /api/v1/captures` → render each as `kind · (content or file_name) · localtime`.
- `ponytail:` text-only quick-note; dashboard media upload + inline media viewing land with the
  M3.5 glass UI (which handles auth-on-media properly).
Check: open `https://<machine>.<tailnet>.ts.net/` on the phone → log in → type a sensitive note →
"Save" → it appears top of the list without a page reload.

### 6. Compose + env + backup + gitignore
- `docker-compose.yml`:
  - Add `./data:/data` to the `api` service volumes.
  - Add a `bot` service: `build: ./app`, `command: python bot.py`, `env_file: .env`,
    `depends_on: { db: { condition: service_healthy } }`, `volumes: ["./data:/data"]`,
    `restart: unless-stopped`. (No ports — long-poll is outbound only, so **no Caddyfile change**.)
- `.env.example`: add under a `# --- Telegram bot (M1) ---` block:
  `TELEGRAM_BOT_TOKEN=` (from @BotFather), `TELEGRAM_ALLOWED_CHAT_ID=` (your numeric chat id —
  message the bot then read `chat.id` from getUpdates once), and `DATA_DIR=/data`.
- `.gitignore`: add `data/` (never commit user blobs).
- `scripts/backup.sh`: enable the commented restic line so `/data` is backed up alongside the
  pg_dump (files are half the data now). Since `./data` is a host bind mount, `restic backup
  ./data` from the host reaches it directly.
- `app/requirements.txt`: add `python-multipart` (required for FastAPI Form/File parsing).
Check: `docker compose config` validates; `docker compose up -d` brings db+api+caddy+bot up;
bot logs "polling as <user_id>"; `restic backup` includes `data/` snapshots.

### 7. Self-check — `app/test_capture.py`
Assert-based, no framework, DB-free (import the pure helpers from `capture.py`):
- `canonical_hash(b"hi") == canonical_hash(b"hi")` and `!= canonical_hash(b"ho")` (dedup key stable).
- `infer_kind("https://x.co/a", None, None) == "url"`; `infer_kind("note", None, None) == "text"`;
  `infer_kind(None, "p.jpg", "image/jpeg") == "photo"`; `... "audio/ogg" == "audio"`; document → "file".
- `safe_ext("../../etc/passwd")` yields no separators and cannot escape `CAPTURES_DIR`
  (path-traversal guard — the security-relevant check ponytail requires for the file path).
Check: `cd app && python test_capture.py` → all asserts pass (guard with `if __name__=="__main__"`).
Add it to `.github/workflows/ci.yml` alongside `test_auth.py`.

## Verify (end-to-end — the M1 exit test)
1. Apply the migration (step 1), `docker compose up -d`, `tailscale serve` already fronting `:8080`.
2. From the phone: forward a TikTok link, a photo, and a voice note to the bot — each < 10s, each
   gets "Saved ✅". Type one sensitive note in the dashboard quick-note.
3. `GET /api/v1/captures` (and the dashboard list) shows all four, newest first.
4. Forward the same link again → "Already saved", captures count unchanged (blake2b dedup).
5. `cd app && python test_capture.py` passes; `scripts/backup.sh` snapshots include `data/`.

## Frontend?
**Yes.** First UI in the repo: a login form + quick-note box + captures list (static HTML +
vanilla JS served by FastAPI). Minimal, but real UI — route to the frontend agent.

## Security pass?
**Warranted.** M1 opens two new trust boundaries M0 didn't have:
- **Telegram ingestion from the internet** — the `TELEGRAM_ALLOWED_CHAT_ID` allowlist is the only
  thing stopping anyone who finds the bot from injecting captures / uploading files. Review that
  it's enforced on every update before any processing.
- **File uploads from user input** — path traversal (storage name must come from uuid, never the
  client filename), size cap (25MB, disk-fill guard), and blobs are stored-not-executed. Review
  `safe_ext`/storage-path construction and the `MAX_BYTES` gate.
- New authenticated write surface (`POST /api/v1/capture`) — reuses JWT so lower risk, but it's a
  new mutation endpoint plus a new same-origin static UI holding tokens in localStorage.
Unlike the M0 rework (no auth/crypto touched, only reduced network exposure), M1 adds real
input-from-the-internet and file handling — a scoped security review is due.
```
