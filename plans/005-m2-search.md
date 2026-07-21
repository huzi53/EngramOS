# 005 — M2 Search works (Tier-1 extraction + CPU embeddings + hybrid search + search UI)

## Goal
Make every capture findable both by meaning and by keyword: enrich each capture with
Tier-1 heuristic extraction (URL metadata, OCR text, dates/amounts/emails/phones) and a
384-dim multilingual embedding, then serve one hybrid search endpoint (pgvector cosine +
Postgres FTS, RRF-merged) behind a search box on the existing dashboard.
**Exit test:** capture 50+ real items, then find a specific one by meaning
("that article about sleep") and by keyword, each in the top 3 results.

## Context (verified against the repo, not assumed)
- **One capture pipeline already exists.** `app/capture.py::store_capture()` is called by
  BOTH the HTTP endpoint (`POST /api/v1/capture`) and the Telegram bot (`app/bot.py`
  imports it directly). Enrichment hooks attach HERE — do it once and every source gets it.
  The endpoint and bot are separate processes but **both build from the same `./app`
  image** (`docker-compose.yml`: `api` and `bot` services), so a Dockerfile/requirements
  change reaches both automatically, and both will load the embedding model.
- **captures table** (`db/migrations/001_captures.sql`): `id, user_id, source, kind,
  content, file_path, file_name, mime_type, content_hash bytea, meta jsonb, created_at`.
  `content` holds text body / URL / media caption; `file_path` is `captures/<uuid>.<ext>`
  relative to `DATA_DIR` (`/data`); `kind ∈ text|url|photo|file|audio`.
- **DB image** is `pgvector/pgvector:pg16`; `init.sql` already ran `CREATE EXTENSION vector`
  and `pgcrypto`. pg16 has `websearch_to_tsquery` and STORED generated columns. pgvector in
  this image supports HNSW.
- **Migrations** are plain idempotent SQL files, wired two ways: mounted into
  `docker-entrypoint-initdb.d` (fresh-volume boot) AND applied to the live DB by a
  documented `psql` one-liner (M1's `001` set this pattern). Follow it exactly.
- **Dockerfile** (`app/Dockerfile`) is `python:3.12-slim`, plain `pip install -r
  requirements.txt`. No system packages installed yet — Tesseract needs `apt-get`.
- **requirements.txt** has: fastapi, uvicorn, psycopg[binary], pyjwt, bcrypt,
  python-multipart, pytest, httpx. **httpx is already present** — reuse it for URL fetching,
  no requests/aiohttp needed.
- **Dashboard** (`app/static/index.html` + `app.js`) is vanilla JS, no build. It already
  has: `authedFetch()` (bearer + one refresh retry), `loadList()` rendering captures with
  **`textContent` only** (the M1 stored-XSS fix — never reintroduce `innerHTML` on capture
  content), disabled-button/loading/error patterns. Search reuses all of this.
- `db.py` is a per-request `psycopg.connect` (no pool) — fine at single-user scale.
- Two real Telegram text rows plus any M1 test rows already exist with NULL embedding —
  the backfill (Step 6) must cover them so the 50-item exit test can include pre-M2 captures.

## Key decisions (ladder-checked)

- **Enrichment runs inline in `store_capture()`, synchronously — no worker, no job queue.**
  plan.md offers a `FOR UPDATE SKIP LOCKED` queue pattern, but M1 shipped no worker and at
  single-user / ~50-item volume inline clears the exit test. Enrich AFTER the dedup INSERT
  and only for NEW rows (skip duplicates). `ponytail:` inline enrich blocks the capture
  reply for embed(~0.1s) + OCR(~1-3s) + URL scrape(≤ its timeout); all under the M1 <10s
  budget. Ceiling → capture latency or laptop RAM hurts; upgrade = move enrich to a
  dedicated worker consuming a `SKIP LOCKED` queue over `WHERE embedding IS NULL`.
- **Bounded URL fetch (5s timeout, size cap, redirect cap).** A hung URL must never wedge
  the bot poll loop or blow the 10s reply budget. This cap is also the SSRF/DoS guard.
- **One `extracted jsonb` column, not five typed columns.** Task lists extracted_date /
  amounts / emails / phones / url_metadata separately, but nothing *queries* them
  relationally in M2 (search is by meaning + keyword). Existing convention is the `meta`
  jsonb blob — mirror it. `ponytail:` collapse to one `extracted jsonb`; add typed columns
  + indexes at M3+ when a feature actually filters (deadlines, `amount > x`, finance).
- **`search_tsv` is a STORED generated column, config `'simple'`** — Postgres maintains the
  FTS vector, zero app/trigger code (rung 4: DB feature over app code). `'simple'` (no
  stemming) is correct for mixed Malay+English; English stemming would mangle Malay tokens.
  It covers `content` + the searchable extracted text (OCR text, URL title/description), so
  keyword search reaches inside images and links. GIN index on it.
- **HNSW vector index (`vector_cosine_ops`), not IVFFlat.** HNSW builds on an empty/tiny
  table with good recall and no list-count tuning or rebuild; IVFFlat needs data + tuning.
  `ponytail:` at ~50 rows the index isn't load-bearing (a seq-scan `ORDER BY <=> LIMIT k`
  is sub-ms) — it's cheap, standard future-proofing for when the dataset grows.
