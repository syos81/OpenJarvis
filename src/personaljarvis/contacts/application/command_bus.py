"""Registrierung der Kontakte-Commands am ApplicationCommandBus (05 §1).

Der Bus selbst liegt in der Basis — er ist nach 05 §1 modulübergreifend **der**
eine Schreibpfad. Hier wird nur verdrahtet, welcher Handler zu welchem Command
gehört.

**Kein Command ohne Freigabe:** Die Handler rufen ausschließlich `prepare()`
auf. Die Ausführung ist ein getrennter Schritt und verlangt eine menschliche
Freigabe (10 §3). Ein Dispatch löst nie einen Provider-Aufruf aus.
"""

from __future__ import annotations

from personaljarvis.base.command_bus import ApplicationCommandBus
from personaljarvis.contacts.application.commands import (
    CreateContact,
    DeleteContact,
    UpdateContact,
)
from personaljarvis.contacts.application.models import PreparedMutation
from personaljarvis.contacts.application.mutation_service import (
    ContactsMutationService,
)

__all__ = ["register_contacts_commands", "CONTACT_COMMANDS"]

#: Geschlossene Menge der Kontakte-Commands.
CONTACT_COMMANDS = (CreateContact, UpdateContact, DeleteContact)


def register_contacts_commands(bus: ApplicationCommandBus,
                               service: ContactsMutationService) -> None:
    """Verdrahtet genau einen Handler je Command.

    Der Handler bereitet vor und gibt den Vorgang zurück — er führt **nicht**
    aus. Damit ist strukturell ausgeschlossen, dass ein Dispatch aus UI, CLI
    oder Chat eine Mutation absendet.
    """
    def handler(command) -> PreparedMutation:
        return service.prepare(command)

    for command_type in CONTACT_COMMANDS:
        bus.register(command_type, handler)
