"""Gemeinsame Fixtures der Kalender-Suite.

**Kalenderfrei:** Kein Test dieser Suite startet einen Sidecar mit
Store-Zugriff, fragt TCC ab, berührt `EKEventStore` oder liest einen echten
Termin. Alle Daten sind erfundene Fixtures; alle Datenbanken liegen in
`tmp_path` oder im Speicher.

Der Fake-Client ist die zentrale Prüfstelle des Sync-Vertrags: Er kann
ausdrücklich auch **unvollständig** antworten, und genau daran hängt die
Tombstone-Regel.
"""

from __future__ import annotations

import uuid

import pytest

from personaljarvis.base.db.factory import ConnectionFactory
from personaljarvis.base.db.migrations import ALL_MIGRATIONS, MigrationRunner
from personaljarvis.calendar.bridge.models import (
    AuthorizationStatus,
    BridgeAttendee,
    BridgeCalendar,
    BridgeEvent,
    CalendarCapabilities,
    CalendarHandshake,
    CalendarSource,
    EventWindowResult,
)

WORKSPACE = "ws-test"
PROVIDER_ACCOUNT = "apple-calendar-test"


def new_id() -> str:
    return str(uuid.uuid4())


@pytest.fixture
def factory(tmp_path):
    """Eine migrierte Datenbank auf einer echten Datei."""
    path = tmp_path / "personal" / "jarvis.db"
    path.parent.mkdir(parents=True, exist_ok=True)
    f = ConnectionFactory(path)
    f.ensure_ready()
    MigrationRunner(f, ALL_MIGRATIONS).run()
    yield f
    f.close()


def make_calendar(provider_id="cal-1", *, name="Privat", writable=True,
                  immutable=False, subscribed=False,
                  calendar_type="calDAV") -> BridgeCalendar:
    return BridgeCalendar(
        provider_calendar_id=provider_id,
        display_name=name,
        calendar_type=calendar_type,
        color="#336699",
        is_subscribed=subscribed,
        is_immutable=immutable,
        is_writable=writable,
        supports_events=True,
        source=CalendarSource(source_identifier="src-1", title="iCloud",
                              source_type="calDAV"),
    )


def make_event(provider_id="ev-1", *, calendar_id="cal-1",
               start="2026-08-10T09:00:00Z", end="2026-08-10T10:00:00Z",
               title="Besprechung", time_zone="Europe/Berlin",
               all_day=False, recurrence=None, detached=False,
               occurrence=None, attendees=(), alarms=(),
               external_uid="uid-1") -> BridgeEvent:
    return BridgeEvent(
        provider_event_id=provider_id,
        calendar_item_id=f"item-{provider_id}",
        external_uid=external_uid,
        provider_calendar_id=calendar_id,
        title=title, notes=None, location=None, url=None,
        starts_at_utc=start, ends_at_utc=end,
        time_zone=time_zone, is_all_day=all_day,
        status="confirmed", availability="busy",
        has_recurrence_rules=recurrence is not None,
        recurrence_rule_count=1 if recurrence is not None else 0,
        recurrence_rule=recurrence,
        is_detached=detached,
        occurrence_start_utc=occurrence,
        alarms=tuple(alarms), attendees=tuple(attendees),
        created_at_utc="2026-08-01T00:00:00Z",
        last_modified_at_utc="2026-08-01T00:00:00Z",
    )


def make_attendee(address="a@example.invalid", *, name="A. Person",
                  organizer=False, status="accepted") -> BridgeAttendee:
    return BridgeAttendee(
        raw_address=address, display_name=name, role="required",
        participant_status=status, participant_type="person",
        is_current_user=False, is_organizer=organizer,
    )


class FakeCalendarClient:
    """Ein Client ohne Prozess und ohne EventKit.

    `complete` ist absichtlich steuerbar: Eine unvollständige Lesung ist der
    Normalfall bei Abbruch, und der Sync muss daraus **nichts** ableiten.
    """

    def __init__(self, calendars=(), events_by_calendar=None, *,
                 complete=True, capabilities=None, fail_calendars=False,
                 fail_events_for=()):
        self._calendars = tuple(calendars)
        self._events = dict(events_by_calendar or {})
        self._complete = complete
        self._capabilities = capabilities or CalendarCapabilities(
            can_read=True, supports_recurrence=True, supports_attendees=True,
            supports_alarms=True, supports_time_zones=True,
            window_required=True, change_feed="notification")
        self._fail_calendars = fail_calendars
        self._fail_events_for = set(fail_events_for)
        self.event_calls: list[tuple[str, str, tuple[str, ...] | None]] = []
        self.stopped = False

    @property
    def capabilities(self):
        return self._capabilities

    @property
    def handshake(self):
        return CalendarHandshake(
            protocol_version=1, bundle_identifier="test",
            key_set_version=1,
            authorization_status=AuthorizationStatus.FULL_ACCESS,
            operations=("ping", "calendars", "events"),
            capabilities=self._capabilities)

    def start(self):
        return self.handshake

    def stop(self):
        self.stopped = True

    def ping(self):
        return True

    def calendars(self):
        if self._fail_calendars:
            from personaljarvis.base.sidecar.errors import BridgeOperationError
            raise BridgeOperationError("provider_error", "kaputt")
        return self._calendars

    def events(self, *, start_utc, end_utc, provider_calendar_ids=None,
               timeout=None):
        self.event_calls.append((start_utc, end_utc, provider_calendar_ids))
        cal_id = (provider_calendar_ids or ("",))[0]
        if cal_id in self._fail_events_for:
            from personaljarvis.base.sidecar.errors import BridgeOperationError
            raise BridgeOperationError("provider_error", "kaputt")
        return EventWindowResult(
            events=tuple(self._events.get(cal_id, ())),
            complete=self._complete,
            window_start_utc=start_utc, window_end_utc=end_utc,
            provider_calendar_ids=provider_calendar_ids,
        )


@pytest.fixture(autouse=True)
def eigentuemerbeleg_vorhanden(monkeypatch):
    """Dieselbe sichtbare Annahme wie in der Kontakte-Suite.

    Seit der Reparatur vom 2026-08-17 entsteht eine Eigentümerentscheidung nur
    gegen einen Beleg aus dem App-Prozess (`base/owner_attestation.py`). Diese
    Suite prüft den Ablauf **nach** der Freigabe; ohne die Öffnung käme keine
    einzige zustande. Die Herkunft prüft `test_owner_provenance.py`.
    """
    from personaljarvis.base import owner_attestation as beleg

    def _immer(*, capability, mutation_id, payload_digest, **_):
        return beleg.OwnerAttestation(
            capability=capability, mutation_id=mutation_id,
            payload_digest=payload_digest,
            attested_at="2026-08-17T12:00:00Z", method="testannahme")

    monkeypatch.setattr(beleg, "read_attestation", _immer)
    monkeypatch.setattr(beleg, "consume_attestation", lambda **_: True)
