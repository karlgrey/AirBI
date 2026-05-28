# VPS-Deployment (Dashboard live) Implementation Plan

> **For agentic workers:** Dies ist ein **operativer Deployment-Plan** auf einem **geteilten Live-Host** — kein TDD-Code-Plan. Jeder Schritt ist ein exakter Befehl mit erwarteter Ausgabe + Verifikation. Schritte mit **⚠ CHECKPOINT** erfordern explizite Nutzer-Bestätigung VOR Ausführung. Schritte mit **⏸ PAUSE (User)** kann Claude nicht selbst ausführen — der Plan hält an, bis der Nutzer fertig ist. Empfohlene Ausführung: **executing-plans (inline, mit Checkpoints)**, NICHT subagent-driven (Live-Server, kein Dispatch destruktiver SSH-Befehle).

**Goal:** Das AirBI-Dashboard mit echten Marvila/Beato-Daten live unter `https://airbi.remoterepublic.com` bringen — Web-App + PostgreSQL auf dem VPS, hinter dem dort aktiven Caddy, als systemd-Unit.

**Architecture:** Code via git-clone (Read-only-Deploy-Key) nach `/opt/airbi`. PostgreSQL frisch via apt. `uv` für den deploy-User. systemd-Unit `airbi-web` bindet uvicorn auf `127.0.0.1:8000`. Caddy-Vhost reverse-proxyt `airbi.remoterepublic.com` dorthin (Auto-TLS). Daten einmalig per `pg_dump`/restore von lokal.

**Tech Stack:** Ubuntu 24.04, PostgreSQL (apt), Python 3.12 + uv, SQLAlchemy/Alembic, systemd, Caddy.

**Bezug:** Umsetzung von `docs/superpowers/specs/2026-05-28-deployment-vps-design.md`.

---

## Voraussetzungen

- SSH-Zugang `deploy@labs.remoterepublic.com` (Key auf dem Dev-Mac, passwortloses sudo verifiziert).
- Lokaler `main` ist auf GitHub gepusht (`origin/main` == lokaler `main`).
- Lokale `airbi`-DB enthält den Crawl mit 25 Apartments.
- DNS `airbi.remoterepublic.com` zeigt auf den Host (verifiziert).

## Globale Sicherheits-Leitplanken (geteilter Host!)

- **Nur AirBI-Artefakte:** `/opt/airbi`, DB/Rolle `airbi`, `airbi-web.service`, der AirBI-Caddy-Block. Andere Apps (`/opt/guesty-*`, `/opt/str`, `/opt/labs-api`, …) und deren Daten **niemals** anfassen.
- **Vor jedem `sudo apt`, Caddy-Reload, DB-Restore:** Checkpoint, Nutzer bestätigt.
- **Caddyfile:** vorher Backup, nur anhängen, `caddy validate` vor `reload`.
- **Kein Force, keine destruktiven Operationen** an Bestands-Services/Dateien.
- Alle Server-Befehle laufen via `ssh deploy@labs.remoterepublic.com '...'` vom Dev-Mac (zsh: `ssh` immer inline schreiben, nicht über Shell-Variable — Wortsplitting-Falle).

---

## Task 1: Deploy-Key + git-clone nach /opt/airbi

**Server-Pfade:** `~/.ssh/airbi_deploy{,.pub}`, `~/.ssh/config`, `/opt/airbi`

- [ ] **Step 1: SSH-Deploy-Keypair auf dem Server erzeugen**

Run:
```bash
ssh -o ConnectTimeout=10 deploy@labs.remoterepublic.com \
  'test -f ~/.ssh/airbi_deploy || ssh-keygen -t ed25519 -f ~/.ssh/airbi_deploy -N "" -C "airbi-deploy@labs"; echo "--- PUBLIC KEY ---"; cat ~/.ssh/airbi_deploy.pub'
```
Expected: Gibt den `ssh-ed25519 …`-Public-Key aus (idempotent — bei erneutem Lauf kein Überschreiben).

- [ ] **Step 2: ⏸ PAUSE (User) — Public Key bei GitHub als Read-only Deploy-Key hinterlegen**

Der Nutzer öffnet `https://github.com/karlgrey/AirBI/settings/keys` → **Add deploy key** → Titel z.B. „labs-vps airbi-web", den Public-Key aus Step 1 einfügen, **„Allow write access" NICHT ankreuzen**, speichern.

