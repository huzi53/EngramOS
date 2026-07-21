# Engram

> *engram (n.) — the physical trace a memory leaves in the brain.*

A personal memory OS: capture anything from your phone in under 10 seconds, have it
automatically organized, linked, and searchable by meaning — self-directed, hosted for
€0/month on the laptop you already own, with zero manual filing.

**Capture → Store → Organize → Link → Understand → Reason → Act**

## Status

📋 **Planning complete (v1.5) — build not started.**
The full audited build plan is in [plan.md](plan.md) (milestones M0–M7, architecture,
budget, risks, and the 12 spec flags that were found and fixed). v1.5 adds the
HuziOS/Engram convergence: laptop-first €0 hosting, HuziOS glass UI as the eventual
interface (M3.5), Obsidian vault indexed rather than migrated.

## Architecture at a glance

- **One box (yours):** the laptop — Docker Compose via WSL2 · Caddy · FastAPI · worker · Telegram bot poller. Phone reaches the dashboard over Tailscale; Tailscale Funnel exposes the two surfaces that need public HTTPS (email ingestion, claude.ai MCP connector). A Hetzner-VPS graduation runbook is documented from M0 — an afternoon move, made only when laptop uptime actually hurts
- **One database:** PostgreSQL 16 + pgvector (vectors, full-text search, graph tables, job queue)
- **Capture:** Telegram bot via long-polling (text, links, photos, files, voice — offline queueing free, no public IP needed) + dashboard quick-note as the direct private path; no app store, no native build
- **Interface:** HuziOS's glass UI, ported panel-by-panel onto Engram's API at M3.5 (strangler fig — HuziOS stays the untouched daily driver until then); the Obsidian vault stays source of truth for study content and is indexed **read-only** into the same search space
- **AI tiers:** Python heuristics (free) → cloud fast model (classify) → cloud smart model (enrich/briefing), hard daily budget cap
- **AI provider:** replaceable by design — any OpenAI-compatible API via `.env` config, restricted to providers that don't train on API traffic (start: OpenAI); swaps gated by a classification eval set
- **Mentor mode:** Engram exposes a remote MCP server; claude.ai (existing Pro sub) is the mentor interface — zero API cost for reasoning
- **Embeddings:** multilingual-e5-small (Malay + English), 384-dim, CPU
- **Running cost:** €0/mo hosting + one-time ~$10 API topup (~a year); domain ~$10/yr only at M5 (email); backups on Backblaze B2 free tier

## Roadmap

| Milestone | Delivers |
|---|---|
| M0 | Infra live on the laptop: Docker, Tailscale HTTPS, auth, B2 backups |
| M1 | Capture via Telegram bot (long-polling) from any device, <10s |
| M2 | Hybrid semantic + keyword search |
| M3 | Auto-classification (budget-capped) |
| M3.5 | HuziOS glass UI ported onto Engram + Obsidian vault indexed read-only |
| M4 | Entity graph, related captures, projects |
| M5 | Morning briefing, rediscovery, email ingestion |
| M6 | Deep enrichment, mentor via claude.ai MCP connector |
| M7 | Hardening, export, voice, optional native app |

MVP = M0–M3, ~1 month of build sessions.

## M0 — Run it

### Before you start (manual, one-time, outside this repo)
- Docker Desktop with the **WSL2 backend** installed and running.
- **Tailscale** installed on this laptop and on your phone, both logged into the same tailnet; enable HTTPS in the tailnet admin console (MagicDNS + HTTPS certs). Verify the phone can reach the laptop on **mobile data**, not just home Wi-Fi.
- Create a Backblaze B2 bucket + application key (kept off Cloudflare on purpose — see plan.md).
- OpenAI API key: not needed yet, deferred to M3.
- Telegram bot token: not needed yet, deferred to M1.

### Configure
```bash
cp .env.example .env
```
Fill in `.env`:
- `POSTGRES_*` / `DATABASE_URL` — pick a long random Postgres password.
- `AUTH_USERNAME` — your login username.
- `AUTH_PASSWORD_HASH` — generate with:
  ```bash
  docker run --rm python:3.12-slim sh -c "pip -q install bcrypt && python -c \"import bcrypt;print(bcrypt.hashpw(b'YOUR_PASSWORD',bcrypt.gensalt()).decode())\""
  ```
  Wrap the result in single quotes when you paste it into `.env` (`AUTH_PASSWORD_HASH='$2b$12$...'`) — otherwise Docker Compose's env_file interpolation and bash's `source` treat `$2b` etc. as variable references and silently blank them out.
- `JWT_SECRET` — generate with `openssl rand -hex 32`.
- `RESTIC_REPOSITORY` / `RESTIC_PASSWORD` / `B2_ACCOUNT_ID` / `B2_ACCOUNT_KEY` — from your B2 bucket + key.

