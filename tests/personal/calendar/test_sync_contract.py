"""Der Sync-Vertrag — die Regeln, die aus EventKits Grenzen folgen.

Jeder Test hier prüft eine Regel, deren Verletzung stillschweigend Daten
verlöre. Sie sind wichtiger als die Zählungen daneben.
"""

from __future__ import annotations

from personaljarvis.base.db.unit_of_work import UnitOfWork
from personaljarvis.calendar.domain import (
    CanonicalAttendee,
    CanonicalEvent,
    SyncWindow,
    event_field_digest,
    window_covers,
)
from personaljarvis.calendar.sync import CalendarSyncService
from tests.personal.calendar.conftest import (
    PROVIDER_ACCOUNT,
    WORKSPACE,
    FakeCalendarClient,
    make_attendee,
    make_calendar,
    make_event,
)

WINDOW = SyncWindow(start_utc="2026-08-01T00:00:00Z",
                    end_utc="2026-09-01T00:00:00Z")
WIDER = SyncWindow(start_utc="2026-07-01T00:00:00Z",
                   end_utc="2026-10-01T00:00:00Z")


def service(factory, client):
    return CalendarSyncService(factory, client, workspace_id=WORKSPACE,
                               provider_account_id=PROVIDER_ACCOUNT)


def _count(factory, sql, params=()):
    with UnitOfWork(factory) as uow:
        return uow.connection.execute(sql, params).fetchone()[0]


# ── Fenster ──────────────────────────────────────────────────────────────────
def test_ein_lauf_nennt_immer_sein_fenster(factory):
    """Ein Bericht ohne Fensterangabe waere wertlos."""
    client = FakeCalendarClient([make_calendar()], {"cal-1": [make_event()]})
    report = service(factory, client).run(WINDOW)
    assert report.window == WINDOW
    assert client.event_calls[0][0] == WINDOW.start_utc
    assert client.event_calls[0][1] == WINDOW.end_utc


def test_das_fenster_landet_im_laufprotokoll(factory):
    client = FakeCalendarClient([make_calendar()], {"cal-1": [make_event()]})
    report = service(factory, client).run(WINDOW)
    with UnitOfWork(factory) as uow:
        row = uow.connection.execute(
            "SELECT window_start_utc, window_end_utc, outcome "
            "FROM calendar_sync_runs WHERE id = ?", (report.run_id,)).fetchone()
    assert tuple(row) == (WINDOW.start_utc, WINDOW.end_utc, "completed")


def test_ein_vergroessertes_fenster_deckt_das_alte_ab_aber_nicht_umgekehrt():
    assert window_covers(WIDER, WINDOW) is True
    assert window_covers(WINDOW, WIDER) is False
    assert window_covers(None, WINDOW) is False


# ── Tombstones: die drei Bedingungen ─────────────────────────────────────────
def test_tombstone_nur_nach_vollstaendiger_lesung(factory):
    """Bedingung 1: unvollstaendig gelesen ⇒ keine Loeschung."""
    client = FakeCalendarClient([make_calendar()],
                                {"cal-1": [make_event("ev-1"), make_event("ev-2")]})
    service(factory, client).run(WINDOW)
    assert _count(factory, "SELECT COUNT(*) FROM events") == 2

    # Zweiter Lauf sieht nur noch ev-1 — aber UNVOLLSTAENDIG.
    abbruch = FakeCalendarClient([make_calendar()], {"cal-1": [make_event("ev-1")]},
                                 complete=False)
    report = service(factory, abbruch).run(WINDOW)
    assert report.results[0].complete is False
    assert report.results[0].deletions_derivable is False
    assert report.tombstoned == 0
    assert _count(factory, "SELECT COUNT(*) FROM events WHERE is_tombstone = 1") == 0


