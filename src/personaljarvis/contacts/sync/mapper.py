"""Abbildung `BridgeContact` → kanonische Domäne.

**Hier — und nur hier — findet die Normalisierung statt** (ADR-0016 Punkt 4):
der Sidecar liefert Rohwerte, der Kern bildet Anzeigenamen, Feldzustände und
kanonische Entitäten.

Drei Regeln sind absolut:

* **`unavailable_by_capability` ist nie „leer".** Ein so markiertes Feld wird
  nicht geschrieben und beim Aktualisieren aus dem Bestand übernommen, nie
  geleert (Plan §5.1, §7.3).
* **Der `unified_identifier` ist niemals Schreibziel** — er wird ausschliesslich
  mitgeführt (Plan §7.1).
* **Der Rohlabel bleibt erhalten.** `label_normalized` steht *daneben*, nie
  *anstelle* — ein verlorenes Rohlabel liesse sich nie zurückgewinnen.

Blob-Entscheidung (Plan §10): Miniaturbilder werden in Gate B **nicht**
gespeichert. Es existiert kein Blobspeicher, und ein S2-Rohbild in der
kanonischen Tabelle wäre der falsche Ort dafür. Geführt werden nur
`image_available` und der Feldzustand von `thumbnail`;
`Contact.thumbnail_blob_ref` bleibt `None`, bis der Blobspeicher entschieden
ist. Damit ist „es gibt ein Bild" bekannt, ohne das Bild zu halten.
"""

from __future__ import annotations

import uuid
from dataclasses import fields as dataclass_fields
from dataclasses import replace

from personaljarvis.contacts.bridge.models import (
    BridgeContact,
    DatedValue,
    FieldState,
)
from personaljarvis.contacts.domain.enums import (
    ContactType,
    FieldAvailabilityState,
    FieldCompleteness,
)
from personaljarvis.contacts.domain.models import (
    Contact,
    ContactDate,
    ContactFieldAvailability,
    ContactRelation,
    EmailAddress,
    ExternalIdentifier,
    InstantMessageAddress,
    PhoneNumber,
    PostalAddress,
    SocialProfile,
    UrlAddress,
    utc_now,
)

__all__ = [
    "MappedContact",
    "TRACKED_FIELDS",
    "build_display_name",
    "map_bridge_contact",
    "merge_into_existing",
    "content_equals",
]

#: Felder, deren Verfügbarkeit dauerhaft geführt wird — wortgleich zu den
#: Schlüsseln, die der Sidecar in `fieldAvailability` liefert. `note` steht so
#: lange auf `unavailable_by_capability`, wie `notesSupported=false` gilt.
TRACKED_FIELDS: tuple[str, ...] = (
    "note", "givenName", "familyName", "organizationName", "birthday",
    "emails", "phones", "postalAddresses", "urlAddresses",
    "socialProfiles", "instantMessages", "relations", "thumbnail",
)

#: Der Namensblock des Providers hängt an **einem** Schlüssel: liefert Apple
#: `givenName` nicht, fehlen auch Mittelname, Präfix, Suffix und Spitzname.
_NAME_BLOCK = "givenName"
#: Ebenso hängen Position und Abteilung am Organisationsschlüssel.
_ORG_BLOCK = "organizationName"

_STATE_MAP = {
    FieldState.PRESENT: FieldAvailabilityState.PRESENT,
    FieldState.ABSENT: FieldAvailabilityState.ABSENT,
    FieldState.UNAVAILABLE_BY_CAPABILITY:
        FieldAvailabilityState.UNAVAILABLE_BY_CAPABILITY,
}

#: Kindsammlungen und der Feldschlüssel, der über ihre Lesbarkeit entscheidet.
_COLLECTION_FIELDS: tuple[tuple[str, str], ...] = (
    ("emails", "emails"),
    ("phones", "phones"),
    ("postal_addresses", "postalAddresses"),
    ("urls", "urlAddresses"),
    ("social_profiles", "socialProfiles"),
    ("instant_messages", "instantMessages"),
    ("relations", "relations"),
    ("dates", "birthday"),
)

