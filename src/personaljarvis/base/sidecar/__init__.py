"""Gemeinsame Primitive nativer Sidecar-Bridges (08 §4).

Transport, Prozessführung, Binärauflösung und Fehlerklassen — alles, was
mehr als ein Modul braucht und nichts, was zu einem Fachbereich gehört.
Der Operationssatz, die Fähigkeiten und das DTO bleiben je Modul (Kontakte:
`contacts.bridge`, Kalender: `calendar.bridge`).

Entstanden 2026-08-04 durch Hebung aus `contacts.bridge`, als der Kalender
denselben Prozessvertrag brauchte — nicht vorsorglich (AV-33).
"""

from personaljarvis.base.sidecar.envelope import (
    PROTOCOL_VERSION,
    SidecarContract,
    decode_line,
    encode_request,
    is_stream_item,
)
from personaljarvis.base.sidecar.errors import (
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
from personaljarvis.base.sidecar.process import (
    DEFAULT_REQUEST_TIMEOUT,
    SidecarProcess,
)
from personaljarvis.base.sidecar.resolver import (
    SidecarLocation,
    binary_architectures,
    host_architecture,
    resolve_sidecar,
    tauri_triple,
)

__all__ = [
    "PROTOCOL_VERSION",
    "SidecarContract",
    "encode_request",
    "decode_line",
    "is_stream_item",
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
    "DEFAULT_REQUEST_TIMEOUT",
    "SidecarLocation",
    "resolve_sidecar",
    "host_architecture",
    "tauri_triple",
    "binary_architectures",
]
