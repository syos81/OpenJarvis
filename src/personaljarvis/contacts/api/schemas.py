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

from personaljarvis.contacts.application import field_contract as FC

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
    "ContactFieldsIn",
    "LabeledValueIn",
    "PostalAddressIn",
    "BirthdayIn",
    "DateIn",
    "UpdateContactIn",
    "DeleteContactIn",
    "ExecuteMutationIn",
    "ExecutionResultOut",
    "CONTAINER_REF_PATTERN",
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
    "RecoveryRunIn",
    "RecoveryRunOut",
    "CapabilitiesOut",
    "ErrorOut",
]

#: Obergrenze für jedes einzelne Textfeld einer Nutzlast.
MAX_TEXT = 512
#: Obergrenze für die Feldanzahl eines Entwurfs bzw. Patches. Begrenzt die
#: Request-Größe, ohne eine feste Feldliste im Transport zu zementieren.
MAX_FIELDS = 40

#: Form der maskierten Containerreferenz (`api.redaction.container_ref`).
#: Das Muster steht hier, damit eine rohe Apple-Kennung schon an der
#: Transportgrenze abprallt und gar nicht erst in die Aufloesung gerät.
CONTAINER_REF_PATTERN = r"^C-[0-9a-f]{6}$"


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
    #: Maskierte Kontoreferenzen. Die Oberflaeche braucht nur ihre **Anzahl**
    #: („aus 2 Quellen"); die rohe Kontokennung hat sie nie benutzt.
    account_refs: list[str] = Field(default_factory=list)
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
    #: Providerherkunft ausschliesslich maskiert (ADR-0019 §2).
    account_refs: list[str] = Field(default_factory=list)
    container_refs: list[str] = Field(default_factory=list)
    provider_type: str = "unknown"
    #: Ob dieser Kontakt überhaupt Ziel einer Mutation sein kann. Trat an die
    #: Stelle von `write_target`: die Oberfläche brauchte davon nie den Wert,
    #: sondern nur die Aussage — und zielt seither über die lokale `id`.
    writable: bool = False
    #: Lokale Revision als Konfliktbedingung für `update`/`delete`. Sie ist
    #: eine Zahl aus der eigenen Datenbank, keine Apple-Kennung.
    revision: str = "1"
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
#
# Keine Eingabe nennt mehr eine rohe Apple-Kennung. Ziel eines `update` oder
# `delete` ist die lokale `contact_id` im Pfad; Ziel eines `create` ist eine
# maskierte `container_ref`. Die Aufloesung auf die echten Kennungen geschieht
# im Backend und ist fail-closed (ADR-0019 §2).
class _MutationBase(_Strict):
    idempotency_key: str = Field(min_length=1, max_length=128)
    correlation_id: str = Field(min_length=1, max_length=128)
    initiation_context: Literal["user_direct", "llm_assisted", "automation",
                                "system"] = "user_direct"


class LabeledValueIn(_Strict):
    """Ein etikettierter Wert. Das Label kommt aus geschlossenem Vorrat."""

    label: str | None = Field(default=None, max_length=32)
    value: str = Field(min_length=1, max_length=FC.MAX_URL)


class PostalAddressIn(_Strict):
    label: str | None = Field(default=None, max_length=32)
    street: str | None = Field(default=None, max_length=MAX_TEXT)
    city: str | None = Field(default=None, max_length=MAX_TEXT)
    state: str | None = Field(default=None, max_length=MAX_TEXT)
    postal_code: str | None = Field(default=None, max_length=MAX_TEXT)
    country: str | None = Field(default=None, max_length=MAX_TEXT)
    iso_country_code: str | None = Field(default=None, max_length=2)


class BirthdayIn(_Strict):
    year: int | None = Field(default=None, ge=1, le=9999)
    month: int = Field(ge=1, le=12)
    day: int = Field(ge=1, le=31)


class DateIn(BirthdayIn):
    label: str | None = Field(default=None, max_length=32)


