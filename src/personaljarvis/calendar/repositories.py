"""SQLite-Repositories des Kalendermoduls (07 §2/§3).

Dieselben Regeln wie im Kontaktmodul:

* Jedes Repository bekommt die **UnitOfWork** injiziert und benutzt deren
  Verbindung. Es öffnet nie eine eigene.
* Es gibt **keinen** Commit in dieser Datei. Der Abschluss gehört dem
  Orchestrator, der die UoW geöffnet hat.
* Constraints werden der Datenbank überlassen und nicht in Python nachgebaut —
  Fremdschlüssel, Unique- und Check-Bedingungen stehen in Migration 0009.
* Reihenfolgen kommen aus `ORDER BY`, nie aus der Einfügereihenfolge.
"""

from __future__ import annotations

import json
import uuid
from typing import Any, Iterable

from personaljarvis.base.db.unit_of_work import UnitOfWork
from personaljarvis.calendar.domain import (
    CanonicalAttendee,
    CanonicalCalendar,
    CanonicalEvent,
    SyncWindow,
    event_field_digest,
)

__all__ = ["CalendarRepository", "EventRepository", "SyncWindowRepository"]


def _new_id() -> str:
    return str(uuid.uuid4())


def _json_or_none(value: Any) -> str | None:
    if value is None:
        return None
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False)


def _loads(value: Any) -> Any:
    if not value:
        return None
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return None


class CalendarRepository:
    """Kalender — Beobachtungen des Providers."""

    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    def upsert_seen(self, calendar: CanonicalCalendar, seen_at: str) -> tuple[str, str]:
        """Legt an oder aktualisiert. Liefert `(id, outcome)`.

        `outcome` ist `created`, `updated` oder `unchanged`. Ein Wiedersehen
        hebt zusätzlich eine frühere Löschmarkierung auf — der Kalender ist
        zurück, nicht neu.
        """
        con = self._uow.connection
        row = con.execute(
            "SELECT id, display_name, calendar_type, source_identifier, "
            "source_title, source_type, color, is_writable, is_subscribed, "
            "is_immutable, supports_events, is_tombstone FROM calendars "
            "WHERE provider_account_id = ? AND provider_calendar_id = ?",
            (calendar.provider_account_id, calendar.provider_calendar_id),
        ).fetchone()

        values = (
            calendar.display_name, calendar.calendar_type,
            calendar.source_identifier, calendar.source_title,
            calendar.source_type, calendar.color,
            1 if calendar.is_writable else 0,
            1 if calendar.is_subscribed else 0,
            1 if calendar.is_immutable else 0,
            1 if calendar.supports_events else 0,
        )

        if row is None:
            new_id = calendar.id or _new_id()
            con.execute(
                "INSERT INTO calendars (id, workspace_id, provider_account_id, "
                "provider_calendar_id, display_name, calendar_type, "
                "source_identifier, source_title, source_type, color, "
                "is_writable, is_subscribed, is_immutable, supports_events, "
                "sync_enabled, first_seen_at, last_seen_at, created_at, updated_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (new_id, calendar.workspace_id, calendar.provider_account_id,
                 calendar.provider_calendar_id, *values,
                 1 if calendar.sync_enabled else 0,
                 seen_at, seen_at, seen_at, seen_at),
            )
            return new_id, "created"

        existing_id = row[0]
        unchanged = (
            tuple(row[1:11]) == values and row[11] == 0
        )
        con.execute(
            "UPDATE calendars SET display_name = ?, calendar_type = ?, "
            "source_identifier = ?, source_title = ?, source_type = ?, color = ?, "
            "is_writable = ?, is_subscribed = ?, is_immutable = ?, "
            "supports_events = ?, is_tombstone = 0, deleted_at = NULL, "
            "last_seen_at = ?, updated_at = ? WHERE id = ?",
            (*values, seen_at, seen_at, existing_id),
        )
        return existing_id, "unchanged" if unchanged else "updated"

    def list_active(self, workspace_id: str) -> tuple[dict[str, Any], ...]:
        con = self._uow.connection
        rows = con.execute(
            "SELECT id, provider_account_id, provider_calendar_id, display_name, "
            "calendar_type, source_identifier, source_title, source_type, color, "
            "is_writable, is_subscribed, is_immutable, supports_events, sync_enabled "
            "FROM calendars WHERE workspace_id = ? AND is_tombstone = 0 "
            "ORDER BY display_name, provider_calendar_id",
            (workspace_id,),
        ).fetchall()
        return tuple(
            {
                "id": r[0], "provider_account_id": r[1],
                "provider_calendar_id": r[2], "display_name": r[3],
                "calendar_type": r[4], "source_identifier": r[5],
                "source_title": r[6], "source_type": r[7], "color": r[8],
                "is_writable": bool(r[9]), "is_subscribed": bool(r[10]),
                "is_immutable": bool(r[11]), "supports_events": bool(r[12]),
                "sync_enabled": bool(r[13]),
            }
            for r in rows
        )

    def tombstone_missing(self, provider_account_id: str,
                          seen_provider_ids: Iterable[str], at: str) -> int:
        """Markiert nicht mehr gemeldete Kalender als gelöscht.

        Kein Hard-Delete: Termine und spätere Zuordnungen bleiben
        nachvollziehbar. Der Aufrufer ruft dies **nur** nach einer
        vollständigen Kalenderlesung auf — nach einem Fehlschlag bliebe der
        Bestand unverändert.
        """
        seen = tuple(seen_provider_ids)
        con = self._uow.connection
        if seen:
            placeholders = ",".join("?" for _ in seen)
            cur = con.execute(
                "UPDATE calendars SET is_tombstone = 1, deleted_at = ?, updated_at = ? "
                "WHERE provider_account_id = ? AND is_tombstone = 0 "
                f"AND provider_calendar_id NOT IN ({placeholders})",
                (at, at, provider_account_id, *seen),
            )
        else:
            cur = con.execute(
                "UPDATE calendars SET is_tombstone = 1, deleted_at = ?, updated_at = ? "
                "WHERE provider_account_id = ? AND is_tombstone = 0",
                (at, at, provider_account_id),
            )
        return cur.rowcount or 0


