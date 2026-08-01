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
    derive_capabilities,
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
        self._command_bus = None
        self._mutation_service = None
        self._approval_service = None
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
        self._capabilities = derive_capabilities(status)
        # Ein bereits gebauter Mutationsdienst haelt die **alte**
        # Faehigkeitsmenge fest. Wer die Menge aendert, macht ihn damit
        # ungueltig — das ist eine Invariante dieser Klasse und keine
        # Obliegenheit des Aufrufers. Der naechste Zugriff baut ihn neu.
        self._mutation_service = None
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
        self._command_bus = None
        self._mutation_service = None
        self._approval_service = None
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

    # ── Mutationspipeline (Gate C) ──────────────────────────────────────────
    # Alle folgenden Methoden **stellen bereit** und starten nichts: kein
    # Hintergrundexecutor, kein Timer, keine Mutation beim Modulstart, keine
    # Route, keine TCC-Anfrage. Jede Ausführung ist ein ausdrücklicher Aufruf.

    def command_bus(self) -> "ApplicationCommandBus":
        """Der eine Schreibpfad, mit den Kontakte-Commands verdrahtet (AV-35).

        Die registrierten Handler **bereiten vor**; sie senden nichts. Ein
        Dispatch aus UI, CLI oder Chat kann deshalb strukturell keine Mutation
        absenden — dafür braucht es die getrennte Freigabe und `execute()`.
        """
        if not self._started:
            raise PersonalJarvisError("Modul ist nicht gestartet")
        if self._command_bus is None:
            from personaljarvis.base.command_bus import ApplicationCommandBus
            from personaljarvis.contacts.application.command_bus import (
                register_contacts_commands,
            )

            bus = ApplicationCommandBus()
            register_contacts_commands(bus, self.mutation_service())
            self._command_bus = bus
        return self._command_bus

    def mutation_service(self, provider=None) -> "ContactsMutationService":
        """Mutationsdienst. Ohne Provider ist keine Ausführung möglich.

        Produktiv ist der Provider seit ADR-0019 der Sidecar — **nur für
        `create`**. Ob überhaupt gesendet werden darf, entscheidet nicht dieser
        Aufbau, sondern die aus dem Handshake abgeleitete Fähigkeitsmenge:
        ohne passenden Vertragsstand bleibt `create_supported` False und schon
        `prepare` scheitert typisiert.
        """
        if not self._started:
            raise PersonalJarvisError("Modul ist nicht gestartet")
        from personaljarvis.contacts.application.mutation_service import (
            ContactsMutationService,
        )

        if provider is not None:
            return ContactsMutationService(self, provider,
                                           capabilities=self._capabilities)
        if self._mutation_service is None:
            # Der produktive Provider wird von der Kompositionswurzel gesetzt.
            # Fehlt er, bleibt der Standard, der nachweislich nichts sendet.
            ziel = getattr(self, "mutation_provider", None) or _UnavailableProvider()
            self._mutation_service = ContactsMutationService(
                self, ziel, capabilities=self._capabilities)
        return self._mutation_service

    def approval_service(self) -> "ContactsApprovalService":
        if not self._started:
            raise PersonalJarvisError("Modul ist nicht gestartet")
        if self._approval_service is None:
            from personaljarvis.contacts.application.approvals import (
                ContactsApprovalService,
            )

            self._approval_service = ContactsApprovalService(self)
        return self._approval_service

    def reconcile_service(self, reader) -> "ContactsReconcileService":
        """Abgleichdienst. Der Leser ist ausschliesslich lesend."""
        if not self._started:
            raise PersonalJarvisError("Modul ist nicht gestartet")
        from personaljarvis.contacts.application.reconcile import (
            ContactsReconcileService,
        )

        return ContactsReconcileService(self, reader)

    def outbox(self, uow: UnitOfWork):
        """Die ExternalActionOutbox über derselben UnitOfWork."""
        from personaljarvis.base.outbox import ExternalActionOutbox

        return ExternalActionOutbox(uow)

    def audit_trail(self, uow: UnitOfWork):
        """Der Audit-Schreiber über derselben UnitOfWork."""
        from personaljarvis.base.audit import AuditTrail

        return AuditTrail(uow, module="contacts")

    # Hier stand eine zweite Recovery-Fabrik (`build_recovery_service`). Sie
    # hatte im gesamten Baum keinen Aufrufer — auch keinen Test. Gebaut wird
    # die Wiederherstellung ausschliesslich vom `ContactsRecoveryEntrypoint`
    # (application/live.py), den die Kompositionswurzel unter
    # `recovery_service` ablegt. Zwei Aufbauwege fuer denselben Dienst sind
    # einer zu viel: der ungenutzte veraltet unbemerkt und behauptet eine
    # Einstiegsmoeglichkeit, die niemand prueft.

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


class _UnavailableProvider:
    """Standard-Provider: es gibt in Gate C keinen echten Schreibpfad.

    Wer ohne ausdrücklich übergebenen Provider auszuführen versucht, bekommt
    einen typisierten Fehler statt eines stillen Fehlversuchs. Der Aufruf ist
    nachweislich **vor** jedem Send.
    """

    def apply(self, payload, *, mutation_id: str, idempotency_key: str,
              approval_id: str):
        from personaljarvis.contacts.application.models import ProviderOutcome
        from personaljarvis.contacts.application.mutation_service import (
            ProviderResponse,
        )

        return ProviderResponse(ProviderOutcome.FAILED_BEFORE_SEND,
                                error_code="not_implemented")
