"""Typisierter Client der Kalender-Bridge.

Grenzen dieses Moduls:

* **Keine Apple-Typen** in der Python-Domäne (AV-4) — der Client liefert
  ausschließlich die DTOs aus `models.py`.
* **Keine Normalisierung, kein Felddigest, keine Zuordnung** — das bleibt im
  Kern (ADR-0016 Punkt 4).
* **Kein Sidecar-Start beim Import oder im Konstruktor.** Der Prozess startet
  erst bei einem ausdrücklichen `start()`.
* **Keine Mutationsoperation.** v1 liest; es gibt hier keine Methode, die
  schreiben könnte.
* `request_authorization` erfolgt **nur** auf ausdrückliche Nutzeraktion und
  niemals automatisch beim Start.
"""

from __future__ import annotations

from typing import Any

from personaljarvis.base.sidecar.errors import (
    BridgeCapabilityMismatch,
    BridgeOperationError,
    BridgeProtocolError,
)
from personaljarvis.calendar.bridge import protocol
from personaljarvis.calendar.bridge.models import (
    AuthorizationStatus,
    BridgeCalendar,
    BridgeEvent,
    CalendarCapabilities,
    CalendarHandshake,
    EventWindowResult,
)
from personaljarvis.calendar.bridge.process import CalendarSidecarProcess

__all__ = ["CalendarBridgeClient", "WINDOW_READ_TIMEOUT_SECONDS"]

#: Eigener Timeout für die Fensterlesung. Ein Fenster über ein Jahr kann in
#: einem grossen Bestand spürbar dauern; die 30-Sekunden-Vorgabe eines
#: Einzelaufrufs wäre dort ein Fehlalarm. Es wird trotzdem nichts wiederholt —
#: eine abgebrochene Lesung ist unvollständig und damit **keine** Löschmenge.
WINDOW_READ_TIMEOUT_SECONDS = 180.0


class CalendarBridgeClient:
    """Lesende Verträge gegen den Sidecar."""

    def __init__(self, process: CalendarSidecarProcess) -> None:
        self._process = process

    # ── Lebenszyklus ────────────────────────────────────────────────────────
    def start(self) -> CalendarHandshake:
        return self._process.start()

    def stop(self) -> None:
        self._process.stop()

    @property
    def handshake(self) -> CalendarHandshake | None:
        return self._process.handshake

    @property
    def capabilities(self) -> CalendarCapabilities:
        hs = self._process.handshake
        if hs is None:
            raise BridgeProtocolError("Bridge ist nicht gestartet")
        return hs.capabilities

    # ── Hilfsmittel ─────────────────────────────────────────────────────────
    def _call(self, operation: str, payload: dict[str, Any] | None = None,
              *, timeout: float | None = None) -> dict[str, Any]:
        kwargs: dict[str, Any] = {}
        if timeout is not None:
            kwargs["timeout"] = timeout
        envelope = self._process.request(operation, payload, **kwargs)
        if envelope.get("ok") is True:
            result = envelope.get("result")
            return result if isinstance(result, dict) else {}
        error = envelope.get("error") or {}
        raise BridgeOperationError(
            str(error.get("code", protocol.ErrorCode.INTERNAL)),
            str(error.get("message", "")),
            retryable=bool(error.get("retryable", False)),
        )

    def _require_capability(self, name: str, enabled: bool) -> None:
        if not enabled:
            raise BridgeCapabilityMismatch(
                f"Der Provider deklariert '{name}' als nicht verfuegbar"
            )

    # ── Kalenderfreie Operationen ───────────────────────────────────────────
    def ping(self) -> bool:
        return bool(self._call(protocol.Operation.PING).get("pong"))

    def caps(self) -> CalendarHandshake:
        return CalendarHandshake.parse(self._call(protocol.Operation.CAPS))

    def authorization_status(self) -> AuthorizationStatus:
        """Liest den Status. Löst **keinen** Dialog aus."""
        raw = self._call(protocol.Operation.AUTHORIZATION_STATUS)
        return AuthorizationStatus.parse(
            str(raw.get("authorizationStatus", "unknown")))

    # ── Autorisierung (nur auf ausdrückliche Nutzeraktion) ──────────────────
    def request_authorization(
        self, *, user_initiated: bool,
    ) -> tuple[bool, AuthorizationStatus, bool]:
        """Fordert die Kalender-Autorisierung an.

        `user_initiated=True` ist Pflicht und bildet die ausdrückliche
        Nutzeraktion ab. Es gibt keinen automatischen Weg.

        Liefert `(granted, status, prompt_attempted)`. `prompt_attempted` ist
        `False`, wenn der Status bereits entschieden war — macOS zeigt dann
        keinen Dialog mehr, und einen Versuch zu behaupten wäre gelogen.
        """
        if not user_initiated:
            raise BridgeProtocolError(
                "requestAuthorization verlangt eine ausdrueckliche Nutzeraktion"
            )
        raw = self._call(protocol.Operation.REQUEST_AUTHORIZATION,
                         {"request": True}, timeout=310.0)
        return (
            bool(raw.get("granted")),
            AuthorizationStatus.parse(str(raw.get("authorizationStatus", "unknown"))),
            bool(raw.get("promptAttempted", False)),
        )

    # ── Lesen ───────────────────────────────────────────────────────────────
    def calendars(self) -> tuple[BridgeCalendar, ...]:
        """Alle sichtbaren Kalender. Ändert nichts und wählt nichts aus."""
        self._require_capability("canRead", self.capabilities.can_read)
        raw = self._call(protocol.Operation.CALENDARS)
        return tuple(BridgeCalendar.parse(c)
                     for c in raw.get("calendars", []) if isinstance(c, dict))

    def events(self, *, start_utc: str, end_utc: str,
               provider_calendar_ids: tuple[str, ...] | None = None,
               timeout: float = WINDOW_READ_TIMEOUT_SECONDS) -> EventWindowResult:
        """Liest **ein** Fenster.

        Das Fenster ist Pflicht: EventKit kennt kein „alle Termine". Das
        Ergebnis führt es mit — ohne Fensterangabe liesse sich „nicht gesehen"
        nicht von „gelöscht" unterscheiden, und genau darauf stützt sich später
        die Tombstone-Regel.
        """
        self._require_capability("canRead", self.capabilities.can_read)
        payload: dict[str, Any] = {"startUtc": start_utc, "endUtc": end_utc}
        if provider_calendar_ids is not None:
            payload["calendarIdentifiers"] = list(provider_calendar_ids)
        raw = self._call(protocol.Operation.EVENTS, payload, timeout=timeout)
        items = raw.get("items", [])
        ids = raw.get("calendarIdentifiers")
        return EventWindowResult(
            events=tuple(BridgeEvent.parse(i) for i in items if isinstance(i, dict)),
            # Fail-closed: fehlt `complete`, gilt die Lesung als unvollständig.
            complete=bool(raw.get("complete", False)),
            window_start_utc=str(raw.get("windowStartUtc", start_utc)),
            window_end_utc=str(raw.get("windowEndUtc", end_utc)),
            provider_calendar_ids=(tuple(str(i) for i in ids)
                                   if isinstance(ids, list) else None),
        )