def test_tombstone_nur_bei_unveraendertem_fenster(factory):
    """Bedingung 2: ein VERGROESSERTES Fenster ist ein Import, keine Loeschung."""
    client = FakeCalendarClient([make_calendar()],
                                {"cal-1": [make_event("ev-1"), make_event("ev-2")]})
    service(factory, client).run(WINDOW)

    # Groesseres Fenster, ev-2 fehlt: ueber den neuen Rand ist nichts bekannt.
    weiter = FakeCalendarClient([make_calendar()], {"cal-1": [make_event("ev-1")]})
    report = service(factory, weiter).run(WIDER)
    assert report.window_changed is True
    assert report.results[0].deletions_derivable is False
    assert report.tombstoned == 0


def test_tombstone_bei_vollstaendigem_lauf_und_gleichem_fenster(factory):
    """Alle drei Bedingungen erfuellt ⇒ die Loeschung ist ableitbar."""
    client = FakeCalendarClient([make_calendar()],
                                {"cal-1": [make_event("ev-1"), make_event("ev-2")]})
    service(factory, client).run(WINDOW)

    zweiter = FakeCalendarClient([make_calendar()], {"cal-1": [make_event("ev-1")]})
    report = service(factory, zweiter).run(WINDOW)
    assert report.results[0].deletions_derivable is True
    assert report.tombstoned == 1
    with UnitOfWork(factory) as uow:
        row = uow.connection.execute(
            "SELECT provider_event_id, observed_window_start_utc, "
            "observed_window_end_utc FROM event_tombstones").fetchone()
    # Der Tombstone haelt fest, UNTER WELCHEM Fenster er entstand.
    assert tuple(row) == ("ev-2", WINDOW.start_utc, WINDOW.end_utc)


def test_ein_termin_ausserhalb_des_fensters_wird_nie_getombstoned(factory):
    """Bedingung 3: nicht gesucht ist nicht dasselbe wie nicht gefunden."""
    frueh = make_event("ev-alt", start="2026-01-05T09:00:00Z",
                       end="2026-01-05T10:00:00Z")
    client = FakeCalendarClient([make_calendar()], {"cal-1": [frueh]})
    service(factory, client).run(SyncWindow(start_utc="2026-01-01T00:00:00Z",
                                            end_utc="2026-02-01T00:00:00Z"))
    assert _count(factory, "SELECT COUNT(*) FROM events") == 1

    # Anderes Fenster, in dem der alte Termin gar nicht liegen kann.
    spaeter = FakeCalendarClient([make_calendar()], {"cal-1": []})
    spaeter_report = service(factory, spaeter).run(WINDOW)
    assert spaeter_report.tombstoned == 0
    assert _count(factory, "SELECT COUNT(*) FROM events WHERE is_tombstone = 1") == 0


def test_ein_wiedergesehener_termin_verliert_seinen_tombstone(factory):
    client = FakeCalendarClient([make_calendar()],
                                {"cal-1": [make_event("ev-1"), make_event("ev-2")]})
    service(factory, client).run(WINDOW)
    service(factory, FakeCalendarClient([make_calendar()],
                                        {"cal-1": [make_event("ev-1")]})).run(WINDOW)
    assert _count(factory, "SELECT COUNT(*) FROM event_tombstones") == 1

    service(factory, FakeCalendarClient(
        [make_calendar()],
        {"cal-1": [make_event("ev-1"), make_event("ev-2")]})).run(WINDOW)
    assert _count(factory, "SELECT COUNT(*) FROM event_tombstones") == 0
    assert _count(factory, "SELECT COUNT(*) FROM events WHERE is_tombstone = 1") == 0


# ── Transaktionsgrenze ist der Kalender ──────────────────────────────────────
def test_ein_kaputter_kalender_laesst_die_anderen_vollstaendig(factory):
    kalender = [make_calendar("cal-1"), make_calendar("cal-2", name="Arbeit"),
                make_calendar("cal-3", name="Sport")]
    client = FakeCalendarClient(
        kalender,
        {"cal-1": [make_event("a1", calendar_id="cal-1")],
         "cal-3": [make_event("c1", calendar_id="cal-3")]},
        fail_events_for={"cal-2"})
    report = service(factory, client).run(WINDOW)

    assert report.outcome == "partial"
    ergebnisse = {r.provider_calendar_id: r for r in report.results}
    assert ergebnisse["cal-1"].complete is True
    assert ergebnisse["cal-2"].complete is False
    assert ergebnisse["cal-2"].error is not None
    assert ergebnisse["cal-3"].complete is True
    # Die beiden gesunden Kalender sind vollstaendig verarbeitet.
    assert _count(factory, "SELECT COUNT(*) FROM events") == 2


