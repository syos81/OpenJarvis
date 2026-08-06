"""Autorisierungsweg und manueller Lese-Sync — kontaktfrei.

**Kein echter Sidecar, kein Apple-Contacts-Store, kein TCC-Dialog.** Der
Bridge-Client wird durch eine Attrappe ersetzt, die jede Operation mitzählt.
Damit ist prüfbar, was sonst nur behauptet wäre: dass ohne erteilte
Berechtigung **keine einzige** Leseoperation den Store erreicht, und dass
keine Route je eine Schreiboperation auslöst.
"""

from __future__ import annotations

import threading
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from personaljarvis.contacts.api.routes import (
    DEFAULT_WORKSPACE_HEADER,
    PREFIX,
    create_contacts_router,
)
from personaljarvis.contacts.application.live import (
    ContactsLiveService,
    SyncBusy,
    SyncNotAuthorized,
    SyncUnavailable,
    technischer_code,
)
from personaljarvis.contacts.bridge.errors import (
    BridgeProcessError,
    BridgeProtocolError,
)
from personaljarvis.contacts.bridge.models import AuthorizationStatus, ContainerInfo
from personaljarvis.contacts.sync.state import CursorState, SyncRunKind, SyncRunResult

from .conftest import WORKSPACE

#: Die Live-Schicht als Datei — fuer den Quelltextnachweis weiter unten.
_REPO_LIVE = (Path(__file__).resolve().parents[3]
              / "src/personaljarvis/contacts/application/live.py")

#: Jede Operation, die den Kontakte-Store berührt. Kein Test dieser Datei darf
#: eine davon auslösen, solange nicht `authorized` gilt.
STORE_OPERATIONEN = ("containers", "enumerate", "changes", "get",
                     "getUnifiedReadOnly")
#: Operationen, die der Client weiterhin verweigert. `create` ist seit
#: ADR-0025 implementiert und gehoert deshalb nicht mehr hierher — Update und
#: Delete bleiben es (Phase M4 bzw. M5, Delete zusaetzlich hinter DEC-D06).
SCHREIB_OPERATIONEN = ("update", "delete")


class BridgeAttrappe:
    """Zählt jede Operation. Sie ist das Messinstrument dieser Suite."""

    def __init__(self, status=AuthorizationStatus.AUTHORIZED, *,
                 grant_to=None, raises=None, container=("con-1",)) -> None:
        self.status = status
        self.grant_to = grant_to
        self.raises = raises
        self._container = container
        self.ops: list[str] = []
        self.starts = 0
        self.stops = 0

    # Lebenszyklus
    def start(self):
        self.starts += 1
        return None

    def stop(self):
        self.stops += 1

    # Kontaktfreie Operationen
    def authorization_status(self):
        self.ops.append("authorizationStatus")
        return self.status

    def request_authorization(self, *, user_initiated: bool):
        assert user_initiated is True, "ohne Nutzeraktion darf es nie hierher"
        self.ops.append("requestAuthorization")
        if self.grant_to is not None:
            self.status = self.grant_to
        return (self.status == AuthorizationStatus.AUTHORIZED, self.status)

    # Store-Operationen
    def containers(self):
        self.ops.append("containers")
        if self.raises is not None:
            raise self.raises
        return tuple(ContainerInfo(identifier=c, name="", type="local")
                     for c in self._container)

    @property
    def store_beruehrt(self) -> bool:
        return any(o in STORE_OPERATIONEN for o in self.ops)


class LiveAttrappe(ContactsLiveService):
    """Echter Dienst, aber ohne Prozess: `_client` liefert die Attrappe."""

    def __init__(self, module, bridge: BridgeAttrappe, *,
                 unavailable: str | None = None) -> None:
        super().__init__(module)
        self.bridge = bridge
        self.unavailable = unavailable

    def _client(self):
        if self.unavailable:
            raise SyncUnavailable(self.unavailable)
        self.bridge.start()
        return self.bridge, self.bridge


def _lauf(kind=SyncRunKind.INITIAL_IMPORT, **kw) -> SyncRunResult:
    defaults = dict(
        kind=kind, succeeded=True, cursor_state=CursorState.ACTIVE,
        provider_account_id="apple-local", container_identifier="con-1",
        imported=3, unchanged=0, cursor_advanced=True)
    defaults.update(kw)
    return SyncRunResult(**defaults)


class SyncAttrappe:
    """Ersetzt den Sync-Dienst. Läuft nie gegen einen echten Store."""

    def __init__(self, ergebnisse=None, *, offen=()) -> None:
        self.ergebnisse = list(ergebnisse or [_lauf()])
        self.calls = 0
        #: Container, die einen Voll-Diff brauchen. Leer = Delta-Pfad.
        self.offen = tuple(offen)
        self.konto_laeufe: list[tuple[str, ...]] = []

    def inventory_containers(self):
        return (ContainerInfo(identifier="con-1", name="", type="local"),)

    def pending_full_diff(self, container_identifiers):
        return tuple(k for k in container_identifiers if k in self.offen)

    def full_diff_account(self, container_identifiers, *, confirm_empty=False):
        """Der kontoweite Pfad — der einzige, der loeschen darf."""
        self.konto_laeufe.append(tuple(container_identifiers))
        self.calls += 1
        return self.ergebnisse[min(self.calls - 1, len(self.ergebnisse) - 1)]

    def sync(self, container_identifier: str):
        self.calls += 1
        return self.ergebnisse[min(self.calls - 1, len(self.ergebnisse) - 1)]


@pytest.fixture
def kopf() -> dict:
    return {DEFAULT_WORKSPACE_HEADER: WORKSPACE}


@pytest.fixture
def in_der_app(monkeypatch):
    """Frueher: Prozesskette wie beim Start durch die gepackte App.

    Die Herkunft des Backends spielt fuer die Berechtigung keine Rolle mehr.
    Seit der Dialog im Tauri-Hauptprozess liegt, verweist der Server jeden
    Anfrageversuch unabhaengig von seiner Startumgebung auf die App. Die
    Fixture bleibt als Name an den Tests stehen, die den Fall benennen, und
    setzt bewusst **nichts** mehr — sie darf das Ergebnis nicht beeinflussen.
    """
    monkeypatch.delenv("PERSONAL_JARVIS_HOST_BUNDLE", raising=False)


