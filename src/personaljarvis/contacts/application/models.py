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
    #: Art des Zielablageorts aus dem geschlossenen Vorrat
    #: (`local | cardDAV | exchange | unassigned | unknown`). Sie gehört in die
    #: Vorschau, weil „wohin" ohne sie nicht beantwortet ist: Eine Kennung
    #: allein sagt dem Menschen nicht, ob er in den lokalen Ablageort oder in
    #: ein Konto schreibt (§8 A, ADR-0025 §2).
    container_type: str | None = None
    #: Lesbarer Name des Zielablageorts aus dem **Bestand** — nie im Frontend
    #: gebildet und nie aus der Kennung abgeleitet. `None` heisst „noch nicht
    #: gelesen": Vor dem ersten Sync nach Migration 0012 trägt der Bestand
    #: keinen Namen, und die Fläche sagt das offen, statt die Kennung als
    #: Namen auszugeben. Ein stiller Rückfall behauptete Wissen, das niemand
    #: hat.
    container_name: str | None = None
    #: Wie viele Kontakte der Zielablageort derzeit führt. **Kontext, nicht
    #: Kategorie**: Eine Null macht aus einem synchronisierten Konto keinen
    #: lokalen Ablageort. Die kategoriale Aussage steht in `container_type`.
    container_contact_count: int | None = None

    @property
    def digest(self) -> str:
        """Digest der Vorschau — bindet die Freigabe an das Gezeigte.

        Der Zielablageort ist seit 2026-08-13 mit **Art** gedeckt, nicht mehr
        nur mit Kennung. Die Anzeige ist Bestandteil der informierten
        Freigabe: Was gezeigt wurde, muss der Digest binden — sonst deckte die
        Freigabe eine andere Darstellung derselben Nutzlast, und genau davor
        schützt die Digestbindung in `consume()`.
        """
        return digest_of({
            "command": self.command,
            "target": self.target_provider_identifier,
            "container": self.container_identifier,
            "containerType": self.container_type,
            # Name und Anzahl stehen auf der Flaeche, also bindet der Digest
            # sie. Sonst deckte die Freigabe dieselbe Nutzlast unter einem
            # anderen Zielnamen — und der Zielname ist die Angabe, an der ein
            # Mensch „wohin" erkennt.
            "containerName": self.container_name,
            "containerContactCount": self.container_contact_count,
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
    #: Der kanonische v1-Zustand des Ziels, wie ihn der Mensch in der
    #: Vorschau sieht (ADR-0026 §8.2/§8.3). Nur bei `update` und `delete`.
    #: Er gehört in die Nutzlast und nicht in einen Seitenkanal: Nur so
    #: deckt ihn der `payload_digest` — und damit die Freigabe.
    expected_previous: Mapping[str, Any] | None = None
    #: `readback_digest` genau dieser Projektion. Der native Pfad prüft
    #: damit, dass der Vergleichsmassstab derselbe ist wie der freigegebene.
    expected_fields_digest: str | None = None

    def as_dict(self) -> dict:
        out = {
            "command": self.command,
            "providerAccountId": self.provider_account_id,
            "containerIdentifier": self.container_identifier,
            "targetProviderIdentifier": self.target_provider_identifier,
            "expectedRevision": self.expected_revision,
            "fields": dict(sorted(self.fields.items())),
        }
        # Bewusst nur wenn vorhanden: Ein `create` hat keinen Vorzustand,
        # und ein `null` im Payload änderte seinen Digest ohne Aussage.
        if self.expected_previous is not None:
            out["expectedPrevious"] = dict(self.expected_previous)
            out["expectedFieldsDigest"] = self.expected_fields_digest
        return out

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
    #: Fingerabdruck des zurückgelesenen Providerzustands (ADR-0025 §5).
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
