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
