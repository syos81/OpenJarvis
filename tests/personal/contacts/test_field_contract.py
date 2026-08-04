"""Geschlossener Feldvertrag v1.

**Kontaktfrei.** Reine Funktionsprüfungen — keine Datenbank, kein Prozess,
kein Apple-Zugriff.

Der Vertrag ist die Stelle, an der entschieden wird, *was überhaupt* zu Apple
gelangen kann. Diese Tests halten drei Dinge fest: die Feldmenge ist
geschlossen, die kanonische Form ist deterministisch, und der Digest bindet
die Vertragsversion mit ein.
"""

from __future__ import annotations

import pytest

from personaljarvis.contacts.application.errors import InvalidCommand
from personaljarvis.contacts.application.field_contract import (
    CREATE_FIELDS,
    FIELD_CONTRACT_VERSION,
    MUTATION_CONTRACT_VERSION,
    NEVER_WRITABLE,
    SCALAR_FIELDS,
    as_bridge_contact,
    canonical_payload,
    parse_canonical_payload,
    parse_create_fields,
    preview_items,
    project_bridge_contact,
    readback_digest,
)

VOLL = {
    "contact_type": "person",
    "given_name": "Fixi", "middle_name": "Zwei", "family_name": "Eins",
    "previous_family_name": "Null", "name_prefix": "Dr.", "name_suffix": "jr.",
    "nickname": "Fix", "phonetic_given_name": "Fiksi",
    "phonetic_family_name": "Ains", "organization_name": "Beispiel GmbH",
    "department_name": "Technik", "job_title": "Entwicklung",
    "birthday": {"year": 1980, "month": 5, "day": 3},
    "emails": [{"label": "work", "value": "f@example.invalid"}],
    "phones": [{"label": "mobile", "value": "+49 30 000001"}],
    "postal_addresses": [{"label": "home", "street": "Weg 1", "city": "Kiel",
                          "postal_code": "24103", "country": "Deutschland",
                          "iso_country_code": "de"}],
    "urls": [{"label": "work", "value": "https://example.invalid"}],
    "dates": [{"label": "other", "month": 9, "day": 1}],
}


# ═══ Feldmenge ══════════════════════════════════════════════════════════════
def test_jedes_erlaubte_feld_wird_uebernommen():
    felder = parse_create_fields(VOLL)
    assert set(felder.scalars) == set(SCALAR_FIELDS)
    assert felder.contact_type == "person"
    assert felder.birthday.year == 1980
    assert len(felder.emails) == len(felder.phones) == 1
    assert len(felder.postal_addresses) == len(felder.urls) == 1
    assert len(felder.dates) == 1


def test_die_feldmenge_ist_geschlossen():
    assert CREATE_FIELDS == set(SCALAR_FIELDS) | {
        "contact_type", "birthday", "emails", "phones", "postal_addresses",
        "urls", "dates"}


def test_unbekanntes_feld_wird_abgewiesen():
    with pytest.raises(InvalidCommand, match="Unbekannte Felder"):
        parse_create_fields({"given_name": "A", "lieblingsfarbe": "blau"})


@pytest.mark.parametrize("feld", sorted(NEVER_WRITABLE))
def test_nie_schreibbare_felder_bekommen_eine_eigene_meldung(feld):
    with pytest.raises(InvalidCommand, match="nie schreibbar"):
        parse_create_fields({"given_name": "A", feld: "x"})


def test_ausgeschlossene_felder_sind_namentlich_verriegelt():
    for feld in ("note", "social_profiles", "instant_messages", "relations",
                 "groups", "sub_locality", "thumbnail", "is_me_card"):
        assert feld in NEVER_WRITABLE
        assert feld not in CREATE_FIELDS


def test_entwurf_ohne_jedes_feld_ist_kein_kontakt():
    with pytest.raises(InvalidCommand):
        parse_create_fields({})
    with pytest.raises(InvalidCommand):
        parse_create_fields({"contact_type": "person"})