Claude wartet auf Bestätigung „erledigt", bevor es weitergeht.

- [ ] **Step 3: SSH-Config-Alias auf dem Server für GitHub anlegen**

Run:
```bash
ssh -o ConnectTimeout=10 deploy@labs.remoterepublic.com 'cat >> ~/.ssh/config <<"EOF"

Host github-airbi
    HostName github.com
    User git
    IdentityFile ~/.ssh/airbi_deploy
    IdentitiesOnly yes
EOF
chmod 600 ~/.ssh/config; echo "config geschrieben"'
```
Expected: `config geschrieben`. (Falls der Block schon existiert: in Step 1 wird der Key nicht neu erzeugt; hier ggf. Duplikat vermeiden — vor erneutem Lauf `grep -q github-airbi ~/.ssh/config` prüfen.)

- [ ] **Step 4: SSH-Zugang zu GitHub verifizieren**

Run:
```bash
ssh -o ConnectTimeout=10 deploy@labs.remoterepublic.com 'ssh -o StrictHostKeyChecking=accept-new -T git@github-airbi 2>&1 | head -2'
```
Expected: `Hi karlgrey/AirBI! You've successfully authenticated, but GitHub does not provide shell access.` (Read-only Deploy-Key → Auth ok.)

- [ ] **Step 5: Repo nach /opt/airbi klonen**

Run:
```bash
ssh -o ConnectTimeout=10 deploy@labs.remoterepublic.com 'git clone git@github-airbi:karlgrey/AirBI.git /opt/airbi && cd /opt/airbi && git log --oneline -1'
```
Expected: Klon erfolgreich, zeigt den letzten Commit (`1840f88 chore: .superpowers/ …` oder neuer). `/opt/airbi` ist deploy-owned.

- [ ] **Step 6: Verifikation**

Run:
```bash
ssh -o ConnectTimeout=10 deploy@labs.remoterepublic.com 'ls /opt/airbi/airbi/web/static/app.css && echo "app.css vorhanden (kein Tailwind-Build nötig)"'
```
Expected: Pfad + `app.css vorhanden`.

---

## Task 2: PostgreSQL installieren + Rolle/DB + .env-Secret

**Server-Pfade:** systemweites PostgreSQL, `/opt/airbi/.env`

- [ ] **Step 1: ⚠ CHECKPOINT — `apt install postgresql` (systemweiter Eingriff)**

Vor Ausführung bestätigen lassen. Dann:
```bash
ssh -o ConnectTimeout=10 deploy@labs.remoterepublic.com 'sudo apt-get update -qq && sudo apt-get install -y postgresql postgresql-client 2>&1 | tail -5; echo "---"; psql --version; systemctl is-active postgresql'
```
Expected: Installation läuft durch, `psql (PostgreSQL) 16.x`, `active`.

- [ ] **Step 2: DB-Passwort generieren + Rolle + Datenbank anlegen + .env schreiben**

Run (das Passwort wird auf dem Server generiert und nur dort in `.env` abgelegt — niemals in git, niemals im Plan):
```bash
ssh -o ConnectTimeout=10 deploy@labs.remoterepublic.com 'PGPW=$(openssl rand -hex 24)
sudo -u postgres psql -v ON_ERROR_STOP=1 <<SQL
DO \$\$ BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '"'"'airbi'"'"') THEN
    CREATE ROLE airbi LOGIN PASSWORD '"'"'$PGPW'"'"';
  ELSE
    ALTER ROLE airbi LOGIN PASSWORD '"'"'$PGPW'"'"';
  END IF;
END \$\$;
SELECT '"'"'db_exists'"'"' FROM pg_database WHERE datname = '"'"'airbi'"'"';
SQL
sudo -u postgres psql -tc "SELECT 1 FROM pg_database WHERE datname='"'"'airbi'"'"'" | grep -q 1 || sudo -u postgres createdb -O airbi airbi
umask 077
printf "DATABASE_URL=postgresql+psycopg://airbi:%s@localhost:5432/airbi\n" "$PGPW" > /opt/airbi/.env
chmod 600 /opt/airbi/.env
echo "Rolle+DB angelegt, .env geschrieben (chmod 600)"'
```
Expected: `Rolle+DB angelegt, .env geschrieben (chmod 600)`. Idempotent (Rolle/DB werden nur angelegt, wenn nicht vorhanden; Passwort wird gesetzt).