#: Skalare Felder und ihr Verfügbarkeitsschlüssel.
_SCALAR_FIELDS: tuple[tuple[str, str], ...] = (
    ("given_name", _NAME_BLOCK), ("middle_name", _NAME_BLOCK),
    ("family_name", "familyName"), ("previous_family_name", _NAME_BLOCK),
    ("name_prefix", _NAME_BLOCK), ("name_suffix", _NAME_BLOCK),
    ("phonetic_given_name", _NAME_BLOCK), ("phonetic_family_name", _NAME_BLOCK),
    ("nickname", _NAME_BLOCK), ("organization_name", _ORG_BLOCK),
    ("department_name", _ORG_BLOCK), ("job_title", _ORG_BLOCK),
    ("birthday_year", "birthday"), ("birthday_month", "birthday"),
    ("birthday_day", "birthday"),
)

#: Felder, die dem lokalen Bestand gehören und von keinem Providerlauf
#: überschrieben werden.
_LOCAL_ONLY = (
    "id", "workspace_id", "created_at", "imported_at", "local_revision",
    "roles", "conflict_state", "last_mutation_id", "last_approval_id",
    "last_audit_id", "deleted_at", "is_tombstone",
)


class MappedContact:
    """Ergebnis der Abbildung: Kontakt, externe Identität, Feldzustände.

    Die Feldzustände liegen zusätzlich am `Contact` selbst — das Repository
    schreibt sie aber über sein eigenes Vertragsobjekt, deshalb sind sie hier
    getrennt greifbar.
    """

    __slots__ = ("contact", "external_identifier", "field_availability")

    def __init__(self, contact: Contact, external_identifier: ExternalIdentifier,
                 field_availability: tuple[ContactFieldAvailability, ...]) -> None:
        self.contact = contact
        self.external_identifier = external_identifier
        self.field_availability = field_availability


# ── Anzeigename ──────────────────────────────────────────────────────────────
def build_display_name(source: BridgeContact) -> str:
    """Deterministischer Anzeigename — **im Kern** gebildet, nie vom Sidecar.

    Reihenfolge: Vor-/Mittel-/Nachname · sonst Organisation · sonst Spitzname ·
    sonst ein neutraler Platzhalter. Es wird ausdrücklich **kein**
    Provider-Identifier eingesetzt: ein Anzeigename ist Text für Menschen und
    darf keine technische Kennung tragen.
    """
    verfuegbar = source.field_availability
    if not verfuegbar.is_unavailable(_NAME_BLOCK):
        teile = (source.given_name, source.middle_name, source.family_name)
        name = " ".join(t.strip() for t in teile if t and t.strip())
        if name:
            return name
        if source.nickname.strip():
            return source.nickname.strip()
    if (not verfuegbar.is_unavailable(_ORG_BLOCK)
            and source.organization_name.strip()):
        return source.organization_name.strip()
    return "(ohne Namen)"


def normalize_label(label: str | None) -> str | None:
    """Apple-Rohlabels wie `_$!<Work>!$_` auf einen schlichten Schlüssel bringen.

    Der Rohwert bleibt unangetastet in `label_raw`; hier entsteht nur die
    zusätzliche, vergleichbare Form.
    """
    if not label:
        return None
    kern = label.strip()
    if kern.startswith("_$!<") and kern.endswith(">!$_"):
        kern = kern[4:-4]
    return kern.strip().lower() or None


def _uuid() -> str:
    return str(uuid.uuid4())


# ── Kindsammlungen ───────────────────────────────────────────────────────────
def _emails(source: BridgeContact) -> tuple[EmailAddress, ...]:
    if source.field_availability.is_unavailable("emails"):
        return ()
    # Leere Werte werden verworfen statt als leerer Datensatz gespeichert —
    # sonst entstünde eine Zeile, die nichts aussagt.
    werte = [v for v in source.emails if v.value.strip()]
    return tuple(
        EmailAddress(id=_uuid(), position=i, label_raw=v.label,
                     label_normalized=normalize_label(v.label),
                     value_raw=v.value,
                     value_normalized=v.value.strip().lower())
        for i, v in enumerate(werte)
    )


