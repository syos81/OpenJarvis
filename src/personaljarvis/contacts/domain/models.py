"""Fachliche Typen der Kontakte-Domäne.

Alle Typen sind **unveränderlich** (`frozen=True`). Eine Änderung erzeugt ein
neues Objekt; damit kann kein Repository und kein Handler ein Domänenobjekt
hinter dem Rücken seines Eigentümers verändern.

Ausdrückliche Grenzen (08 §4, contacts.md §5):

* Kein Apple-Typ und kein `sqlite3.Row` überquert diese Grenze.
* `unified_identifier` ist **nur lesend** — es gibt keinen Konstruktor und
  keine Methode, die ihn zum Schreibziel macht.
* Die Me-Karte ist in v1 **schreibgeschützt**; `Contact.with_changes` lehnt
  eine Änderung ab.
* Notizen sind kein Feld dieser Typen. Ihr Zustand lebt ausschließlich in
  `ContactFieldAvailability`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Iterable

from personaljarvis.contacts.domain.enums import (
    ContactType,
    FieldAvailabilityState,
    FieldCompleteness,
    InitiationContext,
    MutationOutcome,
    MutationState,
    SyncState,
)
from personaljarvis.errors import IntegrityError

__all__ = [
    "utc_now",
    "LabeledValue",
    "EmailAddress",
    "PhoneNumber",
    "PostalAddress",
    "ContactDate",
    "UrlAddress",
    "SocialProfile",
    "InstantMessageAddress",
    "ContactRelation",
    "ContactRole",
    "ContactFieldAvailability",
    "ExternalIdentifier",
    "Organization",
    "OrganizationMembership",
    "Contact",
    "ContactSyncState",
    "ContactTombstone",
    "ContactMutation",
]

_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE
)


def utc_now() -> str:
    """UTC-Zeitstempel in ISO-8601 (07 §4)."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _require_uuid(value: str, name: str) -> str:
    if not _UUID_RE.match(value or ""):
        raise IntegrityError(f"{name} ist keine gültige UUID")
    return value


def _require_nonempty(value: str, name: str) -> str:
    if not value or not value.strip():
        raise IntegrityError(f"{name} darf nicht leer sein")
    return value


def _ordered(values: Iterable) -> tuple:
    """Stabile Reihenfolge nach `position` — nie nach Einfügereihenfolge."""
    items = tuple(values)
    positions = [v.position for v in items]
    if len(set(positions)) != len(positions):
        raise IntegrityError("Positionen innerhalb eines Kontakts sind nicht eindeutig")
    if any(p < 0 for p in positions):
        raise IntegrityError("Position darf nicht negativ sein")
    return tuple(sorted(items, key=lambda v: v.position))


# ── Gelabelte Mehrfachwerte ──────────────────────────────────────────────────
@dataclass(frozen=True)
class LabeledValue:
    """Gemeinsame Grundform: Rohlabel bleibt erhalten, normalisiert daneben."""

    id: str
    position: int
    label_raw: str | None = None
    label_normalized: str | None = None

    def __post_init__(self) -> None:
        _require_uuid(self.id, "id")
        if self.position < 0:
            raise IntegrityError("position darf nicht negativ sein")


@dataclass(frozen=True)
class EmailAddress(LabeledValue):
    value_raw: str = ""
    value_normalized: str = ""

    def __post_init__(self) -> None:
        super().__post_init__()
        _require_nonempty(self.value_raw, "E-Mail")
        _require_nonempty(self.value_normalized, "normalisierte E-Mail")


@dataclass(frozen=True)
class PhoneNumber(LabeledValue):
    value_raw: str = ""
    value_normalized_e164: str | None = None

    def __post_init__(self) -> None:
        super().__post_init__()
        _require_nonempty(self.value_raw, "Telefonnummer")


@dataclass(frozen=True)
class PostalAddress(LabeledValue):
    street: str | None = None
    sub_locality: str | None = None
    city: str | None = None
    state: str | None = None
    postal_code: str | None = None
    country: str | None = None
    iso_country_code: str | None = None


