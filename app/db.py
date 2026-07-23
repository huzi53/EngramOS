import os

import psycopg

# ponytail: per-request connection, no pool — fine at single-user scale.
# Add psycopg_pool if concurrency ever matters.


def get_conn():
    return psycopg.connect(os.environ["DATABASE_URL"])


MAX_LIMIT = 100


def clamp_limit(limit: int) -> int:
    """Shared LIMIT clamp for query params — negative raises a Postgres error,
    unbounded is an unbounded fetch. Used by both capture.py and search.py.
    """
    return max(1, min(limit, MAX_LIMIT))
