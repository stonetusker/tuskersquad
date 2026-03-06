from fastapi.testclient import TestClient
from main import app

def test_health_endpoint():

    client = TestClient(app)

    r = client.get("/health/llm")

    assert r.status_code == 200

    assert r.json()["status"] == "ok"
