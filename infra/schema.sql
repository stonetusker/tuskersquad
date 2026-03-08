-- TuskerSquad Reference Schema
-- This file documents the table structure used by the SQLAlchemy ORM models.
-- The application uses SQLAlchemy create_all() on startup; this file is
-- provided for reference, manual inspection, and database bootstrapping.
--
-- Primary keys use UUID to match the ORM.  Run with:
--   psql -U tusker -d tuskersquad -f schema.sql

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

CREATE TABLE IF NOT EXISTS workflow_runs (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    repository  TEXT NOT NULL,
    pr_number   INTEGER NOT NULL,
    status      TEXT NOT NULL,
    current_agent TEXT,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS engineering_findings (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    workflow_id UUID REFERENCES workflow_runs(id),
    agent       TEXT,
    severity    TEXT,
    title       TEXT,
    description TEXT,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS finding_challenges (
    id               UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    finding_id       UUID REFERENCES engineering_findings(id),
    workflow_id      UUID REFERENCES workflow_runs(id),
    challenger_agent TEXT,
    challenge_reason TEXT,
    decision         TEXT,
    created_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS governance_actions (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    workflow_id UUID REFERENCES workflow_runs(id),
    decision    TEXT,
    approved    BOOLEAN,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS agent_execution_log (
    id           UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    workflow_id  UUID REFERENCES workflow_runs(id),
    agent        TEXT,
    status       TEXT,
    started_at   TIMESTAMP,
    completed_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS qa_summaries (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    workflow_id UUID REFERENCES workflow_runs(id),
    risk_level  TEXT,
    summary     TEXT,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Indexes for common query patterns
CREATE INDEX IF NOT EXISTS idx_findings_workflow ON engineering_findings(workflow_id);
CREATE INDEX IF NOT EXISTS idx_challenges_workflow ON finding_challenges(workflow_id);
CREATE INDEX IF NOT EXISTS idx_governance_workflow ON governance_actions(workflow_id);
CREATE INDEX IF NOT EXISTS idx_agent_log_workflow ON agent_execution_log(workflow_id);
CREATE INDEX IF NOT EXISTS idx_qa_summary_workflow ON qa_summaries(workflow_id);
CREATE INDEX IF NOT EXISTS idx_workflow_status ON workflow_runs(status);