@dataclass(frozen=True)
class ContactDate(LabeledValue):
    kind: str = ""
    year: int | None = None
    month: int | None = None
    day: int | None = None

    def __post_init__(self) -> None:
        super().__post_init__()
        _require_nonempty(self.kind, "Datumsart")
        if self.month is not None and not 1 <= self.month <= 12:
            raise IntegrityError("Monat außerhalb des gültigen Bereichs")
        if self.day is not None and not 1 <= self.day <= 31:
            raise IntegrityError("Tag außerhalb des gültigen Bereichs")


@dataclass(frozen=True)
class UrlAddress(LabeledValue):
    value_raw: str = ""
    value_normalized: str = ""

    def __post_init__(self) -> None:
        super().__post_init__()
        _require_nonempty(self.value_raw, "URL")
        _require_nonempty(self.value_normalized, "normalisierte URL")


@dataclass(frozen=True)
class SocialProfile(LabeledValue):
    service: str = ""
    username: str | None = None
    url: str | None = None

    def __post_init__(self) -> None:
        super().__post_init__()
        _require_nonempty(self.service, "Dienst")


@dataclass(frozen=True)
class InstantMessageAddress(LabeledValue):
    service: str = ""
    username: str = ""

    def __post_init__(self) -> None:
        super().__post_init__()
        _require_nonempty(self.service, "Dienst")
        _require_nonempty(self.username, "Benutzername")


# ── Beziehungen, Rollen, Verfügbarkeit ───────────────────────────────────────
@dataclass(frozen=True)
class ContactRelation:
    """Ein nicht auflösbarer Bezug bleibt als Rohtext erhalten — nie geraten."""

    id: str
    position: int
    relation_type: str
    to_contact_id: str | None = None
    label_raw: str | None = None
    target_name_raw: str | None = None

    def __post_init__(self) -> None:
        _require_uuid(self.id, "id")
        _require_nonempty(self.relation_type, "Beziehungsart")
        if self.to_contact_id is None and not self.target_name_raw:
            raise IntegrityError(
                "Eine Beziehung braucht ein Ziel oder einen Rohnamen"
            )


@dataclass(frozen=True)
class ContactRole:
    """Lokale Kategorie (Privat, Arbeit, HV, Mieter, Vermieter …).

    Rollen werden **nie** zum Provider gepusht.
    """

    workspace_id: str
    role: str
    assigned_at: str = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        _require_nonempty(self.workspace_id, "workspace_id")
        _require_nonempty(self.role, "role")


@dataclass(frozen=True)
class ContactFieldAvailability:
    field_name: str
    state: FieldAvailabilityState
    observed_at: str = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        _require_nonempty(self.field_name, "Feldname")

    @property
    def is_readable(self) -> bool:
        return self.state is FieldAvailabilityState.PRESENT

    @property
    def is_known_empty(self) -> bool:
        """Nur `ABSENT` bedeutet „nachweislich leer"."""
        return self.state is FieldAvailabilityState.ABSENT

    @property
    def is_unavailable(self) -> bool:
        return self.state is FieldAvailabilityState.UNAVAILABLE_BY_CAPABILITY


@dataclass(frozen=True)
class ExternalIdentifier:
    """`unified_identifier` ist ausschließlich lesend (contacts.md §5.1)."""

    id: str
    provider_account_id: str
    container_identifier: str
    provider_identifier: str
    key_set_version: str
    last_seen_at: str = field(default_factory=utc_now)
    unified_identifier: str | None = None
    provider_revision: str | None = None

    def __post_init__(self) -> None:
        _require_uuid(self.id, "id")
        _require_nonempty(self.provider_account_id, "provider_account_id")
        _require_nonempty(self.container_identifier, "container_identifier")
        _require_nonempty(self.provider_identifier, "provider_identifier")
        _require_nonempty(self.key_set_version, "key_set_version")

    @property
    def write_target(self) -> str:
        """Das einzige zulässige Schreibziel: der Rohdatensatz.

        Ausdrücklich **nicht** `unified_identifier` — dessen Instabilität ist
        im Spike belegt (contacts.md §7.1).
        """
        return self.provider_identifier


# ── Organisationen ───────────────────────────────────────────────────────────
@dataclass(frozen=True)
class Organization:
    id: str
    workspace_id: str
    name: str
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        _require_uuid(self.id, "id")
        _require_nonempty(self.workspace_id, "workspace_id")
        _require_nonempty(self.name, "name")


