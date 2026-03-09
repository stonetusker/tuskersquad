-- ═══════════════════════════════════════════════════════════════════════════
-- TuskerSquad — Stonetusker Systems
-- PostgreSQL schema
-- Includes: merge_status, merge_sha, deploy_status, deploy_url (v2)
-- ═══════════════════════════════════════════════════════════════════════════

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Workflow runs (one per PR review)
CREATE TABLE IF NOT EXISTS workflow_runs (
    id            UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    repository    TEXT NOT NULL,
    pr_number     INTEGER NOT NULL,
    status        TEXT NOT NULL DEFAULT 'RUNNING',
    current_agent TEXT,
    -- Auto-merge & deploy tracking (added v2)
    merge_status  TEXT,   -- pending | success | failed | skipped
    merge_sha     TEXT,
    deploy_status TEXT,   -- pending | triggered | failed | skipped
    deploy_url    TEXT,
    created_at    TIMESTAMPTZ DEFAULT NOW(),
    updated_at    TIMESTAMPTZ DEFAULT NOW()
);

-- Engineering findings from all agents
CREATE TABLE IF NOT EXISTS engineering_findings (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    workflow_id UUID REFERENCES workflow_runs(id) ON DELETE CASCADE,
    agent       TEXT,
    severity    TEXT,     -- HIGH | MEDIUM | LOW
    title       TEXT,
    description TEXT,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

-- Challenger disputes
CREATE TABLE IF NOT EXISTS finding_challenges (
    id               UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    finding_id       UUID REFERENCES engineering_findings(id) ON DELETE CASCADE,
    workflow_id      UUID REFERENCES workflow_runs(id) ON DELETE CASCADE,
    challenger_agent TEXT,
    challenge_reason TEXT,
    decision         TEXT,
    created_at       TIMESTAMPTZ DEFAULT NOW()
);

-- Human / Release Manager governance decisions
CREATE TABLE IF NOT EXISTS governance_actions (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    workflow_id UUID REFERENCES workflow_runs(id) ON DELETE CASCADE,
    decision    TEXT,
    approved    BOOLEAN,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

-- Per-agent execution timing
CREATE TABLE IF NOT EXISTS agent_execution_log (
    id           UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    workflow_id  UUID REFERENCES workflow_runs(id) ON DELETE CASCADE,
    agent        TEXT,
    status       TEXT,
    started_at   TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    output       TEXT
);

-- QA Lead synthesis
CREATE TABLE IF NOT EXISTS qa_summaries (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    workflow_id UUID REFERENCES workflow_runs(id) ON DELETE CASCADE,
    risk_level  TEXT,   -- LOW | MEDIUM | HIGH
    summary     TEXT,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

-- Index for fast workflow lookups
CREATE INDEX IF NOT EXISTS idx_wf_created   ON workflow_runs (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_findings_wf  ON engineering_findings (workflow_id);
CREATE INDEX IF NOT EXISTS idx_govact_wf    ON governance_actions (workflow_id);
CREATE INDEX IF NOT EXISTS idx_aglog_wf     ON agent_execution_log (workflow_id);
CREATE INDEX IF NOT EXISTS idx_qa_wf        ON qa_summaries (workflow_id);

-- LLM conversation log (agent ↔ Ollama conversations)
CREATE TABLE IF NOT EXISTS llm_conversation_log (
    id           UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    workflow_id  UUID REFERENCES workflow_runs(id) ON DELETE CASCADE,
    agent        TEXT NOT NULL,
    model        TEXT,
    prompt       TEXT,
    response     TEXT,
    duration_ms  INTEGER,
    success      BOOLEAN DEFAULT TRUE,
    error        TEXT,
    created_at   TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_llmlog_wf ON llm_conversation_log (workflow_id);
CREATE INDEX IF NOT EXISTS idx_llmlog_agent ON llm_conversation_log (workflow_id, agent);

-- Agent decision summaries (per-agent narrative for PR transparency)
CREATE TABLE IF NOT EXISTS agent_decision_summary (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    workflow_id UUID REFERENCES workflow_runs(id) ON DELETE CASCADE,
    agent       TEXT NOT NULL,
    decision    TEXT,        -- PASS | FLAG | CHALLENGE | APPROVE | REJECT | REVIEW_REQUIRED
    summary     TEXT,        -- human-readable paragraph
    risk_level  TEXT,        -- HIGH | MEDIUM | LOW | NONE
    test_count  INTEGER DEFAULT 0,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_agent_decision_wf ON agent_decision_summary (workflow_id);
