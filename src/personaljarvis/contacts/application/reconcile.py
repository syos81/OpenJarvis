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
die vom Provider gemeldete Identität. Fehlt sie, ist der Fall mehrdeutig und
ein Mensch entscheidet. Eine Namenssuche würde einen fremden Kontakt treffen
können; das ist ausgeschlossen.

**Warum es keinen Transaktionsautor-Bezug gibt** (SDK-Befund, macOS 12–13):
`CNChangeHistoryFetchRequest` kennt nur `excludedTransactionAuthors`; ein
`includedTransactionAuthors` existiert nicht, und `CNChangeHistoryEvent` trägt
keinen Autor. Über die öffentliche API lässt sich ein Add-Ereignis deshalb
nicht dem eigenen Schreibvorgang zuordnen. Diese Grenze wird hier nicht
umgangen, sondern getragen: ein `create` mit verlorener Antwort endet bei
`manual_decision_required`.

**Der Sonderfall `provider_applied_pending_reconcile`** ist kein Urteilsfall.
Dort ist die Providerwirkung bereits bewiesen und nur der lokale Spiegel
offen; der Abgleich holt ihn nach, statt etwas zu beurteilen.
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
                 ambiguous: bool = False, readback=None) -> None:
        self.exists = exists
        self.provider_identifier = provider_identifier
        self.fields = fields or {}
        self.transaction_author = transaction_author
        self.ambiguous = ambiguous
        #: Der gelesene Providerdatensatz, falls vorhanden. Er ist die
        #: Providerwahrheit für eine nachzuholende lokale Nachführung — genau
        #: dieselbe Quelle wie ein Read-back nach dem Schreiben.
        self.readback = readback


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
            nur_lokal = (zeile["state"]
                         in MutationState.PENDING_LOCAL_CATCHUP)
            AuditTrail(uow, module=MODULE).record(
                AuditStage.RECONCILE_STARTED, subject_type=SUBJECT_TYPE,
                subject_id=mutation_id, facts={"command": payload.command,
                                               "localCatchupOnly": nur_lokal})
            if not nur_lokal:
                uow.execute(
                    "UPDATE contacts_mutations SET state = ? "
                    "WHERE mutation_id = ?",
                    (MutationState.RECONCILE_REQUIRED, mutation_id))
            outbox_id = zeile["outbox_id"]
            idempotency_key = zeile["idempotency_key"]
            # Bei `create` steht die Identitaet erst nach dem Lauf fest und
            # liegt in der Spalte, nicht in der Nutzlast.
            ziel_kennung = (zeile["target_provider_identifier"]
                            or payload.target_provider_identifier)

        if nur_lokal:
            return self._nur_lokal_nachfuehren(mutation_id, ziel_kennung,
                                               idempotency_key, payload)

        # ── Phase B: lesen, ohne offene Transaktion ────────────────────────
        try:
            beobachtung = self._reader.observe(
                command=payload.command,
                provider_identifier=ziel_kennung,
                expected_fields=dict(payload.fields),
                idempotency_key=idempotency_key)
        except Exception as exc:                        # noqa: BLE001
            beobachtung = ReconcileObservation(exists=None, ambiguous=True,
                                               transaction_author=None)
            detail = type(exc).__name__
        else:
            detail = None

        verdikt, provider_id = self._judge(payload, beobachtung)
        rueckgabe = getattr(beobachtung, "readback", None)

        # Eine angewandte **Neuanlage** ist mit dem Urteil noch nicht fertig:
        # es gibt den Kontakt beim Provider, aber lokal noch nicht. Sie geht
        # deshalb ueber denselben Weg wie ein Lauf, der eben geschrieben hat —
        # Zwischenlage, dann Nachfuehrung, dann erst `succeeded` (ADR-0025 §5).
        if (verdikt == ReconcileVerdict.APPLIED
                and payload.command == "create"):
            return self._create_nachfuehren(mutation_id, provider_id,
                                            rueckgabe, outbox_id)

        # ── Phase C: festschreiben ─────────────────────────────────────────
        with self._persistence.unit_of_work() as uow:
            audit = AuditTrail(uow, module=MODULE)
            outbox = ExternalActionOutbox(uow)
            if verdikt == ReconcileVerdict.APPLIED:
                # Nur `update` und `delete` erreichen diesen Zweig; beide sind
                # nicht implementiert (ADR-0025 §9) und aendern am lokalen
                # Bestand nichts, was hier nachzufuehren waere.
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

    # ── Angewandte Neuanlage: Beleg festschreiben, dann nachführen ─────────
    def _create_nachfuehren(self, mutation_id: str, provider_id: str | None,
                            rueckgabe, outbox_id: str) -> ReconcileResult:
        """Schliesst eine per Abgleich belegte Neuanlage vollständig ab.

        Der Abgleich hat den Kontakt beim Provider gefunden — damit ist die
        Wirkung bewiesen, aber lokal steht noch nichts. Früher setzte dieser
        Weg direkt `succeeded`; der Kontakt fehlte dann im kanonischen
        Bestand, und weil die Echo-Unterdrückung das eigene Add-Ereignis
        herausfiltert, wäre er erst beim nächsten Voll-Diff aufgetaucht.

        Der Ablauf ist deshalb derselbe wie nach einem eigenen Schreiblauf:
        erst der Beleg (C1), dann die Nachführung (C2), dann `succeeded`.

        **Ohne vollständigen Read-back wird nichts abgeschlossen.** Es wird
        weder geraten noch aus Nutzlast oder Vorschau ein Providerzustand
        erfunden — der Vorgang endet bei einer menschlichen Entscheidung. Ein
        zweiter Provideraufruf findet in keinem Fall statt.
        """
        from personaljarvis.contacts.application.field_contract import (
            project_bridge_contact,
            readback_digest,
        )

        if not provider_id or rueckgabe is None:
            with self._persistence.unit_of_work() as uow:
                ContactsMutationService._set_state(
                    uow, mutation_id, MutationState.MANUAL_DECISION_REQUIRED,
                    error_code="readback_missing")
                AuditTrail(uow, module=MODULE).record(
                    AuditStage.MANUAL_DECISION_REQUIRED,
                    subject_type=SUBJECT_TYPE, subject_id=mutation_id,
                    facts={"verdict": ReconcileVerdict.AMBIGUOUS,
                           "detail": "readback_missing"})
            return ReconcileResult(
                mutation_id=mutation_id, verdict=ReconcileVerdict.AMBIGUOUS,
                state=MutationState.MANUAL_DECISION_REQUIRED,
                detail="readback_missing")

        # C1 — Providerwirkung und Beleg festschreiben.
        with self._persistence.unit_of_work() as uow:
            ContactsMutationService._set_state(
                uow, mutation_id,
                MutationState.PROVIDER_APPLIED_PENDING_RECONCILE,
                provider_identifier=provider_id,
                readback_digest=readback_digest(
                    project_bridge_contact(rueckgabe)))
            ExternalActionOutbox(uow).resolve_unknown(outbox_id, succeeded=True)
            AuditTrail(uow, module=MODULE).record(
                AuditStage.RECONCILE_SUCCEEDED, subject_type=SUBJECT_TYPE,
                subject_id=mutation_id,
                facts={"verdict": ReconcileVerdict.APPLIED,
                       "viaReconcile": True})

        # C2 — kanonische Nachführung aus **diesem** Read-back.
        ergebnis = ContactsMutationService(
            self._persistence, None).finalize_pending(mutation_id,
                                                      readback=rueckgabe)
        return ReconcileResult(
            mutation_id=mutation_id, verdict=ReconcileVerdict.APPLIED,
            state=ergebnis.state, provider_identifier=provider_id)

    # ── Sonderfall: nur der lokale Spiegel fehlt ────────────────────────────
    def _nur_lokal_nachfuehren(self, mutation_id: str,
                               ziel_kennung: str | None,
                               idempotency_key: str,
                               payload) -> ReconcileResult:
        """Holt die lokale Nachführung nach — ohne jedes Urteil.

        Die Providerwirkung ist bewiesen; es gibt nichts zu beurteilen. Zuerst
        wird versucht, ohne Providerkontakt auszukommen (der Beleg
        `readback_digest` erlaubt das, wenn Entwurf und Providerzustand
        identisch sind). Erst wenn das nicht trägt, wird **gelesen** — nie
        geschrieben.
        """
        dienst = ContactsMutationService(self._persistence, None)
        try:
            ergebnis = dienst.finalize_pending(mutation_id)
        except MutationNotExecutable:
            beobachtung = self._reader.observe(
                command=payload.command, provider_identifier=ziel_kennung,
                expected_fields=dict(payload.fields),
                idempotency_key=idempotency_key)
            rueckgabe = getattr(beobachtung, "readback", None)
            if beobachtung.exists is not True or rueckgabe is None:
                with self._persistence.unit_of_work() as uow:
                    AuditTrail(uow, module=MODULE).record(
                        AuditStage.MANUAL_DECISION_REQUIRED,
                        subject_type=SUBJECT_TYPE, subject_id=mutation_id,
                        facts={"verdict": ReconcileVerdict.AMBIGUOUS,
                               "detail": "local_catchup_without_provider_state"})
                return ReconcileResult(
                    mutation_id=mutation_id,
                    verdict=ReconcileVerdict.AMBIGUOUS,
                    state=MutationState.PROVIDER_APPLIED_PENDING_RECONCILE,
                    detail="local_catchup_pending")
            ergebnis = dienst.finalize_pending(mutation_id, readback=rueckgabe)

        with self._persistence.unit_of_work() as uow:
            AuditTrail(uow, module=MODULE).record(
                AuditStage.RECONCILE_SUCCEEDED, subject_type=SUBJECT_TYPE,
                subject_id=mutation_id,
                facts={"verdict": ReconcileVerdict.APPLIED,
                       "localCatchupOnly": True})
        return ReconcileResult(
            mutation_id=mutation_id, verdict=ReconcileVerdict.APPLIED,
            state=ergebnis.state,
            provider_identifier=ergebnis.provider_identifier)

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