@pytest.fixture
def ohne_app(monkeypatch):
    """Gegenstueck: ebenfalls ohne Umgebungsmarker, gleiches Ergebnis."""
    monkeypatch.delenv("PERSONAL_JARVIS_HOST_BUNDLE", raising=False)


def _client_mit(module, live) -> TestClient:
    module.live_service = live
    app = FastAPI()
    app.include_router(create_contacts_router(module))
    return TestClient(app)


# ═══ Autorisierung lesen ════════════════════════════════════════════════════
def test_status_lesen_beruehrt_den_store_nicht(module):
    bridge = BridgeAttrappe(AuthorizationStatus.NOT_DETERMINED)
    sicht = LiveAttrappe(module, bridge).authorization()
    assert sicht.status == "notDetermined"
    assert sicht.can_request is True
    assert bridge.ops == ["authorizationStatus"]
    assert not bridge.store_beruehrt


def test_status_lesen_fordert_nie_an(module):
    bridge = BridgeAttrappe(AuthorizationStatus.NOT_DETERMINED)
    LiveAttrappe(module, bridge).authorization()
    assert "requestAuthorization" not in bridge.ops


@pytest.mark.parametrize("status,anfragbar", [
    (AuthorizationStatus.NOT_DETERMINED, True),
    (AuthorizationStatus.DENIED, False),
    (AuthorizationStatus.RESTRICTED, False),
    (AuthorizationStatus.AUTHORIZED, False),
])
def test_anfragbarkeit_je_status(module, status, anfragbar):
    """`denied` und `restricted` ändert nur der Nutzer in den Einstellungen —
    ein Button dafür wäre eine Lüge."""
    sicht = LiveAttrappe(module, BridgeAttrappe(status)).authorization()
    assert sicht.status == status.value
    assert sicht.can_request is anfragbar


def test_status_wird_nie_geraten_wenn_die_bruecke_fehlt(module):
    sicht = LiveAttrappe(module, BridgeAttrappe(),
                         unavailable="kein Binary").authorization()
    assert sicht.status == "unknown"
    assert sicht.bridge_available is False
    assert sicht.can_request is False


def test_sidecar_wird_auch_beim_statuslesen_beendet(module):
    bridge = BridgeAttrappe()
    LiveAttrappe(module, bridge).authorization()
    assert bridge.starts == 1 and bridge.stops == 1


# ═══ Autorisierung anfordern ════════════════════════════════════════════════
def test_anfordern_verlangt_die_nutzeraktion(module):
    live = LiveAttrappe(module, BridgeAttrappe())
    with pytest.raises(SyncNotAuthorized):
        live.request_authorization(user_initiated=False)


def test_anfordern_ohne_nutzeraktion_sendet_nichts(module):
    bridge = BridgeAttrappe()
    live = LiveAttrappe(module, bridge)
    with pytest.raises(SyncNotAuthorized):
        live.request_authorization(user_initiated=False)
    assert bridge.ops == []
    assert bridge.starts == 0


def test_der_server_fordert_die_berechtigung_nicht_mehr_an(module, in_der_app):
    """Architekturgrenze: der Dialog kommt aus dem App-Prozess.

    Über den Sidecar war er nachweislich nicht zu bekommen — macOS rechnete
    die Anfrage einem Prozess ohne App-Bundle zu (`CNErrorDomain/100`, kein
    Dialog). Die Methode bleibt als Vertragsgrenze und sagt, wohin die
    Anfrage gehört, statt einen nicht funktionierenden Weg offenzuhalten.
    """
    bridge = BridgeAttrappe(AuthorizationStatus.NOT_DETERMINED)
    with pytest.raises(SyncUnavailable) as exc:
        LiveAttrappe(module, bridge).request_authorization(user_initiated=True)
    assert exc.value.technical_code == "tcc_prompt_unavailable:handled_by_app"
    assert bridge.ops == [], "kein requestAuthorization an den Sidecar"
    assert bridge.starts == 0, "der Sidecar startet dafür nicht mehr"


def test_kein_wiederholter_serveraufruf_erzeugt_prompt(module, in_der_app):
    """Auch mehrfaches Aufrufen bleibt wirkungslos — es gibt keinen Weg."""
    bridge = BridgeAttrappe(AuthorizationStatus.NOT_DETERMINED)
    live = LiveAttrappe(module, bridge)
    for _ in range(3):
        with pytest.raises(SyncUnavailable):
            live.request_authorization(user_initiated=True)
    assert bridge.ops == []


# ═══ Kein Sync ohne Berechtigung ════════════════════════════════════════════
@pytest.mark.parametrize("status", [
    AuthorizationStatus.NOT_DETERMINED,
    AuthorizationStatus.DENIED,
    AuthorizationStatus.RESTRICTED,
    AuthorizationStatus.UNKNOWN,
])
def test_ohne_berechtigung_wird_keine_leseoperation_gesendet(module, status):
    """Der schärfste Test dieser Datei: nicht einmal `containers`."""
    bridge = BridgeAttrappe(status)
    live = LiveAttrappe(module, bridge)
    with pytest.raises(SyncNotAuthorized):
        live.sync(workspace_id=WORKSPACE)
    assert bridge.ops == ["authorizationStatus"]
    assert not bridge.store_beruehrt
    assert bridge.stops == 1, "auch der abgebrochene Lauf beendet den Sidecar"


def test_ohne_berechtigung_bleibt_die_datenbank_unberuehrt(module):
    live = LiveAttrappe(module, BridgeAttrappe(AuthorizationStatus.DENIED))
    with pytest.raises(SyncNotAuthorized):
        live.sync(workspace_id=WORKSPACE)
    with module.unit_of_work() as uow:
        anzahl = uow.execute("SELECT count(*) AS n FROM contacts").fetchone()["n"]
    assert anzahl == 0


