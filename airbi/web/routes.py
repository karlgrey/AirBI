"""FastAPI-Router der AirBI-Web-App.

`get_session` ist die einzige DB-Dependency und wird in Tests via
`app.dependency_overrides` durch eine Test-Session ersetzt."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends
from fastapi.requests import Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from airbi.db.models import CrawlRun, SearchConfig
from airbi.db.session import SessionLocal
from airbi.insights.segment_matrix import (
    SegmentMatrix,
    compute_segment_matrix,
    latest_completed_run,
)

TEMPLATES_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

_GERMAN_MONTHS = (
    "Januar", "Februar", "März", "April", "Mai", "Juni",
    "Juli", "August", "September", "Oktober", "November", "Dezember",
)


def _format_date_de(dt: datetime | None) -> str | None:
    """Datum im deutschen Stil: '27. Mai 2026' (kein führendes Null im Tag)."""
    if dt is None:
        return None
    return f"{dt.day}. {_GERMAN_MONTHS[dt.month - 1]} {dt.year}"


router = APIRouter()


def get_session() -> Iterator[Session]:
    """DB-Session pro Request. Override in Tests über
    `app.dependency_overrides[get_session]`."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


def _resolve_search_config(
    session: Session, config_id: int | None
) -> SearchConfig | None:
    stmt = select(SearchConfig)
    if config_id is not None:
        stmt = stmt.where(SearchConfig.id == config_id)
    stmt = stmt.order_by(SearchConfig.id.asc()).limit(1)
    return session.execute(stmt).scalar_one_or_none()


def _latest_any_run(
    session: Session, search_config: SearchConfig
) -> CrawlRun | None:
    stmt = (
        select(CrawlRun)
        .where(CrawlRun.search_config_id == search_config.id)
        .order_by(CrawlRun.started_at.desc(), CrawlRun.id.desc())
        .limit(1)
    )
    return session.execute(stmt).scalar_one_or_none()


def _matrices_for(
    session: Session,
    search_config: SearchConfig,
    district_filter: str,
    crawl_run: CrawlRun,
) -> list[SegmentMatrix]:
    districts = (
        search_config.district_slugs
        if district_filter == "both"
        else [district_filter]
    )
    return [
        compute_segment_matrix(session, search_config, d, crawl_run)
        for d in districts
    ]


@router.get("/", response_class=HTMLResponse)
def dashboard(
    request: Request,
    config_id: int | None = None,
    district: str = "marvila",
    session: Session = Depends(get_session),
):
    search_config = _resolve_search_config(session, config_id)
    if search_config is None:
        return templates.TemplateResponse(
            request, "dashboard.html",
            {"search_config": None, "latest_run": None,
             "matrices": [], "active_district": district,
             "completed_run": None},
        )
    latest_run = _latest_any_run(session, search_config)
    completed_run = latest_completed_run(session, search_config)
    matrices = (
        _matrices_for(session, search_config, district, completed_run)
        if completed_run is not None else []
    )
    latest_run_date_de = _format_date_de(latest_run.started_at) if latest_run else None
    city_label = "Lissabon" if search_config.city_slug == "lisboa" else search_config.city_slug
    return templates.TemplateResponse(
        request, "dashboard.html",
        {
            "search_config": search_config,
            "latest_run": latest_run,
            "completed_run": completed_run,
            "matrices": matrices,
            "active_district": district,
            "latest_run_date_de": latest_run_date_de,
            "city_label": city_label,
        },
    )


@router.get("/matrix", response_class=HTMLResponse)
def matrix_partial(
    request: Request,
    config_id: int | None = None,
    district: str = "marvila",
    session: Session = Depends(get_session),
):
    """HTMX-Partial: nur die Matrix-Region (eine oder zwei Matrizen)."""
    search_config = _resolve_search_config(session, config_id)
    if search_config is None:
        return templates.TemplateResponse(
            request, "_matrix_region.html",
            {"matrices": [], "completed_run": None},
        )
    completed_run = latest_completed_run(session, search_config)
    matrices = (
        _matrices_for(session, search_config, district, completed_run)
        if completed_run is not None else []
    )
    return templates.TemplateResponse(
        request, "_matrix_region.html",
        {"matrices": matrices, "completed_run": completed_run},
    )
