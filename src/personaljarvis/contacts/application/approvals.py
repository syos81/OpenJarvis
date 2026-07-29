"""Freigabefläche des Kontakte-Moduls (10 §3, 05 §5).

Dünne, modulnahe Sicht auf den Basis-Freigabekern: Sie beantwortet „welche
Vorgänge warten auf mich" und reicht Entscheidungen weiter. Die
Zustandsmaschine, die Bindung an den Payload-Digest und das
Selbstfreigabe-Verbot liegen im Basis-Store und werden hier **nicht**
dupliziert — es gibt nur eine Wahrheit.
"""

from __future__ import annotations

from dataclasses import dataclass

from personaljarvis.base.approvals import Approval, ApprovalState, ApprovalStore
from personaljarvis.contacts.application.mutation_service import (
    MODULE,
    SUBJECT_TYPE,
    ContactsMutationService,
)

__all__ = ["PendingApproval", "ContactsApprovalService"]


@dataclass(frozen=True)
class PendingApproval:
    """Ein wartender Vorgang — ohne Kontaktwerte, nur Kennungen und Digests."""

    mutation_id: str
    approval_id: str
    command: str
    initiation_context: str
    actor: str
    correlation_id: str
    requested_at: str
    expires_at: str
    preview_digest: str


class ContactsApprovalService:
    def __init__(self, persistence) -> None:
        self._persistence = persistence

    def pending(self) -> tuple[PendingApproval, ...]:
        with self._persistence.unit_of_work() as uow:
            rows = uow.execute(
                "SELECT m.mutation_id, m.command, m.actor, m.correlation_id, "
                "m.initiation_context, a.approval_id, a.requested_at, "
                "a.expires_at, a.preview_digest "
                "FROM contacts_mutations m "
                "JOIN personal_approvals a ON a.approval_id = m.approval_id "
                "WHERE a.state = ? AND a.module = ? "
                "ORDER BY a.requested_at, m.mutation_id",
                (ApprovalState.AWAITING, MODULE)).fetchall()
            return tuple(PendingApproval(
                mutation_id=r["mutation_id"], approval_id=r["approval_id"],
                command=r["command"],
                initiation_context=r["initiation_context"], actor=r["actor"],
                correlation_id=r["correlation_id"],
                requested_at=r["requested_at"], expires_at=r["expires_at"],
                preview_digest=r["preview_digest"]) for r in rows)

    def get(self, mutation_id: str) -> Approval | None:
        with self._persistence.unit_of_work() as uow:
            return ApprovalStore(uow).find_for_subject(SUBJECT_TYPE, mutation_id)

    def expire_due(self, *, now: str | None = None) -> tuple[str, ...]:
        """Meldet fällige Freigaben. Ausführung bleibt ein eigener Schritt."""
        from personaljarvis.contacts.domain.models import utc_now

        grenze = now or utc_now()
        with self._persistence.unit_of_work() as uow:
            rows = uow.execute(
                "SELECT subject_id FROM personal_approvals WHERE state = ? "
                "AND module = ? AND expires_at <= ? ORDER BY subject_id",
                (ApprovalState.AWAITING, MODULE, grenze)).fetchall()
            return tuple(r["subject_id"] for r in rows)
