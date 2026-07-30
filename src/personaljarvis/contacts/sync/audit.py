"""Technische Auditspur der Lese-Synchronisation.

Warum es sie gibt: Am 2026-07-30 setzte ein Voll-Diff 116 Kontakte lokal auf
gelöscht, und der Vorgang war hinterher nicht rekonstruierbar. Die
Schutzinvariante ist inzwischen geschlossen — aber ohne Spur bliebe jeder
Wiederholungsfall wieder unerklärbar.

**Was hier niemals hineingehört** — und deshalb auch nicht hineingelangen kann,
weil die Typen es gar nicht erst annehmen: Namen, Adressen, Nummern,
Organisationen, Geburtstage, Provider-Identifier, rohe Containerkennungen,
Cursor, Token oder Hashes davon, `BridgeContact`-Repräsentationen, private
Pfade. Containerkennungen erscheinen ausschliesslich als `container_ref`.

**Die Spur ersetzt keinen fachlichen Zustand.** Cursor, Modus und
Schlüsselsatz leben weiter in `contacts_sync_state`; hier steht nur, was ein
Lauf getan hat.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

__all__ = [
    "container_ref",
    "ContainerAudit",
    "SyncAuditRecord",
    "SyncAuditWriter",
    "OUTCOME_COMMITTED",
    "OUTCOME_ROLLED_BACK",
    "OUTCOME_ABORTED",
]

OUTCOME_COMMITTED = "committed"
OUTCOME_ROLLED_BACK = "rolled_back"
OUTCOME_ABORTED = "aborted"


def container_ref(identifier: str) -> str:
    """Deterministisches, nicht zurückrechenbares Kürzel einer Containerkennung.

    Dieselbe Bildung wie in der Forensik vom 2026-07-30 — so bleiben Container
    über Läufe und Berichte hinweg zuordenbar, ohne dass die Kennung selbst
    irgendwo steht.
    """
    return "C-" + hashlib.sha256(identifier.encode("utf-8")).hexdigest()[:6]


@dataclass(frozen=True)
class ContainerAudit:
    """Eine Enumeration eines Containers — reine Zählwerte.

    `attempt` ist 1 für den ersten Lauf und 2 für die **eine** erlaubte
    Gegenprobe nach einem Null-Ergebnis. Einen dritten Versuch gibt es nicht.
    """

    container_ref: str
    attempt: int
    reported_count: int
    received_count: int
    complete: bool
    count_consistent: bool
    duplicate_identifiers: int = 0
    previous_count: int = 0
    error_class: str | None = None


@dataclass
class SyncAuditRecord:
    """Ein Lauf. Wird beim Start angelegt und beim Abschluss festgeschrieben."""

    workspace_id: str
    provider_account_id: str
    mode: str
    run_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    started_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    completed_at: str | None = None
    outcome: str = "running"
    container_count: int = 0
    containers: list[ContainerAudit] = field(default_factory=list)
    #: Cursor **nur** als Vorhandensein — nie der Wert.
    cursor_before_present: bool = False
    cursor_after_present: bool = False
    full_diff_required: bool = False
    drop_everything_seen: bool = False
    suspicious_empty: bool = False
    events_add: int = 0
    events_update: int = 0
    events_delete: int = 0
    events_other: int = 0
    imported: int = 0
    updated: int = 0
    unchanged: int = 0
    tombstoned: int = 0
    reactivated: int = 0
    error_class: str | None = None
    error_code: str | None = None

    @property
    def events_total(self) -> int:
        return (self.events_add + self.events_update + self.events_delete
                + self.events_other)

    def add_container(self, eintrag: ContainerAudit) -> None:
        self.containers.append(eintrag)

    def finish(self, outcome: str) -> "SyncAuditRecord":
        self.outcome = outcome
        self.completed_at = datetime.now(UTC).isoformat()
        return self


def _b(wert: bool) -> int:
    return 1 if wert else 0


class SyncAuditWriter:
    """Schreibt die Spur über eine bereits geöffnete UnitOfWork.

    Bewusst ohne eigene Verbindung: die Spur eines zurückgerollten Laufs
    verschwindet mit ihm — sonst behauptete sie einen Lauf, den es nicht gibt.
    Ein **abgebrochener** Lauf wird deshalb in einer eigenen, kurzen
    Transaktion festgehalten (siehe `write_standalone`).
    """

    def __init__(self, uow) -> None:
        self._uow = uow

    def write(self, satz: SyncAuditRecord) -> None:
        self._uow.execute(
            "INSERT INTO contacts_sync_audit ("
            " run_id, workspace_id, provider_account_id, mode, container_count,"
            " started_at, completed_at, outcome, cursor_before_present,"
            " cursor_after_present, full_diff_required, drop_everything_seen,"
            " suspicious_empty, events_total, events_add, events_update,"
            " events_delete, events_other, imported, updated, unchanged,"
            " tombstoned, reactivated, error_class, error_code"
            ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (satz.run_id, satz.workspace_id, satz.provider_account_id,
             satz.mode, satz.container_count, satz.started_at,
             satz.completed_at, satz.outcome, _b(satz.cursor_before_present),
             _b(satz.cursor_after_present), _b(satz.full_diff_required),
             _b(satz.drop_everything_seen), _b(satz.suspicious_empty),
             satz.events_total, satz.events_add, satz.events_update,
             satz.events_delete, satz.events_other, satz.imported,
             satz.updated, satz.unchanged, satz.tombstoned, satz.reactivated,
             satz.error_class, satz.error_code),
        )
        for c in satz.containers:
            self._uow.execute(
                "INSERT INTO contacts_sync_audit_containers ("
                " run_id, container_ref, attempt, reported_count,"
                " received_count, complete, count_consistent,"
                " duplicate_identifiers, previous_count, error_class"
                ") VALUES (?,?,?,?,?,?,?,?,?,?)",
                (satz.run_id, c.container_ref, c.attempt, c.reported_count,
                 c.received_count, _b(c.complete), _b(c.count_consistent),
                 c.duplicate_identifiers, c.previous_count, c.error_class),
            )
