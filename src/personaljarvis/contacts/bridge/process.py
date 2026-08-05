"""Prozessmanagement des Kontakte-Sidecars (Plan §15, Deadlock-/Zombie-Risiko).

Seit 2026-08-04 steht die Prozessführung in `base.sidecar.process`; hier bleibt
nur noch die **Bindung an den Kontakte-Vertrag**: Operationssatz, stderr-Marker
und Handshake-Typ. Verhalten und Garantien sind unverändert — die Klasse ist
dieselbe, nur vorkonfiguriert.

Verbindliche Eigenschaften (dort umgesetzt, hier zur Erinnerung): feste
Argumentliste ohne Shell, beide Drainer vor dem ersten Write, absolute
Deadline je Request, jede Fehlklasse typisiert, `terminate → kill` ohne
Zombie, **kein** automatischer Retry — schon gar nicht bei Mutationen.
"""

from __future__ import annotations

from typing import Any

from personaljarvis.base.sidecar.envelope import SidecarContract
from personaljarvis.base.sidecar.process import (
    _STDERR_MAX_LEN,
    DEFAULT_REQUEST_TIMEOUT,
    _technische_stderr_zeile,
)
from personaljarvis.base.sidecar.process import (
    SidecarProcess as _SidecarProcess,
)
from personaljarvis.contacts.bridge import protocol
from personaljarvis.contacts.bridge.models import Handshake
from personaljarvis.contacts.bridge.resolver import SidecarLocation

# `_STDERR_MAX_LEN` und `_technische_stderr_zeile` sind mit der Hebung nach
# `base.sidecar` umgezogen. Sie bleiben hier ausdrücklich exportiert, weil die
# bestehende Kontakte-Suite sie unter diesem Namen prüft
# (test_crash_diagnostics) — die Regel ist dieselbe, nur ihr Wohnort ist neu.
__all__ = [
    "SidecarProcess", "DEFAULT_REQUEST_TIMEOUT", "CONTACTS_CONTRACT",
    "_STDERR_MAX_LEN", "_technische_stderr_zeile",
]

#: Der Kontakte-Vertrag, wie ihn die generische Prozessführung braucht.
CONTACTS_CONTRACT = SidecarContract(
    stderr_prefix="contacts-bridge",
    mutating_operations=protocol.MUTATING_OPERATIONS,
    shutdown_operation=protocol.Operation.SHUTDOWN,
    protocol_version=protocol.PROTOCOL_VERSION,
)


class SidecarProcess(_SidecarProcess):
    """Besitzt genau einen Kontakte-Sidecar-Kindprozess.

    Nimmt weiterhin eine geprüfte `SidecarLocation` entgegen — der Aufrufer
    sieht keinen Unterschied zur Fassung vor der Hebung.
    """

    def __init__(self, location: SidecarLocation, *,
                 env: dict[str, str] | None = None) -> None:
        self._location = location
        super().__init__(str(location.path), CONTACTS_CONTRACT,
                         Handshake.parse, env=env)

    @property
    def handshake(self) -> Handshake | None:  # type: ignore[override]
        value: Any = super().handshake
        return value
