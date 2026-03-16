"""
ShopFlow health endpoint tests.

These tests are committed into the shopflow repository (apps/backend/tests/)
so the TuskerSquad Backend Engineer agent can run them against the deployed
PR container during the review pipeline.

Run locally from project root:
    pytest apps/backend/tests/ -v
"""
from fastapi.testclient import TestClient
from apps.backend.main import app

client = TestClient(app)


def test_health_endpoint():
    """GET /health must return 200 with status=ok and service=shopflow-demo."""
    r = client.get("/health")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "ok"
    assert data["service"] == "shopflow-demo"
    assert isinstance(data["bugs_active"], list)


def test_health_no_bugs_by_default():
    """With no BUG_* env vars set, bugs_active should be empty."""
    import os
    import importlib
    for flag in ("BUG_PRICE", "BUG_SECURITY", "BUG_SLOW"):
        os.environ.pop(flag, None)
    import apps.backend.bug_flags as bf
    importlib.reload(bf)
    assert bf.BUG_PRICE is False
    assert bf.BUG_SECURITY is False
    assert bf.BUG_SLOW is False
