-- Extend jobtype enum for existing Postgres volumes.
-- Fresh databases get all labels from SQLAlchemy create_all().
--
-- Apply:
--   docker exec -i ai_worker_postgres psql -U postgres -d ai_worker_platform \
--     < init-db/02-stage14-jobtype-enum.sql

ALTER TYPE jobtype ADD VALUE IF NOT EXISTS 'INGESTION';
ALTER TYPE jobtype ADD VALUE IF NOT EXISTS 'RAG_QUERY';
ALTER TYPE jobtype ADD VALUE IF NOT EXISTS 'QUERY_EXPAND';
ALTER TYPE jobtype ADD VALUE IF NOT EXISTS 'RERANK';
ALTER TYPE jobtype ADD VALUE IF NOT EXISTS 'RAG_RETRIEVE';
ALTER TYPE jobtype ADD VALUE IF NOT EXISTS 'RAG_GENERATE';
