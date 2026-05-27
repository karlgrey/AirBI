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
    assert "Marktübersicht" in body
    # CrawlRun-Status-Panel.
    assert "vollständig erfasst" in body
    # Mindestens ein Listing-Titel taucht in den Top-Performern auf.
    assert "Marvila Loft" in body
    # Proxy-Kennzeichnung sichtbar.
    assert "geschätzte Nachfrage" in body



def test_matrix_partial_returns_single_district(client, db_session):
    cfg = _seed_marvila(db_session)
    response = client.get(f"/matrix?config_id={cfg.id}&district=marvila")
    assert response.status_code == 200
    body = response.text
    assert "Marktübersicht Marvila" in body
    assert "Marktübersicht Beato" not in body
    # Partial enthält NICHT das Layout-Root (kein <html>-Tag).
    assert "<html" not in body.lower()


def test_matrix_partial_returns_two_matrices_for_both(client, db_session):
    cfg = _seed_marvila(db_session)
    response = client.get(f"/matrix?config_id={cfg.id}&district=both")
    assert response.status_code == 200
    body = response.text
    assert "Marktübersicht Marvila" in body
    assert "Marktübersicht Beato" in body


def test_dashboard_filter_buttons_use_htmx(client, db_session):
    cfg = _seed_marvila(db_session)
    response = client.get(f"/?config_id={cfg.id}")
    body = response.text
    # Mindestens ein HTMX-Attribut auf den Filter-Buttons.
    assert "hx-get=\"/matrix?config_id=" in body
    assert "hx-target=\"#matrix-region\"" in body


def test_dashboard_has_onboarding_box(client, db_session):
    _seed_marvila(db_session)
    response = client.get("/")
    body = response.text
    assert "So liest du dieses Dashboard" in body


def test_dashboard_uses_untersuchungsbereich_label(client, db_session):
    _seed_marvila(db_session)
    response = client.get("/")
    body = response.text
    assert "Untersuchungsbereich" in body
    assert "Lissabon" in body  # city_label aus city_slug = "lisboa"


def test_dashboard_filter_has_vergleich_button(client, db_session):
    cfg = _seed_marvila(db_session)
    response = client.get(f"/?config_id={cfg.id}")
    body = response.text
    assert "Vergleich" in body
    assert "Marvila" in body and "Beato" in body


def test_dashboard_footer_shows_datenstand(client, db_session):
    _seed_marvila(db_session)
    response = client.get("/")
    body = response.text
    assert "Datenstand" in body
    assert "25 Apartments" in body or "6 Apartments" in body  # _seed_marvila legt 6 an


