# Daten-Uhr (launchd-Crawl-Kadenz + VPS-Auto-Sync) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Automatischer Crawl 2×/Woche (Mo + Do 07:00) auf diesem Mac via launchd, mit Auto-Sync der Daten zum VPS bei Erfolg und macOS-Benachrichtigung bei Fehlern.

**Architecture:** Ein launchd-LaunchAgent startet ein Bash-Wrapper-Skript. Das Skript loggt nach `~/Library/Logs/airbi/`, führt den bestehenden resilienten `airbi crawl` unter `caffeinate` aus, und synct bei Erfolg per dokumentiertem Dump→scp→Restore-Pfad zum VPS (idempotent durch TRUNCATE vor Restore). Kein neuer Python-Code, kein Scheduler in der App.

**Tech Stack:** Bash, launchd (plist), pg_dump/psql (PostgreSQL 16 Homebrew), ssh/scp (BatchMode), osascript.

**Spec:** `docs/superpowers/specs/2026-06-11-daten-uhr-crawl-kadenz-design.md`

**Wichtige Umgebungsfakten (für Worker ohne Kontext):**
- Repo: `/Users/mca/Development/AirBI`, User-Home: `/Users/mca`
- `uv` liegt unter `/opt/homebrew/bin/uv` (launchd hat minimales PATH → absolute Pfade verwenden)
- PostgreSQL-Binaries: `/opt/homebrew/opt/postgresql@16/bin/` (keg-only, nicht im PATH)
- Lokale DB: `airbi`/Passwort `airbi`, DB `airbi`
- VPS: `deploy@labs.remoterepublic.com`, passwortloser SSH-Zugang verifiziert; App-Code in `/opt/airbi`, `.env` enthält `DATABASE_URL`
- Tabellen für den Sync: `search_config`, `crawl_run`, `listing`, `snapshot`
- Der Server liest nur (Web-Dashboard); Sequenz-Stände nach Restore sind deshalb egal

---

### Task 1: Wrapper-Skript `scripts/scheduled_crawl.sh`

**Files:**
- Create: `scripts/scheduled_crawl.sh`

- [ ] **Step 1: Skript anlegen**

```bash
#!/bin/bash
# AirBI Daten-Uhr: Crawl + VPS-Sync, gestartet von launchd (com.airbi.crawl).
# Spec: docs/superpowers/specs/2026-06-11-daten-uhr-crawl-kadenz-design.md
set -uo pipefail

REPO="/Users/mca/Development/AirBI"
LOG_DIR="$HOME/Library/Logs/airbi"
STAMP="$(date +%Y-%m-%d-%H%M)"
LOG="$LOG_DIR/crawl-$STAMP.log"
UV="/opt/homebrew/bin/uv"
PGBIN="/opt/homebrew/opt/postgresql@16/bin"
SERVER="deploy@labs.remoterepublic.com"
CONFIG_NAME="${AIRBI_CONFIG:-Marvila Slice 1}"
DUMP="/tmp/airbi-data-$STAMP.sql"

mkdir -p "$LOG_DIR"
exec >>"$LOG" 2>&1

notify() {
  /usr/bin/osascript -e "display notification \"$1 — Log: $LOG\" with title \"AirBI Daten-Uhr\""
}

echo "=== AirBI scheduled crawl $STAMP (Config: $CONFIG_NAME) ==="

cd "$REPO" || { notify "Repo-Verzeichnis fehlt"; exit 1; }

if ! PYTHONUNBUFFERED=1 /usr/bin/caffeinate -d -i -s -- \
    "$UV" run airbi crawl --config "$CONFIG_NAME" --verbose; then
  notify "Crawl fehlgeschlagen"
  exit 1
fi

echo "--- Crawl ok, Sync zum VPS ---"

if ! PGPASSWORD=airbi "$PGBIN/pg_dump" --data-only --no-owner --no-privileges \
    -h localhost -U airbi -d airbi \
    -t search_config -t crawl_run -t listing -t snapshot -f "$DUMP"; then
  notify "pg_dump fehlgeschlagen"
  exit 1
fi

if ! scp -o BatchMode=yes "$DUMP" "$SERVER:/tmp/airbi-data.sql"; then
  notify "scp zum VPS fehlgeschlagen"
  rm -f "$DUMP"
  exit 1
fi

if ! ssh -o BatchMode=yes "$SERVER" '
  set -e
  cd /opt/airbi
  set -a; . .env; set +a
  PW=$(echo "$DATABASE_URL" | sed -E "s|.*://airbi:([^@]+)@.*|\1|")
  PGPASSWORD="$PW" psql -h localhost -U airbi -d airbi -v ON_ERROR_STOP=1 \
    -c "TRUNCATE search_config, crawl_run, listing, snapshot CASCADE;"
  PGPASSWORD="$PW" psql -h localhost -U airbi -d airbi -v ON_ERROR_STOP=1 \
    -q -f /tmp/airbi-data.sql
  rm -f /tmp/airbi-data.sql
'; then
  notify "VPS-Restore fehlgeschlagen"
  rm -f "$DUMP"
  exit 1
fi

rm -f "$DUMP"
echo "=== Fertig: Crawl + Sync ok ==="
notify "Crawl + Sync erfolgreich"
```

