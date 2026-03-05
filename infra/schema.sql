CREATE TABLE workflow_runs (
    id SERIAL PRIMARY KEY,
    repo TEXT,
    branch TEXT,
    pr_number INT,
    status TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE agent_execution_log (
    id SERIAL PRIMARY KEY,
    workflow_id INT,
    agent TEXT,
    status TEXT,
    started_at TIMESTAMP,
    completed_at TIMESTAMP
);

CREATE TABLE engineering_findings (
    id SERIAL PRIMARY KEY,
    workflow_id INT,
    agent TEXT,
    severity TEXT,
    confidence FLOAT,
    test_name TEXT,
    finding TEXT,
    endpoint TEXT,
    recommendation TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE governance_actions (
    id SERIAL PRIMARY KEY,
    workflow_id INT,
    action TEXT,
    actor TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
