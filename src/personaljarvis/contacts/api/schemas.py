"""Typisierte API-Verträge des Kontakte-Moduls (Plan §9.2).

**Diese Schemas sind die Sicherheitsgrenze der Eingabe.** Sie sind bewusst
`extra="forbid"`: ein unbekanntes Feld wird abgewiesen statt durchgereicht —
damit gibt es keine Mass-Assignment-Lücke. Alle Längen sind begrenzt, damit
ein Freitextfeld nicht zum Ablageort beliebiger Daten wird.

Die Domäne bleibt frei von API-Typen (AV-4): hier stehen ausschließlich
Transportmodelle, die Umwandlung geschieht in `routes.py`.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "MAX_TEXT",
    "MAX_FIELDS",
    "ContactSummaryOut",
    "ContactPageOut",
    "FieldAvailabilityOut",
    "LabeledValueOut",
    "ContactDetailOut",
    "RoleCountOut",
    "RoleAssignIn",
    "RolesOut",
    "CreateContactIn",
    "UpdateContactIn",
    "DeleteContactIn",
    "PreparedMutationOut",
    "FieldChangeOut",
    "MutationOut",
    "MutationDetailOut",
    "ApprovalOut",
    "ApprovalDecisionIn",
    "ReconcileOut",
    "SyncStatusOut",
    "AuthorizationOut",
    "AuthorizationRequestIn",
    "SyncRunOut",
    "CapabilitiesOut",
    "ErrorOut",
]

#: Obergrenze für jedes einzelne Textfeld einer Nutzlast.
MAX_TEXT = 512
#: Obergrenze für die Feldanzahl eines Entwurfs bzw. Patches. Begrenzt die
#: Request-Größe, ohne eine feste Feldliste im Transport zu zementieren.
MAX_FIELDS = 40


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


# ── Ausgabe: Kontakte ───────────────────────────────────────────────────────
class ContactSummaryOut(_Strict):
    id: str
    display_name: str
    organization_name: str | None = None
    contact_type: str
    is_me_card: bool
    field_completeness: str
    sync_state: str
    conflict_state: str | None = None
    roles: list[str] = Field(default_factory=list)
    provider_account_ids: list[str] = Field(default_factory=list)
    email_count: int = 0
    phone_count: int = 0
    address_count: int = 0
    has_unavailable_fields: bool = False


class ContactPageOut(_Strict):
    items: list[ContactSummaryOut]
    next_cursor: str | None = None
    has_more: bool = False


class FieldAvailabilityOut(_Strict):
    field_name: str
    state: Literal["present", "absent", "unavailable_by_capability"]


class LabeledValueOut(_Strict):
    id: str
    position: int
    label_raw: str | None = None
    label_normalized: str | None = None
    value: str | None = None
    extra: dict[str, Any] = Field(default_factory=dict)


class ContactDetailOut(_Strict):
    id: str
    workspace_id: str
    display_name: str
    contact_type: str
    given_name: str | None = None
    middle_name: str | None = None
    family_name: str | None = None
    nickname: str | None = None
    organization_name: str | None = None
    department_name: str | None = None
    job_title: str | None = None
    is_me_card: bool = False
    birthday_year: int | None = None
    birthday_month: int | None = None
    birthday_day: int | None = None
    local_revision: int = 1
    sync_state: str = "in_sync"
    conflict_state: str | None = None
    field_completeness: str = "full"
    updated_at: str | None = None
    #: **Nur eine Referenz**, nie das Bild selbst (Plan §9.2).
    thumbnail_blob_ref: str | None = None
    emails: list[LabeledValueOut] = Field(default_factory=list)
    phones: list[LabeledValueOut] = Field(default_factory=list)
    postal_addresses: list[LabeledValueOut] = Field(default_factory=list)
    urls: list[LabeledValueOut] = Field(default_factory=list)
    dates: list[LabeledValueOut] = Field(default_factory=list)
    social_profiles: list[LabeledValueOut] = Field(default_factory=list)
    instant_messages: list[LabeledValueOut] = Field(default_factory=list)
    relations: list[LabeledValueOut] = Field(default_factory=list)
    roles: list[str] = Field(default_factory=list)
    field_availability: list[FieldAvailabilityOut] = Field(default_factory=list)
    #: Providerherkunft **ohne** Roh-Identifier: Konto und Container genügen
    #: der Anzeige; die Provider-ID wird nur dort ausgegeben, wo sie technisch
    #: gebraucht wird (Mutationsziel).
    provider_accounts: list[str] = Field(default_factory=list)
    containers: list[str] = Field(default_factory=list)
    #: Schreibziel für Update/Delete. Ohne dieses Feld könnte die UI nur über
    #: einen Namen zielen — genau das ist verboten (Plan §7.1).
    write_target: str | None = None
    unified_read_only: bool = True


class RoleCountOut(_Strict):
    role: str
    count: int


class RoleAssignIn(_Strict):
    role: str = Field(min_length=1, max_length=64)


class RolesOut(_Strict):
    contact_id: str
    roles: list[str]


# ── Eingabe: Mutationen ─────────────────────────────────────────────────────
class _MutationBase(_Strict):
    idempotency_key: str = Field(min_length=1, max_length=128)
    correlation_id: str = Field(min_length=1, max_length=128)
    provider_account_id: str = Field(min_length=1, max_length=128)
    initiation_context: Literal["user_direct", "llm_assisted", "automation",
                                "system"] = "user_direct"


class CreateContactIn(_MutationBase):
    container_identifier: str = Field(min_length=1, max_length=256)
    fields: dict[str, Any] = Field(max_length=MAX_FIELDS)


class UpdateContactIn(_MutationBase):
    target_provider_identifier: str = Field(min_length=1, max_length=256)
    expected_revision: str | None = Field(default=None, max_length=64)
    fields: dict[str, Any] = Field(max_length=MAX_FIELDS)


class DeleteContactIn(_MutationBase):
    target_provider_identifier: str = Field(min_length=1, max_length=256)
    expected_revision: str | None = Field(default=None, max_length=64)


class FieldChangeOut(_Strict):
    field_name: str
    previous: Any = None
    planned: Any = None


class PreparedMutationOut(_Strict):
    mutation_id: str
    approval_id: str
    state: str
    payload_digest: str
    preview_digest: str
    reused: bool = False
    command: str
    target_provider_identifier: str | None = None
    container_identifier: str | None = None
    target_label: str | None = None
    changes: list[FieldChangeOut] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class MutationOut(_Strict):
    mutation_id: str
    command: str
    state: str
    outcome: str | None = None
    initiation_context: str
    actor: str
    correlation_id: str
    provider_account_id: str
    target_contact_id: str | None = None
    target_display_name: str | None = None
    container_identifier: str | None = None
    expected_revision: str | None = None
    attempt_count: int = 0
    last_error_code: str | None = None
    created_at: str
    approved_at: str | None = None
    completed_at: str | None = None
    approval_id: str | None = None
    approval_state: str | None = None
    approval_expires_at: str | None = None
    requires_reconcile: bool = False
    needs_manual_decision: bool = False


class MutationDetailOut(MutationOut):
    changes: list[FieldChangeOut] = Field(default_factory=list)
    payload_digest: str = ""
    preview_digest: str = ""


class ApprovalOut(_Strict):
    approval_id: str
    mutation_id: str
    command: str
    state: str
    initiation_context: str
    actor: str
    correlation_id: str
    requested_at: str
    expires_at: str
    decided_at: str | None = None
    decision_actor: str | None = None
    preview_digest: str
    is_expired: bool = False


class ApprovalDecisionIn(_Strict):
    #: Der entscheidende Mensch. `llm_assisted`, `automation` und `system`
    #: werden vom Freigabekern abgewiesen (05 §5) — hier ist das Feld nur
    #: Transport.
    decision_actor: str = Field(min_length=1, max_length=128)


class ReconcileOut(_Strict):
    mutation_id: str
    verdict: str
    state: str
    provider_identifier: str | None = None
    detail: str | None = None


class SyncStatusOut(_Strict):
    provider_account_id: str
    container_identifier: str
    mode: str
    circuit_state: str
    key_set_version: str
    has_cursor: bool
    cursor_taken_at: str | None = None
    last_full_diff_at: str | None = None
    updated_at: str


class AuthorizationOut(_Strict):
    """Autorisierungszustand. `status` wird gelesen, nie geraten."""

    status: Literal["notDetermined", "restricted", "denied", "authorized",
                    "unknown"]
    can_request: bool
    bridge_available: bool
    reason: str = ""


class AuthorizationRequestIn(_Strict):
    """Ausdrückliche Nutzeraktion.

    Das Feld ist Pflicht und muss `True` sein: ein Aufrufer kann den Dialog
    nicht versehentlich auslösen, indem er den Körper weglässt.
    """

    user_initiated: Literal[True]


class SyncRunOut(_Strict):
    """Ergebnis eines Laufs — ausschließlich aggregierte Werte.

    Kein Cursor, kein Token, kein Provider-Identifier, kein Kontaktwert.
    """

    mode: Literal["initial_import", "full_diff", "delta"]
    succeeded: bool
    containers: int
    read: int
    imported: int
    updated: int
    tombstoned: int
    unchanged: int
    events_processed: int
    cursor_present: bool
    cursor_advanced: bool
    requires_full_diff: bool
    error_class: str | None = None
    retryable: bool = False
    detail: str = ""
    completed_at: str


class CapabilitiesOut(_Strict):
    read_supported: bool
    create_supported: bool
    update_supported: bool
    delete_supported: bool
    change_history_supported: bool
    full_diff_supported: bool
    notes_supported: bool
    unified_read_supported: bool
    unified_link_supported: bool
    me_card_writable: bool
    unavailable_fields: list[str] = Field(default_factory=list)
    mutations_available: bool = False


class ErrorOut(_Strict):
    """Fehlerhülle. Trägt **nie** einen Kontaktwert (08 §3 Nr. 5)."""

    code: str
    message: str
    retryable: bool = False
