"""Migrations-Ledger und Migrationsdefinition (07 §6, AV-37).

Das Ledger ist die einzige Wahrheit darüber, welche Migration mit welchem
Inhalt angewandt wurde. Jede Unstimmigkeit führt **fail-closed** zum Abbruch;
es gibt keinen Reparaturpfad im Code (07 §6 Nr. 2).
"""

from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone

from personaljarvis.errors import LedgerError

__all__ = ["Migration", "AppliedMigration", "LEDGER_TABLE", "ensure_ledger", "read_ledger"]

LEDGER_TABLE = "personal_migration_ledger"

_LEDGER_DDL = f"""
CREATE TABLE IF NOT EXISTS {LEDGER_TABLE} (
    migration_id   TEXT    NOT NULL PRIMARY KEY,
    module_owner   TEXT    NOT NULL,
    description    TEXT    NOT NULL,
    checksum       TEXT    NOT NULL,
    applied_at     TEXT    NOT NULL,
    schema_version INTEGER NOT NULL,
    software_version TEXT  NOT NULL
) STRICT
"""


@dataclass(frozen=True)
class Migration:
    """Eine unveränderliche Vorwärtsmigration.

    `migration_id` ist global monoton über **alle** Module (07 §6 Nr. 1);
    `depends_on` darf ausschließlich kleinere IDs nennen und wird beim Lauf
    validiert. Die Prüfsumme deckt den normativen Inhalt ab: die Liste der
    Anweisungen in ihrer Reihenfolge — nicht Kommentare, nicht Formatierung.
    """

    migration_id: str
    module_owner: str
    description: str
    statements: tuple[str, ...]
    schema_version: int
    depends_on: tuple[str, ...] = field(default=())

    @property
    def checksum(self) -> str:
        digest = hashlib.sha256()
        for statement in self.statements:
            digest.update(b"\x1f")
            digest.update(" ".join(statement.split()).encode("utf-8"))
        return digest.hexdigest()


@dataclass(frozen=True)
class AppliedMigration:
    migration_id: str
    checksum: str
    applied_at: str
    schema_version: int


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def ensure_ledger(conn: sqlite3.Connection) -> None:
    """Legt die Ledger-Tabelle an, falls sie fehlt. Idempotent."""
    conn.execute(_LEDGER_DDL)


def read_ledger(conn: sqlite3.Connection) -> dict[str, AppliedMigration]:
    """Liest den Ledger-Inhalt. Ohne Ledger-Tabelle: leeres Ergebnis."""
    exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (LEDGER_TABLE,)
    ).fetchone()
    if not exists:
        return {}
    rows = conn.execute(
        f"SELECT migration_id, checksum, applied_at, schema_version "
        f"FROM {LEDGER_TABLE} ORDER BY migration_id"
    ).fetchall()
    applied: dict[str, AppliedMigration] = {}
    for row in rows:
        entry = AppliedMigration(
            migration_id=row["migration_id"],
            checksum=row["checksum"],
            applied_at=row["applied_at"],
            schema_version=int(row["schema_version"]),
        )
        if entry.migration_id in applied:  # pragma: no cover — PK verhindert das
            raise LedgerError(f"Ledger enthält {entry.migration_id} doppelt")
        applied[entry.migration_id] = entry
    return applied
