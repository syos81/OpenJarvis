"""Providerneutrale DTOs der Kalender-Bridge.

**Keine Apple-Typen überqueren diese Grenze** (AV-4). Die Bridge liefert
technische Rohwerte; Normalisierung, Felddigest, Anzeigenamen und die Zuordnung
von Teilnehmern zu Kontakten bleiben im Kern (ADR-0016 Punkt 4) und finden hier
ausdrücklich **nicht** statt.

Drei Eigenschaften sind Vertragsbestandteil und keine Detailfragen:

* `time_zone` darf `None` sein und heisst dann **schwebend**. Ganztägige und
  schwebende Termine haben keine Zone; sie beim Import nach UTC zu
  normalisieren verschöbe sie beim nächsten Ortswechsel.
* `external_uid` (die CalDAV-UID) ist **nicht eindeutig**: bei Einladungen
  liegt derselbe Termin in mehreren Kalendern. Korrelationshinweis, nie
  Primärschlüssel.
* `recurrence_rule` ist **roh**. Materialisierte Instanzen sind Cache und nie
  Wahrheit; hier wird nichts gedeutet und nichts ausgerechnet.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

__all__ = [
    "AuthorizationStatus",
    "CalendarCapabilities",
    "CalendarHandshake",
    "CalendarSource",
    "BridgeCalendar",
    "BridgeAlarm",
    "BridgeAttendee",
    "BridgeEvent",
    "EventWindowResult",
]


class AuthorizationStatus(str, Enum):
    """Geschlossene Statusmenge.

    `WRITE_ONLY` (macOS 14+) ist ausdrücklich **keine** Leseberechtigung und
    wird nirgends als solche gewertet.
    """

    NOT_DETERMINED = "not_determined"
    RESTRICTED = "restricted"
    DENIED = "denied"
    FULL_ACCESS = "full_access"
    WRITE_ONLY = "write_only"
    UNKNOWN = "unknown"

    @classmethod
    def parse(cls, raw: str) -> "AuthorizationStatus":
        try:
            return cls(raw)
        except ValueError:
            return cls.UNKNOWN

    @property
    def can_read(self) -> bool:
        return self is AuthorizationStatus.FULL_ACCESS


@dataclass(frozen=True)
class CalendarCapabilities:
    """Ehrliche Fähigkeitsgrenzen (08 §3 Nr. 2/7).

    Fail-closed: eine nicht gemeldete Fähigkeit gilt als **nicht vorhanden**.
    `change_feed` ist das Feld, an dem sich Adapter am stärksten unterscheiden;
    `notification` heisst: es gibt einen Auslöser, aber kein Delta.
    """

    can_read: bool = False
    can_create_events: bool = False
    can_update_events: bool = False
    can_delete_events: bool = False
    supports_recurrence: bool = False
    supports_attendees: bool = False
    supports_alarms: bool = False
    supports_free_busy: bool = False
    supports_time_zones: bool = False
    window_required: bool = True
    change_feed: str = "none"
    mutations_implemented: bool = False

    @classmethod
    def parse(cls, raw: Any) -> "CalendarCapabilities":
        d = raw if isinstance(raw, dict) else {}
        return cls(
            can_read=bool(d.get("canRead", False)),
            can_create_events=bool(d.get("canCreateEvents", False)),
            can_update_events=bool(d.get("canUpdateEvents", False)),
            can_delete_events=bool(d.get("canDeleteEvents", False)),
            supports_recurrence=bool(d.get("supportsRecurrence", False)),
            supports_attendees=bool(d.get("supportsAttendees", False)),
            supports_alarms=bool(d.get("supportsAlarms", False)),
            supports_free_busy=bool(d.get("supportsFreeBusy", False)),
            supports_time_zones=bool(d.get("supportsTimeZones", False)),
            window_required=bool(d.get("windowRequired", True)),
            change_feed=str(d.get("changeFeed", "none")),
            mutations_implemented=bool(d.get("mutationsImplemented", False)),
        )


@dataclass(frozen=True)
class CalendarHandshake:
    """Die erste, unaufgefordert gesendete Zeile des Sidecars."""

    protocol_version: int
    bundle_identifier: str
    key_set_version: int
    authorization_status: AuthorizationStatus
    operations: tuple[str, ...]
    capabilities: CalendarCapabilities

    @classmethod
    def parse(cls, raw: dict[str, Any]) -> "CalendarHandshake":
        return cls(
            protocol_version=int(raw.get("protocolVersion", -1)),
            bundle_identifier=str(raw.get("bundleIdentifier", "")),
            key_set_version=int(raw.get("keySetVersion", -1)),
            authorization_status=AuthorizationStatus.parse(
                str(raw.get("authorizationStatus", "unknown"))),
            operations=tuple(raw.get("operations", ())),
            capabilities=CalendarCapabilities.parse(raw.get("capabilities")),
        )


def _opt_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text or None


@dataclass(frozen=True)
class CalendarSource:
    """Herkunft eines Kalenders — technische Kennung, Anzeigename, Art.

    Ausdrücklich **keine** Apple-ID, Mailadresse oder Zugangsdaten.
    """

    source_identifier: str
    title: str
    source_type: str

    @classmethod
    def parse(cls, raw: Any) -> "CalendarSource | None":
        if not isinstance(raw, dict):
            return None
        return cls(
            source_identifier=str(raw.get("sourceIdentifier", "")),
            title=str(raw.get("title", "")),
            source_type=str(raw.get("sourceType", "unknown")),
        )


@dataclass(frozen=True)
class BridgeCalendar:
    """Ein Kalender, wie der Provider ihn meldet.

    `is_writable` ist **Provider-Wahrheit, nicht Politik**: Geburtstags- und
    Abonnementkalender melden `False`, und das Modul darf das nie überstimmen.
    """

    provider_calendar_id: str
    display_name: str
    calendar_type: str
    color: str | None
    is_subscribed: bool
    is_immutable: bool
    is_writable: bool
    supports_events: bool
    source: CalendarSource | None

    @classmethod
    def parse(cls, raw: dict[str, Any]) -> "BridgeCalendar":
        return cls(
            provider_calendar_id=str(raw["calendarIdentifier"]),
            display_name=str(raw.get("title", "")),
            calendar_type=str(raw.get("calendarType", "unknown")),
            color=_opt_str(raw.get("color")),
            is_subscribed=bool(raw.get("isSubscribed", False)),
            is_immutable=bool(raw.get("isImmutable", False)),
            is_writable=bool(raw.get("allowsContentModifications", False)),
            supports_events=bool(raw.get("allowedEntityTypes", True)),
            source=CalendarSource.parse(raw.get("source")),
        )


@dataclass(frozen=True)
class BridgeAlarm:
    """Ein Wecker — absoluter Zeitpunkt **oder** relativer Versatz, nie beides."""

    absolute_date: str | None
    relative_offset_seconds: float | None

    @classmethod
    def parse(cls, raw: dict[str, Any]) -> "BridgeAlarm":
        offset = raw.get("relativeOffset")
        return cls(
            absolute_date=_opt_str(raw.get("absoluteDate")),
            relative_offset_seconds=(
                float(offset) if isinstance(offset, (int, float)) else None),
        )


@dataclass(frozen=True)
class BridgeAttendee:
    """Ein Teilnehmer in Rohform.

    `raw_address` bleibt unverändert, wie der Provider sie liefert — keine
    Kleinschreibung, keine Normalisierung. Die Zuordnung zu einem Kontakt ist
    ein späterer, eigener Schritt und läuft **nie** über Namensähnlichkeit.
    """

    raw_address: str | None
    display_name: str | None
    role: str
    participant_status: str
    participant_type: str
    is_current_user: bool
    is_organizer: bool

    @classmethod
    def parse(cls, raw: dict[str, Any]) -> "BridgeAttendee":
        return cls(
            raw_address=_opt_str(raw.get("rawAddress")),
            display_name=_opt_str(raw.get("displayName")),
            role=str(raw.get("role", "unknown")),
            participant_status=str(raw.get("participantStatus", "unknown")),
            participant_type=str(raw.get("participantType", "unknown")),
            is_current_user=bool(raw.get("isCurrentUser", False)),
            is_organizer=bool(raw.get("isOrganizer", False)),
        )


@dataclass(frozen=True)
class BridgeEvent:
    """Ein Termin, wie der Provider ihn meldet."""

    provider_event_id: str
    calendar_item_id: str | None
    external_uid: str | None
    provider_calendar_id: str
    title: str | None
    notes: str | None
    location: str | None
    url: str | None
    starts_at_utc: str
    ends_at_utc: str
    time_zone: str | None
    is_all_day: bool
    status: str
    availability: str
    has_recurrence_rules: bool
    recurrence_rule_count: int
    recurrence_rule: dict[str, Any] | None
    is_detached: bool
    occurrence_start_utc: str | None
    alarms: tuple[BridgeAlarm, ...]
    attendees: tuple[BridgeAttendee, ...]
    created_at_utc: str | None
    last_modified_at_utc: str | None

    @classmethod
    def parse(cls, raw: dict[str, Any]) -> "BridgeEvent":
        rule = raw.get("recurrenceRule")
        return cls(
            provider_event_id=str(raw.get("providerIdentifier") or ""),
            calendar_item_id=_opt_str(raw.get("calendarItemIdentifier")),
            external_uid=_opt_str(raw.get("externalUid")),
            provider_calendar_id=str(raw.get("calendarIdentifier") or ""),
            title=_opt_str(raw.get("title")),
            notes=_opt_str(raw.get("notes")),
            location=_opt_str(raw.get("location")),
            url=_opt_str(raw.get("url")),
            starts_at_utc=str(raw.get("startsAtUtc") or ""),
            ends_at_utc=str(raw.get("endsAtUtc") or ""),
            time_zone=_opt_str(raw.get("timeZone")),
            is_all_day=bool(raw.get("isAllDay", False)),
            status=str(raw.get("status", "none")),
            availability=str(raw.get("availability", "unknown")),
            has_recurrence_rules=bool(raw.get("hasRecurrenceRules", False)),
            recurrence_rule_count=int(raw.get("recurrenceRuleCount", 0) or 0),
            recurrence_rule=rule if isinstance(rule, dict) else None,
            is_detached=bool(raw.get("isDetached", False)),
            occurrence_start_utc=_opt_str(raw.get("occurrenceStartUtc")),
            alarms=tuple(BridgeAlarm.parse(a)
                         for a in raw.get("alarms", []) if isinstance(a, dict)),
            attendees=tuple(BridgeAttendee.parse(a)
                            for a in raw.get("attendees", []) if isinstance(a, dict)),
            created_at_utc=_opt_str(raw.get("createdAtUtc")),
            last_modified_at_utc=_opt_str(raw.get("lastModifiedAtUtc")),
        )


@dataclass(frozen=True)
class EventWindowResult:
    """Das Ergebnis **einer** Fensterlesung.

    `complete` ist die Bedingung, unter der überhaupt eine Löschung abgeleitet
    werden darf. Fehlt sie, ist „nicht gesehen" schlicht *unbekannt* — ein
    verschobener Termin ist kein gelöschter. Das Fenster wird mitgeführt, weil
    ein Ergebnis ohne Fensterangabe diese Unterscheidung nicht zulässt.
    """

    events: tuple[BridgeEvent, ...]
    complete: bool
    window_start_utc: str
    window_end_utc: str
    provider_calendar_ids: tuple[str, ...] | None
