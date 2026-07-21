-- M1: one new table, applied to the already-running M0 DB (init.sql only runs on
-- first boot of an empty pgdata volume). Idempotent so re-running is harmless.
CREATE TABLE IF NOT EXISTS captures (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id       uuid NOT NULL REFERENCES users(id),
    source        text NOT NULL,              -- 'telegram' | 'quicknote' | 'api'
    kind          text NOT NULL,              -- 'text' | 'url' | 'photo' | 'file' | 'audio'
    content       text,                       -- text body / URL / media caption (nullable)
    file_path     text,                       -- relative path under DATA_DIR, e.g. captures/<uuid>.jpg
    file_name     text,                       -- original filename (display only, never a storage path)
    mime_type     text,
    content_hash  bytea NOT NULL,             -- blake2b of canonical bytes (dedup key)
    meta          jsonb NOT NULL DEFAULT '{}',-- telegram msg/chat id, forward info, etc.
    created_at    timestamptz NOT NULL DEFAULT now()
);
-- dedup: same content for the same user = one capture
CREATE UNIQUE INDEX IF NOT EXISTS captures_hash_uidx ON captures (user_id, content_hash);
-- list view: newest first
CREATE INDEX IF NOT EXISTS captures_created_idx ON captures (user_id, created_at DESC);
-- ponytail: no embedding/vector column yet — M2 ALTER TABLE ADD COLUMN embedding vector(384).
-- ponytail: raw SQL migration; add Alembic at M4 when entity/relation tables + ordering appear.
