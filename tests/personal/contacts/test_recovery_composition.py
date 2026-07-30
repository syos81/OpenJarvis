"""Produktive Verdrahtung der Wiederherstellung. **Kontaktfrei.**

Geprüft wird vor allem, was das Registrieren **nicht** tut. Ein Einstiegspunkt,
der beim Aufbau schon einen Sidecar startet oder eine Transaktion öffnet, wäre
genau die Art von Nebenwirkung, die man erst bemerkt, wenn sie schadet.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

import personaljarvis
from personaljarvis.contacts.application.live import (
    APPLE_PROVIDER_ACCOUNT,
    ContactsRecoveryEntrypoint,
)
from personaljarvis.contacts.sync.recovery import RecoveryNotApplicable

_REPO = Path(__file__).resolve().parents[3]


class AppAttrappe:
    """Minimale FastAPI-Fläche für `attach`."""

    def __init__(self) -> None:
        self.state = type("S", (), {})()
        self.router_gebaut = 0

    def include_router(self, router) -> None:
        self.router_gebaut += 1

    def on_event(self, name):
        return lambda f: f


@pytest.fixture
def sidecar_datei(tmp_path):
    """Eine Datei, die der Resolver akzeptiert — ohne je gestartet zu werden."""
    from personaljarvis.contacts.bridge.resolver import BINARY_NAME

    pfad = tmp_path / BINARY_NAME
    pfad.write_bytes(b"#!/bin/sh\nexit 0\n")
    pfad.chmod(0o755)
    return pfad


@pytest.fixture
def verdrahtet(tmp_path, db_path, sidecar_datei, monkeypatch):
    """Baut das Modul über `attach` auf — wie im produktiven Serverstart."""
    import personaljarvis.contacts.bridge.resolver as resolver

    # Architekturprüfung überbrücken: die Attrappe ist kein Mach-O. Der
    # Auflösungsweg selbst bleibt der produktive.
    monkeypatch.setattr(resolver, "binary_architectures",
                        lambda p: (resolver.host_architecture(),))
    app = AppAttrappe()
    runtime = personaljarvis.attach(
        app, database_path=str(db_path), lock_path=str(tmp_path / "l.lock"),
        sidecar_path=str(sidecar_datei))
    yield app, runtime
    app.state.personal_bootstrap.stop()


# ── Registrierung ───────────────────────────────────────────────────────────
def test_das_produktive_modul_traegt_den_recovery_dienst(verdrahtet):
    _, runtime = verdrahtet
    assert isinstance(runtime.contacts.recovery_service,
                      ContactsRecoveryEntrypoint)


def test_der_dienst_kennt_workspace_und_providerkonto(verdrahtet):
    _, runtime = verdrahtet
    dienst = runtime.contacts.recovery_service
    assert dienst._provider_account_id == APPLE_PROVIDER_ACCOUNT
    assert dienst._workspace_id == personaljarvis.DEFAULT_WORKSPACE


def test_recovery_und_sync_teilen_dieselbe_persistenz(verdrahtet):
    """Keine zweite Verbindung, kein zweiter Bestand."""
    _, runtime = verdrahtet
    modul = runtime.contacts
    assert modul.recovery_service._module is modul
    assert modul.recovery_service._live is modul.live_service


def test_ohne_bridge_bleibt_der_dienst_ungesetzt(module, monkeypatch):
    """Fail-closed statt Rückfallprovider.

    Geprüft wird die Registrierung selbst statt des ganzen `attach`: der
    Resolver sucht bei einem fehlenden Pfad in den bekannten Orten weiter und
    fände auf diesem Rechner das gebaute Bundle — das würde die Aussage
    verwässern.
    """
    from personaljarvis.contacts.bridge.errors import BridgeConfigurationError

    def findet_nichts(*a, **k):
        raise BridgeConfigurationError("kein Sidecar")

    monkeypatch.setattr(
        "personaljarvis.contacts.bridge.resolver.resolve_sidecar", findet_nichts)

    personaljarvis._register_recovery_service(module, None, None)

    assert getattr(module, "recovery_service", None) is None


def test_ohne_bridge_antwortet_der_endpunkt_mit_503(module):
    """Der kontrollierte Ausgang, wenn die Bridge strukturell fehlt."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from personaljarvis.contacts.api.routes import PREFIX, create_contacts_router

    app = FastAPI()
    app.include_router(create_contacts_router(module))   # ohne Registrierung
    antwort = TestClient(app).post(
        f"{PREFIX}/recovery/suspicious-empty",
        json={"user_initiated": True, "confirm_reactivation": True})

    assert antwort.status_code == 503


# ── Nebenwirkungsfreiheit ───────────────────────────────────────────────────
def test_die_registrierung_startet_keinen_sidecar(verdrahtet, monkeypatch):
    import personaljarvis.contacts.bridge.process as prozess

    gestartet: list = []
    monkeypatch.setattr(prozess.SidecarProcess, "start",
                        lambda self: gestartet.append(1))
    _, runtime = verdrahtet
    assert gestartet == []
    assert runtime.contacts.recovery_service is not None


