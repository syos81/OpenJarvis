"""Personal Jarvis — Fachmodule über OpenJarvis (Architektur-Baseline v3).

Der Import dieses Pakets hat **keine** Nebenwirkung: keine Datenbank, keine
Verbindung, kein Verzeichnis, kein Prozess, keine Berechtigungsabfrage.
`import personaljarvis` allein startet nichts.

Die einzige öffentliche Funktion ist `attach(app)` — der eine bewachte
Integrationspunkt aus 04 §4 (Abweichung DEV-3).
"""

from __future__ import annotations

import os
from typing import Any

__all__ = ["attach", "is_enabled", "ENABLE_ENV_VAR", "PersonalNotEnabled",
           "PersonalAlreadyAttached"]

#: Feature-Schalter. Folgt der bestehenden Repository-Konvention: Präfix
#: ``OPENJARVIS_``, Truthy-Werte ``1``/``true``/``yes``/``on`` (Muster aus
#: ``openjarvis/cli/_version_check.py``). **Standard: deaktiviert.** Es gibt
#: keinen stillen Aktivierungsweg — ohne diese Variable passiert nichts.
ENABLE_ENV_VAR = "OPENJARVIS_PERSONAL_ENABLED"

_TRUTHY = ("1", "true", "yes", "on")


class PersonalNotEnabled(RuntimeError):
    """Personal wurde angefordert, ist aber nicht aktiviert."""


def is_enabled(environ: dict[str, str] | None = None) -> bool:
    """Ob Personal Jarvis ausdrücklich aktiviert wurde.

    `environ` ist injizierbar, damit der Schalter deterministisch testbar ist.
    """
    env = os.environ if environ is None else environ
    return env.get(ENABLE_ENV_VAR, "").strip().lower() in _TRUTHY


#: Marker auf ``app.state``: genau **ein** Shutdown-Hook je App.
_SHUTDOWN_HOOK_ATTR = "personal_shutdown_registered"


class PersonalAlreadyAttached(RuntimeError):
    """``attach`` wurde zweimal auf dieselbe App angewandt."""


def _register_shutdown_hook(app: Any, bootstrap: Any) -> bool:
    """Registriert **genau einen** Shutdown-Hook je App.

    Der Hook stoppt ``ContactsModule`` und gibt danach die exklusive
    Prozesssperre frei. Er ist idempotent, weil ``PersonalBootstrap.stop()``
    idempotent ist — ein doppelter Shutdown bleibt harmlos.
    """
    state = getattr(app, "state", None)
    if state is not None and getattr(state, _SHUTDOWN_HOOK_ATTR, False):
        return False

    handler = getattr(app, "add_event_handler", None)
    if callable(handler):
        handler("shutdown", bootstrap.stop)
        if state is not None:
            setattr(state, _SHUTDOWN_HOOK_ATTR, True)
        return True
    return False


def attach(app: Any, *, database_path: str | None = None,
           lock_path: str | None = None,
           sidecar_path: str | None = None,
           bundle_dir: str | None = None) -> Any:
    """Hängt Personal Jarvis an eine bestehende FastAPI-App.

    Verhalten (04 §4, fail-closed):

    * Der Bootstrap läuft vollständig durch, bevor irgendetwas registriert wird
      — einschließlich der exklusiven Prozesssperre (04 §1 Schritt 1).
    * Schlägt Sperre, Migration oder Schema fehl, wird der Fehler
      **weitergereicht** — er wird nicht protokolliert und geschluckt. Eine
      bereits erworbene Sperre wird dabei wieder freigegeben.
    * **Ein zweites ``attach`` auf dieselbe App ist fail-closed** und wird
      abgewiesen: zwei Bootstraps auf einer App hätten zwei Eigentümer für
      dieselbe Sperre.
    * ``app.state.personal_bootstrap`` bleibt die Eigentümerreferenz; genau
      **ein** Shutdown-Hook stoppt sie und gibt die Sperre frei.
    * In Gate B wird weiterhin **keine Route** registriert und **kein**
      Sidecar gestartet.

    Gibt die Laufzeit zurück, damit Aufrufer ohne FastAPI sie ebenfalls
    benutzen können.
    """
    from personaljarvis.bootstrap import PersonalBootstrap

    state = getattr(app, "state", None)
    if state is not None and getattr(state, "personal_bootstrap", None) is not None:
        raise PersonalAlreadyAttached(
            "Personal Jarvis ist an dieser App bereits angehaengt; ein zweiter "
            "Bootstrap wuerde einen zweiten Schreiber erzeugen."
        )

    bootstrap = PersonalBootstrap(
        database_path, lock_path=lock_path,
        sidecar_path=sidecar_path, bundle_dir=bundle_dir,
    )
    runtime = bootstrap.start()

    if state is not None:
        state.personal_bootstrap = bootstrap
        state.personal_runtime = runtime
    _register_shutdown_hook(app, bootstrap)
    return runtime
