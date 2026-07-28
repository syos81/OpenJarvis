"""Modul-Lebenszyklus und Bootstrap. Kontaktfrei.

Diese Suite belegt zusätzlich ausdrücklich, dass Gate A **keinen** Sidecar
startet, **keine** TCC-Abfrage auslöst und **keinen** Contacts-Store berührt.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from personaljarvis.bootstrap import PersonalBootstrap
from personaljarvis.contacts.lifecycle import ContactsModule, ModuleState
from personaljarvis.errors import LedgerError, PersonalJarvisError

REPO_ROOT = Path(__file__).resolve().parents[3]
QUELLEN = REPO_ROOT / "src/personaljarvis"


# ── Start / Stop ─────────────────────────────────────────────────────────────
def test_start_migriert_und_meldet_configuration_required(db_path):
    m = ContactsModule(db_path)
    report = m.start()
    try:
        assert report.applied == ("0001", "0002", "0003")
        # Ohne ProviderAccount und Binding ist das Modul nicht `ready` (14 §4).
        assert m.state is ModuleState.CONFIGURATION_REQUIRED
        assert m.capabilities.notes_supported is False
    finally:
        m.stop()


def test_mehrfacher_start_ist_idempotent(db_path):
    m = ContactsModule(db_path)
    erster = m.start()
    zweiter = m.start()
    try:
        assert erster is zweiter
        assert zweiter.applied == ("0001", "0002", "0003")
    finally:
        m.stop()


def test_stop_setzt_zustand_zurueck(db_path):
    m = ContactsModule(db_path)
    m.start()
    m.stop()
    assert m.state is ModuleState.NOT_INSTALLED
    with pytest.raises(PersonalJarvisError, match="nicht gestartet"):
        m.unit_of_work()


def test_stop_ohne_start_ist_harmlos(db_path):
    ContactsModule(db_path).stop()


def test_capabilities_vor_dem_start_nicht_abrufbar(db_path):
    with pytest.raises(PersonalJarvisError, match="nicht gestartet"):
        _ = ContactsModule(db_path).capabilities


def test_repositories_teilen_die_unit_of_work(module):
    with module.unit_of_work() as uow:
        repos = module.repositories(uow)
        verbindungen = {
            repos.contacts._conn, repos.roles._conn, repos.external_ids._conn,
            repos.field_availability._conn, repos.sync_state._conn,
            repos.tombstones._conn, repos.mutations._conn,
            repos.organizations._conn,
        }
        assert len(verbindungen) == 1
        assert verbindungen.pop() is uow.connection


# ── Fail-closed ──────────────────────────────────────────────────────────────
def test_ledgerfehler_verhindert_den_start(db_path):
    from personaljarvis.base.db.migrations import LEDGER_TABLE

    erster = ContactsModule(db_path)
    erster.start()
    erster.connection_factory.connect().execute(
        f"UPDATE {LEDGER_TABLE} SET checksum = ? WHERE migration_id = '0001'",
        ("0" * 64,))
    erster.stop()

    zweiter = ContactsModule(db_path)
    with pytest.raises(LedgerError):
        zweiter.start()
    assert zweiter.state is ModuleState.MIGRATION_REQUIRED
    with pytest.raises(PersonalJarvisError, match="nicht gestartet"):
        zweiter.unit_of_work()


def test_bootstrap_hinterlaesst_keine_teilregistrierung(tmp_path, monkeypatch):
    from personaljarvis.base.db import migrations as mig
    from personaljarvis.errors import MigrationError

    def boom(self):
        raise MigrationError("simuliert")

    monkeypatch.setattr(mig.MigrationRunner, "run", boom)
    bootstrap = PersonalBootstrap(tmp_path / "x.db")
    with pytest.raises(MigrationError):
        bootstrap.start()
    assert bootstrap.runtime is None


def test_bootstrap_start_ist_idempotent(db_path):
    bootstrap = PersonalBootstrap(db_path)
    try:
        assert bootstrap.start() is bootstrap.start()
    finally:
        bootstrap.stop()


def test_bootstrap_meldet_niemals_ready_in_gate_a(db_path):
    bootstrap = PersonalBootstrap(db_path)
    runtime = bootstrap.start()
    try:
        assert runtime.is_ready is False
        assert runtime.module_states == {
            "contacts": ModuleState.CONFIGURATION_REQUIRED}
    finally:
        bootstrap.stop()


def test_bootstrap_stop_ist_wiederholbar(db_path):
    bootstrap = PersonalBootstrap(db_path)
    bootstrap.start()
    bootstrap.stop()
    bootstrap.stop()
    assert bootstrap.runtime is None


# ── Kontaktfreiheit, strukturell belegt ──────────────────────────────────────
VERBOTENE_BEGRIFFE = (
    "CNContact", "CNContactStore", "requestAuthorization", "TCC",
    "jarvis-contacts", "enumerateProbe", "isolationSummary",
    "JarvisContactsSpike", "subprocess.Popen",
)


def test_gate_a_quellen_enthalten_keine_bridge_begriffe():
    treffer = []
    for datei in QUELLEN.rglob("*.py"):
        text = datei.read_text()
        for begriff in VERBOTENE_BEGRIFFE:
            if begriff in text:
                treffer.append(f"{datei.relative_to(REPO_ROOT)}: {begriff}")
    assert not treffer, treffer


def test_gate_a_haengt_nicht_von_spikes_ab():
    for datei in QUELLEN.rglob("*.py"):
        text = datei.read_text()
        assert "spikes" not in text, datei
        assert "contacts-bridge-g3a" not in text, datei


def test_gate_a_startet_keinen_prozess():
    for datei in QUELLEN.rglob("*.py"):
        text = datei.read_text()
        for begriff in ("import subprocess", "os.system", "os.exec", "Popen"):
            assert begriff not in text, f"{datei}: {begriff}"


def test_kein_sidecar_prozess_nach_dem_lauf(module):
    """Belegt zur Laufzeit: es läuft kein Kontakte-Sidecar."""
    ergebnis = subprocess.run(["/bin/ps", "-Ao", "comm"], capture_output=True,
                              text=True)
    assert "jarvis-contacts" not in ergebnis.stdout


def test_module_haelt_nur_die_datenbank_offen(module):
    """Nach dem Start existiert genau eine Datenbankdatei, sonst nichts."""
    verzeichnis = Path(module.connection_factory.database_path).parent
    dateien = {p.name.split("-")[0] for p in verzeichnis.iterdir()}
    assert dateien <= {"jarvis.db", "jarvis.db"}, sorted(
        p.name for p in verzeichnis.iterdir())
