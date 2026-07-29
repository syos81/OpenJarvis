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
    #: Zustände, aus denen nur der Abgleich weiterführt.
    NEEDS_RECONCILE = frozenset({OUTCOME_UNKNOWN, RECONCILE_REQUIRED})


class ProviderResponse:
    """Antwort des Ausführungsziels — Fake-Bridge oder später echte Bridge."""

    def __init__(self, outcome: str, *, error_code: str | None = None,
                 provider_identifier: str | None = None) -> None:
        if outcome not in ProviderOutcome.ALL:
            raise ValueError(f"Unbekanntes Provider-Ergebnis: {outcome}")
        self.outcome = outcome
        self.error_code = error_code
        self.provider_identifier = provider_identifier


class MutationProvider(Protocol):
    """Das Ausführungsziel einer freigegebenen Mutation.

    In Gate C ist das ausschließlich eine Fake-Bridge. Der echte Sidecar
    liefert weiterhin `not_implemented` und wird **nicht** für Schreibzugriffe
    freigeschaltet.
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

        # ── Phase C: Ergebnis festschreiben ────────────────────────────────
        with self._persistence.unit_of_work() as uow:
            outbox = ExternalActionOutbox(uow)
            audit = AuditTrail(uow, module=MODULE)
            audit.record(AuditStage.PROVIDER_RESULT_RECEIVED,
                         subject_type=SUBJECT_TYPE, subject_id=mutation_id,
                         facts={"outcome": antwort.outcome,
                                "errorCode": antwort.error_code})
            return self._settle(uow, outbox, audit, mutation_id, outbox_id,
                                token, antwort, versuche)

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
            outbox.mark_succeeded(outbox_id, token)
            self._set_state(uow, mutation_id, MutationState.SUCCEEDED,
                            outcome="succeeded", completed=True,
                            provider_identifier=antwort.provider_identifier)
            audit.record(AuditStage.MUTATION_COMPLETED,
                         subject_type=SUBJECT_TYPE, subject_id=mutation_id,
                         facts={"outcome": "succeeded"})
            return ExecutionResult(
                mutation_id=mutation_id, state=MutationState.SUCCEEDED,
                outcome="succeeded",
                provider_identifier=antwort.provider_identifier,
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
        if self._capabilities is None:
            return
        name = {"create": "create", "update": "update",
                "delete": "delete"}[command.command_name]
        try:
            self._capabilities.require(name)
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
                container_identifier=zeile["container_identifier"]),
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
            return MutationPreview(
                command="create", target_provider_identifier=None,
                container_identifier=command.container_identifier,
                changes=tuple(FieldChange(k, None, v) for k, v
                              in sorted(command.draft.fields.items())))
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
                target_label=vorher.get("display_name"))
        # delete: Zielkontakt knapp benennen, sonst keine PII.
        return MutationPreview(
            command="delete",
            target_provider_identifier=command.target_provider_identifier,
            container_identifier=None,
            target_label=vorher.get("display_name"),
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
                   provider_identifier: str | None = None) -> None:
        felder = ["state = ?"]
        werte: list = [state]
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
