from fastapi.testclient import TestClient

from glassdesk.app import create_app
from glassdesk.config import Settings


def make_settings() -> Settings:
    return Settings(
        database_url="postgresql+psycopg://u:p@localhost:5432/glassdesk",
        steward_api_key="stw_test_key",
        session_secret="s" * 32,
    )


def test_health_reports_ok() -> None:
    client = TestClient(create_app(make_settings()))
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
