# 002 — M0 infrastructure scaffold (code + config, no live infra)

> **Superseded (2026-07, v1.5) by plans/003-m0-laptop-first-rework.md.** The app,
> DB schema, single-user JWT auth, CI, and backup/restore script logic below are
> unchanged and still current; only the hosting layer flipped — VPS/domain/ACME →
> laptop + Tailscale + Windows Task Scheduler. Read 003 for the current hosting spec.

## Goal
Scaffold every M0 file that runs on code/config alone — Docker Compose stack (Caddy + FastAPI hello-world + Postgres 16/pgvector), single-user JWT auth, corrected Postgres DDL, nightly restic backup script, and a CI workflow — so the only thing left before "log in from phone + restore works" is the user provisioning real infrastructure.

## Scope boundary (what "done" means after this pass)
- **Built now (code/config in-repo, runnable locally via `docker compose up`):** compose stack, Caddyfile, DB schema, FastAPI app with JWT login/refresh/me + health check, restic backup+restore scripts, GitHub Actions CI, `.env.example`, README setup section.
- **Manual user dependencies (OUT of scope — flagged, not blocking):** buy domain on Cloudflare Registrar + point DNS at VPS; create Hetzner CX22 VPS; harden Cloudflare account (2FA); create Backblaze B2 bucket + app key; create `.env` from `.env.example` with real secrets; run the stack on the VPS; wire the CI deploy secrets. These are the plan.md "Before M0" checklist items — Claude Code cannot do them.
- **Exit test remains manual:** logging in from the phone over the internet and running a real restore require the live VPS + domain + B2, so the M0 exit test is verified by the user after provisioning. This pass makes that a config-and-run exercise, not a coding exercise.

## Cut
- **No worker service** — pipeline is M1; M0 compose is caddy + api + db only.
- **No `captures`/`entities`/vector columns** — M0 needs only a `users` table; building the capture schema now is building ahead (plan.md "full schema comes in M1/M4").
- **No ORM (SQLAlchemy/Alembic)** — one table, raw psycopg3; add a migration tool at M1 when tables multiply.
- **No refresh-token store / rotation table** — stateless JWT refresh for a single user; revoke = rotate `JWT_SECRET`. `ponytail:` comment names the ceiling.
- **No `/data` volume in the backup yet** — no raw files exist until M1 capture; M0 backup dumps Postgres only, script has a commented `/data` line ready to uncomment.
- **No PWA/Pages deploy workflow** — no frontend code exists until M1; wiring an empty Next.js→Pages build now deploys nothing. Documented as the next workflow to add; CI covers the API only.
- **No pydantic-settings / python-dotenv** — `os.environ` (stdlib) reads config; compose injects `.env`.
- **No password-reset / user-management endpoints** — single user, hash lives in `.env`.

## Repo layout to create
```
Engram-OS/
├─ docker-compose.yml          # caddy + api + db
├─ Caddyfile                   # HTTPS reverse proxy → api:8000
├─ .env.example                # corrected, M0 vars only (+ commented M3 block)
├─ .gitignore                  # add: .env, __pycache__/, *.pyc
├─ db/
│  └─ init.sql                 # runs once on first DB boot (corrected DDL, fix #3)
├─ app/
│  ├─ Dockerfile
│  ├─ requirements.txt
│  ├─ main.py                  # app, /health, startup user-upsert, mounts auth
│  ├─ auth.py                  # /api/v1/auth/login, /refresh, /me + JWT + bcrypt
│  ├─ db.py                    # psycopg3 connection helper
│  └─ test_auth.py             # assert-based self-check (login/refresh/401)
├─ scripts/
│  ├─ backup.sh                # pg_dump | restic backup → B2
│  └─ restore.sh              # restic restore → psql (the exit-test half)
└─ .github/workflows/
   └─ ci.yml                   # lint + build image + run test_auth.py
```

## Steps

### 1. `.gitignore` + `.env.example`
File: `.gitignore` — append `.env`, `__pycache__/`, `*.pyc`.
File: `.env.example` — M0 vars only. Reference Appendix A fix #9 (single-user JWT):
```env
# --- Domain / HTTPS (Caddy) ---
DOMAIN=engram.example.com          # your Cloudflare-registered domain, DNS A-record → VPS IP
ACME_EMAIL=you@example.com         # Let's Encrypt account email

# --- Postgres ---
POSTGRES_USER=engram
POSTGRES_PASSWORD=change-me-long-random
POSTGRES_DB=engram
DATABASE_URL=postgresql://engram:change-me-long-random@db:5432/engram

# --- Single-user auth (Appendix A #9: no Supabase/Clerk) ---
AUTH_USERNAME=huzi
# bcrypt hash — generate with:
#   docker run --rm python:3.12-slim sh -c "pip -q install bcrypt && python -c \"import bcrypt;print(bcrypt.hashpw(b'YOUR_PASSWORD',bcrypt.gensalt()).decode())\""
AUTH_PASSWORD_HASH=$2b$12$replace-with-real-hash
JWT_SECRET=change-me-64-random-hex   # openssl rand -hex 32
ACCESS_TTL_MIN=30
REFRESH_TTL_DAYS=60

# --- restic backup → Backblaze B2 (NOT Cloudflare, on purpose) ---
RESTIC_REPOSITORY=b2:your-bucket-name:engram
RESTIC_PASSWORD=change-me-restic-encryption-passphrase
B2_ACCOUNT_ID=your-b2-keyID
B2_ACCOUNT_KEY=your-b2-applicationKey

# --- LLM slots: added in M3, unused in M0 (kept here so .env is one file) ---
# LLM_BASE_URL=https://api.openai.com/v1
# LLM_API_KEY=
# LLM_FAST=
# LLM_SMART=
```
Check: `grep -c '=' .env.example` matches the var count; no double-quoted SQL-style values.

