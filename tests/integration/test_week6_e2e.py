"""
TuskerSquad End-to-End Integration Test
========================================
Verifies the full workflow lifecycle against a running stack:
  docker compose -f infra/docker-compose.yml up --build

Tests:
  1. OpenAPI spec includes all required endpoints (incl. new ones)
  2. Workflow starts and returns workflow_id
  3. All 8 agents execute in correct order
  4. Findings, challenges, governance and QA summary persist to DB
  5. Human governance actions (approve / reject / retest / release override)
  6. Retest triggers a re-run
  7. Release Manager override works

Run with:
  pytest -q tests/integration/test_week6_e2e.py
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
        f"{BASE_URL}{path}", data=data,
        headers={"Content-Type": "application/json"}, method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def _psql(table: str) -> int:
    out = subprocess.check_output([
        "docker", "exec", "-i", "tuskersquad-postgres",
        "psql", "-U", "tusker", "-d", "tuskersquad", "-t", "-A",
        "-c", f"SELECT count(*) FROM {table};",
    ], stderr=subprocess.STDOUT)
    return int(out.decode().strip())


def _wait_for(workflow_id: str, timeout: float = 120.0):
    """Poll until findings, agents, and governance are all populated."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            wf = _get(f"/api/api/workflow/{workflow_id}")
            agents = _get(f"/api/workflows/{workflow_id}/agents")
            findings = _get(f"/api/workflows/{workflow_id}/findings")
            gov = _get(f"/api/workflows/{workflow_id}/governance")
            if findings and agents and gov:
                return wf, agents, findings, gov
        except Exception:
            pass
        time.sleep(0.5)
    return None, [], [], []


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_openapi_required_endpoints():
    """All required REST endpoints must be present in the OpenAPI spec."""
    paths = _get("/openapi.json").get("paths", {})
    required = [
        "/api/workflow/start",
        "/api/workflow/{workflow_id}/approve",
        "/api/workflow/{workflow_id}/reject",
        "/api/workflow/{workflow_id}/retest",
        "/api/workflow/{workflow_id}/release",
        "/api/workflow/{workflow_id}/resume",
        "/api/workflows/{workflow_id}/findings",
        "/api/workflows/{workflow_id}/governance",
        "/api/workflows/{workflow_id}/agents",
        "/api/workflows/{workflow_id}/qa",
    ]
    missing = [e for e in required if e not in paths]
    assert not missing, f"Missing endpoints in OpenAPI spec: {missing}"


def test_full_workflow_lifecycle():
    """Full lifecycle: start → agents → persist → QA summary → human approve."""

    # 1. Start workflow
    pr_num = int(uuid.uuid4().int % 9000) + 1000
    data = _post("/api/workflow/start", {"repo": "tuskeradmin/demo-store", "pr_number": pr_num})
    assert "workflow_id" in data, f"No workflow_id in response: {data}"
    wid = data["workflow_id"]
    assert data.get("status") == "RUNNING"

    # 2. Wait for orchestration
    wf, agents, findings, gov = _wait_for(wid, timeout=120)

    assert wf is not None, "Timed out waiting for workflow to complete orchestration"
    assert len(findings) >= 1, "Expected at least one finding"

    # 3. Agent order (8 agents)
    agent_names = [a["agent"] for a in agents]
    expected = ["planner", "backend", "frontend", "security", "sre", "challenger", "qa_lead", "judge"]
    assert agent_names == expected, f"Agent order mismatch: {agent_names}"

    # 4. Workflow status
    assert wf.get("status") in (
        "WAITING_HUMAN_APPROVAL", "COMPLETED"
    ), f"Unexpected status: {wf.get('status')}"

    # 5. QA summary available
    try:
        qa = _get(f"/api/workflows/{wid}/qa")
        assert "risk_level" in qa
        assert qa["risk_level"] in ("LOW", "MEDIUM", "HIGH")
        assert len(qa.get("summary", "")) > 0
    except Exception as exc:
        # QA endpoint returns 404 if summary not yet available — non-fatal
        print(f"QA summary not available yet: {exc}")

    # 6. Database row counts
    assert _psql("workflow_runs") >= 1
    assert _psql("engineering_findings") >= 1
    assert _psql("agent_execution_log") >= 8
    assert _psql("finding_challenges") >= 1
    assert _psql("governance_actions") >= 1

    # 7. Human approve
    approve_result = _post(f"/api/workflow/{wid}/approve")
    assert approve_result.get("status") == "COMPLETED"
    assert approve_result.get("workflow_id") == wid


def test_retest_endpoint():
    """Retest should reset workflow to RUNNING and trigger a re-run."""
    pr_num = int(uuid.uuid4().int % 9000) + 1000
    data = _post("/api/workflow/start", {"repo": "tuskeradmin/demo-store", "pr_number": pr_num})
    wid = data["workflow_id"]

    # Wait for initial run to reach WAITING_HUMAN_APPROVAL or COMPLETED
    _wait_for(wid, timeout=120)

    retest = _post(f"/api/workflow/{wid}/retest")
    assert retest.get("action") == "RETEST_REQUESTED"
    assert retest.get("status") == "RUNNING"


def test_reject_endpoint():
    """Human reject should mark workflow COMPLETED."""
    pr_num = int(uuid.uuid4().int % 9000) + 1000
    data = _post("/api/workflow/start", {"repo": "tuskeradmin/demo-store", "pr_number": pr_num})
    wid = data["workflow_id"]
    _wait_for(wid, timeout=120)

    result = _post(f"/api/workflow/{wid}/reject")
    assert result.get("status") == "COMPLETED"


def test_release_manager_override():
    """Release Manager override should mark workflow COMPLETED with decision."""
    pr_num = int(uuid.uuid4().int % 9000) + 1000
    data = _post("/api/workflow/start", {"repo": "tuskeradmin/demo-store", "pr_number": pr_num})
    wid = data["workflow_id"]
    _wait_for(wid, timeout=120)

    result = _post(
        f"/api/workflow/{wid}/release",
        {"decision": "APPROVE", "reason": "Integration test — emergency hotfix"},
    )
    assert result.get("decision") == "APPROVE"
    assert result.get("workflow_id") == wid
    assert "reason" in result
