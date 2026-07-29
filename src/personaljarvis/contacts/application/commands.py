"""Typisierte Mutations-Commands (05 §1, Plan §7.1).

Jeder Command ist unveränderlich und trägt **alle** Pflichtfelder, ohne die
11 §3 nicht erfüllbar wäre: Vorgangs-ID, Idempotenzschlüssel, Freigabe-Bezug,
Ursprung und eine **stabile Ziel-ID**.

Ausdrückliche Grenzen:

* **Kein Apple-Typ.** Die Commands kennen `CNContact` nicht (AV-4).
* **Keine Zielsuche.** Es gibt kein Feld für Name, E-Mail oder Suchmuster.
  `update` und `delete` nennen die Provider-ID; `create` nennt den Container.
* **Kein `unifiedIdentifier` als Ziel** — dafür gibt es kein Feld, und die
  Validierung weist ihn zusätzlich ausdrücklich ab.
* **Patch statt Vollobjekt.** `UpdateContact` trägt nur die ausdrücklich
  gesetzten Felder; was nicht genannt ist, bleibt unberührt. Das ist der
  Grund, weshalb ein nicht lesbares Notizfeld nie überschrieben wird.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Mapping

from personaljarvis.contacts.application.errors import (
    InvalidCommand,
    TargetBindingError,
    UnifiedIdentifierNotWritable,
)
from personaljarvis.contacts.domain.enums import InitiationContext
from personaljarvis.contacts.domain.models import utc_now

__all__ = [
    "ContactDraft",
    "ContactPatch",
    "CreateContact",
    "UpdateContact",
    "DeleteContact",
    "MutationCommand",
    "PATCHABLE_FIELDS",
    "NEVER_PATCHABLE",
]

_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)

#: Felder, die ein Patch setzen darf. Bewusst eine Allowlist: ein unbekanntes
#: Feld wird abgewiesen statt durchgereicht.
PATCHABLE_FIELDS: frozenset[str] = frozenset({
    "given_name", "middle_name", "family_name", "previous_family_name",
    "name_prefix", "name_suffix", "phonetic_given_name",
    "phonetic_family_name", "nickname", "organization_name",
    "department_name", "job_title", "birthday_year", "birthday_month",
    "birthday_day", "emails", "phones", "postal_addresses", "dates", "urls",
    "social_profiles", "instant_messages",
})

#: Felder, die eine Mutation **nie** setzen darf.
#: `note` fehlt der Bridge mangels Entitlement — ein Schreibversuch würde eine
#: vorhandene Notiz überschreiben oder löschen (08 §4, Plan §3).
NEVER_PATCHABLE: frozenset[str] = frozenset({
    "note", "notes", "id", "local_revision", "is_me_card",
    "unified_identifier", "thumbnail_blob_ref", "image_available",
})


def _require_uuid(value: str, name: str) -> str:
    if not _UUID_RE.match(value or ""):
        raise InvalidCommand(f"{name} ist keine gueltige UUID")
    return value


def _require_nonempty(value: str, name: str) -> str:
    if not value or not str(value).strip():
        raise InvalidCommand(f"{name} darf nicht leer sein")
    return value


def _reject_unified(identifier: str) -> str:
    """Ein als unified gekennzeichnetes Ziel wird nie zum Schreibziel."""
    if identifier.lower().startswith("unified:"):
        raise UnifiedIdentifierNotWritable(
            "Der unifizierte Identifier ist belegt instabil und niemals "
            "Schreibziel; es ist die Roh-Provider-ID zu verwenden"
        )
    return identifier


def _validate_fields(felder: Mapping[str, Any], *, kontext: str) -> dict:
    unbekannt = sorted(set(felder) - PATCHABLE_FIELDS)
    verboten = sorted(set(felder) & NEVER_PATCHABLE)
    if verboten:
        raise InvalidCommand(
            f"{kontext}: diese Felder sind nie schreibbar: "
            f"{', '.join(verboten)}"
        )
    if unbekannt:
        raise InvalidCommand(
            f"{kontext}: unbekannte Felder: {', '.join(unbekannt)}")
    return dict(felder)


@dataclass(frozen=True)
class ContactDraft:
    """Kanonischer Entwurf für `create` — providerneutral."""

    fields: Mapping[str, Any]

    def __post_init__(self) -> None:
        geprueft = _validate_fields(self.fields, kontext="Entwurf")
        if not geprueft:
            raise InvalidCommand("Ein Entwurf ohne Felder ist nicht zulaessig")
        object.__setattr__(self, "fields", dict(sorted(geprueft.items())))


@dataclass(frozen=True)
class ContactPatch:
    """Ausschließlich ausdrücklich gesetzte Felder für `update`."""

    fields: Mapping[str, Any]

    def __post_init__(self) -> None:
        geprueft = _validate_fields(self.fields, kontext="Patch")
        if not geprueft:
            raise InvalidCommand(
                "Ein Patch ohne Feld waere eine Mutation ohne Wirkung")
        object.__setattr__(self, "fields", dict(sorted(geprueft.items())))


@dataclass(frozen=True)
class _BaseCommand:
    """Gemeinsame Pflichtfelder jeder Mutation."""

    mutation_id: str
    idempotency_key: str
    provider_account_id: str
    workspace_id: str
    actor: str
    initiation_context: InitiationContext
    correlation_id: str
    requested_at: str = field(default_factory=utc_now)
    approval_id: str | None = None

    def __post_init__(self) -> None:
        _require_uuid(self.mutation_id, "mutation_id")
        _require_nonempty(self.idempotency_key, "idempotency_key")
        _require_nonempty(self.provider_account_id, "provider_account_id")
        _require_nonempty(self.workspace_id, "workspace_id")
        _require_nonempty(self.actor, "actor")
        _require_nonempty(self.correlation_id, "correlation_id")
        if self.approval_id is not None:
            _require_uuid(self.approval_id, "approval_id")

    @property
    def command_name(self) -> str:  # pragma: no cover — je Unterklasse gesetzt
        raise NotImplementedError


@dataclass(frozen=True)
class CreateContact(_BaseCommand):
    """Neuanlage in einem **ausdrücklich benannten** Container."""

    container_identifier: str = ""
    draft: ContactDraft | None = None

    def __post_init__(self) -> None:
        super().__post_init__()
        _require_nonempty(self.container_identifier, "container_identifier")
        if self.draft is None:
            raise InvalidCommand("create verlangt einen Kontaktentwurf")

    @property
    def command_name(self) -> str:
        return "create"


@dataclass(frozen=True)
class UpdateContact(_BaseCommand):
    """Änderung genau eines Rohdatensatzes über seine stabile Provider-ID."""

    target_provider_identifier: str = ""
    expected_revision: str | None = None
    patch: ContactPatch | None = None

    def __post_init__(self) -> None:
        super().__post_init__()
        if not self.target_provider_identifier:
            raise TargetBindingError(
                "update verlangt eine stabile targetProviderIdentifier; "
                "ein Name oder Suchergebnis ist niemals ein Ziel"
            )
        _reject_unified(self.target_provider_identifier)
        if self.patch is None:
            raise InvalidCommand("update verlangt einen Patch")

    @property
    def command_name(self) -> str:
        return "update"


@dataclass(frozen=True)
class DeleteContact(_BaseCommand):
    """Löschung genau eines Rohdatensatzes über seine stabile Provider-ID."""

    target_provider_identifier: str = ""
    expected_revision: str | None = None

    def __post_init__(self) -> None:
        super().__post_init__()
        if not self.target_provider_identifier:
            raise TargetBindingError(
                "delete verlangt eine stabile targetProviderIdentifier; "
                "ein Name oder Suchergebnis ist niemals ein Ziel"
            )
        _reject_unified(self.target_provider_identifier)

    @property
    def command_name(self) -> str:
        return "delete"


#: Union aller Mutations-Commands.
MutationCommand = CreateContact | UpdateContact | DeleteContact
