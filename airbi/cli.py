"""airbi CLI — Einstiegspunkt für alle Befehle.

Einstiegspunkt konfiguriert in pyproject.toml:
    [project.scripts]
    airbi = "airbi.cli:main"
"""

from __future__ import annotations

import argparse
import sys


def _cmd_crawl(args: argparse.Namespace) -> int:
    """Führt einen Crawl-Lauf für eine gespeicherte SearchConfig aus."""
    from airbi.db.models import SearchConfig
    from airbi.db.session import SessionLocal
    from airbi.scraper.search_crawl import run_search_crawl

    session = SessionLocal()
    try:
        config = (
            session.query(SearchConfig).filter_by(name=args.config).one_or_none()
        )
        if config is None:
            print(
                f"Fehler: SearchConfig '{args.config}' nicht gefunden.\n"
                "Hinweis: Die SearchConfig muss zuerst in der Datenbank angelegt werden.",
                file=sys.stderr,
            )
            return 1

        crawl_run = run_search_crawl(session, config, headless=not args.headful)
        print(f"Status: {crawl_run.status}  |  listings_seen: {crawl_run.listings_seen}")
        return 0 if crawl_run.status == "completed" else 1

    finally:
        session.close()


def _cmd_web(args: argparse.Namespace) -> int:
    """Startet das FastAPI-Dashboard via uvicorn."""
    import uvicorn

    uvicorn.run(
        "airbi.web.app:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
    )
    return 0


def main(argv: list[str] | None = None) -> None:
    """Haupt-Einstiegspunkt der airbi CLI."""
    parser = argparse.ArgumentParser(
        prog="airbi",
        description="AirBI — Airbnb Marktanalyse-Tool",
    )
    subparsers = parser.add_subparsers(dest="command", metavar="BEFEHL")

    # --- crawl ---
    crawl_parser = subparsers.add_parser(
        "crawl",
        help="Crawl-Lauf für eine SearchConfig starten",
        description="Startet einen Scraper-Lauf für die angegebene SearchConfig.",
    )
    crawl_parser.add_argument(
        "--config",
        required=True,
        metavar="NAME",
        help="Name der SearchConfig, die gecrawlt werden soll",
    )
    crawl_parser.add_argument(
        "--headful",
        action="store_true",
        default=False,
        help="Browser sichtbar anzeigen (Standard: headless)",
    )

    # --- web ---
    web_parser = subparsers.add_parser(
        "web",
        help="Dashboard-Webserver starten (uvicorn)",
        description="Startet das AirBI-Dashboard auf dem angegebenen Host/Port.",
    )
    web_parser.add_argument("--host", default="127.0.0.1", help="Bind-Host (default 127.0.0.1)")
    web_parser.add_argument("--port", type=int, default=8000, help="Bind-Port (default 8000)")
    web_parser.add_argument("--reload", action="store_true", default=False,
                            help="Auto-Reload bei Code-Änderungen (Entwicklung)")

    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        sys.exit(0)

    if args.command == "crawl":
        sys.exit(_cmd_crawl(args))
    if args.command == "web":
        sys.exit(_cmd_web(args))