def test_ein_fehlschlag_beim_inventar_laesst_den_bestand_unveraendert(factory):
    erst = FakeCalendarClient([make_calendar()], {"cal-1": [make_event()]})
    service(factory, erst).run(WINDOW)
    assert _count(factory, "SELECT COUNT(*) FROM calendars WHERE is_tombstone = 0") == 1

    kaputt = FakeCalendarClient(fail_calendars=True)
    report = service(factory, kaputt).run(WINDOW)
    assert report.outcome == "failed"
    # KEIN Kalender wird geloescht, nur weil die Bridge nicht antwortete.
    assert _count(factory, "SELECT COUNT(*) FROM calendars WHERE is_tombstone = 0") == 1


def test_ein_verschwundener_kalender_wird_markiert_nicht_geloescht(factory):
    service(factory, FakeCalendarClient(
        [make_calendar("cal-1"), make_calendar("cal-2", name="Arbeit")],
        {"cal-1": [make_event()]})).run(WINDOW)
    service(factory, FakeCalendarClient([make_calendar("cal-1")],
                                        {"cal-1": [make_event()]})).run(WINDOW)
    # Kein Hard-Delete: der Datensatz bleibt, markiert.
    assert _count(factory, "SELECT COUNT(*) FROM calendars") == 2
    assert _count(factory, "SELECT COUNT(*) FROM calendars WHERE is_tombstone = 1") == 1


# ── Aenderungserkennung ueber den Digest ─────────────────────────────────────
def test_unveraenderter_termin_gilt_als_unveraendert(factory):
    client = FakeCalendarClient([make_calendar()], {"cal-1": [make_event()]})
    erst = service(factory, client).run(WINDOW)
    assert erst.created == 1

    zweit = service(factory, FakeCalendarClient(
        [make_calendar()], {"cal-1": [make_event()]})).run(WINDOW)
    assert zweit.unchanged == 1
    assert zweit.updated == 0


def test_geaenderter_titel_gilt_als_aenderung(factory):
    service(factory, FakeCalendarClient([make_calendar()],
                                        {"cal-1": [make_event()]})).run(WINDOW)
    report = service(factory, FakeCalendarClient(
        [make_calendar()], {"cal-1": [make_event(title="Anders")]})).run(WINDOW)
    assert report.updated == 1


def test_der_digest_ignoriert_den_providerzeitstempel():
    """`lastModifiedDate` kommt vom Server und ist bei CalDAV nicht verlaesslich."""
    a = CanonicalEvent(id="1", calendar_id="c", provider_event_id="e",
                       provider_calendar_id="cal", starts_at_utc="2026-08-10T09:00:00Z",
                       ends_at_utc="2026-08-10T10:00:00Z", title="X",
                       provider_modified_at="2026-08-01T00:00:00Z")
    b = CanonicalEvent(id="2", calendar_id="c", provider_event_id="e",
                       provider_calendar_id="cal", starts_at_utc="2026-08-10T09:00:00Z",
                       ends_at_utc="2026-08-10T10:00:00Z", title="X",
                       provider_modified_at="2026-08-04T12:00:00Z")
    assert event_field_digest(a) == event_field_digest(b)