Hinweise zum Design (nicht ins Skript kopieren):
- `set -uo pipefail` ohne `-e`: Fehler werden explizit pro Schritt behandelt, damit jede Fehlerquelle ihre eigene Notification bekommt.
- `AIRBI_CONFIG`-Override existiert nur für den Fehlerpfad-Test (Task 4) — Default ist die Produktiv-Config.
- TRUNCATE vor Restore macht den Sync idempotent (Spec §3.1 Punkt 3).

- [ ] **Step 2: Ausführbar machen + Syntax-Check**

```bash
chmod +x scripts/scheduled_crawl.sh
bash -n scripts/scheduled_crawl.sh && echo SYNTAX-OK
```

Expected: `SYNTAX-OK`, kein weiterer Output.

- [ ] **Step 3: Commit**

```bash
git add scripts/scheduled_crawl.sh
git commit -m "feat(daten-uhr): Wrapper-Skript für launchd-Crawl + VPS-Sync"
```

---

### Task 2: launchd-plist-Template `scripts/com.airbi.crawl.plist`

**Files:**
- Create: `scripts/com.airbi.crawl.plist`

- [ ] **Step 1: plist anlegen**

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.airbi.crawl</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>/Users/mca/Development/AirBI/scripts/scheduled_crawl.sh</string>
  </array>
  <key>StartCalendarInterval</key>
  <array>
    <dict>
      <key>Weekday</key><integer>1</integer>
      <key>Hour</key><integer>7</integer>
      <key>Minute</key><integer>0</integer>
    </dict>
    <dict>
      <key>Weekday</key><integer>4</integer>
      <key>Hour</key><integer>7</integer>
      <key>Minute</key><integer>0</integer>
    </dict>
  </array>
  <key>StandardOutPath</key>
  <string>/Users/mca/Library/Logs/airbi/launchd.log</string>
  <key>StandardErrorPath</key>
  <string>/Users/mca/Library/Logs/airbi/launchd.log</string>
</dict>
</plist>
```

(Weekday 1 = Montag, 4 = Donnerstag. launchd holt verschlafene Termine beim Aufwachen nach.)

- [ ] **Step 2: Lint**

```bash
plutil -lint scripts/com.airbi.crawl.plist
```

Expected: `scripts/com.airbi.crawl.plist: OK`

- [ ] **Step 3: Commit**

```bash
git add scripts/com.airbi.crawl.plist
git commit -m "feat(daten-uhr): launchd-plist (Mo+Do 07:00)"
```

---

### Task 3: Installation + Doku in DEPLOYMENT.md

**Files:**
- Modify: `docs/DEPLOYMENT.md` (Abschnitt „Daten aktualisieren" ergänzen; Bullet „APScheduler-Auto-Crawl" unter „Bewusst (noch) NICHT auf dem Server" präzisieren)

- [ ] **Step 1: LaunchAgent installieren**

```bash
cp scripts/com.airbi.crawl.plist ~/Library/LaunchAgents/com.airbi.crawl.plist
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.airbi.crawl.plist
launchctl print gui/$(id -u)/com.airbi.crawl | head -5
```

Expected: `launchctl print` zeigt den Job (`state = waiting` o. ä.). Falls „Bootstrap failed: 5: Input/output error": Job war schon geladen → erst `launchctl bootout gui/$(id -u)/com.airbi.crawl`, dann erneut bootstrappen.

- [ ] **Step 2: DEPLOYMENT.md ergänzen**

In `docs/DEPLOYMENT.md`, im Abschnitt „## Daten aktualisieren" direkt nach der Abschnittsüberschrift folgenden Block einfügen (vor dem `UPDATE search_config`-Teil):

```markdown
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
```

Außerdem unter „## Bewusst (noch) NICHT auf dem Server" den Bullet
`- APScheduler-Auto-Crawl, Backup-Cron, Monitoring/Alerting.` ersetzen durch:

```markdown
- Backup-Cron, Monitoring/Alerting. (Auto-Crawl läuft seit 2026-06-11 als launchd-Job auf dem Dev-Mac — bewusst kein APScheduler im Server-Prozess.)
```

- [ ] **Step 3: Commit**

```bash
git add docs/DEPLOYMENT.md
git commit -m "docs(daten-uhr): Installations- und Betriebsdoku"
```

---

### Task 4: Fehlerpfad verifizieren (Notification)

**Files:** keine Änderungen — reiner Verifikationstask.

- [ ] **Step 1: Fehlerlauf mit nicht existenter Config auslösen**

```bash
AIRBI_CONFIG="gibt-es-nicht" bash scripts/scheduled_crawl.sh; echo "exit=$?"
```

Expected: `exit=1` (Crawl bricht ab, weil die SearchConfig nicht existiert).

- [ ] **Step 2: Log + Notification sichten**

```bash
ls -t ~/Library/Logs/airbi/crawl-*.log | head -1 | xargs tail -5
```

Expected: Fehlermeldung des Crawls im Log. Auf dem Bildschirm muss eine macOS-Benachrichtigung „AirBI Daten-Uhr / Crawl fehlgeschlagen…" erschienen sein — beim Nutzer rückfragen, ob sie sichtbar war, falls der Worker sie nicht selbst prüfen kann.

---

### Task 5: Echter Probelauf (Crawl + Sync Ende-zu-Ende)

**Files:** keine Änderungen — reiner Verifikationstask. Dauer: ein voller Crawl (potenziell >1 h) — im Hintergrund laufen lassen.

- [ ] **Step 1: Kickstart**

```bash
launchctl kickstart gui/$(id -u)/com.airbi.crawl
sleep 5
ls -t ~/Library/Logs/airbi/crawl-*.log | head -1
```

Expected: neue Log-Datei existiert und wächst (`tail -f` zeigt Crawl-Fortschritt).

- [ ] **Step 2: Auf Abschluss warten und Log prüfen**

```bash
ls -t ~/Library/Logs/airbi/crawl-*.log | head -1 | xargs tail -3
```

Expected (nach Abschluss): `=== Fertig: Crawl + Sync ok ===` als letzte inhaltliche Zeile.

- [ ] **Step 3: Datenstand lokal vs. VPS vergleichen**

```bash
PGPASSWORD=airbi /opt/homebrew/opt/postgresql@16/bin/psql -U airbi -d airbi -t \
  -c "SELECT count(*) FROM listing; SELECT count(*) FROM snapshot;"
