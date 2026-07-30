"""Ausdrücklich benutzergesteuerte Live-Operationen gegen Apple Contacts.

Dies ist der **einzige** Ort im Produktcode, an dem ein Sidecar-Prozess für
einen Store-Zugriff startet. Alles hier ist ausschließlich lesend.

Verbindliche Eigenschaften:

* **Kein Start-Sync, keine Hintergrundschleife, kein Timer.** Jede Methode
  läuft genau einmal je ausdrücklichem Aufruf und kehrt zurück.
* **Kein automatischer Autorisierungsdialog.** `authorization_status()` liest
  nur; `request_authorization()` verlangt `user_initiated=True` und wird
  ausschließlich von einer Nutzeraktion aufgerufen.
* **Kein Schreibpfad.** Der Client kennt `create`/`update`/`delete` nur als
  `NotImplementedError`, und der Sidecar enthält kein `CNSaveRequest`.
* **Der Sidecar wird immer beendet** — auch auf jedem Fehlerpfad.
* **Keine PII nach aussen.** Alle Rückgaben sind aggregiert; Fehlertexte
  tragen die Fehlerklasse, nie einen Kontaktwert und nie einen Cursor.

Zur Prozesssperre: sie wird hier **nicht erneut erworben**, sondern
vorausgesetzt. Der Bootstrap hält sie über die gesamte Serverlaufzeit
(`PersonalBootstrap.start()`); erreicht eine Anfrage diese Schicht, ist damit
bereits bewiesen, dass kein zweiter Prozess auf dieselbe Datenbank schreibt.
Ein zweiter Erwerb im selben Prozess würde nichts zusätzlich absichern und
könnte sich nur selbst blockieren. Der Riegel hier schützt gegen etwas
anderes: zwei gleichzeitige Läufe **innerhalb** desselben Prozesses.
"""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass
from datetime import UTC, datetime

from personaljarvis.contacts.bridge.client import ContactsBridgeClient
from personaljarvis.contacts.bridge.errors import (
    BridgeConfigurationError,
    BridgeError,
    BridgeOperationError,
)
from personaljarvis.contacts.bridge.models import AuthorizationStatus
from personaljarvis.contacts.bridge.process import SidecarProcess
from personaljarvis.contacts.bridge.resolver import resolve_sidecar
from personaljarvis.contacts.sync.errors import SyncError
from personaljarvis.contacts.sync.state import CursorState, SyncRunKind

__all__ = [
    "AuthorizationView",
    "ContactsLiveService",
    "SyncBusy",
    "SyncNotAuthorized",
    "SyncRunView",
    "SyncUnavailable",
]

#: Kontenschlüssel des Apple-Systemkontos. Ein Konto je Anbieter genügt für
#: den Lesepfad; Mehrkontenbetrieb ist eine spätere, eigene Entscheidung.
APPLE_PROVIDER_ACCOUNT = "apple-local"

#: Pfad der .app, aus deren Prozesskette dieses Backend stammt. Wird
#: ausschliesslich vom Tauri-Hauptprozess beim Start gesetzt.
HOST_BUNDLE_ENV = "PERSONAL_JARVIS_HOST_BUNDLE"


def host_bundle() -> str:
    """Die .app, der macOS eine Berechtigungsanfrage zurechnen wuerde.

    Leer, wenn das Backend nicht von der App gestartet wurde — etwa aus einem
    Terminal. Dann ist der *verantwortliche Prozess* im Sinne von TCC nicht
    die App, sondern das Terminal: es traegt keine
    `NSContactsUsageDescription` und kann keinen Dialog anzeigen.
    """
    return os.environ.get(HOST_BUNDLE_ENV, "").strip()


#: Übersetzung der Bridge-Fehlerantwort in den stabilen Live-Vertrag.
#:
#: Der Sidecar liefert einen Code aus geschlossener Menge plus — bei einem
#: Providerfehler — Apple-Domain und numerischen Code. Beides wurde bisher
#: verworfen; übrig blieb der Ausnahmeklassenname. Diese Abbildung hält die
#: Diagnose fest, ohne je einen Freitext des Systems zu übernehmen.
_BRIDGE_CODE_ZU_VERTRAG: dict[str, str] = {
    "provider_error": "tcc_request_rejected",
    "tcc_denied": "tcc_denied",
    "invalid_request": "bridge_response_invalid",
    "protocol_mismatch": "bridge_response_invalid",
    "invalid_token": "bridge_response_invalid",
    "not_implemented": "operation_not_implemented",
    "unsupported": "operation_not_supported",
}


