-- Add parent/child hierarchy columns for advanced RAG (small-to-big).
-- Fresh databases get these from SQLAlchemy create_all().
-- Existing volumes need this once (create_all does not ALTER tables).
--
-- Apply:
--   docker exec -i ai_worker_postgres psql -U postgres -d ai_worker_platform \
--     < init-db/03-stage15-chunk-hierarchy.sql

ALTER TABLE chunks
  ADD COLUMN IF NOT EXISTS level text NOT NULL DEFAULT 'child';

ALTER TABLE chunks
  ADD COLUMN IF NOT EXISTS parent_chunk_id uuid
  REFERENCES chunks(id) ON DELETE CASCADE;

CREATE INDEX IF NOT EXISTS ix_chunks_parent_chunk_id ON chunks (parent_chunk_id);
CREATE INDEX IF NOT EXISTS ix_chunks_level ON chunks (level);
CREATE INDEX IF NOT EXISTS ix_chunks_metadata_gin ON chunks USING gin (metadata);