# ═══ Sync-Läufe ═════════════════════════════════════════════════════════════
def _live_mit_sync(module, bridge, sync):
    live = LiveAttrappe(module, bridge)
    module.sync_service = lambda *a, **k: sync
    return live


def test_initialimport(module):
    sync = SyncAttrappe([_lauf(SyncRunKind.INITIAL_IMPORT, imported=7)])
    lauf = _live_mit_sync(module, BridgeAttrappe(), sync).sync(
        workspace_id=WORKSPACE)
    assert lauf.succeeded and lauf.mode == "initial_import"
    assert lauf.imported == 7 and lauf.containers == 1


def test_full_diff(module):
    sync = SyncAttrappe([_lauf(SyncRunKind.FULL_DIFF, imported=1, tombstoned=2)])
    lauf = _live_mit_sync(module, BridgeAttrappe(), sync).sync(
        workspace_id=WORKSPACE)
    assert lauf.mode == "full_diff" and lauf.tombstoned == 2


def test_leerer_delta_lauf_ist_erfolg(module):
    """Nichts gefunden ist kein Fehler — sonst wäre der Normalfall rot."""
    sync = SyncAttrappe([_lauf(SyncRunKind.DELTA, imported=0, unchanged=0,
                               events_processed=0, cursor_advanced=True)])
    lauf = _live_mit_sync(module, BridgeAttrappe(), sync).sync(
        workspace_id=WORKSPACE)
    assert lauf.succeeded is True
    assert lauf.mode == "delta"
    assert lauf.imported == lauf.updated == lauf.tombstoned == 0
    assert lauf.error_class is None


def test_der_schwerere_modus_gewinnt(module):
    """Ein Initialimport neben einem Delta ist insgesamt ein Initialimport."""
    sync = SyncAttrappe([_lauf(SyncRunKind.DELTA), _lauf(SyncRunKind.INITIAL_IMPORT)])
    live = LiveAttrappe(module, BridgeAttrappe(container=("a", "b")))
    module.sync_service = lambda *a, **k: sync

    class ZweiContainer(SyncAttrappe):
        def inventory_containers(self):
            return (ContainerInfo("a", "", "local"), ContainerInfo("b", "", "local"))

    sync2 = ZweiContainer([_lauf(SyncRunKind.DELTA),
                           _lauf(SyncRunKind.INITIAL_IMPORT)])
    module.sync_service = lambda *a, **k: sync2
    lauf = live.sync(workspace_id=WORKSPACE)
    assert lauf.mode == "initial_import"
    assert lauf.containers == 2


def test_sidecar_geht_immer(module):
    bridge = BridgeAttrappe()
    _live_mit_sync(module, bridge, SyncAttrappe()).sync(workspace_id=WORKSPACE)
    assert bridge.starts == 1 and bridge.stops == 1


class SyncWirft(SyncAttrappe):
    """Der Containerabruf scheitert — das ist der Weg, auf dem ein
    Bridge-Fehler den Live-Dienst überhaupt erreicht: die Containerabfrage
    läuft über den Sync-Dienst, nicht über den Client."""

    def __init__(self, exc) -> None:
        super().__init__()
        self.exc = exc

    def inventory_containers(self):
        raise self.exc


def test_sidecar_geht_auch_bei_bridgefehler(module):
    bridge = BridgeAttrappe()
    lauf = _live_mit_sync(module, bridge,
                          SyncWirft(BridgeProtocolError("kaputt"))).sync(
        workspace_id=WORKSPACE)
    assert lauf.succeeded is False
    assert lauf.error_class == "BridgeProtocolError"
    assert lauf.retryable is True
    assert bridge.stops == 1


def test_bridgeabbruch_meldet_klasse_ohne_inhalt(module):
    from personaljarvis.contacts.bridge.errors import ProcessDiagnostics

    diag = ProcessDiagnostics(
        request_id=1, operation="containers", elapsed_seconds=0.1,
        child_exit_code=None, child_signal=9, child_alive=False,
        stdout_eof=True, stderr_eof=True)
    bridge = BridgeAttrappe()
    lauf = _live_mit_sync(
        module, bridge,
        SyncWirft(BridgeProcessError("Sidecar starb", diag))).sync(
        workspace_id=WORKSPACE)
    assert lauf.succeeded is False
    assert lauf.error_class == "BridgeProcessError"
    assert "Sidecar starb" not in lauf.detail
    assert bridge.stops == 1


def test_sync_timeout_endet_als_wiederholbarer_fehler(module):
    """Ein Zeitüberlauf ist kein leerer Lauf — sonst würde die Oberfläche
    einen erfolgreichen Abgleich melden, der nie stattfand."""
    from personaljarvis.contacts.bridge.errors import ProcessDiagnostics

    diag = ProcessDiagnostics(
        request_id=2, operation="enumerate", elapsed_seconds=300.0,
        child_exit_code=None, child_signal=None, child_alive=True,
        stdout_eof=False, stderr_eof=False)
    lauf = _live_mit_sync(
        module, BridgeAttrappe(),
        SyncWirft(BridgeProcessError("keine Antwort", diag))).sync(
        workspace_id=WORKSPACE)
    assert lauf.succeeded is False
    assert lauf.retryable is True
    assert lauf.imported == lauf.updated == lauf.tombstoned == 0


def test_fehlende_bruecke_ist_wiederholbar(module):
    live = LiveAttrappe(module, BridgeAttrappe(), unavailable="kein Binary")
    with pytest.raises(SyncUnavailable) as exc:
        live.sync(workspace_id=WORKSPACE)
    assert exc.value.retryable is True