- **Hybrid merge = Reciprocal Rank Fusion (RRF, k=60), done in Python.** Cosine distance and
  `ts_rank` are incomparable scales; RRF fuses by *rank* so no normalization is needed —
  the simplest scheme that reliably satisfies "top 3". Run two small `LIMIT 20` SQL queries,
  fuse by id in Python, return top N. `ponytail:` Python fusion of two ~20-row lists is
  clearer than a two-CTE full-outer-join SQL; move to SQL only if it ever gets hot.
- **Embedding lib: `sentence-transformers` + `intfloat/multilingual-e5-small`** (task-
  prescribed; model+dims locked per plan.md so any later swap must keep 384-dim). Loaded as
  a **lazy module-level singleton** (loaded once per process, not per request). `ponytail:`
  sentence-transformers pulls the full torch stack (~2GB image); `fastembed` (ONNX, no
  torch, same `multilingual-e5-small`, same 384-dim → no re-embedding) is the lighter swap
  if image size / RAM bites — noted, not taken now.
- **e5 prefixes are mandatory and easy to get wrong:** embed documents with `"passage: "`
  and queries with `"query: "`, `normalize_embeddings=True` (so cosine is valid). Getting
  this wrong silently tanks recall — call it out in every embed site.
- **No `pgvector` python package.** Bind the vector as a bracketed string cast `%s::vector`
  (`"[" + ",".join(map(str, vec)) + "]"`) — two lines, no dep. `ponytail:` add
  `pgvector[psycopg]` only if manual formatting ever gets error-prone.
- **Model baked into the image at build time**, not downloaded at runtime. One `RUN` warms
  `SentenceTransformer('intfloat/multilingual-e5-small')` into the image (~470MB layer);
  both api+bot share it, no first-request download stall, works offline, immutable image.
  `ponytail:` alternative = a shared named volume for the HF cache (smaller image, first-run
  download) — not worth the extra volume for one box.
- **Backfill is a run-once script, not an endpoint.** `python backfill.py` inside the
  container loops `WHERE embedding IS NULL` and calls the same `enrich()`. No new auth
  surface, no route to secure.