class ContactFieldsIn(_Strict):
    """Feldvertrag v1 als Transportmodell — die geschlossene Feldmenge.

    `extra="forbid"` weist ein unbekanntes Feld schon hier ab; die fachliche
    Pruefung (Labelvorrat, Grenzen, Normalisierung) macht danach
    `application.field_contract`. Zwei Schranken, eine Wahrheit: was hier
    steht, muss dort ankommen.
    """

    contact_type: Literal["person", "organization"] = "person"
    given_name: str | None = Field(default=None, max_length=MAX_TEXT)
    middle_name: str | None = Field(default=None, max_length=MAX_TEXT)
    family_name: str | None = Field(default=None, max_length=MAX_TEXT)
    previous_family_name: str | None = Field(default=None, max_length=MAX_TEXT)
    name_prefix: str | None = Field(default=None, max_length=MAX_TEXT)
    name_suffix: str | None = Field(default=None, max_length=MAX_TEXT)
    nickname: str | None = Field(default=None, max_length=MAX_TEXT)
    phonetic_given_name: str | None = Field(default=None, max_length=MAX_TEXT)
    phonetic_family_name: str | None = Field(default=None, max_length=MAX_TEXT)
    organization_name: str | None = Field(default=None, max_length=MAX_TEXT)
    department_name: str | None = Field(default=None, max_length=MAX_TEXT)
    job_title: str | None = Field(default=None, max_length=MAX_TEXT)
    birthday: BirthdayIn | None = None
    emails: list[LabeledValueIn] = Field(default_factory=list, max_length=10)
    phones: list[LabeledValueIn] = Field(default_factory=list, max_length=10)
    postal_addresses: list[PostalAddressIn] = Field(default_factory=list,
                                                    max_length=5)
    urls: list[LabeledValueIn] = Field(default_factory=list, max_length=10)
    dates: list[DateIn] = Field(default_factory=list, max_length=5)

    def as_field_mapping(self) -> dict[str, Any]:
        """Nur ausdrücklich gesetzte Felder — `None` heisst „nicht gesetzt"."""
        return {k: v for k, v in self.model_dump().items() if v not in (None, [])}


class CreateContactIn(_MutationBase):
    #: Maskierte Containerreferenz. Eine rohe Apple-Kennung wird hier bereits
    #: vom Muster abgewiesen.
    container_ref: str = Field(pattern=CONTAINER_REF_PATTERN)
    fields: ContactFieldsIn


class UpdateContactIn(_MutationBase):
    """Ziel ist die lokale `contact_id` im Pfad, nie eine Providerkennung."""

    expected_revision: str = Field(min_length=1, max_length=64)
    fields: dict[str, Any] = Field(max_length=MAX_FIELDS)


class DeleteContactIn(_MutationBase):
    expected_revision: str = Field(min_length=1, max_length=64)


class ExecuteMutationIn(_Strict):
    """Die ausdrückliche Nutzeraktion, die eine Ausführung auslöst.

    `Literal[True]` und `extra="forbid"`: es gibt keinen Aufruf ohne bewusste
    Bestätigung im Rumpf, und kein Query-Parameter kann sie ersetzen. Eine
    Freigabe allein führt nichts aus (ADR-0019 §1).
    """

    user_initiated: Literal[True]


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
    #: Lokale Zielkennung — bei `create` erst nach der Ausführung bekannt.
    target_contact_id: str | None = None
    container_ref: str | None = None
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
    provider_type: str = "unknown"
    account_ref: str = ""
    target_contact_id: str | None = None
    target_display_name: str | None = None
    container_ref: str | None = None
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
    """Ergebnis des Abgleichs — ohne Providerkennung.

    Die frühere `provider_identifier` war die einzige rohe Apple-Kennung in
    einer Abgleichantwort und wurde von der Oberfläche nie angezeigt. Wer den
    betroffenen Kontakt sucht, findet ihn über `contact_id`.
    """

    mutation_id: str
    verdict: str
    state: str
    contact_id: str | None = None
    detail: str | None = None


