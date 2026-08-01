"""Vorschau, Nutzlast und Ergebnistypen der Mutationspipeline.

**Trennung, die den Datenschutz trägt:** Die *Vorschau* enthält die konkreten
vorherigen und geplanten Werte — der Nutzer muss sehen, was passiert (10 §1).
Sie wird **zurückgegeben, nicht persistiert**. Persistiert werden nur Digests
(Freigabe, Outbox, Audit). Die zur Ausführung nötige Nutzlast liegt allein in
`contacts_mutations.payload_json`, also in derselben kanonischen Datenbank, in
der die Kontaktdaten ohnehin leben.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from personaljarvis.base.digest import digest_of

__all__ = [
    "FieldChange",
    "MutationPreview",
    "MutationPayload",
    "PreparedMutation",
    "ProviderOutcome",
    "SendPhase",
    "ExecutionResult",
    "ReconcileVerdict",
    "ReconcileResult",
]


@dataclass(frozen=True)
class FieldChange:
    """Ein Feld mit vorherigem und geplantem Wert."""

    field_name: str
    previous: Any
    planned: Any


@dataclass(frozen=True)
class MutationPreview:
    """Was der Nutzer vor der Freigabe sieht (05 §4 Nr. 7).

    Für `update` zeigt sie vorher/nachher je Feld, für `delete` den Zielkontakt
    knapp und ohne unnötige PII, für `create` die geplanten Felder.
    """

    command: str
    target_provider_identifier: str | None
    container_identifier: str | None
    changes: tuple[FieldChange, ...] = ()
    target_label: str | None = None
    warnings: tuple[str, ...] = ()
    #: Lokale Zielkennung — sie und nicht die Providerkennung geht nach aussen.
    target_contact_id: str | None = None

    @property
    def digest(self) -> str:
        """Digest der Vorschau — bindet die Freigabe an das Gezeigte."""
        return digest_of({
            "command": self.command,
            "target": self.target_provider_identifier,
            "container": self.container_identifier,
            "changes": [
                {"field": c.field_name, "previous": c.previous,
                 "planned": c.planned} for c in self.changes
            ],
            "warnings": list(self.warnings),
        })


@dataclass(frozen=True)
class MutationPayload:
    """Die zur Ausführung nötige Nutzlast — deterministisch serialisierbar."""

    command: str
    provider_account_id: str
    container_identifier: str | None
    target_provider_identifier: str | None
    expected_revision: str | None
    fields: Mapping[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "command": self.command,
            "providerAccountId": self.provider_account_id,
            "containerIdentifier": self.container_identifier,
            "targetProviderIdentifier": self.target_provider_identifier,
            "expectedRevision": self.expected_revision,
            "fields": dict(sorted(self.fields.items())),
        }

    @property
    def digest(self) -> str:
        return digest_of(self.as_dict())


@dataclass(frozen=True)
class PreparedMutation:
    """Ergebnis der Vorbereitung — noch **keine** Ausführung."""

    mutation_id: str
    approval_id: str
    outbox_id: str
    state: str
    payload_digest: str
    preview: MutationPreview
    reused: bool = False


class SendPhase:
    """Wo ein Fehler auftrat — die sicherheitsrelevante Unterscheidung."""

    #: Nachweislich nichts gesendet. Gefahrlos wiederholbar.
    BEFORE_SEND = "before_send"
    #: Möglicherweise gesendet. **Nie** automatisch wiederholen.
    AFTER_POSSIBLE_SEND = "after_possible_send"


class ProviderOutcome:
    """Was die Fake- bzw. echte Bridge zurückmeldet."""

    SUCCEEDED = "succeeded"
    REJECTED_BEFORE_SEND = "rejected_before_send"
    CONFLICT = "conflict"
    FAILED_BEFORE_SEND = "failed_before_send"
    OUTCOME_UNKNOWN = "outcome_unknown"

    ALL = frozenset({SUCCEEDED, REJECTED_BEFORE_SEND, CONFLICT,
                     FAILED_BEFORE_SEND, OUTCOME_UNKNOWN})


@dataclass(frozen=True)
class ExecutionResult:
    """Ergebnis eines Ausführungsversuchs."""

    mutation_id: str
    state: str
    outcome: str | None
    error_code: str | None = None
    provider_identifier: str | None = None
    attempt_count: int = 0
    #: Lokale Kennung des kanonischen Spiegels — erst nach der Nachführung (C2).
    contact_id: str | None = None
    #: Fingerabdruck des zurückgelesenen Providerzustands (ADR-0019 §5).
    readback_digest: str | None = None

    @property
    def requires_reconcile(self) -> bool:
        return self.state in ("outcome_unknown", "reconcile_required")

    @property
    def pending_local_catchup(self) -> bool:
        """Beim Provider angewandt, lokal noch nicht nachgeführt."""
        return self.state == "provider_applied_pending_reconcile"


class ReconcileVerdict:
    """Was der Abgleich am Provider gefunden hat."""

    APPLIED = "applied"
    NOT_APPLIED = "not_applied"
    AMBIGUOUS = "ambiguous"


@dataclass(frozen=True)
class ReconcileResult:
    mutation_id: str
    verdict: str
    state: str
    provider_identifier: str | None = None
    detail: str | None = None
