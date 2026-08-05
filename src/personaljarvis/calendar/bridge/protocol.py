"""Produktiver JSON-Lines-Vertrag der Kalender-Bridge (v1, nur Lesen).

Die **Hülle** ist gemeinsam (`base.sidecar.envelope`) — Transport, Streaming
und Versionsgrenze teilt sich der Kalender mit den Kontakten. Hier steht nur
der Fachvertrag: welche Operationen es gibt und welche Fehlercodes gelten.

Bewusste Unterschiede zum Kontakte-Vertrag:

* Es gibt **keine** `changes`-Operation und keinen Cursor. EventKit hat kein
  Gegenstück zu `CNChangeHistory`; `EKEventStoreChangedNotification` ist ein
  Auslöser, nie ein Delta. Wer sie als Delta behandelt, verliert Änderungen.
* `events` verlangt zwingend ein Fenster. Es gibt in EventKit kein „alle
  Termine"; ein Kalender hat weder Anfang noch Ende.
* `MUTATING_OPERATIONS` ist in v1 **leer**: es gibt keine Schreiboperation, die
  abbrechen könnte. Der Schreibvertrag entsteht mit dem Schreibauftrag und
  erbt dann ADR-0019/0020 unverändert.
"""

from __future__ import annotations

from typing import Any, Final

from personaljarvis.base.sidecar import envelope
from personaljarvis.base.sidecar.envelope import SidecarContract

__all__ = [
    "PROTOCOL_VERSION",
    "STDERR_PREFIX",
    "Operation",
    "CALENDAR_FREE_OPERATIONS",
    "READ_OPERATIONS",
    "MUTATING_OPERATIONS",
    "ErrorCode",
    "CALENDAR_CONTRACT",
    "encode_request",
    "decode_line",
    "is_stream_item",
]

PROTOCOL_VERSION: Final[int] = envelope.PROTOCOL_VERSION

#: Marker der eigenen stderr-Zeilen. Alles ohne ihn gilt dem Host als fremd
#: und wird redigiert.
STDERR_PREFIX: Final[str] = "calendar-bridge"


class Operation:
    """Alle produktiv vereinbarten Operationen (v1)."""

    PING = "ping"
    CAPS = "caps"
    SHUTDOWN = "shutdown"
    AUTHORIZATION_STATUS = "authorizationStatus"
    REQUEST_AUTHORIZATION = "requestAuthorization"
    CALENDARS = "calendars"
    EVENTS = "events"


#: Operationen ohne jeden Store-Zugriff — nur diese dürfen ohne erteilte
#: Autorisierung und in kalenderfreien Tests ausgeführt werden.
CALENDAR_FREE_OPERATIONS: Final[frozenset[str]] = frozenset({
    Operation.PING,
    Operation.CAPS,
    Operation.AUTHORIZATION_STATUS,
    Operation.SHUTDOWN,
})

#: Lesende Store-Operationen.
READ_OPERATIONS: Final[frozenset[str]] = frozenset({
    Operation.CALENDARS,
    Operation.EVENTS,
})

#: v1 mutiert nicht. Die Menge bleibt bewusst als leere Menge stehen statt zu
#: fehlen: sie ist der Ort, an dem der Schreibauftrag ansetzt, und der Beleg,
#: dass hier heute nichts mutiert.
MUTATING_OPERATIONS: Final[frozenset[str]] = frozenset()


class ErrorCode:
    """Geschlossene Fehlermenge des Vertrags."""

    TCC_DENIED = "tcc_denied"
    NOT_FOUND = "not_found"
    INVALID_REQUEST = "invalid_request"
    FORBIDDEN = "forbidden"
    PROVIDER_ERROR = "provider_error"
    UNSUPPORTED = "unsupported"
    INTERNAL = "internal"
    NOT_IMPLEMENTED = "not_implemented"
    PROTOCOL_MISMATCH = "protocol_mismatch"

    ALL = frozenset({
        TCC_DENIED, NOT_FOUND, INVALID_REQUEST, FORBIDDEN, PROVIDER_ERROR,
        UNSUPPORTED, INTERNAL, NOT_IMPLEMENTED, PROTOCOL_MISMATCH,
    })


#: Was die gemeinsame Prozessführung vom Kalender-Vertrag wissen muss.
CALENDAR_CONTRACT: Final[SidecarContract] = SidecarContract(
    stderr_prefix=STDERR_PREFIX,
    mutating_operations=MUTATING_OPERATIONS,
    shutdown_operation=Operation.SHUTDOWN,
    protocol_version=PROTOCOL_VERSION,
)


def encode_request(request_id: int, operation: str,
                   payload: dict[str, Any] | None = None) -> str:
    """Serialisiert eine Anfrage deterministisch als eine JSON-Zeile."""
    return envelope.encode_request(request_id, operation, payload,
                                   protocol_version=PROTOCOL_VERSION)


def decode_line(line: str) -> dict[str, Any]:
    """Parst eine Antwortzeile. Wirft `ValueError` bei ungültigem JSON-Objekt."""
    return envelope.decode_line(line)


def is_stream_item(message: dict[str, Any]) -> bool:
    """Ob die Nachricht ein Zwischenelement einer Streaming-Antwort ist."""
    return envelope.is_stream_item(message)
