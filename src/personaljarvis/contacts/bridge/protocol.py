"""Produktiver JSON-Lines-Vertrag der Kontakte-Bridge (Plan §9.1).

Dies ist **nicht** der Spike-Vertrag. Begründete Abweichungen:

* `token` existiert nicht — der Cursor kommt ausschließlich aus der
  `changes`-Antwort, nie aus einem zweiten Store-Read (11 §3).
* `getUnified` heißt `getUnifiedReadOnly` — der belegten Identifier-
  Instabilität wegen ist es ein reiner Lesepfad.
* `updateViaUnified` fehlt — Schreiben auf unified contacts ist ausgeschlossen.
* `create`/`update`/`delete` verlangen `mutationId`, `idempotencyKey`,
  `approvalId` und bei Update/Delete `targetProviderIdentifier`.
* Kein Präfix-Rail, keine Diagnose-Proben, kein Env-Gate.

Die Hülle ist versioniert; eine inkompatible Version wird fail-closed
abgelehnt.
"""

from __future__ import annotations

import json
from typing import Any, Final

__all__ = [
    "PROTOCOL_VERSION",
    "Operation",
    "READ_OPERATIONS",
    "MUTATING_OPERATIONS",
    "CONTACT_FREE_OPERATIONS",
    "ErrorCode",
    "encode_request",
    "decode_line",
    "is_stream_item",
]

#: Version der Protokollhülle. Änderung erzwingt beidseitige Anpassung.
PROTOCOL_VERSION: Final[int] = 1


class Operation:
    """Alle produktiv vereinbarten Operationen."""

    PING = "ping"
    CAPS = "caps"
    SHUTDOWN = "shutdown"
    AUTHORIZATION_STATUS = "authorizationStatus"
    REQUEST_AUTHORIZATION = "requestAuthorization"
    CONTAINERS = "containers"
    ENUMERATE = "enumerate"
    CHANGES = "changes"
    GET = "get"
    GET_UNIFIED_READ_ONLY = "getUnifiedReadOnly"
    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"


#: Operationen ohne jeden Store-Zugriff — nur diese dürfen ohne erteilte
#: Autorisierung und in kontaktfreien Tests ausgeführt werden.
CONTACT_FREE_OPERATIONS: Final[frozenset[str]] = frozenset({
    Operation.PING,
    Operation.CAPS,
    Operation.AUTHORIZATION_STATUS,
    Operation.SHUTDOWN,
})

#: Lesende Store-Operationen.
READ_OPERATIONS: Final[frozenset[str]] = frozenset({
    Operation.CONTAINERS,
    Operation.ENUMERATE,
    Operation.CHANGES,
    Operation.GET,
    Operation.GET_UNIFIED_READ_ONLY,
})

#: Mutierende Operationen. Ein Abbruch führt zu `mutation_outcome_unknown`.
MUTATING_OPERATIONS: Final[frozenset[str]] = frozenset({
    Operation.CREATE,
    Operation.UPDATE,
    Operation.DELETE,
})

#: Pflichtfelder jeder Mutation (Plan §7.1). Ohne sie ist 11 §3 nicht erfüllbar.
MUTATION_REQUIRED_FIELDS: Final[tuple[str, ...]] = (
    "mutationId", "idempotencyKey", "approvalId",
)
MUTATION_TARGET_FIELD: Final[str] = "targetProviderIdentifier"


class ErrorCode:
    """Geschlossene Fehlermenge des Vertrags."""

    TCC_DENIED = "tcc_denied"
    NOT_FOUND = "not_found"
    CONFLICT = "conflict"
    INVALID_REQUEST = "invalid_request"
    FORBIDDEN = "forbidden"
    PROVIDER_ERROR = "provider_error"
    UNSUPPORTED = "unsupported"
    INTERNAL = "internal"
    NOT_IMPLEMENTED = "not_implemented"
    PROTOCOL_MISMATCH = "protocol_mismatch"
    INVALID_TOKEN = "invalid_token"

    ALL = frozenset({
        TCC_DENIED, NOT_FOUND, CONFLICT, INVALID_REQUEST, FORBIDDEN,
        PROVIDER_ERROR, UNSUPPORTED, INTERNAL, NOT_IMPLEMENTED,
        PROTOCOL_MISMATCH, INVALID_TOKEN,
    })


def encode_request(request_id: int, operation: str,
                   payload: dict[str, Any] | None = None) -> str:
    """Serialisiert eine Anfrage deterministisch als eine JSON-Zeile.

    Sortierte Schlüssel und kompakte Trenner: zwei gleiche Anfragen ergeben
    byte-identische Zeilen.
    """
    envelope = {
        "protocolVersion": PROTOCOL_VERSION,
        "requestId": request_id,
        "operation": operation,
        "payload": payload or {},
    }
    return json.dumps(envelope, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False)


def decode_line(line: str) -> dict[str, Any]:
    """Parst eine Antwortzeile. Wirft `ValueError` bei ungültigem JSON-Objekt."""
    data = json.loads(line)
    if not isinstance(data, dict):
        raise ValueError("Antwortzeile ist kein JSON-Objekt")
    return data


def is_stream_item(message: dict[str, Any]) -> bool:
    """Ob die Nachricht ein Zwischenelement einer Streaming-Antwort ist."""
    return message.get("stream") == "item"
