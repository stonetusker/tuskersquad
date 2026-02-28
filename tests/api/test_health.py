from fastapi.testclient import TestClient
from services.langgraph_api.main import app

def test_health_endpoint():

    client = TestClient(app)

    r = client.get("/health/llm")

    assert r.status_code == 200

    assert r.json()["status"] == "ok"
