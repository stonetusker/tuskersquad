"""
API Validation Agent
====================
Sends simple HTTP requests to important endpoints and verifies responses.
"""

import logging
import subprocess
from datetime import datetime
from typing import Any, Dict, List

logger = logging.getLogger("agents.api_validator")


def run_api_validator_agent(
    workflow_id: Any,
    repository: str,
    pr_number: int,
    deploy_url: str = "",
    fid: int = 1,
) -> Dict[str, Any]:
    start = datetime.utcnow()
    findings: List[Dict[str, Any]] = []
    tests_run = 0

    if not deploy_url:
        findings.append({
            "id": fid,
            "agent": "api_validator",
            "severity": "HIGH",
            "title": "No deployment URL",
            "description": "Cannot perform API validation without deploy_url",
            "test_name": "deploy_url",
        })
        fid += 1
    else:
        endpoints = ["/health", "/products", "/user/profile"]
        for ep in endpoints:
            tests_run += 1
            try:
                cmd = ["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}", "--max-time", "10",
                       f"{deploy_url}{ep}"]
                res = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
                code = res.stdout.strip() if res.returncode == 0 else "000"
                if code != "200":
                    findings.append({
                        "id": fid,
                        "agent": "api_validator",
                        "severity": "MEDIUM",
                        "title": f"API {ep} returned {code}",
                        "description": res.stderr or "unexpected status",
                        "test_name": "api_status",
                    })
                fid += 1
            except Exception as e:
                findings.append({
                    "id": fid,
                    "agent": "api_validator",
                    "severity": "MEDIUM",
                    "title": f"API call {ep} failed",
                    "description": str(e),
                    "test_name": "api_status",
                })
                fid += 1

    log = {
        "agent": "api_validator",
        "status": "COMPLETED",
        "started_at": start.isoformat(),
        "completed_at": datetime.utcnow().isoformat(),
        "tests_run": tests_run,
    }
    return {"findings": findings, "agent_log": log, "fid": fid}