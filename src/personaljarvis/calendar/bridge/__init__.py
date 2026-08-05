"""Native Kalender-Bridge (Adapterschicht, AV-4).

Transport, Prozessführung, Binärauflösung und Fehlerklassen kommen aus
`base.sidecar` — hier lebt ausschliesslich der Kalender-Fachvertrag.
"""

from personaljarvis.base.sidecar.errors import (
    BridgeCapabilityMismatch,
    BridgeConfigurationError,
    BridgeError,
    BridgeOperationError,
    BridgeProcessError,
    BridgeProtocolError,
    ProcessDiagnostics,
    ProcessFailureClass,
)
from personaljarvis.calendar.bridge.client import CalendarBridgeClient
from personaljarvis.calendar.bridge.models import (
    AuthorizationStatus,
    BridgeAlarm,
    BridgeAttendee,
    BridgeCalendar,
    BridgeEvent,
    CalendarCapabilities,
    CalendarHandshake,
    CalendarSource,
    EventWindowResult,
)
from personaljarvis.calendar.bridge.process import CalendarSidecarProcess
from personaljarvis.calendar.bridge.resolver import (
    BINARY_NAME,
    SIDECAR_ENV_VAR,
    SidecarLocation,
    resolve_sidecar,
)

__all__ = [
    "CalendarBridgeClient",
    "CalendarSidecarProcess",
    "resolve_sidecar",
    "SidecarLocation",
    "BINARY_NAME",
    "SIDECAR_ENV_VAR",
    "AuthorizationStatus",
    "CalendarCapabilities",
    "CalendarHandshake",
    "CalendarSource",
    "BridgeCalendar",
    "BridgeEvent",
    "BridgeAlarm",
    "BridgeAttendee",
    "EventWindowResult",
    "BridgeError",
    "BridgeConfigurationError",
    "BridgeProtocolError",
    "BridgeProcessError",
    "BridgeOperationError",
    "BridgeCapabilityMismatch",
    "ProcessDiagnostics",
    "ProcessFailureClass",
]
