"""
Repository Validator Agent
=========================
Verifies that the repository and PR exist and are accessible.
"""

import logging
import os
import subprocess
from datetime import datetime
from typing import Any, Dict, List

logger = logging.getLogger("agents.repo_validator")


def run_repo_validator_agent(
    workflow_id: Any,
    repository: str,
    pr_number: int,
    fid: int = 1,
) -> Dict[str, Any]:
    """
    Confirm repository/PR accessibility and ability to checkout the branch.
    Returns findings list with severity HIGH if validation fails.
    """
    start = datetime.utcnow()
    findings: List[Dict[str, Any]] = []

    # use Git provider to check PR info
    provider = None
    try:
        from core.git_provider import get_provider
        provider = get_provider(None)
    except Exception:
        provider = None

    repo_ok = False
    pr_ok = False
    branch_ok = False

    try:
        if provider:
            pr_info = provider.get_pr_info(repository, pr_number)
            if pr_info:
                repo_ok = True
                pr_ok = True
                # try to clone and checkout the head SHA in temp location
                import tempfile
                with tempfile.TemporaryDirectory() as d:
                    repo_url = f"http://tuskersquad-gitea:3000/{repository}.git"
                    clone_cmd = ["git", "clone", "--depth", "1", repo_url, d]
                    r = subprocess.run(clone_cmd, capture_output=True, text=True, timeout=120)
                    if r.returncode == 0 and pr_info.head_sha:
                        co = subprocess.run(["git", "fetch", "origin", pr_info.head_sha], cwd=d,
                                            capture_output=True, text=True, timeout=60)
                        if co.returncode == 0:
                            co2 = subprocess.run(["git", "checkout", pr_info.head_sha], cwd=d,
                                                 capture_output=True, text=True, timeout=60)
                            if co2.returncode == 0:
                                branch_ok = True
    except Exception as exc:
        logger.warning("repo_validator_exception %s", exc)

    if not repo_ok:
        findings.append({
            "id": fid,
            "agent": "repo_validator",
            "severity": "HIGH",
            "title": "Repository inaccessible",
            "description": f"Repository {repository} not found or not accessible",
            "test_name": "repo_access",
        })
        fid += 1
    if not pr_ok:
        findings.append({
            "id": fid,
            "agent": "repo_validator",
            "severity": "HIGH",
            "title": "Pull request missing",
            "description": f"PR #{pr_number} does not exist in {repository}",
            "test_name": "pr_exists",
        })
        fid += 1
    if repo_ok and pr_ok and not branch_ok:
        findings.append({
            "id": fid,
            "agent": "repo_validator",
            "severity": "HIGH",
            "title": "Cannot checkout PR branch",
            "description": "Failed to clone or checkout PR commit",
            "test_name": "pr_checkout",
        })
        fid += 1

    log = {
        "agent": "repo_validator",
        "status": "COMPLETED",
        "started_at": start.isoformat(),
        "completed_at": datetime.utcnow().isoformat(),
        "repo_ok": repo_ok,
        "pr_ok": pr_ok,
        "branch_ok": branch_ok,
    }

    return {"findings": findings, "agent_log": log, "fid": fid, "validator_failed": not (repo_ok and pr_ok and branch_ok)}