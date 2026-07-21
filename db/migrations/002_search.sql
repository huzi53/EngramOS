-- M2: embedding + extracted metadata + generated FTS column, applied to the already-running
-- M1 DB (init.sql/001 only run on first boot of an empty pgdata volume). Idempotent so
-- re-running is harmless.
ALTER TABLE captures ADD COLUMN IF NOT EXISTS embedding vector(384);
ALTER TABLE captures ADD COLUMN IF NOT EXISTS extracted jsonb NOT NULL DEFAULT '{}';
-- Postgres maintains this: FTS over content + the searchable extracted text (OCR, URL meta).
-- 'simple' config = no stemming, correct for mixed Malay+English.
ALTER TABLE captures ADD COLUMN IF NOT EXISTS search_tsv tsvector
  GENERATED ALWAYS AS (
    to_tsvector('simple',
      coalesce(content, '') || ' ' ||
      coalesce(extracted->>'ocr_text', '') || ' ' ||
      coalesce(extracted->>'url_title', '') || ' ' ||
      coalesce(extracted->>'url_description', ''))
  ) STORED;
CREATE INDEX IF NOT EXISTS captures_tsv_gidx ON captures USING GIN (search_tsv);
-- ponytail: HNSW not load-bearing at ~50 rows (seq scan is sub-ms); cheap future-proofing.
CREATE INDEX IF NOT EXISTS captures_embedding_hnsw
  ON captures USING hnsw (embedding vector_cosine_ops);