def test_der_digest_beachtet_die_teilnehmerliste():
    """Eine geaenderte Einladung ist eine Aenderung, kein Rauschen."""
    ohne = CanonicalEvent(id="1", calendar_id="c", provider_event_id="e",
                          provider_calendar_id="cal",
                          starts_at_utc="2026-08-10T09:00:00Z",
                          ends_at_utc="2026-08-10T10:00:00Z")
    mit = CanonicalEvent(
        id="1", calendar_id="c", provider_event_id="e", provider_calendar_id="cal",
        starts_at_utc="2026-08-10T09:00:00Z", ends_at_utc="2026-08-10T10:00:00Z",
        attendees=(CanonicalAttendee(raw_address="a@example.invalid",
                                     display_name="A"),))
    assert event_field_digest(ohne) != event_field_digest(mit)


def test_der_digest_ist_reihenfolgeunabhaengig():
    a1 = CanonicalAttendee(raw_address="a@example.invalid", display_name="A")
    a2 = CanonicalAttendee(raw_address="b@example.invalid", display_name="B")
    basis = dict(id="1", calendar_id="c", provider_event_id="e",
                 provider_calendar_id="cal",
                 starts_at_utc="2026-08-10T09:00:00Z",
                 ends_at_utc="2026-08-10T10:00:00Z")
    assert (event_field_digest(CanonicalEvent(**basis, attendees=(a1, a2)))
            == event_field_digest(CanonicalEvent(**basis, attendees=(a2, a1))))


# ── Zeitzonen und schwebende Termine ─────────────────────────────────────────
def test_eine_fehlende_zeitzone_bleibt_fehlend(factory):
    """Schwebend heisst schwebend — nicht UTC und nicht 'unbekannt'."""
    schwebend = make_event("ev-float", time_zone=None, all_day=True,
                           start="2026-08-12T00:00:00Z",
                           end="2026-08-13T00:00:00Z")
    service(factory, FakeCalendarClient([make_calendar()],
                                        {"cal-1": [schwebend]})).run(WINDOW)
    with UnitOfWork(factory) as uow:
        tz, all_day = uow.connection.execute(
            "SELECT time_zone, is_all_day FROM events").fetchone()
    assert tz is None
    assert all_day == 1


def test_eine_gesetzte_zeitzone_bleibt_erhalten(factory):
    service(factory, FakeCalendarClient(
        [make_calendar()],
        {"cal-1": [make_event(time_zone="America/New_York")]})).run(WINDOW)
    with UnitOfWork(factory) as uow:
        tz = uow.connection.execute("SELECT time_zone FROM events").fetchone()[0]
    assert tz == "America/New_York"


# ── Serien ───────────────────────────────────────────────────────────────────
def test_die_wiederholungsregel_wird_roh_gespeichert(factory):
    regel = {"frequency": "weekly", "interval": 1,
             "daysOfTheWeek": [{"dayOfTheWeek": 2, "weekNumber": 0}],
             "end": {"type": "count", "count": 10}}
    service(factory, FakeCalendarClient(
        [make_calendar()],
        {"cal-1": [make_event("ev-serie", recurrence=regel)]})).run(WINDOW)
    with UnitOfWork(factory) as uow:
        roh, serie = uow.connection.execute(
            "SELECT recurrence_rule_raw, series_id FROM events").fetchone()
    assert '"frequency":"weekly"' in roh
    assert serie == "ev-serie"


