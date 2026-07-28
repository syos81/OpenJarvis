"""Geschlossene Wertemengen der Kontakte-Domäne.

Alle Werte entsprechen wortgleich den CHECK-Constraints der Migration 0002 —
die Datenbank und die Domäne teilen dieselbe Wahrheit, aber die Domäne kennt
kein SQL und keinen Apple-Typ (AV-4).
"""

from __future__ import annotations

from enum import Enum

__all__ = [
    "ContactType",
    "FieldAvailabilityState",
    "SyncState",
    "SyncMode",
    "CircuitState",
    "FieldCompleteness",
    "MutationState",
    "MutationOutcome",
    "InitiationContext",
    "SensitivityLabel",
]


class _StrEnum(str, Enum):
    def __str__(self) -> str:  # pragma: no cover — Komfort
        return self.value


class ContactType(_StrEnum):
    PERSON = "person"
    ORGANIZATION = "organization"


class FieldAvailabilityState(_StrEnum):
    """Drei Zustände — und `ABSENT` ist **nicht** `UNAVAILABLE_BY_CAPABILITY`.

    `ABSENT` heißt: der Provider hat das Feld geliefert, es ist leer.
    `UNAVAILABLE_BY_CAPABILITY` heißt: der Provider konnte es nicht liefern.
    Die zweite Aussage darf nie zur ersten werden — sonst löscht eine
    Synchronisation vorhandene Daten (08 §4).
    """

    PRESENT = "present"
    ABSENT = "absent"
    UNAVAILABLE_BY_CAPABILITY = "unavailable_by_capability"


class SyncState(_StrEnum):
    IN_SYNC = "in_sync"
    LOCAL_PENDING = "local_pending"
    REMOTE_PENDING = "remote_pending"
    CONFLICTED = "conflicted"
    ATTENTION_REQUIRED = "attention_required"


class SyncMode(_StrEnum):
    DELTA = "delta"
    FULL_DIFF_REQUIRED = "full_diff_required"


class CircuitState(_StrEnum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"
    REAUTH_REQUIRED = "reauth_required"


class FieldCompleteness(_StrEnum):
    FULL = "full"
    PARTIAL = "partial"


class MutationState(_StrEnum):
    """Zustandsmaschine aus contacts.md §7.2.

    `OUTCOME_UNKNOWN` ist **weder** Erfolg **noch** Fehlschlag. Von dort führt
    genau ein Weg weiter: `RECONCILE_REQUIRED` — also zuerst lesen.
    """

    DRAFT = "draft"
    VALIDATED = "validated"
    PREVIEWED = "previewed"
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    EXECUTING = "executing"
    VERIFYING = "verifying"
    COMPLETED = "completed"
    FAILED = "failed"
    OUTCOME_UNKNOWN = "outcome_unknown"
    RECONCILE_REQUIRED = "reconcile_required"
    MANUAL_DECISION_REQUIRED = "manual_decision_required"
    DENIED = "denied"
    EXPIRED = "expired"
    ABORTED = "aborted"


class MutationOutcome(_StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    OUTCOME_UNKNOWN = "outcome_unknown"


class InitiationContext(_StrEnum):
    """05 §5 — bestimmt zusammen mit der Risikoklasse die Bestätigungsform."""

    USER_DIRECT = "user_direct"
    LLM_ASSISTED = "llm_assisted"
    AUTOMATION = "automation"
    SYSTEM = "system"


class SensitivityLabel(_StrEnum):
    """Egress-Klassen aus 12 §1. Getrennt von den Rohlabels des Providers."""

    S0 = "S0"
    S1 = "S1"
    S2 = "S2"
