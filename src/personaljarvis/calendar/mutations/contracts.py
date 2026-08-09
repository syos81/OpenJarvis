"""Transportverträge des Kalender-Mutationskanals (B3 P1).

Dieselbe Bauart wie bei den Kontakten (`execution_contracts.py`), aber ein
**eigener** Vertrag: Der Kalender hat einen geschlossenen Feldsatz von sieben
Feldern, kennt keinen Container und bindet sein Ziel über
`provider_calendar_id` plus — ab `update`/`delete` — den `event_identifier`.

Zwei Objekte, zwei Richtungen:

* `ExecutionOrderV1` — was das Backend beim Claim ausgibt. Der
  `payload_digest` deckt exakt `canonical_payload`; Rust rechnet ihn nach,
  und genau diese Nachrechnung bindet Freigabe und Ausführung aneinander.
* `ExecutionReportV1` — was aus dem App-Prozess zurückkommt. Geschlossene
  Ausgänge, geschlossene Fehlerklassen, fail-closed geparst.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from typing import Any
from zoneinfo import ZoneInfo

# Die Fehlerklassen sind wortgleich mit dem CHECK der Outbox-Spalte
# `error_class` (Migration 0008). Der Import aus der Migration ist Absicht:
# eine veröffentlichte Migration ist unveränderlich, und das Settle schreibt
# die Klasse in genau diese Spalte — eine eigene Liste könnte driften.
from personaljarvis.base.db.migrations.versions.m0008_app_process_channel import (
    EXECUTION_ERROR_CLASSES as ERROR_CLASSES,
)
from personaljarvis.base.digest import canonical_json, digest_of

__all__ = [
    "EXECUTION_SCHEMA_VERSION",
    "COMMANDS",
    "REPORT_OUTCOMES",
    "READBACK_STATUSES",
    "ERROR_CLASSES",
    "FIELD_NAMES",
    "MAX_ORDER_BYTES",
    "MAX_REPORT_BYTES",
    "CalendarExecutionContractError",
    "InvalidMutationFields",
    "validate_fields",
    "fingerprint_of",
    "canonical_create_payload",
    "ExecutionOrderV1",
    "ExecutionReportV1",
    "parse_execution_report",
    "report_digest",
]

EXECUTION_SCHEMA_VERSION = 1

COMMANDS: tuple[str, ...] = ("create", "update", "delete")

#: Geschlossene Ausgänge des Berichts. `unknown` heisst „möglicherweise
#: gesendet" — nie „vermutlich gut gegangen".
REPORT_OUTCOMES: tuple[str, ...] = ("applied", "not_sent", "unknown")

READBACK_STATUSES: tuple[str, ...] = (
    "confirmed", "absent_confirmed", "unavailable", "not_checked",
)

#: Der geschlossene Feldsatz. Genau diese sieben — kein achtes Feld reist
#: durch diesen Kanal, auch nicht „zur Sicherheit". `time_zone` ist seit der
#: B3-P1-Zeitzonenkorrektur Pflichtschlüssel: fehlend ist ein Schemafehler,
#: `null` ist die ausdrücklich angeforderte schwebende Semantik.
FIELD_NAMES: tuple[str, ...] = (
    "title", "starts_at_utc", "ends_at_utc", "is_all_day", "location", "notes",
    "time_zone",
)

#: Größenlimits, wortgleich mit dem Kontakte-Kanal. Darüber ist fail-closed.
MAX_ORDER_BYTES = 64 * 1024
MAX_REPORT_BYTES = 256 * 1024

_HEX64 = 64

#: ISO-8601 UTC mit Sekundenpräzision und ausdrücklichem `Z`. Kein Offset,
#: keine Millisekunden: der Vergleich zweier Zeitpunkte bleibt lexikografisch.
_UTC_SECONDS = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


class CalendarExecutionContractError(ValueError):
    """Vertragsverletzung im Transport — trägt eine geschlossene Klasse."""

    def __init__(self, error_class: str, message: str) -> None:
        if error_class not in ERROR_CLASSES:
            raise ValueError(f"Unbekannte Fehlerklasse: {error_class}")
        super().__init__(message)
        self.error_class = error_class


class InvalidMutationFields(ValueError):
    """Der Feldsatz verletzt den geschlossenen Vertrag.

    Die Meldung nennt **nur** Feldnamen, nie Werte: ein Titel oder Ort darf
    in keiner Fehlermeldung erscheinen.
    """

    reason_code = "invalid_fields"


def _pruefe_zeitpunkt(wert: object, feld: str) -> str:
    if not isinstance(wert, str) or not _UTC_SECONDS.match(wert):
        raise InvalidMutationFields(
            f"{feld} ist kein ISO-8601-UTC-Zeitpunkt in Sekundenpräzision")
    from datetime import datetime
    try:
        datetime.strptime(wert, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as exc:
        raise InvalidMutationFields(
            f"{feld} ist kein gültiger Zeitpunkt") from exc
    return wert


def _pruefe_zeitzone(fields: dict[str, Any]) -> str | None:
    """Der Zeitzonenanker — Pflichtschlüssel, nie ein Default.

    „Fehlt" ist ein Schemafehler wie jeder andere; schwebend (`null`) ist
    ausschliesslich die ausdrücklich mitgesendete Entscheidung. Ein Wert muss
    ein gültiger IANA-Name sein — geprüft gegen die Zonendatenbank, nicht
    gegen ein Muster.
    """
    if "time_zone" not in fields:
        raise InvalidMutationFields(
            "time_zone fehlt (null wäre die bewusste schwebende Semantik)")
    wert = fields["time_zone"]
    if wert is None:
        return None
    if not isinstance(wert, str) or not wert:
        raise InvalidMutationFields("time_zone ist weder IANA-Name noch null")
    try:
        ZoneInfo(wert)
    except (KeyError, ValueError, OSError) as exc:
        raise InvalidMutationFields(
            "time_zone ist kein gültiger IANA-Name") from exc
    return wert


def validate_fields(fields: object) -> dict[str, Any]:
    """Prüft den geschlossenen Feldsatz und normalisiert ihn.

    Fehlende optionale Felder werden ausdrücklich `None`; unbekannte Felder
    fallen fail-closed. Das Ergebnis enthält **immer** alle sieben Schlüssel —
    der Fingerprint deckt sie samt `null`-Werten.
    """
    if not isinstance(fields, dict):
        raise InvalidMutationFields("fields ist kein Objekt")
    unbekannt = sorted(set(fields) - set(FIELD_NAMES))
    if unbekannt:
        raise InvalidMutationFields(
            f"Unbekannte Felder: {', '.join(unbekannt)}")

    starts = _pruefe_zeitpunkt(fields.get("starts_at_utc"), "starts_at_utc")
    ends = _pruefe_zeitpunkt(fields.get("ends_at_utc"), "ends_at_utc")
    if ends <= starts:
        raise InvalidMutationFields(
            "ends_at_utc muss nach starts_at_utc liegen")

    ganztags = fields.get("is_all_day", False)
    if not isinstance(ganztags, bool):
        raise InvalidMutationFields("is_all_day ist kein Wahrheitswert")

    ergebnis: dict[str, Any] = {
        "starts_at_utc": starts, "ends_at_utc": ends, "is_all_day": ganztags,
        "time_zone": _pruefe_zeitzone(fields),
    }
    for name in ("title", "location", "notes"):
        wert = fields.get(name)
        if wert is not None and not isinstance(wert, str):
            raise InvalidMutationFields(f"{name} ist weder Text noch null")
        ergebnis[name] = wert
    return ergebnis


def fingerprint_of(fields: dict[str, Any], provider_calendar_id: str) -> str:
    """Deterministischer Fingerprint eines Terminzustands.

    `None`-Werte bleiben ausdrücklich als `null` enthalten: ein Termin ohne
    Ort ist ein anderer Zustand als einer mit leerem Ort — und der
    Fingerprint muss das unterscheiden können.
    """
    return digest_of({
        "provider_calendar_id": provider_calendar_id,
        "title": fields.get("title"),
        "starts_at_utc": fields.get("starts_at_utc"),
        "ends_at_utc": fields.get("ends_at_utc"),
        "is_all_day": fields.get("is_all_day"),
        "location": fields.get("location"),
        "notes": fields.get("notes"),
        # Der Zeitzonenanker gehört zum Zustand: dieselbe Uhrzeit in einer
        # anderen Zone ist ein ANDERER Termin — der Fingerprint bindet das.
        "time_zone": fields.get("time_zone"),
    })


def canonical_create_payload(fields: dict[str, Any],
                             provider_calendar_id: str) -> dict[str, Any]:
    """Die kanonische Nutzlast eines `create` — genau das Objekt, das der
    `payload_digest` deckt und das Rust nachrechnet."""
    return {
        "command": "create",
        "fields": {name: fields.get(name) for name in FIELD_NAMES},
        "provider_target": {
            "provider_calendar_id": provider_calendar_id,
            "event_identifier": None,
        },
        "expected_fingerprint": None,
    }


@dataclass(frozen=True, slots=True)
class ExecutionOrderV1:
    """Der kurzlebige, gebundene Ausführungsauftrag des Kalenderkanals.

    `claim_token` ist der einzige Rohwert: er existiert genau einmal,
    wandert durch das Frontend in den App-Prozess und kommt im Settle
    zurück. Persistiert wird nur sein Digest.
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
    provider_target: dict[str, str | None] = field(default_factory=dict)
    #: Für `create` immer `None`; `update`/`delete` tragen hier den beim
    #: Vorbereiten festgehaltenen Vorzustands-Fingerprint (P2/P3).
    expected_fingerprint: str | None = None
    schema_version: int = EXECUTION_SCHEMA_VERSION

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        text = canonical_json(self.as_dict())
        if len(text.encode("utf-8")) > MAX_ORDER_BYTES:
            raise CalendarExecutionContractError(
                "schema_mismatch", "Ausführungsauftrag überschreitet das Limit")
        return text

    def payload_digest_matches(self) -> bool:
        """Der Auftrag trägt genau den Digest seines kanonischen Payloads."""
        return digest_of(self.canonical_payload) == self.payload_digest


