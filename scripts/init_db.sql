-- Media Monitoring Agent — initial schema
CREATE EXTENSION IF NOT EXISTS vector;

-- Raw ingested articles (one row per unique canonical URL)
CREATE TABLE IF NOT EXISTS articles (
    id              BIGSERIAL PRIMARY KEY,
    source          TEXT NOT NULL,
    url             TEXT NOT NULL UNIQUE,
    canonical_url   TEXT NOT NULL,
    title           TEXT NOT NULL,
    author          TEXT,
    language        TEXT,               -- 'ar' | 'en' | other
    published_at    TIMESTAMPTZ,
    fetched_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    raw_text        TEXT,
    clean_text      TEXT,
    extraction      TEXT NOT NULL DEFAULT 'full',  -- full | headline_only (publisher blocked the fetch)
    embedding       vector(1024),       -- multilingual embedding, set at classify time
    cluster_id      BIGINT,             -- self-referential: canonical article id for this story cluster
    is_canonical    BOOLEAN NOT NULL DEFAULT true
);

CREATE INDEX IF NOT EXISTS idx_articles_published_at ON articles (published_at DESC);
CREATE INDEX IF NOT EXISTS idx_articles_cluster_id ON articles (cluster_id);
-- ivfflat index added after enough rows exist; created lazily by app/scripts, not here.

-- One row per (article, theme) classification
CREATE TABLE IF NOT EXISTS classifications (
    id              BIGSERIAL PRIMARY KEY,
    article_id      BIGINT NOT NULL REFERENCES articles(id) ON DELETE CASCADE,
    theme           TEXT NOT NULL,      -- one of the 4 priority themes
    sentiment       TEXT NOT NULL,      -- positive | neutral | negative
    priority        TEXT NOT NULL,      -- low | medium | high
    risk_score      NUMERIC NOT NULL DEFAULT 0,   -- 0-1, drives the 15-min alert
    justification   TEXT NOT NULL,
    evidence_quote  TEXT,
    model_name      TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_classifications_article_id ON classifications (article_id);
CREATE INDEX IF NOT EXISTS idx_classifications_risk ON classifications (risk_score DESC);

-- Alerts raised for high-risk items
CREATE TABLE IF NOT EXISTS alerts (
    id                  BIGSERIAL PRIMARY KEY,
    article_id          BIGINT NOT NULL REFERENCES articles(id) ON DELETE CASCADE,
    classification_id   BIGINT REFERENCES classifications(id),
    risk_score          NUMERIC NOT NULL,
    reason              TEXT NOT NULL,
    raised_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    acknowledged_at     TIMESTAMPTZ,
    acknowledged_by     TEXT
);

-- one alert per story: re-classifying an article must not page the analyst twice
CREATE UNIQUE INDEX IF NOT EXISTS uq_alerts_article_id ON alerts (article_id);

-- Daily briefings (draft -> approved -> delivered)
CREATE TABLE IF NOT EXISTS briefings (
    id              BIGSERIAL PRIMARY KEY,
    briefing_date   DATE NOT NULL,
    status          TEXT NOT NULL DEFAULT 'draft',  -- draft | degraded | approved | delivered
    content_md      TEXT NOT NULL,      -- what gets delivered (analyst-edited if they edited)
    draft_md        TEXT,               -- the untouched AI draft, kept for the edit-diff feedback loop
    citations_json  JSONB NOT NULL DEFAULT '[]',
    unverified_claims JSONB NOT NULL DEFAULT '[]',
    approved_by     TEXT,
    approved_at     TIMESTAMPTZ,
    delivered_at    TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Observability: one row per pipeline step run, for the run log / cost tracking
CREATE TABLE IF NOT EXISTS runs (
    id              BIGSERIAL PRIMARY KEY,
    step            TEXT NOT NULL,       -- ingest | classify | brief | verify | alert | ask
    status          TEXT NOT NULL,       -- ok | error | degraded
    model           TEXT,                -- which LLM served the call (for per-model cost)
    detail          TEXT,
    input_tokens    INTEGER,
    output_tokens   INTEGER,
    latency_ms      INTEGER,
    started_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at     TIMESTAMPTZ
);

-- Hand-labeled gold set for evaluation (loaded from eval/gold_set.jsonl)
CREATE TABLE IF NOT EXISTS gold_labels (
    id              BIGSERIAL PRIMARY KEY,
    article_url     TEXT NOT NULL,
    theme           TEXT NOT NULL,
    sentiment       TEXT NOT NULL,
    priority        TEXT NOT NULL,
    is_high_risk    BOOLEAN NOT NULL,
    notes           TEXT
);