def _phones(source: BridgeContact) -> tuple[PhoneNumber, ...]:
    if source.field_availability.is_unavailable("phones"):
        return ()
    werte = [v for v in source.phones if v.value.strip()]
    return tuple(
        PhoneNumber(id=_uuid(), position=i, label_raw=v.label,
                    label_normalized=normalize_label(v.label),
                    value_raw=v.value,
                    # E.164 verlangt eine Regionsannahme. Die wird hier nicht
                    # geraten; die Normalform bleibt offen, bis sie belegt ist.
                    value_normalized_e164=None)
        for i, v in enumerate(werte)
    )


def _postal(source: BridgeContact) -> tuple[PostalAddress, ...]:
    if source.field_availability.is_unavailable("postalAddresses"):
        return ()
    return tuple(
        PostalAddress(id=_uuid(), position=i, label_raw=a.label,
                      label_normalized=normalize_label(a.label),
                      street=a.street or None, city=a.city or None,
                      state=a.state or None, postal_code=a.postal_code or None,
                      country=a.country or None,
                      iso_country_code=a.iso_country_code or None)
        for i, a in enumerate(source.postal_addresses)
    )


def _urls(source: BridgeContact) -> tuple[UrlAddress, ...]:
    if source.field_availability.is_unavailable("urlAddresses"):
        return ()
    werte = [v for v in source.urls if v.value.strip()]
    return tuple(
        UrlAddress(id=_uuid(), position=i, label_raw=v.label,
                   label_normalized=normalize_label(v.label),
                   value_raw=v.value, value_normalized=v.value.strip().lower())
        for i, v in enumerate(werte)
    )


def _socials(source: BridgeContact) -> tuple[SocialProfile, ...]:
    if source.field_availability.is_unavailable("socialProfiles"):
        return ()
    werte = [p for p in source.social_profiles if p.service.strip()]
    return tuple(
        SocialProfile(id=_uuid(), position=i, label_raw=p.label,
                      label_normalized=normalize_label(p.label),
                      service=p.service, username=p.username or None,
                      url=p.url or None)
        for i, p in enumerate(werte)
    )


def _ims(source: BridgeContact) -> tuple[InstantMessageAddress, ...]:
    if source.field_availability.is_unavailable("instantMessages"):
        return ()
    werte = [p for p in source.instant_messages
             if p.service.strip() and p.username.strip()]
    return tuple(
        InstantMessageAddress(id=_uuid(), position=i, label_raw=p.label,
                              label_normalized=normalize_label(p.label),
                              service=p.service, username=p.username)
        for i, p in enumerate(werte)
    )


def _relations(source: BridgeContact) -> tuple[ContactRelation, ...]:
    """Apple liefert Beziehungen als freien Text.

    Es wird **nicht geraten**, auf wen sich der Text bezieht: `to_contact_id`
    bleibt `None`, der Rohname bleibt erhalten. Die Auflösung ist eine eigene
    fachliche Entscheidung und gehört nicht in eine Abbildung.
    """
    if source.field_availability.is_unavailable("relations"):
        return ()
    werte = [r for r in source.relations if r.value.strip()]
    return tuple(
        ContactRelation(id=_uuid(), position=i,
                        relation_type=normalize_label(r.label) or "unknown",
                        to_contact_id=None, label_raw=r.label,
                        target_name_raw=r.value)
        for i, r in enumerate(werte)
    )


