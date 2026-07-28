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
from personaljarvis.contacts.bridge.errors import (
    BridgeConfigurationError,
    BridgeError,
    BridgeProtocolError,
)
from personaljarvis.contacts.bridge.models import BridgeCapabilities
from personaljarvis.contacts.bridge.process import SidecarProcess
from personaljarvis.contacts.bridge.resolver import resolve_sidecar
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
    """Teilmenge der Zustandsmaschine aus 14 §4, die Gate A/B erreichen kann."""

    NOT_INSTALLED = "not_installed"
    INITIALIZING = "initializing"
    MIGRATION_REQUIRED = "migration_required"
    CONFIGURATION_REQUIRED = "configuration_required"
    PERMISSION_REQUIRED = "permission_required"
    DEGRADED = "degraded"
    ERROR = "error"
    SHUTTING_DOWN = "shutting_down"


@dataclass(frozen=True)
class BridgeStatus:
    """Ergebnis des kontaktfreien Bridge-Startchecks (Gate B).

    Der Check berührt den Kontakte-Store **nicht**: er startet den Sidecar,
    liest den Handshake, prüft `ping`/`caps` und fährt ihn wieder herunter.
    """

    available: bool
    reason: str = ""
    protocol_version: int | None = None
    authorization_status: str | None = None
    capabilities: "BridgeCapabilities | None" = None
    architectures: tuple[str, ...] = ()


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

    def __init__(self, database_path: Path | str | None = None, *,
                 sidecar_path: Path | str | None = None,
                 bundle_dir: Path | str | None = None) -> None:
        self._factory = ConnectionFactory(database_path)
        self._state = ModuleState.NOT_INSTALLED
        self._report: MigrationReport | None = None
        self._capabilities: ContactCapabilitySet | None = None
        self._started = False
        # Bridge-Konfiguration — es wird beim Konstruieren NICHTS aufgelöst
        # und kein Prozess gestartet.
        self._sidecar_path = sidecar_path
        self._bundle_dir = bundle_dir
        self._bridge_status: BridgeStatus | None = None

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

    @property
    def bridge_status(self) -> BridgeStatus | None:
        """Ergebnis des letzten Bridge-Startchecks; `None` vor dem ersten Lauf."""
        return self._bridge_status

    # ── Bridge-Startcheck (kontaktfrei) ─────────────────────────────────────
    def check_bridge(self) -> BridgeStatus:
        """Startet den Sidecar kontaktfrei und prüft Handshake, `ping`, `caps`.

        Ausdrücklich **kein** Store-Zugriff: es wird weder `containers` noch
        `enumerate`, `changes`, `get` noch `requestAuthorization` gesendet.
        Der Prozess wird danach graziös beendet.

        Der Zustand des Moduls wird entsprechend gesetzt; ein fehlendes Binary
        oder ein Protokollfehler führt zu `degraded`, nie zu einem Absturz.
        """
        try:
            location = resolve_sidecar(self._sidecar_path,
                                       bundle_dir=self._bundle_dir)
        except BridgeConfigurationError as exc:
            self._bridge_status = BridgeStatus(available=False, reason=str(exc))
            self._state = ModuleState.DEGRADED
            return self._bridge_status

        process = SidecarProcess(location)
        try:
            handshake = process.start()
            # Nur kontaktfreie Operationen (protocol.CONTACT_FREE_OPERATIONS).
            from personaljarvis.contacts.bridge import protocol as _p

            envelope = process.request(_p.Operation.PING, timeout=10.0)
            if envelope.get("ok") is not True:
                raise BridgeProtocolError("ping wurde nicht beantwortet")
            status = BridgeStatus(
                available=True,
                protocol_version=handshake.protocol_version,
                authorization_status=handshake.authorization_status.value,
                capabilities=handshake.capabilities,
                architectures=location.architectures,
            )
        except BridgeError as exc:
            status = BridgeStatus(available=False, reason=str(exc))
        finally:
            process.stop()

        self._bridge_status = status
        if not status.available:
            self._state = ModuleState.DEGRADED
        elif status.authorization_status != "authorized":
            # Ohne erteilte Berechtigung ist kein Lesepfad möglich — das ist
            # ein benannter Zustand, keine Fehlermeldung (14 §4).
            self._state = ModuleState.PERMISSION_REQUIRED
        else:
            # Autorisierung liegt vor, aber ohne Binding/Import ist das Modul
            # weiterhin nicht `ready` (Gate B endet vor dem Initialimport).
            self._state = ModuleState.CONFIGURATION_REQUIRED
        return status

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
        self._bridge_status = None
        self._state = ModuleState.NOT_INSTALLED

    # ── Synchronisation (Bereitstellung, kein Lauf) ─────────────────────────
    def sync_service(self, client, *, workspace_id: str,
                     provider_account_id: str):
        """Stellt den Sync-Dienst bereit — und startet **nichts**.

        Ausdrücklich nicht Teil dieser Methode: ein Store-Zugriff, ein
        Initialimport, ein Hintergrundlauf, ein Timer. Der Aufrufer übergibt
        einen bereits gestarteten Bridge-Client und löst jeden Lauf einzeln
        aus (Plan §13).

        Der Import steht bewusst **im Rumpf**: der Sync-Dienst kennt den
        Lebenszyklus nur strukturell, ein Modulimport oben schlösse den Zyklus.
        """
        if not self._started:
            raise PersonalJarvisError("Modul ist nicht gestartet")
        from personaljarvis.contacts.sync.service import ContactsSyncService

        return ContactsSyncService(client, self, workspace_id=workspace_id,
                                   provider_account_id=provider_account_id)

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