# ═══ Nebenläufigkeit ════════════════════════════════════════════════════════
def test_paralleler_lauf_wird_abgewiesen(module):
    """Der zweite Aufruf bekommt einen Konflikt, keinen halben Bestand."""
    drin = threading.Event()
    weiter = threading.Event()

    class Langsam(SyncAttrappe):
        def sync(self, container_identifier):
            drin.set()
            weiter.wait(timeout=5)
            return _lauf()

    live = _live_mit_sync(module, BridgeAttrappe(), Langsam())
    fehler: list[Exception] = []

    def erster():
        live.sync(workspace_id=WORKSPACE)

    t = threading.Thread(target=erster)
    t.start()
    assert drin.wait(timeout=5)
    try:
        assert live.is_running(WORKSPACE) is True
        with pytest.raises(SyncBusy):
            live.sync(workspace_id=WORKSPACE)
    finally:
        weiter.set()
        t.join(timeout=5)
    assert not fehler
    assert live.is_running(WORKSPACE) is False


def test_verschiedene_workspaces_blockieren_sich_nicht(module):
    live = _live_mit_sync(module, BridgeAttrappe(), SyncAttrappe())
    live.sync(workspace_id="ws-a")
    live.sync(workspace_id="ws-b")
    assert live.is_running("ws-a") is False


def test_riegel_wird_auch_nach_fehler_freigegeben(module):
    live = LiveAttrappe(module, BridgeAttrappe(AuthorizationStatus.DENIED))
    with pytest.raises(SyncNotAuthorized):
        live.sync(workspace_id=WORKSPACE)
    assert live.is_running(WORKSPACE) is False


# ═══ HTTP ═══════════════════════════════════════════════════════════════════
def test_route_liest_den_status(module, kopf):
    bridge = BridgeAttrappe(AuthorizationStatus.NOT_DETERMINED)
    client = _client_mit(module, LiveAttrappe(module, bridge))
    body = client.get(f"{PREFIX}/authorization", headers=kopf).json()
    assert body == {"status": "notDetermined", "can_request": True,
                    "bridge_available": True, "reason": "",
                    "technical_code": ""}
    assert not bridge.store_beruehrt


def test_route_fordert_nur_mit_ausdruecklichem_koerper_an(module, kopf):
    bridge = BridgeAttrappe(AuthorizationStatus.NOT_DETERMINED,
                            grant_to=AuthorizationStatus.AUTHORIZED)
    client = _client_mit(module, LiveAttrappe(module, bridge))
    # Leerer Körper, falscher Wert, unbekanntes Feld — alles abgewiesen.
    for koerper in ({}, {"user_initiated": False}, {"user": True},
                    {"user_initiated": True, "force": True}):
        r = client.post(f"{PREFIX}/authorization/request", json=koerper,
                        headers=kopf)
        assert r.status_code == 422, koerper
    assert bridge.ops == []


def test_route_verweist_auf_die_app_statt_zu_fragen(module, kopf, in_der_app):
    bridge = BridgeAttrappe(AuthorizationStatus.NOT_DETERMINED)
    client = _client_mit(module, LiveAttrappe(module, bridge))
    r = client.post(f"{PREFIX}/authorization/request",
                    json={"user_initiated": True}, headers=kopf)
    assert r.status_code == 503
    detail = r.json()["detail"]
    assert detail["technical_code"] == "tcc_prompt_unavailable:handled_by_app"
    assert "Anwendung selbst" in detail["message"]
    assert bridge.starts == 0


def test_syncroute_meldet_aggregiert(module, kopf):
    sync = SyncAttrappe([_lauf(imported=5, unchanged=2)])
    client = _client_mit(module, _live_mit_sync(module, BridgeAttrappe(), sync))
    body = client.post(f"{PREFIX}/sync", headers=kopf).json()
    assert body["succeeded"] is True
    assert body["imported"] == 5
    assert body["read"] == 7
    assert body["completed_at"]


def test_syncroute_ohne_berechtigung_ist_403(module, kopf):
    bridge = BridgeAttrappe(AuthorizationStatus.DENIED)
    client = _client_mit(module, LiveAttrappe(module, bridge))
    r = client.post(f"{PREFIX}/sync", headers=kopf)
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "forbidden"
    assert not bridge.store_beruehrt


def test_syncroute_ohne_bruecke_ist_503_und_wiederholbar(module, kopf):
    client = _client_mit(module, LiveAttrappe(module, BridgeAttrappe(),
                                              unavailable="kein Binary"))
    r = client.post(f"{PREFIX}/sync", headers=kopf)
    assert r.status_code == 503
    assert r.json()["detail"]["retryable"] is True


def test_syncroute_bei_parallelem_lauf_ist_409(module, kopf):
    live = _live_mit_sync(module, BridgeAttrappe(), SyncAttrappe())
    client = _client_mit(module, live)
    live._lock_for(WORKSPACE).acquire()
    try:
        r = client.post(f"{PREFIX}/sync", headers=kopf)
        assert r.status_code == 409
        assert r.json()["detail"]["retryable"] is True
    finally:
        live._lock_for(WORKSPACE).release()


def test_syncroute_nimmt_den_workspace_aus_dem_kopf(module):
    gesehen: list[str] = []
    live = _live_mit_sync(module, BridgeAttrappe(), SyncAttrappe())
    echt = live.sync
    live.sync = lambda *, workspace_id: (gesehen.append(workspace_id),
                                         echt(workspace_id=workspace_id))[1]
    client = _client_mit(module, live)
    client.post(f"{PREFIX}/sync", headers={DEFAULT_WORKSPACE_HEADER: "haushalt"})
    assert gesehen == ["haushalt"]


# ═══ Nichts geschieht von selbst ════════════════════════════════════════════
def test_serve_start_fragt_nichts_ab(db_path, monkeypatch):
    """Der Serverstart darf weder Status lesen noch etwas anfordern."""
    from personaljarvis.bootstrap import PersonalBootstrap

    beruehrt: list[str] = []
    for name in ("authorization", "request_authorization", "sync"):
        monkeypatch.setattr(
            ContactsLiveService, name,
            lambda self, *a, _n=name, **k: beruehrt.append(_n))

    bootstrap = PersonalBootstrap(db_path)
    bootstrap.start()
    try:
        assert beruehrt == []
    finally:
        bootstrap.stop()


