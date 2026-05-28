# AirBI — VPS-Deployment (Dashboard live) — Design / Spec

> **Status:** Design abgestimmt, bereit für Implementierungsplanung
> **Datum:** 2026-05-28
> **Grundlage:** Briefing §10 (Deployment), Slice-1-Spec §11 (Vertiefungsrunde #5)
> **Auftraggeber:** Michael Alber (Remote Republic Labs)
> **Ziel-Host:** `deploy@labs.remoterepublic.com` (Ubuntu 24.04, geteilt mit anderen Apps)

---

## 1. Einordnung

Erste Runde der „Vertiefungsrunde #5" (Deployment & Betrieb), bewusst **eng geschnitten**: Nur das **Dashboard live bringen** auf `airbi.remoterepublic.com`. Web-App + PostgreSQL laufen auf dem VPS hinter dem dort bereits aktiven Caddy. Betriebs-Härtung (APScheduler-Auto-Crawl, Backup, Monitoring) bleibt für eine spätere Runde.

Der Host ist **geteilt** mit anderen Apps (guesty-calendar-app, str, labs-api, billbee-api-client, suno-prompt-generator, tailscale-server — alle Node/PM2). AirBI ist die erste Python-App und die erste, die PostgreSQL braucht.

## 2. Ziel / Zielzustand

`https://airbi.remoterepublic.com` liefert das Dashboard mit den echten Marvila/Beato-Daten (25 Apartments, Stand des letzten lokalen Crawls). Die Web-App startet automatisch beim Boot und nach Crash. TLS via Let's Encrypt (Caddy automatisch).

## 3. Recon-Befund (Host-Landschaft, Stand 2026-05-28)

| Aspekt | Stand |
|---|---|
| OS / HW | Ubuntu 24.04.3 LTS, x86_64, 4 vCPU, 7.7 GB RAM, 218 GB frei |
| Zugang | `deploy@labs.remoterepublic.com`, SSH-Key auf Dev-Mac, **passwortloses sudo** |
| PostgreSQL | **nicht installiert** (kein Paket, kein Data-Dir, Service inaktiv) |
| Reverse-Proxy | **Caddy aktiv** (`/etc/caddy/Caddyfile`, root-owned, Per-Domain-Blöcke, Admin-API auf 127.0.0.1:2019), Ports 80/443 |
| Prozess-Mgmt Bestand | PM2 (Node-Apps auf 3005/3006/3007/3010) |
| Freie Ports | 8000, 8001, 8002 frei |
| Python | 3.12.3 (System), **kein `uv`** im deploy-PATH |
| git | 2.43.0 vorhanden |
| Docker | nicht vorhanden |
| DNS | `airbi.remoterepublic.com` bereits angelegt (zeigt auf den Host) |

## 4. Getroffene Entscheidungen (Decision Log)

| Entscheidung | Wahl | Begründung |
|---|---|---|
| Scope | Nur Dashboard-Live (Web + DB + Caddy + Daten) | „Das Ding live sehen"; Betriebs-Härtung separat |
| Prozess-Manager | **systemd** (`airbi-web.service`) | Briefing §10 nennt systemd; Python+PM2 wäre unsauber; klare Trennung von den Node-Apps |
| Code-Delivery | **git clone + Read-only-Deploy-Key** | Reproduzierbar, künftige Updates per `git pull`; git ist auf dem Server vorhanden |
| Prod-Daten | **pg_dump (lokal) → Restore (Prod)** | 25 Apartments sofort sichtbar; überzeugender als Empty-State |
| Web-Port | uvicorn auf **127.0.0.1:8000** | Frei; nur lokal gebunden, Caddy fronted |
| Paket-Manager | **uv** (für deploy-User installieren) | Konsistent mit Dev; reproduzierbare Locks |
| TLS | Caddy-Auto (Let's Encrypt) | Bereits etabliertes Muster auf dem Host |

## 5. Architektur (5 Komponenten)

1. **Code** in `/opt/airbi` (Konvention). `git clone` via Deploy-Key, Branch `main`.
2. **PostgreSQL** via `apt install postgresql`. Lokaler Unix-Socket + `127.0.0.1:5432`. Rolle `airbi` mit Passwort, DB `airbi` (owner `airbi`). Alembic-Migrationen auf `head`.
3. **uv + Dependencies**: uv für deploy-User installieren (`curl -LsSf https://astral.sh/uv/install.sh | sh`), `uv sync --no-dev` in `/opt/airbi` (Playwright-Browser-Download NICHT nötig — der Crawl läuft nicht auf dem Server; nur die Web-Dependencies).
4. **systemd-Unit** `/etc/systemd/system/airbi-web.service`:
   - `ExecStart=/home/deploy/.local/bin/uv run airbi web --host 127.0.0.1 --port 8000`
   - `WorkingDirectory=/opt/airbi`, `User=deploy`
   - `EnvironmentFile=/opt/airbi/.env` mit `DATABASE_URL=postgresql+psycopg://airbi:<pw>@localhost:5432/airbi` (Env-Name verifiziert: `config.py`-Feld `database_url`, kein Prefix → `DATABASE_URL`)
   - `Restart=always`, `RestartSec=3`, `WantedBy=multi-user.target`
5. **Caddy-Vhost** (Block an `/etc/caddy/Caddyfile` anhängen):
   ```
   airbi.remoterepublic.com {
       reverse_proxy localhost:8000 {
           health_uri /health
           health_interval 10s
           health_timeout 5s
       }
       header {
           Strict-Transport-Security "max-age=31536000; includeSubDomains; preload"
           X-Content-Type-Options "nosniff"
           Referrer-Policy "strict-origin-when-cross-origin"
       }
   }
   ```
   `caddy validate` vor `systemctl reload caddy`.

## 6. Code-Delivery (git clone + Deploy-Key)

1. Auf dem Server ein dediziertes SSH-Keypair erzeugen (`ssh-keygen -t ed25519 -f ~/.ssh/airbi_deploy -N ""`, kommentiert).
2. **User-Schritt:** Public Key als **Read-only Deploy-Key** im GitHub-Repo `karlgrey/AirBI` hinterlegen (Settings → Deploy keys → Add). *Dieser Schritt ist nicht von Claude ausführbar — der Plan pausiert hier für Michael.*
3. SSH-Config-Eintrag (`~/.ssh/config`) für `github-airbi`, dann `git clone git@github-airbi:karlgrey/AirBI.git /opt/airbi`.
4. Updates künftig: `cd /opt/airbi && git pull && uv sync --no-dev && (alembic upgrade head) && sudo systemctl restart airbi-web`.

## 7. Konfiguration / Secrets

- `airbi/config.py` nutzt `pydantic-settings` mit `.env`-Support. Der DB-Env-Name ist **verifiziert** `DATABASE_URL` (Feld `database_url`, kein `env_prefix`; pydantic-settings ist case-insensitiv). Die Prod-DB-URL wird **nicht** committet, sondern in `/opt/airbi/.env` (`chmod 600`, deploy-owned, durch `.gitignore` abgedeckt) gelegt und per systemd `EnvironmentFile=` geladen. `config.py` liest `.env` ohnehin selbst — die `EnvironmentFile`-Direktive ist Redundanz/Klarheit; eine der beiden Quellen genügt, der Plan wählt eine.
- DB-Passwort: stark generiert, nur in der `.env`/systemd-Umgebung.

## 8. Daten-Migration (einmalig)

1. Lokal: `pg_dump` der `airbi`-DB (nur Daten + Schema, oder `--data-only` nach Alembic-Migration auf Prod).
2. Transfer per SSH-Pipe oder scp.
3. Restore in die Prod-`airbi`-DB.
4. Verifikation: Listing/Snapshot/CrawlRun-Counts auf Prod == lokal (25 Apartments, 1 completed CrawlRun).

Reihenfolge-Entscheidung im Plan: erst Alembic-Schema auf Prod, dann `--data-only`-Restore (sauberste Variante, vermeidet Schema-Drift).

## 9. Sicherheits-Leitplanken (geteilter Host!)

- **Nur AirBI-eigene Artefakte anfassen:** `/opt/airbi`, `airbi-web.service`, der AirBI-Caddy-Block, die `airbi`-Rolle/DB. Andere Apps und deren Daten (`/opt/guesty-*`, `/opt/str`, `/opt/labs-api`, …) **niemals** berühren.
- **PostgreSQL-Installation** ist systemweit. Vor `apt install`: Checkpoint. Keine andere App nutzt Postgres (Recon bestätigt), Risiko gering, aber Eingriff bewusst bestätigen lassen.
- **Caddyfile**: vorher kopieren (`/etc/caddy/Caddyfile.bak-airbi-<datum>`), nur den AirBI-Block **anhängen**, `caddy validate` vor `reload`. Niemals bestehende Blöcke ändern.
- **Jeder schreibende/installierende Schritt** mit Ansage. Risikoreiche (apt install, Caddy-reload, DB-Restore) zusätzlich mit expliziter Bestätigung.
- **Kein Force, keine destruktiven Operationen** an existierenden Services/Dateien.

## 10. Acceptance-Kriterien

1. `systemctl status airbi-web` → `active (running)`, übersteht `systemctl restart` und einen simulierten Crash.
2. `curl -s localhost:8000/health` auf dem Server → `{"status":"ok"}`.
3. `https://airbi.remoterepublic.com/` → 200, Dashboard mit gültigem TLS-Zertifikat.
4. Dashboard zeigt die Marvila-Marktübersicht mit den 25 Apartments (nicht Empty-State).
5. Caddy-Reload hat **keine** andere Domain beeinträchtigt (Stichprobe: eine Bestands-Domain antwortet weiterhin).
6. `git pull`-Update-Pfad dokumentiert und einmal trocken verifiziert (`git pull` ohne Änderungen läuft sauber).

## 11. Out of Scope (bewusst NICHT in dieser Runde)

- APScheduler-Auto-Crawl auf dem Server.
- Backup-Konzept / pg_dump-Cron.
- Monitoring/Alerting (Block-Erkennung, Datenqualität).
- Residential-Proxy + Crawl-Topologie auf dem Server (Crawl bleibt auf dem Dev-Rechner; Prod-Daten kommen via Dump/Restore bzw. später SSH-Tunnel).
- Playwright-Browser auf dem Server (nur Web-Dependencies installiert).
- CI/CD-Pipeline (Updates manuell per `git pull`).
- Staging-Umgebung.

---

*Diese Runde bringt das Dashboard mit echten Daten unter die richtige Domain — minimal-invasiv auf einem geteilten Host. Betriebs-Härtung folgt, wenn das Live-Dashboard sich bewährt.*
