"""Fehlerzustände der Mutationspipeline (Plan §7, 08 §3 Nr. 5).

Alle Meldungen sind rein technisch: **niemals** Kontaktnamen, Werte, Notizen,
Provider-Nutzlasten oder Tokens. Ein Aufrufer prüft auf Typ, nicht auf Text.
"""

from __future__ import annotations

from personaljarvis.errors import PersonalJarvisError

__all__ = [
    "MutationError",
    "InvalidCommand",
    "TargetBindingError",
    "UnifiedIdentifierNotWritable",
    "MeCardNotWritable",
    "ForeignProviderAccount",
    "ContainerNotAvailable",
    "RevisionConflict",
    "MutationNotFound",
    "MutationNotExecutable",
    "AlreadySettled",
    "MutationAlreadyPending",
    "ReconcileAmbiguous",
    "CapabilityNotDeclared",
    "DeleteBackupMissing",
    "DeleteBackupUnverified",
]


class MutationError(PersonalJarvisError):
    """Wurzel aller Mutationsfehler."""


class WriteQuotaExhausted(MutationError):
    """Das Kontingent dieser Schreibfreigabe ist aufgebraucht.

    Kein Fehler im Vorgang: Die Mutation ist gueltig, vorbereitet und
    freigegeben. Aufgebraucht ist der Rahmen, den **eine** Aktivierung traegt.
    Ein neuer entsteht nur, wenn der Eigentuemer die Freigabe ausschaltet und
    erneut erteilt — im Produkt mit Systemauthentifizierung. Es gibt bewusst
    keinen Ruecksetzweg; er waere genau der Weg, den ein Agent ginge.
    """


class DeleteBackupMissing(MutationError):
    """Fuer diese Loeschung liegt keine Sicherung des Feldstands vor.

    Kein Fehler im Vorgang, sondern die fehlende Voraussetzung: Geloescht wird
    nur, was inhaltlich wiederherstellbar ist. Der Vorgang bleibt freigegeben
    und laesst sich erneut ausfuehren, sobald die Sicherung steht.
    """


class DeleteBackupUnverified(MutationError):
    """Es gibt eine Sicherung, aber sie traegt diese Loeschung nicht.

    Sie fehlt nicht — sie ist nicht nachweislich **diese**: falscher Vertrag,
    andere Mutation, anderer Container, andere Providerkennung, anderer
    Vorzustandsdigest, fehlende Werte oder falsche Rechte. Eine Sicherung, die
    zu etwas anderem gehoert, ist schlimmer als keine, weil sie wie eine
    aussieht.
    """


class InvalidCommand(MutationError):
    """Der Command ist unvollständig oder in sich widersprüchlich."""


class TargetBindingError(MutationError):
    """Das Ziel ist nicht eindeutig und stabil benannt.

    Ein Name, eine E-Mail, eine Nummer oder ein Suchergebnis ist **niemals**
    ein Ziel (Plan §7.1).
    """


class UnifiedIdentifierNotWritable(TargetBindingError):
    """Der `unifiedIdentifier` ist belegt instabil und nie Schreibziel."""


class MeCardNotWritable(MutationError):
    """Die Me-Karte ist in v1 schreibgeschützt (Plan §7.3)."""


class ForeignProviderAccount(MutationError):
    """Das Ziel gehört einem anderen Providerkonto."""


class ContainerNotAvailable(MutationError):
    """Der gewünschte Container existiert nicht (mehr) — Fehler **vor** dem Send."""


class RevisionConflict(MutationError):
    """Die erwartete Revision stimmt nicht mehr — kein stilles Überschreiben."""


class MutationNotFound(MutationError):
    """Die Mutation existiert nicht."""


class MutationNotExecutable(MutationError):
    """Die Mutation ist in einem Zustand, der keine Ausführung erlaubt."""


class MutationAlreadyPending(MutationError):
    """Für dieselbe fachliche Aktion ist bereits ein Vorgang offen.

    Kein Fehler des Aufrufers, sondern eine Weiche: Der bestehende Vorgang ist
    freigabepflichtig und scharf; ein zweiter daneben hiesse, dass der
    Eigentuemer zweimal freigibt und einmal meint (§8 D). Die Kennung des
    offenen Vorgangs gehoert deshalb in den Fehler — sonst muesste die
    Oberflaeche raten, worauf sie zeigen soll.
    """

    def __init__(self, message: str, *, mutation_id: str,
                 state: str) -> None:
        super().__init__(message)
        self.mutation_id = mutation_id
        self.state = state


class AlreadySettled(MutationError):
    """Die Mutation ist abgeschlossen; ein zweiter Send findet nicht statt."""


class ReconcileAmbiguous(MutationError):
    """Der Abgleich war nicht eindeutig — es entscheidet ein Mensch."""


class CapabilityNotDeclared(MutationError):
    """Der Provider hat die verlangte Fähigkeit nicht deklariert."""
