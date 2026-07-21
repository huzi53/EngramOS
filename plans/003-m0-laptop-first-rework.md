# 003 — M0 laptop-first rework (hosting flip: VPS/domain → laptop + Tailscale)

## Goal
Rework the untracked M0 scaffold from VPS/domain/ACME hosting to laptop-first hosting (Docker Compose via WSL2 + HTTPS over Tailscale + Windows Task Scheduler backups) per plan.md v1.5, then commit the whole scaffold.

## Context (verified, not assumed)
- plan.md v1.5 M0 (line 114) + Decisions "Access" row (line 12): laptop-first, €0/mo, phone reaches it over Tailscale exactly as HuziOS is reached today; Telegram uses long-polling (no public endpoint); VPS is a graduation path with a runbook written day one.
- Only the **hosting/HTTPS/backup-scheduling** layer flips. The app (`app/*`), DB schema (`db/init.sql`), single-user JWT auth (`app/auth.py`), CI (`.github/workflows/ci.yml`), and the backup/restore **script logic** are hosting-agnostic and stay as-is. Verified: `scripts/backup.sh`/`restore.sh` hardcode nothing VPS-specific (they drive `docker compose exec` + restic; identical on laptop or VPS).

## Decision: HTTPS mechanism — Tailscale Serve, not Caddy internal CA
Reject **Caddy internal CA**: the phone would get cert warnings unless its Tailscale-issued root CA is manually installed — fails the "log in from phone, feels normal" spirit of the exit test.
Choose **`tailscale serve`**: Tailscale terminates TLS with its automatic, phone-trusted `*.ts.net` Let's Encrypt cert (DNS-01, nothing exposed publicly), auto-renewing, zero cert files to manage. It reuses the Tailscale client already on this laptop for HuziOS (ladder rung 2), needs no custom Caddy image (rung 5: no new dep), and M5/M6's public surfaces are the same tool (`tailscale funnel`). Caddy stays as the internal **HTTP** reverse proxy so the M1/M6 route blocks the scaffold already anticipates still have a home; `tailscale serve` fronts it.
- Rejected alternative `caddy-tailscale` plugin (Caddy joins the tailnet, one service): needs an `xcaddy` custom build + `TS_AUTHKEY` — a build step and dependency the host's existing Tailscale makes unnecessary.
- Fallback noted in runbook only: `tailscale cert` + mount files into Caddy, if the user ever wants Caddy to terminate TLS.

## Cut
- **No `TS_HOSTNAME`/Tailscale env var in `.env.example`** — `tailscale serve` runs on the host and Caddy reverse-proxies regardless of host header; nothing in the stack reads the tailnet name. YAGNI.
- **No custom Caddy image / caddy-tailscale plugin** — host `tailscale serve` covers M0; a build step earns nothing here.
- **No second (ACME) Caddyfile kept in-repo** — the VPS variant is a 3-line snippet documented in the graduation runbook, not a maintained parallel file. YAGNI.
- **No `caddy_data`/`caddy_config` volumes** — they only persisted ACME/internal-CA certs; with Caddy on plain internal HTTP there's nothing to persist.
- **No changes to `app/*`, `db/init.sql`, CI, or the backup/restore script bodies** — hosting-agnostic; touching them is churn.
- **No backup wrapper script** — Task Scheduler invokes the existing `backup.sh` via one `wsl.exe bash -lc` line; a wrapper adds a file for nothing.
- **No rewrite of plans/002** — superseded with a one-line header pointer (most of it still describes unchanged app/DB/auth/CI/script work).

## Files touched
- `Caddyfile` — strip ACME/domain, become internal HTTP reverse proxy.
- `.env.example` — drop the DOMAIN/ACME_EMAIL block.
- `docker-compose.yml` — Caddy: drop public `80:80`/`443:443` + cert volumes, bind to `127.0.0.1` only.
- `README.md` — rewrite the `## M0 — Run it` section (Before-you-start, Configure, Run, Backups).
- `docs/vps-graduation.md` — **new**, the graduation runbook.
- `plans/002-m0-infra-scaffold.md` — add a one-line "superseded" header note.
- (unchanged, but committed): `app/*`, `db/init.sql`, `scripts/*.sh`, `.github/workflows/ci.yml`, `.env.example`, `.gitignore`.

## Steps

### 1. `Caddyfile` — internal HTTP reverse proxy (Tailscale fronts TLS)
Replace the whole file with:
```
# HTTP only — TLS is terminated by `tailscale serve` on the host (see README).
# M1/M6 add more reverse_proxy blocks here (MCP server, Telegram is long-poll so no route).
:80 {
    reverse_proxy api:8000
}
```
Removes `{$DOMAIN}` + `tls {$ACME_EMAIL}` (no domain, no public ACME on the laptop).
Check: `docker compose config` still validates; `docker compose up caddy api` starts Caddy with no ACME/cert errors in logs.

