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

- [x] Docker Desktop + WSL2 (Ubuntu) + Tailscale — all confirmed installed and running
      (Docker Desktop just needed launching + login; CLI at
      `C:\Users\xyqie\AppData\Local\Programs\DockerDesktop\resources\bin\docker.exe`).
- [x] `.env` created from `.env.example`. `POSTGRES_PASSWORD`/`DATABASE_URL` and
      `JWT_SECRET` auto-generated (random, low-sensitivity). `RESTIC_*`/`B2_*` left as
      placeholders — user doesn't have a Backblaze B2 account yet, deferred as its own
      step (doesn't block compose/login).
- [x] User generated `AUTH_PASSWORD_HASH` themselves (password never entered this
      chat), wired into `.env`.
- [x] `docker compose up -d` → db healthy, api + caddy started.
      `curl localhost:8080/health` → `{"status":"ok"}`.
- [x] Login confirmed working locally with real credentials → returned `access_token`.
- [x] `tailscale serve --bg http://localhost:8080` enabled (had to approve Serve for
      the tailnet at the one-time admin-console link — account action, user did this).
      Live at `https://bubu-ayien.tail8ab968.ts.net/`.
- [x] **M0 exit test half 1: PASSED.** Phone reached `https://bubu-ayien.tail8ab968.ts.net/health`
      → `{"status":"ok"}` over mobile data (Wi-Fi off), once the phone's Tailscale app
      was connected (it had been idle/offline — reconnecting it was the fix).
- [x] Backblaze B2 bucket (`EngramOS-Backup`, US West) + scoped app key created by
      user, wired into `.env`. `restic init` run against `b2:EngramOS-Backup:engram`.
- [x] **M0 exit test half 2: PASSED.** `./scripts/backup.sh` → `./scripts/restore.sh`
      round trip against the real B2 repo: `users` row count = 1, matches expected.
      Along the way: installed `restic` + enabled Docker Desktop's WSL integration for
      Ubuntu (both one-time host setup, not repo changes) — Docker Desktop restart from
      that toggle stopped all containers, brought them back with `docker compose up -d`.
      Found and fixed a real regression: the earlier "leaked temp dir" fix in
      `backup.sh` (commit `b7c36ac`) had switched to a plain `mktemp` file, which broke
      `restore.sh`'s hardcoded `engram-db.dump` filename lookup — restore silently found
      nothing. Fixed in `45cd2db`: back to `mktemp -d` + fixed filename, cleaned up with
      `rm -rf` on the directory (the reviewer's originally-suggested alternative)
      instead of `rm -f` on the file. Caught only because the full round trip was
      actually run end to end, not just statically reviewed.
- [x] **M0 fully done — both exit-test halves pass on the real laptop.**
- [x] Pushed `main` to origin (all commits through `45cd2db`).

## Optional follow-up (not required for M0, noted for later)

- [x] Windows Task Scheduler nightly job for `backup.sh` registered (`EngramOS Nightly
      Backup`, daily 03:00, `WakeToRun` + `StartWhenAvailable` enabled). User still needs
      to confirm Windows Power Options → Sleep → Allow wake timers = Enabled — the task
      can't set that itself.
- [x] Committed `plans/001-huzios-port-vs-fresh-build.md` — had been sitting untracked
      since the original planning session, caught during a git-status sweep.

## M1 — Capture works (full pipeline)

- [x] Planner: wrote `plans/004-m1-capture.md`. Scope: `POST /api/v1/capture`
      (text/URL/photo/file/audio), Telegram long-polling bot, dashboard quick-note box
      (first UI in the repo), captures list (newest-first), blake2b exact dedup.
      Frontend: **yes**. Security pass: **warranted** — new Telegram ingestion path +
      user file uploads are real trust boundaries (unlike the M0 rework).
- [x] Builder: executed `plans/004-m1-capture.md`, 7/7 steps, no deviations. New:
      `db/migrations/001_captures.sql`, `app/capture.py`, `app/bot.py`,
      `app/static/{index.html,app.js}`, `app/test_capture.py`; touched: `main.py`,
      `requirements.txt`, `docker-compose.yml` (+`bot` service, `./data` mount),
      `.env(.example)` (+Telegram vars), `.gitignore`, `scripts/backup.sh` (+`/data`
      backup), README, CI. Also fixed a real stored-XSS in `app.js` (plan's sketch used
      `innerHTML` on attacker/Telegram-controlled text — switched to `textContent`).
      **Real runtime evidence** (actual Docker stack, not simulated): migration applied
      live, all 4 containers up, auth-gated capture endpoint tested (201/401/duplicate
      detection), file+text captures verified end to end with no orphan files on
      dedup, `test_capture.py` + `test_auth.py` both pass, actual backup.sh run against
      the live B2 repo now includes `/data`. Static-only: real Telegram message handling
      (no bot token yet — expected) and phone-browser UI flow.
      Left uncommitted per instructions (plan has no commit step).
- [x] Simplifier: cut 1 line — a redundant eager `os.makedirs` in `main.py`'s startup
      duplicating `capture.py`'s own idempotent one at write-time. Verified with real
      before/after curl + docker checks (health, text/file capture, dedup, 401, both
      test suites) — no behavior change. Rest of the diff already lean, nothing else cut.
- [x] Reviewer: verdict SHIP. No blocking defects — file storage never uses client
      filenames (uuid+sanitized ext, never served/executed), both endpoints enforce
      auth, SQL fully parameterized, dedup hashes correct bytes per kind, chat-id
      allowlist checked before processing, XSS fix confirmed in place. 4 non-blocking
      findings, all fixed (orchestrator applied directly, then rebuilt + re-verified):
      (1) bot could crash-loop on a transient sendMessage network error → wrapped in
      try/except; (2) file upload read entire body into memory before the size check →
      bounded the read itself to MAX_BYTES+1; (3) fresh/empty-volume deploy would boot
      with no captures table (migration was manual-only) → wired
      db/migrations/001_captures.sql into docker-entrypoint-initdb.d alongside init.sql,
      ordered to run after it; (4) bot could crash if it starts before the API creates
      the user row → retry loop instead of immediate crash. One accepted tradeoff, not
      fixed: re-sending an identical file with a new caption silently drops the new
      caption (exact-dedup is working as designed). Verified post-fix: both test suites
      pass, live curl smoke test (capture + list) works, captures table confirmed intact
      via `\d captures`. Cleaned up all test/smoke DB rows and orphan files afterward —
      captures table and data/captures/ both back to empty.
- [x] Security: verdict **FIX FIRST** on one finding, everything else cleared. Real
      issue: `app/bot.py`'s httpx exception strings embed the full request URL
      (`https://api.telegram.org/bot<TOKEN>/...`), so every logged `getUpdates`/
      `getFile`/`sendMessage` failure printed the bot token in plaintext to container
      logs — most likely to fire during initial setup (placeholder token = guaranteed
      401 loop). Fixed: added a `scrub()` helper, applied at all 3 print sites; verified
      by rebuilding and confirming the log now shows `bot***` instead of the real token.
      Cleared (verified, not assumed): path traversal genuinely blocked (uuid + sanitized
      ext), uploaded files never served back by Caddy/FastAPI (no MIME-confusion path),
      Telegram chat-id allowlist fails closed and is unspoofable, both new endpoints
      correctly `Depends(require_access)`, XSS fix confirmed applied at every render
      site (not just one), JWT-in-localStorage acceptable for this same-origin
      single-user app behind Tailscale's real TLS termination, secrets pattern consistent
      with existing `.env`/`.env.example` handling, `python-multipart` a non-issue.
- [x] Frontend: polished the minimal UI in place, no scope creep (no framework, no
      build step, no M2+ features). Added: real error/loading states on login and
      quick-note save (previously a failed save showed nothing), disabled-button
      double-submit guard, 44px touch targets for phone use, empty-state message,
      kind badges on list items. Found+fixed a real gotcha: `app/static/` is baked
      into the API image at build time (no bind mount), so edits need
      `docker compose up -d --build api` to take effect — noted for future UI work.
      Verified in a real browser via Chrome tools: wrong-password flow, empty state,
      save→list-update without reload, double-submit guard (via code trace). Cleaned
      up its own test data afterward — captures table back to empty.
- [x] Verifier: **PASS.** Real end-to-end evidence on the live stack: both test suites
      pass in-container, live text+file capture round trip with dedup confirmed by
      actual disk state (orphan file correctly removed, only 1 file ever persisted
      across 2 identical uploads), newest-first ordering correct, 401 without a bearer
      token, same result through Caddy on :8080. Token-scrub fix confirmed holding in
      live logs (`bot***`, never the real value). Migration fix confirmed matching the
      live `\d captures` schema exactly. Cleaned up after itself — captures table and
      data/captures/ confirmed back to empty (0 before, 0 after). Honest gaps (expected,
      not blocking): real Telegram message delivery untestable (no bot token exists
      yet — placeholder in `.env`), phone-over-Tailscale browser session untestable
      from this environment (API/UI confirmed serving correctly through Caddy though).
- [x] **M1 code complete and verified — ready to commit.**
- [x] **Telegram bot fully live.** User created @HuziOS_Engram_bot via @BotFather,
      got chat ID `406207958` (found by reading it out of the bot's own getUpdates
      response after the user messaged it — no need for a separate userinfo bot),
      wired both into `.env`, restarted the `bot` service. Confirmed end to end: two
      real messages sent from the user's phone ("hi", "hi how are you") both landed
      in the `captures` table as real Telegram-sourced text captures. **M1 is now
      fully operational, not just code-complete.**

## M2 — Search works

- [x] Full pipeline (planner → builder → simplifier → reviewer → security → frontend →
      verifier) executed in sandbox for `plans/005-m2-search.md`. Tier-1 extraction
      (URL metadata, OCR, dates/amounts/emails/phones), 384-dim multilingual embeddings,
      hybrid pgvector+FTS search via RRF, search UI on the dashboard. Defects found and
      fixed along the way: embedding call not fail-soft (rolled back captures on error),
      SSRF redirect TOCTOU gap, OCR missing timeout, search-UI race condition on stale
      results. 16/16 tests passing in sandbox. PR #1 opened draft on `worktree-m2-search`.
- [x] PR #1 merged into `main`, pushed to both `origin` and `private` remotes. Merged
      branch deleted locally + both remotes; stale worktree cleaned up.
- [x] Migration `002_search.sql` applied to the live DB (manual — existing `pgdata`
      volume doesn't pick up new `docker-entrypoint-initdb.d` files).
- [x] Rebuilt (`docker compose up -d --build`) — Tesseract + baked embedding model live.
- [x] `backfill.py` run — both pre-M2 captures got embeddings (`embedding=yes` each).
- [x] Exit test run: 51 items captured, 51/51 embedded, 27/51 with extracted fields.
      Keyword search 5/5 top-3. Semantic search 3/5 top-3 — 2 failures (paraphrase
      queries for "passport renewal" and "migraine" got out-ranked by unrelated items
      that shared a literal word with the query, e.g. "trip", "doctor"). Root cause:
      RRF fuses by rank with no way to distinguish a coincidental keyword overlap from
      genuine relevance, so a strong keyword hit can bury a real semantic match outside
      the top-3 window. Not yet fixed — see gap below.
      Test rows (`source='exit_test'`) deleted afterward, captures table back to only
      the 2 real pre-M2 rows.

### Known gap — status as of 2026-07-23

- [x] **2/5 semantic queries failing top-3 — FIXED.** Full pipeline (planner → builder →
      simplifier → reviewer → verifier) ran on `plans/006-m2-rrf-ranking-fix.md`. Root
      cause: pure RRF scored a vector-only true match (rank 1: `1/61≈0.01639`) just below
      an FTS-only coincidental-keyword distractor (rank 0: `1/60≈0.01667`) — a wash that
      buried real meaning-only matches. Fix: `app/search.py::fuse()` now weights the
      vector list 2x over FTS (`W_VEC=2.0`/`W_FTS=1.0`, one-constant tune, `ponytail:`
      comment marks it as a calibration knob). New regression test
      `test_rrf_vector_only_beats_fts_only_coincidence` in `test_extract.py` (fails under
      old unweighted RRF, passes under the fix — confirmed not a tautology). New
      disposable `app/exit_test_semantic.py` reconstructs the documented failure cases
      (original 51-item corpus script no longer exists) plus 3 control queries. Verified
      independently by the verifier stage on the live Docker stack: 3 consecutive runs,
      5/5 top-3 each time (both "passport renewal" and "migraine" cases now pass 4/4 runs
      total across builder+verifier), cleanup confirmed via direct `SELECT count(*)`
      (0 leftover `source='exit_test'` rows). Reviewer verdict: SHIP, no blocking
      findings. No security or frontend pass needed (internal ranking constant only, no
      new trust boundary, no response-shape change).
- [x] **Test suites re-run on the live stack — DONE.** `test_auth.py`, `test_capture.py`,
      `test_extract.py` all re-run fresh in-container post-fix (not just the pre-existing
      sandbox run) — all pass.
- [ ] **Exit test still hasn't gone through real capture paths.** Two sub-gaps remain,
      both blocked on the real user, not on code:
      - Dashboard quick-note + OCR path: infra is ready (`caddy` brought back up, proxying
        correctly — confirmed `curl :8080/api/v1/me` → `401`), but logging in needs the
        real account password, which no agent has or should guess. **Needs the user to
        log in and run a real photo capture through the dashboard UI.**
      - Telegram bot path: fundamentally requires a message sent from the user's own
        phone/Telegram account — not something an agent can simulate. **Needs the user to
        send a real message (ideally with a photo) to the bot.**