def test_serve_start_startet_keinen_sidecar_prozess(db_path, monkeypatch):
    """Ergaenzt den Test darueber auf der Prozessebene.

    Jener patcht die Dienstmethoden weg und belegt damit, dass niemand sie
    ruft. Er saehe aber nicht, wenn der Bootstrap den Sidecar an ihnen vorbei
    startete — etwa aus einer Bruecken-Vorpruefung heraus. Hier wird deshalb
    `SidecarProcess.start` selbst beobachtet.
    """
    import personaljarvis.contacts.bridge.process as prozess
    from personaljarvis.bootstrap import PersonalBootstrap

    gestartet: list[int] = []
    monkeypatch.setattr(prozess.SidecarProcess, "start",
                        lambda self: gestartet.append(1))

    bootstrap = PersonalBootstrap(db_path)
    runtime = bootstrap.start()
    try:
        assert gestartet == [], "der Bootstrap hat einen Sidecar gestartet"
        # Seit alle Lesepfade auditiert werden, ist die Auditspur der
        # unbestechlichste Zeuge: ein Lauf, den niemand ausgeloest hat,
        # stuende hier.
        with runtime.contacts.unit_of_work() as uow:
            laeufe = uow.execute(
                "SELECT COUNT(*) FROM contacts_sync_audit").fetchone()[0]
        assert laeufe == 0, "der Bootstrap hat einen Sync-Lauf erzeugt"
    finally:
        bootstrap.stop()


def test_seitenaufruf_fragt_nichts_ab(module, kopf, monkeypatch):
    """Das blosse Öffnen der Kontakte-Seite löst keinen Dialog und keinen
    Sync aus — die Seite lädt Liste, Kategorien und Capabilities."""
    beruehrt: list[str] = []
    bridge = BridgeAttrappe(AuthorizationStatus.NOT_DETERMINED)
    live = LiveAttrappe(module, bridge)
    for name in ("request_authorization", "sync"):
        monkeypatch.setattr(
            ContactsLiveService, name,
            lambda self, *a, _n=name, **k: beruehrt.append(_n))
    client = _client_mit(module, live)

    for pfad in ("", "/categories", "/capabilities", "/sync/status",
                 "/mutations", "/approvals"):
        assert client.get(f"{PREFIX}{pfad}", headers=kopf).status_code == 200

    assert beruehrt == []
    assert bridge.starts == 0, "keine dieser Routen startet einen Sidecar"
    assert not bridge.store_beruehrt
    with module.unit_of_work() as uow:
        laeufe = uow.execute(
            "SELECT COUNT(*) FROM contacts_sync_audit").fetchone()[0]
    assert laeufe == 0, "ein Seitenaufruf hat einen Sync-Lauf erzeugt"


def test_nur_drei_routen_koennen_ueberhaupt_einen_sidecar_starten(module):
    """Fixiert die Angriffsfläche: alles andere ist reine Datenbankarbeit."""
    import inspect

    from personaljarvis.contacts.api import routes as R

    quelle = inspect.getsource(R.create_contacts_router)
    # Nur Aufrufstellen, nicht die Definition.
    mit_live = [z.strip() for z in quelle.splitlines() if "_live()." in z]
    assert len(mit_live) == 3, mit_live
    assert {"authorization", "request_authorization", "sync"} == {
        z.split("_live().", 1)[1].split("(", 1)[0] for z in mit_live}


# ═══ Datenschutz und Schreibverbot ══════════════════════════════════════════
def test_antwort_traegt_keinen_cursor_und_kein_token(module, kopf):
    sync = SyncAttrappe([_lauf(imported=1)])
    client = _client_mit(module, _live_mit_sync(module, BridgeAttrappe(), sync))
    text = client.post(f"{PREFIX}/sync", headers=kopf).text
    for verboten in ("cursor_token", "currentToken", "token", "providerIdentifier",
                     "provider_identifier"):
        assert verboten not in text, verboten
    assert "cursor_present" in text  # nur das Boolean


def test_syncantwort_traegt_keine_kontaktfelder(module, kopf):
    sync = SyncAttrappe([_lauf(imported=1)])
    client = _client_mit(module, _live_mit_sync(module, BridgeAttrappe(), sync))
    body = client.post(f"{PREFIX}/sync", headers=kopf).json()
    for verboten in ("display_name", "emails", "phones", "note", "birthday"):
        assert verboten not in body, verboten
    assert set(body) == {
        "mode", "succeeded", "containers", "read", "imported", "updated",
        "tombstoned", "unchanged", "events_processed", "cursor_present",
        "cursor_advanced", "requires_full_diff", "error_class", "retryable",
        "detail", "completed_at"}


def test_der_live_dienst_kennt_keine_schreiboperation(module):
    live = ContactsLiveService(module)
    namen = [n for n in dir(live) if not n.startswith("__")]
    for verboten in ("create", "update", "delete", "save", "write"):
        assert not any(verboten in n.lower() for n in namen), verboten


def test_kein_endpunkt_kann_update_oder_delete_schreiben(module):
    """Update und Delete weist die Bridge schon auf Clientebene ab."""
    from personaljarvis.contacts.bridge.client import ContactsBridgeClient

    for name in SCHREIB_OPERATIONEN:
        with pytest.raises(NotImplementedError):
            getattr(ContactsBridgeClient(None), name)()


def _sidecar_code() -> str:
    from pathlib import Path

    quelle = (Path(__file__).resolve().parents[3]
              / "native/contacts-bridge/src/sidecar.swift").read_text()
    return "\n".join(z.split("//", 1)[0] for z in quelle.splitlines())


