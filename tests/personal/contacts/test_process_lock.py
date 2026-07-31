"""Prozesssperre `personal/serve.lock` (04 §1 Schritt 1, 07 §5).

Kontaktfrei: kein Sidecar, kein Store, keine Berechtigung.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap

import pytest

from personaljarvis.base.process_lock import LOCK_FILENAME, ProcessLock, ProcessLockError
from personaljarvis.errors import ConfigurationError


def test_erste_sperre_wird_erworben(tmp_path):
    lock = ProcessLock(tmp_path / "personal" / LOCK_FILENAME)
    lock.acquire()
    try:
        assert lock.is_held
        assert lock.path.exists()
    finally:
        lock.release()


def test_zweite_sperre_im_selben_prozess_wird_verweigert(tmp_path):
    path = tmp_path / "personal" / LOCK_FILENAME
    first = ProcessLock(path)
    first.acquire()
    try:
        second = ProcessLock(path)
        with pytest.raises(ProcessLockError):
            second.acquire()
        assert not second.is_held
    finally:
        first.release()


def test_zweite_sperre_im_subprozess_wird_verweigert(tmp_path):
    """Die Sperre gilt prozessuebergreifend — der entscheidende Fall (07 §5)."""
    path = tmp_path / "personal" / LOCK_FILENAME
    first = ProcessLock(path)
    first.acquire()
    try:
        script = textwrap.dedent(
            f"""
            import sys
            sys.path.insert(0, {str(_src_dir())!r})
            from personaljarvis.base.process_lock import ProcessLock, ProcessLockError
            try:
                ProcessLock({str(path)!r}).acquire()
            except ProcessLockError:
                sys.exit(42)
            sys.exit(0)
            """
        )
        proc = subprocess.run([sys.executable, "-c", script], capture_output=True)
        assert proc.returncode == 42, proc.stderr.decode()
    finally:
        first.release()


def test_freigabe_erlaubt_erneuten_erwerb(tmp_path):
    path = tmp_path / "personal" / LOCK_FILENAME
    first = ProcessLock(path)
    first.acquire()
    first.release()
    assert not first.is_held

    second = ProcessLock(path)
    second.acquire()          # darf jetzt gelingen
    try:
        assert second.is_held
    finally:
        second.release()


def test_mehrfache_freigabe_ist_harmlos(tmp_path):
    lock = ProcessLock(tmp_path / "personal" / LOCK_FILENAME)
    lock.acquire()
    lock.release()
    lock.release()            # darf nicht werfen
    assert not lock.is_held


def test_zurueckgebliebene_datei_blockiert_nicht(tmp_path):
    """Eine Lockdatei ohne aktive Sperre darf einen Neustart nie verhindern."""
    path = tmp_path / "personal" / LOCK_FILENAME
    path.parent.mkdir(parents=True)
    path.write_text('{"pid": 999999, "started_at": 0, "port": null}\n')

    lock = ProcessLock(path)
    lock.acquire()            # muss gelingen — die Sperre haengt am Deskriptor
    try:
        assert lock.is_held
    finally:
        lock.release()


def test_veralteter_pid_eintrag_wird_beim_erwerb_ersetzt(tmp_path):
    """Der Neustart raeumt den PID-Eintrag des toten Vorgaengers ab.

    Die Sperre haengt am Dateideskriptor, nicht am Inhalt — ein Neustart
    gelingt also ohnehin (siehe Test darueber). Bliebe der alte Eintrag aber
    stehen, zeigte jede Diagnose danach auf einen Prozess, den es nicht mehr
    gibt: die Datei behauptete einen Halter, der nie geantwortet haette.
    """
    path = tmp_path / "personal" / LOCK_FILENAME
    path.parent.mkdir(parents=True)
    path.write_text('{"pid": 999999, "port": 1, "started_at": 0}\n')

    lock = ProcessLock(path, port=8123)
    lock.acquire()
    try:
        meta = lock.read_metadata()
        assert meta is not None
        assert meta["pid"] == os.getpid(), "die fremde PID steht noch da"
        assert meta["port"] == 8123
        assert meta["started_at"] > 0
        # Kein Rest der alten Zeile: die Datei wird gekuerzt, nicht ueberschrieben.
        assert "999999" not in path.read_text()
    finally:
        lock.release()


def test_rechte_sind_eng(tmp_path):
    lock = ProcessLock(tmp_path / "personal" / LOCK_FILENAME)
    lock.acquire()
    try:
        assert lock.file_mode() == 0o600
        assert (os.stat(lock.path.parent).st_mode & 0o777) == 0o700
    finally:
        lock.release()


def test_metadaten_sind_technisch_und_pii_frei(tmp_path):
    lock = ProcessLock(tmp_path / "personal" / LOCK_FILENAME, port=8123)
    lock.acquire()
    try:
        meta = lock.read_metadata()
        assert meta is not None
        assert set(meta) == {"pid", "started_at", "port"}
        assert meta["pid"] == os.getpid()
        assert meta["port"] == 8123
        blob = json.dumps(meta)
        assert "@" not in blob and os.path.expanduser("~") not in blob
    finally:
        lock.release()


def test_unbenutzbares_verzeichnis_ist_konfigurationsfehler(tmp_path):
    blocker = tmp_path / "personal"
    blocker.write_text("keine Datei-als-Verzeichnis")
    with pytest.raises(ConfigurationError):
        ProcessLock(blocker / LOCK_FILENAME).acquire()


def _src_dir() -> str:
    import personaljarvis
    from pathlib import Path

    return str(Path(personaljarvis.__file__).resolve().parent.parent)
