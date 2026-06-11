"""Investment-Memo: komponiert Heimmarkt-Matrix + Vergleichsmarkt-Anker zu
einem erzählenden Memo (Urteil, Kapitel, Vertrauens-Stufe).

Spec: docs/superpowers/specs/2026-06-11-investment-memo-redesign-design.md.
`segment_matrix.py` bleibt der Rechen-Kern; dieses Modul erzeugt daraus
die Erzähl-Schicht."""

from __future__ import annotations

from dataclasses import dataclass, field

from airbi.insights.segment_matrix import SegmentMatrix

# Teil-3-Hook (Velocity-Modul): solange False, formuliert Kapitel 2 im
# Bestand ("hat gesammelt"); mit True wechselt es auf Buchungs-Trend.
VELOCITY_AVAILABLE = False

CONFIDENCE_BELASTBAR = "belastbar"
CONFIDENCE_SOLIDE = "solide Indizien"
CONFIDENCE_DUENN = "dünne Datenlage"

_CONFIDENCE_DOTS = {
    CONFIDENCE_BELASTBAR: 3,
    CONFIDENCE_SOLIDE: 2,
    CONFIDENCE_DUENN: 1,
}


def compute_confidence(
    *, data_age_days: int | None, n: int, min_sample: int, velocity_available: bool
) -> str:
    """Regelbasierte Vertrauens-Stufe (Spec §4)."""
    if data_age_days is None or n < min_sample:
        return CONFIDENCE_DUENN
    if velocity_available and data_age_days < 7:
        return CONFIDENCE_BELASTBAR
    if data_age_days <= 14:
        return CONFIDENCE_SOLIDE
    return CONFIDENCE_DUENN


@dataclass
class Fragment:
    """Ein Stück Kapitel-Inhalt: Fließtext oder Kennzahlen-Chip."""

    kind: str  # "text" | "chip" | "chip_muted"
    text: str


@dataclass
class AnchorStats:
    """Statistik eines benannten Vergleichsmarkts, lokal klassifiziert."""

    name: str
    radius_km: float
    listing_count: int
    segment_n: int = 0
    segment_score: float | None = None
    segment_adr: float | None = None


@dataclass
class MemoChapter:
    number: str  # "01" .. "04"
    title: str
    fragments: list[Fragment] = field(default_factory=list)

    @property
    def plain_text(self) -> str:
        """Kapitel als reiner Text — Grundlage des Jargon-Tests."""
        return " ".join(f.text for f in self.fragments)


@dataclass
class Memo:
    crawl_run_id: int | None
    home_radius_km: float
    center_label: str | None
    verdict_size_label: str | None      # "2 Schlafzimmer" — None = Memo schweigt
    verdict_luxury_class: str | None
    verdict_subline: str
    confidence: str
    confidence_dots: int                # 1..3, fürs ●●○-Rendering
    chapters: list[MemoChapter] = field(default_factory=list)
    home_matrix: SegmentMatrix | None = None
    anchors: list[AnchorStats] = field(default_factory=list)
    data_age_days: int | None = None
