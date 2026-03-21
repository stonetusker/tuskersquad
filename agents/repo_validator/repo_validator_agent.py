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
    provider_init_error = None
    try:
        from services.langgraph_api.core.git_provider import get_provider
        provider = get_provider(None)
    except Exception as e:
        provider_init_error = str(e)

    repo_ok = False
    pr_ok = False
    branch_ok = False
    provider_error = None

    # Check if provider is properly configured (not just instantiated)
    if not provider:
        findings.append({
            "id": fid,
            "agent": "repo_validator",
            "severity": "HIGH",
            "title": "Git provider failed to initialize",
            "description": (
                f"Could not initialise a Git provider client: {provider_init_error}. "
                "Check GIT_PROVIDER environment variable and provider-specific config."
            ),
            "test_name": "git_provider_config",
        })
        fid += 1
    elif not provider._url() or not provider._token():
        # Provider exists but is not properly configured
        missing = []
        if not provider._url():
            missing.append("GITEA_URL")
        if not provider._token():
            missing.append("GITEA_TOKEN")
        findings.append({
            "id": fid,
            "agent": "repo_validator",
            "severity": "HIGH",
            "title": "Git provider not configured",
            "description": (
                f"Git provider '{provider.name}' is missing required environment variables: {', '.join(missing)}. "
                f"For Gitea: GITEA_URL should be 'http://tuskersquad-gitea:3000' (or your Gitea instance) "
                f"and GITEA_TOKEN must be a personal access token with repository and issue read/write scopes. "
                f"Generate token at Gitea Settings → Applications → Generate Token."
            ),
            "test_name": "git_provider_config",
        })
        fid += 1
    else:
        try:
            pr_info = provider.get_pr_info(repository, pr_number)
            if pr_info:
                repo_ok = True
                pr_ok = True
                # try to clone and checkout the head SHA in temp location
                import tempfile
                with tempfile.TemporaryDirectory() as d:
                    gitea_url = os.getenv("GITEA_URL", "http://tuskersquad-gitea:3000").rstrip("/")
                    repo_url = f"{gitea_url}/{repository}.git"
                    clone_cmd = ["git", "clone", "--depth", "1", repo_url, d]
                    r = subprocess.run(clone_cmd, capture_output=True, text=True, timeout=120)
                    if r.returncode != 0:
                        findings.append({
                            "id": fid,
                            "agent": "repo_validator",
                            "severity": "HIGH",
                            "title": "Repository clone failed",
                            "description": (
                                f"Could not clone {repo_url}. "
                                f"Git error: {r.stderr[:300] or r.stdout[:300]}"
                            ),
                            "test_name": "repo_clone",
                        })
                        fid += 1
                    elif pr_info.head_sha:
                        co = subprocess.run(
                            ["git", "fetch", "origin", pr_info.head_sha],
                            cwd=d, capture_output=True, text=True, timeout=60
                        )
                        co2 = subprocess.run(
                            ["git", "checkout", pr_info.head_sha],
                            cwd=d, capture_output=True, text=True, timeout=60
                        )
                        if co.returncode == 0 and co2.returncode == 0:
                            branch_ok = True
                        else:
                            findings.append({
                                "id": fid,
                                "agent": "repo_validator",
                                "severity": "HIGH",
                                "title": "Cannot checkout PR commit",
                                "description": (
                                    f"Could not checkout SHA {pr_info.head_sha}. "
                                    f"Fetch: {co.stderr[:150]}. Checkout: {co2.stderr[:150]}"
                                ),
                                "test_name": "pr_checkout",
                            })
                            fid += 1
                    else:
                        # No head_sha - still reachable, treat as partially valid
                        branch_ok = True
            else:
                findings.append({
                    "id": fid,
                    "agent": "repo_validator",
                    "severity": "HIGH",
                    "title": "Pull request not found",
                    "description": (
                        f"PR #{pr_number} not found in repository {repository}. "
                        "The PR may have been closed, merged, or the repository name is incorrect."
                    ),
                    "test_name": "pr_exists",
                })
                fid += 1
        except Exception as exc:
            provider_error = str(exc)
            logger.warning("repo_validator_provider_exception %s", exc)
            findings.append({
                "id": fid,
                "agent": "repo_validator",
                "severity": "HIGH",
                "title": f"Repository not accessible: {repository}",
                "description": (
                    f"Failed to retrieve PR #{pr_number} from repository {repository}. "
                    f"Error: {str(exc)[:400]}. "
                    "Verify GITEA_URL is correct and Gitea is healthy, "
                    "and that GITEA_TOKEN has the required scopes."
                ),
                "test_name": "repo_access",
            })
            fid += 1

    # Determine if validator failed: any HIGH finding means we cannot proceed
    high_findings = [f for f in findings if f.get("severity") == "HIGH"]
    failed = len(high_findings) > 0

    log = {
        "agent": "repo_validator",
        "status": "COMPLETED",
        "started_at": start.isoformat(),
        "completed_at": datetime.utcnow().isoformat(),
        "repo_ok": repo_ok,
        "pr_ok": pr_ok,
        "branch_ok": branch_ok,
        "validator_failed": failed,
        "provider_available": provider is not None,
    }

    if not failed:
        logger.info("repo_validator_passed workflow=%s repo=%s pr=%d", workflow_id, repository, pr_number)
    else:
        logger.error("repo_validator_failed workflow=%s repo=%s pr=%d findings=%d",
                     workflow_id, repository, pr_number, len(high_findings))

    return {"findings": findings, "agent_log": log, "fid": fid, "validator_failed": failed}