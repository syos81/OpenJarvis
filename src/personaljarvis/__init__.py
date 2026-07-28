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

__all__ = ["attach", "is_enabled", "ENABLE_ENV_VAR", "PersonalNotEnabled"]

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


def attach(app: Any, *, database_path: str | None = None) -> Any:
    """Hängt Personal Jarvis an eine bestehende FastAPI-App.

    Verhalten (04 §4, fail-closed):

    * Der Bootstrap läuft vollständig durch, bevor irgendetwas registriert wird.
    * Schlägt Migration oder Schema fehl, wird der Fehler **weitergereicht** —
      er wird nicht protokolliert und geschluckt.
    * In Gate A wird **keine Route** registriert. Die Laufzeit hängt an
      ``app.state.personal_runtime``, damit ein Shutdown sie stoppen kann.

    Gibt die Laufzeit zurück, damit Aufrufer ohne FastAPI sie ebenfalls
    benutzen können.
    """
    from personaljarvis.bootstrap import PersonalBootstrap

    bootstrap = PersonalBootstrap(database_path)
    runtime = bootstrap.start()

    state = getattr(app, "state", None)
    if state is not None:
        state.personal_bootstrap = bootstrap
        state.personal_runtime = runtime
    return runtime
