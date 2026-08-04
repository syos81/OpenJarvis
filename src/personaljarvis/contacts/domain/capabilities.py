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

__all__ = [
    "derive_capabilities","ContactCapabilitySet", "NOTE_FIELD", "default_capabilities"]

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
        # Defensive Kopie vor jeder Prüfung — eine Liste bliebe mutierbar.
        object.__setattr__(self, "unavailable_fields", tuple(self.unavailable_fields))
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


def derive_capabilities(status, *, app_channel=None,
                        database_path=None) -> ContactCapabilitySet:
    """Handshake → Fähigkeitsmenge. Die Capability-Brücke (ADR-0019 §6).

    Bis hierher endete der Handshake in `BridgeStatus` und kam nie im Kern an:
    `mutationsImplemented` war eine Angabe, die niemand las. Ohne diese
    Ableitung liesse sich eine Schreiboperation nie freischalten — und, was
    schlimmer wäre, mit einer laxeren Ableitung liesse sie sich versehentlich
    freischalten.

    Vier Regeln, alle fail-closed:

    1. **Standard ist überall `False`.** Kein Handshake, keine Fähigkeit.
    2. **Fehlende Angaben zählen als `False`**, nicht als „vermutlich ja".
    3. **Die Vertragsversionen müssen exakt übereinstimmen.** Ein älterer
       Sidecar wird nie von einem neueren Kern freigeschaltet und umgekehrt;
       sonst schickte der Kern Felder, die die Gegenseite still verwirft.
    4. **Je Operation einzeln.** `create` schaltet `update` und `delete`
       nicht mit frei — auch dann nicht, wenn der Sidecar es behauptete.
    """
    from personaljarvis.contacts.application.field_contract import (
        FIELD_CONTRACT_VERSION,
        MUTATION_CONTRACT_VERSION,
    )

    if status is None or not getattr(status, "available", False):
        return default_capabilities()
    caps = getattr(status, "capabilities", None)
    if caps is None:
        return default_capabilities()

    vertrag_passt = (
        getattr(caps, "mutation_contract_version", -1) == MUTATION_CONTRACT_VERSION
        and getattr(caps, "field_contract_version", -1) == FIELD_CONTRACT_VERSION)

    def schreibbar(flag: str) -> bool:
        return bool(vertrag_passt and getattr(caps, flag, False))

    # Seit ADR-0020 §10 kommt das Schreibrecht **nicht** mehr aus dem
    # Sidecar-Handshake: Der Sidecar hat gar keinen Schreibpfad, und sein
    # `createImplemented` ist dauerhaft falsch. Ob `create` angeboten werden
    # darf, entscheidet der App-Prozess-Kanal — und der verlangt eine
    # gueltige, ablaufende Schreibfreigabe. Der Vertragsstand muss trotzdem
    # passen: ein fremder Sidecar-Vertragsstand sperrt weiterhin alles.
    from personaljarvis.contacts.application.app_channel import (
        app_channel_capabilities,
    )

    kanal = (app_channel if app_channel is not None
             else app_channel_capabilities(database_path=database_path))
    return ContactCapabilitySet(
        read_supported=True,
        create_supported=bool(vertrag_passt and kanal.darf_ausfuehren("create")),
        # Update und Delete folgen seit DEC-046 derselben Quelle wie Create:
        # dem App-Prozess-Kanal. Der Sidecar meldet alle drei dauerhaft
        # falsch — er ist Lese- und Diagnosewerkzeug, nicht Schreiber.
        update_supported=bool(vertrag_passt and kanal.darf_ausfuehren("update")),
        delete_supported=bool(vertrag_passt and kanal.darf_ausfuehren("delete")),
        change_history_supported=bool(
            getattr(caps, "change_history_supported", False)),
        full_diff_supported=bool(
            getattr(caps, "full_diff_fallback_supported", False)),
        unified_read_supported=bool(getattr(caps, "unified_read_only", False)),
        key_set_version=str(getattr(status, "protocol_version", "unset")),
    )


def default_capabilities() -> ContactCapabilitySet:
    """Gate-A-Grundzustand: **nur lesend aus der kanonischen Datenbank**.

    Es gibt in Gate A keine Bridge, deshalb ist keine Provider-Operation
    deklariert. Alles Weitere entsteht mit Gate B.
    """
    return ContactCapabilitySet()
