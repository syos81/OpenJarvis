"""Shutdown-Hook, Eigentümerreferenz und Bridge-Lifecycle (Gate-A-Audit, Gate B).

Kontaktfrei: keine Route, kein Sidecar-Start ausser dem ausdruecklichen
`check_bridge()`, kein Store-Zugriff, kein `requestAuthorization`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import personaljarvis
from personaljarvis.base.process_lock import LOCK_FILENAME, ProcessLockError
from personaljarvis.bootstrap import PersonalBootstrap
from personaljarvis.contacts.lifecycle import ContactsModule, ModuleState


class FakeState:
    pass


class FakeApp:
    """Minimale FastAPI-Attrappe: `state` und `add_event_handler`."""

    def __init__(self) -> None:
        self.state = FakeState()
        self.handlers: list[tuple[str, object]] = []

    def add_event_handler(self, event: str, func) -> None:
        self.handlers.append((event, func))


def _paths(tmp_path):
    return {"database_path": str(tmp_path / "jarvis.db"),
            "lock_path": str(tmp_path / "personal" / LOCK_FILENAME)}


# ── Shutdown-Hook ───────────────────────────────────────────────────────────
def test_genau_ein_shutdown_hook(tmp_path):
    app = FakeApp()
    personaljarvis.attach(app, **_paths(tmp_path))
    try:
        shutdown = [h for e, h in app.handlers if e == "shutdown"]
        assert len(shutdown) == 1
    finally:
        app.state.personal_bootstrap.stop()


def test_hook_stoppt_modul_und_gibt_sperre_frei(tmp_path):
    app = FakeApp()
    personaljarvis.attach(app, **_paths(tmp_path))
    bootstrap = app.state.personal_bootstrap
    assert bootstrap.process_lock is not None
    assert bootstrap.process_lock.is_held

    handler = next(h for e, h in app.handlers if e == "shutdown")
    handler()
    assert bootstrap.runtime is None
    # Die Sperre ist frei: ein neuer Bootstrap darf sie erwerben.
    second = PersonalBootstrap(**_paths(tmp_path))
    second.start()
    second.stop()


def test_mehrfacher_shutdown_ist_harmlos(tmp_path):
    app = FakeApp()
    personaljarvis.attach(app, **_paths(tmp_path))
    handler = next(h for e, h in app.handlers if e == "shutdown")
    handler()
    handler()          # darf nicht werfen
    handler()


def test_zweites_attach_auf_dieselbe_app_ist_fail_closed(tmp_path):
    app = FakeApp()
    personaljarvis.attach(app, **_paths(tmp_path))
    try:
        with pytest.raises(personaljarvis.PersonalAlreadyAttached):
            personaljarvis.attach(app, **_paths(tmp_path))
        # Es bleibt bei genau einem Hook.
        assert len([h for e, h in app.handlers if e == "shutdown"]) == 1
    finally:
        app.state.personal_bootstrap.stop()


def test_zwei_apps_starten_keinen_zweiten_schreiber(tmp_path):
    """Zwei App-Instanzen auf demselben Datenverzeichnis: die zweite scheitert."""
    paths = _paths(tmp_path)
    first = FakeApp()
    personaljarvis.attach(first, **paths)
    try:
        second = FakeApp()
        with pytest.raises(ProcessLockError):
            personaljarvis.attach(second, **paths)
        assert getattr(second.state, "personal_bootstrap", None) is None
    finally:
        first.state.personal_bootstrap.stop()


def test_fehlgeschlagener_start_gibt_sperre_frei(tmp_path):
    """Ein Bootstrapfehler darf die Sperre nicht dauerhaft halten."""
    db = tmp_path / "unbrauchbar"
    db.mkdir()                       # Verzeichnis statt Datei ⇒ Start scheitert
    paths = {"database_path": str(db),
             "lock_path": str(tmp_path / "personal" / LOCK_FILENAME)}
    bootstrap = PersonalBootstrap(**paths)
    with pytest.raises(Exception):
        bootstrap.start()
    assert bootstrap.process_lock is None

    # Die Sperre ist frei — ein gesunder Start gelingt danach.
    healthy = PersonalBootstrap(database_path=str(tmp_path / "jarvis.db"),
                                lock_path=paths["lock_path"])
    healthy.start()
    healthy.stop()


def test_personal_deaktiviert_veraendert_nichts():
    """Ohne Feature-Schalter passiert nichts (DEV-3)."""
    assert personaljarvis.is_enabled({}) is False
    assert personaljarvis.is_enabled({personaljarvis.ENABLE_ENV_VAR: "1"}) is True


# ── Bridge-Lifecycle ────────────────────────────────────────────────────────
def test_konstruktor_startet_keinen_sidecar(tmp_path):
    module = ContactsModule(str(tmp_path / "jarvis.db"),
                            sidecar_path=str(tmp_path / "gibt-es-nicht"))
    assert module.bridge_status is None, "kein Start im Konstruktor"


def test_fehlendes_binary_ergibt_degraded(tmp_path):
    module = ContactsModule(str(tmp_path / "jarvis.db"),
                            sidecar_path=str(tmp_path / "gibt-es-nicht"))
    module.start()
    try:
        status = module.check_bridge()
        assert status.available is False
        assert module.state is ModuleState.DEGRADED
        assert "nicht gefunden" in status.reason
    finally:
        module.stop()


def test_kontaktfreier_startcheck_gegen_echten_sidecar(tmp_path):
    native = _native_sidecar()
    if native is None:
        pytest.skip("nativer Sidecar nicht gebaut")
    module = ContactsModule(str(tmp_path / "jarvis.db"), sidecar_path=str(native))
    module.start()
    try:
        status = module.check_bridge()
        assert status.available is True
        assert status.protocol_version == 1
        assert status.capabilities is not None
        assert status.capabilities.notes_supported is False
        # Ohne erteilte Berechtigung ist der benannte Zustand
        # `permission_required` — nie `ready` (14 §4).
        assert module.state in (ModuleState.PERMISSION_REQUIRED,
                                ModuleState.CONFIGURATION_REQUIRED)
    finally:
        module.stop()


def test_modul_meldet_niemals_ready(tmp_path):
    """Gate B endet vor dem Initialimport — es gibt keinen `ready`-Zustand."""
    bootstrap = PersonalBootstrap(**_paths(tmp_path))
    runtime = bootstrap.start()
    try:
        assert runtime.is_ready is False
        assert ModuleState.NOT_INSTALLED not in (runtime.module_states["contacts"],)
    finally:
        bootstrap.stop()


def _native_sidecar() -> Path | None:
    """Ein gebautes Artefakt der Hostarchitektur — es wird nie gebaut.

    Vorrang hat das Tauri-Paketartefakt `binaries/jarvis-contacts-<triple>`;
    danach die Build-Verzeichnisse beider Aufrufwege (`build.sh` direkt bzw.
    `scripts/build-contacts-sidecar.sh`).
    """
    from personaljarvis.contacts.bridge.resolver import (
        BINARY_NAME, binary_architectures, host_architecture, tauri_triple,
    )

    repo = Path(__file__).resolve().parents[3]
    base = repo / "native" / "contacts-bridge"
    arch = host_architecture()
    triple = tauri_triple(arch)
    for cand in (
        repo / "frontend" / "src-tauri" / "binaries" / f"{BINARY_NAME}-{triple}",
        base / f"build-{triple}" / BINARY_NAME,
        base / f"build-{arch}" / BINARY_NAME,
        base / "build" / BINARY_NAME,
    ):
        if cand.exists() and arch in binary_architectures(cand):
            return cand
    return None