@dataclass(frozen=True, slots=True)
class ExecutionReportV1:
    """Das typisierte Ergebnis aus dem App-Prozess."""

    operation_id: str
    mutation_id: str
    operation_type: str
    outcome: str
    send_attempted: bool
    save_request_count: int
    readback_status: str
    schema_version: int = EXECUTION_SCHEMA_VERSION
    #: Der gelesene Zustand: die sieben Felder plus `provider_calendar_id`.
    #: Aus ihm führt der Kern den lokalen Spiegel nach — erfunden wird nichts.
    readback_event: dict[str, Any] | None = None
    #: Die rohe Providerkennung (EventKit `eventIdentifier`). Sie reist
    #: ausschliesslich im Settle-Rumpf; in Audit und Log steht ihr Digest.
    provider_identifier: str | None = None
    fingerprint_checked: bool = False
    fingerprint_matched: bool | None = None
    error_class: str | None = None
    error_digest: str | None = None
    provider_completed_at: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def beweist_nichts_gesendet(self) -> bool:
        """Nur `not_sent` **ohne** Sendeversuch beweist die Unversehrtheit."""
        return self.outcome == "not_sent" and not self.send_attempted


def _pflicht(rohdaten: dict[str, Any], name: str) -> Any:
    if name not in rohdaten:
        raise CalendarExecutionContractError(
            "schema_mismatch", f"Pflichtfeld fehlt: {name}")
    return rohdaten[name]