def technischer_code(schritt: str, exc: Exception) -> str:
    """Stabile, PII-freie Kennung eines gescheiterten Bridge-Schritts.

    Aufbau: ``<schritt>:<vertragscode>[:<domain>/<code>]`` — zum Beispiel
    ``authorization_request:tcc_request_rejected:CNErrorDomain/100``.

    Der Klassenname der Ausnahme ist ausdrücklich **nicht** Teil der Kennung,
    solange der Sidecar etwas Besseres geliefert hat: eine Apple-Fehlerdomain
    sagt, *was* das System abgelehnt hat, ein Python-Klassenname sagt nur,
    *wo* der Fehler durchgereicht wurde.
    """
    if isinstance(exc, BridgeOperationError):
        vertrag = _BRIDGE_CODE_ZU_VERTRAG.get(exc.code, exc.code)
        if exc.provider_domain == "timeout":
            return f"{schritt}:request_timeout"
        detail = exc.provider_detail
        return f"{schritt}:{vertrag}" + (f":{detail}" if detail else "")
    # Kein typisierter Bridge-Fehler: der Prozess selbst gab auf. Hier ist der
    # Klassenname die beste verfügbare Angabe.
    return f"{schritt}:{type(exc).__name__}"


class LiveError(Exception):
    """Basisklasse — trägt nie einen Kontaktwert.

    Ein Live-Fehler besteht aus **zwei getrennten Angaben**, und die
    Trennung ist der ganze Punkt:

    * ``str(exc)`` ist ein Satz für den Menschen vor dem Bildschirm. Er sagt,
      was nicht ging und was jetzt hilft.
    * ``technical_code`` ist eine stabile Vertragskennung aus geschlossener
      Menge, mit der sich ein Fehlerbild wiederfinden lässt.

    Vorher stand in ``str(exc)`` der Klassenname der auslösenden Ausnahme.
    Die Oberfläche zeigte dann wörtlich ``BridgeOperationError`` — eine
    Zeichenkette, die dem Nutzer nichts sagt, keinen Hinweis auf
    Wiederholbarkeit gibt und nicht einmal verrät, welcher Schritt scheiterte.
    Ein Klassenname ist eine Implementierungsinterna und gehört nie in eine
    Nutzermeldung.
    """

    #: Grobe HTTP-nahe Kategorie; wird in `routes.py` auf den Status abgebildet.
    code = "internal"
    retryable = False

    def __init__(self, message: str, *, technical_code: str = "") -> None:
        super().__init__(message)
        #: Stabil, maschinenlesbar, PII-frei. Nie ein Pfad, nie ein Wert.
        self.technical_code = technical_code or type(self).__name__


class SyncBusy(LiveError):
    """Für diesen Workspace läuft bereits ein Lauf."""

    code = "conflict"
    retryable = True


class SyncNotAuthorized(LiveError):
    """Ohne erteilte Berechtigung wird der Store nicht einmal geöffnet."""

    code = "forbidden"


class SyncUnavailable(LiveError):
    """Sidecar nicht auflösbar, nicht startbar oder Protokoll unbrauchbar."""

    code = "unavailable"
    retryable = True


@dataclass(frozen=True)
class AuthorizationView:
    """Autorisierungszustand — geraten wird nie."""

    status: str
    can_request: bool
    bridge_available: bool
    #: Satz für den Menschen. Nie ein Klassenname, nie ein Pfad.
    reason: str = ""
    #: Stabile Vertragskennung für die Fehlersuche. Leer, wenn alles ging.
    technical_code: str = ""

    @property
    def authorized(self) -> bool:
        return self.status == AuthorizationStatus.AUTHORIZED.value


@dataclass(frozen=True)
class SyncRunView:
    """Ergebnis eines Laufs — aggregiert, PII-frei, ohne Cursorwert."""

    mode: str
    succeeded: bool
    containers: int = 0
    read: int = 0
    imported: int = 0
    updated: int = 0
    tombstoned: int = 0
    unchanged: int = 0
    events_processed: int = 0
    cursor_present: bool = False
    cursor_advanced: bool = False
    requires_full_diff: bool = False
    error_class: str | None = None
    retryable: bool = False
    detail: str = ""
    completed_at: str = ""