- [ ] **Step 3: Verbindung als airbi verifizieren**

Run:
```bash
ssh -o ConnectTimeout=10 deploy@labs.remoterepublic.com 'set -a; . /opt/airbi/.env; set +a; PGPASSWORD=$(echo "$DATABASE_URL" | sed -E "s|.*://airbi:([^@]+)@.*|\1|") psql -h localhost -U airbi -d airbi -c "SELECT current_database(), current_user;"'
```
Expected: Tabelle mit `airbi | airbi`. (Bestätigt: Rolle kann sich lokal mit Passwort verbinden.)

- [ ] **Step 4: `.env` ist gitignored — Sanity**

Run:
```bash
ssh -o ConnectTimeout=10 deploy@labs.remoterepublic.com 'cd /opt/airbi && git check-ignore .env && echo "OK: .env wird von git ignoriert"'
```
Expected: `.env` + `OK: .env wird von git ignoriert`.

---

## Task 3: uv + Dependencies + Alembic-Migration

**Server-Pfade:** `~/.local/bin/uv`, `/opt/airbi/.venv`, Alembic auf Prod-DB

- [ ] **Step 1: uv für den deploy-User installieren**

Run:
```bash
ssh -o ConnectTimeout=10 deploy@labs.remoterepublic.com 'command -v ~/.local/bin/uv >/dev/null || curl -LsSf https://astral.sh/uv/install.sh | sh; ~/.local/bin/uv --version'
```
Expected: `uv 0.x.y`. (Idempotent — bei vorhandenem uv kein Re-Install.)

- [ ] **Step 2: Dependencies installieren (ohne Dev, ohne Playwright-Browser)**

Run:
```bash
ssh -o ConnectTimeout=10 deploy@labs.remoterepublic.com 'cd /opt/airbi && ~/.local/bin/uv sync --no-dev 2>&1 | tail -8'
```
Expected: venv `/opt/airbi/.venv` wird erzeugt, Web-Dependencies (fastapi, uvicorn, jinja2, sqlalchemy, psycopg, …) installiert. **Hinweis:** Wir rufen NICHT `playwright install` auf — der Server crawlt nicht; nur das Python-Paket `playwright` wird mitinstalliert (klein), die Browser-Binaries bleiben weg.

- [ ] **Step 3: Import-Smoke-Test (Web-App lädt ohne Crawl-Abhängigkeiten)**

Run:
```bash
ssh -o ConnectTimeout=10 deploy@labs.remoterepublic.com 'cd /opt/airbi && ~/.local/bin/uv run python -c "from airbi.web.app import app; print(\"web-app importiert ok\")"'
```
Expected: `web-app importiert ok` (kein Playwright-Browser-Fehler, weil der Serving-Pfad den Scraper nicht importiert).

- [ ] **Step 4: Alembic-Migrationen auf die Prod-DB anwenden**

Run (config.py liest `/opt/airbi/.env` über CWD):
```bash
ssh -o ConnectTimeout=10 deploy@labs.remoterepublic.com 'cd /opt/airbi && ~/.local/bin/uv run alembic upgrade head 2>&1 | tail -5'
```
Expected: Migration läuft auf `head` durch.

- [ ] **Step 5: Schema verifizieren**

Run:
```bash
ssh -o ConnectTimeout=10 deploy@labs.remoterepublic.com 'cd /opt/airbi && ~/.local/bin/uv run python -c "
import sqlalchemy as sa
from airbi.config import settings
e = sa.create_engine(settings.database_url)
print(sorted(sa.inspect(e).get_table_names()))
"'
```
Expected: `['alembic_version', 'crawl_run', 'listing', 'search_config', 'snapshot']`.

---

## Task 4: Daten-Migration (lokale DB → Prod, data-only)

**Lokal:** `pg_dump` der `airbi`-DB. **Prod:** Restore in die migrierte (leere) Prod-DB.

- [ ] **Step 1: Lokalen Daten-Dump erzeugen (data-only, da Schema via Alembic schon auf Prod ist)**

