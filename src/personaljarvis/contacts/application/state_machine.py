"""Der Zustandsautomat der Mutationspipeline — eine einzige Wahrheit.

Bis 2026-08-03 lagen die Übergangsregeln verstreut an ihren Aufrufstellen:
`execute` prüfte drei Wächter, `finalize_pending` einen anderen,
`reconcile` wieder einen, und `_set_state` schrieb ohne jede Prüfung. Das
funktionierte, war aber nicht **nachlesbar** — und was man nicht nachlesen
kann, kann man auch nicht gegen einen ADR prüfen (ADR-0020 §4, Lücke L5).

Hier steht die Tabelle. Alle Schreibpfade gehen durch `pruefe_uebergang`;
die Statiktests halten Python-Vorrat, SQL-CHECK, API-Schema und ADR
deckungsgleich.

Zwei Eigenschaften sind wichtiger als Vollständigkeit:

* **Nach `send_started` führt kein Weg zurück.** `executing` ist der
  Zustand, ab dem ein Provider-Send stattgefunden haben kann; von dort
  gibt es nur Vorwärtswege (angewandt / nicht angewandt / unbekannt), nie
  zurück nach `approved` oder `prepared`.
* **Terminal ist terminal.** Aus einem Endzustand führt kein Übergang
  hinaus — auch nicht in sich selbst. Ein zweiter Abschluss ist ein
  Konflikt, kein No-op auf Zustandsebene.
"""

from __future__ import annotations

__all__ = [
    "ZUSTAENDE",
    "TERMINAL",
    "NACH_SEND",
    "ERLAUBTE_UEBERGAENGE",
    "UnzulaessigerUebergang",
    "pruefe_uebergang",
    "ist_terminal",
]

#: Der vollständige Zustandsvorrat. Wortgleich mit dem CHECK der Migration
#: 0008 (`MUTATION_STATES_0008`) — ein Statiktest hält beide gleich.
ZUSTAENDE: tuple[str, ...] = (
    "prepared", "awaiting_approval", "approved", "rejected", "expired",
    "cancelled", "executing", "succeeded", "failed_before_send",
    "outcome_unknown", "provider_applied_pending_reconcile",
    "reconcile_required", "manual_decision_required",
    "manually_resolved_not_applied", "manually_resolved_applied", "failed",
)

#: Endzustände: kein Übergang hinaus, kein Claim, kein Send.
TERMINAL: frozenset[str] = frozenset({
    "succeeded", "rejected", "expired", "cancelled", "failed",
    "failed_before_send", "manually_resolved_not_applied",
    "manually_resolved_applied",
})

#: Zustände, in denen ein Provider-Send stattgefunden haben **kann**.
#: Aus ihnen ist kein Rückweg und kein zweiter Versuch zulässig.
NACH_SEND: frozenset[str] = frozenset({
    "executing", "provider_applied_pending_reconcile", "outcome_unknown",
    "reconcile_required", "manual_decision_required",
})

#: Die Übergangstabelle (ADR-0020 §4).
ERLAUBTE_UEBERGAENGE: dict[str, frozenset[str]] = {
    "prepared": frozenset({"awaiting_approval"}),
    "awaiting_approval": frozenset({
        "approved", "rejected", "expired", "cancelled",
    }),
    # Der Claim schaltet nach `executing`; ein Precheck-Fehler **vor** der
    # Auftragsausgabe endet beweisbar in `failed_before_send`.
    "approved": frozenset({"executing", "failed_before_send"}),
    "executing": frozenset({
        "provider_applied_pending_reconcile",
        "failed_before_send",
        "outcome_unknown",
    }),
    "provider_applied_pending_reconcile": frozenset({"succeeded"}),
    "outcome_unknown": frozenset({
        "reconcile_required",
        "manually_resolved_not_applied",
        "manually_resolved_applied",
    }),
    "reconcile_required": frozenset({
        "succeeded", "failed", "manual_decision_required",
    }),
    "manual_decision_required": frozenset({
        "manually_resolved_not_applied", "manually_resolved_applied",
    }),
    # Endzustände:
    "succeeded": frozenset(),
    "rejected": frozenset(),
    "expired": frozenset(),
    "cancelled": frozenset(),
    "failed": frozenset(),
    "failed_before_send": frozenset(),
    "manually_resolved_not_applied": frozenset(),
    "manually_resolved_applied": frozenset(),
}


class UnzulaessigerUebergang(RuntimeError):
    """Ein Zustandswechsel, den der Vertrag nicht kennt."""

    def __init__(self, von: str, nach: str) -> None:
        super().__init__(f"Unzulässiger Übergang: {von} → {nach}")
        self.von = von
        self.nach = nach


def ist_terminal(zustand: str) -> bool:
    return zustand in TERMINAL


def pruefe_uebergang(von: str, nach: str) -> None:
    """Wirft, wenn der Übergang nicht in der Tabelle steht."""
    if von not in ERLAUBTE_UEBERGAENGE:
        raise UnzulaessigerUebergang(von, nach)
    if nach not in ZUSTAENDE:
        raise UnzulaessigerUebergang(von, nach)
    if nach not in ERLAUBTE_UEBERGAENGE[von]:
        raise UnzulaessigerUebergang(von, nach)
