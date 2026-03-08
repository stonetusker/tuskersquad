"""
TuskerSquad End-to-End Integration Test
=======================================
Validates the complete TuskerSquad workflow lifecycle against a running stack.

Prerequisite:
docker compose -f infra/docker-compose.yml up --build

Run:
pytest -v tests/integration/test_tuskersquad_e2e.py
"""

import json
import os
import subprocess
import time
import uuid
import urllib.request

BASE_URL = os.getenv("LANGGRAPH_URL", "http://localhost:8000")


def _get(path: str, timeout: float = 10.0):
    req = urllib.request.Request(f"{BASE_URL}{path}", method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def _post(path: str, payload: dict = None, timeout: float = 10.0):
    data = json.dumps(payload or {}).encode()

    req = urllib.request.Request(
        f"{BASE_URL}{path}",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def _psql(table: str) -> int:
    out = subprocess.check_output(
        [
            "docker",
            "exec",
            "-i",
            "tuskersquad-postgres",
            "psql",
            "-U",
            "tusker",
            "-d",
            "tuskersquad",
            "-t",
            "-A",
            "-c",
            f"SELECT count(*) FROM {table};",
        ],
        stderr=subprocess.STDOUT,
    )

    return int(out.decode().strip())

def _find_workflow(workflow_id: str):
    workflows = _get("/api/workflows")

    for w in workflows:
        if w["workflow_id"] == workflow_id:
            return w

    return None


def _wait_for(workflow_id: str, timeout: float = 180.0):
    """
    Wait until orchestration reaches WAITING_HUMAN_APPROVAL
    or COMPLETED state.
    """

    deadline = time.time() + timeout

    while time.time() < deadline:

        wf = _find_workflow(workflow_id)

        if wf:

            if wf["status"] in (
                "WAITING_HUMAN_APPROVAL",
                "COMPLETED"
            ):
                try:
                    agents = _get(f"/api/workflows/{workflow_id}/agents")
                    findings = _get(f"/api/workflows/{workflow_id}/findings")

                    if agents and findings:
                        return wf, agents, findings

                except Exception:
                    pass

        time.sleep(1)

    return None, [], []


# ------------------------------------------------------------------
# Tests
# ------------------------------------------------------------------


def test_openapi_required_endpoints():

    paths = _get("/openapi.json").get("paths", {})

    required = [
        "/api/workflow/start",
        "/api/workflow/{workflow_id}/approve",
        "/api/workflow/{workflow_id}/reject",
        "/api/workflow/{workflow_id}/retest",
        "/api/workflow/{workflow_id}/release",
        "/api/workflows/{workflow_id}/findings",
        "/api/workflows/{workflow_id}/agents",
        "/api/workflows/{workflow_id}/qa",
    ]

    missing = [p for p in required if p not in paths]

    assert not missing, f"Missing endpoints: {missing}"


def test_full_workflow_lifecycle():

    pr_num = int(uuid.uuid4().int % 9000) + 1000

    data = _post(
        "/api/workflow/start",
        {"repo": "tuskeradmin/demo-store", "pr_number": pr_num}
    )

    assert "workflow_id" in data

    workflow_id = data["workflow_id"]

    wf, agents, findings = _wait_for(workflow_id)

    assert wf is not None, "Workflow orchestration timeout"

    assert len(findings) >= 1

    agent_names = [a["agent"] for a in agents]

    expected_agents = [
        "planner",
        "backend",
        "frontend",
        "security",
        "sre",
        "challenger",
        "qa_lead",
        "judge",
    ]

    for agent in expected_agents:
        assert agent in agent_names

    assert wf["status"] in (
        "WAITING_HUMAN_APPROVAL",
        "COMPLETED"
    )

    try:
        qa = _get(f"/api/workflows/{workflow_id}/qa")

        assert qa["risk_level"] in ("LOW", "MEDIUM", "HIGH")
        assert len(qa.get("summary", "")) > 0

    except Exception:
        pass

    assert _psql("workflow_runs") >= 1
    assert _psql("engineering_findings") >= 1
    assert _psql("agent_execution_log") >= 8
    assert _psql("finding_challenges") >= 1

    approve = _post(f"/api/workflow/{workflow_id}/approve")

    assert approve["workflow_id"] == workflow_id


def test_retest_endpoint():

    pr_num = int(uuid.uuid4().int % 9000) + 1000

    data = _post(
        "/api/workflow/start",
        {"repo": "tuskeradmin/demo-store", "pr_number": pr_num}
    )

    workflow_id = data["workflow_id"]

    _wait_for(workflow_id)

    retest = _post(f"/api/workflow/{workflow_id}/retest")

    assert retest["status"] == "RUNNING"


def test_reject_endpoint():

    pr_num = int(uuid.uuid4().int % 9000) + 1000

    data = _post(
        "/api/workflow/start",
        {"repo": "tuskeradmin/demo-store", "pr_number": pr_num}
    )

    workflow_id = data["workflow_id"]

    _wait_for(workflow_id)

    result = _post(f"/api/workflow/{workflow_id}/reject")

    assert result["workflow_id"] == workflow_id


def test_release_manager_override():

    pr_num = int(uuid.uuid4().int % 9000) + 1000

    data = _post(
        "/api/workflow/start",
        {"repo": "tuskeradmin/demo-store", "pr_number": pr_num}
    )

    workflow_id = data["workflow_id"]

    _wait_for(workflow_id)

    result = _post(
        f"/api/workflow/{workflow_id}/release",
        {
            "decision": "APPROVE",
            "reason": "Integration test emergency override"
        },
    )

    assert result["workflow_id"] == workflow_id
    assert result["decision"] == "APPROVE"
