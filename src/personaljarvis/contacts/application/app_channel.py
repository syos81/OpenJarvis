"""Fähigkeiten des App-Prozess-Kanals (ADR-0020 §10, Phase A).

Der Kanal ist **fail-closed**: ohne belegte Gegenseite ist alles falsch.

**Korrektur 2026-08-03.** Der erste Phase-A-Stand meldete
`create_supported: true` bei `provider_write_enabled: false`. Das war
irreführend: Phase B hat nicht begonnen, es gibt keinen nativen Save, und
eine Oberfläche, die „Create wird unterstützt" liest, hätte einen Knopf ohne
Deckung angeboten. Ein Release meldet deshalb **jede** Schreibfähigkeit
falsch. Unterstützt ist erst, was auch ausgeführt werden kann.

Drei Regeln, die nicht verhandelbar sind:

* **Keine Fähigkeit kommt aus dem Frontend.** Das Frontend meldet, was es
  gerne hätte; ob es geht, entscheidet allein der Kern.
* **Keine Fähigkeit kommt aus der Umgebung.** In diesem Modul wird
  `os.environ` nicht gelesen. Ein Release lässt sich durch keine Variable
  öffnen — der Fake-Modus ist ausschliesslich im Prozess konstruierbar
  (`fake_debug_capabilities`) und wird von keiner Route zurückgegeben.
* **Sidecar-Schreibfähigkeiten zählen nicht mehr.** Seit ADR-0020 ist der
  CLI-Sidecar Lese-, Sync- und Diagnosewerkzeug; sein Handshake wird für
  Schreibrechte ignoriert.
"""

from __future__ import annotations

import platform
from dataclasses import asdict, dataclass

from personaljarvis.contacts.application.write_release import (
    default_release_path,
)

__all__ = [
    "APP_CHANNEL_SCHEMA_VERSION",
    "MODE_NATIVE_CREATE",
    "NATIVE_CREATE_AVAILABLE",
    "CHANNEL_MODES",
    "MODE_DISABLED",
    "MODE_FAKE_DEBUG",
    "PHASE_A_PROVIDER_WRITE_ENABLED",
    "AppChannelCapabilities",
    "InconsistentCapabilities",
    "app_channel_capabilities",
    "fake_debug_capabilities",
]

APP_CHANNEL_SCHEMA_VERSION = 3

#: Kein Provider — weder echt noch gefälscht. Der Zustand jedes Builds in
#: Phase A.
MODE_DISABLED = "disabled"

#: Ein synthetischer Provider im Prozess. Nur für Debug-Builds mit
#: gesetztem Fake-Gate und synthetischem Auftrag; nie über eine Route
#: erreichbar, nie über eine Umgebungsvariable aktivierbar.
MODE_FAKE_DEBUG = "fake_debug"

#: Der native Create-Pfad ist eingeschaltet — es liegt eine gültige,
#: ablaufende Schreibfreigabe vor (`write_release`). Dieser Modus schreibt
#: **echt**.
MODE_NATIVE_CREATE = "native_create"

CHANNEL_MODES = (MODE_DISABLED, MODE_FAKE_DEBUG, MODE_NATIVE_CREATE)

#: Ob der native Create-Code in diesem Stand überhaupt existiert. Das ist
#: eine Aussage über den **Bauzustand**, nicht über Erlaubnis: „vorhanden"
#: heisst nicht „darf". Getrennt zu führen ist der ganze Punkt — sonst
#: müsste man Schreibrechte melden, um Vorhandensein zu melden.
NATIVE_CREATE_AVAILABLE = True

#: Phase A hat **keinen** nativen Save. Der Wert ist eine Konstante, kein
#: Schalter: Er wird erst mit Phase D zu einer Entscheidung.
PHASE_A_PROVIDER_WRITE_ENABLED = False

_OPERATION_TO_FIELD = {
    "create": "create_supported",
    "update": "update_supported",
    "delete": "delete_supported",
}


class InconsistentCapabilities(RuntimeError):
    """Ein Fähigkeitssatz, der sich selbst widerspricht.

    Fail-closed statt „bester Interpretation": Wer `create_supported` meldet,
    aber `provider_write_enabled` verneint, hat entweder einen Fehler oder
    einen manipulierten Handshake — beides darf keinen Auftrag erzeugen.
    """


