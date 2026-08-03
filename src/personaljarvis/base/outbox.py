"""ExternalActionOutbox — externe Schreiboperationen laufen nie direkt (11 §1/§3).

Verbindliche Eigenschaften:

* **Transaktional angelegt.** Kanonische Änderung, Freigabebindung, Audit-Stufe
  und Outbox-Eintrag entstehen in **einer** UnitOfWork.
* **Kein Provider-Aufruf in der Transaktion.** Der Executor beansprucht einen
  Eintrag, schließt die Transaktion und ruft **danach** den Provider. Damit
  hängt keine Schreibsperre an einem fremden Prozess.
* **Claiming verhindert Doppelausführung.** Ein Eintrag wechselt nur aus
  `pending` nach `claimed`, wenn genau eine Transaktion die Zeile trifft.
* **`attempt_count` ist technisch, kein Retry-Recht.** Er zählt Versuche; ob
  ein Versuch wiederholt werden darf, entscheidet allein der Zustand.
* **Aus `outcome_unknown` führt kein automatischer Weg zurück.** Solche
  Einträge werden von `claim_due()` niemals geliefert.
* **Nichts wird still gelöscht.** Abgeschlossene Einträge bleiben stehen.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from dataclasses import dataclass

from personaljarvis.base.db.unit_of_work import UnitOfWork
from personaljarvis.contacts.domain.models import utc_now
from personaljarvis.errors import PersonalJarvisError

__all__ = [
    "token_digest",
    "OutboxState",
    "OutboxError",
    "OutboxEntryNotFound",
    "OutboxNotClaimable",
    "OutboxEntry",
    "ExternalActionOutbox",
]


def token_digest(token: str) -> str:
    """SHA-256-Hex eines Claim-Tokens.

    Der Rohtoken verlaesst den Kern genau einmal (im Ausfuehrungsauftrag)
    und wird nie gespeichert oder protokolliert; verglichen wird immer der
    Digest.
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class OutboxState:
    PENDING = "pending"
    CLAIMED = "claimed"
    SUCCEEDED = "succeeded"
    FAILED_BEFORE_SEND = "failed_before_send"
    OUTCOME_UNKNOWN = "outcome_unknown"
    ABANDONED = "abandoned"

    #: Zustände, die nie wieder in die Ausführung gehen.
    TERMINAL = frozenset({SUCCEEDED, ABANDONED})
    #: `outcome_unknown` ist bewusst weder terminal noch beanspruchbar —
    #: es wartet auf den Abgleich, nicht auf einen Retry.
    NOT_CLAIMABLE = frozenset({CLAIMED, SUCCEEDED, OUTCOME_UNKNOWN, ABANDONED})


class OutboxError(PersonalJarvisError):
    """Wurzel aller Outbox-Fehler."""


class OutboxEntryNotFound(OutboxError):
    """Der Eintrag existiert nicht."""


class OutboxNotClaimable(OutboxError):
    """Der Eintrag darf nicht (mehr) ausgeführt werden."""


@dataclass(frozen=True)
class OutboxEntry:
    outbox_id: str
    module: str
    operation: str
    subject_type: str
    subject_id: str
    approval_id: str
    idempotency_key: str
    payload_digest: str
    state: str
    attempt_count: int
    available_at: str
    created_at: str
    claimed_at: str | None = None
    #: **Nur der Digest.** Der Rohtoken existiert einmal im
    #: Ausfuehrungsauftrag und wird nie persistiert (ADR-0020 §3).
    claim_token_digest: str | None = None
    operation_id: str | None = None
    claim_expires_at: str | None = None
    execution_order_issued_at: str | None = None
    execution_report_digest: str | None = None
    provider_completed_at: str | None = None
    error_class: str | None = None
    error_digest: str | None = None
    settled_at: str | None = None
    last_error_code: str | None = None

    @property
    def auftrag_ausgegeben(self) -> bool:
        """Ab hier ist kein zweiter Claim mehr zulaessig — auch nicht nach
        Verfall: ob gesendet wurde, ist von da an unbeweisbar."""
        return self.execution_order_issued_at is not None

    @property
    def is_claimable(self) -> bool:
        return self.state not in OutboxState.NOT_CLAIMABLE