class ExecutionResultOut(_Strict):
    """Ergebnis eines Ausführungsversuchs — aggregiert und maskiert."""

    mutation_id: str
    state: str
    outcome: str | None = None
    error_code: str | None = None
    retryable: bool = False
    attempt_count: int = 0
    #: Lokale Kennung des angelegten Spiegels — erst nach der Nachführung.
    contact_id: str | None = None
    #: Ob der Vorgang noch eine lokale Nacharbeit braucht. Ein `true` heisst
    #: ausdrücklich **nicht**, dass erneut gesendet werden darf.
    pending_local_catchup: bool = False


class SyncStatusOut(_Strict):
    """Sync-Zustand je Konto × Container — **ohne** rohe Providerkennungen.

    Bis zum 2026-07-31 standen hier `provider_account_id` und
    `container_identifier` im Klartext, also eine Apple-interne Kontoidentität
    in jeder Antwort, jedem Log und jedem Screenshot. Gebraucht wurde davon
    nie der Wert, sondern nur die Unterscheidbarkeit der Zeilen — und die
    leisten `account_ref` und `container_ref` (siehe `api.redaction`).

    Was hier nie stehen darf: rohe Provider- oder Containerkennungen, Cursor-
    oder Change-History-Token, Dateipfade, Kontaktwerte. `cursor_taken_at` ist
    ein Zeitstempel, kein Token.
    """

    #: Stabile Gattung statt Kontokennung, z. B. `apple_contacts`.
    provider_type: str
    account_ref: str
    container_ref: str
    mode: str
    circuit_state: str
    key_set_version: str
    cursor_present: bool
    cursor_taken_at: str | None = None
    last_full_diff_at: str | None = None
    #: Letzter Lauf, der den Zustand fortgeschrieben hat. Beide Quellstempel
    #: werden ausschließlich nach Erfolg gesetzt.
    last_successful_run_at: str | None = None
    #: Spiegelt die Bedingung aus `sync.state.derive_cursor_state`: alles
    #: außer `CursorState.ACTIVE` verlangt einen Voll-Diff.
    requires_full_diff: bool = False
    updated_at: str


class AuthorizationOut(_Strict):
    """Autorisierungszustand. `status` wird gelesen, nie geraten."""

    status: Literal["notDetermined", "restricted", "denied", "authorized",
                    "unknown"]
    can_request: bool
    bridge_available: bool
    #: Satz für den Menschen — nie ein Klassenname, nie ein Pfad.
    reason: str = ""
    #: Stabile, PII-freie Vertragskennung des Fehlerbildes; leer wenn alles ging.
    technical_code: str = ""


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


class RecoveryRunIn(_Strict):
    """Zwei ausdrückliche Bestätigungen, beide Pflicht.

    Die Wiederherstellung greift in den kanonischen Bestand ein. Sie darf
    weder durch einen leeren Körper noch durch einen versehentlichen Aufruf
    auslösbar sein — deshalb `Literal[True]` statt `bool`.
    """

    user_initiated: Literal[True]
    confirm_reactivation: Literal[True]


class RecoveryRunOut(_Strict):
    """Ergebnis — ausschliesslich aggregiert.

    Kein Name, kein Provider-Identifier, keine Containerkennung, kein Cursor,
    kein Pfad, kein Kontaktwert.
    """

    status: Literal["recovered", "not_applicable", "failed"]
    containers_checked: int = 0
    contacts_received: int = 0
    reactivated: int = 0
    tombstones_reconciled: int = 0
    still_absent: int = 0
    local_ids_preserved: bool = True
    full_diff_required: bool = True
    cursor_present: bool = False
    mutations_performed: bool = False
    completed_at: str = ""
    technical_code: str = ""
    retryable: bool = False


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