### 2. `.env.example` — drop DOMAIN / ACME_EMAIL
Delete lines 1–3 (the `# --- Domain / HTTPS (Caddy) ---` block). Leave Postgres, single-user auth, restic/B2, and the commented M3 LLM block exactly as they are (not VPS-specific). Keep the `AUTH_PASSWORD_HASH='...'` single-quote convention.
Check: no remaining `DOMAIN` or `ACME_EMAIL` references anywhere — `grep -rn 'ACME_EMAIL\|DOMAIN' Caddyfile .env.example docker-compose.yml README.md` returns nothing (the runbook may mention them; that's fine).

### 3. `docker-compose.yml` — de-expose Caddy for a Tailscale-fronted laptop
In the `caddy` service:
- Replace `ports: ["80:80","443:443"]` with a single localhost-only binding: `ports: ["127.0.0.1:8080:80"]` (Docker Desktop publishes to the Windows host's localhost; `tailscale serve` picks it up there; `8080` avoids clashing with anything on Windows port 80).
- Remove the `caddy_data`/`caddy_config` volume mounts (no certs to persist now).
- Remove `caddy_data` and `caddy_config` from the top-level `volumes:` block (leave `pgdata`).
Leave `db` and `api` untouched (`api` keeps its `127.0.0.1:8000:8000` local-dev binding).
Check: `docker compose config` validates; `docker compose up -d` brings db+api+caddy healthy; `curl http://localhost:8080/health` → `{"status":"ok"}` through Caddy.

### 4. `README.md` — rewrite `## M0 — Run it` (lines 47–94)
- **Before you start:** drop domain purchase, Hetzner VPS, Cloudflare 2FA. Add:
  - Docker Desktop with the **WSL2 backend** installed and running (matches plan.md Dependencies line 216).
  - **Tailscale** on laptop + phone, logged into the same tailnet; enable HTTPS in the tailnet admin (MagicDNS + HTTPS certs). Verify the phone reaches the laptop on **mobile data**, not just home Wi-Fi.
  - Backblaze B2 bucket + app key (unchanged). OpenAI key → deferred M3, Telegram token → deferred M1 (unchanged).
- **Configure:** drop the `DOMAIN` / `ACME_EMAIL` bullet. Keep the rest (Postgres, `AUTH_*`, `JWT_SECRET`, restic/B2) verbatim, including the single-quote warning for `AUTH_PASSWORD_HASH`.
- **Run:** `docker compose up -d`, then expose over Tailscale from the **Windows host** (not inside a container):
  ```powershell
  tailscale serve --bg https / http://localhost:8080
  ```
  Access from the phone at `https://<your-machine>.<your-tailnet>.ts.net/` (trusted cert, no warning). Local check on the laptop: `curl http://localhost:8080/health` (or `http://localhost:8000/health` direct to the API).
  Update the login `curl` example to use the ts.net URL instead of `https://$DOMAIN`.
- **Backups:** replace the crontab block with **Windows Task Scheduler + wake timer**. The script runs unchanged under WSL2 bash; Task Scheduler invokes it via `wsl.exe`:
  - Program/script: `wsl.exe`
  - Arguments: `bash -lc "cd /mnt/c/Users/<you>/.../Engram-OS && ./scripts/backup.sh >> /tmp/engram-backup.log 2>&1"`
  - Trigger: daily 03:00.
  - **Conditions tab → check "Wake the computer to run this task"**, and in Windows **Power Options → Sleep → Allow wake timers = Enabled**, so the job fires even if the laptop is asleep (the v1.5 requirement that scheduled jobs actually fire). Note the laptop must be powered on (plugged in) for the wake timer to run.
  - Keep the restore-drill instructions (`backup.sh` then `restore.sh`) as-is.
Check: a reader with a fresh WSL2+Docker+Tailscale laptop can go from clone → phone login → backup task, no code edits, no domain, no VPS.

### 5. `scripts/backup.sh` / `restore.sh` — confirm WSL2-clean, no edits
Read-confirmed hosting-agnostic: `set -euo pipefail`, `cd "$(dirname "$0")/.."`, `source .env`, `docker compose exec -T`, `restic`, `mktemp` — all work in WSL2 bash with Docker Desktop's WSL integration. **No changes.** The only new thing is *how they're invoked* (Task Scheduler → `wsl.exe`), documented in step 4.
Check: from a WSL2 shell in the repo, `./scripts/backup.sh` runs against a local restic repo (point `RESTIC_REPOSITORY` at a temp path, `restic init` it) then `./scripts/restore.sh` — the `users` row survives the round-trip (validates logic without B2).

### 6. `docs/vps-graduation.md` — new graduation runbook (short)
Create `docs/` + this file. Trigger line first (real laptop-uptime pain, per plan.md line 226), then the afternoon runbook:
1. **Provision** a Hetzner CX22 with the Docker-preinstalled image; `git clone` the repo; `cp .env.example .env` and fill the same secrets.
2. **Domain (deferred until now):** buy on Cloudflare Registrar, enable account 2FA, add an A-record → VPS IP. This is the point those pre-M0-in-v1.4 steps come back.
3. **Re-enable public HTTPS:** re-add `DOMAIN` + `ACME_EMAIL` to `.env` and swap the Caddyfile back to the ACME variant (paste-in snippet):
   ```
   {$DOMAIN} {
       tls {$ACME_EMAIL}
       reverse_proxy api:8000
   }
   ```
   and restore `ports: ["80:80","443:443"]` + `caddy_data`/`caddy_config` volumes in `docker-compose.yml`. No `tailscale serve` needed on the VPS (though Tailscale still works for admin).
4. **Migrate data** (pick one): (a) `pg_dump` on the laptop → `psql` restore on the VPS, or (b) since backups already go to B2, run `scripts/restore.sh` on the VPS against the same `RESTIC_REPOSITORY` — restic re-points by simply reusing the same env, no repo move.
5. **Re-point scheduling:** the VPS is Linux, so backups move from Windows Task Scheduler back to host crontab: `0 3 * * *  cd /opt/engram && ./scripts/backup.sh >> /var/log/engram-backup.log 2>&1`.
6. `docker compose up -d`; verify `https://$DOMAIN/health`; stop the laptop stack.
Check: file exists, is skimmable in a couple minutes, and every step maps to an existing repo artifact.

### 7. `plans/002-m0-infra-scaffold.md` — mark superseded
Insert a blockquote note directly under the H1 title:
```
> **Superseded (2026-07, v1.5) by plans/003-m0-laptop-first-rework.md.** The app,
> DB schema, single-user JWT auth, CI, and backup/restore script logic below are
> unchanged and still current; only the hosting layer flipped — VPS/domain/ACME →
> laptop + Tailscale + Windows Task Scheduler. Read 003 for the current hosting spec.
```
Check: the two specs no longer contradict silently — 002 points forward.

### 8. Commit the reworked scaffold
All scaffold files are still untracked (never committed). After steps 1–7, stage and commit the whole M0 body of work in one commit:
```
git add docker-compose.yml Caddyfile .env.example .gitignore app/ db/ scripts/ \
        .github/ docs/ README.md plans/002-m0-infra-scaffold.md \
        plans/003-m0-laptop-first-rework.md
git commit
```
Message: `M0 scaffold: laptop-first infra (Compose/WSL2 + Tailscale HTTPS + Task Scheduler backups)` with the standard `Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>` trailer. Commit to `main` (matches this repo's history of committing plan/infra work directly to main); branch first only if the pipeline prefers isolation.
Check: `git status` clean for these paths; `git log -1` shows the commit.

## Verify (end-to-end)
1. `docker compose up -d` → db+api+caddy healthy; `curl http://localhost:8080/health` → `ok`.
2. `tailscale serve --bg https / http://localhost:8080` on the Windows host; from the phone on **mobile data**, `https://<machine>.<tailnet>.ts.net/api/v1/auth/login` returns tokens and `GET /api/v1/me` with the access token returns the user. (Exit-test half 1.)
3. `./scripts/backup.sh` then `./scripts/restore.sh` (local restic repo) → `users` row survives. (Exit-test half 2.)
4. `docs/vps-graduation.md` exists; plans/002 shows the superseded note; the scaffold is committed.

## Frontend?
**No.** Infra/config only — Caddyfile, compose, `.env.example`, README, one docs file, one plan note. No UI code exists or is touched; the dashboard starts at M1.

## Security pass?
**Not warranted for this pass.** Trust-boundary code exists in scope (`app/auth.py` JWT/bcrypt, restic/B2 credentials) but this rework touches **none** of it — no auth, crypto, or credential-handling lines change. The only security-relevant change is the network exposure model, and it strictly *reduces* attack surface: Caddy moves from a public `0.0.0.0:443` ACME endpoint to a `127.0.0.1`-only port reachable solely over the authenticated Tailscale tailnet. A security review is due when auth.py or the capture/API trust boundary actually changes (M1+), not here.
