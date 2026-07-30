"""Lese-Synchronisation des Kontakte-Moduls (Plan §6).

Der Import dieses Pakets hat **keine** Nebenwirkung: kein Prozess, keine
Datenbank, keine Berechtigungsabfrage, kein Lauf. Synchronisation geschieht in
Gate B ausschliesslich über einen ausdrücklichen Aufruf von
`ContactsSyncService`.
"""

from __future__ import annotations

from personaljarvis.contacts.sync.audit import (
    ContainerAudit,
    SyncAuditRecord,
    SyncAuditWriter,
    container_ref,
)
from personaljarvis.contacts.sync.echo import EchoSuppressionLedger
from personaljarvis.contacts.sync.errors import (
    AuthorizationRequired,
    CursorRejected,
    DeleteBasisInvalid,
    FullDiffRequired,
    IncompleteEnumeration,
    KeySetVersionChanged,
    SuspiciousEmptyEnumeration,
    SyncError,
    TransientEmptySnapshot,
    UnknownChangeEvent,
)
from personaljarvis.contacts.sync.mapper import (
    MappedContact,
    build_display_name,
    content_equals,
    map_bridge_contact,
    merge_into_existing,
)
from personaljarvis.contacts.sync.recovery import (
    ContactsRecoveryService,
    RecoveryResult,
)
from personaljarvis.contacts.sync.service import (
    TOMBSTONE_REASON_ABSENT,
    TOMBSTONE_REASON_EVENT,
    ContactsSyncService,
    SyncPersistence,
)
from personaljarvis.contacts.sync.state import (
    CursorState,
    SyncRunKind,
    SyncRunResult,
    derive_cursor_state,
)

__all__ = [
    "ContactsSyncService",
    "SyncPersistence",
    "SyncRunResult",
    "SyncRunKind",
    "CursorState",
    "derive_cursor_state",
    "MappedContact",
    "map_bridge_contact",
    "merge_into_existing",
    "build_display_name",
    "content_equals",
    "EchoSuppressionLedger",
    "SyncError",
    "TransientEmptySnapshot",
    "SuspiciousEmptyEnumeration",
    "DeleteBasisInvalid",
    "ContactsRecoveryService",
    "RecoveryResult",
    "SyncAuditRecord",
    "ContainerAudit",
    "SyncAuditWriter",
    "container_ref",
    "AuthorizationRequired",
    "IncompleteEnumeration",
    "KeySetVersionChanged",
    "CursorRejected",
    "FullDiffRequired",
    "UnknownChangeEvent",
    "TOMBSTONE_REASON_ABSENT",
    "TOMBSTONE_REASON_EVENT",
]
