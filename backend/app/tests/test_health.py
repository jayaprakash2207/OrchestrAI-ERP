from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_healthcheck() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] in {"healthy", "degraded", "unhealthy"}
    assert "database" in body
    assert "llm" in body
    assert "chromadb" in body