ssh deploy@labs.remoterepublic.com 'cd /opt/airbi && set -a; . .env; set +a; \
  PGPASSWORD=$(echo "$DATABASE_URL" | sed -E "s|.*://airbi:([^@]+)@.*|\1|") \
  psql -h localhost -U airbi -d airbi -t \
  -c "SELECT count(*) FROM listing; SELECT count(*) FROM snapshot;"'
```

Expected: identische Zahlen lokal und auf dem VPS. Außerdem muss die lokale Snapshot-Zahl deutlich über dem Stand vor dem Lauf liegen (vorher: 730).

- [ ] **Step 4: Idempotenz des Restores prüfen**

Den Sync-Teil isoliert noch einmal ausführen (Dump existiert nicht mehr → frisch erzeugen) und prüfen, dass die VPS-Zahlen unverändert bleiben (kein Verdoppeln):

```bash
PGPASSWORD=airbi /opt/homebrew/opt/postgresql@16/bin/pg_dump --data-only --no-owner --no-privileges \
  -h localhost -U airbi -d airbi \
  -t search_config -t crawl_run -t listing -t snapshot -f /tmp/airbi-idem.sql
scp -o BatchMode=yes /tmp/airbi-idem.sql deploy@labs.remoterepublic.com:/tmp/airbi-data.sql
ssh -o BatchMode=yes deploy@labs.remoterepublic.com '
  set -e; cd /opt/airbi; set -a; . .env; set +a
  PW=$(echo "$DATABASE_URL" | sed -E "s|.*://airbi:([^@]+)@.*|\1|")
  PGPASSWORD="$PW" psql -h localhost -U airbi -d airbi -v ON_ERROR_STOP=1 \
    -c "TRUNCATE search_config, crawl_run, listing, snapshot CASCADE;"
  PGPASSWORD="$PW" psql -h localhost -U airbi -d airbi -v ON_ERROR_STOP=1 -q -f /tmp/airbi-data.sql
  rm -f /tmp/airbi-data.sql
  PGPASSWORD="$PW" psql -h localhost -U airbi -d airbi -t -c "SELECT count(*) FROM snapshot;"'
rm -f /tmp/airbi-idem.sql
```

Expected: Snapshot-Zahl auf dem VPS identisch zu Step 3 — TRUNCATE+Restore erzeugt keine Duplikate.

- [ ] **Step 5: Dashboard-Smoke-Test auf dem VPS**

```bash
ssh deploy@labs.remoterepublic.com 'curl -s localhost:8000/health'
```

Expected: `{"status":"ok"}` — die App lebt nach dem Restore weiter (sie liest pro Request, kein Neustart nötig).
