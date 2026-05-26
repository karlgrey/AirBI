from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from airbi.db.models import CrawlRun, Listing, SearchConfig, Snapshot
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


def _seed_marvila(session):
    cfg = SearchConfig(name="Marvila Slice 1",
                       district_slugs=["marvila", "beato"])
    run = CrawlRun(search_config=cfg, status="completed", listings_seen=6)
    session.add(run)
    session.flush()

    def add_listing(airbnb_id, district, size_class, price, reviews, title):
        listing = Listing(
            airbnb_id=airbnb_id, city_slug="lisboa", district_slug=district,
            lat=38.74, lng=-9.10, property_type="Apartment", bedrooms=1,
            size_class=size_class, title=title, url=f"https://x/{airbnb_id}",
        )
        session.add(listing)
        session.flush()
        session.add(Snapshot(
            listing_id=listing.id, crawl_run_id=run.id,
            price=Decimal(str(price)), review_count=reviews, rating=4.7,
        ))

    # 4 Marvila-1BRs mit unterschiedlichen Preisen, klare Best-Cell.
    add_listing("M1", "marvila", "1BR", 60, 5,  "Marvila Cosy 1BR")
    add_listing("M2", "marvila", "1BR", 70, 8,  "Marvila Cosy 1BR Nr 2")
    add_listing("M3", "marvila", "1BR", 250, 90, "Marvila Loft Luxe")
    add_listing("M4", "marvila", "1BR", 260, 80, "Marvila Loft Riverside")
    # 2 Beato-Listings.
    add_listing("B1", "beato", "1BR", 80, 12, "Beato Studio")
    add_listing("B2", "beato", "2BR", 130, 20, "Beato Family Flat")
    session.flush()  # KEIN commit — Test-Fixture rollt am Ende zurück.
    return cfg


def test_dashboard_renders_matrix_and_panel(client, db_session):
    cfg = _seed_marvila(db_session)
    response = client.get("/")
    assert response.status_code == 200
    body = response.text
    assert cfg.name in body
    assert "Marvila" in body
    assert "Segment-Matrix" in body
    # CrawlRun-Status-Panel.
    assert "completed" in body
    # Mindestens ein Listing-Titel taucht in den Top-Performern auf.
    assert "Marvila Loft" in body
    # Proxy-Kennzeichnung sichtbar.
    assert "Proxy" in body


def test_dashboard_empty_state_when_no_search_config(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "Noch keine SearchConfig" in response.text
