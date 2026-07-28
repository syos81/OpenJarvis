"""Native-Bridge des Kontakte-Moduls (ADR-0016, DEC-031).

Der Import dieses Pakets hat **keine** Nebenwirkung: es wird kein Prozess
gestartet, kein Binary gesucht, keine Berechtigung abgefragt und kein
Kontakte-Store berührt. Der Sidecar startet ausschließlich über einen
ausdrücklichen `SidecarProcess.start()`.

Die Schichtung folgt AV-4: Apple-Typen existieren nur jenseits des Sidecars;
diesseits gibt es ausschließlich providerneutrale DTOs.
"""

from __future__ import annotations

from personaljarvis.contacts.bridge.client import ContactsBridgeClient
from personaljarvis.contacts.bridge.errors import (
    BridgeCapabilityMismatch,
    BridgeConfigurationError,
    BridgeError,
    BridgeOperationError,
    BridgeProcessError,
    BridgeProtocolError,
    MutationOutcomeUnknown,
    ProcessDiagnostics,
    ProcessFailureClass,
)
from personaljarvis.contacts.bridge.models import (
    AuthorizationStatus,
    BridgeCapabilities,
    BridgeContact,
    ChangeEvent,
    ChangeEventType,
    ChangesResult,
    ContainerInfo,
    EnumerationResult,
    FieldAvailability,
    FieldState,
    Handshake,
)
from personaljarvis.contacts.bridge.process import SidecarProcess
from personaljarvis.contacts.bridge.protocol import (
    CONTACT_FREE_OPERATIONS,
    MUTATING_OPERATIONS,
    PROTOCOL_VERSION,
    READ_OPERATIONS,
    ErrorCode,
    Operation,
)
from personaljarvis.contacts.bridge.resolver import (
    BINARY_NAME,
    SidecarLocation,
    host_architecture,
    resolve_sidecar,
    tauri_triple,
)

__all__ = [
    "PROTOCOL_VERSION",
    "Operation",
    "ErrorCode",
    "CONTACT_FREE_OPERATIONS",
    "READ_OPERATIONS",
    "MUTATING_OPERATIONS",
    "FieldState",
    "FieldAvailability",
    "AuthorizationStatus",
    "BridgeCapabilities",
    "Handshake",
    "ContainerInfo",
    "BridgeContact",
    "ChangeEvent",
    "ChangeEventType",
    "ChangesResult",
    "EnumerationResult",
    "BridgeError",
    "BridgeConfigurationError",
    "BridgeProtocolError",
    "BridgeProcessError",
    "BridgeOperationError",
    "BridgeCapabilityMismatch",
    "MutationOutcomeUnknown",
    "ProcessDiagnostics",
    "ProcessFailureClass",
    "SidecarProcess",
    "SidecarLocation",
    "ContactsBridgeClient",
    "BINARY_NAME",
    "host_architecture",
    "tauri_triple",
    "resolve_sidecar",
]
