"""Paketierung, Feature-Schalter und Integrationspunkt (DEV-3, DEV-5).

Kontaktfrei: kein Sidecar, keine Store-Operation, kein TCC.
"""

from __future__ import annotations

import subprocess
import sys
import tomllib
import zipfile
from pathlib import Path

import pytest

import personaljarvis

REPO_ROOT = Path(__file__).resolve().parents[3]


class _FakeState:
    pass


class _FakeApp:
    def __init__(self) -> None:
        self.state = _FakeState()


# ── Feature-Schalter ─────────────────────────────────────────────────────────
def test_schalter_ist_standardmaessig_aus():
    assert personaljarvis.is_enabled({}) is False


@pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", "on", " on "])
def test_schalter_erkennt_truthy_werte(value):
    assert personaljarvis.is_enabled({personaljarvis.ENABLE_ENV_VAR: value}) is True


@pytest.mark.parametrize("value", ["", "0", "false", "no", "off", "vielleicht"])
def test_schalter_lehnt_alles_andere_ab(value):
    assert personaljarvis.is_enabled({personaljarvis.ENABLE_ENV_VAR: value}) is False


def test_schaltername_folgt_der_repository_konvention():
    assert personaljarvis.ENABLE_ENV_VAR.startswith("OPENJARVIS_")


# ── Import ohne Nebenwirkung ─────────────────────────────────────────────────
def test_import_startet_nichts(tmp_path):
    """`import personaljarvis` darf keine Datei und kein Verzeichnis anlegen."""
    marker = tmp_path / "leer"
    marker.mkdir()
    code = (
        "import personaljarvis, personaljarvis.contacts, "
        "personaljarvis.contacts.domain, personaljarvis.base.db; print('ok')"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True,
        cwd=str(marker), env={"PATH": "/usr/bin:/bin", "HOME": str(tmp_path),
                              "PYTHONPATH": str(REPO_ROOT / "src")},
    )
    assert result.returncode == 0, result.stderr
    assert "ok" in result.stdout
    assert list(marker.iterdir()) == []


# ── attach ───────────────────────────────────────────────────────────────────
def test_attach_haengt_laufzeit_an_und_registriert_keine_route(db_path):
    app = _FakeApp()
    runtime = personaljarvis.attach(app, database_path=str(db_path))
    try:
        assert app.state.personal_runtime is runtime
        assert runtime.contacts.migration_report is not None
        # Gate A meldet niemals ready — es gibt weder Route noch Adapter.
        assert runtime.is_ready is False
        assert not hasattr(app, "routes")
    finally:
        app.state.personal_bootstrap.stop()


def test_attach_reicht_migrationsfehler_weiter(tmp_path, monkeypatch):
    from personaljarvis.base.db import migrations as mig
    from personaljarvis.errors import MigrationError

    def boom(self):
        raise MigrationError("simulierter Schemafehler")

    monkeypatch.setattr(mig.MigrationRunner, "run", boom)
    app = _FakeApp()
    with pytest.raises(MigrationError):
        personaljarvis.attach(app, database_path=str(tmp_path / "x.db"))
    assert not hasattr(app.state, "personal_runtime")


# ── Integrationspunkt in der App-Factory ─────────────────────────────────────
def test_app_factory_ruft_attach_bei_deaktiviertem_personal_nicht(monkeypatch):
    from openjarvis.server import app as app_module

    calls: list = []
    monkeypatch.setattr(personaljarvis, "attach", lambda a, **k: calls.append(a))
    monkeypatch.delenv(personaljarvis.ENABLE_ENV_VAR, raising=False)
    app_module._attach_personal_jarvis(_FakeApp())
    assert calls == []


def test_app_factory_ruft_attach_genau_einmal(monkeypatch):
    from openjarvis.server import app as app_module

    calls: list = []
    monkeypatch.setattr(personaljarvis, "attach", lambda a, **k: calls.append(a))
    monkeypatch.setenv(personaljarvis.ENABLE_ENV_VAR, "1")
    app = _FakeApp()
    app_module._attach_personal_jarvis(app)
    assert calls == [app]


