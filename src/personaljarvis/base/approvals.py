"""Freigabe-Kern für R1-Aktionen (10 §3, ADR-0006).

Verbindliche Eigenschaften:

* **Vorbereitung und Ausführung sind getrennt.** Eine Freigabe entsteht beim
  Vorbereiten und wird beim Ausführen ausdrücklich *verbraucht*.
* **Die Freigabe ist an die Nutzlast gebunden.** Ändert sich die Nutzlast, passt
  der Digest nicht mehr — die Freigabe wird ungültig statt stillschweigend zu
  gelten.
* **Endzustände sind endgültig.** `rejected`, `expired`, `cancelled` und
  `consumed` lassen sich nicht reaktivieren.
* **Ein Modell erteilt sich nie selbst eine Freigabe.** `grant()` verlangt einen
  menschlichen Entscheider; `llm_assisted` und `automation` können ausschließlich
  *anfragen* (05 §5).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from personaljarvis.base.db.unit_of_work import UnitOfWork
from personaljarvis.contacts.domain.models import utc_now
from personaljarvis.errors import PersonalJarvisError

__all__ = [
    "ApprovalState",
    "ApprovalError",
    "ApprovalNotFound",
    "ApprovalNotPending",
    "ApprovalExpired",
    "ApprovalPayloadMismatch",
    "SelfApprovalRejected",
    "Approval",
    "ApprovalStore",
    "DEFAULT_TTL_SECONDS",
]

#: Voreingestellte Gültigkeitsdauer einer R1-Freigabe. Bewusst kurz: eine
#: Vorschau altert, sobald sich der Provider-Zustand ändern kann.
DEFAULT_TTL_SECONDS = 15 * 60

#: Ursprünge, die niemals selbst entscheiden dürfen (05 §5).
_NON_HUMAN_ORIGINS = frozenset({"llm_assisted", "automation", "system"})


class ApprovalState:
    AWAITING = "awaiting_approval"
    GRANTED = "granted"
    REJECTED = "rejected"
    EXPIRED = "expired"
    CANCELLED = "cancelled"
    CONSUMED = "consumed"

    TERMINAL = frozenset({REJECTED, EXPIRED, CANCELLED, CONSUMED})


class ApprovalError(PersonalJarvisError):
    """Wurzel aller Freigabefehler."""


class ApprovalNotFound(ApprovalError):
    """Die Freigabe existiert nicht."""


class ApprovalNotPending(ApprovalError):
    """Die Freigabe ist bereits entschieden oder verbraucht."""


class ApprovalExpired(ApprovalError):
    """Die Freigabe ist abgelaufen und wird nicht ausgeführt."""


class ApprovalPayloadMismatch(ApprovalError):
    """Die Nutzlast hat sich nach der Freigabe geändert."""


class SelfApprovalRejected(ApprovalError):
    """Ein nicht-menschlicher Ursprung hat versucht, selbst freizugeben."""


@dataclass(frozen=True)
class Approval:
    approval_id: str
    module: str
    subject_type: str
    subject_id: str
    risk_class: str
    initiation_context: str
    actor: str
    correlation_id: str
    payload_digest: str
    preview_digest: str
    state: str
    requested_at: str
    expires_at: str
    decided_at: str | None = None
    consumed_at: str | None = None
    decision_actor: str | None = None

    @property
    def is_terminal(self) -> bool:
        return self.state in ApprovalState.TERMINAL

    def is_expired(self, *, now: str | None = None) -> bool:
        return (now or utc_now()) >= self.expires_at


class ApprovalStore:
    """Persistenz der Freigaben — arbeitet immer in der UoW des Aufrufers."""

    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    # ── Anlegen ─────────────────────────────────────────────────────────────
    def request(self, *, approval_id: str, module: str, subject_type: str,
                subject_id: str, risk_class: str, initiation_context: str,
                actor: str, correlation_id: str, payload_digest: str,
                preview_digest: str,
                ttl_seconds: int = DEFAULT_TTL_SECONDS) -> Approval:
        jetzt = datetime.now(timezone.utc).replace(microsecond=0)
        approval = Approval(
            approval_id=approval_id, module=module, subject_type=subject_type,
            subject_id=subject_id, risk_class=risk_class,
            initiation_context=initiation_context, actor=actor,
            correlation_id=correlation_id, payload_digest=payload_digest,
            preview_digest=preview_digest, state=ApprovalState.AWAITING,
            requested_at=jetzt.isoformat(),
            expires_at=(jetzt + timedelta(seconds=ttl_seconds)).isoformat(),
        )
        self._uow.execute(
            "INSERT INTO personal_approvals (approval_id, module, subject_type, "
            "subject_id, risk_class, initiation_context, actor, correlation_id, "
            "payload_digest, preview_digest, state, requested_at, expires_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (approval.approval_id, approval.module, approval.subject_type,
             approval.subject_id, approval.risk_class,
             approval.initiation_context, approval.actor,
             approval.correlation_id, approval.payload_digest,
             approval.preview_digest, approval.state, approval.requested_at,
             approval.expires_at),
        )
        return approval

    # ── Lesen ───────────────────────────────────────────────────────────────
    def get(self, approval_id: str) -> Approval | None:
        row = self._uow.execute(
            "SELECT * FROM personal_approvals WHERE approval_id = ?",
            (approval_id,)).fetchone()
        return self._hydrate(row) if row else None

    def find_for_subject(self, subject_type: str,
                         subject_id: str) -> Approval | None:
        row = self._uow.execute(
            "SELECT * FROM personal_approvals WHERE subject_type = ? "
            "AND subject_id = ?", (subject_type, subject_id)).fetchone()
        return self._hydrate(row) if row else None

    def require(self, approval_id: str) -> Approval:
        approval = self.get(approval_id)
        if approval is None:
            raise ApprovalNotFound("Freigabe existiert nicht")
        return approval

    # ── Entscheiden ─────────────────────────────────────────────────────────
    def grant(self, approval_id: str, *, decision_actor: str) -> Approval:
        """Menschliche Freigabe. Ein Modell kann das nicht auslösen."""
        approval = self.require(approval_id)
        self._require_pending(approval)
        if decision_actor in _NON_HUMAN_ORIGINS or not decision_actor.strip():
            raise SelfApprovalRejected(
                "Eine Freigabe verlangt eine menschliche Entscheidung; "
                f"'{decision_actor}' ist kein zulaessiger Entscheider"
            )
        return self._decide(approval, ApprovalState.GRANTED, decision_actor)

    def reject(self, approval_id: str, *, decision_actor: str) -> Approval:
        approval = self.require(approval_id)
        self._require_pending(approval)
        return self._decide(approval, ApprovalState.REJECTED, decision_actor)

    def cancel(self, approval_id: str, *, decision_actor: str) -> Approval:
        approval = self.require(approval_id)
        self._require_pending(approval)
        return self._decide(approval, ApprovalState.CANCELLED, decision_actor)

    def expire(self, approval_id: str) -> Approval:
        approval = self.require(approval_id)
        if approval.is_terminal:
            raise ApprovalNotPending("Freigabe ist bereits abgeschlossen")
        return self._decide(approval, ApprovalState.EXPIRED, None)

    # ── Verbrauchen ─────────────────────────────────────────────────────────
    def consume(self, approval_id: str, *, payload_digest: str,
                preview_digest: str | None = None) -> Approval:
        """Bindet die Ausführung an die freigegebene Nutzlast **und Vorschau**.

        Fail-closed bei: nicht freigegeben, abgelaufen, Digest abweichend,
        bereits verbraucht. Eine verbrauchte Freigabe deckt **keinen** zweiten
        Sendeversuch.

        Der Vorschau-Digest wurde bis 2026-08-03 zwar gespeichert, aber nie
        geprüft (ADR-0020 Lücke L1). Das war eine echte Lücke: Der Mensch gibt
        frei, was er **gesehen** hat — die Nutzlast allein belegt nicht, dass
        die Anzeige dieselbe Operation zeigte. Wird `preview_digest`
        übergeben, muss er zur Freigabe passen; `None` bedeutet
        „nicht mitgeführt" (Altpfade), nie „egal".
        """
        approval = self.require(approval_id)
        if approval.state == ApprovalState.CONSUMED:
            raise ApprovalNotPending("Freigabe wurde bereits verbraucht")
        if approval.state != ApprovalState.GRANTED:
            raise ApprovalNotPending(
                f"Freigabe ist '{approval.state}', nicht 'granted'")
        if approval.is_expired():
            self._decide(approval, ApprovalState.EXPIRED, None)
            raise ApprovalExpired("Freigabe ist abgelaufen")
        if approval.payload_digest != payload_digest:
            raise ApprovalPayloadMismatch(
                "Die Nutzlast hat sich nach der Freigabe geaendert; "
                "die Freigabe deckt sie nicht mehr"
            )
        if preview_digest is not None \
                and approval.preview_digest != preview_digest:
            raise ApprovalPayloadMismatch(
                "Die Vorschau passt nicht zur Freigabe; freigegeben wurde "
                "eine andere Darstellung derselben Nutzlast"
            )
        jetzt = utc_now()
        self._uow.execute(
            "UPDATE personal_approvals SET state = ?, consumed_at = ? "
            "WHERE approval_id = ?",
            (ApprovalState.CONSUMED, jetzt, approval_id))
        return self.require(approval_id)

    # ── intern ──────────────────────────────────────────────────────────────
    @staticmethod
    def _require_pending(approval: Approval) -> None:
        """Nur eine **wartende** Freigabe ist entscheidbar.

        Ein zweites `grant()` auf eine bereits erteilte Freigabe muss scheitern:
        sonst liesse sich eine abgelaufene Entscheidung durch eine neue
        ersetzen, ohne dass jemand die Vorschau erneut gesehen hat.
        """
        if approval.state != ApprovalState.AWAITING:
            raise ApprovalNotPending(
                f"Freigabe ist '{approval.state}' und nicht mehr entscheidbar")

    def _decide(self, approval: Approval, state: str,
                decision_actor: str | None) -> Approval:
        self._uow.execute(
            "UPDATE personal_approvals SET state = ?, decided_at = ?, "
            "decision_actor = ? WHERE approval_id = ?",
            (state, utc_now(), decision_actor, approval.approval_id))
        return self.require(approval.approval_id)

    @staticmethod
    def _hydrate(row) -> Approval:
        return Approval(
            approval_id=row["approval_id"], module=row["module"],
            subject_type=row["subject_type"], subject_id=row["subject_id"],
            risk_class=row["risk_class"],
            initiation_context=row["initiation_context"], actor=row["actor"],
            correlation_id=row["correlation_id"],
            payload_digest=row["payload_digest"],
            preview_digest=row["preview_digest"], state=row["state"],
            requested_at=row["requested_at"], expires_at=row["expires_at"],
            decided_at=row["decided_at"], consumed_at=row["consumed_at"],
            decision_actor=row["decision_actor"])