def test_es_gibt_keine_tabelle_materialisierter_instanzen(factory):
    """Instanzen sind abgeleiteter Cache und duerfen nie Wahrheit werden."""
    with UnitOfWork(factory) as uow:
        namen = {r[0] for r in uow.connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert not any("occurrence" in n or "instance" in n for n in namen)


def test_eine_abgeloeste_instanz_traegt_ihren_urspruenglichen_beginn(factory):
    ausnahme = make_event("ev-x", detached=True,
                          occurrence="2026-08-17T09:00:00Z")
    service(factory, FakeCalendarClient([make_calendar()],
                                        {"cal-1": [ausnahme]})).run(WINDOW)
    with UnitOfWork(factory) as uow:
        detached, occurrence = uow.connection.execute(
            "SELECT is_detached, occurrence_start_utc FROM events").fetchone()
    assert detached == 1
    assert occurrence == "2026-08-17T09:00:00Z"


# ── Identitaet ───────────────────────────────────────────────────────────────
def test_dieselbe_caldav_uid_darf_mehrfach_vorkommen(factory):
    """Bei Einladungen liegt derselbe Termin in mehreren Kalendern."""
    client = FakeCalendarClient(
        [make_calendar("cal-1"), make_calendar("cal-2", name="Arbeit")],
        {"cal-1": [make_event("ev-a", calendar_id="cal-1", external_uid="geteilt")],
         "cal-2": [make_event("ev-b", calendar_id="cal-2", external_uid="geteilt")]})
    report = service(factory, client).run(WINDOW)
    assert report.created == 2
    assert _count(factory,
                  "SELECT COUNT(*) FROM event_external_ids WHERE external_uid = ?",
                  ("geteilt",)) == 2


def test_ein_termin_ohne_providerkennung_wird_uebergangen(factory):
    ohne = make_event("", calendar_id="cal-1")
    report = service(factory, FakeCalendarClient([make_calendar()],
                                                 {"cal-1": [ohne]})).run(WINDOW)
    assert report.events_seen == 0
    assert _count(factory, "SELECT COUNT(*) FROM events") == 0


# ── Provider-Wahrheit ────────────────────────────────────────────────────────
def test_ein_unveraenderlicher_kalender_ist_nicht_schreibbar(factory):
    """Geburtstage melden false — das Modul ueberstimmt das nie."""
    geburtstage = make_calendar("cal-bday", name="Geburtstage", writable=True,
                                immutable=True, calendar_type="birthday")
    service(factory, FakeCalendarClient([geburtstage], {"cal-bday": []})).run(WINDOW)
    with UnitOfWork(factory) as uow:
        writable = uow.connection.execute(
            "SELECT is_writable FROM calendars").fetchone()[0]
    assert writable == 0


def test_ein_abonnierter_kalender_bleibt_als_solcher_erkennbar(factory):
    abo = make_calendar("cal-abo", name="Feiertage", writable=False,
                        subscribed=True, calendar_type="subscription")
    service(factory, FakeCalendarClient([abo], {"cal-abo": []})).run(WINDOW)
    with UnitOfWork(factory) as uow:
        row = uow.connection.execute(
            "SELECT is_subscribed, is_writable, calendar_type "
            "FROM calendars").fetchone()
    assert tuple(row) == (1, 0, "subscription")


# ── Teilnehmer ───────────────────────────────────────────────────────────────
def test_teilnehmer_werden_roh_uebernommen_und_nie_zugeordnet(factory):
    ev = make_event(attendees=[make_attendee("Chef@Example.invalid",
                                             name="Die Chefin", organizer=True),
                               make_attendee("b@example.invalid", name="B")])
    service(factory, FakeCalendarClient([make_calendar()],
                                        {"cal-1": [ev]})).run(WINDOW)
    with UnitOfWork(factory) as uow:
        rows = uow.connection.execute(
            "SELECT raw_address, contact_id, is_organizer FROM event_attendees "
            "ORDER BY is_organizer DESC").fetchall()
    # Grossschreibung bleibt: Normalisierung ist Kernarbeit, nicht Adapterarbeit.
    assert rows[0][0] == "Chef@Example.invalid"
    assert rows[0][2] == 1
    # Keine Zuordnung ohne ausdrueckliche Entscheidung.
    assert all(r[1] is None for r in rows)


# ── Wiederholbarkeit ─────────────────────────────────────────────────────────
def test_ein_wiederholter_lauf_ist_idempotent(factory):
    daten = {"cal-1": [make_event("ev-1"), make_event("ev-2")]}
    for _ in range(3):
        service(factory, FakeCalendarClient([make_calendar()], daten)).run(WINDOW)
    assert _count(factory, "SELECT COUNT(*) FROM events") == 2
    assert _count(factory, "SELECT COUNT(*) FROM event_external_ids") == 2
