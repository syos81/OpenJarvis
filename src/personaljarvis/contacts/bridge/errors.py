"""Geschlossene Fehlermenge der Native-Bridge (08 §3 Nr. 5).

Seit 2026-08-04 leben diese Klassen in `base.sidecar.errors` — sie waren nie
kontaktspezifisch, und der Kalender braucht dieselben. Dieses Modul bleibt der
Importweg des Kontakte-Moduls; die Typen sind **identisch**, nicht kopiert
(ein `except BridgeError` fängt hier wie dort dasselbe Objekt).

**Keine rohe Provider-Exception verlässt den Adapter** und keine dieser
Meldungen enthält jemals Kontaktdaten — weder Namen, Adressen, Nummern noch
Provider-Identifier. Diagnosetexte beschreiben ausschließlich Technik.
"""

from __future__ import annotations

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

__all__ = [
    "BridgeError",
    "BridgeConfigurationError",
    "BridgeProtocolError",
    "BridgeProcessError",
    "BridgeOperationError",
    "BridgeCapabilityMismatch",
    "MutationOutcomeUnknown",
    "ProcessDiagnostics",
    "ProcessFailureClass",
]
