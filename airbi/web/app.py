"""FastAPI-App-Factory + Modul-Level `app` für Uvicorn-Imports.

CLI/Uvicorn nutzen den String "airbi.web.app:app" als Einstiegspunkt; Tests
nutzen `create_app()` direkt, um die DB-Dependency zu überschreiben."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from airbi.web.routes import router

WEB_DIR = Path(__file__).parent
STATIC_DIR = WEB_DIR / "static"


def create_app() -> FastAPI:
    app = FastAPI(title="AirBI Dashboard", version="0.1.0")
    STATIC_DIR.mkdir(parents=True, exist_ok=True)
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
    app.include_router(router)
    return app


app = create_app()
