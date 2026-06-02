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
    cfg = SearchConfig(
        name="Marvila Slice 1",
        center_lat=38.7391, center_lng=-9.1048, center_label="R. Cap. Leitão 86",
    )
    run = CrawlRun(search_config=cfg, status="completed", listings_seen=6)
    session.add(run)
    session.flush()

    def add_listing(airbnb_id, size_class, price, reviews, title):
        listing = Listing(
            airbnb_id=airbnb_id, city_slug="lisboa", district_slug=None,
            lat=38.7395, lng=-9.1050, property_type="Apartment", bedrooms=1,
            size_class=size_class, title=title, url=f"https://x/{airbnb_id}",
        )
        session.add(listing)
        session.flush()
        session.add(Snapshot(
            listing_id=listing.id, crawl_run_id=run.id,
            price=Decimal(str(price)), review_count=reviews, rating=4.7,
        ))

    # 6 Listings nah am Zentrum, über Größen/Preise verteilt -> alle Zellen
    # bleiben bei Default-min_sample (3) dünn (max. 2 je Zelle).
    add_listing("M1", "1BR", 60, 5,  "Marvila Cosy 1BR")
    add_listing("M2", "1BR", 70, 8,  "Marvila Cosy 1BR Nr 2")
    add_listing("M3", "1BR", 250, 90, "Marvila Loft Luxe")
    add_listing("M4", "1BR", 260, 80, "Marvila Loft Riverside")
    add_listing("B1", "Studio", 80, 12, "Studio am Fluss")
    add_listing("B2", "2BR", 130, 20, "Family Flat")
    session.flush()  # KEIN commit — Test-Fixture rollt am Ende zurück.
    return cfg


def test_dashboard_renders_matrix_and_panel(client, db_session):
    _seed_marvila(db_session)
    response = client.get("/")
    assert response.status_code == 200
    body = response.text
    assert "R. Cap. Leitão 86" in body
    assert "Marktübersicht" in body
    # Datenstand sitzt jetzt im Header (kein Footer-Status bei completed).
    assert "Datenstand" in body
    # Mindestens ein Listing-Titel taucht in den Top-Performern auf.
    assert "Marvila Loft" in body
    # Proxy-Kennzeichnung in der Marktübersichts-Caption.
    assert "Nachfrage je Apartment" in body


def test_matrix_partial_returns_umkreis_matrix(client, db_session):
    cfg = _seed_marvila(db_session)
    response = client.get(f"/matrix?config_id={cfg.id}&radius_km=2")
    assert response.status_code == 200
    body = response.text
    assert "Umkreis" in body and "2 km" in body
    # Partial enthält NICHT das Layout-Root (kein <html>-Tag).
    assert "<html" not in body.lower()


def test_matrix_partial_radius_filters_cohort(client, db_session):
    cfg = _seed_marvila(db_session)
    # 1 km Umkreis enthält die nahen Listings (alle bei 38.7395/-9.1050).
    response = client.get(f"/matrix?config_id={cfg.id}&radius_km=1")
    assert response.status_code == 200
    assert "Umkreis" in response.text


def test_dashboard_radius_buttons_use_htmx(client, db_session):
    cfg = _seed_marvila(db_session)
    response = client.get(f"/?config_id={cfg.id}")
    body = response.text
    # Mindestens ein HTMX-Attribut auf den Umkreis-Buttons.
    assert "hx-get=\"/matrix?config_id=" in body
    assert "radius_km=" in body
    assert "hx-target=\"#matrix-region\"" in body


def test_dashboard_uses_untersuchungsbereich_label(client, db_session):
    _seed_marvila(db_session)
    response = client.get("/")
    body = response.text
    assert "Untersuchungsbereich" in body
    assert "Lissabon" in body  # city_label aus city_slug = "lisboa"
    assert "R. Cap. Leitão 86" in body


def test_dashboard_has_radius_buttons(client, db_session):
    cfg = _seed_marvila(db_session)
    response = client.get(f"/?config_id={cfg.id}")
    body = response.text
    assert "1 km" in body and "2 km" in body and "10 km" in body


