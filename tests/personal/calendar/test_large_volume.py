"""K1-O04 — grosse Bestaende: Laufzeit, Speicher und Fensterwahl.

Kalenderfrei wie die uebrige Suite: kein Sidecar, kein `EKEventStore`, keine
TCC-Abfrage. Der Bestand ist synthetisch, die Datenbank liegt in `tmp_path`.
Gemessen wird der Sync-Vertrag selbst — der Pfad, der bei einem echten
Bestand die Arbeit leistet.

Die Schwellen sind bewusst grosszuegig. Sie sollen eine **Groessenordnung**
festhalten und eine Regression sichtbar machen, nicht eine Maschine
benchmarken; ein zu enger Wert waere auf fremder Hardware nur noch Rauschen.
"""

from __future__ import annotations

import json
import os
import resource
import time

from personaljarvis.base.db.unit_of_work import UnitOfWork
from personaljarvis.calendar.domain import SyncWindow
from personaljarvis.calendar.sync import CalendarSyncService
from tests.personal.calendar.conftest import (
    PROVIDER_ACCOUNT,
    WORKSPACE,
    FakeCalendarClient,
    make_attendee,
    make_calendar,
    make_event,
)

#: Der gemessene Bestand. "Tausende Termine" nach Modulunterlage §8 Nr. 4.
EVENT_COUNT = 4000
CALENDAR_COUNT = 4
ATTENDEES_PER_EVENT = 3

#: Obergrenzen als Groessenordnung, nicht als Benchmark.
MAX_SECONDS_FIRST_RUN = 120.0
MAX_SECONDS_REPEAT_RUN = 120.0
MAX_RESIDENT_GROWTH_MB = 512.0

WINDOW = SyncWindow(start_utc="2026-08-01T00:00:00Z",
                    end_utc="2026-09-01T00:00:00Z")
NARROW = SyncWindow(start_utc="2026-08-10T00:00:00Z",
                    end_utc="2026-08-20T00:00:00Z")
WIDE = SyncWindow(start_utc="2026-07-01T00:00:00Z",
                  end_utc="2026-10-01T00:00:00Z")


def _resident_mb():
    usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    # macOS reports bytes, Linux kilobytes.
    return usage / (1024 * 1024) if usage > 1 << 20 else usage / 1024


def _large_estate():
    """Ein synthetischer Bestand ueber mehrere Kalender."""
    calendars = [
        make_calendar(f"cal-{index}", name=f"Kalender {index}")
        for index in range(CALENDAR_COUNT)
    ]
    events_by_calendar = {}
    per_calendar = EVENT_COUNT // CALENDAR_COUNT
    for index, calendar in enumerate(calendars):
        events = []
        for offset in range(per_calendar):
            day = 1 + (offset % 28)
            hour = offset % 12
            events.append(
                make_event(
                    f"ev-{index}-{offset}",
                    calendar_id=calendar.provider_calendar_id,
                    start=f"2026-08-{day:02d}T{hour:02d}:00:00Z",
                    end=f"2026-08-{day:02d}T{hour + 1:02d}:00:00Z",
                    title=f"Synthetischer Termin {index}-{offset}",
                    external_uid=f"uid-{index}-{offset}",
                    attendees=[
                        make_attendee(
                            address=f"person{slot}@example.invalid",
                            name=f"Erfundene Person {slot}",
                            organizer=slot == 0,
                        )
                        for slot in range(ATTENDEES_PER_EVENT)
                    ],
                )
            )
        events_by_calendar[calendar.provider_calendar_id] = events
    return calendars, events_by_calendar


def _service(factory, client):
    return CalendarSyncService(factory, client, workspace_id=WORKSPACE,
                               provider_account_id=PROVIDER_ACCOUNT)


def _count(factory, sql):
    with UnitOfWork(factory) as uow:
        return uow.connection.execute(sql).fetchone()[0]


