from fastapi.testclient import TestClient

from shelfwise import __version__
from shelfwise.api.main import create_app
from shelfwise.config import Settings


def test_health_reports_version_and_profile() -> None:
    client = TestClient(create_app(Settings(profile="cpu", log_json=False)))

    response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": __version__, "profile": "cpu"}
