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
#: Die Native-Bridge ist die Adapterschicht (AV-4, ADR-0016): genau dort —
#: und nur dort — sind Apple-Begriffe und Prozessverwaltung zulaessig.
BRIDGE = QUELLEN / "contacts" / "bridge"


def _python_code_ohne_prosa(path: Path) -> str:
    """Python-Quelltext ohne Kommentare und Zeichenkettenliterale.

    Die Verbote stehen als Kommentar oder Docstring IM Produktivcode
    ("kein `shell=True`", "kein `requestAuthorization`"). Eine reine Textsuche
    wuerde genau diese Abgrenzungsnotizen als Verstoss melden. Geprueft wird
    deshalb ausschliesslich echter Code.
    """
    import io
    import tokenize

    stuecke = []
    with open(path, "rb") as fh:
        try:
            for tok in tokenize.tokenize(fh.readline):
                if tok.type in (tokenize.COMMENT, tokenize.STRING):
                    continue
                stuecke.append(tok.string)
        except tokenize.TokenError:            # pragma: no cover
            return path.read_text()
    return " ".join(stuecke)


def _kernquellen():
    """Alle Produktivdateien AUSSER der Bridge."""
    return [d for d in QUELLEN.rglob("*.py") if BRIDGE not in d.parents]


# ── Start / Stop ─────────────────────────────────────────────────────────────
def test_start_migriert_und_meldet_configuration_required(db_path):
    m = ContactsModule(db_path)
    report = m.start()
    try:
        assert report.applied == ("0001", "0002", "0003", "0004")
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
        assert zweiter.applied == ("0001", "0002", "0003", "0004")
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


def test_kern_enthaelt_keine_bridge_begriffe():
    """Der Fachkern bleibt frei von Apple- und Prozessbegriffen (AV-4).

    Die Native-Bridge ist davon ausgenommen: sie **ist** die Adapterschicht.
    """
    treffer = []
    for datei in _kernquellen():
        code = _python_code_ohne_prosa(datei)
        for begriff in VERBOTENE_BEGRIFFE:
            if begriff in code:
                treffer.append(f"{datei.relative_to(REPO_ROOT)}: {begriff}")
    assert not treffer, treffer


def test_produktivcode_importiert_keine_spikes():
    """Kein Produktmodul darf `spikes/` als Laufzeitabhaengigkeit nutzen.

    Geprueft werden echte Bezuege — Importe und Pfadangaben —, nicht die
    blosse Erwaehnung des Wortes in einem erlaeuternden Kommentar.
    """
    for datei in QUELLEN.rglob("*.py"):
        text = datei.read_text()
        for muster in ("import spikes", "from spikes", '"spikes/', "'spikes/",
                       "contacts-bridge-g3a"):
            assert muster not in text, f"{datei.relative_to(REPO_ROOT)}: {muster}"


def test_nur_die_bridge_startet_prozesse():
    """Prozessverwaltung ist ausschliesslich in der Bridge zulaessig.

    Der Fachkern startet weiterhin **keinen** Prozess; die Bridge kapselt den
    Sidecar-Start vollstaendig (ADR-0016, Plan §12).
    """
    for datei in _kernquellen():
        code = _python_code_ohne_prosa(datei)
        for begriff in ("subprocess", "os.system", "os.exec", "Popen"):
            assert begriff not in code, f"{datei.relative_to(REPO_ROOT)}: {begriff}"


def test_bridge_verwendet_keine_shell():
    """Auch die Bridge startet nie ueber eine Shell (feste Argumentliste)."""
    for datei in BRIDGE.rglob("*.py"):
        code = _python_code_ohne_prosa(datei)
        assert "shell=True" not in code.replace(" ", ""), datei.relative_to(REPO_ROOT)
        assert "os.system" not in code.replace(" ", ""), datei.relative_to(REPO_ROOT)


def test_kein_sidecar_prozess_nach_dem_lauf(module):
    """Belegt zur Laufzeit: das Modul startet keinen Kontakte-Sidecar.

    Geprueft wird der **eigene Prozessbaum**, nicht die globale Prozesstabelle:
    seit Gate B starten andere Testmodule den Sidecar legitim fuer den
    kontaktfreien Handshake, und `pytest -n auto` laesst sie parallel laufen.
    Ein globaler Scan wuerde dort fremde, korrekte Prozesse als Verstoss melden.
    """
    import os

    ergebnis = subprocess.run(["/bin/ps", "-Ao", "pid,ppid,comm"],
                              capture_output=True, text=True)
    eigene = {os.getpid()}
    kinder = []
    for zeile in ergebnis.stdout.splitlines()[1:]:
        teile = zeile.split(None, 2)
        if len(teile) < 3:
            continue
        pid, ppid, comm = teile
        if ppid.isdigit() and int(ppid) in eigene:
            eigene.add(int(pid))
            kinder.append(comm.strip())
    assert not any("jarvis-contacts" in c for c in kinder), kinder


def test_module_haelt_nur_die_datenbank_offen(module):
    """Nach dem Start existiert genau eine Datenbankdatei, sonst nichts."""
    verzeichnis = Path(module.connection_factory.database_path).parent
    dateien = {p.name.split("-")[0] for p in verzeichnis.iterdir()}
    assert dateien <= {"jarvis.db", "jarvis.db"}, sorted(
        p.name for p in verzeichnis.iterdir())
