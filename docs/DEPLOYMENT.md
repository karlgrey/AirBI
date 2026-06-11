# AirBI — Deployment (Production)

> Live: **https://airbi.remoterepublic.com**
> Erste Ausrollung: 2026-05-28 (Spec: `docs/superpowers/specs/2026-05-28-deployment-vps-design.md`)

## Host & Topologie

| | |
|---|---|
| Host | `deploy@labs.remoterepublic.com` (Ubuntu 24.04, geteilt mit anderen Apps) |
| Code | `/opt/airbi` (git-clone via Read-only-Deploy-Key, Branch `main`) |
| Service | systemd-Unit `airbi-web` → uvicorn auf `127.0.0.1:8000` |
| Reverse-Proxy | Caddy (`/etc/caddy/Caddyfile`, Block `airbi.remoterepublic.com`), Auto-TLS via Let's Encrypt, **HTTP Basic Auth** (user `airbi`) |
| Datenbank | PostgreSQL (lokal), Rolle + DB `airbi` |
| Secret | `/opt/airbi/.env` (`DATABASE_URL`, `chmod 600`, deploy-owned, gitignored) |
| Paket-Manager | `uv` (`~/.local/bin/uv`), venv unter `/opt/airbi/.venv` |

## Komponenten im Detail

- **systemd:** `/etc/systemd/system/airbi-web.service` — `Restart=always`, lädt `EnvironmentFile=/opt/airbi/.env`, `ExecStart=/home/deploy/.local/bin/uv run --no-dev airbi web --host 127.0.0.1 --port 8000`.
- **Caddy-Block:** reverse_proxy → `localhost:8000`, Healthcheck auf `/health`, HSTS-/Security-Header. HTTP→HTTPS-Redirect automatisch.
- **Basic Auth:** `basic_auth`-Direktive im AirBI-Block schützt das Dashboard (niedrigschwellig, nur gegen Crawler/Neugierige). User `airbi`, Passwort als bcrypt-Hash in der Caddyfile (Klartext bewusst **nicht** im Repo). Caddys aktiver Healthcheck geht direkt zum Backend und ist von der Auth unberührt.
  - **Passwort ändern:** `caddy hash-password --plaintext 'NEU'` → den Hash in der `basic_auth { airbi <hash> }`-Zeile ersetzen → `sudo caddy validate --config /etc/caddy/Caddyfile && sudo systemctl reload caddy`.
