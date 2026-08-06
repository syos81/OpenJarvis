"""Append-only, hash-verketteter Audit-Schreiber (10 §5).

Was hier **nie** hineingeht: Kontaktwerte, Notizen, Roh-Tokens, Payloads. Der
Audit-Eintrag trägt technische Kennungen und einen Digest — mehr nicht. Wer
den Klartext braucht, findet ihn in der kanonischen Tabelle, nicht im Audit.

Die Kette schützt gegen nachträgliche unbemerkte Änderung, Löschung und
Umordnung, **nicht** gegen einen Angreifer mit vollen Rechten, der die ganze
Kette konsistent neu schreibt (10 §6 — ehrliches Bedrohungsmodell).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from personaljarvis.base.db.unit_of_work import UnitOfWork
from personaljarvis.base.digest import digest_of
from personaljarvis.contacts.domain.models import utc_now

__all__ = ["AuditStage", "AuditEntry", "AuditTrail"]


class AuditStage:
    """Geschlossene Menge der Pipeline-Stufen (Plan §8)."""

    MUTATION_PREPARED = "mutation_prepared"
    APPROVAL_REQUESTED = "approval_requested"
    APPROVAL_GRANTED = "approval_granted"
    APPROVAL_REJECTED = "approval_rejected"
    APPROVAL_EXPIRED = "approval_expired"
    APPROVAL_CANCELLED = "approval_cancelled"
    EXECUTION_CLAIMED = "execution_claimed"
    PROVIDER_SEND_STARTED = "provider_send_started"
    PROVIDER_RESULT_RECEIVED = "provider_result_received"
    FAILED_BEFORE_SEND = "failed_before_send"
    OUTCOME_UNKNOWN = "outcome_unknown"
    RECONCILE_STARTED = "reconcile_started"
    RECONCILE_SUCCEEDED = "reconcile_succeeded"
    MANUAL_DECISION_REQUIRED = "manual_decision_required"
    #: Ein Mensch hat einen ungewissen Ausgang aufgelöst. Ein **eigenes,
    #: späteres** Ereignis — es ersetzt `OUTCOME_UNKNOWN` nicht, sondern folgt
    #: darauf. Die Kette bleibt damit ehrlich: erst war es unbekannt, dann kam
    #: eine externe Beobachtung dazu.
    MUTATION_OUTCOME_MANUALLY_RESOLVED = "mutation_outcome_manually_resolved"
    MUTATION_COMPLETED = "mutation_completed"
    #: Der Ausfuehrungsauftrag hat das Backend verlassen (ADR-0026 §3). Ab
    #: dieser Stufe ist ein zweiter Claim ausgeschlossen — auch nach
    #: Verfall, denn ob irgendwo gesendet wurde, ist danach unbeweisbar.
    EXECUTION_ORDER_ISSUED = "execution_order_issued"
    #: Ein Bericht aus dem App-Prozess wurde serverseitig bewertet.
    MUTATION_SETTLED = "mutation_settled"

    ALL = frozenset({
        MUTATION_PREPARED, APPROVAL_REQUESTED, APPROVAL_GRANTED,
        APPROVAL_REJECTED, APPROVAL_EXPIRED, APPROVAL_CANCELLED,
        EXECUTION_CLAIMED, PROVIDER_SEND_STARTED, PROVIDER_RESULT_RECEIVED,
        FAILED_BEFORE_SEND, OUTCOME_UNKNOWN, RECONCILE_STARTED,
        RECONCILE_SUCCEEDED, MANUAL_DECISION_REQUIRED,
        MUTATION_OUTCOME_MANUALLY_RESOLVED, MUTATION_COMPLETED,
        EXECUTION_ORDER_ISSUED, MUTATION_SETTLED,
    })


@dataclass(frozen=True)
class AuditEntry:
    audit_id: str
    sequence: int
    stage: str
    subject_id: str
    payload_hash: str
    prev_hash: str | None


class AuditTrail:
    """Schreibt in `personal_audit_log` — immer in der UoW des Aufrufers."""

    def __init__(self, uow: UnitOfWork, *, module: str) -> None:
        self._uow = uow
        self._module = module

    def _head(self) -> tuple[int, str | None]:
        row = self._uow.execute(
            "SELECT sequence, payload_hash FROM personal_audit_log "
            "ORDER BY sequence DESC LIMIT 1").fetchone()
        return (0, None) if row is None else (row["sequence"], row["payload_hash"])

    def record(self, stage: str, *, subject_type: str, subject_id: str,
               facts: dict) -> AuditEntry:
        """Einen Eintrag anhängen. `facts` enthält **nur** technische Angaben."""
        if stage not in AuditStage.ALL:
            raise ValueError(f"Unbekannte Audit-Stufe: {stage}")
        sequence, prev_hash = self._head()
        sequence += 1
        audit_id = str(uuid.uuid4())
        payload_hash = digest_of({
            "sequence": sequence, "stage": stage, "module": self._module,
            "subjectType": subject_type, "subjectId": subject_id,
            "facts": facts, "prevHash": prev_hash,
        })
        self._uow.execute(
            "INSERT INTO personal_audit_log (audit_id, sequence, occurred_at, "
            "module, stage, subject_type, subject_id, payload_hash, prev_hash) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (audit_id, sequence, utc_now(), self._module, stage,
             subject_type, subject_id, payload_hash, prev_hash),
        )
        return AuditEntry(audit_id=audit_id, sequence=sequence, stage=stage,
                          subject_id=subject_id, payload_hash=payload_hash,
                          prev_hash=prev_hash)

    def verify_chain(self) -> bool:
        """Prüft die Verkettung über alle Einträge."""
        rows = self._uow.execute(
            "SELECT sequence, payload_hash, prev_hash FROM personal_audit_log "
            "ORDER BY sequence").fetchall()
        vorher: str | None = None
        for row in rows:
            if row["prev_hash"] != vorher:
                return False
            vorher = row["payload_hash"]
        return True
