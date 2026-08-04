"""Bindet die Lebensdauer des Servers an seinen GUI-Elternprozess.

**Anlass (2026-08-04).** Die Desktop-GUI starb mit SIGABRT im nativen
Kontakte-Save. Der Serve-Prozess überlebte sie — die Prozessgruppen-Kopplung
greift nur beim *geordneten* Beenden, ein harter Absturz sendet nichts. Der
Waise hielt Port 8000 und die Personal-Datenbank, und beim nächsten
App-Start hängte sich die GUI an ihn, statt frisch zu booten. Damit lief
`recover_interrupted()` nie — genau die Erholung, auf der die
At-most-once-Zusage des Mutationskanals beruht, war ausgehebelt.

**Warum Polling auf die GUI-PID und nicht `getppid()`.** Der Server wird
über `uv run` gestartet; sein direkter Elternteil ist `uv`, nicht die GUI.
Stirbt die GUI, lebt `uv` weiter — `getppid()` ändert sich nie. Die GUI
reicht deshalb ihre eigene PID ausdrücklich herein.

**Warum die Startzeit mitgeprüft wird.** PIDs werden wiederverwendet. Ein
`kill(pid, 0)` allein sagt nur „irgendein Prozess trägt diese Nummer" — nach
einem Absturz kann das ein völlig fremder sein, und der Waise lebte ewig.
Die Startzeit des Elternprozesses wird deshalb beim Anlauf festgehalten und
bei jedem Puls verglichen: gleiche PID mit anderer Startzeit ist ein
anderer Prozess, also ist der Elternteil tot.

**Was beim Tod geschieht.** SIGTERM an den eigenen Prozess — derselbe Weg
wie beim geordneten Beenden durch die GUI. Kein eigener Abräum-Code, der
neben dem Shutdown-Pfad altern könnte.
"""

from __future__ import annotations

import logging
import os
import signal
import subprocess
import threading
from collections.abc import Callable

__all__ = [
    "GUI_PID_ENV_VAR",
    "POLL_SECONDS",
    "prozess_startzeit",
    "eltern_lebt",
    "start_parent_watchdog",
]

logger = logging.getLogger(__name__)

#: Die GUI setzt ihre PID hier hinein. Fehlt die Variable, gibt es keinen
#: Watchdog — ein direkt gestarteter `jarvis serve` gehört niemandem.
GUI_PID_ENV_VAR = "OPENJARVIS_GUI_PID"

#: Pulsabstand. Zwei Sekunden sind schnell genug, dass kein App-Neustart
#: einen Waisen vorfindet (der Mensch braucht länger bis zum Dock-Klick),
#: und langsam genug, dass das `ps` nicht ins Gewicht fällt.
POLL_SECONDS = 2.0


def prozess_startzeit(pid: int) -> str | None:
    """Startzeit des Prozesses laut `ps`, oder `None` wenn es ihn nicht gibt.

    `lstart` ist auf die Sekunde stabil und ändert sich für einen lebenden
    Prozess nie — genau die Eigenschaft, die eine PID allein nicht hat.
    """
    try:
        ausgabe = subprocess.run(
            ["/bin/ps", "-o", "lstart=", "-p", str(pid)],
            capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        # `ps` selbst kaputt: lieber „lebt noch" annehmen als den Server
        # wegen eines Werkzeugfehlers zu beenden. Der nächste Puls prüft neu.
        return "<ps-unavailable>"
    zeile = ausgabe.stdout.strip()
    return zeile or None


def eltern_lebt(pid: int, startzeit: str) -> bool:
    """Lebt der ursprüngliche Elternprozess noch?

    Falsch heisst: PID verschwunden **oder** von einem anderen Prozess
    wiederverwendet. `<ps-unavailable>` zählt als „lebt" — fail-open in die
    harmlose Richtung, der nächste Puls entscheidet.
    """
    jetzt = prozess_startzeit(pid)
    if jetzt is None:
        return False
    if jetzt == "<ps-unavailable>" or startzeit == "<ps-unavailable>":
        return True
    return jetzt == startzeit


def start_parent_watchdog(
    *,
    environ: dict[str, str] | None = None,
    beenden: Callable[[], None] | None = None,
    poll_seconds: float = POLL_SECONDS,
) -> threading.Thread | None:
    """Startet den Wächter, wenn eine GUI-PID übergeben wurde.

    Gibt den Daemon-Thread zurück (für Tests), sonst `None`. `beenden` ist
    injizierbar; produktiv ist es SIGTERM an den eigenen Prozess.
    """
    env = os.environ if environ is None else environ
    roh = env.get(GUI_PID_ENV_VAR, "").strip()
    if not roh:
        return None
    try:
        gui_pid = int(roh)
    except ValueError:
        logger.warning("%s ist keine PID: %r", GUI_PID_ENV_VAR, roh)
        return None

    startzeit = prozess_startzeit(gui_pid)
    if startzeit is None:
        # Die GUI ist schon tot, bevor der Server fertig gebootet hat —
        # dann gibt es niemanden, dem dieser Server gehört.
        logger.warning("GUI-Prozess %d existiert nicht mehr; beende sofort",
                       gui_pid)
        (beenden or _selbst_beenden)()
        return None

    stop = beenden or _selbst_beenden

    def _wache() -> None:
        ereignis = threading.Event()
        while True:
            ereignis.wait(poll_seconds)
            if not eltern_lebt(gui_pid, startzeit):
                logger.warning(
                    "GUI-Prozess %d ist weg (Absturz oder PID-Wiederverwendung); "
                    "beende den Server über den regulären SIGTERM-Pfad", gui_pid)
                stop()
                return

    faden = threading.Thread(target=_wache, name="gui-parent-watchdog",
                             daemon=True)
    faden.start()
    return faden


def _selbst_beenden() -> None:
    os.kill(os.getpid(), signal.SIGTERM)
