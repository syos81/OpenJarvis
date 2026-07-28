"""Repository-Verträge (öffentlich) und Implementierungen (modulprivat).

Fremde Module importieren ausschließlich aus `contracts`; die konkreten
SQLite-Klassen werden allein in der Kompositionswurzel aufgelöst (07 §3).
"""

from __future__ import annotations

from personaljarvis.contacts.repositories.contracts import (
    ContactRepository,
    ContactRoleRepository,
    ExternalIdentifierRepository,
    FieldAvailabilityRepository,
    MutationRepository,
    OrganizationRepository,
    SyncStateRepository,
    TombstoneRepository,
)

__all__ = [
    "ContactRepository", "ContactRoleRepository", "ExternalIdentifierRepository",
    "FieldAvailabilityRepository", "MutationRepository", "OrganizationRepository",
    "SyncStateRepository", "TombstoneRepository",
]
