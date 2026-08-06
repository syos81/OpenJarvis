"""Geschlossener, versionierter Feldvertrag v1 der Provider-Mutationen.

**Warum geschlossen.** Bis hierher war die Nutzlast ein `dict[str, Any]`: die
Providergrenze nahm entgegen, was ihr gereicht wurde, und was der Sidecar
damit anfangen würde, stand nirgends. Ein Vertrag, den nur der Empfänger
kennt, ist kein Vertrag. Hier steht er — mit Typen, Grenzen, geschlossenem
Labelvorrat und einer kanonischen Form, die auf beiden Seiten dieselbe ist.

**Warum versioniert.** Der Sidecar und der Kern werden getrennt gebaut und
getrennt signiert. Ohne Versionsnummer könnte ein neuer Kern einem alten
Sidecar Felder schicken, die dieser stillschweigend verwirft — ein
Datenverlust, den niemand bemerkt. Beide Seiten nennen ihre Version, und
Ungleichheit ist fail-closed (ADR-0025 §6).

**Was v1 ausdrücklich nicht kann** — jede Aufnahme verlangt v2 und eine
eigene Entscheidung: Notizen (ohne Apple-Entitlement nicht lesbar, also auch
nicht schreibbar, ohne eine vorhandene Notiz zu zerstören), Kontaktbild,
Me-Karte als Ziel, Link/Unlink, soziale Profile, Sofortnachrichten,
Beziehungen, Gruppenmitgliedschaften, `sub_locality` (im Domänenmodell
vorhanden, aber vom Sidecar-DTO nicht ausgegeben — ein Schreibvertrag dafür
wäre nicht verlustfrei rücklesbar) und jedes unbekannte Feld.

**Listenreihenfolge.** Listen werden kanonisch sortiert — auf dem Weg zum
Provider *und* im Digest. Der Preis ist bekannt und in v1 bewusst bezahlt:
die Reihenfolge innerhalb einer Liste ist nicht frei wählbar. Der Gewinn ist,
dass der Read-back-Vergleich unabhängig davon wird, in welcher Reihenfolge
Apple die Werte zurückgibt — sonst wäre jede Umsortierung durch den Provider
von einer echten Abweichung nicht zu unterscheiden.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from typing import Any, Mapping

from personaljarvis.base.digest import digest_of
from personaljarvis.contacts.application.errors import InvalidCommand

__all__ = [
    "FIELD_CONTRACT_VERSION",
    "MUTATION_CONTRACT_VERSION",
    "SCALAR_FIELDS",
    "LIST_FIELDS",
    "CREATE_FIELDS",
    "EMAIL_LABELS",
    "PHONE_LABELS",
    "ADDRESS_LABELS",
    "URL_LABELS",
    "DATE_LABELS",
    "CONTACT_TYPES",
    "Birthday",
    "LabeledText",
    "PostalAddressValue",
    "DateValue",
    "CreateFields",
    "parse_create_fields",
    "parse_canonical_payload",
    "canonical_payload",
    "canonical_patch",
    "preview_items",
    "readback_digest",
    "project_bridge_contact",
    "project_local_contact",
    "as_bridge_contact",
    "NEVER_WRITABLE",
]

#: Version des Feldvertrags. Eine Änderung an Feldmenge, Typen, Grenzen,
#: Labelvorrat oder kanonischer Form erhöht sie — und macht damit jeden
#: Sidecar mit anderer Version fail-closed unbrauchbar.
FIELD_CONTRACT_VERSION = 1

#: Version der Mutationshülle (Pflichtfelder, Ergebnisvertrag, Operationen).
#: Getrennt vom Feldvertrag, weil sich beides unabhängig ändern kann.
MUTATION_CONTRACT_VERSION = 1

#: Obergrenze jedes einzelnen Textwertes.
MAX_TEXT = 256
MAX_EMAIL = 254
MAX_PHONE = 64
MAX_URL = 512

#: Skalare Textfelder: API-Name → Schlüssel der kanonischen Form.
SCALAR_FIELDS: dict[str, str] = {
    "given_name": "givenName",
    "middle_name": "middleName",
    "family_name": "familyName",
    "previous_family_name": "previousFamilyName",
    "name_prefix": "namePrefix",
    "name_suffix": "nameSuffix",
    "nickname": "nickname",
    "phonetic_given_name": "phoneticGivenName",
    "phonetic_family_name": "phoneticFamilyName",
    "organization_name": "organizationName",
    "department_name": "departmentName",
    "job_title": "jobTitle",
}

#: Listenfelder: API-Name → (kanonischer Schlüssel, Höchstzahl).
LIST_FIELDS: dict[str, tuple[str, int]] = {
    "emails": ("emails", 10),
    "phones": ("phones", 10),
    "postal_addresses": ("postalAddresses", 5),
    "urls": ("urls", 10),
    "dates": ("dates", 5),
}

#: Vollständige, geschlossene Feldmenge eines `create` in v1.
CREATE_FIELDS: frozenset[str] = frozenset(
    set(SCALAR_FIELDS) | set(LIST_FIELDS) | {"contact_type", "birthday"})

CONTACT_TYPES: frozenset[str] = frozenset({"person", "organization"})

#: Felder, die v1 nicht nur nicht kennt, sondern ausdrücklich verweigert. Sie
#: bekommen eine eigene Meldung: „unbekannt" wäre irreführend, denn sie sind
#: sehr wohl bekannt — nur nie schreibbar.
NEVER_WRITABLE: frozenset[str] = frozenset({
    "note", "notes", "id", "local_revision", "is_me_card",
    "unified_identifier", "thumbnail_blob_ref", "image_available",
    "thumbnail", "photo", "image", "social_profiles", "instant_messages",
    "relations", "groups", "sub_locality",
})

#: Geschlossene Labelvorräte. Ein freies Label ist in v1 `invalid_request`:
#: Apple speichert es unverändert, aber der Rückweg über `normalize_label`
#: ist für beliebige Zeichenketten nicht bewiesen — und ein Label, dessen
#: Read-back nicht belegt ist, gehört nicht in einen Schreibvertrag.
EMAIL_LABELS: frozenset[str] = frozenset({"home", "work", "other"})
PHONE_LABELS: frozenset[str] = frozenset({"home", "work", "mobile", "main",
                                          "other"})
ADDRESS_LABELS: frozenset[str] = frozenset({"home", "work", "other"})
URL_LABELS: frozenset[str] = frozenset({"home", "work", "other"})
#: Frei benannte Anlässe („Jahrestag") erst mit v2 — der Rückweg eines freien
#: Datumslabels ist ebenso wenig belegt.
DATE_LABELS: frozenset[str] = frozenset({"other"})

#: Adresskomponenten in kanonischer Reihenfolge. `sub_locality` fehlt
#: absichtlich (siehe Modul-Dokumentation).
ADDRESS_PARTS: tuple[str, ...] = ("street", "city", "state", "postal_code",
                                  "country", "iso_country_code")
_ADDRESS_KEYS: dict[str, str] = {
    "street": "street", "city": "city", "state": "state",
    "postal_code": "postalCode", "country": "country",
    "iso_country_code": "isoCountryCode",
}


# ── Wertetypen ───────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class Birthday:
    month: int
    day: int
    year: int | None = None


@dataclass(frozen=True)
class LabeledText:
    label: str | None
    value: str


@dataclass(frozen=True)
class PostalAddressValue:
    label: str | None
    street: str = ""
    city: str = ""
    state: str = ""
    postal_code: str = ""
    country: str = ""
    iso_country_code: str = ""

    @property
    def is_empty(self) -> bool:
        return not any(getattr(self, teil) for teil in ADDRESS_PARTS)


@dataclass(frozen=True)
class DateValue:
    label: str | None
    month: int
    day: int
    year: int | None = None


@dataclass(frozen=True)
class CreateFields:
    """Kanonischer, vollständig geprüfter Entwurf eines `create` in v1."""

    contact_type: str = "person"
    scalars: Mapping[str, str] = None            # type: ignore[assignment]
    birthday: Birthday | None = None
    emails: tuple[LabeledText, ...] = ()
    phones: tuple[LabeledText, ...] = ()
    postal_addresses: tuple[PostalAddressValue, ...] = ()
    urls: tuple[LabeledText, ...] = ()
    dates: tuple[DateValue, ...] = ()

    def __post_init__(self) -> None:
        if self.scalars is None:
            object.__setattr__(self, "scalars", {})

    @property
    def is_empty(self) -> bool:
        """Nur `contact_type` ist kein Kontakt, sondern eine leere Hülle."""
        return not (self.scalars or self.birthday or self.emails or self.phones
                    or self.postal_addresses or self.urls or self.dates)


# ── Prüfhilfen ───────────────────────────────────────────────────────────────
def _text(wert: Any, *, feld: str, grenze: int = MAX_TEXT) -> str:
    if not isinstance(wert, str):
        raise InvalidCommand(f"{feld}: Text erwartet")
    # Unicode-Normalform: „é" als ein Zeichen und als e+Akzent sind derselbe
    # Name. Ohne diese Normalisierung ergaeben sie verschiedene Digests, und
    # ein Read-back-Vergleich schluege ohne fachlichen Grund fehl.
    normal = unicodedata.normalize("NFC", wert).strip()
    if not normal:
        raise InvalidCommand(
            f"{feld}: leerer Wert. Ein Feld weglassen heisst 'nicht setzen'; "
            f"ein leerer Wert waere eine Loeschung, die create nicht kennt")
    if len(normal) > grenze:
        raise InvalidCommand(f"{feld}: laenger als {grenze} Zeichen")
    if any(unicodedata.category(z) == "Cc" for z in normal):
        raise InvalidCommand(f"{feld}: Steuerzeichen sind nicht zulaessig")
    return normal


def _label(wert: Any, *, feld: str, vorrat: frozenset[str]) -> str | None:
    if wert is None:
        return None
    if not isinstance(wert, str):
        raise InvalidCommand(f"{feld}: Label muss Text oder null sein")
    kern = wert.strip().lower()
    if kern not in vorrat:
        raise InvalidCommand(
            f"{feld}: unbekanntes Label '{kern}'. Zulaessig: "
            f"{', '.join(sorted(vorrat))}")
    return kern


def _liste(wert: Any, *, feld: str, grenze: int) -> list:
    if not isinstance(wert, (list, tuple)):
        raise InvalidCommand(f"{feld}: Liste erwartet")
    if len(wert) > grenze:
        raise InvalidCommand(f"{feld}: hoechstens {grenze} Eintraege")
    return list(wert)


def _eintrag(wert: Any, *, feld: str, erlaubt: frozenset[str]) -> dict:
    if not isinstance(wert, Mapping):
        raise InvalidCommand(f"{feld}: Objekt erwartet")
    unbekannt = sorted(set(wert) - erlaubt)
    if unbekannt:
        raise InvalidCommand(f"{feld}: unbekannte Schluessel: "
                             f"{', '.join(unbekannt)}")
    return dict(wert)


def _tag(wert: Any, *, feld: str, unten: int, oben: int,
         pflicht: bool = True) -> int | None:
    if wert is None:
        if pflicht:
            raise InvalidCommand(f"{feld}: Pflichtangabe")
        return None
    if not isinstance(wert, int) or isinstance(wert, bool):
        raise InvalidCommand(f"{feld}: ganze Zahl erwartet")
    if not unten <= wert <= oben:
        raise InvalidCommand(f"{feld}: ausserhalb von {unten}..{oben}")
    return wert


def _wert_liste(roh: Any, *, feld: str, grenze: int, vorrat: frozenset[str],
                textgrenze: int, pruefer=None) -> tuple[LabeledText, ...]:
    ergebnis = []
    for i, eintrag in enumerate(_liste(roh, feld=feld, grenze=grenze)):
        e = _eintrag(eintrag, feld=f"{feld}[{i}]", erlaubt={"label", "value"})
        wert = _text(e.get("value"), feld=f"{feld}[{i}].value",
                     grenze=textgrenze)
        if pruefer is not None:
            pruefer(wert, f"{feld}[{i}].value")
        ergebnis.append(LabeledText(
            label=_label(e.get("label"), feld=f"{feld}[{i}].label",
                         vorrat=vorrat),
            value=wert))
    # **Reihenfolge ist Position, nicht Sortierung** (ADR-0026 §7). Hier
    # wurde früher nach `(label, value)` sortiert — eine stille Kanonisierung,
    # die zweierlei kaputt macht: Sie verdreht die Absicht des Menschen (wer
    # die Arbeitsadresse zuerst nennt, will sie zuerst haben), und sie
    # entkoppelt den Digest von dem, was der Provider zurückliest. Aufgefallen
    # im Update-Livetest 2026-08-04 mit zwei E-Mails; beim Create mit je einem
    # Wert war es unsichtbar.
    return tuple(ergebnis)


def _pruefe_mail(wert: str, feld: str) -> None:
    if "@" not in wert or wert.startswith("@") or wert.endswith("@"):
        raise InvalidCommand(f"{feld}: keine E-Mail-Adresse")
    if any(z.isspace() for z in wert):
        raise InvalidCommand(f"{feld}: E-Mail enthaelt Leerraum")


def _pruefe_url(wert: str, feld: str) -> None:
    if any(z.isspace() for z in wert):
        raise InvalidCommand(f"{feld}: URL enthaelt Leerraum")


# ── Eingang: rohes Mapping → geprüfter Vertrag ───────────────────────────────
def parse_create_fields(roh: Mapping[str, Any]) -> CreateFields:
    """Prüft ein rohes Feld-Mapping gegen v1 und kanonisiert es.

    Unbekannte Felder werden abgewiesen, nicht durchgereicht. Ein `null` gilt
    bei `create` als „nicht gesetzt" — eine Löschung gibt es hier nicht, weil
    es nichts zu löschen gibt.
    """
    if not isinstance(roh, Mapping):
        raise InvalidCommand("Feldmenge: Objekt erwartet")
    verweigert = sorted(set(roh) & NEVER_WRITABLE)
    if verweigert:
        raise InvalidCommand(
            f"Diese Felder sind in v{FIELD_CONTRACT_VERSION} nie schreibbar: "
            f"{', '.join(verweigert)}")
    unbekannt = sorted(set(roh) - CREATE_FIELDS)
    if unbekannt:
        raise InvalidCommand(
            f"Unbekannte Felder im Feldvertrag v{FIELD_CONTRACT_VERSION}: "
            f"{', '.join(unbekannt)}")

    art = roh.get("contact_type")
    if art is None:
        art = "person"
    elif art not in CONTACT_TYPES:
        raise InvalidCommand(
            f"contact_type: zulaessig sind {', '.join(sorted(CONTACT_TYPES))}")

    skalare: dict[str, str] = {}
    for name in SCALAR_FIELDS:
        if roh.get(name) is None:
            continue
        skalare[name] = _text(roh[name], feld=name)

    geburtstag = None
    if roh.get("birthday") is not None:
        e = _eintrag(roh["birthday"], feld="birthday",
                     erlaubt={"year", "month", "day"})
        geburtstag = Birthday(
            month=_tag(e.get("month"), feld="birthday.month", unten=1, oben=12),
            day=_tag(e.get("day"), feld="birthday.day", unten=1, oben=31),
            year=_tag(e.get("year"), feld="birthday.year", unten=1, oben=9999,
                      pflicht=False))

    adressen: list[PostalAddressValue] = []
    for i, eintrag in enumerate(_liste(roh.get("postal_addresses") or [],
                                       feld="postal_addresses", grenze=5)):
        e = _eintrag(eintrag, feld=f"postal_addresses[{i}]",
                     erlaubt={"label", *ADDRESS_PARTS})
        teile: dict[str, str] = {}
        for teil in ADDRESS_PARTS:
            if e.get(teil) is None:
                continue
            grenze = 2 if teil == "iso_country_code" else MAX_TEXT
            wert = _text(e[teil], feld=f"postal_addresses[{i}].{teil}",
                         grenze=grenze)
            if teil == "iso_country_code":
                if len(wert) != 2 or not wert.isalpha():
                    raise InvalidCommand(
                        f"postal_addresses[{i}].iso_country_code: genau zwei "
                        f"Buchstaben erwartet")
                wert = wert.upper()
            teile[teil] = wert
        adresse = PostalAddressValue(
            label=_label(e.get("label"), feld=f"postal_addresses[{i}].label",
                         vorrat=ADDRESS_LABELS), **teile)
        if adresse.is_empty:
            raise InvalidCommand(
                f"postal_addresses[{i}]: eine Anschrift ohne jede Komponente "
                f"ist kein Wert")
        adressen.append(adresse)

    daten: list[DateValue] = []
    for i, eintrag in enumerate(_liste(roh.get("dates") or [], feld="dates",
                                       grenze=5)):
        e = _eintrag(eintrag, feld=f"dates[{i}]",
                     erlaubt={"label", "year", "month", "day"})
        daten.append(DateValue(
            label=_label(e.get("label"), feld=f"dates[{i}].label",
                         vorrat=DATE_LABELS),
            month=_tag(e.get("month"), feld=f"dates[{i}].month", unten=1,
                       oben=12),
            day=_tag(e.get("day"), feld=f"dates[{i}].day", unten=1, oben=31),
            year=_tag(e.get("year"), feld=f"dates[{i}].year", unten=1,
                      oben=9999, pflicht=False)))

    felder = CreateFields(
        contact_type=art,
        scalars=dict(sorted(skalare.items())),
        birthday=geburtstag,
        emails=_wert_liste(roh.get("emails") or [], feld="emails", grenze=10,
                           vorrat=EMAIL_LABELS, textgrenze=MAX_EMAIL,
                           pruefer=_pruefe_mail),
        phones=_wert_liste(roh.get("phones") or [], feld="phones", grenze=10,
                           vorrat=PHONE_LABELS, textgrenze=MAX_PHONE),
        # Ebenfalls Position, nicht Sortierung (siehe `_wert_liste`).
        postal_addresses=tuple(adressen),
        urls=_wert_liste(roh.get("urls") or [], feld="urls", grenze=10,
                         vorrat=URL_LABELS, textgrenze=MAX_URL,
                         pruefer=_pruefe_url),
        dates=tuple(daten),
    )
    if felder.is_empty:
        raise InvalidCommand(
            "Ein Entwurf ohne jedes Feld legt keinen Kontakt an")
    return felder


def parse_canonical_payload(roh: Mapping[str, Any]) -> CreateFields:
    """Rückweg aus der kanonischen Nutzlast in den typisierten Vertrag.

    Gebraucht beim Wiederaufnehmen eines gespeicherten Vorgangs: in
    `payload_json` liegt die kanonische Form, nicht die API-Form. Der Weg
    zurück führt über dieselbe Prüfung wie der Hinweg — es gibt keinen
    ungeprüften Eintritt in den Vertrag.
    """
    umkehr = {kanonisch: api for api, kanonisch in SCALAR_FIELDS.items()}
    listen = {kanonisch: api for api, (kanonisch, _) in LIST_FIELDS.items()}
    adress_umkehr = {kanonisch: api for api, kanonisch in _ADDRESS_KEYS.items()}
    out: dict[str, Any] = {}
    for schluessel, wert in roh.items():
        if schluessel == "contactType":
            out["contact_type"] = wert
        elif schluessel == "birthday":
            out["birthday"] = wert
        elif schluessel in umkehr:
            out[umkehr[schluessel]] = wert
        elif schluessel == "postalAddresses":
            out["postal_addresses"] = [
                {adress_umkehr.get(k, k): v for k, v in eintrag.items()}
                for eintrag in wert]
        elif schluessel in listen:
            out[listen[schluessel]] = wert
        else:
            raise InvalidCommand(
                f"Kanonische Nutzlast enthaelt unbekannten Schluessel: "
                f"{schluessel}")
    return parse_create_fields(out)


# ── Kanonische Form ──────────────────────────────────────────────────────────
def canonical_payload(felder: CreateFields) -> dict:
    """Die eine Darstellung — für Sidecar-Nutzlast **und** Digest.

    Nur gesetzte Felder erscheinen. Damit hängt der Digest nicht davon ab, ob
    ein Feld weggelassen oder als `null` geschickt wurde: beides heisst
    dasselbe und muss dasselbe ergeben.
    """
    out: dict[str, Any] = {"contactType": felder.contact_type}
    for name, wert in felder.scalars.items():
        out[SCALAR_FIELDS[name]] = wert
    if felder.birthday is not None:
        out["birthday"] = {"year": felder.birthday.year,
                           "month": felder.birthday.month,
                           "day": felder.birthday.day}
    if felder.emails:
        out["emails"] = [{"label": e.label, "value": e.value}
                         for e in felder.emails]
    if felder.phones:
        out["phones"] = [{"label": p.label, "value": p.value}
                         for p in felder.phones]
    if felder.postal_addresses:
        out["postalAddresses"] = [
            {"label": a.label,
             **{_ADDRESS_KEYS[t]: getattr(a, t) for t in ADDRESS_PARTS
                if getattr(a, t)}}
            for a in felder.postal_addresses]
    if felder.urls:
        out["urls"] = [{"label": u.label, "value": u.value}
                       for u in felder.urls]
    if felder.dates:
        out["dates"] = [{"label": d.label, "year": d.year, "month": d.month,
                         "day": d.day} for d in felder.dates]
    return out


def _datum(jahr: int | None, monat: int, tag: int) -> str:
    return f"{jahr:04d}-{monat:02d}-{tag:02d}" if jahr else f"--{monat:02d}-{tag:02d}"


def preview_items(felder: CreateFields) -> tuple[tuple[str, Any], ...]:
    """Anzeigefertige Paare (API-Feldname, Wert) für die Vorschau.

    Bewusst die **API**-Namen und nicht die kanonischen Schlüssel: der Mensch
    vor dem Freigabedialog sieht dieselbe Bezeichnung, die er im Formular
    ausgefüllt hat.
    """
    zeilen: list[tuple[str, Any]] = [("contact_type", felder.contact_type)]
    zeilen.extend(felder.scalars.items())
    if felder.birthday is not None:
        zeilen.append(("birthday", _datum(felder.birthday.year,
                                          felder.birthday.month,
                                          felder.birthday.day)))

    def beschriftet(werte) -> list[str]:
        return [f"{w.label}: {w.value}" if w.label else w.value for w in werte]

    for name, werte in (("emails", felder.emails), ("phones", felder.phones),
                        ("urls", felder.urls)):
        if werte:
            zeilen.append((name, beschriftet(werte)))
    if felder.postal_addresses:
        zeilen.append(("postal_addresses", [
            ((f"{a.label}: " if a.label else "")
             + ", ".join(getattr(a, t) for t in ADDRESS_PARTS if getattr(a, t)))
            for a in felder.postal_addresses]))
    if felder.dates:
        zeilen.append(("dates", [
            (f"{d.label}: " if d.label else "") + _datum(d.year, d.month, d.day)
            for d in felder.dates]))
    return tuple(zeilen)


def readback_digest(felder: CreateFields) -> str:
    """Fingerabdruck eines Feldstands — der stabile Revisionsbeleg.

    Apple stellt keine Revisionsnummer bereit. Dieser Digest tritt an ihre
    Stelle: er deckt ausschliesslich die kanonischen, schreibbaren v1-Felder
    ab und bindet die Vertragsversion mit ein. Er enthält **keinen**
    Provider-Identifier, **keine** lokale Kennung, **keinen** Pfad und
    **keinen** Zeitstempel — derselbe fachliche Inhalt ergibt auf jeder
    Plattform denselben Wert.
    """
    return digest_of({"fieldContractVersion": FIELD_CONTRACT_VERSION,
                      "fields": canonical_payload(felder)})


# ── Rückweg: Provider-Read-back → Vertrag ────────────────────────────────────
def project_bridge_contact(kontakt) -> CreateFields:
    """Projiziert einen gelesenen Providerdatensatz auf die v1-Feldmenge.

    Der Kern normalisiert, nicht der Sidecar (ADR-0016 Punkt 4) — deshalb
    entsteht der Read-back-Digest **hier** und nicht drüben. Der Sidecar
    liefert die Rohwerte samt Apple-Rohlabels; die Rückführung auf den
    Labelvorrat ist dieselbe wie im Lesepfad.

    Ein Feld, das der Provider als `unavailable_by_capability` meldet, wird
    ausgelassen statt als leer geführt — sonst behauptete der Digest eine
    Abwesenheit, die der Provider nie belegt hat.
    """
    from personaljarvis.contacts.sync.mapper import normalize_label

    verfuegbar = kontakt.field_availability

    def sichtbar(schluessel: str) -> bool:
        return not verfuegbar.is_unavailable(schluessel)

    skalare: dict[str, str] = {}
    _NAME, _ORG = "givenName", "organizationName"
    for name, schluessel in (
            ("given_name", _NAME), ("middle_name", _NAME),
            ("family_name", "familyName"), ("previous_family_name", _NAME),
            ("name_prefix", _NAME), ("name_suffix", _NAME),
            ("nickname", _NAME), ("phonetic_given_name", _NAME),
            ("phonetic_family_name", _NAME), ("organization_name", _ORG),
            ("department_name", _ORG), ("job_title", _ORG)):
        if not sichtbar(schluessel):
            continue
        roh = getattr(kontakt, name, "") or ""
        wert = unicodedata.normalize("NFC", roh).strip()
        if wert:
            skalare[name] = wert

    geburtstag = None
    if sichtbar("birthday") and isinstance(kontakt.birthday, dict):
        monat, tag = kontakt.birthday.get("month"), kontakt.birthday.get("day")
        if isinstance(monat, int) and isinstance(tag, int):
            jahr = kontakt.birthday.get("year")
            geburtstag = Birthday(month=monat, day=tag,
                                  year=jahr if isinstance(jahr, int) else None)

    def texte(werte, schluessel: str) -> tuple[LabeledText, ...]:
        if not sichtbar(schluessel):
            return ()
        eintraege = [
            LabeledText(label=normalize_label(w.label),
                        value=unicodedata.normalize("NFC", w.value).strip())
            for w in werte if (w.value or "").strip()]
        # Auch hier Position statt Sortierung: Der Read-back muss dieselbe
        # Ordnung liefern wie der Entwurf, sonst vergleicht der Digest zwei
        # verschiedene Ordnungen desselben Inhalts.
        return tuple(eintraege)

    adressen: list[PostalAddressValue] = []
    if sichtbar("postalAddresses"):
        for a in kontakt.postal_addresses:
            adresse = PostalAddressValue(
                label=normalize_label(a.label),
                street=(a.street or "").strip(), city=(a.city or "").strip(),
                state=(a.state or "").strip(),
                postal_code=(a.postal_code or "").strip(),
                country=(a.country or "").strip(),
                iso_country_code=(a.iso_country_code or "").strip().upper())
            if not adresse.is_empty:
                adressen.append(adresse)

    daten: list[DateValue] = []
    if sichtbar("birthday"):
        for d in kontakt.dates:
            if isinstance(d.month, int) and isinstance(d.day, int):
                daten.append(DateValue(label=normalize_label(d.label),
                                       month=d.month, day=d.day, year=d.year))

    return CreateFields(
        contact_type=(kontakt.contact_type
                      if kontakt.contact_type in CONTACT_TYPES else "person"),
        scalars=dict(sorted(skalare.items())),
        birthday=geburtstag,
        emails=texte(kontakt.emails, "emails"),
        phones=texte(kontakt.phones, "phones"),
        # Ebenfalls Position, nicht Sortierung (siehe `_wert_liste`).
        postal_addresses=tuple(adressen),
        urls=texte(kontakt.urls, "urlAddresses"),
        dates=tuple(daten),
    )


# ── Rückweg ohne Provider: Vertrag → Bridge-DTO ──────────────────────────────
def as_bridge_contact(felder: CreateFields, *, provider_identifier: str,
                      key_set_version: int = 1):
    """Baut aus einem v1-Feldstand ein `BridgeContact`-DTO.

    Gebraucht wird das für **einen** Fall: eine lokale Nachführung, die
    wiederholt werden muss, nachdem der Provider bereits bestätigt hat. Der
    Read-back aus dem ursprünglichen Lauf existiert dann nicht mehr im
    Speicher — aber `readback_digest` belegt, ob der Providerzustand mit dem
    Entwurf übereinstimmt. Tut er das, ist der Entwurf beweisbar dasselbe wie
    der Read-back, und die Nachführung braucht **keinen** erneuten
    Providerkontakt (ADR-0025 §5).

    Das DTO geht anschliessend durch denselben Mapper wie jeder gelesene
    Kontakt — es gibt keinen zweiten Abbildungsweg in die Domäne.
    """
    from personaljarvis.contacts.bridge.models import (
        BridgeContact,
        DatedValue,
        FieldAvailability,
        FieldState,
        LabeledValue,
    )
    from personaljarvis.contacts.bridge.models import (
        PostalAddress as BridgePostalAddress,
    )

    def zustand(gesetzt: bool) -> FieldState:
        # „absent" ist bei einem eben angelegten Datensatz eine belegte
        # Aussage: der Provider hat das Feld geliefert, es ist leer. Nur
        # `note` bleibt `unavailable_by_capability` — es wurde nie gelesen.
        return FieldState.PRESENT if gesetzt else FieldState.ABSENT

    hat_namen = any(n in felder.scalars for n in (
        "given_name", "middle_name", "family_name", "previous_family_name",
        "name_prefix", "name_suffix", "nickname", "phonetic_given_name",
        "phonetic_family_name"))
    hat_org = any(n in felder.scalars for n in (
        "organization_name", "department_name", "job_title"))

    verfuegbar = FieldAvailability({
        "note": FieldState.UNAVAILABLE_BY_CAPABILITY,
        "givenName": zustand(hat_namen),
        "familyName": zustand("family_name" in felder.scalars),
        "organizationName": zustand(hat_org),
        "birthday": zustand(felder.birthday is not None or bool(felder.dates)),
        "emails": zustand(bool(felder.emails)),
        "phones": zustand(bool(felder.phones)),
        "postalAddresses": zustand(bool(felder.postal_addresses)),
        "urlAddresses": zustand(bool(felder.urls)),
        "socialProfiles": FieldState.ABSENT,
        "instantMessages": FieldState.ABSENT,
        "relations": FieldState.ABSENT,
        "thumbnail": FieldState.ABSENT,
    })

    geburtstag = None
    if felder.birthday is not None:
        geburtstag = {"year": felder.birthday.year,
                      "month": felder.birthday.month,
                      "day": felder.birthday.day}

    return BridgeContact(
        provider_identifier=provider_identifier,
        key_set_version=key_set_version,
        contact_type=felder.contact_type,
        is_me_card=False,
        field_availability=verfuegbar,
        field_completeness="full",
        emails=tuple(LabeledValue(label=e.label, value=e.value)
                     for e in felder.emails),
        phones=tuple(LabeledValue(label=p.label, value=p.value)
                     for p in felder.phones),
        postal_addresses=tuple(BridgePostalAddress(
            label=a.label, street=a.street, city=a.city, state=a.state,
            postal_code=a.postal_code, country=a.country,
            iso_country_code=a.iso_country_code)
            for a in felder.postal_addresses),
        urls=tuple(LabeledValue(label=u.label, value=u.value)
                   for u in felder.urls),
        dates=tuple(DatedValue(label=d.label, year=d.year, month=d.month,
                               day=d.day) for d in felder.dates),
        birthday=geburtstag,
        **{name: felder.scalars.get(name, "") for name in SCALAR_FIELDS},
    )


# ── Lokaler Zielzustand: die Grundlage jedes Update- und Delete-Vergleichs ───
#: Spalten der Kontaktzeile, die zu einem v1-Skalar gehören. Bewusst
#: aufgezählt statt hergeleitet: Was hier fehlt, wird auch nicht verglichen —
#: und das soll man sehen, nicht erraten.
_LOKALE_SKALARE: dict[str, str] = {
    "given_name": "given_name",
    "middle_name": "middle_name",
    "family_name": "family_name",
    "previous_family_name": "previous_family_name",
    "name_prefix": "name_prefix",
    "name_suffix": "name_suffix",
    "nickname": "nickname",
    "phonetic_given_name": "phonetic_given_name",
    "phonetic_family_name": "phonetic_family_name",
    "organization_name": "organization_name",
    "department_name": "department_name",
    "job_title": "job_title",
}


def project_local_contact(uow, contact_id: str) -> CreateFields:
    """Projiziert den **lokalen** Spiegel auf die v1-Feldmenge.

    Das ist der Zustand, den der Mensch in der Vorschau sieht — und damit der
    einzige, gegen den sich vor einem Update oder Delete sinnvoll vergleichen
    lässt. Der Providerzustand wird nicht geraten: Ob er noch derselbe ist,
    entscheidet der native Pfad, indem er unmittelbar vor dem Save liest.

    Leere Werte werden ausgelassen, nicht als leer geführt: `canonical_payload`
    behandelt Fehlen und Leere gleich, und der Digest darf nicht davon
    abhängen, ob eine Spalte `NULL` oder `''` enthält.
    """
    zeile = uow.execute(
        "SELECT * FROM contacts WHERE id = ?", (contact_id,)).fetchone()
    if zeile is None:
        raise InvalidCommand("Zielkontakt existiert lokal nicht")

    roh: dict[str, Any] = {}
    for api_name, spalte in _LOKALE_SKALARE.items():
        wert = zeile[spalte]
        if wert:
            roh[api_name] = wert
    if zeile["contact_type"]:
        roh["contact_type"] = zeile["contact_type"]
    if zeile["birthday_month"] and zeile["birthday_day"]:
        roh["birthday"] = {"year": zeile["birthday_year"],
                           "month": zeile["birthday_month"],
                           "day": zeile["birthday_day"]}

    def liste(tabelle: str, wertspalte: str) -> list[dict]:
        return [{"label": r["label_normalized"], "value": r[wertspalte]}
                for r in uow.execute(
                    f"SELECT label_normalized, {wertspalte} FROM {tabelle} "
                    "WHERE contact_id = ? ORDER BY position", (contact_id,))
                if r[wertspalte]]

    for name, tabelle, spalte in (("emails", "contact_emails", "value_raw"),
                                  ("phones", "contact_phones", "value_raw"),
                                  ("urls", "contact_urls", "value_raw")):
        werte = liste(tabelle, spalte)
        if werte:
            roh[name] = werte

    anschriften = []
    for r in uow.execute(
            "SELECT label_normalized, street, city, state, postal_code, "
            "country, iso_country_code FROM contact_postal_addresses "
            "WHERE contact_id = ? ORDER BY position", (contact_id,)):
        eintrag: dict[str, Any] = {"label": r["label_normalized"]}
        for feld in ("street", "city", "state", "country"):
            if r[feld]:
                eintrag[feld] = r[feld]
        if r["postal_code"]:
            eintrag["postal_code"] = r["postal_code"]
        if r["iso_country_code"]:
            eintrag["iso_country_code"] = r["iso_country_code"]
        anschriften.append(eintrag)
    if anschriften:
        roh["postal_addresses"] = anschriften

    termine = [{"label": r["label_normalized"], "year": r["year"],
                "month": r["month"], "day": r["day"]}
               for r in uow.execute(
                   "SELECT label_normalized, year, month, day FROM "
                   "contact_dates WHERE contact_id = ? AND kind != 'birthday' "
                   "ORDER BY position", (contact_id,))
               if r["month"] and r["day"]]
    if termine:
        roh["dates"] = termine

    return parse_create_fields(roh)


def canonical_patch(roh: Mapping[str, Any]) -> dict:
    """Bringt einen **Patch** in die kanonische Form — nur die genannten Felder.

    Nötig geworden im Livetest am 2026-08-04: Der Update-Payload trug die
    API-Namen (`family_name`), der native Pfad erwartet die kanonischen
    Schlüssel (`familyName`). Beim Create fiel das nie auf, weil dort der
    ganze Entwurf durch `parse_create_fields` und `canonical_payload` läuft;
    der Patch wurde roh durchgereicht. Der native Torwächter hat es korrekt
    als `unsupported_field` abgewiesen — vor jeder Übergabe.

    Der Unterschied zu `canonical_payload`: Hier ist **Fehlen** bedeutsam.
    Ein nicht genanntes Feld bleibt unangetastet, ein genanntes `null`
    (Skalar) beziehungsweise `[]` (Liste) löscht ausdrücklich. Beides muss
    den Digest erreichen — sonst hinge die Löschung an einer Auslassung.
    """
    out: dict[str, Any] = {}
    for name, wert in roh.items():
        if name in SCALAR_FIELDS:
            if wert is None:
                out[SCALAR_FIELDS[name]] = None
            else:
                out[SCALAR_FIELDS[name]] = _text(wert, feld=name)
            continue
        if name == "contact_type":
            raise InvalidCommand(
                "Ein Typwechsel ist in v1 nicht zugesagt (ADR-0026 §7)")
        if name == "birthday":
            if wert is None:
                out["birthday"] = None
            else:
                felder = parse_create_fields({"birthday": wert})
                out["birthday"] = canonical_payload(felder)["birthday"]
            continue
        if name in LIST_FIELDS:
            schluessel, _ = LIST_FIELDS[name]
            if wert is None or (isinstance(wert, list) and not wert):
                # Ausdrückliches Leeren — nicht dasselbe wie Weglassen.
                out[schluessel] = []
                continue
            felder = parse_create_fields({name: wert})
            out[schluessel] = canonical_payload(felder)[schluessel]
            continue
        raise InvalidCommand(f"Feld ist in v1 nicht schreibbar: {name}")
    if not out:
        raise InvalidCommand("Ein Patch ohne Feld waere eine Mutation ohne Wirkung")
    return dict(sorted(out.items()))
