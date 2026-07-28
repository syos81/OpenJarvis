"""Lebenszyklus des Kontakte-Moduls (14 §4).

Gate-A-Verantwortung — ausdrücklich **nur** dieser Umfang:

* Datenbankpfad und Einstellungen übernehmen,
* ConnectionFactory aufbauen,
* Migrationen prüfen und ausführen,
* UnitOfWork und Repositories bereitstellen,
* Capability-Grundzustand bereitstellen,
* sauberes Start-/Stop-Verhalten.

Ausdrücklich **nicht** in Gate A: Sidecar, Apple-Autorisierung, Hintergrund-
Synchronisation, Routen. Diese Datei startet keinen Prozess und öffnet keine
Netzwerk- oder XPC-Verbindung.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from personaljarvis.base.db.factory import ConnectionFactory
from personaljarvis.base.db.migrations import ALL_MIGRATIONS, MigrationRunner
from personaljarvis.base.db.migrations.runner import MigrationReport
from personaljarvis.base.db.unit_of_work import UnitOfWork
from personaljarvis.contacts.domain.capabilities import (
    ContactCapabilitySet,
    default_capabilities,
)
from personaljarvis.contacts.repositories.sqlite import (
    SqliteContactRepository,
    SqliteContactRoleRepository,
    SqliteExternalIdentifierRepository,
    SqliteFieldAvailabilityRepository,
    SqliteMutationRepository,
    SqliteOrganizationRepository,
    SqliteSyncStateRepository,
    SqliteTombstoneRepository,
)
from personaljarvis.errors import DatabaseError, PersonalJarvisError

__all__ = ["ModuleState", "ContactsRepositories", "ContactsModule"]


class ModuleState(str, Enum):
    """Teilmenge der Zustandsmaschine aus 14 §4, die Gate A erreichen kann."""

    NOT_INSTALLED = "not_installed"
    INITIALIZING = "initializing"
    MIGRATION_REQUIRED = "migration_required"
    CONFIGURATION_REQUIRED = "configuration_required"
    ERROR = "error"
    SHUTTING_DOWN = "shutting_down"


@dataclass(frozen=True)
class ContactsRepositories:
    """Alle Repositories einer UnitOfWork — gemeinsam konstruiert, eine Verbindung."""

    contacts: SqliteContactRepository
    roles: SqliteContactRoleRepository
    external_ids: SqliteExternalIdentifierRepository
    field_availability: SqliteFieldAvailabilityRepository
    sync_state: SqliteSyncStateRepository
    tombstones: SqliteTombstoneRepository
    mutations: SqliteMutationRepository
    organizations: SqliteOrganizationRepository


class ContactsModule:
    """Startet und stoppt den persistenten Teil des Kontakte-Moduls."""

    def __init__(self, database_path: Path | str | None = None) -> None:
        self._factory = ConnectionFactory(database_path)
        self._state = ModuleState.NOT_INSTALLED
        self._report: MigrationReport | None = None
        self._capabilities: ContactCapabilitySet | None = None
        self._started = False

    # ── Zustand ─────────────────────────────────────────────────────────────
    @property
    def state(self) -> ModuleState:
        return self._state

    @property
    def migration_report(self) -> MigrationReport | None:
        return self._report

    @property
    def capabilities(self) -> ContactCapabilitySet:
        if self._capabilities is None:
            raise PersonalJarvisError("Modul ist nicht gestartet")
        return self._capabilities

    @property
    def connection_factory(self) -> ConnectionFactory:
        return self._factory

    # ── Start / Stop ────────────────────────────────────────────────────────
    def start(self) -> MigrationReport:
        """Fail-closed: bei Ledger- oder Schemafehler startet nichts weiter.

        Ein zweiter Start ist **idempotent** — er wiederholt die Migration
        nicht und gibt denselben Bericht zurück.
        """
        if self._started:
            assert self._report is not None
            return self._report

        self._state = ModuleState.INITIALIZING
        try:
            self._factory.ensure_ready()
            runner = MigrationRunner(self._factory, ALL_MIGRATIONS)
            report = runner.run()
        except DatabaseError:
            # Der Zustand benennt die Ursache: ein Schema-/Ledger-Problem ist
            # kein allgemeiner Fehler, sondern verlangt eine Migration bzw.
            # eine Wiederherstellung (14 §4).
            self._state = ModuleState.MIGRATION_REQUIRED
            self._capabilities = None
            raise
        except Exception:
            self._state = ModuleState.ERROR
            self._capabilities = None
            raise

        self._report = report
        self._capabilities = default_capabilities()
        # In Gate A existiert noch kein ProviderAccount und kein Binding —
        # das Modul ist ausdrücklich `configuration_required`, nicht `ready`.
        self._state = ModuleState.CONFIGURATION_REQUIRED
        self._started = True
        return report

    def stop(self) -> None:
        if not self._started:
            self._state = ModuleState.NOT_INSTALLED
            return
        self._state = ModuleState.SHUTTING_DOWN
        self._factory.close()
        self._started = False
        self._capabilities = None
        self._state = ModuleState.NOT_INSTALLED

    # ── Arbeitseinheiten ────────────────────────────────────────────────────
    def unit_of_work(self) -> UnitOfWork:
        if not self._started:
            raise PersonalJarvisError("Modul ist nicht gestartet")
        return UnitOfWork(self._factory)

    def repositories(self, uow: UnitOfWork) -> ContactsRepositories:
        """Repositories über **derselben** UnitOfWork — nie eigene Verbindungen."""
        return ContactsRepositories(
            contacts=SqliteContactRepository(uow),
            roles=SqliteContactRoleRepository(uow),
            external_ids=SqliteExternalIdentifierRepository(uow),
            field_availability=SqliteFieldAvailabilityRepository(uow),
            sync_state=SqliteSyncStateRepository(uow),
            tombstones=SqliteTombstoneRepository(uow),
            mutations=SqliteMutationRepository(uow),
            organizations=SqliteOrganizationRepository(uow),
        )
