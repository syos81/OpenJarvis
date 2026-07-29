"""Abgleich nach `outcome_unknown` — der einzige Weg aus dem Zwischenzustand.

Der verbindliche Ablauf (Plan §7.2, 11 §4/§5):

1. Der Schreibaufruf wurde **möglicherweise** ausgeführt.
2. Die Antwort war nicht eindeutig ⇒ Mutation steht auf `outcome_unknown`.
3. **Kein automatischer Retry.** Die Outbox liefert solche Einträge nie mehr.
4. Der Abgleich **liest** den Zielzustand — er schreibt nie.
5. Beobachtung gegen erwarteten Effekt:
   * eindeutig angewandt   ⇒ `succeeded`
   * eindeutig nicht angewandt ⇒ `failed` (neu freizugeben, nicht zu wiederholen)
   * mehrdeutig            ⇒ `manual_decision_required`

**Für `create` gilt eine schärfere Regel:** Es wird **nie** nach einem Namen
gesucht. Zugeordnet wird ausschließlich über einen belegten stabilen Bezug —
die vom Provider gemeldete Identität oder den Transaktionsautor-Marker. Fehlt
beides, ist der Fall mehrdeutig und ein Mensch entscheidet. Eine Namenssuche
würde einen fremden Kontakt treffen können; das ist ausgeschlossen.
"""

from __future__ import annotations

from typing import Any, Protocol

from personaljarvis.base.audit import AuditStage, AuditTrail
from personaljarvis.base.outbox import ExternalActionOutbox
from personaljarvis.contacts.application.errors import (
    MutationNotExecutable,
    MutationNotFound,
)
from personaljarvis.contacts.application.models import (
    ReconcileResult,
    ReconcileVerdict,
)
from personaljarvis.contacts.application.mutation_service import (
    MODULE,
    SUBJECT_TYPE,
    ContactsMutationService,
    MutationState,
)
from personaljarvis.contacts.domain.models import utc_now

__all__ = ["ReconcileObservation", "ReconcileReader", "ContactsReconcileService"]


class ReconcileObservation:
    """Was am Provider beobachtet wurde — ausschließlich lesend erhoben."""

    def __init__(self, *, exists: bool | None,
                 provider_identifier: str | None = None,
                 fields: dict[str, Any] | None = None,
                 transaction_author: str | None = None,
                 ambiguous: bool = False) -> None:
        self.exists = exists
        self.provider_identifier = provider_identifier
        self.fields = fields or {}
        self.transaction_author = transaction_author
        self.ambiguous = ambiguous


class ReconcileReader(Protocol):
    """Nur-Lese-Zugriff für den Abgleich.

    In Gate C ist das eine Fake-Bridge. Sie darf **nichts** schreiben.
    """

    def observe(self, *, command: str, provider_identifier: str | None,
                expected_fields: dict[str, Any],
                idempotency_key: str) -> ReconcileObservation: ...


