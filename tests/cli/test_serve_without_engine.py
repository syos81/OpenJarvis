"""`jarvis serve` must survive a missing inference engine.

The server carries capabilities that need no model at all — health,
telemetry, memory browsing, the Personal Jarvis modules. Exiting because one
optional dependency is absent took every one of them down with it.

These tests run against an isolated `OPENJARVIS_HOME` so no database, config
or log of the real installation is touched, and `uvicorn.run` is replaced so
nothing binds a port.
"""

from __future__ import annotations

import importlib

import pytest
from click.testing import CliRunner

from openjarvis.cli.serve import serve

# `openjarvis.cli` re-exportiert das Kommando unter demselben Namen wie das
# Modul. Sowohl `import openjarvis.cli.serve as m` als auch der Punktpfad von
# `monkeypatch.setattr` treffen deshalb das Click-Kommando statt des Moduls —
# ueber die Modultabelle ist die Aufloesung eindeutig.
serve_modul = importlib.import_module("openjarvis.cli.serve")


@pytest.fixture
def isolierte_umgebung(tmp_path, monkeypatch):
    """Eigenes OPENJARVIS_HOME — der echte Bestand bleibt unberuehrt.

    Alle Hintergrunddienste sind abgeschaltet. `serve` startet sonst
    Scheduler-, Speicher- und Telemetriethreads, die es erst beim
    Herunterfahren des Servers wieder einsammelt — und der wird hier nie
    gestartet. Die Threads liefen im Testlauf weiter und haben den
    pytest-Worker blockiert.
    """
    heim = tmp_path / "openjarvis-home"
    heim.mkdir()
    (heim / "config.toml").write_text(
        "[telemetry]\nenabled = false\n"
        "[agent_manager]\nenabled = false\n"
        "[channel]\nenabled = false\n"
        "[sessions]\nenabled = false\n"
        "[traces]\nenabled = false\n"
        "[memory]\nenabled = false\n"
        "[agent]\ncontext_from_memory = false\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("OPENJARVIS_HOME", str(heim))
    monkeypatch.delenv("OPENJARVIS_API_KEY", raising=False)
    return heim


@pytest.fixture
def personal_aktiv(monkeypatch):
    """Personal Jarvis ausdruecklich aktiviert — wie es die gepackte App tut."""
    monkeypatch.setenv("OPENJARVIS_PERSONAL_ENABLED", "1")


@pytest.fixture
def gestarteter_server(monkeypatch):
    """Faengt `uvicorn.run` ab und haelt die uebergebene App fest."""
    laeufe: list[dict] = []

    def _run(app, host=None, port=None, **kwargs):
        laeufe.append({"app": app, "host": host, "port": port})

    import uvicorn

    monkeypatch.setattr(uvicorn, "run", _run)
    return laeufe


def _ohne_engine(monkeypatch):
    """Keine Engine ist aufloesbar — der harte Abbruchfall von frueher.

    Gepatcht wird auf dem **Modulobjekt**: der Pfad `openjarvis.cli.serve`
    loest als Attribut auf das gleichnamige Click-Kommando auf, nicht auf das
    Modul.
    """
    monkeypatch.setattr(serve_modul, "get_engine", lambda *a, **k: None)
    monkeypatch.setattr(serve_modul, "discover_engines", lambda cfg: [])
    monkeypatch.setattr(serve_modul, "discover_models", lambda engines: {})


def test_server_startet_ohne_engine(isolierte_umgebung, gestarteter_server,
                                    monkeypatch):
    _ohne_engine(monkeypatch)

    ergebnis = CliRunner().invoke(serve, ["--port", "8123"], obj={"quiet": True})

    assert ergebnis.exit_code == 0, ergebnis.output
    assert len(gestarteter_server) == 1, "uvicorn wurde nicht gestartet"
    assert gestarteter_server[0]["port"] == 8123


def test_meldung_nennt_was_fehlt_und_was_bleibt(isolierte_umgebung,
                                                gestarteter_server, monkeypatch):
    """Der Nutzer erfaehrt beides: was ausfaellt und was weiterlaeuft."""
    _ohne_engine(monkeypatch)

    ergebnis = CliRunner().invoke(serve, ["--port", "8124"], obj={"quiet": True})

    assert "No inference engine available" in ergebnis.output
    assert "server starts" in ergebnis.output.lower()


def test_engine_der_app_meldet_sich_als_ungesund(isolierte_umgebung,
                                                 gestarteter_server, monkeypatch):
    """`/health` muss 503 liefern koennen — die Engine luegt nicht.

    Der Server laeuft, die Engine nicht. Genau diese Unterscheidung braucht
    der Desktop-Start, um „degradiert" von „tot" zu trennen.
    """
    _ohne_engine(monkeypatch)

    CliRunner().invoke(serve, ["--port", "8125"], obj={"quiet": True})

    app = gestarteter_server[0]["app"]
    assert app.state.engine.health() is False
    assert app.state.engine.list_models() == []


def test_fehlendes_modell_bei_vorhandener_engine_bleibt_fatal(
        isolierte_umgebung, gestarteter_server, monkeypatch):
    """Eine antwortende Engine ohne Modell ist eine echte Fehlkonfiguration.

    Sie bleibt ein harter Abbruch — hier laeuft etwas, es hat nur nichts zu
    bedienen. Das ist ein anderer Fall als „gar keine Engine".
    """
    class _LeereEngine:
        engine_id = "leer"
        is_cloud = False

        def list_models(self):
            return []

        def health(self):
            return True

        def can_serve(self, model):
            return True

        def close(self):
            pass

    monkeypatch.setattr(serve_modul, "get_engine",
                        lambda *a, **k: ("leer", _LeereEngine()))
    monkeypatch.setattr(serve_modul, "discover_engines", lambda cfg: [])
    monkeypatch.setattr(serve_modul, "discover_models", lambda engines: {})

    ergebnis = CliRunner().invoke(serve, ["--port", "8126", "--model", ""],
                                  obj={"quiet": True})

    assert ergebnis.exit_code == 1
    assert "No model available" in ergebnis.output
    assert gestarteter_server == [], "Der Server haette nicht starten duerfen"


def test_kontakte_routen_sind_auch_ohne_engine_registriert(
        isolierte_umgebung, personal_aktiv, gestarteter_server, monkeypatch):
    """Die Lesestrecke braucht kein Modell — sie muss also ohne Engine da sein.

    Genau das war der Ausfall: eine fehlende Inferenz-Engine nahm Kontakte,
    API und Read-Sync mit, obwohl keines davon ein Modell benoetigt.
    """
    _ohne_engine(monkeypatch)

    CliRunner().invoke(serve, ["--port", "8127"], obj={"quiet": True})

    app = gestarteter_server[0]["app"]
    pfade = {r.path for r in app.routes}
    for pflicht in (
        "/v1/personal/contacts",
        "/v1/personal/contacts/authorization",
        "/v1/personal/contacts/authorization/request",
        "/v1/personal/contacts/sync",
        "/v1/personal/contacts/sync/status",
        "/v1/personal/contacts/categories",
    ):
        assert pflicht in pfade, pflicht


def test_kein_sidecar_und_kein_store_zugriff_beim_start(
        isolierte_umgebung, personal_aktiv, gestarteter_server, monkeypatch):
    """Das Anhaengen der Routen darf keine Providerspur hinterlassen.

    Kein Sidecar-Prozess, keine Autorisierungsabfrage — die Routen sind
    erreichbar, aber nichts davon laeuft von selbst los.
    """
    import subprocess

    _ohne_engine(monkeypatch)

    CliRunner().invoke(serve, ["--port", "8128"], obj={"quiet": True})

    eigen = subprocess.run(["/bin/ps", "-Ao", "pid,ppid,comm"],
                           capture_output=True, text=True, timeout=30).stdout
    assert "jarvis-contacts" not in eigen