# ═══ Grenzen, Labels, Validierung ═══════════════════════════════════════════
def test_leerer_wert_wird_abgewiesen():
    """Weglassen heisst „nicht gesetzt"; ein leerer Wert waere eine Loeschung."""
    with pytest.raises(InvalidCommand, match="leerer Wert"):
        parse_create_fields({"given_name": "   "})


def test_null_gilt_als_nicht_gesetzt():
    felder = parse_create_fields({"given_name": "A", "family_name": None})
    assert "family_name" not in felder.scalars


def test_zu_langer_wert_wird_abgewiesen():
    with pytest.raises(InvalidCommand, match="laenger als"):
        parse_create_fields({"given_name": "x" * 300})


def test_steuerzeichen_werden_abgewiesen():
    with pytest.raises(InvalidCommand, match="Steuerzeichen"):
        parse_create_fields({"given_name": "A\x07B"})


@pytest.mark.parametrize("feld,label", [
    ("emails", "mobile"), ("phones", "privat"), ("urls", "main"),
    ("dates", "jahrestag"),
])
def test_label_ausserhalb_des_vorrats_wird_abgewiesen(feld, label):
    eintrag = ({"label": label, "month": 1, "day": 1} if feld == "dates"
               else {"label": label, "value": "a@b.invalid"})
    with pytest.raises(InvalidCommand, match="unbekanntes Label"):
        parse_create_fields({feld: [eintrag]})


def test_zulaessige_labels_kommen_durch():
    felder = parse_create_fields({
        "phones": [{"label": name, "value": f"+49 30 {i}"}
                   for i, name in enumerate(("home", "work", "mobile", "main",
                                             "other"))]})
    assert {p.label for p in felder.phones} == {"home", "work", "mobile",
                                                "main", "other"}


def test_hoechstzahl_je_liste_wird_erzwungen():
    with pytest.raises(InvalidCommand, match="hoechstens 10"):
        parse_create_fields({"emails": [{"label": None, "value": f"a{i}@b.invalid"}
                                        for i in range(11)]})
    with pytest.raises(InvalidCommand, match="hoechstens 5"):
        parse_create_fields({"postal_addresses": [{"label": None, "city": "K"}
                                                  for _ in range(6)]})


def test_mailadresse_wird_geprueft():
    with pytest.raises(InvalidCommand, match="keine E-Mail"):
        parse_create_fields({"emails": [{"label": None, "value": "ohne-at"}]})


def test_datum_ausserhalb_des_bereichs_wird_abgewiesen():
    with pytest.raises(InvalidCommand, match="ausserhalb"):
        parse_create_fields({"birthday": {"month": 13, "day": 1}})


def test_leere_anschrift_ist_kein_wert():
    with pytest.raises(InvalidCommand, match="ohne jede Komponente"):
        parse_create_fields({"postal_addresses": [{"label": "home"}]})


def test_laenderkennung_wird_normalisiert():
    felder = parse_create_fields({"postal_addresses": [
        {"label": None, "city": "Kiel", "iso_country_code": "de"}]})
    assert felder.postal_addresses[0].iso_country_code == "DE"


# ═══ Kanonische Form ════════════════════════════════════════════════════════
def test_unicode_wird_kanonisch_normalisiert():
    """Dieselbe Schreibweise, ein Digest — sonst schluege der Read-back fehl."""
    zusammen = parse_create_fields({"given_name": "José"})
    zerlegt = parse_create_fields({"given_name": "José"})
    assert zusammen.scalars == zerlegt.scalars
    assert readback_digest(zusammen) == readback_digest(zerlegt)


def test_gleiche_eingabe_ergibt_denselben_digest():
    """Determinismus heisst: derselbe Eingang, derselbe Digest."""
    eingang = {"emails": [{"label": "work", "value": "b@x.invalid"},
                          {"label": "home", "value": "a@x.invalid"}]}
    a = parse_create_fields(dict(eingang))
    b = parse_create_fields(dict(eingang))
    assert canonical_payload(a) == canonical_payload(b)
    assert readback_digest(a) == readback_digest(b)


