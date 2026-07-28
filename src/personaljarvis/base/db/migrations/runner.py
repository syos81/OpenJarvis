"""Migrations-Runner — nur vorwärts, atomar, fail-closed (07 §6).

Belegte SQLite-Eigenschaften, auf denen dieser Runner aufbaut (empirisch
geprüft, nicht angenommen):

* **DDL ist transaktional.** Ein `ROLLBACK` nach `CREATE TABLE` entfernt die
  Tabelle wieder. Schemaänderung und Ledger-Eintrag können deshalb in
  **derselben** Transaktion liegen — eine Migration ist atomar.
* **`PRAGMA foreign_keys` ist innerhalb einer Transaktion wirkungslos.** Die
  Factory setzt es deshalb vor jedem `BEGIN`.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from personaljarvis.base.db.factory import ConnectionFactory
from personaljarvis.base.db.migrations.ledger import (
    LEDGER_TABLE,
    Migration,
    ensure_ledger,
    read_ledger,
    utc_now,
)
from personaljarvis.errors import LedgerError, MigrationError

__all__ = ["MigrationRunner", "MigrationReport"]


@dataclass(frozen=True)
class MigrationReport:
    applied: tuple[str, ...]
    already_applied: tuple[str, ...]
    schema_version: int


def _software_version() -> str:
    try:
        from importlib.metadata import version

        return version("openjarvis")
    except Exception:
        return "unknown"


class MigrationRunner:
    """Führt eine feste, geordnete Migrationsliste aus."""

    def __init__(
        self,
        factory: ConnectionFactory,
        migrations: tuple[Migration, ...],
    ) -> None:
        self._factory = factory
        self._migrations = migrations
        self._validate_definitions()

    # ── Statische Prüfungen der Definitionen ────────────────────────────────
    def _validate_definitions(self) -> None:
        seen: set[str] = set()
        previous: str | None = None
        for migration in self._migrations:
            if migration.migration_id in seen:
                raise MigrationError(
                    f"Doppelte Migrations-ID: {migration.migration_id}"
                )
            seen.add(migration.migration_id)
            if previous is not None and migration.migration_id <= previous:
                raise MigrationError(
                    "Migrationen sind nicht monoton geordnet: "
                    f"{migration.migration_id} folgt auf {previous}"
                )
            for dependency in migration.depends_on:
                if dependency >= migration.migration_id:
                    raise MigrationError(
                        f"{migration.migration_id} hängt von {dependency} ab — "
                        "Abhängigkeiten müssen kleiner als die eigene ID sein"
                    )
                if dependency not in seen:
                    raise MigrationError(
                        f"{migration.migration_id} hängt von unbekannter "
                        f"Migration {dependency} ab"
                    )
            if not migration.statements:
                raise MigrationError(
                    f"{migration.migration_id} enthält keine Anweisung"
                )
            previous = migration.migration_id

    # ── Ledger-Prüfung ──────────────────────────────────────────────────────
    def verify(self, conn: sqlite3.Connection) -> tuple[Migration, ...]:
        """Vergleicht Ledger und Definitionen. Gibt die offenen Migrationen zurück.

        Fail-closed bei: unbekannter angewandter ID, abweichender Prüfsumme.
        """
        applied = read_ledger(conn)
        known = {m.migration_id: m for m in self._migrations}

        unknown = sorted(set(applied) - set(known))
        if unknown:
            raise LedgerError(
                "Ledger enthält angewandte Migrationen, die diese Software "
                f"nicht kennt: {', '.join(unknown)}. Personal bleibt "
                "deaktiviert; Wiederherstellung aus dem Backup erforderlich."
            )

        for migration in self._migrations:
            entry = applied.get(migration.migration_id)
            if entry is None:
                continue
            if entry.checksum != migration.checksum:
                raise LedgerError(
                    f"Prüfsumme von {migration.migration_id} weicht ab. "
                    "Veröffentlichte Migrationen sind unveränderlich; eine "
                    "Korrektur ist eine neue Migration. Personal bleibt "
                    "deaktiviert."
                )

        return tuple(m for m in self._migrations if m.migration_id not in applied)

    # ── Ausführung ──────────────────────────────────────────────────────────
    def run(self) -> MigrationReport:
        conn = self._factory.connect()
        ensure_ledger(conn)
        pending = self.verify(conn)
        already = tuple(
            m.migration_id for m in self._migrations if m not in pending
        )

        applied_now: list[str] = []
        software = _software_version()
        for migration in pending:
            self._apply(conn, migration, software)
            applied_now.append(migration.migration_id)

        version = max(
            (m.schema_version for m in self._migrations), default=0
        )
        return MigrationReport(
            applied=tuple(applied_now),
            already_applied=already,
            schema_version=version,
        )

    def _apply(
        self, conn: sqlite3.Connection, migration: Migration, software: str
    ) -> None:
        """Eine Migration atomar anwenden: Schema **und** Ledger in einer TX."""
        if conn.in_transaction:
            raise MigrationError(
                "Migration kann nicht innerhalb einer offenen Transaktion laufen"
            )
        conn.execute("BEGIN IMMEDIATE")
        try:
            for statement in migration.statements:
                conn.execute(statement)
            conn.execute(
                f"INSERT INTO {LEDGER_TABLE} (migration_id, module_owner, "
                "description, checksum, applied_at, schema_version, "
                "software_version) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    migration.migration_id,
                    migration.module_owner,
                    migration.description,
                    migration.checksum,
                    utc_now(),
                    migration.schema_version,
                    software,
                ),
            )
        except Exception as exc:
            conn.execute("ROLLBACK")
            raise MigrationError(
                f"Migration {migration.migration_id} fehlgeschlagen und "
                f"vollständig zurückgerollt ({type(exc).__name__})"
            ) from exc
        conn.execute("COMMIT")