def test_die_registrierung_liest_keinen_autorisierungsstatus(tmp_path, db_path,
                                                             sidecar_datei,
                                                             monkeypatch):
    import personaljarvis.contacts.bridge.client as client_modul
    import personaljarvis.contacts.bridge.resolver as resolver

    monkeypatch.setattr(resolver, "binary_architectures",
                        lambda p: (resolver.host_architecture(),))
    gelesen: list = []
    monkeypatch.setattr(client_modul.ContactsBridgeClient,
                        "authorization_status",
                        lambda self: gelesen.append(1))

    app = AppAttrappe()
    runtime = personaljarvis.attach(
        app, database_path=str(db_path), lock_path=str(tmp_path / "l.lock"),
        sidecar_path=str(sidecar_datei))
    try:
        assert gelesen == []
        assert runtime.contacts.recovery_service is not None
    finally:
        app.state.personal_bootstrap.stop()


def test_das_konstruieren_des_einstiegs_oeffnet_keine_transaktion(module):
    class Zaehlend:
        def __init__(self, echt):
            self._echt = echt
            self.transaktionen = 0

        def unit_of_work(self):
            self.transaktionen += 1
            return self._echt.unit_of_work()

        def repositories(self, uow):
            return self._echt.repositories(uow)

    zaehler = Zaehlend(module)
    ContactsRecoveryEntrypoint(None, zaehler, workspace_id="ws")
    assert zaehler.transaktionen == 0


# ── Der Endpunkt nach der Verdrahtung ───────────────────────────────────────
def test_der_endpunkt_meldet_kein_fehlender_dienst_mehr(verdrahtet):
    """Nicht mehr 503 wegen fehlender Registrierung — sondern die echte
    Vorbedingungsprüfung."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from personaljarvis.contacts.api.routes import PREFIX, create_contacts_router

    _, runtime = verdrahtet
    app = FastAPI()
    app.include_router(create_contacts_router(runtime.contacts))
    antwort = TestClient(app).post(
        f"{PREFIX}/recovery/suspicious-empty",
        json={"user_initiated": True, "confirm_reactivation": True})

    assert antwort.status_code == 409, antwort.text
    assert antwort.json()["detail"]["technical_code"] == "no_tombstones"


def test_die_vorbedingungen_greifen_vor_dem_ersten_store_zugriff(verdrahtet,
                                                                  monkeypatch):
    import personaljarvis.contacts.bridge.process as prozess

    gestartet: list = []
    monkeypatch.setattr(prozess.SidecarProcess, "start",
                        lambda self: gestartet.append(1))
    _, runtime = verdrahtet

    with pytest.raises(RecoveryNotApplicable) as fehler:
        runtime.contacts.recovery_service.recover()

    assert fehler.value.technical_code == "no_tombstones"
    assert gestartet == [], "kein Sidecar bei gescheiterter Vorpruefung"


# ── Keine automatische Ausführung, keine Werkzeugfläche ─────────────────────
def test_kein_automatischer_lauf_beim_start(verdrahtet):
    """Der Bootstrap darf nichts reparieren."""
    _, runtime = verdrahtet
    with runtime.contacts.unit_of_work() as uow:
        laeufe = uow.execute(
            "SELECT COUNT(*) FROM contacts_sync_audit WHERE mode = 'recovery'"
        ).fetchone()[0]
    assert laeufe == 0


def test_kein_aufruf_im_lebenszyklus_oder_scheduler():
    """Belegt an der Quelle: niemand ruft `recover(` ausser Route und Tests."""
    treffer = subprocess.run(
        ["git", "grep", "-ln", r"\.recover(", "--", "src/", "frontend/src"],
        cwd=_REPO, capture_output=True, text=True, timeout=60).stdout.split()
    # Genau zwei Stellen: die Route und der Einstiegspunkt, den sie benutzt.
    # Kein Lebenszyklus, kein Startup, kein Scheduler, keine UI.
    assert set(treffer) == {"src/personaljarvis/contacts/api/routes.py",
                            "src/personaljarvis/contacts/application/live.py"}, treffer


def test_keine_agenten_oder_toolregistrierung():
    treffer = subprocess.run(
        ["git", "grep", "-l", "recovery/suspicious-empty"],
        cwd=_REPO, capture_output=True, text=True, timeout=60).stdout.split()
    erlaubt = {"src/personaljarvis/contacts/api/routes.py",
               "tests/personal/contacts/test_recovery_and_audit.py"}
    assert set(treffer) <= erlaubt, treffer


def test_keine_ui_schaltflaeche():
    """Die Kontakte-Seite bekommt keinen Reparaturknopf.

    Geprüft wird der Kontaktebereich; „recovery" kommt im Upstream-Frontend
    an unbeteiligter Stelle vor (Agentenseite) und ist dort nicht gemeint.
    """
    treffer = subprocess.run(
        ["git", "grep", "-lni", "recovery", "--", "frontend/src/personal"],
        cwd=_REPO, capture_output=True, text=True, timeout=60).stdout.split()
    assert treffer == [], treffer


def test_kein_zugriff_auf_den_alten_addressbook_connector():
    quelle = (_REPO / "src/personaljarvis/contacts/sync/recovery.py").read_text(
        encoding="utf-8")
    for verboten in ("AddressBook", "addressbook.sqlitedb", "openjarvis.tools",
                     "sqlite3.connect"):
        assert verboten not in quelle, verboten
