# ponytail: fixtures reconstructed from TODO.md's documented cases, not the
# original 51-item corpus — a confidence check on real embeddings, the pure-function
# regression in test_extract.py is the deterministic guardrail.
"""Re-run of the M2 semantic exit-test block against the live stack, seeding only the
2 documented paraphrase failures (+ their distractors) plus 3 known-passing controls.
Run: docker compose exec api python exit_test_semantic.py
Cleans up its own rows (source='exit_test') in a finally block.
"""
from capture import store_capture
from db import get_conn
from search import search

# (text, source) pairs to seed, and the paraphrase query that should find each one in top-3
CASES = [
    # documented failure #1: "passport renewal" paraphrase vs a "trip"-sharing distractor
    ("Need to renew my passport before it expires next month", "I need to get my passport renewed"),
    ("Booked a trip to Bali for next week", None),
    # documented failure #2: "migraine" paraphrase vs a "doctor"-sharing distractor
    ("Been getting bad migraines every afternoon this week", "my head has been hurting a lot lately"),
    ("Doctor's appointment moved to Friday 3pm", None),
    # known-passing semantic controls
    ("Need to buy milk and eggs from the store", "grocery shopping list"),
    ("Remember to water the plants on the balcony", "don't forget the balcony plants"),
    ("Finished reading a great book about ancient Rome", "that history book I read was good"),
]


def run():
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT id FROM users LIMIT 1")
        user_id = str(cur.fetchone()[0])

    payload = {"sub": user_id}
    seeded = []  # (capture_id, query) for the ones we need to assert on
    try:
        for text, query in CASES:
            result = store_capture(user_id, "exit_test", text=text)
            if query:
                seeded.append((result["id"], query))

        passed = 0
        for capture_id, query in seeded:
            results = search(q=query, payload=payload)
            top3_ids = [r["id"] for r in results[:3]]
            ok = capture_id in [str(i) for i in top3_ids]
            print(f"{'PASS' if ok else 'FAIL'}: {query!r} -> top3={top3_ids}")
            passed += ok
        print(f"{passed}/{len(seeded)} semantic queries in top-3")
    finally:
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM captures WHERE source = 'exit_test'")
            conn.commit()


if __name__ == "__main__":
    run()
