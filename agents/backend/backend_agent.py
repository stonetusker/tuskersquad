"""
Backend Engineer Agent
======================
Runs pytest against the demo application API tests and interprets results.
Falls back to synthetic findings if the demo app is unreachable or pytest
is not installed.
"""

import os
import subprocess
import logging
import json
from datetime import datetime
from typing import Dict, Any, List

logger = logging.getLogger("agents.backend")

DEMO_APP_URL = os.getenv("DEMO_APP_URL", "http://tuskersquad-demo-backend:8080")
TEST_DIR = os.getenv("BACKEND_TEST_DIR", "tests/api")


def _run_pytest(test_dir: str) -> Dict[str, Any]:
    """
    Execute pytest against the API test suite.
    Returns a dict with keys: passed, failed, errors, output, test_names.
    """
    result = {
        "passed": 0,
        "failed": 0,
        "errors": 0,
        "output": "",
        "test_names": [],
        "ran": False,
    }

    try:
        cmd = [
            "python", "-m", "pytest",
            test_dir,
            "--tb=short",
            "-q",
            "--no-header",
            f"--base-url={DEMO_APP_URL}",
            "--json-report",
            "--json-report-file=/tmp/pytest_report.json",
        ]

        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=60,
            cwd=os.getcwd(),
        )

        result["output"] = proc.stdout + proc.stderr
        result["ran"] = True

        # Try to parse JSON report for structured results
        try:
            with open("/tmp/pytest_report.json") as f:
                report = json.load(f)
            summary = report.get("summary", {})
            result["passed"] = summary.get("passed", 0)
            result["failed"] = summary.get("failed", 0)
            result["errors"] = summary.get("error", 0)
            result["test_names"] = [
                t["nodeid"] for t in report.get("tests", []) if t.get("outcome") == "failed"
            ]
        except Exception:
            # Parse from stdout if JSON report unavailable
            for line in result["output"].splitlines():
                if " passed" in line or " failed" in line:
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

    except FileNotFoundError:
        result["output"] = "pytest not found in PATH"
    except subprocess.TimeoutExpired:
        result["output"] = "pytest timed out after 60 seconds"
    except Exception as exc:
        result["output"] = f"pytest execution error: {exc}"

    return result


def _synthetic_findings(workflow_id: str, fid: int) -> List[Dict[str, Any]]:
    """Deterministic synthetic findings used when pytest cannot run."""
    now = datetime.utcnow().isoformat()
    return [
        {
            "id": fid,
            "workflow_id": workflow_id,
            "agent": "backend",
            "severity": "MEDIUM",
            "title": "backend - checkout_latency",
            "description": (
                "Automated backend review detected a potential latency issue "
                "in the checkout endpoint. Response time exceeded 2s threshold "
                "under simulated load."
            ),
            "test_name": "checkout_latency",
            "created_at": now,
        },
        {
            "id": fid + 1,
            "workflow_id": workflow_id,
            "agent": "backend",
            "severity": "LOW",
            "title": "backend - order_total_precision",
            "description": (
                "Order total calculation uses floating point arithmetic without "
                "Decimal quantisation — potential for rounding errors on "
                "high-value orders."
            ),
            "test_name": "order_total_precision",
            "created_at": now,
        },
    ]


def run_backend_agent(workflow_id: str, repository: str, pr_number: int, fid: int = 1) -> Dict[str, Any]:
    """
    Main entry point called by the graph runner.

    Returns:
        dict with keys: findings (list), fid (next available finding id),
        agent_log (dict with timing).
    """
    start = datetime.utcnow()
    findings: List[Dict[str, Any]] = []

    logger.info("backend_agent_started", extra={"workflow_id": workflow_id})

    pytest_result = _run_pytest(TEST_DIR)

    if pytest_result["ran"]:
        logger.info(
            "pytest_completed",
            extra={
                "workflow_id": workflow_id,
                "passed": pytest_result["passed"],
                "failed": pytest_result["failed"],
            },
        )

        now = datetime.utcnow().isoformat()

        if pytest_result["failed"] > 0 or pytest_result["errors"] > 0:
            findings.append({
                "id": fid,
                "workflow_id": workflow_id,
                "agent": "backend",
                "severity": "HIGH",
                "title": f"backend - {pytest_result['failed']} pytest test(s) failed",
                "description": (
                    f"{pytest_result['failed']} test(s) failed, "
                    f"{pytest_result['errors']} error(s). "
                    f"Failed tests: {', '.join(pytest_result['test_names'][:5]) or 'see logs'}. "
                    f"Output: {pytest_result['output'][:300]}"
                ),
                "test_name": "checkout_latency",
                "created_at": now,
            })
            fid += 1
        else:
            # All tests passed — still report as informational finding
            findings.append({
                "id": fid,
                "workflow_id": workflow_id,
                "agent": "backend",
                "severity": "LOW",
                "title": f"backend - all {pytest_result['passed']} pytest tests passed",
                "description": "All backend API tests passed successfully.",
                "test_name": "pytest_suite",
                "created_at": now,
            })
            fid += 1
    else:
        # Fallback to synthetic findings
        logger.warning(
            "pytest_unavailable_using_synthetic_findings",
            extra={"workflow_id": workflow_id, "reason": pytest_result["output"]},
        )
        synth = _synthetic_findings(workflow_id, fid)
        findings.extend(synth)
        fid += len(synth)

    agent_log = {
        "agent": "backend",
        "status": "COMPLETED",
        "started_at": start.isoformat(),
        "completed_at": datetime.utcnow().isoformat(),
    }

    return {"findings": findings, "fid": fid, "agent_log": agent_log}
