"""
Tests for ShopFlow demo backend health endpoint.
Run from the project root:  pytest tests/api/test_health.py
"""
from fastapi.testclient import TestClient
from apps.backend.main import app

client = TestClient(app)


def test_health_endpoint():
    """GET /health must return 200 with status=ok."""
    r = client.get("/health")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "ok"
    assert data["service"] == "shopflow-demo"
    # bugs_active is a list (may be empty or have entries depending on env)
    assert isinstance(data["bugs_active"], list)


def test_health_no_bugs_by_default():
    """With no BUG_* env vars set, bugs_active should be empty."""
    import os
    # Ensure all bug flags are off for this test
    for flag in ("BUG_PRICE", "BUG_SECURITY", "BUG_SLOW"):
        os.environ.pop(flag, None)
    r = client.get("/health")
    assert r.status_code == 200
    # bug_flags module may have been imported already — reload to pick up env change
    import importlib
    import apps.backend.bug_flags as bf
    importlib.reload(bf)
    # After reload, flags should be False
    assert bf.BUG_PRICE is False
    assert bf.BUG_SECURITY is False
    assert bf.BUG_SLOW is False
