"""Transportverträge des App-Prozess-Mutationskanals (ADR-0026 §5).

**Dies ist die normative Quelle.** TypeScript (`executionContracts.ts`) und
Rust (`contacts_execution.rs`) bilden dieselben Verträge nach; goldene
Fixtures (`tests/personal/contacts/fixtures/execution_contracts/`) werden
aus **dieser** Datei erzeugt, und Statiktests in allen drei Sprachen lesen
sie. Eine Felddrift bricht damit den Build, statt erst zur Laufzeit
aufzufallen.

Zwei Objekte, zwei Richtungen:

* `ExecutionOrderV1` — was das Backend beim Claim ausgibt. Es enthält
  ausschliesslich, was der native Save braucht: **keine** Approval-Objekte,
  **keine** Audit-Historie, **keine** Datenbankzeilen.
* `ExecutionReportV1` — was aus dem App-Prozess zurückkommt. Geschlossene
  Ausgänge, geschlossene Fehlerklassen, keine frei interpretierbaren
  Ergebnis-Zeichenketten: das Backend soll nichts raten müssen.

Beide sind versioniert und **fail-closed**: unbekannte Felder, fremde
Versionen und zu grosse Nutzlasten werden abgewiesen, nie ignoriert.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any

from personaljarvis.base.digest import canonical_json, digest_of

__all__ = [
    "EXECUTION_SCHEMA_VERSION",
    "OPERATION_TYPES",
    "REPORT_OUTCOMES",
    "READBACK_STATUSES",
    "ERROR_CLASSES",
    "PRE_SEND_ERROR_CLASSES",
    "POST_SEND_ERROR_CLASSES",
    "MAX_ORDER_BYTES",
    "MAX_REPORT_BYTES",
    "ExecutionOrderV1",
    "ExecutionReportV1",
    "ExecutionContractError",
    "parse_execution_report",
    "report_digest",
]

#: Version der Transporthülle. Getrennt von Feld- und Mutationsvertrag,
#: weil sich die Hülle unabhängig ändern kann.
EXECUTION_SCHEMA_VERSION = 1

OPERATION_TYPES: tuple[str, ...] = ("create", "update", "delete")

#: Geschlossene Ausgänge — wortgleich mit ADR-0025 §4 und ADR-0026 §5.
REPORT_OUTCOMES: tuple[str, ...] = ("applied", "not_sent", "outcome_unknown")

READBACK_STATUSES: tuple[str, ...] = (
    "confirmed", "absent_confirmed", "failed", "not_attempted",
)

#: Klassen, die **beweisen**, dass nichts übergeben wurde.
PRE_SEND_ERROR_CLASSES: tuple[str, ...] = (
    "invalid_claim", "expired_claim_before_send", "digest_mismatch",
    "schema_mismatch", "capability_denied", "not_authorized",
    "target_not_found", "revision_conflict", "invalid_payload",
    "unsupported_field", "container_unavailable", "write_stack_unavailable",
    "provider_channel_disabled_before_send",
)

#: Klassen, nach denen ein Send stattgefunden haben **kann**.
POST_SEND_ERROR_CLASSES: tuple[str, ...] = (
    "provider_exception", "provider_save_error", "readback_failed",
    "response_lost", "app_process_crash", "backend_unreachable_for_settle",
)

ERROR_CLASSES: tuple[str, ...] = PRE_SEND_ERROR_CLASSES + POST_SEND_ERROR_CLASSES

#: Größenlimits (ADR-0026 §5). Darüber ist fail-closed `schema_mismatch`.
MAX_ORDER_BYTES = 64 * 1024
MAX_REPORT_BYTES = 256 * 1024

_HEX64 = 64


class ExecutionContractError(ValueError):
    """Vertragsverletzung im Transport — trägt eine geschlossene Klasse."""

    def __init__(self, error_class: str, message: str) -> None:
        if error_class not in ERROR_CLASSES:
            raise ValueError(f"Unbekannte Fehlerklasse: {error_class}")
        super().__init__(message)
        self.error_class = error_class


def _hex64(wert: object, feld: str) -> str:
    if not isinstance(wert, str) or len(wert) != _HEX64 \
            or any(z not in "0123456789abcdef" for z in wert):
        raise ExecutionContractError(
            "schema_mismatch", f"{feld} ist kein 64-stelliger Hexdigest")
    return wert


@dataclass(frozen=True, slots=True)
class ExecutionOrderV1:
    """Der kurzlebige, gebundene Ausführungsauftrag.

    `claim_token` ist der **einzige** Rohwert hier: er existiert genau
    einmal, wandert durch das Frontend in den App-Prozess und kommt im
    Settle zurück. Persistiert wird nur sein Digest.
    """

    operation_id: str
    mutation_id: str
    claim_token: str
    operation_type: str
    payload_digest: str
    preview_digest: str
    canonical_payload: dict[str, Any]
    issued_at: str
    expires_at: str
    expected_revision: str | None = None
    provider_target: dict[str, str | None] = field(default_factory=dict)
    readback_requirements: dict[str, Any] = field(
        default_factory=lambda: {"required": True, "keys": "field_contract_v1"})
    schema_version: int = EXECUTION_SCHEMA_VERSION
    mutation_contract_version: int = 1
    field_contract_version: int = 1
    transaction_author: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        text = canonical_json(self.as_dict())
        if len(text.encode("utf-8")) > MAX_ORDER_BYTES:
            raise ExecutionContractError(
                "schema_mismatch", "Ausführungsauftrag überschreitet das Limit")
        return text

    def payload_digest_matches(self) -> bool:
        """Der Auftrag trägt genau den Digest seines kanonischen Payloads."""
        return digest_of(self.canonical_payload) == self.payload_digest


@dataclass(frozen=True, slots=True)
class ExecutionReportV1:
    """Das typisierte Ergebnis aus dem App-Prozess.

    `save_request_count` ist bewusst Teil des Vertrags: Mehr als ein
    Speicherauftrag je Claim ist ein Vertragsbruch, und der Bericht muss
    ihn melden können, statt ihn zu verschweigen.
    """

    operation_id: str
    mutation_id: str
    operation_type: str
    outcome: str
    send_attempted: bool
    save_request_count: int
    readback_status: str
    schema_version: int = EXECUTION_SCHEMA_VERSION
    provider_identifier_digest: str | None = None
    #: Die **rohe** Providerkennung. ADR-0026 §5 nennt sie ausdruecklich: das
    #: Backend braucht sie fuer die External-ID, sonst gaebe es nach dem
    #: Create keinen Weg zurueck zu diesem Kontakt. Sie reist ausschliesslich
    #: im Settle-Rumpf und darf niemals in Audit, Log, Oberflaeche oder
    #: normaler API erscheinen — dort steht der Digest.
    provider_identifier: str | None = None
    #: Der gelesene Zustand als BridgeContact-DTO (ADR-0026 §5). Aus ihm
    #: bildet der Kern den `readback_digest` und fuehrt den lokalen Spiegel
    #: nach — erfunden wird nichts.
    readback_contact: dict[str, Any] | None = None
    readback_revision: str | None = None
    readback_digest: str | None = None
    error_class: str | None = None
    error_digest: str | None = None
    diagnostic_artifact_present: bool = False
    provider_completed_at: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def beweist_nichts_gesendet(self) -> bool:
        """Nur `not_sent` **ohne** Sendeversuch beweist die Unversehrtheit."""
        return self.outcome == "not_sent" and not self.send_attempted


def _pflicht(rohdaten: dict[str, Any], name: str) -> Any:
    if name not in rohdaten:
        raise ExecutionContractError(
            "schema_mismatch", f"Pflichtfeld fehlt: {name}")
    return rohdaten[name]


def parse_execution_report(rohdaten: object) -> ExecutionReportV1:
    """Liest einen Bericht fail-closed.

    Jede Abweichung ist ein Vertragsbruch mit geschlossener Klasse — es gibt
    keinen „unbekanntes Feld wird ignoriert"-Pfad: was der Kern nicht kennt,
    kann er nicht bewerten, und ein stiller Verlust wäre schlimmer als eine
    Ablehnung.
    """
    if isinstance(rohdaten, (str, bytes)):
        roh = rohdaten if isinstance(rohdaten, bytes) else rohdaten.encode("utf-8")
        if len(roh) > MAX_REPORT_BYTES:
            raise ExecutionContractError(
                "schema_mismatch", "Bericht überschreitet das Limit")
        try:
            rohdaten = json.loads(roh)
        except ValueError as exc:
            raise ExecutionContractError(
                "schema_mismatch", "Bericht ist kein gültiges JSON") from exc

    if not isinstance(rohdaten, dict):
        raise ExecutionContractError("schema_mismatch", "Bericht ist kein Objekt")

    erlaubt = set(ExecutionReportV1.__dataclass_fields__)
    unbekannt = sorted(set(rohdaten) - erlaubt)
    if unbekannt:
        raise ExecutionContractError(
            "schema_mismatch", f"Unbekannte Felder: {', '.join(unbekannt)}")

    version = rohdaten.get("schema_version", EXECUTION_SCHEMA_VERSION)
    if version != EXECUTION_SCHEMA_VERSION:
        raise ExecutionContractError(
            "schema_mismatch",
            f"Fremde Schemaversion: {version!r}")

    outcome = _pflicht(rohdaten, "outcome")
    if outcome not in REPORT_OUTCOMES:
        raise ExecutionContractError(
            "schema_mismatch", f"Unbekannter Ausgang: {outcome!r}")

    operation_type = _pflicht(rohdaten, "operation_type")
    if operation_type not in OPERATION_TYPES:
        raise ExecutionContractError(
            "schema_mismatch", f"Unbekannte Operation: {operation_type!r}")

    readback_status = _pflicht(rohdaten, "readback_status")
    if readback_status not in READBACK_STATUSES:
        raise ExecutionContractError(
            "schema_mismatch", f"Unbekannter Read-back-Status: {readback_status!r}")

    kennung = rohdaten.get("provider_identifier")
    if kennung is not None and (not isinstance(kennung, str) or not kennung
                                or len(kennung) > 512):
        raise ExecutionContractError(
            "schema_mismatch", "provider_identifier ist keine brauchbare Kennung")
    rueckgabe = rohdaten.get("readback_contact")
    if rueckgabe is not None and not isinstance(rueckgabe, dict):
        raise ExecutionContractError(
            "schema_mismatch", "readback_contact ist kein Objekt")

    fehlerklasse = rohdaten.get("error_class")
    if fehlerklasse is not None and fehlerklasse not in ERROR_CLASSES:
        raise ExecutionContractError(
            "schema_mismatch", f"Unbekannte Fehlerklasse: {fehlerklasse!r}")

    anzahl = _pflicht(rohdaten, "save_request_count")
    if not isinstance(anzahl, int) or isinstance(anzahl, bool) or anzahl < 0:
        raise ExecutionContractError(
            "schema_mismatch", "save_request_count ist keine Zahl ≥ 0")
    if anzahl > 1:
        # Der Vertrag erlaubt hoechstens einen Speicherauftrag je Claim.
        raise ExecutionContractError(
            "schema_mismatch", "Mehr als ein Speicherauftrag gemeldet")

    gesendet = _pflicht(rohdaten, "send_attempted")
    if not isinstance(gesendet, bool):
        raise ExecutionContractError(
            "schema_mismatch", "send_attempted ist kein Wahrheitswert")
    if anzahl > 0 and not gesendet:
        raise ExecutionContractError(
            "schema_mismatch",
            "Widerspruch: Speicherauftrag gezählt, aber send_attempted=false")
    if outcome == "applied" and not gesendet:
        raise ExecutionContractError(
            "schema_mismatch",
            "Widerspruch: applied ohne Sendeversuch")

    for name in ("operation_id", "mutation_id"):
        wert = _pflicht(rohdaten, name)
        if not isinstance(wert, str) or len(wert) != 36:
            raise ExecutionContractError(
                "schema_mismatch", f"{name} ist keine UUID")

    for name in ("provider_identifier_digest", "readback_digest", "error_digest"):
        wert = rohdaten.get(name)
        if wert is not None:
            _hex64(wert, name)

    return ExecutionReportV1(**rohdaten)


def report_digest(bericht: ExecutionReportV1) -> str:
    """Serverseitiger Digest des Berichts — die Klammer der Settle-Idempotenz.

    Bewusst **ohne** `claim_token`: der Token bindet die Berechtigung, der
    Digest bindet den Inhalt. Zwei Berichte mit gleichem Inhalt sind
    derselbe Bericht, auch wenn das Frontend ihn zweimal schickt.
    """
    return digest_of(bericht.as_dict())
