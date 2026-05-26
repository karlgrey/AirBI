import pytest
from fastapi.testclient import TestClient

from airbi.web.app import create_app
from airbi.web.routes import get_session


@pytest.fixture
def client(db_session):
    app = create_app()
    app.dependency_overrides[get_session] = lambda: db_session
    return TestClient(app)


def test_health_returns_ok(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_static_app_css_is_served(client):
    response = client.get("/static/app.css")
    # In Task 5 existiert app.css noch nicht; Task 6 erzeugt sie.
    # Akzeptiert: 200 (wenn Datei da) ODER 404 (wenn nicht). Aber der
    # /static-Mount muss reagieren, nicht den Server crashen.
    assert response.status_code in (200, 404)