Run (lokal auf dem Dev-Mac):
```bash
pg_dump --data-only --no-owner --no-privileges \
  -h localhost -U airbi -d airbi \
  -t search_config -t crawl_run -t listing -t snapshot \
  -f /tmp/airbi-data.sql
wc -l /tmp/airbi-data.sql && grep -c "INSERT\|COPY" /tmp/airbi-data.sql
```
Expected: Datei `/tmp/airbi-data.sql` erzeugt, enthält COPY/INSERT-Blöcke für die vier Tabellen. (Falls lokal `PGPASSWORD` nötig: `PGPASSWORD=airbi` voranstellen — lokale Dev-Credentials aus Plan 1.)

- [ ] **Step 2: ⚠ CHECKPOINT — Dump auf Prod transferieren + einspielen**

Vor Ausführung bestätigen lassen (schreibt Daten in die Prod-DB). Dann:
```bash
scp /tmp/airbi-data.sql deploy@labs.remoterepublic.com:/tmp/airbi-data.sql
ssh -o ConnectTimeout=10 deploy@labs.remoterepublic.com 'cd /opt/airbi && set -a; . .env; set +a; PGPASSWORD=$(echo "$DATABASE_URL" | sed -E "s|.*://airbi:([^@]+)@.*|\1|") psql -h localhost -U airbi -d airbi -v ON_ERROR_STOP=1 -f /tmp/airbi-data.sql 2>&1 | tail -8; rm -f /tmp/airbi-data.sql'
```
Expected: `COPY`/`INSERT`-Bestätigungen ohne Fehler; Dump-Datei auf dem Server danach gelöscht.

- [ ] **Step 3: Daten auf Prod verifizieren**

Run:
```bash
ssh -o ConnectTimeout=10 deploy@labs.remoterepublic.com 'cd /opt/airbi && ~/.local/bin/uv run python -c "
from airbi.db.session import SessionLocal
from airbi.db.models import CrawlRun, Listing, Snapshot, SearchConfig
s = SessionLocal()
print(\"SearchConfigs:\", s.query(SearchConfig).count())
print(\"CrawlRuns:\", s.query(CrawlRun).count(), \"(completed:\", s.query(CrawlRun).filter_by(status=\"completed\").count(), \")\")
print(\"Listings:\", s.query(Listing).count())
print(\"Snapshots:\", s.query(Snapshot).count())
s.close()
"'
```
Expected: Counts == lokal (SearchConfigs ≥1, CrawlRuns ≥1 completed, Listings ~25, Snapshots ~25).

---

## Task 5: systemd-Unit `airbi-web`

**Server-Pfade:** `/etc/systemd/system/airbi-web.service`

- [ ] **Step 1: Unit-Datei schreiben**

Run:
```bash
ssh -o ConnectTimeout=10 deploy@labs.remoterepublic.com 'sudo tee /etc/systemd/system/airbi-web.service >/dev/null <<"EOF"
[Unit]
Description=AirBI Dashboard (FastAPI/uvicorn)
After=network.target postgresql.service
Wants=postgresql.service

[Service]
Type=simple
User=deploy
Group=deploy
WorkingDirectory=/opt/airbi
Environment=HOME=/home/deploy
EnvironmentFile=/opt/airbi/.env
ExecStart=/home/deploy/.local/bin/uv run airbi web --host 127.0.0.1 --port 8000
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF
echo "unit geschrieben"'
```
Expected: `unit geschrieben`.

- [ ] **Step 2: Aktivieren + starten**

Run:
```bash
ssh -o ConnectTimeout=10 deploy@labs.remoterepublic.com 'sudo systemctl daemon-reload && sudo systemctl enable --now airbi-web && sleep 4 && systemctl is-active airbi-web'
```
Expected: `active`.

- [ ] **Step 3: Lokalen Health-Check auf dem Server**

Run:
```bash
ssh -o ConnectTimeout=10 deploy@labs.remoterepublic.com 'curl -s -o /dev/null -w "health: %{http_code}\n" http://127.0.0.1:8000/health; curl -s http://127.0.0.1:8000/health'
```
Expected: `health: 200` + `{"status":"ok"}`.

- [ ] **Step 4: Dashboard-Root lokal prüfen (Daten sichtbar?)**