### Run
```bash
docker compose up -d
```
This brings up Postgres, the API, and Caddy (plain HTTP, bound to `127.0.0.1:8080`). Expose it over Tailscale from the **Windows host** (not inside a container):
```powershell
tailscale serve --bg https / http://localhost:8080
```
Access from your phone at `https://<your-machine>.<your-tailnet>.ts.net/` — Tailscale's automatic cert is already trusted, no warning. Local check on the laptop: `curl http://localhost:8080/health` (or `curl http://localhost:8000/health` direct to the API) → `{"status":"ok"}`.

Log in:
```bash
curl -X POST https://<your-machine>.<your-tailnet>.ts.net/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"<AUTH_USERNAME>","password":"<your password>"}'
```
Use the returned `access_token` as `Authorization: Bearer <token>` against `GET /api/v1/me`.

### Backups
Schedule nightly via **Windows Task Scheduler** (the laptop has no host crontab). The script itself runs unchanged under WSL2 bash; Task Scheduler just invokes it via `wsl.exe`:
- Program/script: `wsl.exe`
- Arguments: `bash -lc "cd /mnt/c/Users/<you>/.../Engram-OS && ./scripts/backup.sh >> /tmp/engram-backup.log 2>&1"`
- Trigger: daily 03:00.
- **Conditions tab → check "Wake the computer to run this task"**, and in Windows **Power Options → Sleep → Allow wake timers = Enabled** — so the job fires even if the laptop is asleep. The laptop must still be powered on (plugged in) for the wake timer to work.

To drill the restore half of the exit test: run `./scripts/backup.sh`, then `./scripts/restore.sh` — it restores the latest snapshot into a scratch DB and prints the `users` row count so you can confirm the data survived.

Laptop uptime becomes a real problem? See [`docs/vps-graduation.md`](docs/vps-graduation.md) for the afternoon move to a VPS.

## M1 — Capture

Adds a captures table, `POST /api/v1/capture` (text/URL/photo/file/audio), a Telegram
long-polling bot (no webhook, no public endpoint), and a minimal dashboard (quick-note +
captures list) served as static HTML/JS from the API.

### One-time: apply the migration
The M0 stack is already running, so the new table isn't picked up by `init.sql` (that
only runs on first boot of an empty pgdata volume). Apply it directly:
```bash
docker compose exec -T db psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" < db/migrations/001_captures.sql
```

### Configure
Add to `.env` (see `.env.example`):
- `TELEGRAM_BOT_TOKEN` — from [@BotFather](https://t.me/BotFather).
- `TELEGRAM_ALLOWED_CHAT_ID` — message the bot once, then read `chat.id` from
  `https://api.telegram.org/bot<token>/getUpdates`. Every other chat id is silently ignored.
- `DATA_DIR=/data` — where captured files land inside the containers.

### Run
```bash
docker compose up -d
```
Brings up `db`, `api`, `bot`, and `caddy`. The bot has no ports and needs no Caddy route —
long-polling is outbound only. Check `docker compose logs bot` for `polling as <user_id>`.

Dashboard: `https://<your-machine>.<your-tailnet>.ts.net/` — log in, type a note, hit Save.
Telegram: forward a link, photo, or voice note to the bot — each replies "Saved ✅" (or
"Already saved" if you forward the same thing twice, thanks to blake2b exact-dedup).

Files land on the host at `./data/captures/`; `scripts/backup.sh` now backs that up
alongside the Postgres dump.

Self-check: `cd app && python test_capture.py` → `all asserts passed`.

## M2 — Search

Adds Tier-1 heuristic extraction (URL title/description, OCR on photos, dates/amounts/
emails/phones), a 384-dim multilingual embedding per capture, and one hybrid search
endpoint (`GET /api/v1/search?q=`, pgvector cosine + Postgres full-text, RRF-merged)
behind a search box on the dashboard. Enrichment runs inline inside `store_capture()` —
no worker, no job queue (see `plans/005-m2-search.md`).

### One-time: apply the migration
```bash
docker compose exec -T db psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" < db/migrations/002_search.sql
```

### Rebuild (bakes Tesseract + the embedding model into the image)
```bash
docker compose up -d --build
```

### Backfill pre-M2 captures
Existing rows have no embedding yet — run once after the migration + rebuild:
```bash
docker compose exec api python backfill.py
```

### Run
Dashboard now has a search box above the captures list: type a query, hit Search (or
press Enter) — results are ranked by meaning + keyword, top-N first. Clear the box (or
the Clear button) to go back to the recent-captures view.

Self-check: `cd app && python test_extract.py` → `all asserts passed`.
