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
    "SuspiciousEmptyEnumeration",
    "TransientEmptySnapshot",
    "DeleteBasisInvalid",
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


class SuspiciousEmptyEnumeration(SyncError):
    """Ein zuvor gefüllter Container liefert plötzlich **null** Datensätze.

    Der Provider meldet dabei `complete=true` — genau wie bei einem echt
    geleerten Adressbuch. Beides ist an der Antwort nicht unterscheidbar, und
    die falsche Deutung ist teuer: sie löscht den gesamten lokalen Bestand.

    Deshalb fail-closed. Ein einzelnes widersprüchliches Null-Ergebnis ist
    **kein** Löschbeleg. Ein tatsächlich geleertes Adressbuch bleibt abbildbar,
    aber nur über eine ausdrückliche Bestätigung (`confirm_empty`), nie als
    Nebenwirkung eines gewöhnlichen Laufs.

    Am 2026-07-30 hat genau dieser Fall 116 Kontakte lokal auf gelöscht
    gesetzt: derselbe Container lieferte vier Minuten nach einem erfolgreichen
    Import 0 Datensätze mit `complete=true`.
    """


class TransientEmptySnapshot(SyncError):
    """Die erste Enumeration war leer, die Gegenprobe nicht.

    Der Provider hat sich innerhalb eines Laufs widersprochen. Beide Antworten
    können nicht gleichzeitig stimmen, und welche die richtige ist, lässt sich
    nicht entscheiden — also wird keine benutzt. Der Lauf endet ohne Wirkung,
    der nächste ausdrückliche Lauf beginnt auf klarer Grundlage.

    Ausdrücklich **kein** stilles Fortsetzen mit dem zweiten Ergebnis: ein
    Bestand, der auf einer widersprüchlichen Messung beruht, ist keine
    Verbesserung gegenüber gar keinem Lauf.
    """


class DeleteBasisInvalid(SyncError):
    """Die Löschbasis des Providerkontos ist nicht belastbar.

    Löschungen entstehen nur, wenn **jeder erwartete Container** vollständig
    und unverdächtig aufgezählt wurde. Fällt einer aus, ist die Abwesenheit
    eines Datensatzes nicht mehr beweisbar — er könnte im ausgefallenen
    Container liegen. Der Lauf endet dann ohne Löschmenge.
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
