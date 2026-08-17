"""Das Kontingent einer Schreibfreigabe.

**Wogegen es steht.** Die Belegpflicht macht jede einzelne Freigabe zu einer
Eigentümerhandlung. Sie sagt aber nichts darüber, **wie viele** Handlungen eine
einzige Aktivierung tragen darf. Am 2026-08-17 gemessen: unter einer Freigabe
liefen 25 von 25 Mutationen durch, ohne Begrenzung. Standing Write bedeutet
Einzelobjekt-Schreiben — nicht die Freigabe einer beliebig grossen
Mutationsklasse. Das Kontingent ist die Zahl dazu.

**Was gezählt wird.** Ausschliesslich Versuche, die den finalen
Mutationspunkt erreichen: nach bestandener Vorprüfung, im selben Schritt, in
dem die Freigabe verbraucht und der Sendebeginn protokolliert wird. Eine
Vorschau kostet nichts. Eine abgebrochene Freigabe kostet nichts. Eine an der
Vorprüfung gescheiterte Mutation kostet nichts — sie hat den Provider nie
erreicht.

**Warum ein Wiederholungsversuch nichts kostet.** Gezählt werden nicht
Ereignisse, sondern **Mutationen**: eine Zeile je Aktivierung und Mutation, mit
dem Primärschlüssel als Idempotenz. Ein technischer Retry derselben Mutation
trifft dieselbe Zeile. Das ist keine Regel, die jemand einhalten muss, sondern
eine, die das Schema erzwingt.

**Woran eine Aktivierung hängt.** Am Fingerabdruck der geltenden
Freigabeurkunde. Nimmt der Eigentümer sie zurück und erteilt sie neu — was im
Produkt eine Systemauthentifizierung verlangt —, entsteht eine andere Urkunde
und damit ein frisches Kontingent. Es gibt bewusst **keine** Funktion, die
einen Zähler zurücksetzt: Ein Rücksetzweg wäre genau der Weg, den ein Agent
gehen würde.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from personaljarvis.base.db.unit_of_work import UnitOfWork
from personaljarvis.contacts.application.write_release import WriteRelease

__all__ = [
    "QUOTA_PER_ACTIVATION",
    "QuotaState",
    "activation_id",
    "claim_quota",
    "quota_state",
]

#: Wie viele beanspruchte Mutationen eine Aktivierung trägt. Eigentümerentscheid
#: vom 2026-08-17.
QUOTA_PER_ACTIVATION = 10


@dataclass(frozen=True, slots=True)
class QuotaState:
    """Der Stand einer Aktivierung — für Anzeige und Entscheidung dasselbe."""

    used: int
    limit: int

    @property
    def remaining(self) -> int:
        return max(0, self.limit - self.used)

    @property
    def exhausted(self) -> bool:
        return self.used >= self.limit

    def als_text(self) -> str:
        """Der Satz, den der Eigentümer liest."""
        if self.exhausted:
            return (f"{self.used} von {self.limit} verwendet – erneut "
                    "freigeben erforderlich")
        return f"{self.remaining} von {self.limit} Schreibvorgängen verfügbar"


def activation_id(freigabe: WriteRelease | None) -> str | None:
    """Fingerabdruck der geltenden Urkunde — oder `None` ohne Freigabe.

    Bewusst über den **Inhalt** der Urkunde und nicht über eine erzeugte
    Kennung: Eine erzeugte Kennung müsste irgendwo gespeichert werden, und
    dieser Ort wäre wieder etwas, das man ändern kann. Ändert sich die Urkunde,
    ändert sich der Abdruck.
    """
    if freigabe is None:
        return None
    # Trennzeichen, damit zwei verschiedene Urkunden nicht durch
    # Verkettung denselben Text ergeben koennen.
    roh = "|".join((
        freigabe.contract, freigabe.capability, freigabe.mode,
        freigabe.expires_at or "", *sorted(freigabe.operations),
        # Der Ausstellungszeitpunkt ist der Teil, der sich beim erneuten
        # Einschalten aendert — und nur dort entsteht ein frisches Kontingent.
        getattr(freigabe, "granted_at", "") or "",
    ))
    return hashlib.sha256(roh.encode("utf-8")).hexdigest()


def quota_state(uow: UnitOfWork, aktivierung: str | None) -> QuotaState:
    """Liest den Stand. Ändert nichts."""
    if not aktivierung:
        return QuotaState(used=0, limit=QUOTA_PER_ACTIVATION)
    zeile = uow.execute(
        "SELECT COUNT(*) AS n FROM contacts_write_quota "
        "WHERE activation_id = ?", (aktivierung,)).fetchone()
    return QuotaState(used=(zeile["n"] if zeile else 0),
                      limit=QUOTA_PER_ACTIVATION)


def claim_quota(uow: UnitOfWork, aktivierung: str | None, mutation_id: str,
                *, at: str) -> QuotaState:
    """Bucht **diese** Mutation auf **diese** Aktivierung.

    Idempotent: Dieselbe Mutation ein zweites Mal kostet nichts, weil sie
    dieselbe Zeile trifft. Der zurückgegebene Stand ist der **nach** der
    Buchung — der Aufrufer entscheidet daran, ob er weitergeht.

    Ohne Aktivierung wird nichts gebucht: Dann gibt es keine Dauerfreigabe, und
    die Frage, wie viele Mutationen sie trägt, stellt sich nicht.
    """
    if not aktivierung:
        return QuotaState(used=0, limit=QUOTA_PER_ACTIVATION)
    bereits = uow.execute(
        "SELECT 1 FROM contacts_write_quota "
        "WHERE activation_id = ? AND mutation_id = ?",
        (aktivierung, mutation_id)).fetchone()
    if bereits is None:
        uow.execute(
            "INSERT OR IGNORE INTO contacts_write_quota "
            "(activation_id, mutation_id, claimed_at) VALUES (?,?,?)",
            (aktivierung, mutation_id, at))
    return quota_state(uow, aktivierung)
