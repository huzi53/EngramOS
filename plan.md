# DOPE OS — Executable Build Plan v1.2

> Derived from `Personal_OS_Technical_Specification_v1.0.pdf` (Kimi-generated, 2026-07-20),
> audited and corrected. This plan supersedes the spec where they conflict — see
> [Appendix A: Spec deviations & fixes](#appendix-a-spec-deviations--fixes).

## Locked decisions (from planning session, 2026-07-20)

| Decision | Choice |
|---|---|
| Audience | Single user (Huzi). No multi-tenancy, no third-party auth service. Keep `user_id` column for future-proofing only. |
| Access | Hosted on a cheap VPS, reachable from anywhere over HTTPS. Not localhost. Laptop stays available as a fallback/worker but is not the primary host. |
| Phone | Android. Capture via installable PWA with Web Share Target (day one), optional tiny native app later. |
| AI tiers | **No local LLM** (no GPU). Tier 1 = Python heuristics (free). Tier 2 = cloud **fast model** (classification). Tier 3 = cloud **smart model** (enrichment, briefing). **Interactive reasoning (mentor) = existing Claude Pro sub via claude.ai MCP connector — no Claude API.** Hard daily budget cap on the API tiers. |
| AI provider | **Replaceable by design** (v1.1). All pipeline LLM calls go through the OpenAI-compatible API standard — provider is env config, not code. **Picked by data policy first, price second (v1.2): start OpenAI (no-training default on API traffic)**; swap candidates: Kimi/Moonshot paid, Claude, others passing the data-policy gate. See [AI provider portability](#ai-provider-portability). |
| Budget | VPS ~€5/mo + domain ~$10/yr + **one-time ~$10 API topup lasting ~a year** + Claude Pro (already paying). Total new spend ≈ **€5/mo + ~$1/mo AI**. |
| Build mode | Claude Code writes the code; Huzi directs, reviews, and tests. Pace is set by review bandwidth, not coding time. |
| Priorities | 1) Capture + search. 2) Auto-organization + linking. Briefing/rediscovery next; mentor/insights later. |

## Goal

A personal memory system: capture anything from the phone in under 10 seconds, have it
automatically organized, linked, and searchable by meaning — accessible from anywhere,
running for under $20/month, with zero manual filing.

## Architecture (right-sized)

One box, one database, one app:

```
Android phone ──share──> PWA (Next.js, installed)         Laptop/desktop ──> same PWA
                              │ HTTPS
                              v
                    VPS (Hetzner, Docker Compose)
                    ├─ Caddy          (HTTPS, reverse proxy)
                    ├─ FastAPI        (API + auth: single-user JWT)
                    ├─ Worker         (pipeline: extract → classify → embed → link)
                    ├─ PostgreSQL 16  (+ pgvector) — captures, entities, relations,
                    │                   full-text search, vector search, job queue
                    └─ /data volume   (raw files) + nightly restic backup → Cloudflare R2/B2
                              │
                              v
                    LLM API — any OpenAI-compatible provider, set via env
                    (LLM_FAST = classify · LLM_SMART = enrich/briefing)
                    CPU embeddings on VPS (multilingual-e5-small, 384-dim —
                    local, handles Malay+English, provider-independent)
                    MCP server (behind Caddy) ──> claude.ai custom connector
                    (mentor mode runs on the existing Claude Pro sub, $0 API)
```

**What replaced the spec's 6 datastores:** Postgres does vectors (pgvector), full-text
search (tsvector), graph (`entities` + `capture_relations` tables + recursive CTEs),
metadata (JSONB), and the job queue (`FOR UPDATE SKIP LOCKED`). Files live on the VPS
disk. Neo4j, Qdrant, Meilisearch, MinIO, Redis, Celery: all deferred until data volume
proves the need (likely never for one user).

## AI provider portability

The spec's first principle — *"Data is the primary asset. AI is a replaceable processing
layer"* — is enforced by four hard rules (added v1.1):