def test_der_sidecar_hat_genau_einen_schreibpfad():
    """Ein `CNSaveRequest` — und er steht ausschliesslich in `opCreate`.

    Frueher lautete der Nachweis „gar kein CNSaveRequest". Seit ADR-0025 legt
    der Sidecar Kontakte an; die Aussage muss deshalb schaerfer werden statt
    zu verschwinden: **genau einer**, und zwar dort, wo er hingehoert.

    Seit dem 2026-08-01 fuehrt der Weg zum Store ausschliesslich durch die
    Objective-C-@try/@catch-Grenze (`JCExecuteSaveRequestGuarded`): ein
    direkter `store.execute(`-Aufruf in Swift waere wieder ein Pfad, auf dem
    eine NSException den Prozess toetet und ihre Diagnose verliert.
    """
    code = _sidecar_code()
    assert code.count("CNSaveRequest()") == 1
    assert code.count("store.execute(") == 0
    assert code.count("JCExecuteSaveRequestGuarded(") == 1
    # Die eine Stelle liegt in opCreate und vor keiner Schleife.
    nach_create = code.split("func opCreate")[1]
    assert "CNSaveRequest()" in nach_create
    assert "for " not in nach_create.split("JCExecuteSaveRequestGuarded(")[0].split(
        "let req = CNSaveRequest()")[1]


def test_der_sidecar_schreibt_nur_neue_kontakte():
    """Kein Update-, Delete- oder Gruppenpfad am Store."""
    code = _sidecar_code()
    for verboten in ("req.update(", "req.delete(", "mutableCopy()",
                     "CNMutableGroup", "addMember", "removeMember",
                     "unifiedContact(withIdentifier"):
        # `unifiedContact` bleibt erlaubt, wo es der reine Lesepfad benutzt.
        if verboten == "unifiedContact(withIdentifier":
            continue
        assert verboten not in code, verboten
    # `add` gibt es genau einmal — die Neuanlage.
    assert code.count("req.add(") == 1


# ═══ Fehlervertrag: nie ein nackter Klassenname ═════════════════════════════
#
# Regression zum gescheiterten arm64-Livetest: die Oberfläche zeigte wörtlich
# „BridgeOperationError". Diese Zeichenkette entstand, weil `str(exc)` der
# Live-Fehler der Klassenname der auslösenden Ausnahme war. Ein Klassenname
# sagt dem Nutzer nichts, verrät nicht, ob ein zweiter Versuch hilft, und
# benennt nicht einmal den gescheiterten Schritt.
def _kopf_ws() -> dict:
    return {DEFAULT_WORKSPACE_HEADER: WORKSPACE}


def test_kein_ausnahmeklassenname_in_der_nutzermeldung(module, monkeypatch):
    """Der Kern der Regression — über den echten Weg, nicht am Dienst vorbei.

    Der Handshake scheitert mit genau der Ausnahme, deren Klassenname im
    Livetest auf dem Bildschirm stand.
    """
    from personaljarvis.contacts.bridge import client as bridge_client
    from personaljarvis.contacts.bridge.errors import BridgeOperationError

    def start_scheitert(self):
        raise BridgeOperationError("provider_error", "interner Text",
                                   provider_domain="CNErrorDomain",
                                   provider_code=100)

    monkeypatch.setattr(bridge_client.ContactsBridgeClient, "start",
                        start_scheitert)
    live = ContactsLiveService(module, sidecar_path=_echtes_binary())
    client = _client_mit(module, live)

    detail = client.post(f"{PREFIX}/sync", headers=_kopf_ws()).json()["detail"]
    assert "BridgeOperationError" not in detail["message"]
    assert "Error" not in detail["message"]
    # Statt des Klassennamens steht jetzt die Apple-Angabe in der Kennung.
    assert detail["technical_code"] == (
        "bridge_start:tcc_request_rejected:CNErrorDomain/100")
    assert detail["retryable"] is True


def _echtes_binary():
    """Pfad des gebauten Sidecars; ohne ihn wird der Test übersprungen.

    Der Auflösungsschritt muss gelingen, damit der **Start** scheitern kann —
    sonst prüfte der Test den falschen Zweig.
    """
    from pathlib import Path

    repo = Path(__file__).resolve().parents[3]
    for kandidat in (
        repo / "frontend/src-tauri/binaries/jarvis-contacts-aarch64-apple-darwin",
        repo / "frontend/src-tauri/binaries/jarvis-contacts-x86_64-apple-darwin",
    ):
        if kandidat.exists():
            return kandidat
    pytest.skip("Sidecar nicht gebaut")


def test_der_fehlervertrag_traegt_alle_vier_felder(module):
    live = LiveAttrappe(module, BridgeAttrappe(), unavailable=None)
    live._client = lambda: (_ for _ in ()).throw(  # noqa: SLF001
        SyncUnavailable("Die Bruecke liess sich nicht starten.",
                        technical_code="bridge_start_failed:BridgeOperationError"))
    client = _client_mit(module, live)
    detail = client.post(f"{PREFIX}/sync", headers=_kopf_ws()).json()["detail"]
    assert set(detail) == {"code", "message", "technical_code", "retryable"}
    assert detail["code"] == "unavailable"
    assert detail["retryable"] is True
    assert detail["technical_code"] == "bridge_start_failed:BridgeOperationError"
    assert detail["message"].endswith(".")


def test_technische_kennung_traegt_keine_pfade_und_keine_werte(module):
    """Der Resolver nennt in seiner Meldung Suchpfade — die dürfen nicht raus."""
    live = LiveAttrappe(module, BridgeAttrappe(), unavailable=None)
    from personaljarvis.contacts.bridge.errors import BridgeConfigurationError

    def wirft():
        raise BridgeConfigurationError(
            "Kein Sidecar unter /Users/geheim/pfad/jarvis-contacts")

    echt = ContactsLiveService._client
    live._client = lambda: echt(live)  # noqa: SLF001
    live._sidecar_path = "/Users/geheim/pfad/gibtesnicht"  # noqa: SLF001
    client = _client_mit(module, live)
    detail = client.post(f"{PREFIX}/sync", headers=_kopf_ws()).json()["detail"]
    assert "/Users/" not in detail["message"]
    assert "/Users/" not in detail["technical_code"]
    assert detail["technical_code"] == "bridge_not_found"