@dataclass(frozen=True)
class OrganizationMembership:
    organization_id: str
    contact_id: str
    role: str | None = None
    confirmed_at: str = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        _require_uuid(self.organization_id, "organization_id")
        _require_uuid(self.contact_id, "contact_id")


# ── Kontakt ──────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class Contact:
    id: str
    workspace_id: str
    contact_type: ContactType
    display_name: str
    given_name: str | None = None
    middle_name: str | None = None
    family_name: str | None = None
    previous_family_name: str | None = None
    name_prefix: str | None = None
    name_suffix: str | None = None
    phonetic_given_name: str | None = None
    phonetic_family_name: str | None = None
    nickname: str | None = None
    organization_name: str | None = None
    department_name: str | None = None
    job_title: str | None = None
    is_me_card: bool = False
    birthday_year: int | None = None
    birthday_month: int | None = None
    birthday_day: int | None = None
    image_available: bool = False
    thumbnail_blob_ref: str | None = None
    field_completeness: FieldCompleteness = FieldCompleteness.FULL
    sync_state: SyncState = SyncState.IN_SYNC
    conflict_state: str | None = None
    local_revision: int = 1
    source_updated_at: str | None = None
    imported_at: str | None = None
    last_seen_at: str | None = None
    last_mutation_id: str | None = None
    last_approval_id: str | None = None
    last_audit_id: str | None = None
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)
    deleted_at: str | None = None
    is_tombstone: bool = False
    emails: tuple[EmailAddress, ...] = ()
    phones: tuple[PhoneNumber, ...] = ()
    postal_addresses: tuple[PostalAddress, ...] = ()
    dates: tuple[ContactDate, ...] = ()
    urls: tuple[UrlAddress, ...] = ()
    social_profiles: tuple[SocialProfile, ...] = ()
    instant_messages: tuple[InstantMessageAddress, ...] = ()
    relations: tuple[ContactRelation, ...] = ()
    roles: tuple[ContactRole, ...] = ()
    field_availability: tuple[ContactFieldAvailability, ...] = ()
    external_ids: tuple[ExternalIdentifier, ...] = ()

    def __post_init__(self) -> None:
        _require_uuid(self.id, "id")
        _require_nonempty(self.workspace_id, "workspace_id")
        _require_nonempty(self.display_name, "display_name")
        if self.local_revision < 1:
            raise IntegrityError("local_revision muss positiv sein")
        if self.birthday_month is not None and not 1 <= self.birthday_month <= 12:
            raise IntegrityError("Geburtsmonat außerhalb des gültigen Bereichs")
        if self.birthday_day is not None and not 1 <= self.birthday_day <= 31:
            raise IntegrityError("Geburtstag außerhalb des gültigen Bereichs")
        if (self.birthday_month is None) != (self.birthday_day is None):
            raise IntegrityError(
                "Geburtstag braucht Monat und Tag gemeinsam; das Jahr ist optional"
            )
        if self.is_tombstone and self.deleted_at is None:
            raise IntegrityError("Ein Tombstone braucht deleted_at")
        # Reihenfolge stabilisieren statt der Einfügereihenfolge vertrauen.
        object.__setattr__(self, "emails", _ordered(self.emails))
        object.__setattr__(self, "phones", _ordered(self.phones))
        object.__setattr__(self, "postal_addresses", _ordered(self.postal_addresses))
        object.__setattr__(self, "dates", _ordered(self.dates))
        object.__setattr__(self, "urls", _ordered(self.urls))
        object.__setattr__(self, "social_profiles", _ordered(self.social_profiles))
        object.__setattr__(self, "instant_messages", _ordered(self.instant_messages))
        object.__setattr__(self, "relations", _ordered(self.relations))

    # ── Feldverfügbarkeit ───────────────────────────────────────────────────
    def availability_of(self, field_name: str) -> FieldAvailabilityState | None:
        for entry in self.field_availability:
            if entry.field_name == field_name:
                return entry.state
        return None

    def is_field_readable(self, field_name: str) -> bool:
        return self.availability_of(field_name) is FieldAvailabilityState.PRESENT

    def is_field_known_empty(self, field_name: str) -> bool:
        """Nur `ABSENT` heißt leer. `UNAVAILABLE_BY_CAPABILITY` heißt **nicht** leer."""
        return self.availability_of(field_name) is FieldAvailabilityState.ABSENT

    # ── Kontrollierte Änderung ──────────────────────────────────────────────
    def with_changes(self, **changes) -> Contact:
        """Neues Objekt mit geänderten Feldern; erhöht `local_revision`.

        Die Me-Karte ist in v1 schreibgeschützt (contacts.md §7.3) — der
        einzige zulässige Eingriff ist das Setzen lokaler Rollen, das über
        `with_roles` läuft und den Datensatz selbst nicht verändert.
        """
        if self.is_me_card:
            raise IntegrityError(
                "Die Me-Karte ist in dieser Version schreibgeschützt"
            )
        for forbidden in ("id", "local_revision"):
            if forbidden in changes:
                raise IntegrityError(f"{forbidden} ist nicht änderbar")
        return replace(
            self,
            local_revision=self.local_revision + 1,
            updated_at=utc_now(),
            **changes,
        )

    def with_roles(self, roles: Iterable[ContactRole]) -> Contact:
        """Lokale Kategorien setzen — auch für die Me-Karte zulässig (R0, lokal)."""
        return replace(self, roles=tuple(roles))


