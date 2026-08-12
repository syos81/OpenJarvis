#!/usr/bin/env python3
"""Sicherung des Kontaktebestands vor einer produktiven Mutation.

Warum es das gibt
-----------------
Dauerregeln §3 verlangt vor destruktiven Tests auf nicht-disposablen Daten
ein *brauchbares* Backup und einen *vorab belegten* Recovery-Weg. Ein
Hinweis auf die Existenz irgendeiner Sicherungsfunktion genügt
ausdrücklich nicht. Der verschlüsselte Backup-Kern (AV-23, 13 §1) ist noch
nicht gebaut; bis dahin stellt dieses Skript genau das her, was die
M2-Abnahmecheckliste Punkt 8 verlangt — nicht mehr:

* eine konsistente Kopie der produktiven SQLite (über die SQLite-eigene
  Backup-API, damit WAL-Stände nicht halb mitkopiert werden),
* `PRAGMA integrity_check` auf **der Kopie**, nicht auf dem Original,
* die fachlichen Aggregate vorher, als Vergleichsbasis für nachher,
* ein Lesbarkeitsnachweis: die Kopie wird geöffnet und ausgezählt. Erst
  damit ist der Recovery-Weg belegt und nicht bloss behauptet.

Die Sicherung liegt **ausserhalb** des Repositorys, im ohnehin privaten
Datenverzeichnis: Datei 0600, Ordner 0700.

Der Bericht ist PII-arm: er nennt Zahlen, Zeitstempel und Hashes, aber
keinen Namen, keine Adresse und keinen Provider-Identifier.

Aufruf:  contacts-backup.py <grund>
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

DB = Path.home() / ".openjarvis" / "personal" / "jarvis.db"
ZIEL = Path.home() / ".openjarvis" / "personal" / "backups" / "contacts"

#: Fachlich relevante Zählungen. Die Auswahl ist bewusst klein: sie muss
#: einen Verlust sichtbar machen, nicht den Bestand beschreiben.
AGGREGATE = (
    "contacts",
    "contact_external_ids",
    "contact_emails",
    "contact_phones",
    "contact_postal_addresses",
    "contact_urls",
    "contact_field_availability",
    "contacts_tombstones",
    "contacts_mutations",
    "contacts_sync_state",
    "contacts_sync_audit",
)


def _zaehle(con: sqlite3.Connection) -> dict[str, int]:
    werte: dict[str, int] = {}
    for tabelle in AGGREGATE:
        try:
            werte[tabelle] = con.execute(
                f"select count(*) from {tabelle}").fetchone()[0]
        except sqlite3.Error:
            # Eine fehlende Tabelle ist eine Aussage, kein Absturz.
            werte[tabelle] = -1
    return werte


def _sha256(pfad: Path) -> str:
    h = hashlib.sha256()
    with pfad.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def main() -> int:
    if len(sys.argv) != 2 or not sys.argv[1].strip():
        print("Aufruf: contacts-backup.py <grund>", file=sys.stderr)
        return 2
    grund = sys.argv[1].strip()

    if not DB.is_file():
        print(f"Keine Datenbank unter {DB}", file=sys.stderr)
        return 3

    stempel = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    ordner = ZIEL / stempel
    ordner.mkdir(parents=True, exist_ok=True)
    os.chmod(ZIEL.parent, 0o700)
    os.chmod(ZIEL, 0o700)
    os.chmod(ordner, 0o700)
    kopie = ordner / "jarvis.db"

    # ── Kopie über die Backup-API: konsistent auch bei offener WAL ──────────
    quelle = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    vorher = _zaehle(quelle)
    ziel = sqlite3.connect(kopie)
    with ziel:
        quelle.backup(ziel)
    ziel.close()
    quelle.close()
    os.chmod(kopie, 0o600)

    # ── Recovery-Weg belegen: die KOPIE wird geprüft und ausgezählt ─────────
    pruef = sqlite3.connect(f"file:{kopie}?mode=ro", uri=True)
    integritaet = pruef.execute("PRAGMA integrity_check").fetchone()[0]
    nachher = _zaehle(pruef)
    pruef.close()

    lesbar = integritaet == "ok" and nachher == vorher

    bericht = {
        "reason": grund,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_size_bytes": DB.stat().st_size,
        "backup_path_mode": oct(kopie.stat().st_mode & 0o777),
        "backup_dir_mode": oct(ordner.stat().st_mode & 0o777),
        "backup_sha256": _sha256(kopie),
        "integrity_check": integritaet,
        "aggregates_source": vorher,
        "aggregates_backup": nachher,
        # Der Recovery-Weg gilt als belegt, wenn die Sicherung mechanisch
        # lesbar ist UND denselben Bestand trägt wie die Quelle.
        "restore_path_verified": lesbar,
    }
    berichtdatei = ordner / "backup-record.json"
    berichtdatei.write_text(json.dumps(bericht, indent=2, sort_keys=True),
                            encoding="utf-8")
    os.chmod(berichtdatei, 0o600)

    print(json.dumps(bericht, indent=2, sort_keys=True))
    if not lesbar:
        print("BACKUP NICHT BELEGT — Integritaet oder Aggregate weichen ab",
              file=sys.stderr)
        return 1
    print(f"BACKUP OK: {ordner}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