@pytest.mark.parametrize("fehler,status,kategorie,wiederholbar", [
    (SyncBusy("läuft schon", technical_code="sync_already_running"),
     409, "conflict", True),
    (SyncNotAuthorized("keine Berechtigung", technical_code="not_authorized:denied"),
     403, "forbidden", False),
    (SyncUnavailable("Brücke weg", technical_code="bridge_not_found"),
     503, "unavailable", True),
])
def test_jede_fehlerklasse_bringt_ihren_eigenen_vertrag(
        module, fehler, status, kategorie, wiederholbar):
    live = LiveAttrappe(module, BridgeAttrappe(), unavailable=None)
    live.sync = lambda **kw: (_ for _ in ()).throw(fehler)  # noqa: SLF001
    client = _client_mit(module, live)
    r = client.post(f"{PREFIX}/sync", headers=_kopf_ws())
    assert r.status_code == status
    assert r.json()["detail"]["code"] == kategorie
    assert r.json()["detail"]["retryable"] is wiederholbar


def test_autorisierungssicht_meldet_kennung_statt_klassenname(module):
    """Auch der nicht-fehlerhafte Weg darf keinen Klassennamen zeigen."""
    live = LiveAttrappe(module, BridgeAttrappe(),
                        unavailable="egal")
    client = _client_mit(module, live)
    body = client.get(f"{PREFIX}/authorization", headers=_kopf_ws()).json()
    assert body["bridge_available"] is False
    assert body["status"] == "unknown"
    assert "Error" not in body["reason"]
    assert body["technical_code"]


def test_technische_kennungen_stammen_aus_geschlossener_menge():
    """Jede Kennung ist stabil und PII-frei — kein Pfad, kein Wert."""
    import re
    from pathlib import Path

    quelle = (Path(__file__).resolve().parents[3]
              / "src/personaljarvis/contacts/application/live.py").read_text()
    kennungen = re.findall(r'technical_code=f?"([^"]+)"', quelle)
    assert kennungen, "keine Kennungen gefunden"
    for k in kennungen:
        assert "/" not in k, k
        assert not k.startswith("{"), k
        assert re.match(r"^[a-z_]+(:\{?[a-z_.()]*\}?)?$", k), k


# ═══ Berechtigungsanfrage: Diagnose und Prozessweg ══════════════════════════
#
# Regression zum zweiten gescheiterten arm64-Livetest. Sichtbar war nur
# „authorization_request_failed:BridgeOperationError" — der Apple-Fehlercode,
# den der Sidecar bereits gemeldet hatte, ging auf dem Weg nach oben verloren.
from personaljarvis.contacts.bridge.errors import BridgeOperationError  # noqa: E402


def test_apple_domain_und_code_bleiben_erhalten():
    """Der Kern: `CNErrorDomain/100` darf nicht zu einem Klassennamen werden."""
    exc = BridgeOperationError("provider_error", "abgelehnt",
                               provider_domain="CNErrorDomain", provider_code=100)
    kennung = technischer_code("authorization_request", exc)
    assert kennung == "authorization_request:tcc_request_rejected:CNErrorDomain/100"
    assert "BridgeOperationError" not in kennung


def test_negative_apple_codes_bleiben_lesbar():
    exc = BridgeOperationError("provider_error", "x",
                               provider_domain="NSCocoaErrorDomain",
                               provider_code=-1)
    assert technischer_code("authorization_request", exc).endswith(
        "NSCocoaErrorDomain/-1")


def test_timeout_ist_kein_providerfehler():
    exc = BridgeOperationError("internal", "blieb aus",
                               provider_domain="timeout", provider_code=0,
                               retryable=True)
    assert technischer_code("authorization_request", exc) == (
        "authorization_request:request_timeout")


@pytest.mark.parametrize("bridge_code,erwartet", [
    ("invalid_request", "bridge_response_invalid"),
    ("protocol_mismatch", "bridge_response_invalid"),
    ("tcc_denied", "tcc_denied"),
    ("provider_error", "tcc_request_rejected"),
])
def test_vertragscodes_stammen_aus_geschlossener_menge(bridge_code, erwartet):
    exc = BridgeOperationError(bridge_code, "x")
    assert technischer_code("authorization_request", exc) == (
        f"authorization_request:{erwartet}")


def test_ohne_providerangabe_bleibt_der_klassenname_die_beste_auskunft():
    """Gab der Sidecar nichts Strukturiertes her, ist der Klassenname das
    einzig Verfügbare — dann ist er zulässig, aber nur dann."""
    kennung = technischer_code("bridge_start", BridgeProtocolError("x"))
    assert kennung == "bridge_start:BridgeProtocolError"


def test_keine_localizeddescription_im_sidecar():
    """Apple-Fehlertexte können Pfade enthalten und werden nie übertragen."""
    from pathlib import Path

    quelle = (Path(__file__).resolve().parents[3]
              / "native/contacts-bridge/src/sidecar.swift").read_text()
    code = "\n".join(z.split("//", 1)[0] for z in quelle.splitlines())
    assert "localizedDescription" not in code
    assert "userInfo" not in code


def test_der_sidecar_meldet_domain_und_code_strukturiert():
    from pathlib import Path

    quelle = (Path(__file__).resolve().parents[3]
              / "native/contacts-bridge/src/sidecar.swift").read_text()
    assert "providerDomain" in quelle and "providerCode" in quelle
    assert "e.domain" in quelle and "e.code" in quelle


# ── Der Prozessweg ─────────────────────────────────────────────────────────


def test_statuslesen_braucht_die_app_nicht(module, ohne_app):
    """`authorizationStatus` fragt nichts an und bleibt deshalb erlaubt."""
    bridge = BridgeAttrappe(AuthorizationStatus.NOT_DETERMINED)
    sicht = LiveAttrappe(module, bridge).authorization()
    assert sicht.status == "notDetermined"
    assert bridge.ops == ["authorizationStatus"]