1. **One client, OpenAI-compatible.** All LLM calls use the `openai` Python SDK with a
   configurable `base_url`. OpenAI is native; Kimi (Moonshot), Anthropic, DeepSeek, and
   OpenRouter all expose OpenAI-compatible endpoints. Swapping provider = editing `.env`:
   ```env
   LLM_BASE_URL=https://api.openai.com/v1     # or https://api.moonshot.ai/v1 (Kimi), etc.
   LLM_API_KEY=sk-...
   LLM_FAST=<current cheap model>              # tier 2: classification, tagging
   LLM_SMART=<current strong model>            # tier 3: enrichment, briefing, mentor
   ```
   No provider name appears anywhere in code — only `FAST` and `SMART` slots.
2. **Pricing lives in config, not code.** The AI Router's budget cap reads a per-model
   `{input_price, output_price}` table from config, so cost tracking survives any swap.
3. **Lowest-common-denominator structured output.** JSON requested in the prompt +
   Pydantic validation + one retry on parse failure. No provider-specific JSON modes or
   tool-calling formats, so every OpenAI-compatible provider behaves identically.
4. **Eval set gates every swap.** ~30 real captures with known-correct classifications,
   stored in the repo (built during M3). After any provider/model change, re-run the eval;
   accept the swap only if accuracy stays ≥ the current baseline. This catches silent
   quality regressions that a "it seems to work" check misses.
5. **Data-policy gate on providers (v1.2).** Capture content is life data. Any provider
   used in the pipeline must have an explicit no-training policy on API traffic
   (e.g. OpenAI API default; Kimi paid tier). **Free tiers that reserve training rights
   are banned for capture content regardless of price** — it would violate the spec's
   own §15 data-sovereignty principle. Price is the tiebreaker only *after* this gate.

Embeddings are already portable: they run locally (multilingual-e5-small, CPU), so
chat-model swaps never require re-embedding.

## Milestones

Each milestone is a checkpoint with a testable exit criterion. Build order = priority order.

### M0 — Infrastructure live
Domain (buy on Cloudflare Registrar — at-cost pricing, and it unlocks free Email Routing
for M5) + Hetzner VPS + Docker Compose (Caddy, FastAPI hello-world, Postgres+pgvector)
+ HTTPS + single-user JWT login + nightly encrypted backup job. PWA/frontend builds run
in **GitHub Actions**, never on the 4GB VPS (Next.js builds can OOM a box that's also
running Postgres + embeddings) — only built artifacts get deployed.
**Exit test:** you log in from your phone over the internet; a restore from backup works.

### M1 — Capture works (MVP core)
`POST /api/v1/capture` (text, URL, photo, file) · PWA with Web Share Target registered
on Android · quick-note box · client retry queue (IndexedDB) so capture never fails ·
blake2b exact-hash dedup · captures list view (newest first).
**Exit test:** share a TikTok link, a photo, and a text note from your phone in <10s each;
all three appear in the dashboard; sharing the same link twice creates one capture.
*Honest expectation (v1.2):* TikTok/IG shares arrive as a URL; login walls mean extraction
gets link + thumbnail + caption (oEmbed/yt-dlp where it works), **not** full video content.
The capture is still searchable by its metadata — judge M1 against that, not the spec's fantasy.

