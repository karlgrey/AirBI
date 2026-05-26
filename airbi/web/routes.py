"""FastAPI-Router der AirBI-Web-App.

`get_session` ist die einzige DB-Dependency und wird in Tests via
`app.dependency_overrides` durch eine Test-Session ersetzt."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from fastapi import APIRouter, Depends
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from airbi.db.session import SessionLocal

TEMPLATES_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

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
