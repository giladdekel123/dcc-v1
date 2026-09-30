from fastapi.testclient import TestClient

from app.main import app


def test_app_serves_health_and_index(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    client = TestClient(app)

    health = client.get("/api/health")
    assert health.status_code == 200
    assert health.json() == {
        "status": "ok",
        "app": "DCC V1",
        "version": "0.1.0",
        "database": "not_configured",
    }

    index = client.get("/")
    assert index.status_code == 200
    assert "DCC V1" in index.text and 'id="search-form"' in index.text and 'id="refine"' in index.text

    for asset, content_type in (("/app.js", "javascript"), ("/styles.css", "text/css")):
        response = client.get(asset)
        assert response.status_code == 200 and content_type in response.headers["content-type"]
