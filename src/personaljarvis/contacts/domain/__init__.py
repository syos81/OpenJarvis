"""Kontakte-Domäne — providerneutral und plattformunabhängig (AV-4)."""

from __future__ import annotations

from personaljarvis.contacts.domain.capabilities import (
    NOTE_FIELD,
    ContactCapabilitySet,
    default_capabilities,
)
from personaljarvis.contacts.domain.enums import (
    CircuitState,
    ContactType,
    FieldAvailabilityState,
    FieldCompleteness,
    InitiationContext,
    MutationOutcome,
    MutationState,
    SensitivityLabel,
    SyncMode,
    SyncState,
)
from personaljarvis.contacts.domain.labels import ENTITY_TYPE, FIELD_LABELS, label_for
from personaljarvis.contacts.domain.models import (
    Contact,
    ContactDate,
    ContactFieldAvailability,
    ContactMutation,
    ContactRelation,
    ContactRole,
    ContactSyncState,
    ContactTombstone,
    EmailAddress,
    ExternalIdentifier,
    InstantMessageAddress,
    Organization,
    OrganizationMembership,
    PhoneNumber,
    PostalAddress,
    SocialProfile,
    UrlAddress,
    utc_now,
)

__all__ = [
    "CircuitState", "Contact", "ContactCapabilitySet", "ContactDate",
    "ContactFieldAvailability", "ContactMutation", "ContactRelation",
    "ContactRole", "ContactSyncState", "ContactTombstone", "ContactType",
    "ENTITY_TYPE", "EmailAddress", "ExternalIdentifier", "FIELD_LABELS",
    "FieldAvailabilityState", "FieldCompleteness", "InitiationContext",
    "InstantMessageAddress", "MutationOutcome", "MutationState", "NOTE_FIELD",
    "Organization", "OrganizationMembership", "PhoneNumber", "PostalAddress",
    "SensitivityLabel", "SocialProfile", "SyncMode", "SyncState", "UrlAddress",
    "default_capabilities", "label_for", "utc_now",
]
