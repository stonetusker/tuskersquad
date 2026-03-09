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
    All 4 engineering agents always run for maximum coverage.
    """
    start = datetime.utcnow()
    log = {
        "agent": "planner",
        "status": "COMPLETED",
        "started_at": start.isoformat(),
        "completed_at": datetime.utcnow().isoformat(),
    }
    logger.info("planner_complete workflow=%s repo=%s pr=%d", workflow_id, repository, pr_number)
    return {
        "plan": ["backend", "frontend", "security", "sre"],
        "findings": [],
        "agent_log": log,
        "fid": fid,
    }