def test_die_grenze_haengt_an_keiner_umgebungsvariablen(module, monkeypatch):
    """Der Server verweist **immer** auf die App — egal, wie er gestartet wurde.

    Frueher entschied `PERSONAL_JARVIS_HOST_BUNDLE` darueber, ob der Server
    die Anfrage selbst versuchte. Seit der Dialog im App-Prozess liegt, gibt
    es diesen Versuch nicht mehr; eine Variable, die nichts mehr steuert, waere
    tote Sicherheitslogik und wird deshalb nicht mehr gelesen.
    """
    for wert in (None, "/Anwendungen/Jarvis.app", ""):
        if wert is None:
            monkeypatch.delenv("PERSONAL_JARVIS_HOST_BUNDLE", raising=False)
        else:
            monkeypatch.setenv("PERSONAL_JARVIS_HOST_BUNDLE", wert)
        bridge = BridgeAttrappe(AuthorizationStatus.NOT_DETERMINED)
        with pytest.raises(SyncUnavailable) as exc:
            LiveAttrappe(module, bridge).request_authorization(user_initiated=True)
        assert exc.value.technical_code == "tcc_prompt_unavailable:handled_by_app"
        assert bridge.starts == 0


def test_die_live_schicht_liest_keine_prozessumgebung():
    """Belegt an der Quelle: kein `os.environ` mehr in dieser Schicht."""
    quelle = (_REPO_LIVE).read_text(encoding="utf-8")
    assert "os.environ" not in quelle
    assert "HOST_BUNDLE" not in quelle


def test_der_lese_sync_laeuft_weiter_ueber_den_sidecar(module):
    bridge = BridgeAttrappe(AuthorizationStatus.AUTHORIZED)
    sync = SyncAttrappe([_lauf(imported=4)])
    module.sync_service = lambda *a, **k: sync
    lauf = LiveAttrappe(module, bridge).sync(workspace_id=WORKSPACE)
    assert lauf.succeeded and lauf.imported == 4
    assert bridge.starts == 1 and bridge.stops == 1


def test_der_sidecar_kann_weiterhin_keine_mutation(module):
    from personaljarvis.contacts.bridge.client import ContactsBridgeClient

    for name in SCHREIB_OPERATIONEN:
        with pytest.raises(NotImplementedError):
            getattr(ContactsBridgeClient(None), name)()


def test_keine_route_fordert_noch_ueber_den_sidecar_an(module):
    """Statisch: im Produktivcode ruft nichts mehr `client.request_authorization`."""
    import inspect

    from personaljarvis.contacts.application import live as L

    quelle = inspect.getsource(L)
    code = "\n".join(z.split("#", 1)[0] for z in quelle.splitlines())
    assert "client.request_authorization" not in code
    assert ".request_authorization(user_initiated=True)" not in code


def _objc_shim() -> str:
    """Der Objective-C-Shim des App-Prozesses, ohne Kommentare.

    Der Systemaufruf liegt seit der ABI-Korrektur dort und nicht mehr in
    Rust: der Objective-C-Compiler prüft Blocksignatur, BOOL-Darstellung und
    den Enum-Wert gegen die echten SDK-Header, was aus roher
    Nachrichtenübermittlung heraus nicht beweisbar war.
    """
    from pathlib import Path

    repo = Path(__file__).resolve().parents[3]
    quelle = (repo / "frontend/src-tauri/objc/JCContactsAuthorization.m").read_text()
    return "\n".join(z for z in quelle.splitlines()
                     if not z.strip().startswith("//"))


def _rust_modul() -> str:
    from pathlib import Path

    repo = Path(__file__).resolve().parents[3]
    quelle = (repo / "frontend/src-tauri/src/contacts_authorization.rs").read_text()
    produktiv = quelle.split("#[cfg(test)]", 1)[0]
    return "\n".join(z for z in produktiv.splitlines()
                     if not z.strip().startswith(("//", "//!")))


def test_der_app_prozess_ist_der_einzige_anfrageweg():
    """Genau eine Aufrufstelle, und sie liegt im Shim des App-Prozesses."""
    shim = _objc_shim()
    assert shim.count("requestAccessForEntityType") == 1
    assert "authorizationStatusForEntityType" in shim
    # Die Rust-Seite bindet nur an, sie sendet keine Nachricht selbst.
    assert "requestAccessForEntityType" not in _rust_modul()


def test_der_app_prozess_liest_keinen_kontakt():
    for name, code in (("shim", _objc_shim()), ("rust", _rust_modul())):
        for verboten in ("CNSaveRequest", "CNMutableContact", "unifiedContact",
                         "enumerateContacts", "CNContactFetchRequest",
                         "containersMatchingPredicate"):
            assert verboten not in code, f"{verboten} in {name}"


def test_der_app_prozess_liest_keine_localizeddescription():
    """Apple-Fehlertexte können Pfade tragen — nur Domain und Zahl gehen raus."""
    for name, code in (("shim", _objc_shim()), ("rust", _rust_modul())):
        assert "localizedDescription" not in code, name
        assert "userInfo" not in code, name
    shim = _objc_shim()
    assert "error.domain" in shim and "error.code" in shim


def test_der_shim_nimmt_den_enumwert_aus_dem_header():
    """Kein ungeprüfter Magic Integer: `CNEntityTypeContacts` ist der erste
    und einzige Fall eines `NS_ENUM(NSInteger, CNEntityType)`, also 0 — und
    der Shim benutzt die Konstante, nicht die Zahl."""
    shim = _objc_shim()
    assert "CNEntityTypeContacts" in shim
    assert "entityType:0" not in shim.replace(" ", "")


def test_der_main_thread_wird_nicht_blockiert():
    """Der Systemaufruf gehört auf die Main Queue, das Warten nicht."""
    shim = _objc_shim()
    assert "dispatch_async(dispatch_get_main_queue()" in shim
    assert "dispatch_sync(dispatch_get_main_queue()" not in shim
    assert shim.index("dispatch_semaphore_wait") > shim.index(
        "dispatch_async(dispatch_get_main_queue()")


def test_der_shim_zaehlt_die_callbacks():
    """Ein zweiter Callback bliebe sonst unsichtbar."""
    assert "callbackCount += 1" in _objc_shim()
    assert "callback_count" in _rust_modul()