# ── Sync, Tombstone, Mutation ────────────────────────────────────────────────
@dataclass(frozen=True)
class ContactSyncState:
    provider_account_id: str
    container_identifier: str
    key_set_version: str
    mode: str
    cursor_token: str | None = None
    cursor_taken_at: str | None = None
    last_full_diff_at: str | None = None
    circuit_state: str = "closed"
    updated_at: str = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        _require_nonempty(self.provider_account_id, "provider_account_id")
        _require_nonempty(self.container_identifier, "container_identifier")
        _require_nonempty(self.key_set_version, "key_set_version")


@dataclass(frozen=True)
class ContactTombstone:
    provider_account_id: str
    provider_identifier: str
    reason: str
    deleted_at: str = field(default_factory=utc_now)
    contact_id: str | None = None
    retain_until: str | None = None

    def __post_init__(self) -> None:
        _require_nonempty(self.provider_account_id, "provider_account_id")
        _require_nonempty(self.provider_identifier, "provider_identifier")
        _require_nonempty(self.reason, "reason")


@dataclass(frozen=True)
class ContactMutation:
    """Vorgangsgebundene Mutation (contacts.md §7.1).

    Ohne `idempotency_key` und ohne Ziel entsteht kein Objekt — die Regel „nie
    per Name mutieren" ist damit typseitig durchgesetzt.
    """

    mutation_id: str
    command: str
    idempotency_key: str
    state: MutationState
    initiation_context: InitiationContext
    target_contact_id: str | None = None
    target_provider_identifier: str | None = None
    provider_account_id: str | None = None
    approval_id: str | None = None
    expected_revision: str | None = None
    outcome: MutationOutcome | None = None
    created_at: str = field(default_factory=utc_now)
    settled_at: str | None = None

    def __post_init__(self) -> None:
        _require_uuid(self.mutation_id, "mutation_id")
        _require_nonempty(self.command, "command")
        _require_nonempty(self.idempotency_key, "idempotency_key")
        if self.target_contact_id is None and self.target_provider_identifier is None:
            raise IntegrityError(
                "Eine Mutation braucht ein ausdrückliches Ziel — "
                "ein Name oder Suchmuster ist niemals ein Ziel"
            )

    @property
    def is_settled(self) -> bool:
        """`OUTCOME_UNKNOWN` gilt ausdrücklich **nicht** als abgeschlossen."""
        return self.state in (
            MutationState.COMPLETED,
            MutationState.FAILED,
            MutationState.DENIED,
            MutationState.EXPIRED,
            MutationState.ABORTED,
        )

    @property
    def requires_reconcile(self) -> bool:
        return self.state in (
            MutationState.OUTCOME_UNKNOWN,
            MutationState.RECONCILE_REQUIRED,
        )

    @property
    def may_retry_automatically(self) -> bool:
        """Immer `False` bei unbekanntem Ausgang — kein automatischer Retry."""
        return not self.requires_reconcile and self.state is MutationState.FAILED
