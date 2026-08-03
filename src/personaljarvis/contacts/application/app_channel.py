"""Fähigkeiten des App-Prozess-Kanals (ADR-0020 §10, Phase A).

Der Kanal ist **fail-closed**: Ohne belegte Gegenseite ist alles falsch. In
Phase A ist zusätzlich `provider_write_enabled` grundsätzlich falsch — der
Transport steht, der native Save nicht. Eine Oberfläche, die daraus
Schreibbarkeit liest, hätte einen Knopf ohne Deckung.

Zwei Regeln, die nicht verhandelbar sind:

* **Keine Fähigkeit kommt aus dem Frontend.** Das Frontend meldet, was es
  gerne hätte; ob es geht, entscheidet allein der Kern anhand seiner
  Konstanten und (ab Phase B) des nativen Handshakes.
* **Sidecar-Schreibfähigkeiten zählen nicht mehr.** Seit ADR-0020 ist der
  CLI-Sidecar ausschliesslich Lese-, Sync- und Diagnosewerkzeug; ein
  `createImplemented: true` aus seinem Handshake wird für Schreibrechte
  ignoriert.
"""

from __future__ import annotations

import platform
from dataclasses import asdict, dataclass

__all__ = [
    "APP_CHANNEL_SCHEMA_VERSION",
    "PHASE_A_PROVIDER_WRITE_ENABLED",
    "AppChannelCapabilities",
    "app_channel_capabilities",
]

APP_CHANNEL_SCHEMA_VERSION = 1

#: Phase A hat **keinen** nativen Save. Der Wert ist eine Konstante, kein
#: Schalter: Er wird erst mit Phase D zu einer Entscheidung.
PHASE_A_PROVIDER_WRITE_ENABLED = False


@dataclass(frozen=True, slots=True)
class AppChannelCapabilities:
    schema_version: int
    channel: str
    create_supported: bool
    update_supported: bool
    delete_supported: bool
    provider_write_enabled: bool
    architecture: str
    app_version: str
    native_bridge_version: str

    @property
    def channel_available(self) -> bool:
        """Ob der **Transport** benutzt werden darf.

        Bewusst unabhängig von `provider_write_enabled`: In Phase A darf ein
        Auftrag entstehen und bis zum Fake-Kanal laufen — nur senden darf
        niemand. Wären beide dasselbe Flag, liesse sich der Transport nicht
        testen, ohne den Schreibweg zu öffnen.
        """
        return self.create_supported or self.update_supported \
            or self.delete_supported

    def as_dict(self) -> dict:
        return asdict(self)


def app_channel_capabilities(
    *, app_version: str = "1.0.1",
    native_bridge_version: str = "0",
) -> AppChannelCapabilities:
    """Der Handshake des Kerns — die einzige Quelle für Schreibrechte."""
    return AppChannelCapabilities(
        schema_version=APP_CHANNEL_SCHEMA_VERSION,
        channel="app_process",
        # Phase A: Der Transport für `create` steht; Update und Delete
        # kommen erst mit ihren eigenen Phasen (E/F).
        create_supported=True,
        update_supported=False,
        delete_supported=False,
        provider_write_enabled=PHASE_A_PROVIDER_WRITE_ENABLED,
        architecture=platform.machine(),
        app_version=app_version,
        native_bridge_version=native_bridge_version,
    )
