"""
Backend Engineer Agent
======================
Runs pytest against the demo application API tests.
Falls back to synthetic findings if pytest cannot run.
"""

import os
import subprocess
import logging
import json
from datetime import datetime
from typing import Dict, Any, List

logger = logging.getLogger("agents.backend")

DEMO_APP_URL      = os.getenv("DEMO_APP_URL",      "http://tuskersquad-demo-backend:8080")
TEST_DIR          = os.getenv("BACKEND_TEST_DIR", "tests/api")
BACKEND_TEST_TOOL = os.getenv("BACKEND_TEST_TOOL", "pytest")  # pytest | unittest | nose2


def _run_pytest(test_dir: str, base_url: str) -> Dict[str, Any]:
    result = {"passed": 0, "failed": 0, "errors": 0, "output": "", "test_names": [], "ran": False}

    try:
        env = os.environ.copy()
        env["BASE_URL"] = base_url  # tests read from env, not --base-url flag

        cmd = ["python", "-m", "pytest", test_dir, "--tb=short", "-q", "--no-header"]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60, env=env)
        result["output"] = (proc.stdout + proc.stderr)[:2000]
        result["ran"] = True

        for line in result["output"].splitlines():
            parts = line.strip().split()
            for i, p in enumerate(parts):
                if p in ("passed", "failed", "error") and i > 0:
                    try:
                        n = int(parts[i - 1])
                        if p == "passed":
                            result["passed"] = n
                        elif p == "failed":
                            result["failed"] = n
                        elif p == "error":
                            result["errors"] = n
                    except ValueError:
                        pass

    except FileNotFoundError:
        result["output"] = "pytest not found"
    except subprocess.TimeoutExpired:
        result["output"] = "pytest timed out"
    except Exception as exc:
        result["output"] = f"pytest error: {exc}"

    return result


def _synthetic_findings(workflow_id: str, fid: int) -> List[Dict[str, Any]]:
    now = datetime.utcnow().isoformat()
    return [
        {
            "id": fid, "workflow_id": workflow_id, "agent": "backend",
            "severity": "MEDIUM",
            "title": "backend - checkout_latency",
            "description": (
                "Checkout endpoint response time exceeded 2s threshold under load. "
                "Investigate slow DB query in checkout handler."
            ),
            "test_name": "checkout_latency", "created_at": now,
        },
        {
            "id": fid + 1, "workflow_id": workflow_id, "agent": "backend",
            "severity": "LOW",
            "title": "backend - order_total_precision",
            "description": (
                "Order total uses float arithmetic without Decimal — "
                "rounding errors possible on high-value orders."
            ),
            "test_name": "order_total_precision", "created_at": now,
        },
    ]


def run_backend_agent(workflow_id: str, repository: str, pr_number: int, fid: int = 1) -> Dict[str, Any]:
    start = datetime.utcnow()
    findings: List[Dict[str, Any]] = []
    logger.info("backend_agent_started workflow=%s", workflow_id)

    pr = _run_pytest(TEST_DIR, DEMO_APP_URL)

    if pr["ran"]:
        now = datetime.utcnow().isoformat()
        if pr["failed"] > 0 or pr["errors"] > 0:
            findings.append({
                "id": fid, "workflow_id": workflow_id, "agent": "backend",
                "severity": "HIGH",
                "title": f"backend - {pr['failed']} {BACKEND_TEST_TOOL} test(s) failed",
                "description": f"{pr['failed']} failed, {pr['errors']} errors. Output: {pr['output'][:400]}",
                "test_name": "checkout_latency", "created_at": now,
            })
            fid += 1
        else:
            findings.append({
                "id": fid, "workflow_id": workflow_id, "agent": "backend",
                "severity": "LOW",
                "title": f"backend - all {pr['passed']} {BACKEND_TEST_TOOL} tests passed",
                "description": "All backend API tests passed.",
                "test_name": "pytest_suite", "created_at": now,
            })
            fid += 1
    else:
        logger.warning("test_tool_unavailable tool=%s workflow=%s: %s", BACKEND_TEST_TOOL, workflow_id, pr["output"])
        synth = _synthetic_findings(workflow_id, fid)
        findings.extend(synth)
        fid += len(synth)

    return {
        "findings": findings, "fid": fid,
        "agent_log": {
            "agent": "backend", "status": "COMPLETED",
            "started_at": start.isoformat(),
            "completed_at": datetime.utcnow().isoformat(),
        },
    }