class ContactsLiveService:
    """Autorisierung und manueller Lese-Sync — jeweils genau auf Zuruf."""

    #: Ein Lauf je Workspace. Der Riegel liegt im Prozess; die Prozesssperre
    #: des Bootstraps verhindert bereits einen zweiten Schreiber im System.
    _riegel: dict[str, threading.Lock] = {}
    _riegel_guard = threading.Lock()

    def __init__(self, module, *, provider_account_id: str = APPLE_PROVIDER_ACCOUNT,
                 sidecar_path=None, bundle_dir=None) -> None:
        self._module = module
        self._provider_account_id = provider_account_id
        self._sidecar_path = sidecar_path
        self._bundle_dir = bundle_dir

    # ── Sidecar-Lebenszyklus ────────────────────────────────────────────────
    def _client(self) -> tuple[ContactsBridgeClient, SidecarProcess]:
        """Löst auf und startet — der Aufrufer beendet **immer** im finally."""
        try:
            location = resolve_sidecar(self._sidecar_path,
                                       bundle_dir=self._bundle_dir)
        except BridgeConfigurationError as exc:
            # `str(exc)` des Resolvers nennt Suchpfade — die gehoeren nicht in
            # eine Nutzermeldung. Die Ursache steht im technischen Code.
            raise SyncUnavailable(
                "Die Kontakte-Bruecke wurde nicht gefunden. Die Anwendung "
                "wurde vermutlich unvollstaendig gepackt.",
                technical_code="bridge_not_found") from exc
        process = SidecarProcess(location)
        client = ContactsBridgeClient(process)
        try:
            client.start()
        except BridgeError as exc:
            process.stop()
            raise SyncUnavailable(
                "Die Kontakte-Bruecke liess sich nicht starten. Ein erneuter "
                "Versuch ist sinnvoll; bleibt es dabei, hilft ein Neustart "
                "der Anwendung.",
                technical_code=technischer_code("bridge_start", exc),
            ) from exc
        return client, process

    # ── Autorisierung ───────────────────────────────────────────────────────
    def authorization(self) -> AuthorizationView:
        """Liest den Status. Löst **keinen** Dialog aus.

        `authorizationStatus` gehört zu den kontaktfreien Operationen — es
        wird kein Kontakt gelesen und keine Berechtigung angefordert.
        """
        try:
            client, process = self._client()
        except SyncUnavailable as exc:
            return AuthorizationView(
                status="unknown", can_request=False, bridge_available=False,
                reason=str(exc), technical_code=exc.technical_code)
        try:
            status = client.authorization_status()
        except BridgeError as exc:
            return AuthorizationView(
                status="unknown", can_request=False, bridge_available=True,
                reason="Der Berechtigungsstatus konnte nicht gelesen werden. "
                       "Er wird nicht geraten.",
                technical_code=technischer_code("status_read", exc))
        finally:
            process.stop()
        return AuthorizationView(
            status=status.value,
            # Nur aus `notDetermined` heraus ist ein Dialog überhaupt möglich.
            # `denied` und `restricted` ändert nur der Nutzer in den
            # Systemeinstellungen — ein erneuter Aufruf wäre wirkungslos.
            can_request=status == AuthorizationStatus.NOT_DETERMINED,
            bridge_available=True)

    def request_authorization(self, *, user_initiated: bool) -> AuthorizationView:
        """Fordert die Berechtigung an — ausschließlich auf Nutzeraktion.

        Es gibt keinen automatischen Wiederholungsversuch: lehnt der Nutzer
        ab, bleibt es dabei, bis er es selbst in den Systemeinstellungen
        ändert.
        """
        if not user_initiated:
            raise SyncNotAuthorized(
                "Die Berechtigung wird nur auf eine ausdrueckliche "
                "Nutzeraktion hin angefordert.",
                technical_code="user_action_required")

        # Der Server fordert die Berechtigung **nicht mehr an**.
        #
        # Belegt auf arm64: macOS rechnet einen TCC-Dialog dem verantwortlichen
        # Prozess zu. Der Sidecar wird ueber `uv` und `python` erreicht — beides
        # CLI-Binaries ohne App-Bundle. `requestAccess` kam von dort mit
        # `CNErrorDomain/100` zurueck, ohne dass je ein Dialog erschien, und der
        # Status blieb `notDetermined`: eine technische Ablehnung vor dem
        # Dialog, keine Nutzerentscheidung.
        #
        # Der Dialog kommt jetzt aus dem Tauri-Hauptprozess, der die App *ist*.
        # Diese Methode bleibt als Vertragsgrenze bestehen und sagt klar, wohin
        # die Anfrage gehoert — statt einen Weg offenzuhalten, der nachweislich
        # nicht funktioniert.
        #
        # `authorizationStatus` bleibt unberuehrt beim Sidecar: es fragt nichts
        # an und braucht keinen verantwortlichen Prozess. Ebenso alle spaeteren
        # Leseoperationen.
        raise SyncUnavailable(
            "Der Berechtigungsdialog wird von der Anwendung selbst "
            "angefordert, nicht vom Server.",
            technical_code="tcc_prompt_unavailable:handled_by_app")

    # ── Manueller Lese-Sync ─────────────────────────────────────────────────
    def _lock_for(self, workspace_id: str) -> threading.Lock:
        with self._riegel_guard:
            return self._riegel.setdefault(workspace_id, threading.Lock())

    def is_running(self, workspace_id: str) -> bool:
        return self._lock_for(workspace_id).locked()

    def sync(self, *, workspace_id: str) -> SyncRunView:
        """Ein vollständiger, ausschließlich lesender Lauf.

        Reihenfolge (Plan §5): Riegel → Autorisierung → Sidecar → Dienst über
        den Lebenszyklus → Lauf je Container → Sidecar beenden.

        Ohne erteilte Berechtigung wird **keine** Store-Operation gesendet —
        auch kein `containers`.
        """
        riegel = self._lock_for(workspace_id)
        if not riegel.acquire(blocking=False):
            raise SyncBusy(
                "Fuer diesen Arbeitsbereich laeuft bereits ein Abgleich. "
                "Warte, bis er fertig ist.",
                technical_code="sync_already_running")
        try:
            return self._sync_unter_riegel(workspace_id)
        finally:
            riegel.release()

    def _sync_unter_riegel(self, workspace_id: str) -> SyncRunView:
        client, process = self._client()
        try:
            status = client.authorization_status()
            if status != AuthorizationStatus.AUTHORIZED:
                # Abbruch **vor** jeder Leseoperation. Der Status ist gelesen,
                # nicht geraten, und kein Container wurde abgefragt.
                raise SyncNotAuthorized(
                    "Ohne erteilte Berechtigung werden keine Kontakte "
                    "gelesen.",
                    technical_code=f"not_authorized:{status.value}")

            dienst = self._module.sync_service(
                client, workspace_id=workspace_id,
                provider_account_id=self._provider_account_id)

            container = dienst.inventory_containers()
            gesamt = _Summe()
            for eintrag in container:
                ergebnis = dienst.sync(eintrag.identifier)
                gesamt.add(ergebnis)
            return gesamt.view(len(container))
        except (BridgeError, SyncError) as exc:
            # Timeout, Protokollbruch, abgestürzter Sidecar: der Lauf endet
            # als Fehler mit Klasse, nie mit Inhalt. Der Sync-Dienst selbst
            # fängt seine Fehler bereits je Container ab — das hier greift
            # für `inventory_containers()` und alles Unerwartete davor.
            return SyncRunView(
                mode=SyncRunKind.DELTA.value, succeeded=False,
                error_class=type(exc).__name__, retryable=True,
                detail="Die Bruecke hat den Lauf nicht abgeschlossen.",
                completed_at=_jetzt())
        finally:
            # Der Sidecar geht auf **jedem** Pfad. Ein verwaister Kindprozess
            # haette Zugriff auf den Kontakte-Store, ohne dass die App laeuft.
            process.stop()