class ExternalActionOutbox:
    """Persistenz der ausstehenden externen Schreiboperationen."""

    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    # ── Anlegen ─────────────────────────────────────────────────────────────
    def enqueue(self, *, module: str, operation: str, subject_type: str,
                subject_id: str, approval_id: str, idempotency_key: str,
                payload_digest: str, available_at: str | None = None) -> OutboxEntry:
        outbox_id = str(uuid.uuid4())
        jetzt = utc_now()
        self._uow.execute(
            "INSERT INTO personal_external_action_outbox (outbox_id, module, "
            "operation, subject_type, subject_id, approval_id, idempotency_key, "
            "payload_digest, state, attempt_count, available_at, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (outbox_id, module, operation, subject_type, subject_id,
             approval_id, idempotency_key, payload_digest, OutboxState.PENDING,
             0, available_at or jetzt, jetzt),
        )
        return self.require(outbox_id)

    # ── Lesen ───────────────────────────────────────────────────────────────
    def get(self, outbox_id: str) -> OutboxEntry | None:
        row = self._uow.execute(
            "SELECT * FROM personal_external_action_outbox WHERE outbox_id = ?",
            (outbox_id,)).fetchone()
        return self._hydrate(row) if row else None

    def require(self, outbox_id: str) -> OutboxEntry:
        entry = self.get(outbox_id)
        if entry is None:
            raise OutboxEntryNotFound("Outbox-Eintrag existiert nicht")
        return entry

    def find_for_subject(self, subject_type: str,
                         subject_id: str) -> OutboxEntry | None:
        row = self._uow.execute(
            "SELECT * FROM personal_external_action_outbox WHERE "
            "subject_type = ? AND subject_id = ?",
            (subject_type, subject_id)).fetchone()
        return self._hydrate(row) if row else None

    def list_due(self, *, module: str, now: str | None = None) -> tuple[OutboxEntry, ...]:
        """Fällige, beanspruchbare Einträge — `outcome_unknown` ist nie dabei."""
        rows = self._uow.execute(
            "SELECT * FROM personal_external_action_outbox WHERE module = ? "
            "AND state IN (?, ?) AND available_at <= ? "
            "ORDER BY created_at, outbox_id",
            (module, OutboxState.PENDING, OutboxState.FAILED_BEFORE_SEND,
             now or utc_now())).fetchall()
        return tuple(self._hydrate(r) for r in rows)

    # ── Beanspruchen und Abschließen ────────────────────────────────────────
    def claim(self, outbox_id: str) -> tuple[OutboxEntry, str]:
        """Beansprucht einen Eintrag exklusiv und gibt das Claim-Token zurück.

        Das bedingte `UPDATE` ist der Schutz gegen Doppelausführung: ein
        zweiter Beanspruchungsversuch trifft null Zeilen.
        """
        entry = self.require(outbox_id)
        if not entry.is_claimable:
            raise OutboxNotClaimable(
                f"Eintrag ist '{entry.state}' und nicht beanspruchbar")
        # CSPRNG statt UUID: das Token ist ein Berechtigungsnachweis, kein
        # Bezeichner. 32 Bytes, hex — und nur sein Digest wird gespeichert.
        token = secrets.token_hex(32)
        cursor = self._uow.execute(
            "UPDATE personal_external_action_outbox SET state = ?, "
            "claimed_at = ?, claim_token_digest = ?, "
            "attempt_count = attempt_count + 1 "
            "WHERE outbox_id = ? AND state IN (?, ?)",
            (OutboxState.CLAIMED, utc_now(), token_digest(token), outbox_id,
             OutboxState.PENDING, OutboxState.FAILED_BEFORE_SEND),
        )
        if cursor.rowcount != 1:
            raise OutboxNotClaimable(
                "Eintrag wurde zwischenzeitlich von einem anderen Lauf "
                "beansprucht")
        return self.require(outbox_id), token

    def _settle(self, outbox_id: str, claim_token: str, state: str,
                error_code: str | None) -> OutboxEntry:
        cursor = self._uow.execute(
            "UPDATE personal_external_action_outbox SET state = ?, "
            "settled_at = ?, last_error_code = ?, claim_token_digest = NULL "
            "WHERE outbox_id = ? AND claim_token_digest = ?",
            (state, utc_now(), error_code, outbox_id, token_digest(claim_token)))
        if cursor.rowcount != 1:
            raise OutboxNotClaimable(
                "Abschluss ohne gueltigen Claim — der Eintrag gehoert einem "
                "anderen Lauf")
        return self.require(outbox_id)

    def mark_succeeded(self, outbox_id: str, claim_token: str) -> OutboxEntry:
        return self._settle(outbox_id, claim_token, OutboxState.SUCCEEDED, None)

    def mark_failed_before_send(self, outbox_id: str, claim_token: str, *,
                                error_code: str) -> OutboxEntry:
        """Nachweislich nichts gesendet — der Eintrag bleibt beanspruchbar."""
        return self._settle(outbox_id, claim_token,
                            OutboxState.FAILED_BEFORE_SEND, error_code)

    def mark_outcome_unknown(self, outbox_id: str, claim_token: str, *,
                             error_code: str) -> OutboxEntry:
        """Möglicherweise gesendet — ab hier **kein** automatischer Versuch mehr."""
        return self._settle(outbox_id, claim_token,
                            OutboxState.OUTCOME_UNKNOWN, error_code)

    def recover_claimed_as_unknown(self, outbox_id: str, *,
                                   error_code: str) -> OutboxEntry:
        """Schliesst einen beanspruchten Eintrag **ohne** Token als ungewiss.

        Der Wiederanlauf ist genau der Fall, in dem es kein Token mehr gibt:
        Der Prozess, der es hielt, ist gestorben — sonst haette er selbst
        abgeschlossen. Ein Tokenzwang waere hier kein Schutz, sondern eine
        Sackgasse.

        Sicher bleibt es, weil der Weg ausschliesslich nach
        `outcome_unknown` fuehrt: er behauptet nie einen Erfolg, gibt den
        Eintrag nie wieder frei und erlaubt damit keinen zweiten Send.
        """
        cursor = self._uow.execute(
            "UPDATE personal_external_action_outbox SET state = ?, "
            "settled_at = ?, last_error_code = ?, claim_token_digest = NULL "
            "WHERE outbox_id = ? AND state = ?",
            (OutboxState.OUTCOME_UNKNOWN, utc_now(), error_code, outbox_id,
             OutboxState.CLAIMED))
        if cursor.rowcount != 1:
            raise OutboxNotClaimable(
                "Nur ein beanspruchter Eintrag kann wiederangelaufen werden")
        return self.require(outbox_id)

    def abandon(self, outbox_id: str, *, error_code: str) -> OutboxEntry:
        """Nach abgeschlossenem Abgleich endgültig aus der Warteschlange nehmen."""
        entry = self.require(outbox_id)
        if entry.state in OutboxState.TERMINAL:
            raise OutboxNotClaimable("Eintrag ist bereits abgeschlossen")
        self._uow.execute(
            "UPDATE personal_external_action_outbox SET state = ?, "
            "settled_at = ?, last_error_code = ?, claim_token_digest = NULL "
            "WHERE outbox_id = ?",
            (OutboxState.ABANDONED, utc_now(), error_code, outbox_id))
        return self.require(outbox_id)

    def resolve_unknown(self, outbox_id: str, *, succeeded: bool) -> OutboxEntry:
        """Abschluss nach Abgleich — der einzige Weg aus `outcome_unknown`."""
        entry = self.require(outbox_id)
        if entry.state != OutboxState.OUTCOME_UNKNOWN:
            raise OutboxNotClaimable(
                f"Eintrag ist '{entry.state}', nicht 'outcome_unknown'")
        ziel = OutboxState.SUCCEEDED if succeeded else OutboxState.ABANDONED
        self._uow.execute(
            "UPDATE personal_external_action_outbox SET state = ?, "
            "settled_at = ? WHERE outbox_id = ?",
            (ziel, utc_now(), outbox_id))
        return self.require(outbox_id)

    @staticmethod
    def _hydrate(row) -> OutboxEntry:
        return OutboxEntry(
            outbox_id=row["outbox_id"], module=row["module"],
            operation=row["operation"], subject_type=row["subject_type"],
            subject_id=row["subject_id"], approval_id=row["approval_id"],
            idempotency_key=row["idempotency_key"],
            payload_digest=row["payload_digest"], state=row["state"],
            attempt_count=row["attempt_count"],
            available_at=row["available_at"], created_at=row["created_at"],
            claimed_at=row["claimed_at"],
            claim_token_digest=row["claim_token_digest"],
            operation_id=row["operation_id"],
            claim_expires_at=row["claim_expires_at"],
            execution_order_issued_at=row["execution_order_issued_at"],
            execution_report_digest=row["execution_report_digest"],
            provider_completed_at=row["provider_completed_at"],
            error_class=row["error_class"], error_digest=row["error_digest"],
            settled_at=row["settled_at"], last_error_code=row["last_error_code"])