def test_large_estate_runtime_memory_and_window_choice(factory, tmp_path):
    calendars, events_by_calendar = _large_estate()
    client = FakeCalendarClient(calendars, events_by_calendar)
    service = _service(factory, client)

    before_mb = _resident_mb()
    started = time.monotonic()
    first = service.run(WINDOW)
    first_seconds = time.monotonic() - started
    after_first_mb = _resident_mb()

    assert first.outcome == "completed"
    stored = _count(factory, "SELECT COUNT(*) FROM events")
    assert stored == EVENT_COUNT, f"erwartet {EVENT_COUNT}, gespeichert {stored}"
    attendees = _count(factory, "SELECT COUNT(*) FROM event_attendees")
    assert attendees == EVENT_COUNT * ATTENDEES_PER_EVENT

    # Der Wiederholungslauf ist der eigentliche Vertrag: der Felddigest
    # erkennt unveraenderte Termine, es entsteht kein zweiter Bestand.
    started = time.monotonic()
    second = service.run(WINDOW)
    repeat_seconds = time.monotonic() - started
    after_repeat_mb = _resident_mb()

    assert second.outcome == "completed"
    assert _count(factory, "SELECT COUNT(*) FROM events") == EVENT_COUNT
    assert _count(factory, "SELECT COUNT(*) FROM events WHERE is_tombstone = 1") == 0

    # Fensterwahl: verkleinern erzeugt keine Tombstones, vergroessern ist ein
    # Import ohne Loeschableitung. Beides muss auch im grossen Bestand gelten.
    service.run(NARROW)
    assert _count(factory, "SELECT COUNT(*) FROM events WHERE is_tombstone = 1") == 0
    service.run(WIDE)
    assert _count(factory, "SELECT COUNT(*) FROM events WHERE is_tombstone = 1") == 0
    assert _count(factory, "SELECT COUNT(*) FROM events") == EVENT_COUNT

    growth_mb = max(after_first_mb, after_repeat_mb) - before_mb

    measurement = {
        "gate_id": "K1-O04",
        "event_count": EVENT_COUNT,
        "calendar_count": CALENDAR_COUNT,
        "attendees_per_event": ATTENDEES_PER_EVENT,
        "first_run_seconds": round(first_seconds, 3),
        "repeat_run_seconds": round(repeat_seconds, 3),
        "resident_growth_mb": round(growth_mb, 1),
        "tombstones_after_window_changes": 0,
        "calendar_free": True,
    }
    target = tmp_path / "k1-o04-measurement.json"
    target.write_text(json.dumps(measurement, sort_keys=True, indent=2),
                      encoding="utf-8")
    # Die Messung erscheint im Testlauf, damit sie in das Rohlog des Gates
    # gelangt; sie enthaelt ausschliesslich Zahlen.
    print("K1-O04 measurement " + json.dumps(measurement, sort_keys=True))

    assert first_seconds < MAX_SECONDS_FIRST_RUN, measurement
    assert repeat_seconds < MAX_SECONDS_REPEAT_RUN, measurement
    assert growth_mb < MAX_RESIDENT_GROWTH_MB, measurement


def test_window_is_recorded_with_every_run(factory):
    """Jeder Lauf nennt sein Fenster — auch im grossen Bestand."""
    calendars, events_by_calendar = _large_estate()
    service = _service(factory, FakeCalendarClient(calendars, events_by_calendar))
    service.run(WINDOW)
    with UnitOfWork(factory) as uow:
        rows = uow.connection.execute(
            "SELECT window_start_utc, window_end_utc FROM calendar_sync_runs"
        ).fetchall()
    assert rows
    for start, end in rows:
        assert start == WINDOW.start_utc
        assert end == WINDOW.end_utc


def test_measurement_uses_no_real_calendar(factory):
    """Kontrolle: der Bestand ist synthetisch und beruehrt kein EventKit."""
    calendars, events_by_calendar = _large_estate()
    client = FakeCalendarClient(calendars, events_by_calendar)
    assert not hasattr(client, "_process")
    assert os.environ.get("EVENTKIT_ENABLED") is None
    titles = {
        event.title
        for events in events_by_calendar.values()
        for event in events
    }
    assert all(title.startswith("Synthetischer Termin") for title in titles)
