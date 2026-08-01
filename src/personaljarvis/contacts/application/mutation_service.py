"""Freigabepflichtige Mutationspipeline für Kontakte (Plan §7, 05, 10, 11).

Der Ablauf hat **drei getrennte Schritte**, und diese Trennung ist die
eigentliche Sicherung:

1. `prepare(command)` — validiert, bindet das Ziel, erzeugt Vorschau, Freigabe
   und Outbox-Eintrag in **einer** UnitOfWork. Es wird nichts gesendet.
2. Freigabe durch einen **Menschen** (`ApprovalStore.grant`).
3. `execute(mutation_id)` — beansprucht den Outbox-Eintrag, verbraucht die
   Freigabe, ruft **außerhalb der Transaktion** den Provider und schreibt das
   Ergebnis zurück.

Verbindliche Regeln, die hier durchgesetzt werden:

* **Nie über einen Namen mutieren.** `update`/`delete` verlangen die stabile
  Provider-ID; `create` einen benannten Container.
* **`expected_revision` wird vor dem Send geprüft.** Abweichung ⇒ `conflict`,
  kein stilles Überschreiben.
* **Me-Karte und unifizierter Identifier sind nie Schreibziel.**
* **Kein automatischer Retry aus `outcome_unknown`.** Aus diesem Zustand führt
  nur der Abgleich (`reconcile.py`).
* **Kein Provider-Aufruf in der Datenbanktransaktion.**
"""

from __future__ import annotations

import uuid
from typing import Protocol

from personaljarvis.base.approvals import (
    Approval,
    ApprovalState,
    ApprovalStore,
    DEFAULT_TTL_SECONDS,
)
from personaljarvis.base.audit import AuditStage, AuditTrail
from personaljarvis.base.db.unit_of_work import UnitOfWork
from personaljarvis.base.digest import canonical_json
from personaljarvis.base.outbox import ExternalActionOutbox, OutboxState
from personaljarvis.contacts.application.commands import (
    CreateContact,
    DeleteContact,
    MutationCommand,
    UpdateContact,
)
from personaljarvis.contacts.application.errors import (
    AlreadySettled,
    CapabilityNotDeclared,
    ContainerNotAvailable,
    ForeignProviderAccount,
    InvalidCommand,
    MeCardNotWritable,
    MutationNotExecutable,
    MutationNotFound,
    RevisionConflict,
)
from personaljarvis.contacts.application.models import (
    ExecutionResult,
    FieldChange,
    MutationPayload,
    MutationPreview,
    PreparedMutation,
    ProviderOutcome,
)
from personaljarvis.contacts.domain.models import utc_now

__all__ = [
    "MODULE",
    "SUBJECT_TYPE",
    "TRANSACTION_AUTHOR",
    "MutationState",
    "MutationProvider",
    "ProviderResponse",
    "ContactsMutationService",
]

MODULE = "contacts"
SUBJECT_TYPE = "contacts.mutation"

#: Autor jeder Schreiboperation — Grundlage der Echo-Unterdrückung (11 §3).
TRANSACTION_AUTHOR = "de.kluender.jarvis.contacts-bridge"


class MutationState:
    PREPARED = "prepared"
    AWAITING_APPROVAL = "awaiting_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"
    CANCELLED = "cancelled"
    EXECUTING = "executing"
    SUCCEEDED = "succeeded"
    FAILED_BEFORE_SEND = "failed_before_send"
    OUTCOME_UNKNOWN = "outcome_unknown"
    #: Beim Provider bewiesen angewandt, lokal noch nicht nachgeführt.
    PROVIDER_APPLIED_PENDING_RECONCILE = "provider_applied_pending_reconcile"
    RECONCILE_REQUIRED = "reconcile_required"
    MANUAL_DECISION_REQUIRED = "manual_decision_required"
    FAILED = "failed"

    #: Endzustände. Ein zweiter Send findet nie statt.
    #:
    #: `FAILED_BEFORE_SEND` ist bewusst terminal (Audit-Befund Gate C):
    #: es wurde nachweislich nichts gesendet, aber der Vorgang samt Vorschau
    #: und Freigabe ist verbraucht. Ein neuer Versuch ist eine **neue**
    #: freigabepflichtige Mutation — kein Retry desselben Vorgangs. Ohne
    #: diese Regel bliebe der Zustand ein Zombie: nicht terminal, nicht
    #: ausführbar, und sein Outbox-Eintrag stünde dauerhaft als fällig.
    TERMINAL = frozenset({SUCCEEDED, REJECTED, EXPIRED, CANCELLED, FAILED,
                          FAILED_BEFORE_SEND})
    #: Zustände, aus denen nur der Abgleich weiterführt — **nie** ein Send.
    #: `PROVIDER_APPLIED_PENDING_RECONCILE` gehört ausdrücklich dazu: dort ist
    #: die Providerwirkung bewiesen, ein zweiter Send legte einen zweiten
    #: Kontakt an.
    NEEDS_RECONCILE = frozenset({OUTCOME_UNKNOWN, RECONCILE_REQUIRED,
                                 PROVIDER_APPLIED_PENDING_RECONCILE})
    #: Zustand, der ausschliesslich eine **lokale** Nacharbeit braucht.
    PENDING_LOCAL_CATCHUP = frozenset({PROVIDER_APPLIED_PENDING_RECONCILE})


