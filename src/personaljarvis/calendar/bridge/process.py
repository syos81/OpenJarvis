"""Prozessmanagement des Kalender-Sidecars.

Die Prozessführung ist gemeinsam (`base.sidecar.process`) — feste
Argumentliste ohne Shell, beide Drainer vor dem ersten Write, absolute
Deadline je Request, typisierte Fehlklassen, `terminate → kill` ohne Zombie,
kein automatischer Retry. Hier steht nur die Bindung an den Kalender-Vertrag.
"""

from __future__ import annotations

from typing import Any

from personaljarvis.base.sidecar.process import (
    DEFAULT_REQUEST_TIMEOUT,
)
from personaljarvis.base.sidecar.process import (
    SidecarProcess as _SidecarProcess,
)
from personaljarvis.calendar.bridge import protocol
from personaljarvis.calendar.bridge.models import CalendarHandshake
from personaljarvis.calendar.bridge.resolver import SidecarLocation

__all__ = ["CalendarSidecarProcess", "DEFAULT_REQUEST_TIMEOUT"]


class CalendarSidecarProcess(_SidecarProcess):
    """Besitzt genau einen Kalender-Sidecar-Kindprozess."""

    def __init__(self, location: SidecarLocation, *,
                 env: dict[str, str] | None = None) -> None:
        self._location = location
        super().__init__(str(location.path), protocol.CALENDAR_CONTRACT,
                         CalendarHandshake.parse, env=env)

    @property
    def handshake(self) -> CalendarHandshake | None:  # type: ignore[override]
        value: Any = super().handshake
        return value
