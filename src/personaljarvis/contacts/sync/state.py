"""Cursor- und Laufzustände der Sync-Pipeline (Plan §6.2).

**Keine zweite Datenwahrheit:** Der persistente Zustand bleibt
`contacts_sync_state` (`cursor_token`, `key_set_version`, `mode`,
`circuit_state`). `CursorState` ist ausschliesslich die *abgeleitete* Sicht
darauf plus die beiden Laufzustände, die sich nicht persistieren lassen
(`PROCESSING`, `FAILED`).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from personaljarvis.contacts.domain.enums import SyncMode
from personaljarvis.contacts.domain.models import ContactSyncState

__all__ = ["CursorState", "SyncRunKind", "SyncRunResult", "derive_cursor_state"]


class CursorState(str, Enum):
    """Zustand des Delta-Cursors."""

    #: Noch nie ein erfolgreicher Lauf — der erste Lauf ist ein Voll-Diff.
    ABSENT = "absent"
    #: Gültiger Cursor, Delta-Pfad tragfähig.
    ACTIVE = "active"
    #: Der Provider hat den Cursor abgelehnt.
    INVALID = "invalid"
    #: `dropEverything`, Schlüsselsatzwechsel oder abgelehnter Cursor.
    FULL_DIFF_REQUIRED = "full_diff_required"
    #: Ein Lauf ist unterwegs; der Cursor wird noch nicht fortgeschrieben.
    PROCESSING = "processing"
    #: Der letzte Lauf scheiterte; der Cursor blieb unverändert.
    FAILED = "failed"


class SyncRunKind(str, Enum):
    INITIAL_IMPORT = "initial_import"
    DELTA = "delta"
    FULL_DIFF = "full_diff"


def derive_cursor_state(state: ContactSyncState | None) -> CursorState:
    """Leitet den Cursor-Zustand aus dem persistierten Sync-State ab.

    Der Aufrufer erzeugt daraus **keinen** zweiten Speicher: die Wahrheit
    bleibt die Zeile in `contacts_sync_state`.
    """
    if state is None:
        return CursorState.ABSENT
    if state.mode == SyncMode.FULL_DIFF_REQUIRED.value:
        return CursorState.FULL_DIFF_REQUIRED
    if not state.cursor_token:
        return CursorState.ABSENT
    return CursorState.ACTIVE


@dataclass(frozen=True)
class SyncRunResult:
    """Ergebnis eines Laufs — technisch, PII-frei.

    Enthält bewusst **keine** Provider-Identifier, Namen, Werte oder
    Cursor-Token. `cursor_advanced` sagt nur, *ob* fortgeschritten wurde.
    """

    kind: SyncRunKind
    succeeded: bool
    cursor_state: CursorState
    provider_account_id: str
    container_identifier: str
    imported: int = 0
    updated: int = 0
    tombstoned: int = 0
    unchanged: int = 0
    events_processed: int = 0
    cursor_advanced: bool = False
    requires_full_diff: bool = False
    error_class: str | None = None
    detail: str = ""
    audit_events: tuple[str, ...] = field(default_factory=tuple)

    @property
    def changed_anything(self) -> bool:
        return bool(self.imported or self.updated or self.tombstoned)

    def as_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind.value,
            "succeeded": self.succeeded,
            "cursorState": self.cursor_state.value,
            "imported": self.imported,
            "updated": self.updated,
            "tombstoned": self.tombstoned,
            "unchanged": self.unchanged,
            "eventsProcessed": self.events_processed,
            "cursorAdvanced": self.cursor_advanced,
            "requiresFullDiff": self.requires_full_diff,
            "errorClass": self.error_class,
            "detail": self.detail,
            "auditEvents": list(self.audit_events),
        }