### 2. Postgres DDL — `db/init.sql` (Appendix A fix #3)
Only the `users` table + enable pgvector (proves the `pgvector/pgvector:pg16` image works, even with no vector column yet). Corrected style: **single quotes** for string literals, correct `USING GIN (col)` syntax if any index appears. `pgcrypto` for `gen_random_uuid()`.
```sql
CREATE EXTENSION IF NOT EXISTS vector;      -- M0: prove pgvector loads; columns arrive M2
CREATE EXTENSION IF NOT EXISTS pgcrypto;    -- gen_random_uuid()

CREATE TABLE IF NOT EXISTS users (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    username      text NOT NULL UNIQUE,
    password_hash text NOT NULL,
    created_at    timestamptz NOT NULL DEFAULT now()
);
-- ponytail: single-user system. `users.id` is the user_id every M1+ table (captures,
-- entities, relations) will FK to, per locked decision "keep user_id for future-proofing".
-- No captures/vector/GIN objects here — that's M1/M2, don't build ahead (Appendix A context).
```
Note for executor: init.sql runs **only on first boot** (empty pgdata volume). Schema changes after M0 need a migration path (introduced M1), not edits to this file.
Check: `docker compose up db` boots clean; `\dt` shows `users`; `\dx` lists `vector` + `pgcrypto`. Confirms fix #3 SQL parses (the spec's double-quoted `DEFAULT "{}"` would error here).

### 3. FastAPI app
File: `app/requirements.txt` — pin latest stable:
```
fastapi
uvicorn[standard]
psycopg[binary]
pyjwt
bcrypt
```
File: `app/db.py` — one function: open a psycopg3 connection from `DATABASE_URL` (module-level connection or per-request; per-request `with psycopg.connect(...)` is fine at single-user scale). `ponytail:` comment: no pool, add `psycopg_pool` if concurrency ever matters.

File: `app/main.py`:
- `app = FastAPI()`, `include_router` from `auth.py`.
- Startup event: upsert the single user — read `AUTH_USERNAME` + `AUTH_PASSWORD_HASH` from env, `INSERT ... ON CONFLICT (username) DO UPDATE SET password_hash=...`. Keeps DB as source of truth for `users.id` while the password stays an env secret.
- `GET /health` → `{"status":"ok"}` after a `SELECT 1` against the DB; return 503 if the DB query raises (this is the reverse-proxy + DB liveness probe).