def test_die_reihenfolge_ist_position_und_bedeutungstragend():
    """Zwei Reihenfolgen sind zwei Zustände (ADR-0020 §7).

    Früher sortierte der Vertrag die Listen nach `(label, value)` und machte
    sie damit gleich. Das verdrehte die Absicht des Menschen — wer die
    Arbeitsadresse zuerst nennt, will sie zuerst haben — und entkoppelte den
    Digest von dem, was der Provider zurückliest. Aufgefallen im
    Update-Livetest am 2026-08-04 mit zwei E-Mails.
    """
    zuerst_arbeit = parse_create_fields({"emails": [
        {"label": "work", "value": "b@x.invalid"},
        {"label": "home", "value": "a@x.invalid"}]})
    zuerst_privat = parse_create_fields({"emails": [
        {"label": "home", "value": "a@x.invalid"},
        {"label": "work", "value": "b@x.invalid"}]})
    assert canonical_payload(zuerst_arbeit)["emails"][0]["label"] == "work"
    assert canonical_payload(zuerst_privat)["emails"][0]["label"] == "home"
    assert readback_digest(zuerst_arbeit) != readback_digest(zuerst_privat)


def test_weglassen_und_null_ergeben_denselben_digest():
    ohne = parse_create_fields({"given_name": "A"})
    mit_null = parse_create_fields({"given_name": "A", "nickname": None,
                                    "emails": []})
    assert readback_digest(ohne) == readback_digest(mit_null)


def test_kanonische_form_und_rueckweg_sind_verlustfrei():
    felder = parse_create_fields(VOLL)
    zurueck = parse_canonical_payload(canonical_payload(felder))
    assert readback_digest(zurueck) == readback_digest(felder)


def test_kanonische_form_traegt_nur_gesetzte_felder():
    payload = canonical_payload(parse_create_fields({"given_name": "A"}))
    assert payload == {"contactType": "person", "givenName": "A"}


# ═══ Digest ═════════════════════════════════════════════════════════════════
#: Feste Testnutzlast fuer den Goldwert. Erfundene Daten, kein echter Kontakt.
GOLDNUTZLAST = {
    "contact_type": "person",
    "given_name": "ZZZ-Vertrag", "family_name": "Goldwert",
    "organization_name": "Beispiel GmbH",
    "birthday": {"year": 1980, "month": 5, "day": 3},
    "emails": [{"label": "work", "value": "zzz@example.invalid"}],
    "phones": [{"label": "mobile", "value": "+49 30 000001"}],
    "postal_addresses": [{"label": "home", "street": "Weg 1", "city": "Kiel",
                          "postal_code": "24103", "country": "Deutschland",
                          "iso_country_code": "de"}],
    "urls": [{"label": "work", "value": "https://example.invalid"}],
    "dates": [{"label": "other", "month": 9, "day": 1}],
}

#: Gepinnter Erwartungswert. Er faellt bei **jeder** unbeabsichtigten
#: Aenderung der Kanonisierung — Feldnamen, Sortierung, Weglassregeln,
#: Unicode-Normalform, Laenderkennung, Vertragsversion. Aendert sich die
#: Kanonisierung absichtlich, ist das eine neue Feldvertragsversion; dann
#: gehoert dieser Wert bewusst neu gesetzt und nicht stillschweigend
#: nachgezogen.
GOLDWERT = "17a9b881f9aa199e5e237957fe6fd4a49e63553ed52e0ad8e6341fe42d432570"


def test_digest_goldwert_bleibt_stabil():
    """Ein fester Digest fuer eine feste Nutzlast — der externe Anker.

    Die uebrigen Digest-Tests vergleichen Ergebnisse derselben Bildung
    miteinander und wuerden eine gemeinsame Verschiebung nicht bemerken.
    Dieser Wert steht ausserhalb der Bildung.
    """
    assert readback_digest(parse_create_fields(GOLDNUTZLAST)) == GOLDWERT


