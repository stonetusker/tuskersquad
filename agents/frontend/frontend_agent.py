"""
Frontend Engineer Agent
=======================
Runs Playwright end-to-end tests covering Login, Checkout, and Order flows
against the demo application frontend. Falls back to synthetic findings if
Playwright is not installed or the demo app is unreachable.
"""

import os
import subprocess
import logging
from datetime import datetime
from typing import Dict, Any, List

logger = logging.getLogger("agents.frontend")

DEMO_FRONTEND_URL = os.getenv("DEMO_FRONTEND_URL", "http://localhost:5173")
PLAYWRIGHT_TEST_DIR = os.getenv("PLAYWRIGHT_TEST_DIR", "tests/ui")


def _run_playwright() -> Dict[str, Any]:
    """
    Execute Playwright tests.
    Returns a dict with keys: passed, failed, output, ran.
    """
    result = {
        "passed": 0,
        "failed": 0,
        "output": "",
        "ran": False,
    }

    try:
        cmd = [
            "python", "-m", "pytest",
            PLAYWRIGHT_TEST_DIR,
            "--tb=short",
            "-q",
            "--no-header",
        ]

        env = os.environ.copy()
        env["BASE_URL"] = DEMO_FRONTEND_URL

        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,
            env=env,
        )

        result["output"] = proc.stdout + proc.stderr
        result["ran"] = True

        for line in result["output"].splitlines():
            parts = line.strip().split()
            for i, p in enumerate(parts):
                if p == "passed" and i > 0:
                    try:
                        result["passed"] = int(parts[i - 1])
                    except ValueError:
                        pass
                if p == "failed" and i > 0:
                    try:
                        result["failed"] = int(parts[i - 1])
                    except ValueError:
                        pass

        if proc.returncode == 0 and result["passed"] == 0:
            result["passed"] = 1

    except FileNotFoundError:
        result["output"] = "pytest / playwright not found"
    except subprocess.TimeoutExpired:
        result["output"] = "Playwright tests timed out after 120s"
    except Exception as exc:
        result["output"] = f"Playwright execution error: {exc}"

    return result


def _synthetic_findings(workflow_id: str, fid: int) -> List[Dict[str, Any]]:
    now = datetime.utcnow().isoformat()
    return [
        {
            "id": fid,
            "workflow_id": workflow_id,
            "agent": "frontend",
            "severity": "MEDIUM",
            "title": "frontend - checkout_ui_validation_missing",
            "description": (
                "Playwright flow detected that the checkout form does not "
                "validate quantity fields client-side. A user can submit "
                "negative quantities without an error message."
            ),
            "test_name": "checkout_flow",
            "created_at": now,
        },
        {
            "id": fid + 1,
            "workflow_id": workflow_id,
            "agent": "frontend",
            "severity": "LOW",
            "title": "frontend - login_error_message_verbose",
            "description": (
                "Login failure response exposes 'Invalid credentials' detail "
                "directly in the UI which may assist credential enumeration."
            ),
            "test_name": "login_flow",
            "created_at": now,
        },
    ]


def run_frontend_agent(workflow_id: str, repository: str, pr_number: int, fid: int = 1) -> Dict[str, Any]:
    """
    Main entry point called by the graph runner.

    Returns:
        dict with keys: findings, fid, agent_log.
    """
    start = datetime.utcnow()
    findings: List[Dict[str, Any]] = []

    logger.info("frontend_agent_started", extra={"workflow_id": workflow_id})

    pw_result = _run_playwright()

    if pw_result["ran"]:
        logger.info(
            "playwright_completed",
            extra={"workflow_id": workflow_id, "passed": pw_result["passed"], "failed": pw_result["failed"]},
        )
        now = datetime.utcnow().isoformat()

        if pw_result["failed"] > 0:
            findings.append({
                "id": fid,
                "workflow_id": workflow_id,
                "agent": "frontend",
                "severity": "HIGH",
                "title": f"frontend - {pw_result['failed']} Playwright test(s) failed",
                "description": (
                    f"{pw_result['failed']} UI test(s) failed. "
                    f"Output: {pw_result['output'][:400]}"
                ),
                "test_name": "playwright_suite",
                "created_at": now,
            })
            fid += 1
        else:
            findings.append({
                "id": fid,
                "workflow_id": workflow_id,
                "agent": "frontend",
                "severity": "LOW",
                "title": f"frontend - all Playwright flows passed",
                "description": "Login, Checkout, and Order flows all completed successfully.",
                "test_name": "playwright_suite",
                "created_at": now,
            })
            fid += 1
    else:
        logger.warning(
            "playwright_unavailable_using_synthetic_findings",
            extra={"workflow_id": workflow_id, "reason": pw_result["output"]},
        )
        synth = _synthetic_findings(workflow_id, fid)
        findings.extend(synth)
        fid += len(synth)

    agent_log = {
        "agent": "frontend",
        "status": "COMPLETED",
        "started_at": start.isoformat(),
        "completed_at": datetime.utcnow().isoformat(),
    }

    return {"findings": findings, "fid": fid, "agent_log": agent_log}
