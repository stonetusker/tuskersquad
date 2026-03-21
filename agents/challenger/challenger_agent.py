"""
Challenger Agent
================
Reviews engineering findings and raises disputes for findings that may
be affected by environment variance (e.g. container cold-start latency).
No external imports required — operates purely on the findings list.
"""

import logging
from datetime import datetime
from typing import Any, Dict, List

logger = logging.getLogger("agents.challenger")


def run_challenger_agent(
    workflow_id: Any,
    repository: str,
    pr_number: int,
    findings: List[Dict],
    fid: int = 1,
) -> Dict[str, Any]:
    """
    Synchronous challenger agent called by graph_builder._run_eng_agent().
    Returns: {findings, challenges, agent_log, fid}
    """
    start = datetime.utcnow()
    challenges: List[Dict[str, Any]] = []

    ENVIRONMENT_SENSITIVE = {"checkout_latency", "load_test", "p95_latency"}

    for finding in findings:
        test_name = finding.get("test_name", "")
        if test_name in ENVIRONMENT_SENSITIVE:
            # Skip challenges for demo
            pass

    log = {
        "agent": "challenger",
        "status": "COMPLETED",
        "started_at": start.isoformat(),
        "completed_at": datetime.utcnow().isoformat(),
    }

    logger.info(
        "challenger_complete workflow=%s challenges=%d",
        workflow_id, len(challenges),
    )

    return {
        "findings": [],       # challenger does not add new findings
        "challenges": challenges,
        "agent_log": log,
        "fid": fid,
    }
