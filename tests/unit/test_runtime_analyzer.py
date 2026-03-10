import os
import subprocess
import sys

# ensure workspace root is on path so `agents` package is importable
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))

from agents.runtime_analyzer.runtime_analyzer_agent import run_runtime_analyzer_agent


class DummyCompleted:
    def __init__(self, returncode, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def fake_run(cmd, capture_output, text, timeout):
    # simple fake that inspects the docker subcommand
    if "logs" in cmd:
        # simulate an error message in logs
        return DummyCompleted(0, stdout="ERROR: something bad happened\n", stderr="")
    if "stats" in cmd:
        # return a JSON object with high CPU and memory
        return DummyCompleted(0, stdout='{"CPUPerc":"85%","MemUsage":"100MiB / 1GiB","MemPerc":"85%"}')
    return DummyCompleted(1)


def test_no_deploy_url():
    result = run_runtime_analyzer_agent(
        workflow_id="w1",
        repository="repo",
        pr_number=1,
        deploy_url="",
        test_results=None,
        container_name="",
        fid=1,
    )
    titles = [f.get("title", "") for f in result.get("findings", [])]
    assert "No deployment for analysis" in titles


def test_high_cpu_and_memory(monkeypatch):
    monkeypatch.setattr(subprocess, "run", fake_run)
    result = run_runtime_analyzer_agent(
        workflow_id="w2",
        repository="repo",
        pr_number=2,
        deploy_url="http://example.com",
        test_results={},
        container_name="container123",
        fid=1,
    )

    stats = result.get("analysis_results", {}).get("container_stats", {})
    assert stats.get("cpu_percent") == 85.0
    assert stats.get("memory_percent") == 85.0

    # ensure findings for high cpu and memory exist
    titles = [f.get("title", "") for f in result.get("findings", [])]
    assert any("High CPU" in t for t in titles)
    assert any("High memory" in t for t in titles)
    # also the log error from fake_run should generate a finding
    assert any("Runtime log issue" in t for t in titles)