class EventRepository:
    """Termine — kanonischer Bestand samt Providerbindung und Teilnehmern."""

    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    def upsert_seen(self, event: CanonicalEvent, provider_account_id: str,
                    seen_at: str) -> tuple[str, str]:
        """Legt an oder aktualisiert. Liefert `(id, outcome)`.

        `outcome` ist `created`, `updated` oder `unchanged` — entschieden
        ausschliesslich über den **Felddigest**, nie über einen
        Providerzeitstempel.
        """
        con = self._uow.connection
        digest = event_field_digest(event)

        row = con.execute(
            "SELECT e.id, e.field_digest, e.is_tombstone FROM event_external_ids x "
            "JOIN events e ON e.id = x.event_id "
            "WHERE x.provider_account_id = ? AND x.provider_calendar_id = ? "
            "AND x.provider_event_id = ?",
            (provider_account_id, event.provider_calendar_id,
             event.provider_event_id),
        ).fetchone()

        columns = (
            event.title, event.notes, event.location, event.url,
            event.starts_at_utc, event.ends_at_utc, event.time_zone,
            1 if event.is_all_day else 0, event.status, event.availability,
            _json_or_none(event.recurrence_rule_raw), event.recurrence_rule_count,
            event.series_id, 1 if event.is_detached else 0,
            event.occurrence_start_utc,
            1 if event.has_alarms else 0, _json_or_none(list(event.alarms_raw)),
            1 if event.has_attendees else 0,
            event.provider_created_at, event.provider_modified_at, digest,
        )

        if row is None:
            new_id = event.id or _new_id()
            con.execute(
                "INSERT INTO events (id, calendar_id, title, notes, location, url, "
                "starts_at_utc, ends_at_utc, time_zone, is_all_day, status, "
                "availability, recurrence_rule_raw, recurrence_rule_count, "
                "series_id, is_detached, occurrence_start_utc, has_alarms, "
                "alarms_raw, has_attendees, provider_created_at, "
                "provider_modified_at, field_digest, first_seen_at, last_seen_at, "
                "created_at, updated_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (new_id, event.calendar_id, *columns, seen_at, seen_at,
                 seen_at, seen_at),
            )
            con.execute(
                "INSERT INTO event_external_ids (event_id, provider_account_id, "
                "provider_calendar_id, provider_event_id, calendar_item_id, "
                "external_uid, first_seen_at, last_seen_at) VALUES (?,?,?,?,?,?,?,?)",
                (new_id, provider_account_id, event.provider_calendar_id,
                 event.provider_event_id, event.calendar_item_id,
                 event.external_uid, seen_at, seen_at),
            )
            self._replace_attendees(new_id, event.attendees, seen_at)
            # Der Tombstone eines wiedergesehenen Termins ist gegenstandslos.
            con.execute(
                "DELETE FROM event_tombstones WHERE provider_account_id = ? "
                "AND provider_calendar_id = ? AND provider_event_id = ?",
                (provider_account_id, event.provider_calendar_id,
                 event.provider_event_id),
            )
            return new_id, "created"

        event_id, previous_digest, was_tombstone = row
        unchanged = previous_digest == digest and not was_tombstone
        con.execute(
            "UPDATE events SET calendar_id = ?, title = ?, notes = ?, location = ?, "
            "url = ?, starts_at_utc = ?, ends_at_utc = ?, time_zone = ?, "
            "is_all_day = ?, status = ?, availability = ?, recurrence_rule_raw = ?, "
            "recurrence_rule_count = ?, series_id = ?, is_detached = ?, "
            "occurrence_start_utc = ?, has_alarms = ?, alarms_raw = ?, "
            "has_attendees = ?, provider_created_at = ?, provider_modified_at = ?, "
            "field_digest = ?, is_tombstone = 0, deleted_at = NULL, "
            "last_seen_at = ?, updated_at = ? WHERE id = ?",
            (event.calendar_id, *columns, seen_at, seen_at, event_id),
        )
        con.execute(
            "UPDATE event_external_ids SET calendar_item_id = ?, external_uid = ?, "
            "last_seen_at = ? WHERE provider_account_id = ? "
            "AND provider_calendar_id = ? AND provider_event_id = ?",
            (event.calendar_item_id, event.external_uid, seen_at,
             provider_account_id, event.provider_calendar_id,
             event.provider_event_id),
        )
        if not unchanged:
            self._replace_attendees(event_id, event.attendees, seen_at)
        con.execute(
            "DELETE FROM event_tombstones WHERE provider_account_id = ? "
            "AND provider_calendar_id = ? AND provider_event_id = ?",
            (provider_account_id, event.provider_calendar_id,
             event.provider_event_id),
        )
        return event_id, "unchanged" if unchanged else "updated"

    def _replace_attendees(self, event_id: str,
                           attendees: tuple[CanonicalAttendee, ...],
                           at: str) -> None:
        con = self._uow.connection
        con.execute("DELETE FROM event_attendees WHERE event_id = ?", (event_id,))
        for a in attendees:
            if a.raw_address is None and a.display_name is None:
                # Ein Teilnehmer ohne jede Kennung ist kein Datensatz.
                continue
            con.execute(
                "INSERT INTO event_attendees (id, event_id, contact_id, raw_address, "
                "display_name, role, participant_status, participant_type, "
                "is_organizer, is_current_user, created_at, updated_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (_new_id(), event_id, a.contact_id, a.raw_address, a.display_name,
                 a.role, a.participant_status, a.participant_type,
                 1 if a.is_organizer else 0, 1 if a.is_current_user else 0,
                 at, at),
            )

    def tombstone_absent_in_window(
        self, *, provider_account_id: str, provider_calendar_id: str,
        calendar_id: str, window: SyncWindow, seen_provider_ids: Iterable[str],
        at: str,
    ) -> int:
        """Leitet Löschungen ab — **nur** innerhalb des beobachteten Fensters.

        Der Aufrufer ruft dies ausschliesslich auf, wenn der Kalender in diesem
        Lauf vollständig gelesen wurde und das Fenster unverändert war. Die
        Einschränkung auf das Fenster steht zusätzlich hier im SQL: ein Termin
        ausserhalb ist nicht „nicht gesehen", sondern schlicht nicht gesucht
        worden.
        """
        seen = tuple(seen_provider_ids)
        con = self._uow.connection
        params: list[Any] = [provider_account_id, provider_calendar_id,
                             calendar_id, window.end_utc, window.start_utc]
        clause = ""
        if seen:
            clause = " AND x.provider_event_id NOT IN (" + \
                     ",".join("?" for _ in seen) + ")"
            params.extend(seen)

        rows = con.execute(
            "SELECT e.id, x.provider_event_id FROM events e "
            "JOIN event_external_ids x ON x.event_id = e.id "
            "WHERE x.provider_account_id = ? AND x.provider_calendar_id = ? "
            "AND e.calendar_id = ? AND e.is_tombstone = 0 "
            # Ueberlappung mit dem Fenster, nicht blosser Beginn: ein
            # mehrtaegiger Termin ragt hinein.
            "AND e.starts_at_utc < ? AND e.ends_at_utc > ?" + clause,
            tuple(params),
        ).fetchall()

        for event_id, provider_event_id in rows:
            con.execute(
                "UPDATE events SET is_tombstone = 1, deleted_at = ?, updated_at = ? "
                "WHERE id = ?", (at, at, event_id),
            )
            con.execute(
                "INSERT INTO event_tombstones (provider_account_id, "
                "provider_calendar_id, provider_event_id, event_id, deleted_at, "
                "observed_window_start_utc, observed_window_end_utc) "
                "VALUES (?,?,?,?,?,?,?) "
                "ON CONFLICT(provider_account_id, provider_calendar_id, "
                "provider_event_id) DO UPDATE SET deleted_at = excluded.deleted_at, "
                "observed_window_start_utc = excluded.observed_window_start_utc, "
                "observed_window_end_utc = excluded.observed_window_end_utc",
                (provider_account_id, provider_calendar_id, provider_event_id,
                 event_id, at, window.start_utc, window.end_utc),
            )
        return len(rows)

    def list_window(self, workspace_id: str, window: SyncWindow,
                    *, calendar_ids: tuple[str, ...] | None = None,
                    limit: int = 2000) -> tuple[dict[str, Any], ...]:
        """Projiziert den gespeicherten Bestand. Kein Provider-Zugriff."""
        con = self._uow.connection
        params: list[Any] = [workspace_id, window.end_utc, window.start_utc]
        clause = ""
        if calendar_ids:
            clause = " AND e.calendar_id IN (" + \
                     ",".join("?" for _ in calendar_ids) + ")"
            params.extend(calendar_ids)
        params.append(limit)
        rows = con.execute(
            "SELECT e.id, e.calendar_id, e.title, e.notes, e.location, e.url, "
            "e.starts_at_utc, e.ends_at_utc, e.time_zone, e.is_all_day, e.status, "
            "e.availability, e.recurrence_rule_raw, e.is_detached, "
            "e.occurrence_start_utc, e.has_alarms, e.alarms_raw, e.has_attendees, "
            "c.display_name, c.color, c.is_writable, "
            # Providerbindung fuer den Schreibpfad (B3 P2): ein Update
            # adressiert seinen Termin ueber genau diese beiden Kennungen.
            "c.provider_calendar_id, x.provider_event_id "
            "FROM events e JOIN calendars c ON c.id = e.calendar_id "
            "JOIN event_external_ids x ON x.event_id = e.id "
            "WHERE c.workspace_id = ? AND e.is_tombstone = 0 AND c.is_tombstone = 0 "
            "AND e.starts_at_utc < ? AND e.ends_at_utc > ?" + clause +
            " ORDER BY e.starts_at_utc, e.id LIMIT ?",
            tuple(params),
        ).fetchall()
        return tuple(
            {
                "id": r[0], "calendar_id": r[1], "title": r[2], "notes": r[3],
                "location": r[4], "url": r[5], "starts_at_utc": r[6],
                "ends_at_utc": r[7], "time_zone": r[8], "is_all_day": bool(r[9]),
                "status": r[10], "availability": r[11],
                "recurrence_rule": _loads(r[12]), "is_detached": bool(r[13]),
                "occurrence_start_utc": r[14], "has_alarms": bool(r[15]),
                "alarms": _loads(r[16]) or [], "has_attendees": bool(r[17]),
                "calendar_name": r[18], "calendar_color": r[19],
                "calendar_is_writable": bool(r[20]),
                "provider_calendar_id": r[21], "provider_event_id": r[22],
                "attendees": self._attendees(r[0]),
            }
            for r in rows
        )

    def _attendees(self, event_id: str) -> list[dict[str, Any]]:
        rows = self._uow.connection.execute(
            "SELECT raw_address, display_name, role, participant_status, "
            "participant_type, is_organizer, is_current_user, contact_id "
            "FROM event_attendees WHERE event_id = ? "
            "ORDER BY is_organizer DESC, display_name, raw_address",
            (event_id,),
        ).fetchall()
        return [
            {"raw_address": r[0], "display_name": r[1], "role": r[2],
             "participant_status": r[3], "participant_type": r[4],
             "is_organizer": bool(r[5]), "is_current_user": bool(r[6]),
             "contact_id": r[7]}
            for r in rows
        ]


class SyncWindowRepository:
    """Das zuletzt **vollständig** beobachtete Fenster je Kalender."""

    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    def get(self, calendar_id: str) -> SyncWindow | None:
        row = self._uow.connection.execute(
            "SELECT window_start_utc, window_end_utc FROM calendar_sync_windows "
            "WHERE calendar_id = ?", (calendar_id,),
        ).fetchone()
        return SyncWindow(start_utc=row[0], end_utc=row[1]) if row else None

    def record_complete_run(self, calendar_id: str, window: SyncWindow,
                            at: str, event_count: int) -> None:
        self._uow.connection.execute(
            "INSERT INTO calendar_sync_windows (calendar_id, window_start_utc, "
            "window_end_utc, last_complete_run_at, last_run_event_count) "
            "VALUES (?,?,?,?,?) ON CONFLICT(calendar_id) DO UPDATE SET "
            "window_start_utc = excluded.window_start_utc, "
            "window_end_utc = excluded.window_end_utc, "
            "last_complete_run_at = excluded.last_complete_run_at, "
            "last_run_event_count = excluded.last_run_event_count",
            (calendar_id, window.start_utc, window.end_utc, at, event_count),
        )