def _dates(source: BridgeContact) -> tuple[ContactDate, ...]:
    """Weitere Daten neben dem Geburtstag.

    Ein Datum ohne Monat **und** Tag trägt keine Aussage und wird verworfen;
    die Domäne verlangt beide gemeinsam.
    """
    if source.field_availability.is_unavailable("birthday"):
        return ()
    werte: list[DatedValue] = [
        d for d in source.dates if d.month is not None and d.day is not None
    ]
    return tuple(
        ContactDate(id=_uuid(), position=i, label_raw=d.label,
                    label_normalized=normalize_label(d.label),
                    kind=normalize_label(d.label) or "other",
                    year=d.year, month=d.month, day=d.day)
        for i, d in enumerate(werte)
    )


def _availability(source: BridgeContact,
                  observed_at: str) -> tuple[ContactFieldAvailability, ...]:
    return tuple(
        ContactFieldAvailability(
            field_name=feld,
            state=_STATE_MAP[source.field_availability.state_of(feld)],
            observed_at=observed_at,
        )
        for feld in TRACKED_FIELDS
    )


# ── Abbildung ────────────────────────────────────────────────────────────────
def map_bridge_contact(
    source: BridgeContact, *, workspace_id: str, provider_account_id: str,
    container_identifier: str, contact_id: str | None = None,
    observed_at: str | None = None,
) -> MappedContact:
    """Bildet einen Provider-Rohdatensatz auf die kanonische Entität ab.

    `contact_id` wird beim Aktualisieren mitgegeben; beim Import entsteht eine
    neue Kennung. Der Aufruf schreibt nichts — er erzeugt nur Objekte.
    """
    jetzt = observed_at or utc_now()
    cid = contact_id or _uuid()
    verfuegbar = source.field_availability

    def text(feld: str, roh: str) -> str | None:
        """Ein nicht lesbares Feld wird **nicht** als leer geschrieben."""
        if verfuegbar.is_unavailable(feld):
            return None
        return roh.strip() or None

    geburtstag = source.birthday if isinstance(source.birthday, dict) else {}
    if verfuegbar.is_unavailable("birthday"):
        geburtstag = {}

    def datumsteil(name: str) -> int | None:
        wert = geburtstag.get(name)
        return wert if isinstance(wert, int) and not isinstance(wert, bool) else None

    monat, tag = datumsteil("month"), datumsteil("day")
    # Die Domäne verlangt Monat und Tag gemeinsam; ein halbes Datum wäre eine
    # Behauptung, die der Provider nicht deckt.
    if monat is None or tag is None:
        jahr = monat = tag = None
    else:
        jahr = datumsteil("year")

    contact = Contact(
        id=cid,
        workspace_id=workspace_id,
        contact_type=(ContactType.ORGANIZATION
                      if source.contact_type == "organization"
                      else ContactType.PERSON),
        display_name=build_display_name(source),
        given_name=text(_NAME_BLOCK, source.given_name),
        middle_name=text(_NAME_BLOCK, source.middle_name),
        family_name=text("familyName", source.family_name),
        previous_family_name=text(_NAME_BLOCK, source.previous_family_name),
        name_prefix=text(_NAME_BLOCK, source.name_prefix),
        name_suffix=text(_NAME_BLOCK, source.name_suffix),
        phonetic_given_name=text(_NAME_BLOCK, source.phonetic_given_name),
        phonetic_family_name=text(_NAME_BLOCK, source.phonetic_family_name),
        nickname=text(_NAME_BLOCK, source.nickname),
        organization_name=text(_ORG_BLOCK, source.organization_name),
        department_name=text(_ORG_BLOCK, source.department_name),
        job_title=text(_ORG_BLOCK, source.job_title),
        is_me_card=source.is_me_card,
        birthday_year=jahr,
        birthday_month=monat,
        birthday_day=tag,
        image_available=source.image_available,
        # Blob-Entscheidung: kein Blobspeicher in Gate B, also keine Referenz.
        thumbnail_blob_ref=None,
        field_completeness=(FieldCompleteness.PARTIAL if source.is_partial
                            else FieldCompleteness.FULL),
        imported_at=jetzt,
        last_seen_at=jetzt,
        source_updated_at=jetzt,
        created_at=jetzt,
        updated_at=jetzt,
        emails=_emails(source),
        phones=_phones(source),
        postal_addresses=_postal(source),
        dates=_dates(source),
        urls=_urls(source),
        social_profiles=_socials(source),
        instant_messages=_ims(source),
        relations=_relations(source),
        field_availability=_availability(source, jetzt),
    )

    external = ExternalIdentifier(
        id=_uuid(),
        provider_account_id=provider_account_id,
        container_identifier=container_identifier,
        provider_identifier=source.provider_identifier,
        # Nur lesend mitgeführt — nie Schreibziel (Plan §7.1).
        unified_identifier=source.unified_identifier,
        key_set_version=str(source.key_set_version),
        last_seen_at=jetzt,
    )
    return MappedContact(contact, external,
                         _availability(source, jetzt))