File: `app/auth.py` — single-user JWT (Appendix A #9), three endpoints + helpers:
- `POST /api/v1/auth/login` — body `{username, password}`; look up user row; `bcrypt.checkpw`; on success mint **access** JWT (`ACCESS_TTL_MIN`, claim `type=access`, `sub=user.id`) + **refresh** JWT (`REFRESH_TTL_DAYS`, `type=refresh`). Wrong creds → 401. Constant-time compare via bcrypt.
- `POST /api/v1/auth/refresh` — body `{refresh_token}`; decode + require `type=refresh`; mint a new access token. `ponytail: stateless refresh, no revocation list — rotate JWT_SECRET to invalidate all sessions; add a token table only if multi-device revoke is ever needed.`
- `GET /api/v1/me` — `Depends` on a `require_access` dependency that decodes the `Authorization: Bearer` token, requires `type=access`, returns `{id, username}`. This is the protected route the exit test hits from the phone.
- JWT helpers: `encode(sub, type, ttl)` / `decode(token)` using `pyjwt` HS256 with `JWT_SECRET`; map `ExpiredSignatureError`/`InvalidTokenError` → 401.

File: `app/Dockerfile` — `python:3.12-slim`, `pip install -r requirements.txt`, copy app, `CMD ["uvicorn","main:app","--host","0.0.0.0","--port","8000"]`.

Check: `curl -s localhost:8000/health` → ok; login with the env password returns two tokens; `/api/v1/me` with the access token returns the user; wrong password → 401; expired/absent token → 401.

### 4. `app/test_auth.py` — the one runnable check
Assert-based, no framework. Uses FastAPI `TestClient` against an in-process app with a throwaway DB (or monkeypatch the user lookup to a known bcrypt hash so it needs no DB — simpler, keep it DB-free). Asserts: correct login → 200 + both tokens; wrong password → 401; `/me` without token → 401; `/me` with minted access token → 200; refresh token rejected at `/me` (wrong `type`).
Check: `cd app && python -m pytest test_auth.py` OR `python test_auth.py` (guard with `if __name__=="__main__"`), all asserts pass. This is the CI gate.

### 5. Caddyfile
File: `Caddyfile` — env-substituted, automatic HTTPS via ACME:
```
{$DOMAIN} {
    tls {$ACME_EMAIL}
    reverse_proxy api:8000
}
```
Note: for local testing without a domain, run Caddy with `DOMAIN=localhost` (Caddy issues an internal cert) or hit `api:8000` directly. `ponytail:` — MCP server + Telegram webhook routes get added to this file at M1/M6, one `reverse_proxy` block each.
Check: with real DNS, `https://$DOMAIN/health` serves the API over a valid cert; locally, `docker compose up` starts Caddy without error.

### 6. `docker-compose.yml`
Three services, `.env` auto-loaded:
- **db**: `pgvector/pgvector:pg16`; env `POSTGRES_*`; volume `pgdata:/var/lib/postgresql/data`; mount `./db/init.sql:/docker-entrypoint-initdb.d/init.sql:ro`; `healthcheck: pg_isready`.
- **api**: `build: ./app`; `env_file: .env`; `depends_on: db (service_healthy)`; expose `8000` (internal only, no host port in prod — Caddy fronts it; optionally publish for local dev).
- **caddy**: `caddy:2`; `env_file: .env`; ports `80:80`, `443:443`; mount `./Caddyfile:/etc/caddy/Caddyfile:ro`; volumes `caddy_data`, `caddy_config` (cert persistence); `depends_on: api`.
- Named volumes: `pgdata`, `caddy_data`, `caddy_config`.
Check: `docker compose config` validates; `docker compose up` brings all three healthy; `/health` reachable through Caddy.

### 7. restic backup + restore scripts
File: `scripts/backup.sh` — bash, `set -euo pipefail`, sources `.env` (or relies on compose/cron env). Steps: `pg_dump` (via `docker compose exec -T db pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB"`) → pipe to a temp file → `restic backup` that file (repo/password/B2 creds from env) → `restic forget --keep-daily 7 --keep-weekly 4 --prune`. A commented `# restic backup /data` line ready for M1. `restic snapshots` at the end for a visible result.
File: `scripts/restore.sh` — `restic restore latest` → `psql` load into a scratch DB, print row counts. This script IS the "restore from backup works" half of the exit test; keep it real, not a stub.
Scheduling: **host crontab**, not a container (laziest — no extra service). README documents the line:
```
0 3 * * *  cd /opt/engram && ./scripts/backup.sh >> /var/log/engram-backup.log 2>&1
```
`ponytail: host cron over a scheduler container — add a compose cron service only if the VPS ever runs cron-less.`
Check (local, no B2): point `RESTIC_REPOSITORY` at a local path (`restic init` a temp repo), run `backup.sh` then `restore.sh`, confirm the `users` row survives the round-trip. This validates the script logic without needing B2.

### 8. GitHub Actions CI — `.github/workflows/ci.yml`
On push/PR: `python:3.12`, `pip install -r app/requirements.txt`, run `python -m pytest app/test_auth.py`, then `docker build ./app` (proves the image builds). No deploy step in M0 — deploy secrets (VPS SSH, Pages token) don't exist yet.
`ponytail:` header comment: the PWA-build-in-Actions workflow (plan.md M0: "frontend builds run in GitHub Actions, never on the VPS") is added when the Next.js app lands in M1+ — an empty Pages deploy now ships nothing.
Check: workflow YAML is valid (`act` or a push); the pytest + docker-build job is green.

### 9. README setup section
Append an M0 "Run it" section: the Before-M0 manual checklist (domain, VPS, Cloudflare 2FA, B2 bucket, OpenAI key deferred to M3, Telegram deferred to M1), how to generate `AUTH_PASSWORD_HASH` and `JWT_SECRET`, `cp .env.example .env`, `docker compose up -d`, the cron line, and how to run `restore.sh` for the exit-test drill.
Check: a reader can go from fresh VPS → logged in by following it, with no code edits.

## Verify (end-to-end, once user has infra)
1. `docker compose up -d` on the VPS → all three services healthy.
2. `https://$DOMAIN/health` returns `ok` over a valid Let's Encrypt cert.
3. From the phone browser: POST login → get tokens → GET `/api/v1/me` with the access token returns the user. (Exit test half 1.)
4. Run `scripts/backup.sh`, then on a scratch DB run `scripts/restore.sh`, confirm the `users` row restores. (Exit test half 2.)
Local pre-infra proxy for steps 3–4: same flow with `DOMAIN=localhost` and a local restic repo — proves all code/config before any money is spent.

## Frontend?
**No.** M0 is infra + API only; the Next.js dashboard/PWA starts at M1. No UI files are created in this pass. Route to the frontend agent when M1's quick-note box and captures list are built, not here.
