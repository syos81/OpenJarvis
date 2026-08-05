"""Kanonische Kalender-Domäne — Modelle, Digest, Fensterregeln.

Providerneutral und plattformunabhängig (ADR-0002): nichts in dieser Datei
weiss von EventKit, und nichts von SQLite. Hier steht die Fachlogik, die der
Sidecar ausdrücklich **nicht** enthalten darf.

Der Felddigest lebt hier und nicht in der Bridge. Das ist keine Formsache:
`last_modified_at` kommt vom Server und ist bei CalDAV nicht verlässlich —
der Digest ist lokal, deterministisch und deshalb die einzige ehrliche
Änderungserkennung.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

__all__ = [
    "DEFAULT_WINDOW_PAST_DAYS",
    "DEFAULT_WINDOW_FUTURE_DAYS",
    "SyncWindow",
    "CanonicalCalendar",
    "CanonicalAttendee",
    "CanonicalEvent",
    "event_field_digest",
    "window_covers",
]

#: Startcache, **keine** dauerhafte Produktgrenze (Baseline B-8). Die Navigation
#: darf das Fenster kontrolliert erweitern; jeder Lauf nennt sein Fenster.
DEFAULT_WINDOW_PAST_DAYS = 90
DEFAULT_WINDOW_FUTURE_DAYS = 365


def _iso_utc(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass(frozen=True)
class SyncWindow:
    """Ein Zeitfenster in UTC. Anfang inklusiv, Ende exklusiv."""

    start_utc: str
    end_utc: str

    @classmethod
    def around(cls, now: datetime, *, past_days: int = DEFAULT_WINDOW_PAST_DAYS,
               future_days: int = DEFAULT_WINDOW_FUTURE_DAYS) -> "SyncWindow":
        return cls(start_utc=_iso_utc(now - timedelta(days=past_days)),
                   end_utc=_iso_utc(now + timedelta(days=future_days)))

    def __post_init__(self) -> None:
        if not self.start_utc or not self.end_utc:
            raise ValueError("Fenstergrenzen duerfen nicht leer sein")
        if self.start_utc >= self.end_utc:
            raise ValueError("Fensterbeginn muss vor dem Fensterende liegen")

    def contains(self, instant_utc: str) -> bool:
        return self.start_utc <= instant_utc < self.end_utc

    def equals(self, other: "SyncWindow | None") -> bool:
        return (other is not None
                and self.start_utc == other.start_utc
                and self.end_utc == other.end_utc)


def window_covers(observed: SyncWindow | None, candidate: SyncWindow) -> bool:
    """Ob ein zuvor beobachtetes Fenster das aktuelle vollständig abdeckt.

    Wird das Fenster **vergrössert**, ist der erste Lauf danach ein Import ohne
    Löschableitung: über den neu hinzugekommenen Rand ist schlicht nichts
    bekannt. Wird es **verkleinert**, entstehen ebenfalls keine Tombstones —
    was herausfällt, ist nicht gelöscht, sondern nur nicht mehr im Blick.
    """
    if observed is None:
        return False
    return (observed.start_utc <= candidate.start_utc
            and observed.end_utc >= candidate.end_utc)


@dataclass(frozen=True)
class CanonicalCalendar:
    """Ein Kalender in kanonischer Form."""

    id: str
    workspace_id: str
    provider_account_id: str
    provider_calendar_id: str
    display_name: str
    calendar_type: str
    source_identifier: str | None = None
    source_title: str | None = None
    source_type: str | None = None
    color: str | None = None
    #: Provider-Wahrheit, nicht Politik. Wird nie überstimmt.
    is_writable: bool = False
    is_subscribed: bool = False
    is_immutable: bool = False
    supports_events: bool = True
    sync_enabled: bool = True


@dataclass(frozen=True)
class CanonicalAttendee:
    raw_address: str | None
    display_name: str | None
    role: str = "unknown"
    participant_status: str = "unknown"
    participant_type: str = "unknown"
    is_organizer: bool = False
    is_current_user: bool = False
    #: Bleibt `None`, bis eine ausdrückliche Zuordnung stattfindet. Niemals
    #: über Namensähnlichkeit geraten.
    contact_id: str | None = None


@dataclass(frozen=True)
class CanonicalEvent:
    """Ein Termin in kanonischer Form."""

    id: str
    calendar_id: str
    provider_event_id: str
    provider_calendar_id: str
    starts_at_utc: str
    ends_at_utc: str
    title: str | None = None
    notes: str | None = None
    location: str | None = None
    url: str | None = None
    #: `None` heisst **schwebend** — nicht „unbekannt" und nicht „UTC".
    time_zone: str | None = None
    is_all_day: bool = False
    status: str = "none"
    availability: str = "unknown"
    recurrence_rule_raw: dict[str, Any] | None = None
    recurrence_rule_count: int = 0
    series_id: str | None = None
    is_detached: bool = False
    occurrence_start_utc: str | None = None
    alarms_raw: tuple[dict[str, Any], ...] = ()
    attendees: tuple[CanonicalAttendee, ...] = ()
    calendar_item_id: str | None = None
    external_uid: str | None = None
    provider_created_at: str | None = None
    provider_modified_at: str | None = None

    @property
    def has_alarms(self) -> bool:
        return bool(self.alarms_raw)

    @property
    def has_attendees(self) -> bool:
        return bool(self.attendees)


#: Die Felder, deren Änderung eine Änderung des Termins IST. Bewusst
#: geschlossen und bewusst ohne `last_seen_at` oder Providerzeitstempel: sonst
#: gälte jeder Lauf als Änderung.
_DIGEST_FIELDS = (
    "title", "notes", "location", "url", "starts_at_utc", "ends_at_utc",
    "time_zone", "is_all_day", "status", "availability",
    "recurrence_rule_raw", "recurrence_rule_count", "is_detached",
    "occurrence_start_utc",
)


def event_field_digest(event: CanonicalEvent) -> str:
    """Deterministischer Digest der fachlich bedeutsamen Felder.

    Zwei gleiche Termine ergeben denselben Digest, unabhängig von Reihenfolge
    und Laufzeitpunkt: sortierte Schlüssel, kompakte Trenner, feste Feldliste.
    Teilnehmer und Wecker gehen mit ein — eine geänderte Teilnehmerliste ist
    eine geänderte Einladung, kein Rauschen.
    """
    payload: dict[str, Any] = {
        name: getattr(event, name) for name in _DIGEST_FIELDS
    }
    payload["alarms"] = [
        {k: a.get(k) for k in sorted(a)} for a in event.alarms_raw
    ]
    payload["attendees"] = sorted(
        (
            {
                "raw_address": a.raw_address,
                "display_name": a.display_name,
                "role": a.role,
                "participant_status": a.participant_status,
                "is_organizer": a.is_organizer,
            }
            for a in event.attendees
        ),
        key=lambda a: (a["raw_address"] or "", a["display_name"] or ""),
    )
    text = json.dumps(payload, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
