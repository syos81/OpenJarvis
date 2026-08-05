"""Kalender-Synchronisation — fensterbasierter Voll-Diff je Kalender.

Der Vertrag folgt **zwangsläufig** aus dem, was EventKit nicht kann:

* Es gibt keine Änderungshistorie. `EKEventStoreChangedNotification` ist ein
  Auslöser („schau nach"), niemals ein Delta („das hat sich geändert"). Wer sie
  als Delta behandelt, verliert Änderungen.
* Es gibt kein „alle Termine". Gelesen wird immer über ein Fenster.
* Löschungen sind nicht beobachtbar. Ein Termin, der im nächsten Lauf fehlt,
  kann gelöscht, verschoben oder aus dem Fenster gefallen sein — ohne weitere
  Information sind diese drei Fälle ununterscheidbar.

Daraus folgen die vier Regeln dieses Moduls:

1. **Fensterbasierter Voll-Diff je Kalender ist der Normalbetrieb**, nicht der
   Notfall. Jeder Lauf nennt sein Fenster.
2. **Die Transaktionsgrenze ist der Kalender, nicht der Lauf.** Ein
   abgebrochener Lauf hinterlässt vollständig verarbeitete Kalender und
   unberührte — nie halb verarbeitete.
3. **Ein Tombstone entsteht nur unter drei Bedingungen zugleich:** der Kalender
   wurde in diesem Lauf **vollständig** gelesen, das Fenster war
   **unverändert**, und der Termin lag **im Fenster**. Sonst gilt „nicht
   gesehen" als *unbekannt* — ein verschobener Termin ist kein gelöschter.
4. **Ein unterbrochener Lauf wird nie fortgesetzt, sondern wiederholt.** Es
   gibt keinen Cursor, an dem man ansetzen könnte. Der Wiederholungslauf ist
   billig, weil der Digest unveränderte Termine sofort erkennt.

Änderungserkennung läuft über den **Felddigest**, nicht über
`lastModifiedDate`: der Zeitstempel kommt vom Server und ist bei CalDAV nicht
verlässlich.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable

from personaljarvis.base.db.factory import ConnectionFactory
from personaljarvis.base.db.unit_of_work import UnitOfWork
from personaljarvis.base.sidecar.errors import BridgeError
from personaljarvis.calendar.bridge.client import CalendarBridgeClient
from personaljarvis.calendar.bridge.models import BridgeCalendar, BridgeEvent
from personaljarvis.calendar.domain import (
    CanonicalAttendee,
    CanonicalCalendar,
    CanonicalEvent,
    SyncWindow,
    window_covers,
)
from personaljarvis.calendar.repositories import (
    CalendarRepository,
    EventRepository,
    SyncWindowRepository,
)

__all__ = ["CalendarSyncReport", "CalendarSyncResult", "CalendarSyncService"]


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class CalendarSyncResult:
    """Was mit **einem** Kalender in diesem Lauf geschah."""

    provider_calendar_id: str
    calendar_id: str | None = None
    complete: bool = False
    #: Ob aus diesem Kalender in diesem Lauf Löschungen abgeleitet werden
    #: durften. `False` heisst nicht „nichts gelöscht", sondern „nicht
    #: entscheidbar".
    deletions_derivable: bool = False
    events_seen: int = 0
    created: int = 0
    updated: int = 0
    unchanged: int = 0
    tombstoned: int = 0
    error: str | None = None


@dataclass
class CalendarSyncReport:
    """Das Ergebnis eines Laufs. Führt sein Fenster ausdrücklich mit."""

    run_id: str
    window: SyncWindow
    started_at: str
    finished_at: str | None = None
    calendars_total: int = 0
    results: list[CalendarSyncResult] = field(default_factory=list)
    #: Fenster gegenüber dem letzten Lauf geändert ⇒ Import ohne
    #: Löschableitung (Baseline B-8).
    window_changed: bool = False
    error: str | None = None

    @property
    def calendars_complete(self) -> int:
        return sum(1 for r in self.results if r.complete)

    @property
    def events_seen(self) -> int:
        return sum(r.events_seen for r in self.results)

    @property
    def created(self) -> int:
        return sum(r.created for r in self.results)

    @property
    def updated(self) -> int:
        return sum(r.updated for r in self.results)

    @property
    def unchanged(self) -> int:
        return sum(r.unchanged for r in self.results)

    @property
    def tombstoned(self) -> int:
        return sum(r.tombstoned for r in self.results)

    @property
    def outcome(self) -> str:
        """`completed`, `partial` oder `failed` — eine Gesamtaussage.

        Ohne sie müsste jeder Aufrufer die Teilergebnisse selbst
        zusammenrechnen, und der erste, der es vergisst, meldet einen Erfolg,
        den es nicht gab.
        """
        if self.error is not None:
            return "failed"
        if not self.results:
            return "failed"
        if all(r.complete for r in self.results):
            return "completed"
        if any(r.complete for r in self.results):
            return "partial"
        return "failed"


def _to_canonical_calendar(c: BridgeCalendar, workspace_id: str,
                           provider_account_id: str) -> CanonicalCalendar:
    source = c.source
    return CanonicalCalendar(
        id="", workspace_id=workspace_id,
        provider_account_id=provider_account_id,
        provider_calendar_id=c.provider_calendar_id,
        display_name=c.display_name or c.provider_calendar_id,
        calendar_type=c.calendar_type,
        source_identifier=source.source_identifier if source else None,
        source_title=source.title if source else None,
        source_type=source.source_type if source else None,
        color=c.color,
        # Provider-Wahrheit. Ein abonnierter oder unveraenderlicher Kalender
        # meldet false, und das Modul ueberstimmt das nie.
        is_writable=c.is_writable and not c.is_immutable,
        is_subscribed=c.is_subscribed,
        is_immutable=c.is_immutable,
        supports_events=c.supports_events,
    )


def _to_canonical_event(e: BridgeEvent, calendar_id: str) -> CanonicalEvent:
    return CanonicalEvent(
        id="", calendar_id=calendar_id,
        provider_event_id=e.provider_event_id,
        provider_calendar_id=e.provider_calendar_id,
        starts_at_utc=e.starts_at_utc, ends_at_utc=e.ends_at_utc,
        title=e.title, notes=e.notes, location=e.location, url=e.url,
        time_zone=e.time_zone, is_all_day=e.is_all_day,
        status=e.status, availability=e.availability,
        recurrence_rule_raw=e.recurrence_rule,
        recurrence_rule_count=e.recurrence_rule_count,
        # Die Serienidentität ist der Termin-Identifier selbst: EventKit gibt
        # bei einer Serie allen Instanzen dieselbe `eventIdentifier`. Die
        # Instanz ist erst mit ihrem Beginn eindeutig — deshalb steht die
        # Kennung hier als `series_id` und nicht als Primärschlüssel.
        series_id=(e.provider_event_id if e.has_recurrence_rules else None),
        is_detached=e.is_detached,
        occurrence_start_utc=(e.occurrence_start_utc if e.is_detached else None),
        alarms_raw=tuple(
            {"absolute_date": a.absolute_date,
             "relative_offset_seconds": a.relative_offset_seconds}
            for a in e.alarms
        ),
        attendees=tuple(
            CanonicalAttendee(
                raw_address=a.raw_address, display_name=a.display_name,
                role=a.role, participant_status=a.participant_status,
                participant_type=a.participant_type,
                is_organizer=a.is_organizer, is_current_user=a.is_current_user,
            )
            for a in e.attendees
        ),
        calendar_item_id=e.calendar_item_id,
        external_uid=e.external_uid,
        provider_created_at=e.created_at_utc,
        provider_modified_at=e.last_modified_at_utc,
    )


class CalendarSyncService:
    """Führt Läufe aus. Startet **nie** von selbst — ein Lauf ist eine Handlung."""

    def __init__(self, factory: ConnectionFactory, client: CalendarBridgeClient, *,
                 workspace_id: str, provider_account_id: str,
                 now: Callable[[], str] = _now_iso) -> None:
        self._factory = factory
        self._client = client
        self._workspace_id = workspace_id
        self._provider_account_id = provider_account_id
        self._now = now

    def run(self, window: SyncWindow) -> CalendarSyncReport:
        """Ein vollständiger Lauf über alle sichtbaren Kalender."""
        report = CalendarSyncReport(run_id=str(uuid.uuid4()), window=window,
                                    started_at=self._now())

        # ── 1. Kalenderinventar ─────────────────────────────────────────────
        #
        # Zuerst, damit die Termine gleich ihren Kalender kennen. Scheitert es,
        # bleibt der Bestand unverändert — insbesondere wird KEIN Kalender
        # als gelöscht markiert, nur weil die Bridge gerade nicht antwortete.
        try:
            bridge_calendars = self._client.calendars()
        except BridgeError as exc:
            report.error = exc.__class__.__name__
            report.finished_at = self._now()
            self._record_run(report)
            return report

        at = self._now()
        calendar_ids: dict[str, str] = {}
        with UnitOfWork(self._factory) as uow:
            repo = CalendarRepository(uow)
            for bc in bridge_calendars:
                canonical = _to_canonical_calendar(
                    bc, self._workspace_id, self._provider_account_id)
                cal_id, _ = repo.upsert_seen(canonical, at)
                calendar_ids[bc.provider_calendar_id] = cal_id
            repo.tombstone_missing(self._provider_account_id,
                                   calendar_ids.keys(), at)
        report.calendars_total = len(bridge_calendars)

        # ── 2. Termine, Kalender für Kalender ───────────────────────────────
        #
        # Je Kalender eine eigene Transaktion (Regel 2). Ein Fehlschlag beim
        # dritten Kalender laesst die ersten beiden vollstaendig verarbeitet
        # zurueck und die restlichen unberuehrt.
        for bc in bridge_calendars:
            result = CalendarSyncResult(
                provider_calendar_id=bc.provider_calendar_id,
                calendar_id=calendar_ids.get(bc.provider_calendar_id))
            report.results.append(result)
            if not bc.supports_events:
                result.complete = True
                continue
            try:
                self._sync_one_calendar(bc, result, window, report)
            except BridgeError as exc:
                # Ehrlich: dieser Kalender ist unvollstaendig, und aus ihm folgt
                # in diesem Lauf keine Loeschung.
                result.error = exc.__class__.__name__
                result.complete = False
                result.deletions_derivable = False

        report.finished_at = self._now()
        self._record_run(report)
        return report

    def _sync_one_calendar(self, bc: BridgeCalendar, result: CalendarSyncResult,
                           window: SyncWindow,
                           report: CalendarSyncReport) -> None:
        calendar_id = result.calendar_id
        assert calendar_id is not None

        window_result = self._client.events(
            start_utc=window.start_utc, end_utc=window.end_utc,
            provider_calendar_ids=(bc.provider_calendar_id,))

        at = self._now()
        with UnitOfWork(self._factory) as uow:
            events = EventRepository(uow)
            windows = SyncWindowRepository(uow)

            previous = windows.get(calendar_id)
            # Das Fenster gilt als unveraendert, wenn das zuletzt vollstaendig
            # beobachtete Fenster das jetzige abdeckt. Ein VERGROESSERTES
            # Fenster ist ein Import ohne Loeschableitung: ueber den neuen Rand
            # ist nichts bekannt. Ein VERKLEINERTES erzeugt ebenfalls keine
            # Tombstones — was herausfaellt, ist nicht geloescht.
            window_unchanged = window_covers(previous, window)
            if previous is not None and not window.equals(previous):
                report.window_changed = True

            seen_ids: list[str] = []
            for be in window_result.events:
                if not be.provider_event_id:
                    # Ohne Providerkennung ist der Termin nicht bindbar. Er
                    # wird uebergangen statt unter einer erfundenen Kennung
                    # gespeichert.
                    continue
                canonical = _to_canonical_event(be, calendar_id)
                _, outcome = events.upsert_seen(
                    canonical, self._provider_account_id, at)
                seen_ids.append(be.provider_event_id)
                result.events_seen += 1
                if outcome == "created":
                    result.created += 1
                elif outcome == "updated":
                    result.updated += 1
                else:
                    result.unchanged += 1

            result.complete = window_result.complete
            # Die drei Bedingungen aus Regel 3 stehen hier als EINE Bedingung.
            result.deletions_derivable = window_result.complete and window_unchanged
            if result.deletions_derivable:
                result.tombstoned = events.tombstone_absent_in_window(
                    provider_account_id=self._provider_account_id,
                    provider_calendar_id=bc.provider_calendar_id,
                    calendar_id=calendar_id, window=window,
                    seen_provider_ids=seen_ids, at=at)

            # Nur ein VOLLSTAENDIGER Lauf darf das beobachtete Fenster
            # fortschreiben. Sonst behauptete der naechste Lauf eine
            # Beobachtung, die nie stattgefunden hat.
            if window_result.complete:
                windows.record_complete_run(calendar_id, window, at,
                                            result.events_seen)

    def _record_run(self, report: CalendarSyncReport) -> None:
        """Protokolliert den Lauf — mit Fenster, sonst wäre er wertlos."""
        with UnitOfWork(self._factory) as uow:
            uow.execute(
                "INSERT INTO calendar_sync_runs (id, provider_account_id, "
                "started_at, finished_at, window_start_utc, window_end_utc, "
                "calendars_total, calendars_complete, events_seen, events_created, "
                "events_updated, events_unchanged, events_tombstoned, "
                "window_changed, outcome) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (report.run_id, self._provider_account_id, report.started_at,
                 report.finished_at, report.window.start_utc,
                 report.window.end_utc, report.calendars_total,
                 report.calendars_complete, report.events_seen, report.created,
                 report.updated, report.unchanged, report.tombstoned,
                 1 if report.window_changed else 0, report.outcome),
            )