class ProviderResponse:
    """Antwort des Ausführungsziels — Fake-Bridge oder echte Bridge.

    Der Konstruktor erzwingt bei `SUCCEEDED` genau eines: einen
    `provider_identifier`. Ein Erfolg ohne Ziel wäre sinnlos.

    `readback` und `readback_digest` erzwingt er **nicht** — die Prüfung
    liegt nachgelagert und ist dort fail-closed: der produktive Provider
    stuft ein `applied` ohne Read-back als `outcome_unknown` ein
    (`bridge_provider._auswerten`), und `finalize_pending` verweigert die
    Nachführung ohne belegte Providerwahrheit. Ein Erfolg ohne Beleg kann
    also entstehen — er kommt nur nirgends bis `succeeded` durch.
    """

    def __init__(self, outcome: str, *, error_code: str | None = None,
                 provider_identifier: str | None = None,
                 readback=None, readback_digest: str | None = None,
                 container_identifier: str | None = None) -> None:
        if outcome not in ProviderOutcome.ALL:
            raise ValueError(f"Unbekanntes Provider-Ergebnis: {outcome}")
        if outcome == ProviderOutcome.SUCCEEDED and not provider_identifier:
            raise ValueError(
                "Ein angewandter Vorgang ohne Provider-Identifier waere ein "
                "Erfolg ohne Ziel")
        self.outcome = outcome
        self.error_code = error_code
        self.provider_identifier = provider_identifier
        #: Der zurückgelesene Providerdatensatz — die **einzige**
        #: Providerwahrheit für die lokale Nachführung.
        self.readback = readback
        self.readback_digest = readback_digest
        self.container_identifier = container_identifier


class MutationProvider(Protocol):
    """Das Ausführungsziel einer freigegebenen Mutation.

    Produktiv ist das seit ADR-0019 der Sidecar — **ausschliesslich für
    `create`**. `update` und `delete` liefern weiterhin `not_implemented`.
    """

    def apply(self, payload: MutationPayload, *, mutation_id: str,
              idempotency_key: str, approval_id: str) -> ProviderResponse: ...


