# TODO

Running checklist for the Engram-OS + HuziOS repo work. Updated as steps complete.

## Done — 2026-07-21

- [x] Pulled `origin/main` (v1.4 → v1.5, "HuziOS/Engram convergence"); merged clean
      with local uncommitted M0 footnotes in `plan.md` (no conflict markers).
- [x] Found `huzi53/HuziOS` was **public** with the full Obsidian vault tracked in git
      (personal ACCA notes + copyrighted course PDFs/PPTs) — flagged to user.
- [x] Set `huzi53/HuziOS` to **private**.
- [x] Created `huzi53/huzios-public` — clean-history export of app code + docs only
      (`app/`, `CLAUDE.md`, `journey-into-HuziOS.md`, `start.cmd`, `start-hidden.vbs`).
      `vault/`, `backups/`, `.claude/`, `plans/` never entered its history.
- [x] Scanned both exports for hardcoded secrets/API keys/tracked `.env` — none found.
- [x] Added MIT `LICENSE` to `engram-os` and `huzios-public`.
- [x] Added GitHub topics to both public repos for discoverability.
- [x] Committed + pushed the v1.5 merge to `engram-os`.

## M0 laptop-first rework (decision made: proceeding, full pipeline)

- [x] Planner: wrote `plans/003-m0-laptop-first-rework.md`. Decision: HTTPS via
      `tailscale serve` (not Caddy internal CA — avoids phone cert warnings), Caddy
      stays as internal reverse proxy. `plans/002` marked superseded, not rewritten.
      Frontend: no. Security pass: not warranted this round (auth.py/JWT/backup creds
      unchanged; only change is network exposure shrinking VPS-public → tailnet-only).
- [x] Builder: executed `plans/003-m0-laptop-first-rework.md`, 8/8 steps, no deviations.
      Caddyfile → plain reverse proxy (Tailscale terminates TLS); .env.example dropped
      DOMAIN/ACME_EMAIL; compose Caddy port → 127.0.0.1:8080 only, dropped cert volumes;
      README "Run it" rewritten for WSL2/Tailscale/Task Scheduler; new
      `docs/vps-graduation.md` runbook; plans/002 marked superseded. Committed `86c2fbc`
      (not pushed). `pytest app/test_auth.py` → 6 passed. Docker/WSL2 not present in this
      environment — compose/Caddy/backup round-trip checks are static-only, not
      runtime-verified; real verification needs the actual laptop.
- [x] Simplifier: reviewed full commit `86c2fbc` diff — nothing to cut, no speculative
      abstractions/dead config found. `pytest` re-run (6 passed), compose/CI YAML
      re-validated with `yaml.safe_load`. 0 lines removed, shipped as-is.
- [x] Reviewer: verdict SHIP. 3 low-severity non-blocking findings, fixed directly
      (commit `b7c36ac`): auth.py 500-on-malformed-hash → 401; restore.sh missing
      `ON_ERROR_STOP=1` (silent partial restore); backup.sh leaking temp dirs.
      Verified: JWT logic sound (no alg confusion, correct type-gating, bcrypt
      constant-time), no leftover DOMAIN/ACME_EMAIL refs, init.sql/restore target
      a scratch DB not the live one. `pytest` 6 passed after fixes.
- [x] Security: skipped — planner's call confirmed by reviewer (auth.py logic
      unchanged in scope, only a failure-mode fix; network exposure strictly shrank).
- [x] Frontend: skipped — no UI in this pass.
- [x] Verifier: **PASS WITH GAPS**. Ran `pytest` (6 passed), validated compose/CI YAML,
      traced the Caddy port chain (`:80` → `127.0.0.1:8080` → `tailscale serve localhost:8080`,
      consistent), grepped repo clean of stray DOMAIN/ACME_EMAIL, proved the auth.py fix
      by reproducing `bcrypt.checkpw` raising `ValueError` on a malformed hash, `bash -n`
      on both scripts. Honest gaps (expected, sandbox has no Docker/WSL2/Tailscale/restic):
      live `docker compose up`, live `tailscale serve` + phone login, live backup→restore
      round-trip. **These three need to be run for real on the actual laptop before M0 is
      truly done** — see "Still needs the user's laptop" below.
- [x] Commits landed: `86c2fbc` (rework + first-time scaffold commit), `b7c36ac`
      (reviewer-fix follow-up). Not yet pushed to origin.

## Still needs the user's laptop (can't run in this sandbox)

- [ ] Install/confirm Docker Desktop + WSL2 + Tailscale on the actual laptop.
- [ ] `docker compose up -d` → confirm db/api/caddy all healthy.
- [ ] `tailscale serve --bg https / http://localhost:8080`, then log in from the phone
      over mobile data (not home wifi) — the real M0 exit test, half 1.
- [ ] `./scripts/backup.sh` then `./scripts/restore.sh` against a real/local restic repo,
      confirm the `users` row survives — exit test half 2.
- [ ] Push `main` to origin once the above is confirmed working.
