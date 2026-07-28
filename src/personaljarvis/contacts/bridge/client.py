"""Typisierter Client der Native-Bridge.

Grenzen dieses Moduls:

* **Keine Apple-Typen** in der Python-Domäne (AV-4) — der Client liefert
  ausschließlich die DTOs aus `models.py`.
* **Keine Normalisierung, kein Anzeigename, kein Hashing** — das bleibt im
  Kern (ADR-0016 Punkt 4).
* **Kein Sidecar-Start beim Import oder im Konstruktor.** Der Prozess startet
  erst bei einem ausdrücklichen `start()`.
* **Keine Mutationsausführung.** `create`/`update`/`delete` sind vertraglich
  definiert und liefern bis Gate C `not_implemented`.
* `requestAuthorization` erfolgt **nur** auf ausdrückliche Nutzeraktion und
  niemals automatisch beim Start (Plan §8).
"""

from __future__ import annotations

from typing import Any

from personaljarvis.contacts.bridge import protocol
from personaljarvis.contacts.bridge.errors import (
    BridgeCapabilityMismatch,
    BridgeOperationError,
    BridgeProtocolError,
)
from personaljarvis.contacts.bridge.models import (
    AuthorizationStatus,
    BridgeCapabilities,
    BridgeContact,
    ChangeEvent,
    ChangesResult,
    ContainerInfo,
    EnumerationResult,
    Handshake,
)
from personaljarvis.contacts.bridge.process import SidecarProcess

__all__ = ["ContactsBridgeClient"]


class ContactsBridgeClient:
    """Lesende Verträge gegen den Sidecar."""

    def __init__(self, process: SidecarProcess) -> None:
        self._process = process

    # ── Lebenszyklus ────────────────────────────────────────────────────────
    def start(self) -> Handshake:
        return self._process.start()

    def stop(self) -> None:
        self._process.stop()

    @property
    def handshake(self) -> Handshake | None:
        return self._process.handshake

    @property
    def capabilities(self) -> BridgeCapabilities:
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

    # ── Kontaktfreie Operationen ────────────────────────────────────────────
    def ping(self) -> bool:
        return bool(self._call(protocol.Operation.PING).get("pong"))

    def caps(self) -> Handshake:
        return Handshake.parse(self._call(protocol.Operation.CAPS))

    def authorization_status(self) -> AuthorizationStatus:
        """Liest den Status. Löst **keinen** Dialog aus."""
        raw = self._call(protocol.Operation.AUTHORIZATION_STATUS)
        return AuthorizationStatus.parse(str(raw.get("authorizationStatus", "unknown")))

    # ── Autorisierung (nur auf ausdrückliche Nutzeraktion) ──────────────────
    def request_authorization(self, *, user_initiated: bool) -> tuple[bool, AuthorizationStatus]:
        """Fordert die Kontakte-Autorisierung an.

        `user_initiated=True` ist Pflicht und bildet die ausdrückliche
        Nutzeraktion ab (Plan §8). Es gibt keinen automatischen Weg.
        """
        if not user_initiated:
            raise BridgeProtocolError(
                "requestAuthorization verlangt eine ausdrueckliche Nutzeraktion"
            )
        raw = self._call(protocol.Operation.REQUEST_AUTHORIZATION,
                         {"request": True}, timeout=180.0)
        return (bool(raw.get("granted")),
                AuthorizationStatus.parse(str(raw.get("authorizationStatus", "unknown"))))

    # ── Lesende Store-Operationen ───────────────────────────────────────────
    def containers(self) -> tuple[ContainerInfo, ...]:
        raw = self._call(protocol.Operation.CONTAINERS)
        return tuple(ContainerInfo.parse(c) for c in raw.get("containers", []))

    def enumerate(self, *, container_identifier: str | None = None,
                  timeout: float = 300.0) -> EnumerationResult:
        """Vollständige Enumeration.

        **Ohne `complete=True` ist das Ergebnis ungültig** und darf nie als
        Löschmenge dienen (Plan §6.1). Der Aufrufer muss das prüfen; das DTO
        macht es über `usable_as_delete_basis` explizit.
        """
        payload = ({"containerIdentifier": container_identifier}
                   if container_identifier else {})
        raw = self._call(protocol.Operation.ENUMERATE, payload, timeout=timeout)
        items = raw.get("items", [])
        return EnumerationResult(
            contacts=tuple(BridgeContact.parse(i) for i in items),
            count=int(raw.get("count", 0)),
            complete=bool(raw.get("complete", False)),
            key_set_version=int(raw.get("keySetVersion", -1)),
        )

    def changes(self, *, starting_token: str | None = None) -> ChangesResult:
        """Delta-Lauf. Der neue Cursor stammt **aus dieser Antwort**."""
        self._require_capability("changeHistory",
                                 self.capabilities.change_history_supported)
        payload = {"startingToken": starting_token} if starting_token else {}
        raw = self._call(protocol.Operation.CHANGES, payload)
        return ChangesResult(
            events=tuple(ChangeEvent.parse(e) for e in raw.get("events", [])),
            current_token=str(raw.get("currentToken", "")),
            key_set_version=int(raw.get("keySetVersion", -1)),
        )

    def get(self, provider_identifier: str) -> BridgeContact:
        raw = self._call(protocol.Operation.GET,
                         {"providerIdentifier": provider_identifier})
        return BridgeContact.parse(raw["contact"])

    def get_unified_read_only(self, provider_identifier: str) -> BridgeContact:
        """Ausschließlich lesend — der `unified_identifier` ist nie Schreibziel."""
        raw = self._call(protocol.Operation.GET_UNIFIED_READ_ONLY,
                         {"providerIdentifier": provider_identifier})
        contact = BridgeContact.parse(raw["contact"])
        return contact

    # ── Mutationen: bis Gate C nicht implementiert ──────────────────────────
    def create(self, **_: Any) -> None:
        raise NotImplementedError(
            "Mutationen entstehen in Gate C ueber den ApplicationCommandBus "
            "(AV-35) — nie direkt ueber den Bridge-Client."
        )

    update = create
    delete = create
