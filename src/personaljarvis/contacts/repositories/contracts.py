"""Repository-**Verträge** des Kontakte-Moduls (07 §3).

Verträge sind öffentlich, Implementierungen modulprivat. Kein fremdes Modul
importiert eine Implementierung; die Auflösung geschieht ausschließlich in der
Kompositionswurzel per Constructor Injection (04 §1).

Alle Verträge nehmen Domänenobjekte entgegen und geben Domänenobjekte zurück —
**nie** `sqlite3.Row`, nie ein Tupel, nie ein Apple-Objekt.

Wichtig zur Einordnung: „Create/Update/Delete" bedeutet hier ausschließlich
**lokale kanonische Persistenz**. Es ist keine Apple-Contacts-Mutation; die
entsteht erst mit Gate C über den CommandBus und die Outbox.
"""

from __future__ import annotations

from typing import Protocol, Sequence, runtime_checkable

from personaljarvis.contacts.domain.models import (
    Contact,
    ContactFieldAvailability,
    ContactMutation,
    ContactRole,
    ContactSyncState,
    ContactTombstone,
    ExternalIdentifier,
    Organization,
    OrganizationMembership,
)

__all__ = [
    "ContactRepository",
    "ContactRoleRepository",
    "ExternalIdentifierRepository",
    "FieldAvailabilityRepository",
    "SyncStateRepository",
    "TombstoneRepository",
    "MutationRepository",
    "OrganizationRepository",
]


@runtime_checkable
class ContactRepository(Protocol):
    """Kanonische Kontakte inklusive aller Kinddatensätze."""

    def add(self, contact: Contact) -> None: ...

    def get(self, contact_id: str) -> Contact | None: ...

    def update(self, contact: Contact) -> None: ...

    def soft_delete(self, contact_id: str, deleted_at: str) -> None: ...

    def list_by_workspace(
        self, workspace_id: str, *, include_tombstones: bool = False
    ) -> Sequence[Contact]: ...

    def search_by_display_name(
        self, workspace_id: str, fragment: str
    ) -> Sequence[Contact]: ...


@runtime_checkable
class ContactRoleRepository(Protocol):
    """Lokale Kategorien; werden nie zum Provider gepusht."""

    def set_roles(self, contact_id: str, roles: Sequence[ContactRole]) -> None: ...

    def list_for_contact(self, contact_id: str) -> Sequence[ContactRole]: ...

    def list_contact_ids_by_role(
        self, workspace_id: str, role: str
    ) -> Sequence[str]: ...


@runtime_checkable
class ExternalIdentifierRepository(Protocol):
    def upsert(self, contact_id: str, identifier: ExternalIdentifier) -> None: ...

    def list_for_contact(self, contact_id: str) -> Sequence[ExternalIdentifier]: ...

    def find_contact_id(
        self, provider_account_id: str, provider_identifier: str
    ) -> str | None: ...


@runtime_checkable
class FieldAvailabilityRepository(Protocol):
    """Trennt „nachweislich leer" von „nicht lesbar" (08 §4)."""

    def set_for_contact(
        self, contact_id: str, entries: Sequence[ContactFieldAvailability]
    ) -> None: ...

    def list_for_contact(
        self, contact_id: str
    ) -> Sequence[ContactFieldAvailability]: ...


@runtime_checkable
class SyncStateRepository(Protocol):
    def upsert(self, state: ContactSyncState) -> None: ...

    def get(
        self, provider_account_id: str, container_identifier: str
    ) -> ContactSyncState | None: ...

    def list_all(self) -> Sequence[ContactSyncState]: ...


@runtime_checkable
class TombstoneRepository(Protocol):
    def add(self, tombstone: ContactTombstone) -> None: ...

    def exists(
        self, provider_account_id: str, provider_identifier: str
    ) -> bool: ...

    def list_all(self) -> Sequence[ContactTombstone]: ...


@runtime_checkable
class MutationRepository(Protocol):
    def add(self, mutation: ContactMutation) -> None: ...

    def get(self, mutation_id: str) -> ContactMutation | None: ...

    def find_by_idempotency_key(self, key: str) -> ContactMutation | None: ...

    def update_state(self, mutation: ContactMutation) -> None: ...

    def list_requiring_reconcile(self) -> Sequence[ContactMutation]: ...


@runtime_checkable
class OrganizationRepository(Protocol):
    def add(self, organization: Organization) -> None: ...

    def get(self, organization_id: str) -> Organization | None: ...

    def add_membership(self, membership: OrganizationMembership) -> None: ...

    def list_memberships(
        self, organization_id: str
    ) -> Sequence[OrganizationMembership]: ...
