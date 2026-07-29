"""Autorisierungsweg und manueller Lese-Sync — kontaktfrei.

**Kein echter Sidecar, kein Apple-Contacts-Store, kein TCC-Dialog.** Der
Bridge-Client wird durch eine Attrappe ersetzt, die jede Operation mitzählt.
Damit ist prüfbar, was sonst nur behauptet wäre: dass ohne erteilte
Berechtigung **keine einzige** Leseoperation den Store erreicht, und dass
keine Route je eine Schreiboperation auslöst.
"""

from __future__ import annotations

import threading

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
)
from personaljarvis.contacts.bridge.errors import (
    BridgeProcessError,
    BridgeProtocolError,
)
from personaljarvis.contacts.bridge.models import AuthorizationStatus, ContainerInfo
from personaljarvis.contacts.sync.state import CursorState, SyncRunKind, SyncRunResult

from .conftest import WORKSPACE

#: Jede Operation, die den Kontakte-Store berührt. Kein Test dieser Datei darf
#: eine davon auslösen, solange nicht `authorized` gilt.
STORE_OPERATIONEN = ("containers", "enumerate", "changes", "get",
                     "getUnifiedReadOnly")
SCHREIB_OPERATIONEN = ("create", "update", "delete")


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

    def __init__(self, ergebnisse=None) -> None:
        self.ergebnisse = list(ergebnisse or [_lauf()])
        self.calls = 0

    def inventory_containers(self):
        return (ContainerInfo(identifier="con-1", name="", type="local"),)

    def sync(self, container_identifier: str):
        self.calls += 1
        return self.ergebnisse[min(self.calls - 1, len(self.ergebnisse) - 1)]


@pytest.fixture
def kopf() -> dict:
    return {DEFAULT_WORKSPACE_HEADER: WORKSPACE}


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


def test_anfordern_gibt_den_neuen_status_zurueck(module):
    bridge = BridgeAttrappe(AuthorizationStatus.NOT_DETERMINED,
                            grant_to=AuthorizationStatus.AUTHORIZED)
    sicht = LiveAttrappe(module, bridge).request_authorization(user_initiated=True)
    assert sicht.status == "authorized"
    assert bridge.ops == ["requestAuthorization"]
    assert not bridge.store_beruehrt


def test_ablehnung_wird_nicht_automatisch_wiederholt(module):
    bridge = BridgeAttrappe(AuthorizationStatus.NOT_DETERMINED,
                            grant_to=AuthorizationStatus.DENIED)
    live = LiveAttrappe(module, bridge)
    sicht = live.request_authorization(user_initiated=True)
    assert sicht.status == "denied"
    assert sicht.can_request is False
    assert bridge.ops.count("requestAuthorization") == 1


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
                    "bridge_available": True, "reason": ""}
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


def test_route_fordert_mit_nutzeraktion_an(module, kopf):
    bridge = BridgeAttrappe(AuthorizationStatus.NOT_DETERMINED,
                            grant_to=AuthorizationStatus.AUTHORIZED)
    client = _client_mit(module, LiveAttrappe(module, bridge))
    r = client.post(f"{PREFIX}/authorization/request",
                    json={"user_initiated": True}, headers=kopf)
    assert r.status_code == 200
    assert r.json()["status"] == "authorized"


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


def test_kein_endpunkt_kann_eine_provideroperation_schreiben(module):
    """Die Bridge weist Schreiboperationen schon auf Clientebene ab."""
    from personaljarvis.contacts.bridge.client import ContactsBridgeClient

    for name in SCHREIB_OPERATIONEN:
        with pytest.raises(NotImplementedError):
            getattr(ContactsBridgeClient(None), name)()


def test_der_sidecar_enthaelt_keinen_schreibpfad():
    """Der stärkste Nachweis: `CNSaveRequest` kommt im Quelltext nicht als
    Code vor — nur in einem erklärenden Kommentar."""
    from pathlib import Path

    quelle = (Path(__file__).resolve().parents[3]
              / "native/contacts-bridge/src/sidecar.swift").read_text()
    code = "\n".join(z.split("//", 1)[0] for z in quelle.splitlines())
    assert "CNSaveRequest" not in code
    assert "CNMutableContact" not in code