@dataclass(frozen=True, slots=True)
class AppChannelCapabilities:
    schema_version: int
    channel: str
    channel_mode: str
    #: Bauzustand, nicht Erlaubnis: der native Create-Pfad ist einkompiliert.
    native_create_available: bool
    create_supported: bool
    update_supported: bool
    delete_supported: bool
    provider_write_enabled: bool
    architecture: str
    app_version: str
    native_bridge_version: str

    def __post_init__(self) -> None:
        self.pruefe()

    # ── Prüfungen ───────────────────────────────────────────────────────────
    def pruefe(self) -> None:
        """Wirft bei jedem widersprüchlichen oder unbekannten Zustand."""
        if self.channel != "app_process":
            raise InconsistentCapabilities(f"Unbekannter Kanal: {self.channel!r}")
        if self.channel_mode not in CHANNEL_MODES:
            raise InconsistentCapabilities(
                f"Unbekannter Kanalmodus: {self.channel_mode!r}")
        schreibbar = (self.create_supported or self.update_supported
                      or self.delete_supported)
        if schreibbar and not self.provider_write_enabled:
            raise InconsistentCapabilities(
                "Eine Operation gilt als unterstützt, obwohl der Provider "
                "nicht schreiben darf")
        if self.channel_mode == MODE_NATIVE_CREATE \
                and not self.native_create_available:
            raise InconsistentCapabilities(
                "Nativer Kanal ohne nativen Code")
        if self.provider_write_enabled and self.channel_mode == MODE_DISABLED:
            raise InconsistentCapabilities(
                "Schreiben erlaubt bei abgeschaltetem Kanal")
        if self.channel_mode == MODE_DISABLED and schreibbar:
            raise InconsistentCapabilities(
                "Abgeschalteter Kanal meldet eine unterstützte Operation")

    def supports(self, operation: str) -> bool:
        """Ob **diese** Operation ausgeführt werden darf.

        Unbekannte Operationen sind falsch, nicht wahr — ein Tippfehler im
        Aufrufer darf keinen Schreibversuch freischalten.
        """
        feld = _OPERATION_TO_FIELD.get(operation)
        return bool(feld and getattr(self, feld))

    def darf_ausfuehren(self, operation: str) -> bool:
        """Der Torwächter des Claims: Schreibrecht **und** Operation.

        Bewusst eine Konjunktion. Ein Oder liesse einen der beiden Schalter
        allein genügen — und genau das war der Fehlstand, in dem `create`
        unterstützt schien, obwohl niemand schreiben konnte.
        """
        return self.provider_write_enabled and self.supports(operation)

    @property
    def channel_available(self) -> bool:
        """Ob der Kanal überhaupt etwas ausführen kann."""
        return self.provider_write_enabled and (
            self.create_supported or self.update_supported
            or self.delete_supported)

    def as_dict(self) -> dict:
        return asdict(self)


def app_channel_capabilities(
    *, app_version: str = "1.0.1",
    native_bridge_version: str = "0",
    release_path=None,
    database_path=None,
) -> AppChannelCapabilities:
    """Der Handshake des Kerns — die einzige Quelle für Schreibrechte.

    Ohne gültige Schreibfreigabe ist das Ergebnis konstant: Transport
    vorbereitet, nativer Create-Code vorhanden, Provider-Schreiben
    deaktiviert. Mit gültiger Freigabe — einer 0600-Datei im 0700-Ordner,
    die Vertrag, Umfang, Grund und einen Ablauf nennt — meldet der Kanal
    `create`, und **nur** `create`.

    `release_path` ist ein Parameter und ausdrücklich **keine**
    Umgebungsvariable: Tests und Werkzeuge geben ihn direkt an; nichts an
    der Prozessumgebung kann den Kanal öffnen.
    """
    from personaljarvis.contacts.application.write_release import (
        read_write_release,
    )

    freigabe = read_write_release(
        release_path if release_path is not None
        else default_release_path(database_path))
    def darf(operation: str) -> bool:
        return bool(freigabe and freigabe.erlaubt(operation)
                    and NATIVE_CREATE_AVAILABLE)

    darf_create, darf_update, darf_delete = (
        darf("create"), darf("update"), darf("delete"))
    irgendwas = darf_create or darf_update or darf_delete
    return AppChannelCapabilities(
        schema_version=APP_CHANNEL_SCHEMA_VERSION,
        channel="app_process",
        channel_mode=MODE_NATIVE_CREATE if irgendwas else MODE_DISABLED,
        native_create_available=NATIVE_CREATE_AVAILABLE,
        create_supported=darf_create,
        update_supported=darf_update,
        delete_supported=darf_delete,
        provider_write_enabled=irgendwas,
        architecture=platform.machine(),
        app_version=app_version,
        native_bridge_version=native_bridge_version,
    )


def fake_debug_capabilities(
    *, create: bool = True, update: bool = False, delete: bool = False,
    app_version: str = "1.0.1", native_bridge_version: str = "0",
) -> AppChannelCapabilities:
    """Der synthetische Kanal — **nur** im Prozess, nur für Debug-Läufe.

    Diese Funktion ist die einzige Stelle, an der Phase A überhaupt eine
    Schreibfähigkeit erzeugen kann. Sie ist bewusst kein Schalter, sondern
    ein Aufruf: Sie steht in keiner Route, in keinem Startpfad und in keiner
    Umgebungsvariablen. Wer sie ruft, hält den Fake-Auftrag in derselben
    Hand — ein gepacktes Release kann sie nicht erreichen.

    `provider_write_enabled` ist hier wahr, weil in diesem Modus tatsächlich
    etwas ausgeführt wird: der synthetische Provider. `channel_mode` sagt
    ausdrücklich, dass es eine Fälschung ist, damit niemand die Wahrheit im
    Flag sucht statt im Modus.
    """
    return AppChannelCapabilities(
        schema_version=APP_CHANNEL_SCHEMA_VERSION,
        channel="app_process",
        channel_mode=MODE_FAKE_DEBUG,
        native_create_available=NATIVE_CREATE_AVAILABLE,
        create_supported=create,
        update_supported=update,
        delete_supported=delete,
        provider_write_enabled=True,
        architecture=platform.machine(),
        app_version=app_version,
        native_bridge_version=native_bridge_version,
    )
