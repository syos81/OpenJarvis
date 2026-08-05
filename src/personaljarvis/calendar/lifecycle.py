"""Lebenszyklus des Kalendermoduls (14).

Das Modul besitzt **keine eigene** `ConnectionFactory`. Es bekommt die des
Bootstraps injiziert — zwei Factories auf derselben Datei wären zwei Schreiber,
und die Ein-Writer-Zusicherung aus 07 §5 hängt genau an dieser einen Instanz
(`has_active_unit_of_work` ist pro Factory).

Das Modul startet **keinen** Sidecar. Es löst beim Konstruieren nichts auf,
fragt keine Berechtigung an und liest keinen Kalender. Ein Sidecar startet erst
auf eine ausdrückliche Handlung.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from personaljarvis.base.db.factory import ConnectionFactory
from personaljarvis.base.sidecar.errors import BridgeError
from personaljarvis.calendar.bridge.client import CalendarBridgeClient
from personaljarvis.calendar.bridge.models import (
    AuthorizationStatus,
    CalendarCapabilities,
)
from personaljarvis.calendar.bridge.process import CalendarSidecarProcess
from personaljarvis.calendar.bridge.resolver import resolve_sidecar
from personaljarvis.calendar.sync import CalendarSyncService

__all__ = ["CalendarBridgeStatus", "CalendarModule"]


@dataclass(frozen=True)
class CalendarBridgeStatus:
    """Was über die Bridge bekannt ist, ohne sie zu benutzen.

    `available=False` ist ein vollwertiges Ergebnis und kein Fehler: auf einem
    Rechner ohne gebauten Sidecar soll das Modul ehrlich sagen, dass es nichts
    lesen kann — nicht so tun, als wäre der Kalender leer.
    """

    available: bool
    authorization_status: AuthorizationStatus = AuthorizationStatus.UNKNOWN
    capabilities: CalendarCapabilities = CalendarCapabilities()
    detail: str = ""


class CalendarModule:
    """Hält Konfiguration und Dienste des Kalendermoduls."""

    def __init__(self, factory: ConnectionFactory, *,
                 workspace_id: str, provider_account_id: str,
                 sidecar_path: Path | str | None = None,
                 bundle_dir: Path | str | None = None) -> None:
        self._factory = factory
        self._workspace_id = workspace_id
        self._provider_account_id = provider_account_id
        # Bridge-Konfiguration — es wird beim Konstruieren NICHTS aufgelöst
        # und kein Prozess gestartet.
        self._sidecar_path = sidecar_path
        self._bundle_dir = bundle_dir
        self._bridge_status: CalendarBridgeStatus | None = None

    @property
    def connection_factory(self) -> ConnectionFactory:
        return self._factory

    @property
    def workspace_id(self) -> str:
        return self._workspace_id

    @property
    def provider_account_id(self) -> str:
        return self._provider_account_id

    @property
    def bridge_status(self) -> CalendarBridgeStatus:
        """Der zuletzt ermittelte Status. Löst selbst nichts aus."""
        return self._bridge_status or CalendarBridgeStatus(
            available=False, detail="noch nicht geprueft")

    # ── Bridge ──────────────────────────────────────────────────────────────
    def open_client(self) -> CalendarBridgeClient:
        """Startet den Sidecar und liefert einen gestarteten Client.

        Der Aufrufer ist für `stop()` verantwortlich. Diese Methode fragt
        **keine** Berechtigung an — sie liest nur den Handshake.
        """
        location = resolve_sidecar(self._sidecar_path,
                                   bundle_dir=self._bundle_dir)
        client = CalendarBridgeClient(CalendarSidecarProcess(location))
        client.start()
        return client

    def check_bridge(self) -> CalendarBridgeStatus:
        """Kalenderfreier Handshake: Fähigkeiten und Status, sonst nichts.

        Es werden ausschliesslich `ready` und `ping` benutzt — beides gehört zu
        den kalenderfreien Operationen. Kein `EKEventStore`-Zugriff, kein
        Dialog. Fail-closed: jede Bridge-Fehlerfamilie ergibt einen Status
        ohne Fähigkeiten.
        """
        client: CalendarBridgeClient | None = None
        try:
            client = self.open_client()
            handshake = client.handshake
            assert handshake is not None
            client.ping()
            status = CalendarBridgeStatus(
                available=True,
                authorization_status=handshake.authorization_status,
                capabilities=handshake.capabilities,
            )
        except BridgeError as exc:
            status = CalendarBridgeStatus(
                available=False, detail=exc.__class__.__name__)
        finally:
            if client is not None:
                client.stop()
        self._bridge_status = status
        return status

    # ── Dienste ─────────────────────────────────────────────────────────────
    def sync_service(self, client: CalendarBridgeClient) -> CalendarSyncService:
        """Baut den Sync-Dienst über einem bereits gestarteten Client."""
        return CalendarSyncService(
            self._factory, client,
            workspace_id=self._workspace_id,
            provider_account_id=self._provider_account_id,
        )