### M2 — Search works
Tier-1 extraction (URL scrape/metadata, dates via dateparser, amounts, emails, phones;
Tesseract OCR for images) · CPU embeddings (**multilingual-e5-small**, 384-dim — chosen
over English-centric MiniLM because captures are mixed Malay + English) on every capture ·
hybrid search endpoint (pgvector cosine + Postgres FTS, merged) · search UI.
**Exit test:** capture 50+ real items, then find a specific one by meaning ("that article
about sleep") and by keyword, in the top 3 results.

### M3 — Auto-organization (priority feature)
Fast-model classification per capture (categories, tags, title, priority, content_type,
deadline, action_required — the spec's Stage-2 prompt, pointed at the `LLM_FAST` slot) ·
AI Router with daily budget cap + per-model pricing config + spend tracking table ·
classification eval set (~30 labeled captures, the swap gate from the portability rules) ·
category/tag browse UI · thumbs up/down feedback stored on captures.
**Exit test:** a week of real captures lands >80% correctly categorized with sensible
titles, at <$0.15/day API spend.

### M4 — Linking & graph
`entities` + `capture_entities` + `capture_relations` tables (spec schema, corrected SQL) ·
entity extraction (from fast-model output + heuristics) · similarity links (cosine > 0.82) ·
temporal-proximity + shared-entity + project links · projects CRUD · "Related" panel
on every capture.
**Exit test:** open any capture and see genuinely related items; open a project and see
everything that belongs to it without ever having filed anything.

### M5 — Daily loop: briefing + rediscovery
Morning briefing (cron 06:55: pending tasks, due dates, yesterday's captures, 1–3
rediscovered items → one smart-model call → dashboard card + optional push via ntfy) ·
rediscovery scoring (spec §8, simplified: project-context + semantic + anniversary) ·
email ingestion via **Cloudflare Email Routing → Worker → POST /api/v1/capture**
(`capture@yourdomain` — free, real-time, no mail credentials stored on the VPS;
IMAP polling documented as fallback only).
**Exit test:** for one week, the morning card is worth reading, and a forwarded email
becomes a searchable capture.

### M6 — Deep enrichment + mentor v1 (redesigned in v1.2)
Selective smart-model enrichment (spec §4.4 trigger rules: high priority / long content /
finance / low confidence) · **remote MCP server** behind Caddy exposing `search_captures`,
`get_related`, `get_project`, `get_patterns`, `log_study_session` · added as a **custom
connector in claude.ai** — the Claude app (Pro sub, already paid) becomes the mentor
interface with full memory access: mobile, voice, projects included, zero API cost,
and no custom chat UI to build · insights v1 (capture-habit patterns only).
**Exit test:** in the Claude mobile app, ask about something you captured a month ago
and get an answer citing the right captures via the connector.

### M7 — Hardening
Voice notes (faster-whisper tiny, CPU) if wanted · security pass (rate limit, input
validation, file-type checks, headers) · restore drill + data export (JSON + files) ·
performance pass · optional: tiny native Android app (share intent + widget) if the
PWA share target ever feels limiting.
**Exit test:** full export restores on a clean machine; dashboard loads <2s on phone.

## Dependencies

**Before M0 (decisions/purchases — the only things Claude Code can't do for you):**
- [ ] Hetzner account + VPS (CX22 ~€4.50/mo to start; resize to 8GB later if OCR/whisper need it)
- [ ] A domain name (~$10/yr) bought on **Cloudflare Registrar**, pointed at the VPS
      (also provides free Email Routing for M5 — no Gmail account needed)
- [ ] OpenAI API key with a **one-time ~$10 topup** and auto-recharge OFF
- [ ] Cloudflare R2 or Backblaze B2 bucket for backups (free tiers cover this)
- [ ] Claude Pro sub stays active (mentor mode rides on it via MCP connector, M6)

**Internal blockers:**
- M1 blocks everything (no data → nothing downstream matters)
- M3's AI Router (budget cap) must exist before M6 (smart-model enrichment) to prevent cost surprises
- Embedding model choice is **locked at M2** (384-dim multilingual-e5-small) — changing later means re-embedding everything (cheap at personal scale, but a migration)

## Estimated time

Build mode is "Claude Code writes it, Huzi reviews" — so estimates are in
review-sessions, not coding-hours. Assume 2–4 sessions/week. **Low confidence overall**
(solo, first project of this shape); M0–M2 estimates are firmer than M5–M7.

| Milestone | Sessions | Calendar (rough) |
|---|---|---|
| M0 Infra | 2–3 | Week 1 |
| M1 Capture | 3–4 | Weeks 1–2 |
| M2 Search | 3–4 | Weeks 2–3 |
| M3 Auto-org | 3–4 | Weeks 3–4 |
| M4 Linking | 4–5 | Weeks 5–6 |
| M5 Briefing/rediscovery | 4–5 | Weeks 7–8 |
| M6 Enrichment/mentor | 4–6 | Weeks 9–11 |
| M7 Hardening | 3–4 | Week 12+ |

MVP you'd actually use daily = **M0–M3, roughly a month**. Everything after runs on real
accumulated data, which is exactly what M4–M6 need to be tuneable.

## Risks

| Risk | Why it's real here | Mitigation |
|---|---|---|
| **Abandonment mid-build** (the spec itself jokes about a 50% abandonment pattern) | 24-week horizon, solo | Plan is cut so M1–M3 (~1 month) already delivers daily value; every milestone is independently useful |
| **Capture friction kills adoption** | If sharing takes >10s or fails offline, you stop using it and the data moat never forms | PWA share target + IndexedDB retry queue in M1, before any AI work |
| **API cost creep** | No local tier to absorb load; every smart feature is metered | Budget-cap table + router before smart-model features; provider console spend limit as backstop |
| **Small-VPS resource limits** | OCR + embeddings + Postgres on 4GB RAM | Tesseract (light) not PaddleOCR; batch embedding; resize VPS is a 2-minute operation |
| **Classification quality disappoints** ("zero manual organization" is the promise) | Cheap fast models on terse captures can misfile | Feedback buttons from M3 day one; misfiles feed prompt tuning and the eval set; escalate low-confidence to the smart model within budget |
| **Provider swap regresses quality silently** | Prompts are tuned against one model's behavior; a swap (OpenAI → Kimi) can misfile without erroring | Eval set (M3) re-run gates every provider/model change; keep old config until new one passes baseline |
| **Mentor depends on the Claude Pro sub** | Cancel Pro and mentor mode loses its interface | MCP is an open standard — any MCP client (Claude Code, other apps) can connect to the same server; a self-hosted chat UI on the cheap API is a contained V3 fallback |
| **Data loss** (spec anti-pattern #10: "this is someone's life") | Single VPS is a single point of failure | Encrypted nightly offsite backups from M0, restore actually tested in M0 and re-drilled in M7 |
| **PWA share-target limitations** | Some apps share weird payloads; PWA can't do accessibility/screenshot monitoring | Accept for MVP; native Android app is a contained M7 add-on, not a rewrite |

## MVP

**M0–M3:** capture anything from the phone from anywhere, exact-dedup, hybrid
semantic+keyword search, auto-classification with a budget-capped fast model, browsable by
category/tag. One VPS, one database, one PWA. This tests the core assumption —
*"if capture is frictionless and retrieval is smart, I'll actually use it"* — for
~€5 + pocket change in API calls per month.

## V2

**M4–M6:** entity/relation graph in Postgres, related-capture surfacing, projects,
morning briefing, rediscovery, email ingestion, selective deep enrichment, mentor chat
over your own data, first insights.

## V3 (rough)

Voice capture, native Android app + home-screen widget, browser extension,
spaced-repetition study system + quiz generation (spec §9), finance pattern tracking,
reflection engine (spec §11), notification intelligence, third-party API/webhooks —
and only if data volume ever demands it: dedicated vector/graph/search stores.

---

## Appendix A: Spec deviations & fixes

Flags found in the source spec and how this plan resolves them:

1. **Embedding dimension mismatch** — spec schema says `Vector(1536)` but its own stack
   picks `all-MiniLM-L6-v2` (384-dim). **Fix:** 384-dim everywhere; pgvector column
   `vector(384)`; model upgraded to `multilingual-e5-small` in v1.2 (same dims,
   handles Malay+English). Migration path documented if we ever switch models.
2. **Qdrant AND pgvector both specced** — **Fix:** pgvector only.
3. **Invalid SQL** — double-quoted string literals (`DEFAULT "{}"`, `IN ("HIGH",...)`)
   and malformed GIN index syntax. **Fix:** rewrite schema with single quotes, correct
   `USING GIN (column)` syntax, during M1.
4. **Duplicate graph layers** (Neo4j + Postgres relation tables). **Fix:** Postgres
   tables are the single source of truth; Neo4j dropped.
5. **"IMAP webhook"** doesn't exist. **Fix (v1.2):** Cloudflare Email Routing → Worker →
   ingestion API — genuinely real-time, credential-less; IMAP polling kept only as a
   documented fallback for domainless setups.
6. **Stale, hardcoded model names** (`claude-sonnet-4`, `gpt-4o`, `gemini-1.5-pro`).
   **Fix (v1.1):** no model names in code at all — abstract `LLM_FAST`/`LLM_SMART` slots
   behind an OpenAI-compatible client, provider and models set in `.env`
   (see [AI provider portability](#ai-provider-portability)).
7. **Local LLM tier assumed GPU** — user has none. **Fix:** tier 2 becomes the cloud fast
   model; heuristics tier absorbs everything it can for free; hard daily budget cap enforced
   in the router (spec's throttling ladder kept: 80% → downgrade, 100% → heuristics only).
8. **Six datastores for one user** contradicts the spec's own anti-pattern #9
   ("don't over-engineer v1"). **Fix:** Postgres + disk + Caddy; queue via
   `SKIP LOCKED`; Redis/Celery/Meilisearch/MinIO deferred behind real need.
9. **Multi-user auth (Supabase/Clerk)** for a single-user system. **Fix:** single-user
   JWT (one password + long-lived refresh), `user_id` kept in schema for optionality.
10. **iOS/Android native app in Phase 1** — **Fix:** Android PWA Web Share Target at M1
    (works day one, no store, no Mac); native app demoted to optional M7.
11. **Screenshot accessibility-service monitoring** — Play-policy minefield and not
    needed for a personal sideload; **deferred to V3**, share-sheet covers screenshots fine.
12. **24-week team-sized roadmap** — **Fix:** re-phased to milestone/review-session
    model above; MVP value lands at ~1 month instead of week 4 of 24.

## Appendix B: Changelog

- **v1.2 (2026-07-20):** Cost + privacy restructure after user challenge. Mentor mode
  moved off the API entirely — Engram exposes a remote MCP server and claude.ai (existing
  Pro sub) becomes the mentor interface; M6 no longer builds a chat UI. Pipeline provider
  locked to no-train-on-API-traffic providers (start: OpenAI), free tiers banned for
  capture content (data-policy gate, portability rule 5). Budget model changed to
  one-time ~$10 topup (~a year) instead of $5–10/mo. Embeddings switched
  MiniLM → multilingual-e5-small (mixed Malay+English captures). Email ingestion
  switched IMAP polling → Cloudflare Email Routing webhook. TikTok/IG capture depth
  expectation documented. Frontend builds moved to GitHub Actions (VPS RAM).
- **v1.1 (2026-07-20):** AI provider made replaceable — OpenAI-compatible client with
  `LLM_FAST`/`LLM_SMART` env slots, per-model pricing config, portable JSON output,
  eval-set swap gate. Starting provider: OpenAI (was: hardcoded Claude); Kimi/Moonshot
  and Claude remain drop-in candidates.
- **v1.0 (2026-07-20):** Initial audited plan from Personal_OS_Technical_Specification_v1.0.

## Appendix C: Next step

Per the planning skill: this plan defines *what* and *in which order*. The first build
session (M0) should start by running the **system-architect** pass to fix the concrete
repo layout, docker-compose file, corrected Postgres schema DDL, and API surface — then
scaffold it. Say **"start M0"** in a new session in this folder to kick off.