- **DB:** Schema via Alembic (`alembic upgrade head`). Daten initial per `pg_dump --data-only` vom Dev-Rechner eingespielt.
- **Suchgebiet/Auswertung:** Distanzbasierte Umkreis-Bänder um das Zielobjekt (kein Bezirks-Modell mehr). Die `search_config` braucht `center_lat`/`center_lng`/`center_label` + `band_radii_km` — nach der Migration `b2c3d4e5f6a7` einmalig setzen (siehe „Daten aktualisieren"). Die Auswertung filtert pro Umkreis zur Query-Zeit (Dashboard-Schalter 1/2/3/5/10 km); Re-Crawl zum Umschalten nicht nötig.

## Update-Pfad (neue Version ausrollen)

```bash
ssh deploy@labs.remoterepublic.com
cd /opt/airbi
git pull --ff-only
~/.local/bin/uv sync --no-dev
~/.local/bin/uv run alembic upgrade head      # nur falls neue Migrationen
sudo systemctl restart airbi-web               # IMMER, auch bei template-only-Änderungen
curl -s localhost:8000/health                  # {"status":"ok"} erwarten
```

## Betrieb

- **Status:** `systemctl status airbi-web`
- **Logs:** `journalctl -u airbi-web -f`
- **Caddy-Reload (nach Caddyfile-Änderung):** `sudo caddy validate --config /etc/caddy/Caddyfile && sudo systemctl reload caddy`
- **Caddyfile-Backups:** `/etc/caddy/Caddyfile.bak-airbi-<timestamp>`

## Daten aktualisieren

### Automatisch (Daten-Uhr, Standard-Pfad seit 2026-06-11)

Ein launchd-LaunchAgent auf dem Dev-Mac crawlt **Mo + Do 07:00** und synct
bei Erfolg automatisch zum VPS (Dump → scp → TRUNCATE+Restore). Manuelles
Crawlen + Dump/Restore (unten) bleibt als Fallback.

- Skript: `scripts/scheduled_crawl.sh` (Log: `~/Library/Logs/airbi/crawl-<stamp>.log`)
- plist-Template: `scripts/com.airbi.crawl.plist`
- Installation:
  `cp scripts/com.airbi.crawl.plist ~/Library/LaunchAgents/ && launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.airbi.crawl.plist`
- Sofort-Lauf zum Testen: `launchctl kickstart gui/$(id -u)/com.airbi.crawl`
- Deinstallation: `launchctl bootout gui/$(id -u)/com.airbi.crawl`
- Fehler melden sich als macOS-Benachrichtigung („AirBI Daten-Uhr"); ein
  abgebrochener Crawl wird vom nächsten Lauf automatisch resumiert.

**Einmalig nach Migration `b2c3d4e5f6a7`** — Umkreis-Felder der Config setzen:
```sql
UPDATE search_config SET center_lat=38.7391, center_lng=-9.1048,
  center_label='R. Cap. Leitão 86', band_radii_km='[1, 2, 3, 5, 10]'
WHERE name='Marvila Slice 1';
```

Der Crawl läuft **nicht** auf dem Server (braucht Residential-IP). Neue Daten kommen per Dump/Restore vom Dev-Rechner.

**Befehle auf dem Dev-Rechner:**

- `uv run airbi crawl --config "Marvila Slice 1" --verbose` — voller Lauf (5 konzentrische Boxen + Detail-Crawl). **Resilient**: Auto-Resume eines `running`-CrawlRuns, per-Box-Commit in der Such-Phase, Detail-Phase delegiert an refresh-details. Ein Abbruch verliert max. eine Box + ein Detail-Listing. Mit `PYTHONUNBUFFERED=1 caffeinate -d -i -s --` umgeben empfohlen.
- `uv run airbi refresh-details --config "Marvila Slice 1" --verbose` — **resilient**: re-crawlt nur die Detail-Seiten aller Listings des letzten completed Runs. Per-Listing-Commit, resumierbar (skipped Listings mit `bedrooms IS NOT NULL`), Browser-Neustart alle 50. Sinnvoll nach einer Parser-Änderung, ohne neue Such-Phase.

**Dump/Restore-Pfad:**



```bash
# lokal
PGPASSWORD=airbi pg_dump --data-only --no-owner --no-privileges -h localhost -U airbi -d airbi \
  -t search_config -t crawl_run -t listing -t snapshot -f /tmp/airbi-data.sql
scp /tmp/airbi-data.sql deploy@labs.remoterepublic.com:/tmp/
# auf dem Server (Prod-DB ggf. vorher leeren, je nach Strategie)
ssh deploy@labs.remoterepublic.com 'cd /opt/airbi && set -a; . .env; set +a; \
  PGPASSWORD=$(echo "$DATABASE_URL" | sed -E "s|.*://airbi:([^@]+)@.*|\1|") \
  psql -h localhost -U airbi -d airbi -f /tmp/airbi-data.sql; rm -f /tmp/airbi-data.sql'
```

## Rollback

- App stoppen: `sudo systemctl stop airbi-web` (andere Apps unberührt).
- Caddy-Block zurück: Backup zurückspielen, `caddy validate`, `systemctl reload caddy`.
- DB zurücksetzen: `sudo -u postgres dropdb airbi` + neu anlegen (betrifft keine andere App).

## Bewusst (noch) NICHT auf dem Server

- Backup-Cron, Monitoring/Alerting. (Auto-Crawl läuft seit 2026-06-11 als launchd-Job auf dem Dev-Mac — bewusst kein APScheduler im Server-Prozess.)
- Residential-Proxy + Crawl-Topologie (Crawl bleibt Dev-Rechner).
- Playwright-Browser-Binaries (Server crawlt nicht).
- CI/CD, Staging.