## Cut (deferred, with reason)
- **Job queue / worker service** — inline enrich clears the exit test at ~50 items; a
  `SKIP LOCKED` worker is the documented upgrade when latency/RAM actually hurts. (plan.md
  and ponytail both say don't build the queue speculatively.)
- **Typed extraction columns + their indexes** (extracted_date as a real `date`, amounts as
  numeric, GIN on emails, etc.) — M3+, when a feature filters on them. M2 stores everything
  in one `extracted jsonb`.
- **A second vector-DB / Meilisearch / Qdrant** — Postgres does vectors AND FTS. Explicitly
  banned by plan.md.
- **Generic plugin/registry extraction framework** — `extract.py` is a handful of plain
  functions called in sequence. No abstraction over one implementation each.
- **Re-embedding on content edit / model change migration** — captures are immutable after
  capture; there's no edit path yet. Model is locked at 384-dim, so no re-embed needed.
- **Voice-note transcription** (audio → text for search) — explicitly M7 (faster-whisper).
  Audio captures are searchable by caption/metadata only in M2.
- **yt-dlp / oEmbed deep video extraction** — plan.md's "honest expectation": login-walled
  TikTok/IG give URL + `<meta>` tags only. Tier-1 URL scrape gets og:title/description/
  image; that's the M2 target, not full video content.
- **Per-result highlight/snippet from ts_headline** — return `content` truncated in the UI;
  add `ts_headline` only if plain snippets prove insufficient for the exit test.
- **Malay Tesseract language pack decision left to the build:** include `tesseract-ocr-msa`
  if apt provides it cleanly, else ship `eng` only (English OCR still reads most Malay Latin
  text acceptably) — note it, don't block the image build on a missing pack.

## Files touched
- `db/migrations/002_search.sql` — **new**: embedding + extracted + generated tsvector
  columns, HNSW + GIN indexes. Idempotent, applied both ways (initdb mount + live psql).
- `app/extract.py` — **new**: Tier-1 heuristic extraction functions (URL scrape, OCR,
  dates/amounts/emails/phones regex) + the SSRF-guarded fetch.
- `app/embed.py` — **new**: lazy-singleton model loader + `embed_passage()` / `embed_query()`
  with the correct e5 prefixes and normalization; vector→string helper.
- `app/capture.py` — **edit**: add `enrich(...)`; call it inside `store_capture()` after a
  NEW-row insert; `UPDATE captures SET embedding, extracted`.
- `app/search.py` — **new**: `GET /api/v1/search` (vector + FTS queries, RRF merge).
- `app/main.py` — **edit**: `include_router(search_router)`; optional startup model warm.
- `app/backfill.py` — **new**: run-once enrich of rows `WHERE embedding IS NULL`.
- `app/static/index.html` + `app/static/app.js` — **edit**: search box + `search()`,
  reusing `authedFetch` + the `textContent` render.
- `app/requirements.txt` — **edit**: sentence-transformers, dateparser, beautifulsoup4,
  pytesseract, Pillow.
- `app/Dockerfile` — **edit**: `apt-get` Tesseract; bake the embedding model.
- `app/test_extract.py` — **new**: assert-based self-check for the pure extractors + SSRF
  guard + RRF fusion.
- `.github/workflows/ci.yml` — **edit**: run `test_extract.py`.
- `README.md` — **edit**: `## M2 — Search` run/backfill section.

## Steps

### 1. Migration — `db/migrations/002_search.sql`
New idempotent file (single-quoted literals, `IF NOT EXISTS` throughout):
```sql
ALTER TABLE captures ADD COLUMN IF NOT EXISTS embedding vector(384);
ALTER TABLE captures ADD COLUMN IF NOT EXISTS extracted jsonb NOT NULL DEFAULT '{}';
-- Postgres maintains this: FTS over content + the searchable extracted text (OCR, URL meta).
-- 'simple' config = no stemming, correct for mixed Malay+English.
ALTER TABLE captures ADD COLUMN IF NOT EXISTS search_tsv tsvector
  GENERATED ALWAYS AS (
    to_tsvector('simple',
      coalesce(content, '') || ' ' ||
      coalesce(extracted->>'ocr_text', '') || ' ' ||
      coalesce(extracted->>'url_title', '') || ' ' ||
      coalesce(extracted->>'url_description', ''))
  ) STORED;
CREATE INDEX IF NOT EXISTS captures_tsv_gidx ON captures USING GIN (search_tsv);
-- ponytail: HNSW not load-bearing at ~50 rows (seq scan is sub-ms); cheap future-proofing.
CREATE INDEX IF NOT EXISTS captures_embedding_hnsw
  ON captures USING hnsw (embedding vector_cosine_ops);
```
Apply to the live DB (same one-liner shape M1 documented):
`docker compose exec -T db psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" < db/migrations/002_search.sql`
Mount it into `docker-compose.yml` `db.volumes` as `002_search.sql` in `docker-entrypoint-initdb.d`
(after `001`), so a fresh-volume boot also gets it.
**Check:** `\d captures` shows `embedding vector(384)`, `extracted jsonb`, `search_tsv`
tsvector + both indexes; inserting a row and setting `content` populates `search_tsv`
automatically (`SELECT search_tsv FROM captures LIMIT 1` is non-empty).

### 2. Extraction — `app/extract.py`
Plain functions, stdlib `re` + httpx (installed) + bs4 + dateparser + pytesseract/PIL:
- `extract_emails(text) -> list[str]`, `extract_phones(text) -> list[str]`,
  `extract_amounts(text) -> list[str]` — stdlib `re`, no deps. Amounts: currency-ish
  `(?:RM|\$|€|£)\s?\d[\d,]*(?:\.\d+)?` (RM first — Malaysian ringgit is the common case).
- `extract_dates(text) -> list[str]` — `dateparser.search.search_dates(text)`; return ISO
  strings; `[]` on None. Wrap in try/except (dateparser can be slow/raise on junk).
- `fetch_url(url) -> str | None` — **SSRF-guarded** (trust boundary, see Security):
  reject non-`http(s)` schemes; resolve host, reject private/loopback/link-local/reserved
  IPs (`ipaddress.ip_address(...).is_private/is_loopback/is_link_local/is_reserved`); httpx
  GET `timeout=5`, `follow_redirects=True` but cap redirects, read at most ~512KB
  (`r.iter_bytes`, stop at cap), require an HTML-ish content-type. Return HTML text or None.
- `extract_url_metadata(url) -> dict` — `fetch_url` then bs4 (`html.parser` backend, no
  lxml dep): `{"url_title": <title or og:title>, "url_description": <meta description or
  og:description>, "url_image": <og:image>}`, missing keys omitted. Empty dict on fetch fail.
- `ocr_image(file_bytes) -> str` — `PIL.Image.open(BytesIO(...))` (set
  `Image.MAX_IMAGE_PIXELS` guard against decompression bombs), `pytesseract.image_to_string`.
  Return `""` on any failure (corrupt image, tesseract missing) — OCR is best-effort, never
  fatal to a capture.
`ponytail:` every extractor fails soft (returns empty) — a capture must save even if one
extractor errors on hostile input.
**Check:** `test_extract.py` (Step 9) asserts email/phone/amount/date regexes on samples and
that `fetch_url("http://127.0.0.1/")` / `fetch_url("file:///etc/passwd")` are rejected.

### 3. Embedding — `app/embed.py`
Lazy singleton (loaded once per process on first use):
```python
_model = None
def _get_model():
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer("intfloat/multilingual-e5-small")
    return _model

def embed_passage(text: str) -> list[float]:
    return _get_model().encode("passage: " + text, normalize_embeddings=True).tolist()

def embed_query(text: str) -> list[float]:
    return _get_model().encode("query: " + text, normalize_embeddings=True).tolist()

def to_pgvector(vec: list[float]) -> str:
    return "[" + ",".join(map(str, vec)) + "]"   # bind with %s::vector, no pgvector dep
```
`ponytail:` e5 REQUIRES the `passage:`/`query:` prefixes + normalization — omitting them
silently wrecks recall. Do not "simplify" them away.
**Check:** `python -c "from embed import embed_query; v=embed_query('hi'); assert len(v)==384"`.

### 4. Wire enrichment into `store_capture()` — `app/capture.py`
Add `enrich(text, kind, file_bytes, mime) -> tuple[str|None, dict]` returning
`(embedding_string_or_None, extracted_dict)`:
- `extracted = {}`; if `kind == "url"` (or content looks like a URL):
  `extracted |= extract_url_metadata(content)`.
- if `kind == "photo"` and `file_bytes`: `extracted["ocr_text"] = ocr_image(file_bytes)`.
- text fields: run `extract_dates/emails/phones/amounts` over `content` (+ ocr_text +
  url_title/description) and store non-empty lists into `extracted`.
- Build the **document text** = `content` + ` ` + ocr_text + ` ` + url_title + ` ` +
  url_description (all coalesced). If it's non-empty → `embedding = to_pgvector(
  embed_passage(doc_text))`, else `None` (nothing to embed, e.g. a bare audio file).
In `store_capture()`, in the **new-row branch only** (after the `RETURNING` row, before
`return`), call `enrich(...)` and:
`UPDATE captures SET embedding = %s::vector, extracted = %s WHERE id = %s`
(pass `None` embedding as `None`; `search_tsv` regenerates automatically from the new
`extracted`). Do NOT enrich on the duplicate path. Keep the existing orphan-file cleanup.
`file_bytes` is already in memory at this point (endpoint `await file.read()`, bot
`download_file`) — reuse it for OCR, don't re-read from disk.
**Check:** `curl -F text='Meet me RM50 on 3 Jan, a@b.com' ... /api/v1/capture` → 201; then
`SELECT extracted, embedding IS NOT NULL FROM captures WHERE id=<new>` shows the parsed
amount/date/email and a non-null embedding. Duplicate re-post does not re-enrich.

### 5. Search endpoint — `app/search.py`
`router = APIRouter()`; `GET /api/v1/search`, `Depends(require_access)`, params `q: str`,
`limit: int = 10`. If `q` blank → return `[]`.
- `qvec = to_pgvector(embed_query(q))`.
- **Vector query** (`K = 20`):
  `SELECT id, source, kind, content, file_name, created_at, 1 - (embedding <=> %s::vector)
   AS score FROM captures WHERE user_id=%s AND embedding IS NOT NULL
   ORDER BY embedding <=> %s::vector LIMIT 20` (bind qvec twice).
- **FTS query** (`K = 20`):
  `SELECT id, source, kind, content, file_name, created_at,
   ts_rank(search_tsv, websearch_to_tsquery('simple', %s)) AS score
   FROM captures WHERE user_id=%s AND search_tsv @@ websearch_to_tsquery('simple', %s)
   ORDER BY score DESC LIMIT 20`.
- **RRF merge** in Python: for each list, `rrf[id] += 1 / (60 + rank)` (rank 0-based); keep a
  `by_id` dict of the row payloads; sort ids by fused score desc; return top `limit` as list
  of dicts (same field shape as `GET /api/v1/captures` so the UI renders identically),
  include the fused `score`.
`ponytail:` RRF k=60 is the standard constant; two `LIMIT 20` lists fused in Python — no
score normalization, no gnarly SQL join.
**Check:** capture "notes on sleep and circadian rhythm" and a decoy; `GET /api/v1/search?q=sleep`
returns the sleep row rank 1; `?q=circadian` (keyword) also returns it; no bearer → 401.

### 6. Backfill — `app/backfill.py`
Run-once `__main__` script (reuses `enrich` + `get_conn`):
`SELECT id, kind, content, file_path, mime_type FROM captures WHERE embedding IS NULL`;
for each: read `file_bytes` from `DATA_DIR/<file_path>` if `file_path` set (for OCR), call
`enrich(...)`, `UPDATE ... SET embedding, extracted`. Print progress; commit per row so a
crash mid-run is resumable (next run picks up the still-NULL ones). Idempotent by the
`embedding IS NULL` filter.
Run: `docker compose exec api python backfill.py`.
**Check:** after run, `SELECT count(*) FROM captures WHERE embedding IS NULL` is 0 (except
rows with genuinely no embeddable text, e.g. bare audio); the pre-M2 Telegram rows are now
searchable.

### 7. main.py wiring — `app/main.py`
`from search import router as search_router`; `app.include_router(search_router)` (before the
static mount, so `/api/v1/*` wins). Optionally warm the model in `lifespan` startup
(`from embed import _get_model; _get_model()`) so the first capture doesn't eat the ~5-10s
model load and blow the 10s reply budget — one line, recommended.
**Check:** `docker compose up api` boots (model warm may add ~10s to startup); `/health`,
`/api/v1/captures`, `/api/v1/search` all respond.

### 8. Search UI — `app/static/index.html` + `app.js`
- `index.html`: add above `<ul id="list">` inside `#app`: a search `<input id="q">` + a
  "Search" button, and a "Clear" affordance. Reuse existing input/button styles.
- `app.js`:
  - `search()` → read `q`; if empty call `loadList()` (recent view); else
    `authedFetch('/api/v1/search?q=' + encodeURIComponent(q))`, then render results into
    `#list` using the **exact existing render loop** from `loadList` (kind badge +
    `textContent` for `content || file_name` + localtime meta — never `innerHTML`).
  - Wire the button + Enter key; disabled/loading/error states mirroring `save()`.
  - Extract the shared render into a `renderList(items)` helper so `loadList` and `search`
    don't duplicate it.
`ponytail:` reuse `authedFetch` + the XSS-safe render verbatim; no new rendering path.
**Check:** on the phone over Tailscale → log in → type "sleep" → Search → the sleep capture
is in the top results, rendered without a page reload; clearing the box restores the recent
list.

### 9. Self-check — `app/test_extract.py`
Assert-based, DB-free, no network (SSRF test hits only rejected local targets):
- `extract_emails("x a@b.com y") == ["a@b.com"]`; phone + `RM50`/`$5.00` amount asserts.
- `extract_dates("meet on 3 January 2026")` yields a 2026 date; junk → `[]`.
- `fetch_url("file:///etc/passwd")` and `fetch_url("http://127.0.0.1:80/")` both return None
  (SSRF guard — the security-relevant check).
- RRF fusion: given two ranked id-lists, an id appearing high in both outranks an id high in
  only one (import the fuse helper from `search.py`; keep it a pure function so it's testable).
**Check:** `cd app && python test_extract.py` → all asserts pass. Add to `ci.yml`.

### 10. Deps + image — `requirements.txt`, `Dockerfile`
- `requirements.txt` add: `sentence-transformers`, `dateparser`, `beautifulsoup4`,
  `pytesseract`, `Pillow`. (httpx already present.) Note: sentence-transformers pulls torch;
  to keep the image smaller install CPU-only torch first via
  `--extra-index-url https://download.pytorch.org/whl/cpu` (add a `torch` line + the index
  URL, or a pip config line in the Dockerfile).
- `Dockerfile`: before `pip install`, add Tesseract:
  `RUN apt-get update && apt-get install -y --no-install-recommends tesseract-ocr
   tesseract-ocr-eng && rm -rf /var/lib/apt/lists/*` (add `tesseract-ocr-msa` too if it
   installs cleanly — else eng-only, see Cut). After `pip install`, **bake the model**:
  `RUN python -c "from sentence_transformers import SentenceTransformer;
   SentenceTransformer('intfloat/multilingual-e5-small')"` (~470MB layer, both api+bot share
   it, no runtime download).
`ponytail:` no new compose service — `api` and `bot` already build `./app`, so both get
Tesseract + the baked model; the only cost is two model copies in RAM at single-user scale
(the marked ceiling in Key decisions).
**Check:** `docker build ./app` succeeds; `docker compose exec api tesseract --version` works;
first capture does not download the model (already baked).

## Verify (end-to-end — the M2 exit test)
1. Apply migration (Step 1), rebuild (`docker compose up -d --build`), run backfill (Step 6).
2. Capture 50+ real items across kinds (text, URLs, a couple of photos with text) via the
   bot + quick-note. Confirm each gets `embedding IS NOT NULL` and a populated `extracted`.
3. **By meaning:** search a paraphrase ("that article about sleep") → the intended capture
   is in the top 3.
4. **By keyword:** search an exact word from a different capture → that capture is in the
   top 3.
5. `cd app && python test_extract.py` passes; `test_auth.py` + `test_capture.py` still pass.

## Frontend?
**Yes.** A search box + results rendering added to the dashboard (`index.html` + `app.js`),
reusing `authedFetch` and the XSS-safe `textContent` render. Route to the frontend agent.

## Security pass?
**Yes — warranted.** M2 opens real new trust boundaries beyond M1's:
- **SSRF (the main one):** the URL-metadata scraper fetches a user/Telegram-supplied URL
  *server-side*. Without a guard it can hit `localhost`, private ranges, or cloud-metadata
  IPs. Review `fetch_url`: scheme allowlist (http/https only), private/loopback/link-local/
  reserved-IP rejection AFTER host resolution, 5s timeout, redirect cap, ~512KB read cap,
  content-type check.
- **Untrusted image → OCR:** Pillow/Tesseract process attacker-supplied image bytes.
  Decompression-bomb guard (`Image.MAX_IMAGE_PIXELS`), OCR fails soft, files already size-
  capped at 25MB (M1) and never served/executed.
- **New authed query endpoint** `/api/v1/search?q=` — SQL is fully parameterized
  (`websearch_to_tsquery` + bound qvec), reuses `require_access`; low risk but new input
  surface worth a look.
Scope the review to those three (SSRF fetch guard, OCR/image-bomb, the search endpoint) —
JWT/auth/file-storage were already cleared in M1 and are unchanged here.
