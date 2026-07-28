"""Capability-Deklaration des Kontakte-Moduls (08 §3 Nr. 2, 08 §4).

Fähigkeiten werden **deklariert, nicht verschwiegen** (AV-3). Die beiden
belegten Grenzen aus dem Spike G3a sind hier strukturell verankert:

* `notes_supported` ist `False` und lässt sich nicht durch Konfiguration
  einschalten — ein Entitlement erfordert einen eigenen ADR.
* `unified_link_supported` ist `False`; Verknüpfen und Trennen sind keine
  zugesagte mutierende Fähigkeit.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from personaljarvis.contacts.domain.enums import FieldAvailabilityState
from personaljarvis.errors import CapabilityError

__all__ = ["ContactCapabilitySet", "NOTE_FIELD", "default_capabilities"]

# Der Feldname, unter dem die Nicht-Verfügbarkeit von Notizen geführt wird.
NOTE_FIELD = "note"


@dataclass(frozen=True)
class ContactCapabilitySet:
    """Was ein konkreter Provider/Account tatsächlich kann."""

    read_supported: bool = True
    create_supported: bool = False
    update_supported: bool = False
    delete_supported: bool = False
    change_history_supported: bool = False
    full_diff_supported: bool = False
    notes_supported: bool = False
    unified_read_supported: bool = False
    unified_link_supported: bool = False
    me_card_writable: bool = False
    key_set_version: str = "unset"
    unavailable_fields: tuple[str, ...] = field(default=(NOTE_FIELD,))

    def __post_init__(self) -> None:
        if self.notes_supported:
            raise CapabilityError(
                "Notizen sind ohne besonderes Apple-Entitlement nicht zugesagt; "
                "eine Aktivierung erfordert einen eigenen ADR (08 §4)"
            )
        if self.unified_link_supported:
            raise CapabilityError(
                "Verknüpfen und Trennen vereinheitlichter Kontakte ist keine "
                "zugesagte mutierende Fähigkeit (08 §4)"
            )
        if self.me_card_writable:
            raise CapabilityError(
                "Die Me-Karte ist in dieser Version schreibgeschützt"
            )
        if NOTE_FIELD not in self.unavailable_fields:
            raise CapabilityError(
                "Solange notes_supported False ist, muss 'note' als nicht "
                "verfügbar geführt werden — sonst gilt es fälschlich als leer"
            )

    def availability_for(self, field_name: str) -> FieldAvailabilityState | None:
        """Von der Fähigkeit abgeleiteter Zustand; `None` heißt „nicht bestimmt"."""
        if field_name in self.unavailable_fields:
            return FieldAvailabilityState.UNAVAILABLE_BY_CAPABILITY
        return None

    def require(self, operation: str) -> None:
        """Fail-closed-Prüfung vor einer Operation."""
        supported = {
            "read": self.read_supported,
            "create": self.create_supported,
            "update": self.update_supported,
            "delete": self.delete_supported,
            "change_history": self.change_history_supported,
            "full_diff": self.full_diff_supported,
            "unified_read": self.unified_read_supported,
        }
        if operation not in supported:
            raise CapabilityError(f"Unbekannte Operation: {operation}")
        if not supported[operation]:
            raise CapabilityError(f"Operation '{operation}' ist nicht deklariert")


def default_capabilities() -> ContactCapabilitySet:
    """Gate-A-Grundzustand: **nur lesend aus der kanonischen Datenbank**.

    Es gibt in Gate A keine Bridge, deshalb ist keine Provider-Operation
    deklariert. Alles Weitere entsteht mit Gate B.
    """
    return ContactCapabilitySet()
