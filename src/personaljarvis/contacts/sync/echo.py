"""Grundlage der Echo-Unterdrückung (Plan §6.4).

Ein von uns selbst geschriebener Datensatz erzeugt beim Provider ein
Änderungsereignis. Würde der Delta-Pfad es wie eine Fremdänderung behandeln,
liefe der eigene Schreibvorgang als vermeintliche Providerneuerung zurück in
den Bestand.

**Zwei Linien, nicht eine:**

1. *Primär, providerseitig:* der Sidecar setzt
   `excludedTransactionAuthors = [transactionAuthor]`. Apple filtert die
   eigenen Ereignisse dann bereits vor der Auslieferung.
2. *Sekundär, hier:* falls der Transaktionsautor einmal nicht durchschlägt —
   etwa nach einem Fremdprozess, einem Wiederherstellungsfall oder einem
   Providerwechsel —, greift diese Sperre im Kern.

Die zweite Linie kostet fast nichts und ist der Grund, warum ein einzelner
verlorener Transaktionsautor keinen Bestandsschaden auslöst.

In Gate B gibt es **keine** ausgeführten Mutationen; die Sperre ist daher
vorbereitet und wirkt, sobald Gate C schreibt. Sie ist bewusst schon jetzt im
Delta-Pfad verdrahtet und nicht erst später eingesetzt — nachträglich
eingezogene Sperren werden vergessen.
"""

from __future__ import annotations

from typing import Protocol, Sequence

from personaljarvis.contacts.domain.enums import MutationState
from personaljarvis.contacts.domain.models import ContactMutation

__all__ = ["EchoSuppressionLedger", "MutationLookup", "IN_FLIGHT_STATES"]

#: Zustände, in denen eine Mutation beim Provider bereits angekommen sein kann.
#: `OUTCOME_UNKNOWN` gehört ausdrücklich dazu: „unbekannt" heisst gerade nicht
#: „nicht geschrieben", und ein Ereignis dazu wäre möglicherweise das eigene.
IN_FLIGHT_STATES: frozenset[MutationState] = frozenset({
    MutationState.EXECUTING,
    MutationState.VERIFYING,
    MutationState.OUTCOME_UNKNOWN,
    MutationState.RECONCILE_REQUIRED,
})


class MutationLookup(Protocol):
    """Der Ausschnitt des Mutationsrepositories, den die Sperre braucht."""

    def list_requiring_reconcile(self) -> Sequence[ContactMutation]: ...


class EchoSuppressionLedger:
    """Kennt die Provider-Datensätze, die gerade von uns selbst bewegt werden.

    Der Ledger hält **keine** Kontaktdaten — nur Provider-Identifier aus
    laufenden Vorgängen.
    """

    def __init__(self, targets: Sequence[str] = ()) -> None:
        self._targets = frozenset(t for t in targets if t)

    @classmethod
    def from_mutations(
        cls, mutations: Sequence[ContactMutation]
    ) -> "EchoSuppressionLedger":
        return cls(tuple(
            m.target_provider_identifier for m in mutations
            if m.state in IN_FLIGHT_STATES and m.target_provider_identifier
        ))

    @classmethod
    def from_repository(cls, repository: MutationLookup) -> "EchoSuppressionLedger":
        """Baut die Sperre aus den Vorgängen, die noch nicht abgeschlossen sind.

        `list_requiring_reconcile` liefert genau die Vorgänge mit unbekanntem
        oder abzugleichendem Ausgang — also jene, deren Ereignis nicht sicher
        einer Fremdänderung zuzuordnen ist.
        """
        return cls.from_mutations(tuple(repository.list_requiring_reconcile()))

    def suppresses(self, provider_identifier: str | None) -> bool:
        return bool(provider_identifier) and provider_identifier in self._targets

    def __len__(self) -> int:
        return len(self._targets)

    @property
    def is_empty(self) -> bool:
        return not self._targets
