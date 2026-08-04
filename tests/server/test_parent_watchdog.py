"""Der GUI-Eltern-Wächter: normales Beenden, harter Absturz, PID-Wiederverwendung.

Kontaktfrei und ohne Netz. Die „GUI" ist hier ein wegwerfbarer
`sleep`-Kindprozess; getötet wird ausschliesslich er. Der Wächter läuft mit
injiziertem `beenden` — kein Test sendet ein Signal an den Testprozess.
"""

from __future__ import annotations

import os
import signal
import subprocess
import threading
import time

from openjarvis.server.parent_watchdog import (
    GUI_PID_ENV_VAR,
    eltern_lebt,
    prozess_startzeit,
    start_parent_watchdog,
)


def _gui_attrappe() -> subprocess.Popen:
    return subprocess.Popen(["/bin/sleep", "300"])


def _warte_bis(pruefung, sekunden: float = 10.0) -> bool:
    ende = time.monotonic() + sekunden
    while time.monotonic() < ende:
        if pruefung():
            return True
        time.sleep(0.05)
    return False


# ═══ A · Bausteine ══════════════════════════════════════════════════════════
def test_startzeit_eines_lebenden_prozesses_ist_stabil():
    gui = _gui_attrappe()
    try:
        erste = prozess_startzeit(gui.pid)
        zweite = prozess_startzeit(gui.pid)
        assert erste is not None
        assert erste == zweite
    finally:
        gui.terminate()
        gui.wait()


def test_ein_toter_prozess_hat_keine_startzeit():
    gui = _gui_attrappe()
    gui.terminate()
    gui.wait()
    assert _warte_bis(lambda: prozess_startzeit(gui.pid) is None)


def test_pid_wiederverwendung_wird_erkannt():
    """Gleiche PID, andere Startzeit — der Elternteil ist tot.

    Eine echte Wiederverwendung lässt sich nicht deterministisch erzwingen;
    geprüft wird die Entscheidungsfunktion mit genau den Werten, die dabei
    entstehen: die festgehaltene Startzeit des Originals gegen die Startzeit
    eines **anderen** Prozesses unter „derselben" Nummer.
    """
    original = _gui_attrappe()
    try:
        alt = prozess_startzeit(original.pid)
        original.terminate()
        original.wait()
        # lstart hat Sekundenauflösung: der „Nachnutzer" muss in einer
        # anderen Sekunde geboren sein, sonst ist er vom Original nicht
        # unterscheidbar — wie in der Wirklichkeit auch.
        time.sleep(1.1)
        nachnutzer = _gui_attrappe()
        # Der Nachnutzer steht stellvertretend für einen fremden Prozess,
        # der die Nummer übernommen hat.
        assert eltern_lebt(nachnutzer.pid, alt) is False
    finally:
        nachnutzer.terminate()
        nachnutzer.wait()
        if original.poll() is None:
            original.terminate()
        original.wait()


# ═══ B · Der Wächter ════════════════════════════════════════════════════════
def test_harter_absturz_beendet_den_server():
    """SIGKILL an die GUI — kein geordnetes Beenden, keine Signale an Kinder."""
    gui = _gui_attrappe()
    beendet = threading.Event()
    faden = start_parent_watchdog(
        environ={GUI_PID_ENV_VAR: str(gui.pid)},
        beenden=beendet.set, poll_seconds=0.1)
    assert faden is not None
    try:
        assert not beendet.wait(0.5), "beendet, obwohl die GUI lebt"
        os.kill(gui.pid, signal.SIGKILL)
        gui.wait()
        assert beendet.wait(10), "Absturz der GUI nicht erkannt"
    finally:
        if gui.poll() is None:
            gui.terminate()
        gui.wait()


def test_normales_beenden_der_gui_wird_ebenfalls_erkannt():
    """Auch ein geordnetes Ende der GUI lässt den Server nicht zurück.

    Im Normalfall kommt das SIGTERM der Prozessgruppe zuerst — der Wächter
    ist dann schon tot. Er ist die Rückfallebene, kein Ersatz.
    """
    gui = _gui_attrappe()
    beendet = threading.Event()
    start_parent_watchdog(environ={GUI_PID_ENV_VAR: str(gui.pid)},
                          beenden=beendet.set, poll_seconds=0.1)
    gui.terminate()
    gui.wait()
    assert beendet.wait(10)


def test_bereits_tote_gui_beendet_sofort():
    gui = _gui_attrappe()
    gui.kill()
    gui.wait()
    assert _warte_bis(lambda: prozess_startzeit(gui.pid) is None)
    beendet = threading.Event()
    faden = start_parent_watchdog(
        environ={GUI_PID_ENV_VAR: str(gui.pid)},
        beenden=beendet.set, poll_seconds=0.1)
    assert faden is None
    assert beendet.is_set()


def test_ohne_gui_pid_gibt_es_keinen_waechter():
    """Ein direkt gestarteter `jarvis serve` gehört niemandem."""
    beendet = threading.Event()
    assert start_parent_watchdog(environ={}, beenden=beendet.set) is None
    assert not beendet.is_set()


def test_unbrauchbare_pid_wird_ignoriert():
    beendet = threading.Event()
    assert start_parent_watchdog(
        environ={GUI_PID_ENV_VAR: "keine-zahl"}, beenden=beendet.set) is None
    assert not beendet.is_set()
