-- Runs once on first DB boot (empty pgdata volume only). Schema changes after
-- M0 need a migration path (introduced M1), not edits to this file.
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