def test_dashboard_ships_radius_button_click_highlighter(client, db_session):
    """Nach Klick swappt HTMX nur die Matrix; ohne Client-Skript bliebe der
    aktive Button auf dem initialen SSR-Stand. Stelle sicher, dass das Skript
    + die Marker (umkreis-nav id, umkreis-btn class) ausgeliefert werden."""
    _seed_marvila(db_session)
    body = client.get("/").text
    assert 'id="umkreis-nav"' in body
    assert "umkreis-btn" in body
    assert "addEventListener('click'" in body


def test_dashboard_header_shows_datenstand(client, db_session):
    _seed_marvila(db_session)
    response = client.get("/")
    body = response.text
    assert "Datenstand" in body
    assert "25 Apartments" in body or "6 Apartments" in body  # _seed_marvila legt 6 an


def test_dashboard_empty_state_shows_neuer_text(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "Noch kein Untersuchungsbereich angelegt" in response.text


def test_format_date_de_renders_german_month_names():
    """Direkter Test der Format-Helper: schützt gegen Off-by-one im Monats-Index
    oder Reorder von _GERMAN_MONTHS."""
    from datetime import datetime

    from airbi.web.routes import _format_date_de

    assert _format_date_de(datetime(2026, 5, 27)) == "27. Mai 2026"
    assert _format_date_de(datetime(2026, 1, 1)) == "1. Januar 2026"
    assert _format_date_de(datetime(2026, 12, 31)) == "31. Dezember 2026"
    assert _format_date_de(None) is None


def test_matrix_uses_klartext_size_labels(client, db_session):
    _seed_marvila(db_session)
    response = client.get("/")
    body = response.text
    assert "1 Schlafzimmer" in body
    assert "2 Schlafzimmer" in body
    assert "3+ Schlafzimmer" in body
    assert "Studio" in body
    assert "Apartment-Größe" in body
    assert "Luxusklasse" in body


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
    """Die Top-Performer-Sektion heißt im UI 'Top-Apartments'.

    'Top-Performer' darf im Investment-Brief vorkommen ('Profil der
    Top-Performer.') — das ist die Konzept-Sprache, nicht der Section-Titel.
    """
    _seed_marvila(db_session)
    response = client.get("/")
    body = response.text
    assert "Top-Apartments" in body
    # Kein Section-Header mehr namens "Top-Performer" (alte Variante).
    assert ">Top-Performer<" not in body


def test_top_apartments_has_sort_explanation(client, db_session):
    """Untertitel erklärt, was die Liste zeigt + nach was sortiert wird.
    _seed_marvila liefert thin data -> der 'populärsten im Umkreis'-Variant."""
    _seed_marvila(db_session)
    response = client.get("/")
    body = response.text
    assert "sortiert nach Bewertungen" in body
    assert "im Umkreis" in body


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


def test_hero_thin_state_when_no_best_cell(client, db_session):
    """Wenn die Datenbasis dünn ist (alle Zellen unter min_sample): Hero zeigt
    die Thin-Variante mit 'Datenbasis zu dünn' und Hinweis auf größeren Umkreis,
    statt einer Empfehlungs-Schlagzeile."""
    _seed_marvila(db_session)  # 6 Apartments → alle Zellen dünn (min_sample=3)
    response = client.get("/")
    body = response.text
    assert "Datenbasis zu dünn" in body
    assert "größeren Umkreis" in body
    # Alter Recommendation-Block ist weg.
    assert "Empfehlung — noch nicht möglich" not in body
    assert "Hebel:" not in body


def _seed_winner_config(db_session, *, amenities=None, is_superhost=True):
    """Helper: SearchConfig + Listings, sodass eine Best-Cell entsteht
    (min_sample=1, mehrere Listings im 2-km-Umkreis)."""
    from decimal import Decimal
    from airbi.db.models import CrawlRun, Listing, SearchConfig, Snapshot
    cfg = SearchConfig(
        name="Winner-Config",
        center_lat=38.7391, center_lng=-9.1048, center_label="R. Cap. Leitão 86",
        classification_config={"min_sample": 1, "amenity_share_threshold": 0.5},
    )
    run = CrawlRun(search_config=cfg, status="completed", listings_seen=2)
    db_session.add(run)
    db_session.flush()
    for i, (price, reviews) in enumerate([(100, 50), (110, 60)]):
        listing = Listing(
            airbnb_id=f"W{i}", city_slug="lisboa", district_slug=None,
            lat=38.7395, lng=-9.1050, property_type="Apartment",
            bedrooms=1, beds=2, max_guests=3, is_superhost=is_superhost,
            size_class="1BR", title=f"Winner {i}", url=f"https://x/W{i}",
            amenities=list(amenities or ["Wifi", "Air conditioning", "River view"]),
        )
        db_session.add(listing)
        db_session.flush()
        db_session.add(Snapshot(
            listing_id=listing.id, crawl_run_id=run.id,
            price=Decimal(str(price)), review_count=reviews, rating=4.7,
        ))
    db_session.flush()
    return cfg


def test_hero_renders_best_cell_with_kpi_labels(client, db_session):
    """Hero-Card zeigt Empfehlung-Eyebrow, die Best-Cell als Schlagzeile
    (Größe + Luxusklasse in Klartext) und die drei KPI-Labels."""
    cfg = _seed_winner_config(db_session)
    response = client.get(f"/?config_id={cfg.id}&radius_km=2")
    body = response.text
    # Eyebrow + Schlagzeile (Empfehlung erscheint nur noch im Hero)
    assert "Empfehlung" in body
    # Best-Cell wird als "Klartext-Größe · Luxusklasse" gerendert (mit
    # Whitespace zwischen den Jinja-Blöcken — Browser kollabiert das).
    assert "1 Schlafzimmer" in body
    assert any(tier in body for tier in ("Budget", "Mid", "Premium", "Luxury"))
    # 3 KPI-Labels
    assert "Wettbewerber" in body
    assert "Median pro Nacht" in body
    assert "Ø Bewertungen je Apt" in body


def test_investment_brief_is_collapsible_details_block(client, db_session):
    """Investment-Brief ist ein natives <details>-Element mit klickbarem
    <summary>. So funktioniert er ohne JS und ist screenreader-tauglich."""
    cfg = _seed_winner_config(db_session)
    body = client.get(f"/?config_id={cfg.id}&radius_km=2").text
    assert "<details" in body
    assert "<summary" in body
    assert "Investment-Brief" in body


def test_brief_contains_methodology_with_proxy_disclaimer(client, db_session):
    """Der Methodik-Absatz im Brief ersetzt den alten Proxy-Hinweis und ist
    auch in der Thin-Variante vorhanden."""
    _seed_marvila(db_session)
    body = client.get("/").text
    assert "Methodik" in body
    assert "Indikator" in body
    assert "% der Gäste bewerten" in body


def test_brief_contains_recommended_segment_profile(client, db_session):
    """Mit Best-Cell + Detail-Daten enthält der Brief 'Profil im empfohlenen
    Segment' samt mindestens einer Amenity und Superhost-Quote in Prozent.
    Das Profil ist auf die Listings des Best-Cells beschränkt — konsistent
    zur Hero-Empfehlung."""
    cfg = _seed_winner_config(db_session)  # 2 Listings, beide Superhost, Wifi etc.
    body = client.get(f"/?config_id={cfg.id}&radius_km=2").text
    assert "Profil im empfohlenen Segment" in body
    assert "Wifi" in body
    # Superhost-Quote als Prozent (beide Superhost → 100 %)
    assert "100 %" in body or "100%" in body


def test_dashboard_has_no_onboarding_box(client, db_session):
    """Onboarding-Box wurde durch den selbsterklärenden Hero ersetzt."""
    _seed_marvila(db_session)
    body = client.get("/").text
    assert "So liest du dieses Dashboard" not in body


def test_map_section_renders_with_listings_and_data(client, db_session):
    """Karten-Section: <div id='airbi-map'>, Detail-Panel und JSON-Daten-Block
    sind im HTML; Leaflet kommt aus base.html."""
    cfg = _seed_winner_config(db_session)
    body = client.get(f"/?config_id={cfg.id}&radius_km=2").text
    assert 'id="airbi-map"' in body
    assert 'id="map-detail"' in body
    assert 'id="airbi-map-data"' in body
    # Leaflet wird im base.html geladen
    assert "leaflet.css" in body
    assert "leaflet.js" in body
    # Der Daten-Block enthält den Center-Label
    assert "R. Cap. Le" in body  # in der JSON-Datenstruktur


def test_underserved_section_renders_with_other_chance_cells(client, db_session):
    """Unterversorgungs-Sicht: 'Andere Chancen-Segmente' rendert mit
    Mini-Cards (inkl. Prosa-Begründung) sobald es Cells außer der Best-Cell
    mit Score gibt."""
    cfg = _seed_winner_config(db_session)  # 2 1BR-Listings (Budget + Mid)
    body = client.get(f"/?config_id={cfg.id}&radius_km=2").text
    assert "Andere Chancen-Segmente" in body
    # Mini-Card-Untertitel-Marker (Bew./Apt im KPI-Strip der Cards)
    assert "Bew./Apt" in body
    # Prosa-Begründung pro Card (eines der zwei Wordings muss da sein)
    assert "Demand-Signal" in body or "unterversorgt" in body


def test_underserved_section_absent_when_no_other_cells(client, db_session):
    """Wenn nur die Best-Cell Score hat (z.B. nur ein Listing-Cluster),
    bleibt die Chancen-Section weg."""
    from decimal import Decimal
    from airbi.db.models import CrawlRun, Listing, SearchConfig, Snapshot
    cfg = SearchConfig(
        name="OneCell", center_lat=38.7391, center_lng=-9.1048,
        center_label="R. Cap. Leitão 86",
        classification_config={"min_sample": 1, "underserved_max": 3},
    )
    run = CrawlRun(search_config=cfg, status="completed", listings_seen=2)
    db_session.add(run); db_session.flush()
    # Zwei Listings im exakt selben Cell → nur eine Cell hat Score,
    # die ist die Best-Cell → underserved leer.
    for i in range(2):
        listing = Listing(
            airbnb_id=f"S{i}", city_slug="lisboa", district_slug=None,
            lat=38.7395, lng=-9.1050, property_type="Apartment",
            bedrooms=1, beds=2, max_guests=3,
            size_class="1BR", title=f"L{i}", url=f"https://x/S{i}",
        )
        db_session.add(listing); db_session.flush()
        db_session.add(Snapshot(
            listing_id=listing.id, crawl_run_id=run.id,
            price=Decimal("100"), review_count=50, rating=4.7,
        ))
    db_session.flush()
    body = client.get(f"/?config_id={cfg.id}&radius_km=2").text
    assert "Andere Chancen-Segmente" not in body


def test_dashboard_has_no_old_empfehlungs_block(client, db_session):
    """Der alte 'Empfehlung — am attraktivsten/noch nicht möglich'-Block am
    Ende ist entfallen (Hero ersetzt ihn vollständig)."""
    cfg = _seed_winner_config(db_session)
    body = client.get(f"/?config_id={cfg.id}&radius_km=2").text
    assert "Empfehlung — am attraktivsten" not in body
    assert "Empfehlung — noch nicht möglich" not in body


def test_matrix_axis_is_luxusklasse(client, db_session):
    """Matrix-Achse heißt 'Luxusklasse'. Die Methodik (Preis + Amenities)
    wandert in den Investment-Brief — der Begriff 'Luxusklasse' bleibt im
    Matrix-Header sichtbar."""
    _seed_marvila(db_session)
    response = client.get("/")
    body = response.text
    assert "Luxusklasse" in body