def _jetzt() -> str:
    return datetime.now(UTC).isoformat()


class _Summe:
    """Aggregiert mehrere Containerläufe zu einer Antwort."""

    def __init__(self) -> None:
        self.imported = self.updated = self.tombstoned = 0
        self.unchanged = self.events = 0
        self.kinds: list[str] = []
        self.ok = True
        self.cursor_present = False
        self.cursor_advanced = False
        self.requires_full_diff = False
        self.error_class: str | None = None

    def add(self, ergebnis) -> None:
        self.imported += ergebnis.imported
        self.updated += ergebnis.updated
        self.tombstoned += ergebnis.tombstoned
        self.unchanged += ergebnis.unchanged
        self.events += ergebnis.events_processed
        self.kinds.append(ergebnis.kind.value)
        self.ok = self.ok and ergebnis.succeeded
        self.cursor_present |= ergebnis.cursor_state == CursorState.ACTIVE
        self.cursor_advanced |= ergebnis.cursor_advanced
        self.requires_full_diff |= ergebnis.requires_full_diff
        if not ergebnis.succeeded and self.error_class is None:
            self.error_class = ergebnis.error_class

    def view(self, container: int) -> SyncRunView:
        # Der schwerste Modus gewinnt: ein Initialimport neben einem Delta
        # ist insgesamt ein Initialimport, sonst wäre die Anzeige zu optimistisch.
        rang = (SyncRunKind.INITIAL_IMPORT.value, SyncRunKind.FULL_DIFF.value,
                SyncRunKind.DELTA.value)
        modus = next((r for r in rang if r in self.kinds),
                     SyncRunKind.DELTA.value)
        return SyncRunView(
            mode=modus, succeeded=self.ok, containers=container,
            read=self.imported + self.updated + self.unchanged,
            imported=self.imported, updated=self.updated,
            tombstoned=self.tombstoned, unchanged=self.unchanged,
            events_processed=self.events,
            cursor_present=self.cursor_present,
            cursor_advanced=self.cursor_advanced,
            requires_full_diff=self.requires_full_diff,
            error_class=self.error_class,
            retryable=bool(self.error_class),
            detail="" if self.ok else "Mindestens ein Container schlug fehl.",
            completed_at=_jetzt())
