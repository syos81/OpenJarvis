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
    """Zustandsmaschine der Mutationspipeline (contacts.md §7.2, Migration 0004).

    Wortgleich mit dem CHECK-Constraint der Tabelle `contacts_mutations` — es
    gibt genau **eine** Wahrheit über den Zustandsvorrat.

    Zwei Zustände sind bewusst getrennt und dürfen nie zusammenfallen:

    * `FAILED_BEFORE_SEND` — nachweislich **nichts** gesendet, gefahrlos.
    * `OUTCOME_UNKNOWN` — **möglicherweise** gesendet. Weder Erfolg noch
      Fehlschlag; von dort führt genau ein Weg weiter, und der heißt
      `RECONCILE_REQUIRED` — also zuerst lesen, nie wiederholen.

    Seit 0006 gibt es dazwischen einen dritten, ebenfalls getrennten Zustand:

    * `PROVIDER_APPLIED_PENDING_RECONCILE` — **bewiesen** gesendet und
      angewandt, aber der kanonische Spiegel ist noch nicht nachgeführt. Er
      ist das Gegenteil von `OUTCOME_UNKNOWN`: dort ist nichts bewiesen, hier
      alles. Aus ihm führt nie ein weiterer Send, sondern ausschliesslich die
      Wiederholung der **lokalen** Nachführung (ADR-0019 §5).
    """

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
    PROVIDER_APPLIED_PENDING_RECONCILE = "provider_applied_pending_reconcile"
    RECONCILE_REQUIRED = "reconcile_required"
    MANUAL_DECISION_REQUIRED = "manual_decision_required"
    #: Ein Mensch hat den Provider ausserhalb von Jarvis geprüft und die
    #: Änderung dort nicht beobachtet. Terminal — und ausdrücklich **nicht**
    #: dasselbe wie `FAILED_BEFORE_SEND`: gesendet wurde, nur ohne Wirkung.
    MANUALLY_RESOLVED_NOT_APPLIED = "manually_resolved_not_applied"
    FAILED = "failed"


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