# ── Zusammenführung mit dem Bestand ──────────────────────────────────────────
def merge_into_existing(existing: Contact, mapped: MappedContact,
                        source: BridgeContact) -> Contact:
    """Führt eine frische Abbildung mit dem Bestand zusammen.

    Zwei Dinge werden ausdrücklich **nicht** überschrieben:

    1. Felder im Zustand `unavailable_by_capability` — sie behalten den
       bestehenden Wert. Andernfalls löschte eine Fähigkeitslücke des
       Providers vorhandene Daten (08 §4).
    2. Lokales Eigentum — Kennung, Arbeitsbereich, Rollen, Revisionszähler und
       die Vorgangsverweise gehören dem Bestand, nicht dem Provider.
    """
    neu = mapped.contact
    uebernahmen: dict[str, object] = {
        name: getattr(existing, name) for name in _LOCAL_ONLY
    }
    uebernahmen["local_revision"] = existing.local_revision + 1

    for attribut, feld in _SCALAR_FIELDS:
        if source.field_availability.is_unavailable(feld):
            uebernahmen[attribut] = getattr(existing, attribut)
    for attribut, feld in _COLLECTION_FIELDS:
        if source.field_availability.is_unavailable(feld):
            uebernahmen[attribut] = getattr(existing, attribut)

    if source.field_availability.is_unavailable("thumbnail"):
        uebernahmen["image_available"] = existing.image_available
        uebernahmen["thumbnail_blob_ref"] = existing.thumbnail_blob_ref
    if source.field_availability.is_unavailable(_NAME_BLOCK):
        # Ohne lesbaren Namensblock wäre der neue Anzeigename ein Platzhalter,
        # der einen vorhandenen Namen überschriebe.
        uebernahmen["display_name"] = existing.display_name

    return replace(neu, **uebernahmen)


def content_equals(links: Contact, rechts: Contact) -> bool:
    """Ob zwei Kontakte inhaltlich gleich sind — ohne Zeit und Zählerstände.

    Damit erkennt der Delta-Pfad ein Ereignis, das nichts geändert hat, und
    schreibt nicht. Kennungen der Kinddatensätze bleiben aussen vor: sie werden
    bei jeder Abbildung neu vergeben und sagen nichts über den Inhalt.
    """
    def kinder(werte) -> tuple:
        return tuple(
            tuple((f.name, getattr(v, f.name))
                  for f in dataclass_fields(v) if f.name != "id")
            for v in werte
        )

    def profil(c: Contact) -> tuple:
        skalare = tuple(
            (name, getattr(c, name))
            for name, _ in (*_SCALAR_FIELDS, ("display_name", ""),
                            ("contact_type", ""), ("is_me_card", ""),
                            ("image_available", ""), ("field_completeness", ""))
        )
        sammlungen = tuple(
            (name, kinder(getattr(c, name))) for name, _ in _COLLECTION_FIELDS
        )
        verfuegbarkeit = tuple(
            sorted((e.field_name, e.state) for e in c.field_availability)
        )
        return (skalare, sammlungen, verfuegbarkeit)

    return profil(links) == profil(rechts)
