import os

import psycopg

# ponytail: per-request connection, no pool — fine at single-user scale.
# Add psycopg_pool if concurrency ever matters.


def get_conn():
    return psycopg.connect(os.environ["DATABASE_URL"])
