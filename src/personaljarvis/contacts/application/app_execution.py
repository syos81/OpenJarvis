"""Claim und Settle des App-Prozess-Mutationskanals (ADR-0020, Phase A).

Der Kern sendet seit ADR-0020 nicht mehr selbst. Er tut zwei Dinge:

1. **Claim** — er beansprucht genau **einen** Ausführungsversuch, verbraucht
   die Freigabe gegen Nutzlast **und** Vorschau, und gibt einen kurzlebigen,
   gebundenen Auftrag heraus. Ab dem Moment der Ausgabe gilt der Versuch als
   möglicherweise gesendet: `provider_send_started` steht in derselben
   Transaktion, **bevor** die Antwort das Backend verlässt.
2. **Settle** — er nimmt genau **einen** typisierten Bericht entgegen,
   rechnet dessen Digest selbst nach und entscheidet den Zustand. Er ruft
   dabei nie einen Provider, nie Tauri und nie den Sidecar.

Was hier bewusst **nicht** passiert: ein zweiter Claim. Weder Verfall noch
Reload, Absturz oder ausbleibender Bericht öffnen einen neuen Versuch —
sobald ein Auftrag ausgegeben wurde, ist unbeweisbar, ob irgendwo gesendet
wurde, und der einzige ehrliche Weg heisst `outcome_unknown` → Abgleich.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from personaljarvis.base.approvals import (
    ApprovalPayloadMismatch,
    ApprovalStore,
)
from personaljarvis.base.audit import AuditTrail
from personaljarvis.base.outbox import (
    ExternalActionOutbox,
    OutboxNotClaimable,
    token_digest,
)
from personaljarvis.contacts.application.errors import (
    AlreadySettled,
    MutationNotExecutable,
    MutationNotFound,
)
from personaljarvis.contacts.application.execution_contracts import (
    ExecutionOrderV1,
    ExecutionReportV1,
    report_digest,
)
from personaljarvis.contacts.application.state_machine import pruefe_uebergang
from personaljarvis.contacts.domain.models import utc_now

__all__ = [
    "CLAIM_TTL_SECONDS",
    "AppExecutionService",
    "SettleErgebnis",
    "SettleConflict",
    "ChannelNotEnabled",
]

MODULE = "contacts"

#: Lebensdauer eines Claims (ADR-0020 §3). Der Verfall wirkt ausschliesslich
#: **vor** der nativen Validierung; nach Auftragsausgabe erlaubt er nie einen
#: neuen Versuch.
CLAIM_TTL_SECONDS = 600

_MUTATION_STATES_APPROVED = "approved"
_MUTATION_STATE_EXECUTING = "executing"


class SettleConflict(RuntimeError):
    """Ein zweiter, abweichender Bericht zu demselben Versuch."""


class ChannelNotEnabled(RuntimeError):
    """Der App-Prozess-Schreibkanal ist nicht freigeschaltet."""


@dataclass(frozen=True, slots=True)
class SettleErgebnis:
    mutation_id: str
    state: str
    outcome: str | None
    idempotent: bool
    error_class: str | None = None


def _plus_sekunden(zeitpunkt: str, sekunden: int) -> str:
    basis = datetime.fromisoformat(zeitpunkt.replace("Z", "+00:00"))
    if basis.tzinfo is None:
        basis = basis.replace(tzinfo=timezone.utc)
    return (basis + timedelta(seconds=sekunden)).isoformat()


class AppExecutionService:
    """Claim- und Settle-Seite des App-Prozess-Kanals.

    Der Dienst arbeitet ausschliesslich auf dem Kern: Datenbank, Outbox,
    Freigaben, Audit. Er kennt weder Tauri noch den Sidecar.
    """

    def __init__(self, persistence, *, channel_capabilities=None) -> None:
        self._persistence = persistence
        self._caps = channel_capabilities

    # ── Claim ───────────────────────────────────────────────────────────────
    def claim(self, mutation_id: str) -> ExecutionOrderV1:
        """Beansprucht genau einen Versuch und gibt den Auftrag heraus.

        Reihenfolge ist Absicht: Erst alle Prüfungen, die **vor** jedem Send
        scheitern dürfen, dann der Claim, dann `provider_send_started`. Wer
        die Audit-Stufe erst nach der Antwort schriebe, verlöre bei einem
        Absturz genau die Information, dass gesendet worden sein könnte.
        """
        if self._caps is None or not self._caps.channel_available:
            # Fail-closed: ohne Fähigkeitssatz gibt es keinen Auftrag. Ein
            # fehlender Handshake ist kein Freibrief.
            raise ChannelNotEnabled(
                "Der App-Prozess-Schreibkanal ist nicht freigeschaltet")

        with self._persistence.unit_of_work() as uow:
            zeile = uow.execute(
                "SELECT * FROM contacts_mutations WHERE mutation_id = ?",
                (mutation_id,)).fetchone()
            if zeile is None:
                raise MutationNotFound("Vorgang existiert nicht")

            # Erst hier steht fest, **welche** Operation ansteht: geprüft
            # wird Schreibrecht UND die Fähigkeit genau dieser Operation.
            # Ein Kanal, der `create` kann, darf deshalb noch lange kein
            # `delete` beanspruchen.
            if not self._caps.darf_ausfuehren(zeile["command"]):
                raise ChannelNotEnabled(
                    f"Operation '{zeile['command']}' ist im App-Prozess-Kanal "
                    "nicht freigeschaltet")

            zustand = zeile["state"]
            if zustand != _MUTATION_STATES_APPROVED:
                # Ein bereits beanspruchter oder abgeschlossener Vorgang
                # bekommt nie einen zweiten Auftrag — auch nicht denselben.
                raise MutationNotExecutable(
                    f"Vorgang ist '{zustand}', nicht 'approved'")

            outbox = ExternalActionOutbox(uow)
            eintrag = outbox.require(zeile["outbox_id"])
            if eintrag.auftrag_ausgegeben:
                raise AlreadySettled(
                    "Für diesen Vorgang wurde bereits ein Ausführungsauftrag "
                    "ausgegeben")

            # Freigabe gegen **beide** Digests verbrauchen (ADR-0020 §9).
            try:
                ApprovalStore(uow).consume(
                    zeile["approval_id"],
                    payload_digest=zeile["payload_digest"],
                    preview_digest=zeile["preview_digest"])
            except ApprovalPayloadMismatch as exc:
                raise MutationNotExecutable(str(exc)) from exc

            try:
                _, token = outbox.claim(zeile["outbox_id"])
            except OutboxNotClaimable as exc:
                raise MutationNotExecutable(str(exc)) from exc

            jetzt = utc_now()
            operation_id = str(uuid.uuid4())
            laeuft_ab = _plus_sekunden(jetzt, CLAIM_TTL_SECONDS)

            uow.execute(
                "UPDATE personal_external_action_outbox SET operation_id = ?, "
                "claim_expires_at = ?, execution_order_issued_at = ? "
                "WHERE outbox_id = ?",
                (operation_id, laeuft_ab, jetzt, zeile["outbox_id"]))

            pruefe_uebergang(zustand, _MUTATION_STATE_EXECUTING)
            uow.execute(
                "UPDATE contacts_mutations SET state = ?, "
                "execution_started_at = ?, attempt_count = ? "
                "WHERE mutation_id = ?",
                (_MUTATION_STATE_EXECUTING, jetzt,
                 outbox.require(zeile["outbox_id"]).attempt_count, mutation_id))

            audit = AuditTrail(uow, module=MODULE)
            fakten = {
                "operationId": operation_id,
                "operationType": zeile["command"],
                "attemptNumber": outbox.require(zeile["outbox_id"]).attempt_count,
                "channel": "app_process",
            }
            audit.record("execution_claimed", subject_type="contact_mutation",
                         subject_id=mutation_id, facts=fakten)
            audit.record("execution_order_issued",
                         subject_type="contact_mutation",
                         subject_id=mutation_id,
                         facts={**fakten, "expiresAt": laeuft_ab})
            # Ab hier gilt: es koennte gesendet werden. Die Stufe steht in
            # dieser Transaktion, damit sie einen Absturz ueberlebt.
            audit.record("provider_send_started",
                         subject_type="contact_mutation",
                         subject_id=mutation_id,
                         facts={**fakten, "automaticRetry": False})

            payload = _kanonischer_payload(zeile)
            return ExecutionOrderV1(
                operation_id=operation_id,
                mutation_id=mutation_id,
                claim_token=token,
                operation_type=zeile["command"],
                payload_digest=zeile["payload_digest"],
                preview_digest=zeile["preview_digest"] or "",
                canonical_payload=payload,
                issued_at=jetzt,
                expires_at=laeuft_ab,
                expected_revision=zeile["expected_revision"],
                provider_target={
                    "container_identifier": zeile["container_identifier"],
                    "provider_identifier": zeile["target_provider_identifier"],
                },
                transaction_author=zeile["transaction_author"],
            )

    # ── Settle ──────────────────────────────────────────────────────────────
    def settle(self, mutation_id: str, bericht: ExecutionReportV1, *,
               claim_token: str) -> SettleErgebnis:
        """Nimmt genau einen Bericht entgegen — idempotent, ohne Providerkontakt.

        Idempotenz ist bewusst inhaltsbasiert: derselbe Bericht darf beliebig
        oft ankommen (Netz, Reload, Wiederholung), ein **abweichender** nie.
        Der Digest wird serverseitig gerechnet; das Frontend liefert ihn nicht.
        """
        with self._persistence.unit_of_work() as uow:
            zeile = uow.execute(
                "SELECT * FROM contacts_mutations WHERE mutation_id = ?",
                (mutation_id,)).fetchone()
            if zeile is None:
                raise MutationNotFound("Vorgang existiert nicht")

            outbox = ExternalActionOutbox(uow)
            eintrag = outbox.require(zeile["outbox_id"])

            if bericht.mutation_id != mutation_id \
                    or eintrag.operation_id != bericht.operation_id:
                raise SettleConflict(
                    "Der Bericht gehört zu einem anderen Ausführungsversuch")

            digest = report_digest(bericht)

            # Wiederholung desselben Berichts: exakt dieselbe Antwort, keine
            # zweite Wirkung, kein zusaetzlicher Versuch.
            if eintrag.execution_report_digest == digest:
                return SettleErgebnis(
                    mutation_id=mutation_id, state=zeile["state"],
                    outcome=zeile["outcome"], idempotent=True,
                    error_class=eintrag.error_class)
            if eintrag.execution_report_digest is not None:
                raise SettleConflict(
                    "Zu diesem Versuch liegt bereits ein abweichender Bericht vor")

            if eintrag.claim_token_digest is None \
                    or eintrag.claim_token_digest != token_digest(claim_token):
                raise SettleConflict("Ungültige Claim-Bindung")

            ziel, outcome, fehlerklasse = _bewerte(bericht)
            pruefe_uebergang(zeile["state"], ziel)

            uow.execute(
                "UPDATE personal_external_action_outbox SET "
                "execution_report_digest = ?, provider_completed_at = ?, "
                "error_class = ?, error_digest = ? WHERE outbox_id = ?",
                (digest, bericht.provider_completed_at, fehlerklasse,
                 bericht.error_digest, zeile["outbox_id"]))

            if ziel == "failed_before_send":
                outbox.mark_failed_before_send(
                    zeile["outbox_id"], claim_token,
                    error_code=fehlerklasse or "not_sent")
                outbox.abandon(zeile["outbox_id"],
                               error_code=fehlerklasse or "not_sent")
            elif ziel == "outcome_unknown":
                outbox.mark_outcome_unknown(
                    zeile["outbox_id"], claim_token,
                    error_code=fehlerklasse or "outcome_unknown")
            else:  # provider_applied_pending_reconcile
                outbox.mark_succeeded(zeile["outbox_id"], claim_token)

            uow.execute(
                "UPDATE contacts_mutations SET state = ?, outcome = ?, "
                "last_error_code = ? WHERE mutation_id = ?",
                (ziel, outcome, fehlerklasse, mutation_id))

            audit = AuditTrail(uow, module=MODULE)
            audit.record("provider_result_received",
                         subject_type="contact_mutation",
                         subject_id=mutation_id,
                         facts={
                             "operationId": bericht.operation_id,
                             "outcome": bericht.outcome,
                             "sendAttempted": bericht.send_attempted,
                             "saveRequestCount": bericht.save_request_count,
                             "readbackStatus": bericht.readback_status,
                             "errorClass": fehlerklasse,
                             "channel": "app_process",
                         })
            audit.record("mutation_settled", subject_type="contact_mutation",
                         subject_id=mutation_id,
                         facts={
                             "operationId": bericht.operation_id,
                             "state": ziel,
                             "resend": False,
                             "reportDigest": digest,
                         })
            return SettleErgebnis(mutation_id=mutation_id, state=ziel,
                                  outcome=outcome, idempotent=False,
                                  error_class=fehlerklasse)


def _bewerte(bericht: ExecutionReportV1) -> tuple[str, str | None, str | None]:
    """Übersetzt einen Bericht in den Zielzustand.

    Die Zuordnung ist absichtlich streng: Nur ein `not_sent` **ohne**
    Sendeversuch darf `failed_before_send` werden — das ist die einzige
    Aussage, die „nachweislich nichts übergeben" bedeutet. Alles andere,
    was nicht sauber angewandt ist, endet im ungewissen Ausgang.
    """
    if bericht.beweist_nichts_gesendet:
        return "failed_before_send", "failed", bericht.error_class
    if bericht.outcome == "applied" and bericht.readback_status in (
            "confirmed", "absent_confirmed"):
        return "provider_applied_pending_reconcile", None, None
    return "outcome_unknown", "outcome_unknown", bericht.error_class


def _kanonischer_payload(zeile) -> dict:
    """Die **vollstaendige** kanonische Nutzlast — genau das, was der
    `payload_digest` deckt.

    Nur `fields` mitzugeben waere verlockend (der native Save braucht nur
    sie), aber dann koennte Rust den Digest nicht nachrechnen — und genau
    diese Nachrechnung ist die Bindung zwischen dem, was der Mensch
    freigegeben hat, und dem, was ausgefuehrt wird (ADR-0020 §5).
    """
    import json
    roh = json.loads(zeile["payload_json"])
    return roh if isinstance(roh, dict) else {}
