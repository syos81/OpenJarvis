"""Providerneutrale DTOs der Native-Bridge.

**Keine Apple-Typen überqueren diese Grenze** (AV-4). Die Bridge liefert
technische Rohwerte; Normalisierung, Anzeigenamen und Hashing bleiben im Kern
(ADR-0016 Punkt 4) und finden hier ausdrücklich **nicht** statt.

Zentral ist `FieldAvailability`: Es ist der einzige Ort, an dem
„nicht lesbar" von „leer" unterschieden wird (Plan §5.1). Ein Feld im Zustand
`unavailable_by_capability` darf von keinem Sync-, Diff- oder Konfliktpfad als
leer behandelt werden.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, ClassVar

__all__ = [
    "FieldState",
    "FieldAvailability",
    "AuthorizationStatus",
    "BridgeCapabilities",
    "Handshake",
    "ContainerInfo",
    "LabeledValue",
    "PostalAddress",
    "ServiceProfile",
    "DatedValue",
    "BridgeContact",
    "ChangeEventType",
    "ChangeEvent",
    "ChangesResult",
    "EnumerationResult",
]


class FieldState(str, Enum):
    PRESENT = "present"
    ABSENT = "absent"
    UNAVAILABLE_BY_CAPABILITY = "unavailable_by_capability"


class AuthorizationStatus(str, Enum):
    NOT_DETERMINED = "notDetermined"
    RESTRICTED = "restricted"
    DENIED = "denied"
    AUTHORIZED = "authorized"
    UNKNOWN = "unknown"

    @classmethod
    def parse(cls, raw: str) -> "AuthorizationStatus":
        try:
            return cls(raw)
        except ValueError:
            return cls.UNKNOWN


@dataclass(frozen=True)
class FieldAvailability:
    """Feldzustände eines Datensatzes."""

    states: dict[str, FieldState] = field(default_factory=dict)

    @classmethod
    def parse(cls, raw: dict[str, Any] | None) -> "FieldAvailability":
        out: dict[str, FieldState] = {}
        for name, value in (raw or {}).items():
            try:
                out[name] = FieldState(value)
            except ValueError:
                # Unbekannter Zustand wird konservativ als „nicht verfügbar"
                # gewertet — niemals als „leer".
                out[name] = FieldState.UNAVAILABLE_BY_CAPABILITY
        return cls(out)

    def state_of(self, field_name: str) -> FieldState:
        """Unbekannte Felder gelten als **nicht verfügbar**, nicht als leer."""
        return self.states.get(field_name, FieldState.UNAVAILABLE_BY_CAPABILITY)

    def is_unavailable(self, field_name: str) -> bool:
        return self.state_of(field_name) is FieldState.UNAVAILABLE_BY_CAPABILITY

    def is_writable(self, field_name: str) -> bool:
        """Ein nicht lesbares Feld darf nie geschrieben werden (Plan §7.3)."""
        return not self.is_unavailable(field_name)


@dataclass(frozen=True)
class BridgeCapabilities:
    """Ehrliche Fähigkeitsgrenzen des Providers (08 §3 Nr. 2/7)."""

    notes_supported: bool = False
    link_unlink_supported: bool = False
    unified_read_only: bool = True
    me_card_read_only: bool = True
    change_history_supported: bool = True
    full_diff_fallback_supported: bool = True
    mutations_implemented: bool = False

    @classmethod
    def parse(cls, raw: dict[str, Any] | None) -> "BridgeCapabilities":
        r = raw or {}
        return cls(
            notes_supported=bool(r.get("notesSupported", False)),
            link_unlink_supported=bool(r.get("linkUnlinkSupported", False)),
            unified_read_only=bool(r.get("unifiedReadOnly", True)),
            me_card_read_only=bool(r.get("meCardReadOnly", True)),
            change_history_supported=bool(r.get("changeHistorySupported", False)),
            full_diff_fallback_supported=bool(r.get("fullDiffFallbackSupported", False)),
            mutations_implemented=bool(r.get("mutationsImplemented", False)),
        )


@dataclass(frozen=True)
class Handshake:
    """Die erste, unaufgefordert gesendete Zeile des Sidecars."""

    protocol_version: int
    bundle_identifier: str
    transaction_author: str
    key_set_version: int
    authorization_status: AuthorizationStatus
    operations: tuple[str, ...]
    capabilities: BridgeCapabilities

    @classmethod
    def parse(cls, raw: dict[str, Any]) -> "Handshake":
        return cls(
            protocol_version=int(raw.get("protocolVersion", -1)),
            bundle_identifier=str(raw.get("bundleIdentifier", "")),
            transaction_author=str(raw.get("transactionAuthor", "")),
            key_set_version=int(raw.get("keySetVersion", -1)),
            authorization_status=AuthorizationStatus.parse(
                str(raw.get("authorizationStatus", "unknown"))),
            operations=tuple(raw.get("operations", ())),
            capabilities=BridgeCapabilities.parse(raw.get("capabilities")),
        )


@dataclass(frozen=True)
class ContainerInfo:
    identifier: str
    name: str
    type: str

    @classmethod
    def parse(cls, raw: dict[str, Any]) -> "ContainerInfo":
        return cls(identifier=str(raw["identifier"]), name=str(raw.get("name", "")),
                   type=str(raw.get("type", "unknown")))


@dataclass(frozen=True)
class LabeledValue:
    label: str | None
    value: str


@dataclass(frozen=True)
class PostalAddress:
    label: str | None
    street: str
    city: str
    state: str
    postal_code: str
    country: str
    iso_country_code: str


@dataclass(frozen=True)
class ServiceProfile:
    """Soziales Profil bzw. Sofortnachrichtenadresse — Rohwerte des Providers."""

    label: str | None
    service: str
    username: str
    url: str | None = None


@dataclass(frozen=True)
class DatedValue:
    """Ein gelabeltes Datum. Jahr, Monat und Tag sind einzeln optional."""

    label: str | None
    year: int | None = None
    month: int | None = None
    day: int | None = None


def _labeled(items: Any) -> tuple[LabeledValue, ...]:
    if not isinstance(items, list):
        return ()
    return tuple(
        LabeledValue(label=i.get("label"), value=str(i.get("value", "")))
        for i in items if isinstance(i, dict)
    )


def _int_or_none(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _profiles(items: Any, *, with_url: bool) -> tuple[ServiceProfile, ...]:
    if not isinstance(items, list):
        return ()
    return tuple(
        ServiceProfile(
            label=i.get("label"), service=str(i.get("service", "")),
            username=str(i.get("username", "")),
            url=(i.get("urlString") if with_url else None),
        )
        for i in items if isinstance(i, dict)
    )


def _dates(items: Any) -> tuple[DatedValue, ...]:
    if not isinstance(items, list):
        return ()
    return tuple(
        DatedValue(label=i.get("label"), year=_int_or_none(i.get("year")),
                   month=_int_or_none(i.get("month")), day=_int_or_none(i.get("day")))
        for i in items if isinstance(i, dict)
    )


@dataclass(frozen=True)
class BridgeContact:
    """Rohdatensatz des Providers — **nicht** die kanonische Entität."""

    #: Rohantwort **ohne** den Miniaturbild-Blob — siehe `parse`.
    BLOB_KEYS: ClassVar[tuple[str, ...]] = ("thumbnailBase64",)

    provider_identifier: str
    key_set_version: int
    contact_type: str
    is_me_card: bool
    field_availability: FieldAvailability
    field_completeness: str
    given_name: str = ""
    middle_name: str = ""
    family_name: str = ""
    previous_family_name: str = ""
    name_prefix: str = ""
    name_suffix: str = ""
    phonetic_given_name: str = ""
    phonetic_family_name: str = ""
    organization_name: str = ""
    job_title: str = ""
    department_name: str = ""
    nickname: str = ""
    emails: tuple[LabeledValue, ...] = ()
    phones: tuple[LabeledValue, ...] = ()
    postal_addresses: tuple[PostalAddress, ...] = ()
    urls: tuple[LabeledValue, ...] = ()
    social_profiles: tuple[ServiceProfile, ...] = ()
    instant_messages: tuple[ServiceProfile, ...] = ()
    relations: tuple[LabeledValue, ...] = ()
    dates: tuple[DatedValue, ...] = ()
    birthday: dict[str, int | None] | None = None
    image_available: bool = False
    #: Nur die **Größe** der Miniatur. Der Blob selbst wird bewusst nicht in
    #: die Domäne getragen (siehe `sync.mapper` zur Blob-Entscheidung).
    thumbnail_bytes: int = 0
    unified_identifier: str | None = None
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def is_partial(self) -> bool:
        return self.field_completeness != "full"

    @property
    def notes_readable(self) -> bool:
        """Immer `False`, solange `notesSupported=false` gilt."""
        return self.field_availability.is_writable("note")

    @classmethod
    def parse(cls, raw: dict[str, Any]) -> "BridgeContact":
        addresses = tuple(
            PostalAddress(
                label=a.get("label"), street=str(a.get("street", "")),
                city=str(a.get("city", "")), state=str(a.get("state", "")),
                postal_code=str(a.get("postalCode", "")),
                country=str(a.get("country", "")),
                iso_country_code=str(a.get("isoCountryCode", "")),
            )
            for a in raw.get("postalAddresses", []) if isinstance(a, dict)
        )
        bd = raw.get("birthday")
        return cls(
            provider_identifier=str(raw["providerIdentifier"]),
            key_set_version=int(raw.get("keySetVersion", -1)),
            contact_type=str(raw.get("contactType", "person")),
            is_me_card=bool(raw.get("isMeCard", False)),
            field_availability=FieldAvailability.parse(raw.get("fieldAvailability")),
            field_completeness=str(raw.get("fieldCompleteness", "partial")),
            given_name=str(raw.get("givenName", "")),
            middle_name=str(raw.get("middleName", "")),
            family_name=str(raw.get("familyName", "")),
            previous_family_name=str(raw.get("previousFamilyName", "")),
            name_prefix=str(raw.get("namePrefix", "")),
            name_suffix=str(raw.get("nameSuffix", "")),
            phonetic_given_name=str(raw.get("phoneticGivenName", "")),
            phonetic_family_name=str(raw.get("phoneticFamilyName", "")),
            organization_name=str(raw.get("organizationName", "")),
            job_title=str(raw.get("jobTitle", "")),
            department_name=str(raw.get("departmentName", "")),
            nickname=str(raw.get("nickname", "")),
            emails=_labeled(raw.get("emails")),
            phones=_labeled(raw.get("phones")),
            postal_addresses=addresses,
            urls=_labeled(raw.get("urlAddresses")),
            social_profiles=_profiles(raw.get("socialProfiles"), with_url=True),
            instant_messages=_profiles(raw.get("instantMessages"), with_url=False),
            relations=_labeled(raw.get("relations")),
            dates=_dates(raw.get("dates")),
            birthday=bd if isinstance(bd, dict) else None,
            image_available=bool(raw.get("imageAvailable", False)),
            thumbnail_bytes=int(raw.get("thumbnailBytes") or 0),
            unified_identifier=raw.get("unifiedIdentifier"),
            # Der Miniaturbild-Blob wird hier **verworfen**: er würde sonst als
            # S2-Rohdatum unbemerkt in jedem DTO, jeder Fehlermeldung und jedem
            # Repr weiterreisen. Geführt wird nur seine Größe.
            raw={k: v for k, v in raw.items() if k not in cls.BLOB_KEYS},
        )


class ChangeEventType(str, Enum):
    ADD = "add"
    UPDATE = "update"
    DELETE = "delete"
    DROP_EVERYTHING = "dropEverything"
    OTHER = "other"

    @classmethod
    def parse(cls, raw: str) -> "ChangeEventType":
        try:
            return cls(raw)
        except ValueError:
            return cls.OTHER


@dataclass(frozen=True)
class ChangeEvent:
    type: ChangeEventType
    provider_identifier: str | None = None
    container_identifier: str | None = None

    @classmethod
    def parse(cls, raw: dict[str, Any]) -> "ChangeEvent":
        return cls(
            type=ChangeEventType.parse(str(raw.get("type", "other"))),
            provider_identifier=raw.get("providerIdentifier"),
            container_identifier=raw.get("containerIdentifier"),
        )


@dataclass(frozen=True)
class ChangesResult:
    """Ergebnis eines Delta-Laufs.

    `current_token` stammt **aus dieser Antwort** und wird unverändert
    persistiert — nie über einen zweiten Store-Read beschafft (11 §3).
    """

    events: tuple[ChangeEvent, ...]
    current_token: str
    key_set_version: int

    @property
    def requires_full_diff(self) -> bool:
        """`dropEverything` ist ein legitimes Resync-Signal (Plan §6.2)."""
        return any(e.type is ChangeEventType.DROP_EVERYTHING for e in self.events)


@dataclass(frozen=True)
class EnumerationResult:
    """Ergebnis einer vollständigen Enumeration.

    **Ohne `complete=True` ist das Ergebnis ungültig** und darf niemals als
    Löschmenge interpretiert werden (Plan §6.1/§6.3).
    """

    contacts: tuple[BridgeContact, ...]
    count: int
    complete: bool
    key_set_version: int

    @property
    def usable_as_delete_basis(self) -> bool:
        return self.complete and self.count == len(self.contacts)