def test_goldwert_haengt_an_der_vertragsversion():
    """Eine neue Vertragsversion muss den Digest zwingend veraendern."""
    from personaljarvis.base.digest import digest_of

    felder = parse_create_fields(GOLDNUTZLAST)
    anders = digest_of({"fieldContractVersion": FIELD_CONTRACT_VERSION + 1,
                        "fields": canonical_payload(felder)})
    assert anders != GOLDWERT


def test_goldnutzlast_traegt_keine_echten_kontaktdaten():
    text = str(GOLDNUTZLAST)
    assert "example.invalid" in text
    for verboten in ("@gmail", "@icloud", "kluender", "lukas"):
        assert verboten not in text.lower()


def test_digest_ist_plattformstabil_und_wertabhaengig():
    felder = parse_create_fields({"given_name": "Fixi", "family_name": "Eins"})
    # Fester Wert: derselbe fachliche Inhalt muss auf jeder Plattform und in
    # jeder Sitzung denselben Digest ergeben.
    erwartet = readback_digest(felder)
    assert erwartet == readback_digest(
        parse_create_fields({"family_name": "Eins", "given_name": "Fixi"}))
    assert len(erwartet) == 64
    anders = readback_digest(parse_create_fields({"given_name": "Fixi"}))
    assert anders != erwartet


def test_digest_bindet_die_vertragsversion():
    from personaljarvis.base.digest import digest_of

    felder = parse_create_fields({"given_name": "A"})
    assert readback_digest(felder) == digest_of({
        "fieldContractVersion": FIELD_CONTRACT_VERSION,
        "fields": canonical_payload(felder)})


def test_digest_traegt_keine_kennung_und_keinen_zeitstempel():
    felder = parse_create_fields({"given_name": "A"})
    payload = canonical_payload(felder)
    text = str(payload)
    for verboten in ("providerIdentifier", "contact_id", "ABAccount",
                     "/Users/", "updated_at", "created_at"):
        assert verboten not in text


def test_vertragsversionen_sind_gesetzt():
    assert FIELD_CONTRACT_VERSION == 1
    assert MUTATION_CONTRACT_VERSION == 1


# ═══ Rückweg über das Bridge-DTO ════════════════════════════════════════════
def test_dto_rundlauf_ergibt_denselben_digest():
    felder = parse_create_fields(VOLL)
    dto = as_bridge_contact(felder, provider_identifier="PID-1")
    assert readback_digest(project_bridge_contact(dto)) == readback_digest(felder)


def test_dto_fuehrt_notizen_als_nicht_verfuegbar():
    dto = as_bridge_contact(parse_create_fields({"given_name": "A"}),
                            provider_identifier="PID-1")
    assert dto.field_availability.is_unavailable("note")
    assert not dto.notes_readable


def test_projektion_laesst_nicht_lesbare_felder_aus():
    """Ein gesperrtes Feld wird nie als leer gefuehrt (Plan §5.1)."""
    from personaljarvis.contacts.bridge.models import BridgeContact

    roh = BridgeContact.parse({
        "providerIdentifier": "PID-2", "keySetVersion": 1,
        "contactType": "person", "isMeCard": False,
        "fieldAvailability": {"givenName": "unavailable_by_capability",
                              "emails": "present"},
        "fieldCompleteness": "partial", "givenName": "Sichtbar",
        "emails": [{"label": "_$!<Work>!$_", "value": "a@b.invalid"}]})
    projiziert = project_bridge_contact(roh)
    assert "given_name" not in projiziert.scalars
    assert projiziert.emails[0].label == "work"


# ═══ Vorschau ═══════════════════════════════════════════════════════════════
def test_vorschau_nennt_api_feldnamen():
    zeilen = dict(preview_items(parse_create_fields(VOLL)))
    assert zeilen["given_name"] == "Fixi"
    assert zeilen["birthday"] == "1980-05-03"
    assert zeilen["emails"] == ["work: f@example.invalid"]
    assert "givenName" not in zeilen