def test_dashboard_empty_state_shows_neuer_text(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "Noch kein Untersuchungsbereich angelegt" in response.text


def test_matrix_uses_klartext_size_labels(client, db_session):
    _seed_marvila(db_session)
    response = client.get("/")
    body = response.text
    assert "1 Schlafzimmer" in body
    assert "2 Schlafzimmer" in body
    assert "3+ Schlafzimmer" in body
    assert "Studio" in body
    assert "Apartment-Größe" in body
    assert "Preisklasse" in body


def test_matrix_cell_uses_klartext_metrics(client, db_session):
    _seed_marvila(db_session)
    response = client.get("/")
    body = response.text
    assert "Bew./Apt" in body
    assert "Wettb." in body
    assert "/N." in body


def test_matrix_thin_marker_in_klartext(client, db_session):
    _seed_marvila(db_session)
    response = client.get("/")
    body = response.text
    assert "Stichprobe klein" in body
    assert ">dünn<" not in body


def test_matrix_empty_cell_uses_em_dash(client, db_session):
    _seed_marvila(db_session)
    response = client.get("/")
    body = response.text
    assert "—" in body
    assert ">leer<" not in body


def test_top_apartments_section_renamed(client, db_session):
    _seed_marvila(db_session)
    response = client.get("/")
    body = response.text
    assert "Top-Apartments" in body
    assert "Top-Performer" not in body


def test_top_apartments_has_sort_explanation(client, db_session):
    _seed_marvila(db_session)
    response = client.get("/")
    body = response.text
    assert "Sortiert nach Bewertungen" in body
    assert "Buchungs-Indikator" in body


def test_top_apartments_use_compact_size_tags(client, db_session):
    _seed_marvila(db_session)
    response = client.get("/")
    body = response.text
    # Kompakt-Form für Top-Apartments-Tag: "1 SZ · ...", nicht "1BR · ..."
    assert "1 SZ" in body or "2 SZ" in body
    # Alter Slug-Stil darf nicht in sichtbaren Tag-Spans der Top-Apartments vorkommen.
    # "1BR · " und "2BR · " sind nur noch in title=-Tooltips der Tabelle erlaubt,
    # nicht im sichtbaren Span-Inhalt.
    import re
    # Prüfe, dass kein sichtbarer Tag-Span (ml-2 rounded … text-slate-600) den Slug enthält.
    tag_spans = re.findall(
        r'<span class="ml-2 rounded bg-slate-100[^"]*text-slate-600">(.*?)</span>',
        body,
        re.DOTALL,
    )
    for span in tag_spans:
        assert "1BR" not in span, f"Slug '1BR' in tag-span: {span!r}"
        assert "2BR" not in span, f"Slug '2BR' in tag-span: {span!r}"


def test_recommendation_block_appears_below_top_apartments(client, db_session):
    _seed_marvila(db_session)
    response = client.get("/")
    body = response.text
    top_idx = body.find("Top-Apartments")
    rec_idx = body.find("Empfehlung")
    assert top_idx > -1 and rec_idx > -1
    assert top_idx < rec_idx


def test_thin_recommendation_shows_lever_hint(client, db_session):
    _seed_marvila(db_session)  # Marvila Fixtures: 6 Apartments, alle Zellen dünn
    response = client.get("/")
    body = response.text
    assert "Empfehlung — noch nicht möglich" in body
    assert "Datenbasis ist noch zu klein" in body
    assert "Hebel:" in body
    assert "Untersuchungsbereich" in body  # auch in der Card-Überschrift, aber zusätzlich im Hebel-Text


def test_winner_recommendation_includes_proxy_disclaimer(client, db_session):
    """Wenn eine Best-Cell existiert: Empfehlungs-Block enthält den Hinweis,
    dass die Nachfragewerte ein Indikator sind. Mit dem Seed reichen die
    Marvila-Daten nicht für eine Best-Cell. Wir nehmen daher eine zweite
    SearchConfig mit min_sample=1 und prüfen den Sieger-Block.
    """
    from decimal import Decimal
    from airbi.db.models import CrawlRun, Listing, SearchConfig, Snapshot

    cfg = SearchConfig(
        name="Test-Config-min1",
        district_slugs=["marvila"],
        classification_config={"min_sample": 1},
    )
    run = CrawlRun(search_config=cfg, status="completed", listings_seen=2)
    db_session.add(run)
    db_session.flush()
    for i, (price, reviews) in enumerate([(100, 50), (110, 60)]):
        listing = Listing(
            airbnb_id=f"W{i}", city_slug="lisboa", district_slug="marvila",
            lat=38.74, lng=-9.10, property_type="Apartment", bedrooms=1,
            size_class="1BR", title=f"Winner {i}", url=f"https://x/W{i}",
        )
        db_session.add(listing)
        db_session.flush()
        db_session.add(Snapshot(
            listing_id=listing.id, crawl_run_id=run.id,
            price=Decimal(str(price)), review_count=reviews, rating=4.7,
        ))
    db_session.flush()

    response = client.get(f"/?config_id={cfg.id}&district=marvila")
    body = response.text
    assert "Empfehlung — am attraktivsten" in body
    assert "Nachfragewerte sind ein Indikator" in body
    assert "% der Gäste bewerten" in body
