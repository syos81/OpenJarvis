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

from typing import Any, Final

from personaljarvis.base.sidecar import envelope

__all__ = [
    "PROTOCOL_VERSION",
    "MUTATION_CONTRACT_VERSION",
    "FIELD_CONTRACT_VERSION",
    "MutationOutcome",
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
#: Die Hülle selbst ist seit 2026-08-04 gemeinsam (`base.sidecar.envelope`);
#: hier steht nur noch, welche Version das Kontakte-Modul spricht.
PROTOCOL_VERSION: Final[int] = envelope.PROTOCOL_VERSION

#: Version der Mutationshülle (Pflichtfelder, Ergebnisvertrag) und des
#: Feldvertrags. Beide Seiten nennen sie im Handshake und in jeder
#: Mutationsanfrage; Ungleichheit schaltet die Fähigkeit fail-closed ab
#: (ADR-0025 §6). Die Werte spiegeln `application.field_contract` — dort steht
#: die fachliche Wahrheit, hier die Protokollsicht darauf.
MUTATION_CONTRACT_VERSION: Final[int] = 1
FIELD_CONTRACT_VERSION: Final[int] = 1


class MutationOutcome:
    """Geschlossener Ergebnisvertrag einer Mutation (ADR-0025 §4).

    Die drei Werte sind **nicht** austauschbar: `NOT_SENT` behauptet, dass
    nachweislich nichts übergeben wurde, `OUTCOME_UNKNOWN` behauptet gerade
    das Gegenteil einer Behauptung. Ein Ausgang ausserhalb dieser Menge wird
    fail-closed als `OUTCOME_UNKNOWN` gewertet.
    """

    APPLIED = "applied"
    NOT_SENT = "not_sent"
    OUTCOME_UNKNOWN = "outcome_unknown"

    ALL = frozenset({APPLIED, NOT_SENT, OUTCOME_UNKNOWN})


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

#: Zusätzliche Pflichtfelder jeder Mutation ab Vertragsversion 1. Ohne sie
#: könnte ein Kern einem fremden Sidecar Felder schicken, die dieser still
#: verwirft.
MUTATION_VERSION_FIELDS: Final[tuple[str, ...]] = (
    "mutationContractVersion", "fieldContractVersion",
)


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
    byte-identische Zeilen. Die Serialisierung ist gemeinsam
    (`base.sidecar.envelope`) — nicht kopiert.
    """
    return envelope.encode_request(request_id, operation, payload,
                                   protocol_version=PROTOCOL_VERSION)


def decode_line(line: str) -> dict[str, Any]:
    """Parst eine Antwortzeile. Wirft `ValueError` bei ungültigem JSON-Objekt."""
    return envelope.decode_line(line)


def is_stream_item(message: dict[str, Any]) -> bool:
    """Ob die Nachricht ein Zwischenelement einer Streaming-Antwort ist."""
    return envelope.is_stream_item(message)
