"""ApplicationCommandBus — der einzige logische Schreibpfad (05 §1, AV-35).

API-Router, CLI, Chat-Tools und Automationen erzeugen **dieselben** Commands
und durchlaufen **denselben** Handler. Ein zweiter produktiver Ausführungsweg
existiert nicht (05 §3).

Verbindliche Eigenschaften:

* **Geschlossene Registrierung.** Ein Command-Typ, ein Handler. Doppelte
  Registrierung ist ein Fehler, keine Überschreibung.
* **Keine dynamische Ausführung.** Es gibt kein `eval`, kein `importlib`, keine
  Auflösung über Zeichenketten — der Typ selbst ist der Schlüssel.
* **Fail-closed.** Ein unbekannter Command wird abgelehnt, nicht geraten.
* **Kein impliziter Commit.** Der Bus öffnet und schließt keine Transaktion;
  das gehört dem Handler bzw. dem Orchestrator (07 §2).
* **Kein automatischer Retry.** Der Bus wiederholt nichts. Ob etwas wiederholt
  werden darf, entscheidet die Zustandsmaschine der Mutation.

Der Bus liegt in der Basis, weil er nach 05 §1 modulübergreifend **der** eine
Schreibpfad ist. Er wird nach AV-33 nur in dem Umfang materialisiert, den die
Kontakte-Mutationspipeline unmittelbar braucht.
"""

from __future__ import annotations

from typing import Any, Callable, TypeVar

from personaljarvis.errors import PersonalJarvisError

__all__ = [
    "CommandBusError",
    "UnknownCommand",
    "HandlerAlreadyRegistered",
    "ApplicationCommandBus",
]

_C = TypeVar("_C")


class CommandBusError(PersonalJarvisError):
    """Wurzel aller Command-Bus-Fehler."""


class UnknownCommand(CommandBusError):
    """Für diesen Command ist kein Handler registriert — fail-closed."""


class HandlerAlreadyRegistered(CommandBusError):
    """Genau ein Handler je Command; eine zweite Registrierung ist ein Fehler."""


class ApplicationCommandBus:
    """Verteilt typisierte Commands an genau einen Handler."""

    def __init__(self) -> None:
        self._handlers: dict[type, Callable[[Any], Any]] = {}

    def register(self, command_type: type[_C],
                 handler: Callable[[_C], Any]) -> None:
        if command_type in self._handlers:
            raise HandlerAlreadyRegistered(
                f"Fuer {command_type.__name__} ist bereits ein Handler "
                f"registriert")
        if not callable(handler):
            raise CommandBusError("Handler ist nicht aufrufbar")
        self._handlers[command_type] = handler

    @property
    def registered_commands(self) -> tuple[type, ...]:
        return tuple(self._handlers)

    def handles(self, command_type: type) -> bool:
        return command_type in self._handlers

    def dispatch(self, command: Any) -> Any:
        """Führt genau einen Handler aus. Unbekannter Typ ⇒ `UnknownCommand`.

        Die Auflösung erfolgt über den **exakten** Typ, nicht über Vererbung:
        eine Unterklasse erbt keine Freigabe, sondern braucht eine eigene
        Registrierung.
        """
        handler = self._handlers.get(type(command))
        if handler is None:
            raise UnknownCommand(
                f"Kein Handler fuer {type(command).__name__} registriert")
        return handler(command)
