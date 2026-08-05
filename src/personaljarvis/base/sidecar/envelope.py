"""Die gemeinsame JSON-Lines-Hülle nativer Sidecar-Bridges.

Nur die **Hülle** — nicht der Fachvertrag. Welche Operationen es gibt, welche
davon mutieren und welche Fehlercodes gelten, entscheidet jedes Modul in
seinem eigenen `protocol`-Modul und reicht es als `SidecarContract` an den
Prozess weiter. So teilen sich Kontakte und Kalender Transport, Deadlines und
Fehlerklassen, ohne sich einen Operationssatz zu teilen, den nur eines von
beiden hat.

Determinismus ist Vertragsbestandteil: sortierte Schlüssel, kompakte Trenner.
Zwei gleiche Anfragen ergeben byte-identische Zeilen.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Final

__all__ = [
    "PROTOCOL_VERSION",
    "SidecarContract",
    "encode_request",
    "decode_line",
    "is_stream_item",
]

#: Version der Hülle. Beide Seiten nennen sie; Ungleichheit ist fail-closed.
PROTOCOL_VERSION: Final[int] = 1


@dataclass(frozen=True)
class SidecarContract:
    """Was `SidecarProcess` vom Fachvertrag wissen muss — und nicht mehr.

    `stderr_prefix` ist der Marker, mit dem der jeweilige Sidecar seine
    **eigenen**, bereits technischen Diagnosezeilen kennzeichnet. Alles ohne
    diesen Marker gilt als fremd und wird redigiert (siehe `process`).
    """

    #: Marker der eigenen stderr-Zeilen, z. B. `contacts-bridge`.
    stderr_prefix: str
    #: Operationen, deren Abbruch `mutation_outcome_unknown` ergibt.
    mutating_operations: frozenset[str] = field(default_factory=frozenset)
    #: Name der Shutdown-Operation für den graziösen Stop.
    shutdown_operation: str = "shutdown"
    #: Erwartete Hüllenversion.
    protocol_version: int = PROTOCOL_VERSION


def encode_request(request_id: int, operation: str,
                   payload: dict[str, Any] | None = None,
                   *, protocol_version: int = PROTOCOL_VERSION) -> str:
    """Serialisiert eine Anfrage deterministisch als eine JSON-Zeile."""
    envelope = {
        "protocolVersion": protocol_version,
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
