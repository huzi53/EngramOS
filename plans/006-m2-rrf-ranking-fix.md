# 006 — M2 RRF ranking fix (weighted fusion) + live-stack verify

## Goal
A genuine meaning-only (paraphrase) match ranks in the top 3 instead of being buried
under a capture that merely shares one literal word with the query.

## Root cause (confirmed, not symptom)
`app/search.py::fuse` is pure Reciprocal Rank Fusion by rank position only. The two
documented failures ("passport renewal", "migraine") are the case where the true match is
**vector-only** (paraphrase → no literal overlap → absent from the FTS list) and the
distractor is **FTS-only** (shares one word like "trip"/"doctor" → FTS rank 0, but
semantically far → not near the top of the vector list). Pure RRF then scores:
- true match, vector rank 1: `1/(60+1) = 0.01639`
- distractor, FTS rank 0: `1/(60+0) = 0.01667`  ← wins by a hair, buries the real match.

RRF discards the one signal that separates them: cosine magnitude. The smallest lever that
restores it without mixing incomparable scales is to weight the vector list higher than the
FTS list in the fusion — a one-constant rank tune, not a rewrite.

## Cut (deliberately not doing)
- Blending raw cosine similarity into the fused score — incomparable scales (RRF exists
  precisely to avoid this); weighting rank fixes the documented cases with one constant.
- Widening `CANDIDATES` — the distractor is already inside the pool; a bigger pool doesn't
  change the fusion arithmetic that produced the loss.
- Tiebreak-by-cosine re-rank — unnecessary once the vector weight lifts vector-only matches
  above FTS-only coincidences; add only if a future exit-test shows genuine score ties.
- Reconstructing the full original 51-item exit corpus — seed only the documented semantic
  cases; enough to confirm the fix against real embeddings.
- Any code for gap item 2 (real Telegram/dashboard/OCR capture paths) — that is a
  verification gap needing the user's phone, not a bug. Handled in Verify, no code.

## Files touched
- `app/search.py` — modify `fuse` to apply per-list weights via two new module constants.
  Signature unchanged (keeps the existing unit test calling `fuse(v, f)` valid).
- `app/test_extract.py` — add one pure-function regression assert (imports `fuse` already).
- `app/exit_test_semantic.py` — **new**, small, disposable: seed the documented semantic
  cases via `store_capture`, run `search`, assert top-3, delete `source='exit_test'` rows.
  Reuses existing `store_capture` (capture.py:84) and `search` (search.py:29).

## Steps

1. **Weighted RRF in `app/search.py`.**
   Add below the existing `RRF_K = 60` / `CANDIDATES = 20` constants:
   ```python
   # ponytail: calibration knob. Vector hits weighted above FTS so a meaning-only match
   # isn't buried under a coincidental keyword hit. 2.0 fixes the 2 documented paraphrase
   # failures; retune only if the exit-test semantic block regresses. Upgrade path if this
   # ever proves too blunt: tiebreak near-equal fused scores by cosine distance.
   W_VEC = 2.0
   W_FTS = 1.0
   ```
   In `fuse`, replace the two `+ 1.0 / (RRF_K + rank)` terms with
   `+ W_VEC / (RRF_K + rank)` (vector loop) and `+ W_FTS / (RRF_K + rank)` (fts loop).
   Update the function/module docstring line noting the vector list carries higher weight.
   **Check:** `cd app && python -c "from search import fuse; print(fuse(['x','t'],['d']))"`
   shows `t` scoring above `d` (t ≈ 0.0328 > d ≈ 0.0167).

2. **Regression test in `app/test_extract.py`.**
   Add after `test_rrf_fusion_prefers_ids_ranked_high_in_both`, and call it in `__main__`:
   ```python
   def test_rrf_vector_only_beats_fts_only_coincidence():
       # M2 exit-test bug: a meaning-only match (vector list, not rank 0) lost to a
       # coincidental keyword hit (fts rank 0). Weighted RRF must rank the vector match higher.
       scores = fuse(["other", "true_match"], ["distractor"])
       assert scores["true_match"] > scores["distractor"]
   ```
   (Under old pure RRF this asserts 0.01639 > 0.01667 → fails, reproducing the bug; under
   weighted RRF 0.0328 > 0.0167 → passes.)
   **Check:** `cd app && python test_extract.py` prints `all asserts passed`.

3. **Reconstructed semantic exit-test `app/exit_test_semantic.py` (new, disposable).**
   Small script, run in-container against the live DB. Fixtures rebuilt from TODO.md's
   documented cases (the original in-container script was deleted, TODO.md:212). Structure:
   - A fixed `user_id` (reuse the real user's id — read from `SELECT id FROM users LIMIT 1`).
   - Seed ~8-10 captures via `store_capture(user_id, "exit_test", text=...)`: the 2 failing
     pairs — a "passport renewal" item + a "trip"-sharing distractor; a "migraine" item + a
     "doctor"-sharing distractor — plus 3 known-passing semantic items as controls.
   - Run `search` (call the router fn directly with a `payload={"sub": user_id}` stub, as the
     original direct-pipeline exit test did) for each paraphrase query; assert the intended
     capture id is in the top 3; print PASS/FAIL per query.
   - `finally:` `DELETE FROM captures WHERE source='exit_test'` (matches M2 cleanup).
   Mark at top: `# ponytail: fixtures reconstructed from TODO.md's documented cases, not the
   original 51-item corpus — a confidence check on real embeddings, the pure-function
   regression in test_extract.py is the deterministic guardrail.`
   **Check:** `docker compose exec api python exit_test_semantic.py` → 5/5 semantic queries
   top-3 (was 3/5). Rows gone afterward (`SELECT count(*) ... source='exit_test'` = 0).

## Verify (end-to-end)
1. Rebuild the changed image: `docker compose up -d --build api`.
2. **Gap item 3 — re-run test suites on the live stack** (trivial, no code change):
   `docker compose exec api python test_extract.py` (now includes the new regression),
   then `test_auth.py` and `test_capture.py`. Expect all pass (17/17 with the new assert).
3. **Gap item 1 confirmation — semantic exit-test block:** run Step 3's script in-container;
   confirm 5/5 top-3 and cleanup. This is the requested re-run of the semantic block.
4. **Gap item 2 — real capture paths (partial, honest scope):**
   - Automatable without the user: exercise the **dashboard quick-note + OCR path** on a real
     image via browser automation (`claude-in-chrome` / `/run`) — upload a photo with text,
     confirm the capture lands with `embedding IS NOT NULL` and populated `extracted.ocr_text`.
   - **Needs the user (cannot be automated):** sending real Telegram messages/photos from the
     user's phone to exercise the live bot path. Flag this explicitly as outstanding — an
     agent cannot drive the user's phone/Telegram client.

## Frontend?
**No.** The change is backend ranking logic only. No new search param, no response-shape
change (`score` field already exists), no UI edit. Do not route to the frontend agent.

## Security pass?
**No.** No new trust boundary — the fix alters an internal fusion constant/arithmetic on
already-parameterized queries behind the existing `require_access`. Input surface unchanged.
