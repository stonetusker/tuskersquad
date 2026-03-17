"""
Planner Agent
=============
Analyses the PR and decides which agents to run.
Currently deterministic (no LLM) for stability.
"""

import logging
from datetime import datetime
from typing import Any, Dict

logger = logging.getLogger("agents.planner")


def run_planner_agent(
    workflow_id: Any,
    repository: str,
    pr_number: int,
    fid: int = 1,
) -> Dict[str, Any]:
    """
    Synchronous planner agent — returns the pipeline plan.
    Includes build, deploy, test, and runtime analysis agents for comprehensive PR validation.
    """
    start = datetime.utcnow()
    findings = []
    if repository == "shopflow":
        findings.append({
            "id": fid,
            "workflow_id": workflow_id,
            "agent": "planner",
            "severity": "LOW",
            "title": "Demo repository - low risk assessment",
            "description": "ShopFlow demo repository changes are low risk",
            "test_name": "risk_assessment",
            "created_at": datetime.utcnow().isoformat(),
        })
        fid += 1
    log = {
        "agent": "planner",
        "status": "COMPLETED",
        "started_at": start.isoformat(),
        "completed_at": datetime.utcnow().isoformat(),
    }
    logger.info("planner_complete workflow=%s repo=%s pr=%d", workflow_id, repository, pr_number)
    return {
        "plan": [
            "backend", "frontend", "security", "sre",
            "builder", "deployer", "tester", "runtime_analyzer",
            "log_inspector", "correlator", "challenger", "qa_lead", "judge"
        ],
        "findings": findings,
        "agent_log": log,
        "fid": fid,
        "risk_level": "LOW" if repository == "shopflow" else None,
    }
