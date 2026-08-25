-- Modular RAG schema: job types, answer cache, and query metrics.
-- Apply on existing volumes:
--   docker compose exec -T postgres psql -U postgres -d ai_worker_platform < init-db/04-stage15-modular-rag.sql

ALTER TYPE jobtype ADD VALUE IF NOT EXISTS 'ROUTE_QUERY';
ALTER TYPE jobtype ADD VALUE IF NOT EXISTS 'CRITIC';
ALTER TYPE jobtype ADD VALUE IF NOT EXISTS 'RAG_EVAL';
ALTER TYPE jobtype ADD VALUE IF NOT EXISTS 'MCP_TOOL_CALL';

CREATE TABLE IF NOT EXISTS rag_answer_cache (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    question_hash TEXT NOT NULL UNIQUE,
    question TEXT NOT NULL,
    answer TEXT NOT NULL,
    sources JSONB NOT NULL DEFAULT '[]'::jsonb,
    route TEXT NOT NULL DEFAULT 'cache',
    hit_count INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS rag_query_metrics (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id UUID REFERENCES jobs(id) ON DELETE SET NULL,
    question TEXT NOT NULL,
    route TEXT NOT NULL,
    answer TEXT,
    context_relevance DOUBLE PRECISION,
    answer_relevance DOUBLE PRECISION,
    groundedness DOUBLE PRECISION,
    critic_passed BOOLEAN,
    critic_attempts INTEGER NOT NULL DEFAULT 1,
    retrieve_hit BOOLEAN,
    rerank_changed_top1 BOOLEAN,
    total_latency_ms DOUBLE PRECISION,
    observability JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_rag_query_metrics_created_at
    ON rag_query_metrics (created_at DESC);
CREATE INDEX IF NOT EXISTS ix_rag_query_metrics_route
    ON rag_query_metrics (route);
CREATE INDEX IF NOT EXISTS ix_rag_query_metrics_groundedness
    ON rag_query_metrics (groundedness);
