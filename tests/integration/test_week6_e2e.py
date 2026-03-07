import os
import time
import uuid
import subprocess

import json
import urllib.request
import urllib.error


BASE_URL = os.getenv("LANGGRAPH_URL", "http://localhost:8000")


def _http_get(path: str, timeout: float = 5.0):
    url = f"{BASE_URL}{path}"
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.load(resp)


def _http_post(path: str, payload: dict, timeout: float = 5.0):
    url = f"{BASE_URL}{path}"
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.load(resp)


def _psql_count(table: str) -> int:
    cmd = [
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
    ]

    out = subprocess.check_output(cmd, stderr=subprocess.STDOUT)
    return int(out.decode().strip())


def test_week6_end_to_end():
    # 1. OpenAPI
    paths = _http_get("/openapi.json").get("paths", {})
    assert "/api/workflow/start" in paths

    # 2. Start workflow
    payload = {"repo": "tuskeradmin/demo-store", "pr_number": int(uuid.uuid4().int % 1000)}
    data = _http_post("/api/workflow/start", payload)
    assert "workflow_id" in data
    wid = data["workflow_id"]
    assert data.get("status") == "RUNNING"

    # 3/4/5/6/7/8: Wait for orchestration to finish and persist
    findings = []
    agents = []
    governance = []
    workflow_state = {}

    # allow more time for background orchestration to finish in CI/host
    deadline = time.time() + 60
    while time.time() < deadline:
        workflow_state = _http_get(f"/api/workflow/{wid}")
        agents = _http_get(f"/api/workflows/{wid}/agents")
        findings = _http_get(f"/api/workflows/{wid}/findings")
        governance = _http_get(f"/api/workflows/{wid}/governance")

        if findings and agents and governance:
            break

        time.sleep(0.5)

    assert len(findings) >= 1, "Expected at least one finding"
    assert len(agents) == 7, f"Expected 7 agents in timeline, got {len(agents)}"
    expected_order = ["planner", "backend", "frontend", "security", "sre", "challenger", "judge"]
    assert [a["agent"] for a in agents] == expected_order

    assert workflow_state.get("status") in ("WAITING_HUMAN_APPROVAL", "COMPLETED")

    # 9. Database persistence checks via docker exec psql
    assert _psql_count("workflow_runs") >= 1
    assert _psql_count("engineering_findings") >= 1
    assert _psql_count("agent_execution_log") >= 7
    # challenger creates at least one challenge in our deterministic graph
    assert _psql_count("finding_challenges") >= 1
    assert _psql_count("governance_actions") >= 1