class ContactsReconcileService:
    """Löst `outcome_unknown` auf — durch Lesen, nie durch Wiederholen."""

    def __init__(self, persistence, reader: ReconcileReader) -> None:
        self._persistence = persistence
        self._reader = reader

    def pending(self) -> tuple[str, ...]:
        """Mutationen, die auf einen Abgleich warten."""
        with self._persistence.unit_of_work() as uow:
            rows = uow.execute(
                "SELECT mutation_id FROM contacts_mutations WHERE state IN "
                "(?, ?) ORDER BY created_at, mutation_id",
                (MutationState.OUTCOME_UNKNOWN,
                 MutationState.RECONCILE_REQUIRED)).fetchall()
            return tuple(r["mutation_id"] for r in rows)

    def reconcile(self, mutation_id: str) -> ReconcileResult:
        # ── Phase A: Vorgang laden, Abgleich anmelden ──────────────────────
        with self._persistence.unit_of_work() as uow:
            zeile = ContactsMutationService._require_row(uow, mutation_id)
            if zeile["state"] not in MutationState.NEEDS_RECONCILE:
                raise MutationNotExecutable(
                    f"Mutation ist '{zeile['state']}' und braucht keinen Abgleich")
            payload = ContactsMutationService._payload_from_row(zeile)
            AuditTrail(uow, module=MODULE).record(
                AuditStage.RECONCILE_STARTED, subject_type=SUBJECT_TYPE,
                subject_id=mutation_id, facts={"command": payload.command})
            uow.execute(
                "UPDATE contacts_mutations SET state = ? WHERE mutation_id = ?",
                (MutationState.RECONCILE_REQUIRED, mutation_id))
            outbox_id = zeile["outbox_id"]
            idempotency_key = zeile["idempotency_key"]

        # ── Phase B: lesen, ohne offene Transaktion ────────────────────────
        try:
            beobachtung = self._reader.observe(
                command=payload.command,
                provider_identifier=payload.target_provider_identifier,
                expected_fields=dict(payload.fields),
                idempotency_key=idempotency_key)
        except Exception as exc:                        # noqa: BLE001
            beobachtung = ReconcileObservation(exists=None, ambiguous=True,
                                               transaction_author=None)
            detail = type(exc).__name__
        else:
            detail = None

        verdikt, provider_id = self._judge(payload, beobachtung)

        # ── Phase C: festschreiben ─────────────────────────────────────────
        with self._persistence.unit_of_work() as uow:
            audit = AuditTrail(uow, module=MODULE)
            outbox = ExternalActionOutbox(uow)
            if verdikt == ReconcileVerdict.APPLIED:
                ContactsMutationService._set_state(
                    uow, mutation_id, MutationState.SUCCEEDED,
                    outcome="succeeded", completed=True,
                    provider_identifier=provider_id)
                outbox.resolve_unknown(outbox_id, succeeded=True)
                audit.record(AuditStage.RECONCILE_SUCCEEDED,
                             subject_type=SUBJECT_TYPE, subject_id=mutation_id,
                             facts={"verdict": verdikt})
                audit.record(AuditStage.MUTATION_COMPLETED,
                             subject_type=SUBJECT_TYPE, subject_id=mutation_id,
                             facts={"outcome": "succeeded",
                                    "viaReconcile": True})
                zustand = MutationState.SUCCEEDED
            elif verdikt == ReconcileVerdict.NOT_APPLIED:
                # Eindeutig nicht ausgeführt: Endzustand. Eine Wiederholung
                # ist eine **neue** freigabepflichtige Mutation, kein Retry.
                ContactsMutationService._set_state(
                    uow, mutation_id, MutationState.FAILED, outcome="failed",
                    completed=True, error_code="not_applied")
                outbox.resolve_unknown(outbox_id, succeeded=False)
                audit.record(AuditStage.RECONCILE_SUCCEEDED,
                             subject_type=SUBJECT_TYPE, subject_id=mutation_id,
                             facts={"verdict": verdikt,
                                    "requiresNewApproval": True})
                zustand = MutationState.FAILED
            else:
                ContactsMutationService._set_state(
                    uow, mutation_id, MutationState.MANUAL_DECISION_REQUIRED,
                    error_code=detail or "ambiguous")
                audit.record(AuditStage.MANUAL_DECISION_REQUIRED,
                             subject_type=SUBJECT_TYPE, subject_id=mutation_id,
                             facts={"verdict": verdikt, "detail": detail})
                zustand = MutationState.MANUAL_DECISION_REQUIRED

            return ReconcileResult(mutation_id=mutation_id, verdict=verdikt,
                                   state=zustand,
                                   provider_identifier=provider_id,
                                   detail=detail)

    # ── Urteilsbildung ──────────────────────────────────────────────────────
    @staticmethod
    def _judge(payload, beobachtung: ReconcileObservation
               ) -> tuple[str, str | None]:
        if beobachtung.ambiguous:
            return ReconcileVerdict.AMBIGUOUS, None

        if payload.command == "create":
            # Ausschliesslich ueber einen belegten stabilen Bezug zuordnen.
            # Es gibt hier bewusst keine Namenssuche.
            if beobachtung.exists and beobachtung.provider_identifier:
                return (ReconcileVerdict.APPLIED,
                        beobachtung.provider_identifier)
            if beobachtung.exists is False:
                return ReconcileVerdict.NOT_APPLIED, None
            return ReconcileVerdict.AMBIGUOUS, None

        if payload.command == "delete":
            if beobachtung.exists is False:
                return ReconcileVerdict.APPLIED, payload.target_provider_identifier
            if beobachtung.exists is True:
                return ReconcileVerdict.NOT_APPLIED, None
            return ReconcileVerdict.AMBIGUOUS, None

        # update: Feldvergleich gegen den erwarteten Effekt.
        if beobachtung.exists is not True:
            return ReconcileVerdict.AMBIGUOUS, None
        erwartet = dict(payload.fields)
        beobachtet = beobachtung.fields
        fehlend = [k for k in erwartet if k not in beobachtet]
        if fehlend:
            return ReconcileVerdict.AMBIGUOUS, None
        if all(beobachtet[k] == v for k, v in erwartet.items()):
            return (ReconcileVerdict.APPLIED,
                    payload.target_provider_identifier)
        if all(beobachtet[k] != v for k, v in erwartet.items()):
            return ReconcileVerdict.NOT_APPLIED, None
        # Teilweise angewandt: niemals raten.
        return ReconcileVerdict.AMBIGUOUS, None
