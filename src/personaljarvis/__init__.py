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

#: Derselbe Standard-Workspace wie in den Routen — ein zweiter Wert
#: hier hiesse, dass Reparatur und Abgleich auf verschiedene Bestaende
#: zeigen.
DEFAULT_WORKSPACE = "default"

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
           bundle_dir: str | None = None,
           calendar_sidecar_path: str | None = None) -> Any:
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
    * Seit Gate D wird der Kontakte-Router registriert — erst **nachdem** der
      Bootstrap durchgelaufen ist, damit keine Anfrage eine halb geöffnete
      Datenbank sieht. Ein **Sidecar startet weiterhin nicht**.

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
        calendar_sidecar_path=calendar_sidecar_path,
    )
    runtime = bootstrap.start()

    if state is not None:
        state.personal_bootstrap = bootstrap
        state.personal_runtime = runtime
    _register_shutdown_hook(app, bootstrap)

    # Router registrieren (Gate D). Bewusst tolerant gegenueber Objekten ohne
    # `include_router`: Tests reichen leichte App-Attrappen herein, und ein
    # fehlender Router darf den Bootstrap nicht scheitern lassen, nachdem
    # Datenbank und Sperre bereits stehen.
    # Reihenfolge ist hier bedeutungstragend (ADR-0025 §6):
    #
    #   bootstrap.start()   Modul, Migrationen, Erholung verwaister Vorgaenge
    #   check_bridge()      kontaktfreier Handshake -> Faehigkeitsmenge
    #   _register_*()       Werkzeuge verdrahten
    #
    # Ohne den Startcheck bliebe `capabilities` auf dem Gate-A-Grundzustand
    # (alles ausser Lesen False) und `create` waere dauerhaft gesperrt — die
    # Bruecke aus dem Handshake haette keinen Aufrufer. Er muss **vor** der
    # Registrierung laufen, damit der danach neu gebaute Mutationsdienst die
    # abgeleitete Menge traegt und nicht die alte.
    _derive_capabilities(runtime.contacts)
    _register_recovery_service(runtime.contacts, sidecar_path, bundle_dir)
    _register_mutation_bridge(runtime.contacts, sidecar_path, bundle_dir)

    if hasattr(app, "include_router"):
        from personaljarvis.calendar.api import create_calendar_router
        from personaljarvis.contacts.api import create_contacts_router

        app.include_router(create_contacts_router(runtime.contacts))
        if runtime.calendar is not None:
            app.include_router(create_calendar_router(runtime.calendar))
    return runtime


def _derive_capabilities(module: Any) -> None:
    """Leitet die Fähigkeitsmenge aus dem Sidecar-Handshake ab.

    **Kontaktfrei.** `check_bridge()` sendet ausschliesslich `ping` und liest
    die unaufgeforderte `ready`-Zeile — beides gehört zu
    `protocol.CONTACT_FREE_OPERATIONS`. Es gibt keinen `CNContactStore`-
    Zugriff, kein `authorizationStatus`, kein `requestAuthorization`, keinen
    Dialog und keine Kontaktoperation. Der Prozess wird danach beendet.

    **Fail-closed in jeder Richtung.** Fehlt das Binary, scheitert der
    Handshake, fehlen die Vertragsversionen oder passen sie nicht exakt, so
    bleibt jede Schreibfähigkeit `False` — `check_bridge()` fängt die gesamte
    Bridge-Fehlerfamilie ab und liefert dann einen Status ohne Fähigkeiten.
    Eine teilweise oder optimistische Freischaltung gibt es nicht.
    """
    module.check_bridge()


def _register_mutation_bridge(module: Any, sidecar_path: str | None,
                              bundle_dir: str | None) -> None:
    """Verdrahtet das produktive Ausführungsziel und den Abgleichleser.

    **Die Registrierung löst nichts aus.** Sie startet keinen Prozess, prüft
    keine Berechtigung und führt keine Mutation aus; `resolve_sidecar` sieht
    ausschliesslich auf die Datei. Ausgeführt wird erst auf eine ausdrückliche
    Nutzeraktion über `POST …/mutations/{id}/execute`.

    Ist die Bridge strukturell nicht vorhanden, bleibt der Standardprovider
    stehen (`_UnavailableProvider` → `failed_before_send`), und die Capability
    bleibt ohnehin `False`. Ein Fake- oder Rückfallprovider wird ausdrücklich
    **nicht** eingesetzt: eine Anlage auf erfundenen Daten wäre schlimmer als
    keine.

    Die Fähigkeitsprüfung geschieht nicht hier, sondern zweimal später — beim
    Vorbereiten und erneut beim Ausführen, jeweils gegen die aus dem Handshake
    abgeleitete Menge. Hier steht nur das Werkzeug bereit.
    """
    from personaljarvis.contacts.application.bridge_provider import (
        ContactsBridgeMutationProvider,
        ContactsBridgeReconcileReader,
    )
    from personaljarvis.contacts.bridge.errors import BridgeConfigurationError
    from personaljarvis.contacts.bridge.resolver import resolve_sidecar

    try:
        resolve_sidecar(sidecar_path, bundle_dir=bundle_dir)
    except BridgeConfigurationError:
        return

    module._mutation_service = None      # naechster Zugriff baut ihn neu
    module.mutation_provider = ContactsBridgeMutationProvider(
        sidecar_path=sidecar_path, bundle_dir=bundle_dir)
    module.reconcile_reader = ContactsBridgeReconcileReader(
        sidecar_path=sidecar_path, bundle_dir=bundle_dir)


def _register_recovery_service(module: Any, sidecar_path: str | None,
                               bundle_dir: str | None) -> None:
    """Verdrahtet die Wiederherstellung — und löst dabei nichts aus.

    Sie beantwortet einen konkret erkannten Fehlerzustand (lokal getombstonete
    Kontakte, die der Provider unverändert kennt). Registriert wird nur ein
    Einstiegspunkt; Sidecar, Autorisierung, Enumeration und Reparatur passieren
    ausschliesslich auf ausdrücklichen Aufruf.

    Ist die Bridge strukturell nicht vorhanden — kein Binary, falsche
    Architektur —, bleibt `recovery_service` ungesetzt und der Endpunkt
    antwortet kontrolliert mit 503. Ein Fake- oder Rückfallprovider wird
    ausdrücklich **nicht** eingesetzt: eine Reparatur auf erfundenen Daten wäre
    schlimmer als keine.

    Die Prüfung selbst ist nebenwirkungsfrei: `resolve_sidecar` sieht auf die
    Datei, startet aber keinen Prozess.
    """
    from personaljarvis.contacts.application.live import (
        APPLE_PROVIDER_ACCOUNT,
        ContactsLiveService,
        ContactsRecoveryEntrypoint,
    )
    from personaljarvis.contacts.bridge.errors import BridgeConfigurationError
    from personaljarvis.contacts.bridge.resolver import resolve_sidecar

    try:
        resolve_sidecar(sidecar_path, bundle_dir=bundle_dir)
    except BridgeConfigurationError:
        return

    live = getattr(module, "live_service", None)
    if live is None:
        live = ContactsLiveService(module, sidecar_path=sidecar_path,
                                   bundle_dir=bundle_dir)
        module.live_service = live
    module.recovery_service = ContactsRecoveryEntrypoint(
        live, module, workspace_id=DEFAULT_WORKSPACE,
        provider_account_id=APPLE_PROVIDER_ACCOUNT)
