"""Review-Velocity (Teilprojekt 3, Spec-Nachtrag 2026-07-30).

Der Review-Count-Proxy (Kapitel 2 des Memos) misst bislang nur den
**Bestand** ("hat je Apartment die meisten Bewertungen gesammelt") — das
eigentliche Nachfrage-Maß laut Briefing §3 ist die **Velocity**: wie schnell
wächst die Bewertungsanzahl zwischen Snapshots ("wird aktuell am stärksten
gebucht"). Der Hook dafür (`VELOCITY_AVAILABLE`) existiert seit dem
Memo-Redesign (2026-06-11) in `airbi.insights.memo`; dieses Modul liefert
die tatsächliche Berechnung.

Drei Schichten wie in `segment_matrix.py`:
- reiner Kern: `compute_weekly_velocity` (keine DB).
- DB-Anbindung: `compute_velocities` (lädt Snapshot-Historie).
- Verdrahtung: `attach_velocities` (setzt `ListingRow.weekly_velocity`).
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.orm import Session

from airbi.db.models import Snapshot

if TYPE_CHECKING:
    from airbi.insights.segment_matrix import ListingRow

# Mindest-Spanne zwischen erstem und letztem Snapshot, ab der eine Velocity
# als belastbar gilt (Wiki-Referenz 13.07.2026: "571 Listings >=21 Tage
# Spanne" war der Datenreife-Meilenstein fuer dieses Modul).
MIN_SPAN_DAYS = 21


def compute_weekly_velocity(
    snapshots: list[tuple[datetime, int]], *, min_span_days: int = MIN_SPAN_DAYS
) -> float | None:
    """Reviews/Woche aus erstem und letztem Snapshot eines Listings.

    `snapshots`: Liste aus (captured_at, review_count), Reihenfolge egal.
    None, wenn weniger als zwei Snapshots vorliegen oder die Spanne unter
    `min_span_days` liegt. Ein negatives Delta (Parser-Rauschen, seltener
    Review-Count-Rückgang) wird auf 0.0 geklippt — es gibt keine negative
    Nachfrage.
    """
    if len(snapshots) < 2:
        return None
    ordered = sorted(snapshots, key=lambda s: s[0])
    first_at, first_count = ordered[0]
    last_at, last_count = ordered[-1]
    span_days = (last_at - first_at).days
    if span_days < min_span_days:
        return None
    delta = max(0, last_count - first_count)
    return round(delta / span_days * 7, 3)


def compute_velocities(
    session: Session, listing_ids: list[int], *, min_span_days: int = MIN_SPAN_DAYS
) -> dict[int, float]:
    """Weekly Velocity je Listing-ID, über die GESAMTE Snapshot-Historie
    (alle CrawlRuns) — nicht nur den aktuellen Run, die Zeitreihe ist der
    Punkt. Listings ohne belastbares Signal fehlen im Ergebnis-Dict."""
    if not listing_ids:
        return {}
    stmt = (
        select(Snapshot.listing_id, Snapshot.captured_at, Snapshot.review_count)
        .where(Snapshot.listing_id.in_(listing_ids))
        .order_by(Snapshot.listing_id, Snapshot.captured_at)
    )
    by_listing: dict[int, list[tuple[datetime, int]]] = {}
    for listing_id, captured_at, review_count in session.execute(stmt).all():
        by_listing.setdefault(listing_id, []).append((captured_at, review_count or 0))

    result: dict[int, float] = {}
    for listing_id, snaps in by_listing.items():
        velocity = compute_weekly_velocity(snaps, min_span_days=min_span_days)
        if velocity is not None:
            result[listing_id] = velocity
    return result


def attach_velocities(
    session: Session,
    rows: list["ListingRow"],
    *,
    min_span_days: int = MIN_SPAN_DAYS,
) -> None:
    """Setzt `row.weekly_velocity` in-place für alle Rows mit `listing_id`.
    Rows ohne `listing_id` (z.B. reine Fixture-Daten) bleiben unangetastet."""
    listing_ids = {r.listing_id for r in rows if r.listing_id is not None}
    if not listing_ids:
        return
    velocities = compute_velocities(session, list(listing_ids), min_span_days=min_span_days)
    for row in rows:
        if row.listing_id is not None and row.listing_id in velocities:
            row.weekly_velocity = velocities[row.listing_id]