def test_app_factory_fehlendes_paket_ist_fehler_wenn_aktiviert(monkeypatch):
    """Aktiviert, aber nicht installiert ⇒ Fehler, kein stiller Rückfall."""
    import builtins

    from openjarvis.server import app as app_module

    real_import = builtins.__import__

    def blocked(name, *args, **kwargs):
        if name == "personaljarvis":
            raise ImportError("simuliert nicht installiert")
        return real_import(name, *args, **kwargs)

    monkeypatch.setenv(personaljarvis.ENABLE_ENV_VAR, "1")
    monkeypatch.setattr(builtins, "__import__", blocked)
    with pytest.raises(RuntimeError, match="nicht installiert"):
        app_module._attach_personal_jarvis(_FakeApp())


def test_app_factory_verschluckt_schemafehler_nicht(monkeypatch):
    from openjarvis.server import app as app_module
    from personaljarvis.errors import LedgerError

    def boom(app, **kwargs):
        raise LedgerError("simulierte Ledger-Abweichung")

    monkeypatch.setenv(personaljarvis.ENABLE_ENV_VAR, "1")
    monkeypatch.setattr(personaljarvis, "attach", boom)
    with pytest.raises(LedgerError):
        app_module._attach_personal_jarvis(_FakeApp())


def test_app_factory_attach_ende_zu_ende(tmp_path, monkeypatch):
    """Audit-Befund Testqualität: der Integrationspunkt lief bisher nur mit
    gepatchtem `attach`. Hier läuft er echt — mit realem Bootstrap, realen
    Migrationen und einer echten Datenbank unter OPENJARVIS_HOME."""
    from openjarvis.server import app as app_module

    monkeypatch.setenv("OPENJARVIS_HOME", str(tmp_path))
    monkeypatch.setenv(personaljarvis.ENABLE_ENV_VAR, "1")
    app = _FakeApp()
    app_module._attach_personal_jarvis(app)
    try:
        runtime = app.state.personal_runtime
        assert runtime.contacts.migration_report is not None
        assert runtime.contacts.migration_report.applied[0] == "0001"
        db = tmp_path / "personal" / "jarvis.db"
        assert db.exists()
        import stat as stat_module

        assert stat_module.S_IMODE(db.stat().st_mode) == 0o600
    finally:
        app.state.personal_bootstrap.stop()


def test_integrationspunkt_ist_genau_eine_stelle():
    source = (REPO_ROOT / "src/openjarvis/server/app.py").read_text()
    assert source.count("personaljarvis.attach(app)") == 1
    assert source.count("_attach_personal_jarvis(app)") == 1


# ── pyproject / Wheel ────────────────────────────────────────────────────────
def _pyproject() -> dict:
    return tomllib.loads((REPO_ROOT / "pyproject.toml").read_text())


def test_dependency_group_personal_existiert_und_ist_leer():
    groups = _pyproject()["dependency-groups"]
    assert "personal" in groups
    # Gate A kommt mit der Standardbibliothek aus — nichts vorziehen.
    assert groups["personal"] == []


def test_bestehende_gruppen_und_extras_unveraendert():
    data = _pyproject()
    groups = data["dependency-groups"]
    assert groups["dev"] == ["maturin>=1.12.6"]
    assert groups["desktop-native"] == ["openjarvis-rust"]
    assert "personal" not in data["project"].get("optional-dependencies", {})


def test_wheel_konfiguration_enthaelt_beide_pakete():
    packages = _pyproject()["tool"]["hatch"]["build"]["targets"]["wheel"]["packages"]
    assert "src/openjarvis" in packages
    assert "src/personaljarvis" in packages


def test_lockfile_kennt_die_personal_gruppe():
    lock = (REPO_ROOT / "uv.lock").read_text()
    assert "personal = []" in lock


@pytest.mark.slow
def test_wheel_enthaelt_personaljarvis(tmp_path):
    """Baut ein Wheel und prüft seinen Inhalt statisch."""
    out = tmp_path / "dist"
    result = subprocess.run(
        ["uv", "build", "--wheel", "--out-dir", str(out)],
        cwd=str(REPO_ROOT), capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    wheels = list(out.glob("*.whl"))
    assert len(wheels) == 1
    names = zipfile.ZipFile(wheels[0]).namelist()
    assert "personaljarvis/__init__.py" in names
    assert "personaljarvis/contacts/__init__.py" in names
    assert "personaljarvis/contacts/lifecycle.py" in names
    assert "personaljarvis/base/db/migrations/versions/m0002_contacts.py" in names
    assert (
        "personaljarvis/base/db/migrations/versions/"
        "m0003_contacts_child_constraints.py" in names
    )
    # Das bestehende Paket bleibt vollständig enthalten.
    assert any(n.startswith("openjarvis/") for n in names)
    assert "openjarvis/server/app.py" in names