def _hex64(wert: object, feld: str) -> str:
    if not isinstance(wert, str) or len(wert) != _HEX64 \
            or any(z not in "0123456789abcdef" for z in wert):
        raise CalendarExecutionContractError(
            "schema_mismatch", f"{feld} ist kein 64-stelliger Hexdigest")
    return wert


def parse_execution_report(rohdaten: object) -> ExecutionReportV1:
    """Liest einen Bericht fail-closed.

    Unbekannte Felder, fremde Versionen und Widersprüche werden abgewiesen,
    nie ignoriert — was der Kern nicht kennt, kann er nicht bewerten.
    """
    if isinstance(rohdaten, (str, bytes)):
        roh = rohdaten if isinstance(rohdaten, bytes) else rohdaten.encode("utf-8")
        if len(roh) > MAX_REPORT_BYTES:
            raise CalendarExecutionContractError(
                "schema_mismatch", "Bericht überschreitet das Limit")
        try:
            rohdaten = json.loads(roh)
        except ValueError as exc:
            raise CalendarExecutionContractError(
                "schema_mismatch", "Bericht ist kein gültiges JSON") from exc

    if not isinstance(rohdaten, dict):
        raise CalendarExecutionContractError(
            "schema_mismatch", "Bericht ist kein Objekt")

    erlaubt = set(ExecutionReportV1.__dataclass_fields__)
    unbekannt = sorted(set(rohdaten) - erlaubt)
    if unbekannt:
        raise CalendarExecutionContractError(
            "schema_mismatch", f"Unbekannte Felder: {', '.join(unbekannt)}")

    version = rohdaten.get("schema_version", EXECUTION_SCHEMA_VERSION)
    if version != EXECUTION_SCHEMA_VERSION:
        raise CalendarExecutionContractError(
            "schema_mismatch", f"Fremde Schemaversion: {version!r}")

    outcome = _pflicht(rohdaten, "outcome")
    if outcome not in REPORT_OUTCOMES:
        raise CalendarExecutionContractError(
            "schema_mismatch", f"Unbekannter Ausgang: {outcome!r}")

    operation_type = _pflicht(rohdaten, "operation_type")
    if operation_type not in COMMANDS:
        raise CalendarExecutionContractError(
            "schema_mismatch", f"Unbekannte Operation: {operation_type!r}")

    readback_status = _pflicht(rohdaten, "readback_status")
    if readback_status not in READBACK_STATUSES:
        raise CalendarExecutionContractError(
            "schema_mismatch",
            f"Unbekannter Read-back-Status: {readback_status!r}")

    kennung = rohdaten.get("provider_identifier")
    if kennung is not None and (not isinstance(kennung, str) or not kennung
                                or len(kennung) > 512):
        raise CalendarExecutionContractError(
            "schema_mismatch", "provider_identifier ist keine brauchbare Kennung")

    rueckgabe = rohdaten.get("readback_event")
    if rueckgabe is not None and not isinstance(rueckgabe, dict):
        raise CalendarExecutionContractError(
            "schema_mismatch", "readback_event ist kein Objekt")

    fehlerklasse = rohdaten.get("error_class")
    if fehlerklasse is not None and fehlerklasse not in ERROR_CLASSES:
        raise CalendarExecutionContractError(
            "schema_mismatch", f"Unbekannte Fehlerklasse: {fehlerklasse!r}")

    anzahl = _pflicht(rohdaten, "save_request_count")
    if not isinstance(anzahl, int) or isinstance(anzahl, bool) or anzahl < 0:
        raise CalendarExecutionContractError(
            "schema_mismatch", "save_request_count ist keine Zahl ≥ 0")
    if anzahl > 1:
        # Der Vertrag erlaubt hoechstens einen Speicherauftrag je Claim.
        raise CalendarExecutionContractError(
            "schema_mismatch", "Mehr als ein Speicherauftrag gemeldet")

    gesendet = _pflicht(rohdaten, "send_attempted")
    if not isinstance(gesendet, bool):
        raise CalendarExecutionContractError(
            "schema_mismatch", "send_attempted ist kein Wahrheitswert")
    if anzahl > 0 and not gesendet:
        raise CalendarExecutionContractError(
            "schema_mismatch",
            "Widerspruch: Speicherauftrag gezählt, aber send_attempted=false")
    if outcome == "applied" and not gesendet:
        raise CalendarExecutionContractError(
            "schema_mismatch", "Widerspruch: applied ohne Sendeversuch")

    geprueft = _pflicht(rohdaten, "fingerprint_checked")
    if not isinstance(geprueft, bool):
        raise CalendarExecutionContractError(
            "schema_mismatch", "fingerprint_checked ist kein Wahrheitswert")
    getroffen = rohdaten.get("fingerprint_matched")
    if getroffen is not None and not isinstance(getroffen, bool):
        raise CalendarExecutionContractError(
            "schema_mismatch", "fingerprint_matched ist weder bool noch null")
    if not geprueft and getroffen is not None:
        raise CalendarExecutionContractError(
            "schema_mismatch",
            "Widerspruch: fingerprint_matched ohne fingerprint_checked")

    for name in ("operation_id", "mutation_id"):
        wert = _pflicht(rohdaten, name)
        if not isinstance(wert, str) or len(wert) != 36:
            raise CalendarExecutionContractError(
                "schema_mismatch", f"{name} ist keine UUID")

    if rohdaten.get("error_digest") is not None:
        _hex64(rohdaten["error_digest"], "error_digest")

    return ExecutionReportV1(**rohdaten)


def report_digest(bericht: ExecutionReportV1) -> str:
    """Serverseitiger Digest des Berichts — die Klammer der Settle-Idempotenz.

    Bewusst **ohne** `claim_token`: der Token bindet die Berechtigung, der
    Digest bindet den Inhalt.
    """
    return digest_of(bericht.as_dict())
