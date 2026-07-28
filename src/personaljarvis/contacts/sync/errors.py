"""Fehlerzustände der Sync-Pipeline (Plan §6, 11 §3).

Alle Meldungen sind rein technisch: **niemals** Kontaktnamen, Werte,
Provider-Identifier oder Cursor-Token. Ein Aufrufer prüft auf Typ, nicht auf
Zeichenketten.
"""

from __future__ import annotations

from personaljarvis.errors import PersonalJarvisError

__all__ = [
    "SyncError",
    "AuthorizationRequired",
    "IncompleteEnumeration",
    "KeySetVersionChanged",
    "CursorRejected",
    "FullDiffRequired",
    "UnknownChangeEvent",
]


class SyncError(PersonalJarvisError):
    """Wurzel aller Sync-Fehler."""


class AuthorizationRequired(SyncError):
    """Der Provider ist nicht autorisiert; es wird **nichts** angefordert.

    Die Autorisierung ist eine ausdrückliche Nutzeraktion (Plan §8) und wird
    von der Sync-Pipeline niemals selbst ausgelöst.
    """


class IncompleteEnumeration(SyncError):
    """Eine Enumeration ohne Abschlussmarker oder mit Zählabweichung.

    **Verbindliche Folge (Plan §6.1/§6.3):** Der Lauf wird verworfen. Es
    entsteht keine Löschmenge, kein Tombstone, kein neuer Cursor und kein
    Teil-Commit.
    """


class KeySetVersionChanged(SyncError):
    """Der Schlüsselsatz des Providers hat gewechselt.

    Ein Wechsel entwertet den Cursor: der nächste Lauf muss ein Voll-Diff sein.
    """


class CursorRejected(SyncError):
    """Der gespeicherte Cursor wurde vom Provider abgelehnt (ungültig/abgelaufen)."""


class FullDiffRequired(SyncError):
    """Der Delta-Pfad ist nicht mehr tragfähig; ein Voll-Diff ist nötig.

    Das ist **kein** Datenfehler: `dropEverything` ist ein legitimes
    Resync-Signal (Plan §6.2).
    """


class UnknownChangeEvent(SyncError):
    """Ein unbekannter Ereignistyp — fail-closed.

    Der Lauf wird abgebrochen statt geraten; der nächste Lauf entscheidet
    kontrolliert über einen Voll-Diff.
    """