Run:
```bash
ssh -o ConnectTimeout=10 deploy@labs.remoterepublic.com 'curl -s -o /dev/null -w "/: %{http_code}\n" "http://127.0.0.1:8000/"; curl -s "http://127.0.0.1:8000/" | grep -c "Marktübersicht\|Marvila Slice 1"'
```
Expected: `/: 200` und grep-Count ≥1 (echte Daten gerendert, nicht Empty-State).

- [ ] **Step 5: Restart-Resilienz**

Run:
```bash
ssh -o ConnectTimeout=10 deploy@labs.remoterepublic.com 'sudo systemctl restart airbi-web && sleep 4 && systemctl is-active airbi-web && curl -s -o /dev/null -w "nach restart: %{http_code}\n" http://127.0.0.1:8000/health'
```
Expected: `active` + `nach restart: 200`.

---

## Task 6: Caddy-Vhost für airbi.remoterepublic.com

**Server-Pfade:** `/etc/caddy/Caddyfile` (Backup + Append)

- [ ] **Step 1: Caddyfile sichern**

Run:
```bash
ssh -o ConnectTimeout=10 deploy@labs.remoterepublic.com 'sudo cp -a /etc/caddy/Caddyfile /etc/caddy/Caddyfile.bak-airbi-$(date +%Y%m%d-%H%M%S) && ls -la /etc/caddy/Caddyfile.bak-airbi-* | tail -1'
```
Expected: Backup-Datei angelegt.

- [ ] **Step 2: Prüfen, dass noch kein airbi-Block existiert**

Run:
```bash
ssh -o ConnectTimeout=10 deploy@labs.remoterepublic.com 'grep -q "airbi.remoterepublic.com" /etc/caddy/Caddyfile && echo "BLOCK EXISTIERT SCHON — nicht doppeln" || echo "kein airbi-Block, anhängen ok"'
```
Expected: `kein airbi-Block, anhängen ok`.

- [ ] **Step 3: ⚠ CHECKPOINT — AirBI-Block anhängen**

Vor Ausführung bestätigen lassen. Dann:
```bash
ssh -o ConnectTimeout=10 deploy@labs.remoterepublic.com 'sudo tee -a /etc/caddy/Caddyfile >/dev/null <<"EOF"

# AirBI Dashboard — added 2026-05-28
airbi.remoterepublic.com {
	reverse_proxy localhost:8000 {
		header_up Host {host}
		header_up X-Real-IP {remote}
		header_up X-Forwarded-For {remote}
		header_up X-Forwarded-Proto {scheme}
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
EOF
echo "Block angehängt"'
```
Expected: `Block angehängt`.

- [ ] **Step 4: Caddy-Config validieren (VOR reload)**

Run:
```bash
ssh -o ConnectTimeout=10 deploy@labs.remoterepublic.com 'sudo caddy validate --config /etc/caddy/Caddyfile 2>&1 | tail -5'
```
Expected: `Valid configuration`. **Bei Fehler:** Backup aus Step 1 zurückspielen (`sudo cp <backup> /etc/caddy/Caddyfile`), NICHT reloaden, eskalieren.

- [ ] **Step 5: ⚠ CHECKPOINT — Caddy reloaden (betrifft alle Domains)**

Vor Ausführung bestätigen lassen. Dann:
```bash
ssh -o ConnectTimeout=10 deploy@labs.remoterepublic.com 'sudo systemctl reload caddy && sleep 2 && systemctl is-active caddy'
```
Expected: `active`.

- [ ] **Step 6: Bestands-Domain unbeeinträchtigt (Regressionsprüfung)**

Run:
```bash
ssh -o ConnectTimeout=10 deploy@labs.remoterepublic.com 'curl -s -o /dev/null -w "guesty: %{http_code}\n" https://guesty.remoterepublic.com/ 2>&1'
```
Expected: Bestands-Domain antwortet weiter (200/302/o.ä., kein Verbindungsabbruch).

---

## Task 7: End-to-End-Acceptance + Update-Pfad

- [ ] **Step 1: TLS + Dashboard öffentlich erreichbar (vom Dev-Mac)**

Run:
```bash
curl -s -o /dev/null -w "https://airbi: %{http_code}, TLS: %{ssl_verify_result}\n" https://airbi.remoterepublic.com/
```
Expected: `https://airbi: 200, TLS: 0` (0 = Zertifikat ok). Erster Request kann durch Let's-Encrypt-Ausstellung ein paar Sekunden dauern — ggf. 1× wiederholen.

