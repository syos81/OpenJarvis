"""Kanonische Bestandsaggregate für Abnahmeberichte — ausschliesslich lesend.

Anlass (2026-08-03): Ein Abnahmebericht meldete „offene Tombstones: 116",
weil er schlicht `SELECT COUNT(*) FROM contacts_tombstones` zählte. Die
Tabelle ist aber eine **Historie**: Sie behält jede je gesetzte
Grabsteinzeile, auch nachdem ein Wiederherstellungslauf sie abgeschlossen
hat. Offen ist eine Zeile nur, solange ihr `reason` nicht der
Abschlussgrund `RECONCILED_REASON` ist — genau so zählt es der produktive
Wiederherstellungsdienst (`ContactsRecoveryService._offene_tombstones`).

Damit Bericht und Produktivcode nicht auseinanderdriften, borgt dieses
Modul die Definition direkt von dort, statt sie zu wiederholen.

Zwei Dinge heissen im Schema „Tombstone" und dürfen nie verwechselt werden:

* `contacts.is_tombstone` — die **Kontaktzeile** selbst gilt als gelöscht.
* `contacts_tombstones` — der **Provider-Löschnachweis** je
  `(provider_account_id, provider_identifier)`, als Historie geführt.

Dieses Modul schreibt nichts, migriert nichts und öffnet keine Verbindung
selbst; es bekommt eine bestehende und stellt ausschliesslich
`SELECT`-Abfragen.
"""

from __future__ import annotations

import sqlite3
from dataclasses import asdict, dataclass

from personaljarvis.contacts.sync.recovery import RECONCILED_REASON

__all__ = ["Bestandsaggregate", "bestandsaggregate", "TERMINALE_MUTATIONSZUSTAENDE"]

#: Zustände, aus denen kein weiterer Sendeversuch mehr folgt.
TERMINALE_MUTATIONSZUSTAENDE: tuple[str, ...] = (
    "succeeded",
    "failed",
    "failed_before_send",
    "rejected",
    "expired",
    "cancelled",
    "manually_resolved_not_applied",
)


@dataclass(frozen=True, slots=True)
class Bestandsaggregate:
    """Zählwerte eines Kontaktbestands. Keine Kontaktinhalte, nur Zahlen."""

    aktive_kontakte: int
    getombstonete_kontakte: int
    externe_identitaeten: int
    #: Alle je gesetzten Grabsteinzeilen — Historie, nicht „offen".
    tombstone_zeilen_gesamt: int
    #: Die einzige Zahl, die „aktive/offene Tombstones" bedeutet.
    offene_tombstones: int
    abgeschlossene_tombstones: int
    mutationen_gesamt: int
    mutationen_terminal: int
    freigaben: int
    audit_ereignisse: int
    sync_laeufe: int

    def as_dict(self) -> dict[str, int]:
        return asdict(self)


def bestandsaggregate(
    conn: sqlite3.Connection, *, provider_account_id: str | None = None,
) -> Bestandsaggregate:
    """Liest die kanonischen Zählwerte.

    `provider_account_id` schränkt die Tombstone-Zählung auf ein Konto ein —
    so zählt auch der Wiederherstellungsdienst. Ohne Angabe werden alle
    Konten summiert.
    """
    def zaehle(sql: str, *werte: object) -> int:
        zeile = conn.execute(sql, werte).fetchone()
        return int(zeile[0]) if zeile else 0

    if provider_account_id is None:
        wo, args = "", ()
    else:
        wo, args = " AND provider_account_id = ?", (provider_account_id,)

    platzhalter = ",".join("?" * len(TERMINALE_MUTATIONSZUSTAENDE))
    return Bestandsaggregate(
        aktive_kontakte=zaehle(
            "SELECT COUNT(*) FROM contacts "
            "WHERE is_tombstone = 0 AND deleted_at IS NULL"),
        getombstonete_kontakte=zaehle(
            "SELECT COUNT(*) FROM contacts WHERE is_tombstone = 1"),
        externe_identitaeten=zaehle(
            "SELECT COUNT(*) FROM contact_external_ids"),
        tombstone_zeilen_gesamt=zaehle(
            f"SELECT COUNT(*) FROM contacts_tombstones WHERE 1 = 1{wo}", *args),
        offene_tombstones=zaehle(
            f"SELECT COUNT(*) FROM contacts_tombstones WHERE reason != ?{wo}",
            RECONCILED_REASON, *args),
        abgeschlossene_tombstones=zaehle(
            f"SELECT COUNT(*) FROM contacts_tombstones WHERE reason = ?{wo}",
            RECONCILED_REASON, *args),
        mutationen_gesamt=zaehle("SELECT COUNT(*) FROM contacts_mutations"),
        mutationen_terminal=zaehle(
            f"SELECT COUNT(*) FROM contacts_mutations "
            f"WHERE state IN ({platzhalter})", *TERMINALE_MUTATIONSZUSTAENDE),
        freigaben=zaehle("SELECT COUNT(*) FROM personal_approvals"),
        audit_ereignisse=zaehle("SELECT COUNT(*) FROM personal_audit_log"),
        sync_laeufe=zaehle("SELECT COUNT(*) FROM contacts_sync_audit"),
    )
