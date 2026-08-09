#!/usr/bin/env python3
"""B3 Stufe 0: Sicherung des Zielkalenderbestands vor der ersten Mutation.

Liest ausschliesslich den bestehenden autorisierten Bestand (die produktive
SQLite des Lesepfads), exportiert den vollstaendigen Zeilenbestand des
Zielkalenders sowie eine Kopie der Datenbank NACH AUSSERHALB des Repos,
setzt restriktive Rechte und schreibt den PII-armen Nachweis, den der
B3-Mutationsdienst vor jedem Claim verlangt.

Aufruf:  b3-calendar-backup.py <provider_calendar_id>
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

DB = Path.home() / ".openjarvis" / "personal" / "jarvis.db"
ZIEL = Path.home() / ".openjarvis" / "personal" / "backups" / "calendar"


def main() -> int:
    if len(sys.argv) != 2:
        print("Aufruf: b3-calendar-backup.py <provider_calendar_id>",
              file=sys.stderr)
        return 2
    provider_calendar_id = sys.argv[1]
    if not DB.is_file():
        print("Produktive Datenbank fehlt", file=sys.stderr)
        return 3

    ZIEL.mkdir(parents=True, exist_ok=True)
    ZIEL.chmod(0o700)
    stempel = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    verbindung = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    verbindung.row_factory = sqlite3.Row
    kalender = verbindung.execute(
        "SELECT id, provider_calendar_id FROM calendars "
        "WHERE provider_calendar_id = ?", (provider_calendar_id,)).fetchone()
    if kalender is None:
        print("Zielkalender ist im Bestand nicht bekannt", file=sys.stderr)
        return 4
    zeilen = [dict(r) for r in verbindung.execute(
        "SELECT * FROM events WHERE calendar_id = ?", (kalender["id"],))]
    verbindung.close()

    # Vollexport (verlustarm: alle Spalten des Bestands) — nur lokal.
    export = ZIEL / f"events-{stempel}.json"
    export.write_text(json.dumps(
        {"schema_version": 1, "provider_calendar_id": provider_calendar_id,
         "exported_at_utc": stempel, "events": zeilen},
        ensure_ascii=False, sort_keys=True, indent=1), encoding="utf-8")
    export.chmod(0o600)

    # Zusaetzlich die Datenbankkopie nach bestehender Konvention.
    dbkopie = ZIEL / f"jarvis.db.pre-b3-{stempel}.bak"
    shutil.copyfile(DB, dbkopie)
    dbkopie.chmod(0o600)

    # Mechanischer Lesbarkeitstest: beide Artefakte werden zurueckgelesen.
    gelesen = json.loads(export.read_text(encoding="utf-8"))
    if len(gelesen["events"]) != len(zeilen):
        print("Lesbarkeitstest des Exports fehlgeschlagen", file=sys.stderr)
        return 5
    pruefung = sqlite3.connect(f"file:{dbkopie}?mode=ro", uri=True)
    integritaet = pruefung.execute("PRAGMA integrity_check").fetchone()[0]
    pruefung.close()
    if integritaet != "ok":
        print("Integritaetsprüfung der DB-Kopie fehlgeschlagen", file=sys.stderr)
        return 6

    digest = hashlib.sha256(export.read_bytes()).hexdigest()
    nachweis = {
        "schema_version": 1,
        "created_at_utc": stempel,
        "sha256": digest,
        "db_copy_sha256": hashlib.sha256(dbkopie.read_bytes()).hexdigest(),
        "entry_count": len(zeilen),
        # PII-arm: nie der Kalendername, nur der stabile Digest der Kennung.
        "source_calendar_digest": hashlib.sha256(
            provider_calendar_id.encode("utf-8")).hexdigest(),
        "verified": True,
    }
    latest = ZIEL / "latest.json"
    latest.write_text(json.dumps(nachweis, sort_keys=True, indent=1),
                      encoding="utf-8")
    latest.chmod(0o600)
    print(json.dumps(nachweis, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