class ContactsMutationService:
    """Orchestriert Vorbereitung, Freigabebindung und Ausführung."""

    def __init__(self, persistence, provider: MutationProvider, *,
                 capabilities=None,
                 approval_ttl_seconds: int = DEFAULT_TTL_SECONDS) -> None:
        self._persistence = persistence
        self._provider = provider
        self._capabilities = capabilities
        self._ttl = approval_ttl_seconds

    # ── 1. Vorbereiten ──────────────────────────────────────────────────────
    def prepare(self, command: MutationCommand) -> PreparedMutation:
        """Validiert, bindet, erzeugt Vorschau, Freigabe und Outbox-Eintrag.

        Es wird **nichts** gesendet. Ein zweiter Aufruf mit demselben
        Idempotenzschlüssel gibt denselben Vorgang zurück und legt **keine**
        zweite Mutation an.
        """
        self._require_capability(command)
        with self._persistence.unit_of_work() as uow:
            vorhanden = self._find_by_idempotency(
                uow, command.provider_account_id, command.idempotency_key)
            if vorhanden is not None:
                return self._reuse(uow, vorhanden)

            ziel = self._resolve_target(uow, command)
            payload = self._build_payload(command)
            preview = self._build_preview(uow, command, ziel)

            approval_id = command.approval_id or str(uuid.uuid4())
            approvals = ApprovalStore(uow)
            approvals.request(
                approval_id=approval_id, module=MODULE,
                subject_type=SUBJECT_TYPE, subject_id=command.mutation_id,
                risk_class="R1",
                initiation_context=command.initiation_context.value,
                actor=command.actor, correlation_id=command.correlation_id,
                payload_digest=payload.digest, preview_digest=preview.digest,
                ttl_seconds=self._ttl)

            outbox = ExternalActionOutbox(uow).enqueue(
                module=MODULE, operation=command.command_name,
                subject_type=SUBJECT_TYPE, subject_id=command.mutation_id,
                approval_id=approval_id,
                idempotency_key=command.idempotency_key,
                payload_digest=payload.digest)

            audit = AuditTrail(uow, module=MODULE)
            eintrag = audit.record(
                AuditStage.MUTATION_PREPARED, subject_type=SUBJECT_TYPE,
                subject_id=command.mutation_id,
                facts=self._facts(command, payload_digest=payload.digest))
            audit.record(
                AuditStage.APPROVAL_REQUESTED, subject_type=SUBJECT_TYPE,
                subject_id=command.mutation_id,
                facts={"approvalId": approval_id,
                       "previewDigest": preview.digest})

            self._insert_mutation(uow, command, payload=payload,
                                  preview=preview, approval_id=approval_id,
                                  outbox_id=outbox.outbox_id,
                                  audit_id=eintrag.audit_id,
                                  target_contact_id=ziel.get("contact_id"))

            return PreparedMutation(
                mutation_id=command.mutation_id, approval_id=approval_id,
                outbox_id=outbox.outbox_id,
                state=MutationState.AWAITING_APPROVAL,
                payload_digest=payload.digest, preview=preview)

    # ── 2. Freigabe (menschlich) ────────────────────────────────────────────
    def grant(self, mutation_id: str, *, decision_actor: str) -> Approval:
        with self._persistence.unit_of_work() as uow:
            zeile = self._require_row(uow, mutation_id)
            approvals = ApprovalStore(uow)
            approval = approvals.grant(zeile["approval_id"],
                                       decision_actor=decision_actor)
            uow.execute(
                "UPDATE contacts_mutations SET state = ?, approved_at = ? "
                "WHERE mutation_id = ?",
                (MutationState.APPROVED, utc_now(), mutation_id))
            AuditTrail(uow, module=MODULE).record(
                AuditStage.APPROVAL_GRANTED, subject_type=SUBJECT_TYPE,
                subject_id=mutation_id,
                facts={"approvalId": approval.approval_id,
                       "decisionActor": decision_actor})
            return approval

    def reject(self, mutation_id: str, *, decision_actor: str) -> Approval:
        return self._terminate(mutation_id, decision_actor=decision_actor,
                               approval_call="reject",
                               state=MutationState.REJECTED,
                               stage=AuditStage.APPROVAL_REJECTED)

    def cancel(self, mutation_id: str, *, decision_actor: str) -> Approval:
        return self._terminate(mutation_id, decision_actor=decision_actor,
                               approval_call="cancel",
                               state=MutationState.CANCELLED,
                               stage=AuditStage.APPROVAL_CANCELLED)

    def expire(self, mutation_id: str) -> Approval:
        return self._terminate(mutation_id, decision_actor=None,
                               approval_call="expire",
                               state=MutationState.EXPIRED,
                               stage=AuditStage.APPROVAL_EXPIRED)

    # ── 3. Ausführen ────────────────────────────────────────────────────────
    def execute(self, mutation_id: str) -> ExecutionResult:
        """Beansprucht, verbraucht die Freigabe und ruft den Provider.

        Der Provider-Aufruf liegt **außerhalb** jeder Transaktion. Vorher wird
        alles geprüft, was ohne Send prüfbar ist — jeder Fehler dort ist
        `failed_before_send` und damit gefahrlos.
        """
        # ── Phase A: beanspruchen, prüfen, Freigabe verbrauchen ─────────────
        with self._persistence.unit_of_work() as uow:
            zeile = self._require_row(uow, mutation_id)
            # Die Fähigkeit wurde bei `prepare` geprüft. Zwischen Vorbereitung
            # und Ausführung kann ein Neustart mit anderem Sidecar liegen —
            # deshalb hier erneut, bevor irgendetwas beansprucht wird.
            self._require_capability_named(zeile["command"])
            zustand = zeile["state"]
            if zustand in MutationState.TERMINAL:
                raise AlreadySettled(
                    f"Mutation ist '{zustand}'; ein zweiter Send findet nicht statt")
            if zustand in MutationState.NEEDS_RECONCILE:
                raise MutationNotExecutable(
                    "Mutation wartet auf den Abgleich; aus 'outcome_unknown' "
                    "fuehrt kein automatischer Ausfuehrungsweg")
            if zustand != MutationState.APPROVED:
                raise MutationNotExecutable(
                    f"Mutation ist '{zustand}', nicht 'approved'")

            payload = self._payload_from_row(zeile)
            outbox = ExternalActionOutbox(uow)
            eintrag, token = outbox.claim(zeile["outbox_id"])

            audit = AuditTrail(uow, module=MODULE)
            audit.record(AuditStage.EXECUTION_CLAIMED,
                         subject_type=SUBJECT_TYPE, subject_id=mutation_id,
                         facts={"outboxId": eintrag.outbox_id,
                                "attempt": eintrag.attempt_count})

            # Prüfungen vor dem Send — jeder Fehler hier ist gefahrlos.
            try:
                self._precheck(uow, zeile, payload)
            except (RevisionConflict, ContainerNotAvailable,
                    ForeignProviderAccount, MeCardNotWritable) as exc:
                code = type(exc).__name__
                outbox.mark_failed_before_send(eintrag.outbox_id, token,
                                               error_code=code)
                # Terminal: der Eintrag darf nie wieder als faellig gelistet
                # werden — ein neuer Versuch ist eine neue Mutation.
                outbox.abandon(eintrag.outbox_id, error_code=code)
                self._set_state(uow, mutation_id,
                                MutationState.FAILED_BEFORE_SEND,
                                outcome="failed", error_code=code,
                                completed=True)
                audit.record(AuditStage.FAILED_BEFORE_SEND,
                             subject_type=SUBJECT_TYPE, subject_id=mutation_id,
                             facts={"errorCode": code, "sent": False})
                return ExecutionResult(
                    mutation_id=mutation_id,
                    state=MutationState.FAILED_BEFORE_SEND, outcome="failed",
                    error_code=code, attempt_count=eintrag.attempt_count)

            ApprovalStore(uow).consume(zeile["approval_id"],
                                       payload_digest=payload.digest)
            self._set_state(uow, mutation_id, MutationState.EXECUTING,
                            execution_started=True)
            audit.record(AuditStage.PROVIDER_SEND_STARTED,
                         subject_type=SUBJECT_TYPE, subject_id=mutation_id,
                         facts={"operation": payload.command,
                                "payloadDigest": payload.digest})
            approval_id = zeile["approval_id"]
            idempotency_key = zeile["idempotency_key"]
            outbox_id = eintrag.outbox_id
            versuche = eintrag.attempt_count

        # ── Phase B: Provider-Aufruf, ohne offene Transaktion ───────────────
        try:
            antwort = self._provider.apply(
                payload, mutation_id=mutation_id,
                idempotency_key=idempotency_key, approval_id=approval_id)
        except Exception as exc:                       # noqa: BLE001
            # Eine Ausnahme aus dem Aufruf heisst: der Ausgang ist unbekannt.
            antwort = ProviderResponse(
                ProviderOutcome.OUTCOME_UNKNOWN,
                error_code=type(exc).__name__)

        # ── Phase C1: Providerergebnis festschreiben ───────────────────────
        with self._persistence.unit_of_work() as uow:
            outbox = ExternalActionOutbox(uow)
            audit = AuditTrail(uow, module=MODULE)
            audit.record(AuditStage.PROVIDER_RESULT_RECEIVED,
                         subject_type=SUBJECT_TYPE, subject_id=mutation_id,
                         facts={"outcome": antwort.outcome,
                                "errorCode": antwort.error_code})
            ergebnis = self._settle(uow, outbox, audit, mutation_id, outbox_id,
                                    token, antwort, versuche)

        if not ergebnis.pending_local_catchup:
            return ergebnis

        # ── Phase C2: kanonische Nachführung, eigene Arbeitseinheit ────────
        #
        # Bewusst **nach** C1 und in einer eigenen Transaktion: scheitert sie,
        # bleibt die bewiesene Providerwirkung festgeschrieben und sichtbar.
        # Eine gemeinsame Transaktion würde bei einem Fehler auch den Beweis
        # zurückrollen — und der Vorgang stünde wieder auf `executing`, als
        # wäre nie etwas geschehen.
        return self.finalize_pending(mutation_id, readback=antwort.readback,
                                     attempt_count=ergebnis.attempt_count)

    # ── C2: kanonische lokale Nachführung ───────────────────────────────────
    def finalize_pending(self, mutation_id: str, *, readback=None,
                         attempt_count: int = 0) -> ExecutionResult:
        """Führt den kanonischen Spiegel nach und schliesst den Vorgang ab.

        **Löst nie einen Provideraufruf aus.** Die Providerwahrheit kommt
        entweder als `readback` aus dem Lauf, der eben geschrieben hat, oder —
        bei einer Wiederholung — aus dem Entwurf, sofern `readback_digest`
        belegt, dass Entwurf und Providerzustand identisch sind. Weicht der
        Providerzustand ab und liegt kein Read-back vor, bleibt der Vorgang in
        der Zwischenlage; dann ist der Abgleich zuständig, und der liest.

        Der Aufruf ist wiederholbar: findet er den Kontakt bereits unter der
        Provider-Identität, aktualisiert er ihn, statt einen zweiten anzulegen.
        """
        with self._persistence.unit_of_work() as uow:
            zeile = self._require_row(uow, mutation_id)
            zustand = zeile["state"]
            if zustand == MutationState.SUCCEEDED:
                return ExecutionResult(
                    mutation_id=mutation_id, state=MutationState.SUCCEEDED,
                    outcome="succeeded",
                    provider_identifier=zeile["target_provider_identifier"],
                    contact_id=zeile["target_contact_id"],
                    readback_digest=zeile["readback_digest"],
                    attempt_count=zeile["attempt_count"])
            if zustand not in MutationState.PENDING_LOCAL_CATCHUP:
                raise MutationNotExecutable(
                    f"Mutation ist '{zustand}' und wartet nicht auf eine "
                    f"lokale Nachfuehrung")

            quelle = readback if readback is not None else self._aus_entwurf(zeile)
            if quelle is None:
                raise MutationNotExecutable(
                    "Der Providerzustand weicht vom Entwurf ab; die "
                    "Nachfuehrung braucht einen Abgleich mit dem Provider")

            contact_id = self._spiegeln(uow, zeile, quelle)
            self._set_state(uow, mutation_id, MutationState.SUCCEEDED,
                            outcome="succeeded", completed=True)
            uow.execute(
                "UPDATE contacts_mutations SET target_contact_id = ? "
                "WHERE mutation_id = ?", (contact_id, mutation_id))
            AuditTrail(uow, module=MODULE).record(
                AuditStage.MUTATION_COMPLETED, subject_type=SUBJECT_TYPE,
                subject_id=mutation_id,
                facts={"outcome": "succeeded", "localMirrorUpdated": True})
            return ExecutionResult(
                mutation_id=mutation_id, state=MutationState.SUCCEEDED,
                outcome="succeeded",
                provider_identifier=zeile["target_provider_identifier"],
                contact_id=contact_id, readback_digest=zeile["readback_digest"],
                attempt_count=attempt_count or zeile["attempt_count"])

    @staticmethod
    def _aus_entwurf(zeile):
        """Der Entwurf als Providerwahrheit — **nur** wenn der Beleg passt.

        `readback_digest` wurde aus dem tatsächlich zurückgelesenen Datensatz
        gebildet. Stimmt er mit dem Digest des Entwurfs überein, sind beide
        beweisbar derselbe Feldstand — dann darf der Entwurf die Nachführung
        speisen, ohne dass jemand den Provider erneut fragt. Stimmt er nicht,
        wird nichts geraten.
        """
        from personaljarvis.contacts.application.field_contract import (
            as_bridge_contact,
            parse_canonical_payload,
            readback_digest,
        )

        beleg = zeile["readback_digest"]
        kennung = zeile["target_provider_identifier"]
        if not beleg or not kennung or zeile["command"] != "create":
            return None
        payload = ContactsMutationService._payload_from_row(zeile)
        entwurf = parse_canonical_payload(payload.fields)
        if readback_digest(entwurf) != beleg:
            return None
        return as_bridge_contact(entwurf, provider_identifier=kennung)

    def _spiegeln(self, uow: UnitOfWork, zeile, quelle) -> str:
        """Schreibt den Providerdatensatz in den kanonischen Bestand.

        Es entsteht **kein** Duplikat: existiert die Provider-Identität lokal
        bereits, wird derselbe Datensatz aktualisiert. Lokale Rollen und
        Kategorien bleiben unberührt — sie gehören dem Bestand, nicht dem
        Provider.
        """
        from personaljarvis.contacts.sync.mapper import map_bridge_contact

        repos = self._persistence.repositories(uow)
        vorhanden = repos.external_ids.find_contact_id(
            zeile["provider_account_id"], quelle.provider_identifier)
        abbildung = map_bridge_contact(
            quelle, workspace_id=zeile["workspace_id"],
            provider_account_id=zeile["provider_account_id"],
            container_identifier=zeile["container_identifier"] or "",
            contact_id=vorhanden, observed_at=utc_now())
        if vorhanden is None:
            repos.contacts.add(abbildung.contact)
        else:
            repos.contacts.update(abbildung.contact)
        repos.external_ids.upsert(abbildung.contact.id,
                                  abbildung.external_identifier)
        repos.field_availability.set_for_contact(abbildung.contact.id,
                                                 abbildung.field_availability)
        return abbildung.contact.id

    # ── Erholung nach Prozessabbruch ────────────────────────────────────────
    def recover_interrupted(self) -> tuple[str, ...]:
        """Löst verwaiste Ausführungen nach einem Prozessabbruch auf.

        Eine Mutation in `executing` mit beanspruchtem Outbox-Eintrag ist die
        Spur eines Abbruchs zwischen Phase A und Phase C. Ob der Provider den
        Schreibaufruf noch erhalten hat, ist **nicht feststellbar** — die
        Audit-Stufe `provider_send_started` wurde vor dem Aufruf festgeschrieben.
        Deshalb gilt fail-closed: jeder solche Vorgang wird `outcome_unknown`
        und wartet auf den Abgleich. **Nie** wird er erneut gesendet, und nie
        wird er als `failed_before_send` eingestuft (unbekannte Phase ist nie
        „nichts gesendet").

        **`provider_applied_pending_reconcile` wird hier nicht angefasst.**
        Dort ist die Providerwirkung bewiesen; ihn auf `outcome_unknown`
        zurückzusetzen hiesse, einen Beweis gegen eine Ungewissheit zu
        tauschen. Die Abfrage unten trifft ausschliesslich `executing` — der
        Zustand bleibt sichtbar und wird über die **lokale** Nachführung
        aufgelöst, nie über einen Send.

        Ausdrücklicher Verwaltungsaufruf: darf nur laufen, wenn kein Executor
        aktiv ist (im Serve-Betrieb sichert das die Prozesssperre). Es gibt
        keinen Timer und keinen automatischen Aufruf.
        """
        erholt: list[str] = []
        with self._persistence.unit_of_work() as uow:
            rows = uow.execute(
                "SELECT m.mutation_id, m.outbox_id, o.state AS outbox_state, "
                "o.claim_token FROM contacts_mutations m "
                "JOIN personal_external_action_outbox o "
                "ON o.outbox_id = m.outbox_id WHERE m.state = ? "
                "ORDER BY m.created_at, m.mutation_id",
                (MutationState.EXECUTING,)).fetchall()
            outbox = ExternalActionOutbox(uow)
            audit = AuditTrail(uow, module=MODULE)
            for row in rows:
                if row["outbox_state"] != OutboxState.CLAIMED                         or row["claim_token"] is None:
                    continue
                outbox.mark_outcome_unknown(row["outbox_id"],
                                            row["claim_token"],
                                            error_code="interrupted")
                self._set_state(uow, row["mutation_id"],
                                MutationState.OUTCOME_UNKNOWN,
                                outcome="outcome_unknown",
                                error_code="interrupted")
                audit.record(AuditStage.OUTCOME_UNKNOWN,
                             subject_type=SUBJECT_TYPE,
                             subject_id=row["mutation_id"],
                             facts={"errorCode": "interrupted",
                                    "recovered": True,
                                    "automaticRetry": False})
                erholt.append(row["mutation_id"])
        return tuple(erholt)

    # ── Ergebnisverarbeitung ────────────────────────────────────────────────
    def _settle(self, uow, outbox, audit, mutation_id, outbox_id, token,
                antwort, versuche) -> ExecutionResult:
        if antwort.outcome == ProviderOutcome.SUCCEEDED:
            # C1 — die Providerwirkung ist bewiesen und wird sofort
            # festgeschrieben. `succeeded` ist das aber noch **nicht**: der
            # kanonische Spiegel steht noch aus. Ohne diese Trennung waere ein
            # Abbruch zwischen Provider und Spiegel von einem ungewissen
            # Ausgang nicht zu unterscheiden (ADR-0019 §5).
            outbox.mark_succeeded(outbox_id, token)
            self._set_state(uow, mutation_id,
                            MutationState.PROVIDER_APPLIED_PENDING_RECONCILE,
                            provider_identifier=antwort.provider_identifier,
                            readback_digest=antwort.readback_digest)
            return ExecutionResult(
                mutation_id=mutation_id,
                state=MutationState.PROVIDER_APPLIED_PENDING_RECONCILE,
                outcome=None,
                provider_identifier=antwort.provider_identifier,
                readback_digest=antwort.readback_digest,
                attempt_count=versuche)

        if antwort.outcome in (ProviderOutcome.REJECTED_BEFORE_SEND,
                               ProviderOutcome.FAILED_BEFORE_SEND,
                               ProviderOutcome.CONFLICT):
            code = antwort.error_code or antwort.outcome
            outbox.mark_failed_before_send(outbox_id, token, error_code=code)
            # Terminal — siehe MutationState.TERMINAL.
            outbox.abandon(outbox_id, error_code=code)
            self._set_state(uow, mutation_id,
                            MutationState.FAILED_BEFORE_SEND,
                            outcome="failed", error_code=code,
                            completed=True)
            audit.record(AuditStage.FAILED_BEFORE_SEND,
                         subject_type=SUBJECT_TYPE, subject_id=mutation_id,
                         facts={"errorCode": code, "sent": False})
            return ExecutionResult(
                mutation_id=mutation_id,
                state=MutationState.FAILED_BEFORE_SEND, outcome="failed",
                error_code=code, attempt_count=versuche)

        # outcome_unknown — möglicherweise gesendet.
        code = antwort.error_code or "outcome_unknown"
        outbox.mark_outcome_unknown(outbox_id, token, error_code=code)
        self._set_state(uow, mutation_id, MutationState.OUTCOME_UNKNOWN,
                        outcome="outcome_unknown", error_code=code)
        audit.record(AuditStage.OUTCOME_UNKNOWN, subject_type=SUBJECT_TYPE,
                     subject_id=mutation_id,
                     facts={"errorCode": code, "automaticRetry": False})
        return ExecutionResult(
            mutation_id=mutation_id, state=MutationState.OUTCOME_UNKNOWN,
            outcome="outcome_unknown", error_code=code, attempt_count=versuche)

    # ── Hilfen ──────────────────────────────────────────────────────────────
    def _require_capability(self, command: MutationCommand) -> None:
        self._require_capability_named(command.command_name)

    def _require_capability_named(self, command_name: str) -> None:
        if self._capabilities is None:
            return
        if command_name not in ("create", "update", "delete"):
            raise InvalidCommand(f"Unbekannter Command: {command_name}")
        try:
            self._capabilities.require(command_name)
        except Exception as exc:                        # noqa: BLE001
            raise CapabilityNotDeclared(str(exc)) from exc

    @staticmethod
    def _find_by_idempotency(uow: UnitOfWork, provider_account_id: str,
                             key: str):
        return uow.execute(
            "SELECT * FROM contacts_mutations WHERE provider_account_id = ? "
            "AND idempotency_key = ?", (provider_account_id, key)).fetchone()

    def _reuse(self, uow: UnitOfWork, zeile) -> PreparedMutation:
        """Derselbe Vorgang, keine zweite Mutation (Plan §7.1)."""
        payload = self._payload_from_row(zeile)
        return PreparedMutation(
            mutation_id=zeile["mutation_id"],
            approval_id=zeile["approval_id"], outbox_id=zeile["outbox_id"],
            state=zeile["state"], payload_digest=payload.digest,
            preview=MutationPreview(
                command=zeile["command"],
                target_provider_identifier=zeile["target_provider_identifier"],
                container_identifier=zeile["container_identifier"],
                target_contact_id=zeile["target_contact_id"]),
            reused=True)

    def _resolve_target(self, uow: UnitOfWork, command: MutationCommand) -> dict:
        """Bindet das Ziel an einen bekannten Datensatz — nie an einen Namen."""
        if isinstance(command, CreateContact):
            return {"contact_id": None}
        zeile = uow.execute(
            "SELECT c.id AS contact_id, c.is_me_card, e.provider_account_id "
            "FROM contact_external_ids e JOIN contacts c ON c.id = e.contact_id "
            "WHERE e.provider_identifier = ?",
            (command.target_provider_identifier,)).fetchone()
        if zeile is None:
            # Unbekanntes Ziel ist zulässig (der lokale Bestand kann älter
            # sein); geprüft wird dann erst vor dem Send.
            return {"contact_id": None}
        if zeile["provider_account_id"] != command.provider_account_id:
            raise ForeignProviderAccount(
                "Das Ziel gehoert einem anderen Providerkonto")
        if zeile["is_me_card"]:
            raise MeCardNotWritable(
                "Die Me-Karte ist in dieser Version schreibgeschuetzt")
        return {"contact_id": zeile["contact_id"]}

    @staticmethod
    def _build_payload(command: MutationCommand) -> MutationPayload:
        if isinstance(command, CreateContact):
            return MutationPayload(
                command="create",
                provider_account_id=command.provider_account_id,
                container_identifier=command.container_identifier,
                target_provider_identifier=None, expected_revision=None,
                fields=dict(command.draft.fields))
        if isinstance(command, UpdateContact):
            return MutationPayload(
                command="update",
                provider_account_id=command.provider_account_id,
                container_identifier=None,
                target_provider_identifier=command.target_provider_identifier,
                expected_revision=command.expected_revision,
                fields=dict(command.patch.fields))
        if isinstance(command, DeleteContact):
            return MutationPayload(
                command="delete",
                provider_account_id=command.provider_account_id,
                container_identifier=None,
                target_provider_identifier=command.target_provider_identifier,
                expected_revision=command.expected_revision, fields={})
        raise InvalidCommand(f"Unbekannter Command: {type(command).__name__}")

    def _build_preview(self, uow: UnitOfWork, command: MutationCommand,
                       ziel: dict) -> MutationPreview:
        """Vorschau mit konkreten Werten — wird zurückgegeben, nie gespeichert."""
        if isinstance(command, CreateContact):
            # Die Vorschau nennt die **API**-Feldnamen, nicht die kanonischen
            # Schlüssel: der Mensch sieht dieselbe Bezeichnung wie im Formular.
            from personaljarvis.contacts.application.field_contract import (
                preview_items,
            )

            return MutationPreview(
                command="create", target_provider_identifier=None,
                container_identifier=command.container_identifier,
                changes=tuple(FieldChange(name, None, wert) for name, wert
                              in preview_items(command.draft.contract)))
        vorher = {}
        if ziel.get("contact_id"):
            zeile = uow.execute(
                "SELECT * FROM contacts WHERE id = ?",
                (ziel["contact_id"],)).fetchone()
            if zeile is not None:
                vorher = dict(zeile)
        if isinstance(command, UpdateContact):
            return MutationPreview(
                command="update",
                target_provider_identifier=command.target_provider_identifier,
                container_identifier=None,
                changes=tuple(
                    FieldChange(k, vorher.get(k), v) for k, v
                    in sorted(command.patch.fields.items())),
                target_label=vorher.get("display_name"),
                target_contact_id=ziel.get("contact_id"))
        # delete: Zielkontakt knapp benennen, sonst keine PII.
        return MutationPreview(
            command="delete",
            target_provider_identifier=command.target_provider_identifier,
            container_identifier=None,
            target_label=vorher.get("display_name"),
            target_contact_id=ziel.get("contact_id"),
            warnings=("Der Datensatz wird beim Provider geloescht.",))

    def _precheck(self, uow: UnitOfWork, zeile, payload: MutationPayload) -> None:
        """Alles, was ohne Send prüfbar ist — vor dem Send."""
        if payload.command == "create":
            containers = self._known_containers(uow, payload.provider_account_id)
            if containers and payload.container_identifier not in containers:
                raise ContainerNotAvailable(
                    "Der gewuenschte Container ist nicht (mehr) vorhanden")
            return
        ziel = uow.execute(
            "SELECT c.id, c.is_me_card, c.local_revision, e.provider_account_id "
            "FROM contact_external_ids e JOIN contacts c ON c.id = e.contact_id "
            "WHERE e.provider_identifier = ?",
            (payload.target_provider_identifier,)).fetchone()
        if ziel is None:
            return                      # lokal unbekannt: der Provider entscheidet
        if ziel["provider_account_id"] != payload.provider_account_id:
            raise ForeignProviderAccount(
                "Das Ziel gehoert einem anderen Providerkonto")
        if ziel["is_me_card"]:
            raise MeCardNotWritable("Die Me-Karte ist schreibgeschuetzt")
        if (payload.expected_revision is not None
                and str(ziel["local_revision"]) != str(payload.expected_revision)):
            raise RevisionConflict(
                "Die erwartete Revision stimmt nicht mehr; es wird nichts "
                "ueberschrieben")

    @staticmethod
    def _known_containers(uow: UnitOfWork, provider_account_id: str) -> set[str]:
        rows = uow.execute(
            "SELECT DISTINCT container_identifier FROM contacts_sync_state "
            "WHERE provider_account_id = ?", (provider_account_id,)).fetchall()
        return {r["container_identifier"] for r in rows}

    @staticmethod
    def _facts(command: MutationCommand, *, payload_digest: str) -> dict:
        """Nur technische Angaben — nie ein Kontaktwert."""
        return {
            "command": command.command_name,
            "providerAccountId": command.provider_account_id,
            "initiationContext": command.initiation_context.value,
            "actor": command.actor,
            "correlationId": command.correlation_id,
            "payloadDigest": payload_digest,
            "target": getattr(command, "target_provider_identifier", None),
        }

    def _insert_mutation(self, uow: UnitOfWork, command: MutationCommand, *,
                         payload: MutationPayload, preview: MutationPreview,
                         approval_id: str, outbox_id: str, audit_id: str,
                         target_contact_id: str | None) -> None:
        uow.execute(
            "INSERT INTO contacts_mutations (mutation_id, command, "
            "correlation_id, actor, initiation_context, workspace_id, "
            "provider_account_id, container_identifier, target_contact_id, "
            "target_provider_identifier, expected_revision, idempotency_key, "
            "approval_id, outbox_id, audit_id, transaction_author, "
            "payload_json, payload_digest, preview_digest, state, "
            "attempt_count, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (command.mutation_id, command.command_name, command.correlation_id,
             command.actor, command.initiation_context.value,
             command.workspace_id, command.provider_account_id,
             payload.container_identifier, target_contact_id,
             payload.target_provider_identifier, payload.expected_revision,
             command.idempotency_key, approval_id, outbox_id, audit_id,
             TRANSACTION_AUTHOR, canonical_json(payload.as_dict()),
             payload.digest, preview.digest, MutationState.AWAITING_APPROVAL,
             0, command.requested_at))

    @staticmethod
    def _require_row(uow: UnitOfWork, mutation_id: str):
        zeile = uow.execute(
            "SELECT * FROM contacts_mutations WHERE mutation_id = ?",
            (mutation_id,)).fetchone()
        if zeile is None:
            raise MutationNotFound("Mutation existiert nicht")
        return zeile

    @staticmethod
    def _payload_from_row(zeile) -> MutationPayload:
        import json

        roh = json.loads(zeile["payload_json"])
        return MutationPayload(
            command=roh["command"],
            provider_account_id=roh["providerAccountId"],
            container_identifier=roh["containerIdentifier"],
            target_provider_identifier=roh["targetProviderIdentifier"],
            expected_revision=roh["expectedRevision"],
            fields=roh["fields"])

    @staticmethod
    def _set_state(uow: UnitOfWork, mutation_id: str, state: str, *,
                   outcome: str | None = None, error_code: str | None = None,
                   completed: bool = False, execution_started: bool = False,
                   provider_identifier: str | None = None,
                   readback_digest: str | None = None) -> None:
        felder = ["state = ?"]
        werte: list = [state]
        if readback_digest is not None:
            felder.append("readback_digest = ?"); werte.append(readback_digest)
        if outcome is not None:
            felder.append("outcome = ?"); werte.append(outcome)
        if error_code is not None:
            felder.append("last_error_code = ?"); werte.append(error_code)
        if execution_started:
            felder.append("execution_started_at = ?"); werte.append(utc_now())
        if completed:
            felder.append("completed_at = ?"); werte.append(utc_now())
        if provider_identifier is not None:
            felder.append("target_provider_identifier = "
                          "COALESCE(target_provider_identifier, ?)")
            werte.append(provider_identifier)
        werte.append(mutation_id)
        uow.execute(
            f"UPDATE contacts_mutations SET {', '.join(felder)} "
            "WHERE mutation_id = ?", werte)

    def _terminate(self, mutation_id: str, *, decision_actor: str | None,
                   approval_call: str, state: str, stage: str) -> Approval:
        with self._persistence.unit_of_work() as uow:
            zeile = self._require_row(uow, mutation_id)
            approvals = ApprovalStore(uow)
            if approval_call == "expire":
                approval = approvals.expire(zeile["approval_id"])
            else:
                approval = getattr(approvals, approval_call)(
                    zeile["approval_id"], decision_actor=decision_actor)
            self._set_state(uow, mutation_id, state, completed=True)
            ExternalActionOutbox(uow).abandon(zeile["outbox_id"],
                                              error_code=state)
            AuditTrail(uow, module=MODULE).record(
                stage, subject_type=SUBJECT_TYPE, subject_id=mutation_id,
                facts={"approvalId": approval.approval_id,
                       "decisionActor": decision_actor})
            return approval