- [ ] **Step 2: Echte Daten im öffentlichen Dashboard**

Run:
```bash
curl -s https://airbi.remoterepublic.com/ | grep -o "Marktübersicht\|Untersuchungsbereich\|Datenstand" | sort -u
```
Expected: Mindestens `Marktübersicht`, `Untersuchungsbereich`, `Datenstand` erscheinen → Klartext-Dashboard mit Daten live.

- [ ] **Step 3: §10-Acceptance-Kriterien abhaken**

Spec §10 Punkt für Punkt: (1) `systemctl status airbi-web` active + restart-fest ✓ (Task 5), (2) `/health` 200 ✓, (3) HTTPS 200 + gültiges TLS ✓, (4) Daten statt Empty-State ✓, (5) Bestands-Domain unbeeinträchtigt ✓ (Task 6 Step 6), (6) Update-Pfad (Step 4).

- [ ] **Step 4: Update-Pfad trocken verifizieren**

Run:
```bash
ssh -o ConnectTimeout=10 deploy@labs.remoterepublic.com 'cd /opt/airbi && git pull --ff-only 2>&1 | tail -3 && echo "pull ok (kein Force, fast-forward-only)"'
```
Expected: `Already up to date.` + `pull ok`. Dokumentiert den künftigen Update-Befehl:
`cd /opt/airbi && git pull --ff-only && ~/.local/bin/uv sync --no-dev && ~/.local/bin/uv run alembic upgrade head && sudo systemctl restart airbi-web`.

- [ ] **Step 5: Deploy-Doku im Repo ablegen**

Lokal eine knappe `docs/DEPLOYMENT.md` mit dem obigen Update-Befehl, der Host-/Pfad-Übersicht und „bewusst nicht: Auto-Crawl/Backup/Monitoring" anlegen und committen + pushen:
```bash
git add docs/DEPLOYMENT.md && git commit -m "docs: VPS-Deployment-Übersicht + Update-Pfad" && git push origin main
```
(Inhalt: Host `deploy@labs.remoterepublic.com`, Code `/opt/airbi`, Service `airbi-web`, Caddy-Block, DB `airbi`, Update-Befehl, Out-of-Scope.)

---

## Definition of Done

- [ ] `https://airbi.remoterepublic.com/` liefert 200 mit gültigem TLS und zeigt das Klartext-Dashboard mit den echten 25 Apartments (nicht Empty-State).
- [ ] `airbi-web.service` ist `enabled` + `active`, übersteht `restart`.
- [ ] Caddy-Reload hat keine Bestands-Domain beeinträchtigt; Caddyfile-Backup liegt vor.
- [ ] Prod-DB-Counts == lokale Counts.
- [ ] `.env` mit DB-Secret ist `chmod 600`, deploy-owned, gitignored — nicht in git.
- [ ] Update-Pfad (`git pull` → `uv sync` → `alembic upgrade` → `restart`) verifiziert + in `docs/DEPLOYMENT.md` dokumentiert (committet + gepusht).

## Bewusst NICHT in diesem Plan (Spec §11)

- APScheduler-Auto-Crawl auf dem Server, Backup-Cron, Monitoring/Alerting.
- Residential-Proxy + Crawl-Topologie auf dem Server (Crawl bleibt Dev-Rechner).
- Playwright-Browser-Binaries auf dem Server.
- CI/CD, Staging.

## Rollback (falls etwas schiefgeht)

- **App kaputt:** `sudo systemctl stop airbi-web` — andere Apps unberührt.
- **Caddy-Block-Problem:** Backup zurück (`sudo cp /etc/caddy/Caddyfile.bak-airbi-<ts> /etc/caddy/Caddyfile && sudo caddy validate --config /etc/caddy/Caddyfile && sudo systemctl reload caddy`).
- **DB-Müll:** `sudo -u postgres dropdb airbi` (nur AirBI-DB) + neu anlegen — betrifft keine andere App (keine nutzt Postgres).
- **Komplett zurück:** Unit deaktivieren (`sudo systemctl disable --now airbi-web`), `/opt/airbi` entfernen, Caddy-Block-Backup zurück, `airbi`-Rolle/DB droppen.
