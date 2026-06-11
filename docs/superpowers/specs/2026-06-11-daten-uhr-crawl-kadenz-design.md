# Daten-Uhr — automatische Crawl-Kadenz auf dem Mac

> Status: Design abgenommen (2026-06-11)
> Auslöser: Review-Velocity ist das im Briefing vorgesehene Nachfrage-Maß,
> aber der Datenbestand trägt sie nicht: 5 Crawl-Runs (22.05.–01.06.),
> Ø 1,2 Snapshots pro Listing, nur 42 von 634 Listings mit zwei
> Messtagen. Es gibt keinen automatischen Crawl-Rhythmus — jede Woche
> ohne Lauf verschiebt belastbare Velocity weiter nach hinten.

## 1. Ziel

Eine unbeaufsichtigte Crawl-Kadenz, die ab sofort Snapshot-Historie
aufbaut und den Produktions-Stand auf dem VPS automatisch aktuell hält.
Teilprojekt 1 von 3 (danach: Memo-Redesign des Dashboards,
Velocity-Modul).

## 2. Entscheidungen

- **Ort: dieser Mac, launchd.** Der Crawl braucht die Wohn-IP
  (Residential), der VPS crawlt bewusst nicht (siehe DEPLOYMENT.md).
  VPS + Residential-Proxy bleibt eine spätere Option, wenn sich das
  Tool bewährt — bewusst nicht jetzt.
- **Kadenz: 2×/Woche** (Montag + Donnerstag, 07:00). Wöchentlich würde
  für Velocity reichen, zwei Messpunkte pro Woche halbieren aber die
  Wartezeit bis zur belastbaren Historie — bei weiterhin unauffälligem
  Request-Volumen („so wenig Requests wie nötig" bleibt gewahrt).
- **Auto-Sync zum VPS bei Erfolg.** Der dokumentierte
  Dump/scp/Restore-Pfad aus DEPLOYMENT.md, als Skript gegossen.
  Passwortloser SSH-Zugang `deploy@labs.remoterepublic.com` ist
  verifiziert (BatchMode-Test 2026-06-11).

## 3. Komponenten

### 3.1 `scripts/scheduled_crawl.sh`

Wrapper, den launchd startet:

1. Log-Datei `~/Library/Logs/airbi/crawl-<YYYY-MM-DD-HHMM>.log`
   öffnen (Verzeichnis bei Bedarf anlegen), alles dorthin.
2. `PYTHONUNBUFFERED=1 caffeinate -d -i -s -- uv run airbi crawl
   --config "Marvila Slice 1" --verbose` aus dem Repo-Verzeichnis.
   Die Crawl-Resilienz (Auto-Resume eines `running`-Runs,
   per-Box-Commit, Detail-Phase per-Listing-Commit) existiert bereits
   und wird unverändert genutzt.
3. **Exit 0:** Sync-Schritt — `pg_dump --data-only` der vier Tabellen
   (`search_config`, `crawl_run`, `listing`, `snapshot`) → scp →
   Restore auf dem VPS (Prod-Daten der vier Tabellen vorher leeren,
   damit der Restore idempotent ist) → Tempdatei löschen.
4. **Exit ≠ 0 (Crawl oder Sync):** macOS-Benachrichtigung via
   `osascript -e 'display notification …'` mit Pfad zum Log. Kein
   stilles Scheitern; kein Retry-Orchestrator — der nächste
   launchd-Lauf resumiert den abgebrochenen Run von selbst.

### 3.2 `~/Library/LaunchAgents/com.airbi.crawl.plist`

- `StartCalendarInterval`: Mo + Do, 07:00.
- launchd holt einen verschlafenen Lauf beim nächsten Aufwachen nach
  (Coalescing) — Mac zu, Job kommt trotzdem.
- `StandardOutPath`/`StandardErrorPath` als Fallback-Log
  (`~/Library/Logs/airbi/launchd.log`), das Skript loggt ohnehin
  selbst.
- Die plist liegt versioniert als Template im Repo
  (`scripts/com.airbi.crawl.plist`); Installation = Kopie nach
  `~/Library/LaunchAgents` + `launchctl bootstrap gui/$(id -u) …`.
  Install-Schritte in DEPLOYMENT.md dokumentieren.

## 4. Fehlerfälle

| Fall | Verhalten |
|---|---|
| Mac schläft zum Termin | launchd holt den Lauf beim Aufwachen nach |
| Crawl bricht ab (Block, Netz) | Notification; nächster Lauf resumiert via Auto-Resume |
| Mac nicht im Heimnetz | Crawl läuft über fremde IP oder scheitert → Notification; kein Sonderfall-Code |
| VPS nicht erreichbar | Crawl-Daten sind lokal committed; Notification; Sync holt der nächste erfolgreiche Lauf nach |
| Zwei Läufe überlappen | Auto-Resume-Logik greift (ein `running`-Run wird fortgesetzt, nicht dupliziert) |

## 5. Tests / Verifikation

- Syntax-Check (`bash -n`), danach ein **echter Probelauf** über
  `launchctl kickstart`: ein vollständiger Crawl + Sync, im Log
  verifiziert. Ein Dry-Run-Modus lohnt sich für dieses Skript nicht.
- Restore-Idempotenz: zweimal hintereinander syncen darf auf dem VPS
  keine Duplikate erzeugen (Leeren vor Restore).
- Notification: Fehlerpfad einmal künstlich auslösen (z. B. falscher
  Config-Name) und Benachrichtigung sichten.

## 6. Bewusst nicht gebaut

- Kein Monitoring-Stack, kein Alerting über die macOS-Notification
  hinaus, kein Backup-Cron (separates Thema).
- Kein APScheduler im Web-Prozess — der Scheduler ist launchd, nicht
  die App; der VPS bleibt crawl-frei.
- Keine Proxy-Integration (kommt ggf. mit dem VPS-Crawl-Teilprojekt).
