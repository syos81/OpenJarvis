"""HTTP-Verträge des Kalendermoduls unter `/v1/personal/calendar`.

**Was diese Routen strukturell nicht können:**

* Keine Route schreibt in den Provider. v1 kennt keine Mutation — es gibt hier
  keinen Endpunkt, der einen Termin anlegen, ändern oder löschen könnte.
* Keine Route fragt selbsttätig eine Berechtigung an. Der TCC-Dialog läuft
  ausschliesslich über `POST …/authorization`, und nur mit ausdrücklicher
  Bestätigung im Rumpf.
* Keine Route startet einen Hintergrundlauf. Ein Sync ist eine Handlung.

**Sicherheitsgrenzen:** Alle Routen liegen unter `/v1/` und erben damit die
Upstream-`AuthMiddleware` (Bearer, 09 §1). Eingaben sind `extra="forbid"`-
validiert, und kein Fehlertext trägt einen Termininhalt: Titel, Ort, Notiz und
Teilnehmer erscheinen **nie** in einer Fehlermeldung.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from personaljarvis.base.db.unit_of_work import UnitOfWork
from personaljarvis.base.sidecar.errors import BridgeError
from personaljarvis.calendar.domain import (
    DEFAULT_WINDOW_FUTURE_DAYS,
    DEFAULT_WINDOW_PAST_DAYS,
    SyncWindow,
)
from personaljarvis.calendar.lifecycle import CalendarModule
from personaljarvis.calendar.repositories import (
    CalendarRepository,
    EventRepository,
)

__all__ = ["create_calendar_router"]


class AuthorizationRequest(BaseModel):
    """Die ausdrückliche Nutzeraktion. Ohne sie gibt es keinen Dialog."""

    model_config = ConfigDict(extra="forbid")
    user_initiated: bool = Field(
        description="Muss true sein. Bildet die ausdrückliche Nutzeraktion ab.")


class SyncRequest(BaseModel):
    """Ein Lauf mit **explizitem** Fenster.

    Die Vorgabewerte sind der Startcache aus der Baseline, keine dauerhafte
    Produktgrenze: die Oberfläche darf das Fenster beim Navigieren erweitern.
    """

    model_config = ConfigDict(extra="forbid")
    past_days: int = Field(default=DEFAULT_WINDOW_PAST_DAYS, ge=0, le=3650)
    future_days: int = Field(default=DEFAULT_WINDOW_FUTURE_DAYS, ge=1, le=3650)


def _window(past_days: int, future_days: int) -> SyncWindow:
    return SyncWindow.around(datetime.now(timezone.utc),
                             past_days=past_days, future_days=future_days)


def create_calendar_router(module: CalendarModule) -> APIRouter:
    router = APIRouter(prefix="/v1/personal/calendar", tags=["personal-calendar"])

    @router.get("/status")
    def status() -> dict[str, Any]:
        """Was das Modul über sich sagen kann, **ohne** den Provider zu fragen.

        Bewusst der zuletzt bekannte Bridge-Status: ein Statusaufruf soll
        keinen Prozess starten. Wer den aktuellen Stand will, ruft
        `POST /bridge/check`.
        """
        s = module.bridge_status
        return {
            "bridge_available": s.available,
            "authorization_status": s.authorization_status.value,
            "can_read": s.authorization_status.can_read,
            "capabilities": {
                "can_read": s.capabilities.can_read,
                "can_create_events": s.capabilities.can_create_events,
                "can_update_events": s.capabilities.can_update_events,
                "can_delete_events": s.capabilities.can_delete_events,
                "supports_recurrence": s.capabilities.supports_recurrence,
                "supports_attendees": s.capabilities.supports_attendees,
                "supports_alarms": s.capabilities.supports_alarms,
                "supports_time_zones": s.capabilities.supports_time_zones,
                "window_required": s.capabilities.window_required,
                "change_feed": s.capabilities.change_feed,
            },
            "detail": s.detail,
            "default_window": {
                "past_days": DEFAULT_WINDOW_PAST_DAYS,
                "future_days": DEFAULT_WINDOW_FUTURE_DAYS,
            },
        }

    @router.post("/bridge/check")
    def check_bridge() -> dict[str, Any]:
        """Kalenderfreier Handshake. Liest **keinen** Kalender."""
        s = module.check_bridge()
        return {"bridge_available": s.available,
                "authorization_status": s.authorization_status.value,
                "detail": s.detail}

    @router.post("/authorization")
    def request_authorization(body: AuthorizationRequest) -> dict[str, Any]:
        """Fordert die Kalenderberechtigung an — nur auf Nutzeraktion.

        `prompt_attempted=false` heisst: der Status war bereits entschieden und
        macOS zeigt keinen Dialog mehr. Das wird ehrlich gemeldet, statt einen
        Versuch zu behaupten, den es nicht gab.
        """
        if not body.user_initiated:
            raise HTTPException(
                status_code=400,
                detail="Die Berechtigung wird nur auf ausdrueckliche "
                       "Nutzeraktion angefragt.")
        client = None
        try:
            client = module.open_client()
            granted, status, attempted = client.request_authorization(
                user_initiated=True)
        except BridgeError as exc:
            raise HTTPException(status_code=503,
                                detail=f"Bridge nicht verfuegbar: "
                                       f"{exc.__class__.__name__}") from None
        finally:
            if client is not None:
                client.stop()
        return {"granted": granted, "authorization_status": status.value,
                "prompt_attempted": attempted}

    @router.get("/calendars")
    def list_calendars() -> dict[str, Any]:
        """Der gespeicherte Kalenderbestand. Reine Projektion, kein Provider."""
        with UnitOfWork(module.connection_factory) as uow:
            calendars = CalendarRepository(uow).list_active(module.workspace_id)
        return {"calendars": list(calendars), "count": len(calendars)}

    @router.get("/events")
    def list_events(
        start_utc: str = Query(description="ISO-8601 UTC, inklusiv"),
        end_utc: str = Query(description="ISO-8601 UTC, exklusiv"),
        calendar_ids: list[str] | None = Query(default=None),
        limit: int = Query(default=2000, ge=1, le=20000),
    ) -> dict[str, Any]:
        """Termine eines Fensters aus dem **gespeicherten** Bestand.

        Das angefragte Fenster wird in der Antwort wiederholt. Die Oberfläche
        muss zeigen können, welchen Zeitraum sie kennt — ein Kalender, der so
        tut, als kenne er alles, lügt.
        """
        try:
            window = SyncWindow(start_utc=start_utc, end_utc=end_utc)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from None
        with UnitOfWork(module.connection_factory) as uow:
            events = EventRepository(uow).list_window(
                module.workspace_id, window,
                calendar_ids=tuple(calendar_ids) if calendar_ids else None,
                limit=limit)
        return {
            "events": list(events),
            "count": len(events),
            "window": {"start_utc": window.start_utc, "end_utc": window.end_utc},
            # Ehrlichkeit vor Schoenheit: klebt der Bestand am Limit, KANN
            # etwas fehlen — dann darf die Ansicht keine Vollstaendigkeit
            # behaupten.
            "truncated": len(events) >= limit,
        }

    @router.post("/sync")
    def sync(body: SyncRequest) -> dict[str, Any]:
        """Ein Lauf. Startet nie von selbst und wiederholt sich nie von selbst."""
        window = _window(body.past_days, body.future_days)
        client = None
        try:
            client = module.open_client()
            report = module.sync_service(client).run(window)
        except BridgeError as exc:
            raise HTTPException(status_code=503,
                                detail=f"Bridge nicht verfuegbar: "
                                       f"{exc.__class__.__name__}") from None
        finally:
            if client is not None:
                client.stop()
        return {
            "run_id": report.run_id,
            "outcome": report.outcome,
            "window": {"start_utc": report.window.start_utc,
                       "end_utc": report.window.end_utc},
            "window_changed": report.window_changed,
            "calendars_total": report.calendars_total,
            "calendars_complete": report.calendars_complete,
            "events_seen": report.events_seen,
            "created": report.created,
            "updated": report.updated,
            "unchanged": report.unchanged,
            "tombstoned": report.tombstoned,
            "calendars": [
                {"provider_calendar_id": r.provider_calendar_id,
                 "complete": r.complete,
                 "deletions_derivable": r.deletions_derivable,
                 "events_seen": r.events_seen,
                 "created": r.created, "updated": r.updated,
                 "unchanged": r.unchanged, "tombstoned": r.tombstoned,
                 "error": r.error}
                for r in report.results
            ],
            "error": report.error,
        }

    return router
