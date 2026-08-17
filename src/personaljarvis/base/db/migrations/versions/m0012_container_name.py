"""Migration 0012 — lesbarer Name des Ablageorts (Eigentümer: `contacts`).

Die produktive Vorschau muss sagen, **wohin** geschrieben wird, und zwar so,
dass ein Mensch es erkennt. Bis hierher konnte sie das nicht: Der Bestand
führte je Ablageort nur Kennung und Art. Die Kennung ist
`5EBEB6A2-…:ABAccount` — technisch eindeutig und für die Frage „ist das mein
iCloud-Konto oder der lokale Ablageort?" unbrauchbar.

Der Name existiert bereits an der Adaptergrenze: `ContainerInfo` trägt
`identifier`, `name` und `type`, der Sidecar liefert alle drei. **Der
Feldvertrag v1 bleibt dadurch unberührt** — es wird nichts Neues vom Provider
verlangt, sondern nur aufbewahrt, was er ohnehin sagt.

Die Spalte ist nullbar, und das ist eine Aussage. Bestehende Zeilen tragen
keinen Namen, bis der nächste Sync gelaufen ist. `NULL` heisst deshalb
ausdrücklich „noch nicht gelesen" und nie „hat keinen Namen": Die Vorschau
zeigt in diesem Zustand offen, dass der Name fehlt, und nennt die Kennung als
Notbehelf. Ein stiller Rückfall, der aussieht wie eine Angabe, wäre schlimmer
als eine sichtbare Lücke — er behauptete Wissen, das niemand hat.
"""

from __future__ import annotations

from personaljarvis.base.db.migrations.ledger import Migration

__all__ = ["MIGRATION"]

_STATEMENTS: tuple[str, ...] = (
    "ALTER TABLE contacts_sync_state ADD COLUMN container_name TEXT",
)

MIGRATION = Migration(
    migration_id="0012",
    module_owner="contacts",
    description="Lesbarer Name des Ablageorts fuer die produktive Vorschau",
    statements=_STATEMENTS,
    schema_version=12,
    depends_on=("0011",),
)
