"""Produktiver Bridge-Vertrag und DTOs (Plan §9.1, §5.1).

Kontaktfrei: kein Prozess, kein Store, keine Berechtigung.
"""

from __future__ import annotations

import json

import pytest

from personaljarvis.contacts.bridge import protocol
from personaljarvis.contacts.bridge.models import (
    AuthorizationStatus,
    BridgeCapabilities,
    BridgeContact,
    ChangeEventType,
    ChangesResult,
    ChangeEvent,
    EnumerationResult,
    FieldAvailability,
    FieldState,
    Handshake,
)


# ── Hülle und Versionierung ─────────────────────────────────────────────────
def test_anfrage_ist_deterministisch_serialisiert():
    a = protocol.encode_request(7, protocol.Operation.PING, {"b": 1, "a": 2})
    b = protocol.encode_request(7, protocol.Operation.PING, {"a": 2, "b": 1})
    assert a == b, "gleiche Anfrage muss byte-identisch serialisieren"
    assert json.loads(a)["protocolVersion"] == protocol.PROTOCOL_VERSION


def test_huelle_traegt_die_pflichtfelder():
    envelope = json.loads(protocol.encode_request(1, protocol.Operation.CAPS))
    assert set(envelope) == {"protocolVersion", "requestId", "operation", "payload"}


def test_ungueltige_antwortzeile_wirft():
    with pytest.raises(ValueError):
        protocol.decode_line("[1,2,3]")
    with pytest.raises(json.JSONDecodeError):
        protocol.decode_line("kein json")


def test_operationsmengen_sind_disjunkt_und_vollstaendig():
    assert protocol.CONTACT_FREE_OPERATIONS.isdisjoint(protocol.READ_OPERATIONS)
    assert protocol.CONTACT_FREE_OPERATIONS.isdisjoint(protocol.MUTATING_OPERATIONS)
    assert protocol.READ_OPERATIONS.isdisjoint(protocol.MUTATING_OPERATIONS)


def test_spike_operationen_sind_nicht_im_vertrag():
    """`token`, `updateViaUnified` und die Proben sind bewusst entfallen."""
    alle = (protocol.CONTACT_FREE_OPERATIONS | protocol.READ_OPERATIONS
            | protocol.MUTATING_OPERATIONS)
    for entfallen in ("token", "updateViaUnified", "enumerateProbe", "isolationSummary"):
        assert entfallen not in alle


def test_unified_ist_ausschliesslich_lesend_benannt():
    assert protocol.Operation.GET_UNIFIED_READ_ONLY == "getUnifiedReadOnly"


# ── Feldverfügbarkeit: „nicht lesbar" ist nicht „leer" ──────────────────────
def test_notiz_unavailable_ist_nicht_leer():
    fa = FieldAvailability.parse({"note": "unavailable_by_capability",
                                  "givenName": "present"})
    assert fa.state_of("note") is FieldState.UNAVAILABLE_BY_CAPABILITY
    assert fa.is_unavailable("note")
    assert not fa.is_writable("note"), "ein nicht lesbares Feld darf nie geschrieben werden"
    assert fa.is_writable("givenName")


def test_unbekanntes_feld_gilt_als_nicht_verfuegbar_nicht_als_leer():
    fa = FieldAvailability.parse({})
    assert fa.state_of("note") is FieldState.UNAVAILABLE_BY_CAPABILITY
    assert not fa.is_writable("note")


def test_unbekannter_zustand_wird_konservativ_gewertet():
    fa = FieldAvailability.parse({"note": "voellig-neuer-zustand"})
    assert fa.state_of("note") is FieldState.UNAVAILABLE_BY_CAPABILITY


def test_absent_ist_von_unavailable_unterschieden():
    fa = FieldAvailability.parse({"nickname": "absent"})
    assert fa.state_of("nickname") is FieldState.ABSENT
    assert fa.is_writable("nickname"), "leer ist beschreibbar, nicht-lesbar nicht"


# ── DTOs ────────────────────────────────────────────────────────────────────
def _contact_raw(**over):
    base = {
        "providerIdentifier": "PID-1",
        "keySetVersion": 1,
        "contactType": "person",
        "isMeCard": False,
        "fieldAvailability": {"note": "unavailable_by_capability",
                              "givenName": "present"},
        "fieldCompleteness": "full",
        "givenName": "A", "familyName": "B",
    }
    base.update(over)
    return base


def test_vollstaendiges_dto():
    c = BridgeContact.parse(_contact_raw())
    assert not c.is_partial
    assert c.provider_identifier == "PID-1"
    assert not c.notes_readable


def test_partielles_dto_ist_gekennzeichnet():
    c = BridgeContact.parse(_contact_raw(fieldCompleteness="partial"))
    assert c.is_partial


def test_me_card_status():
    assert BridgeContact.parse(_contact_raw(isMeCard=True)).is_me_card
    assert not BridgeContact.parse(_contact_raw()).is_me_card


def test_unified_identifier_nur_lesend_transportiert():
    c = BridgeContact.parse(_contact_raw(unifiedIdentifier="UNI-9"))
    assert c.unified_identifier == "UNI-9"
    assert c.provider_identifier == "PID-1", "Schreibziel bleibt der Rohdatensatz"


def test_capabilities_default_ist_konservativ():
    caps = BridgeCapabilities.parse({})
    assert caps.notes_supported is False
    assert caps.link_unlink_supported is False
    assert caps.mutations_implemented is False
    assert caps.unified_read_only is True


def test_handshake_parst_vertrag():
    hs = Handshake.parse({
        "protocolVersion": 1, "bundleIdentifier": "x", "transactionAuthor": "x",
        "keySetVersion": 1, "authorizationStatus": "notDetermined",
        "operations": ["ping"], "capabilities": {"notesSupported": False},
    })
    assert hs.authorization_status is AuthorizationStatus.NOT_DETERMINED
    assert hs.capabilities.notes_supported is False


# ── Enumeration und Delta ───────────────────────────────────────────────────
def test_unvollstaendige_enumeration_ist_keine_loeschbasis():
    result = EnumerationResult(contacts=(), count=5, complete=False, key_set_version=1)
    assert not result.usable_as_delete_basis


def test_vollstaendige_enumeration_ist_loeschbasis():
    c = BridgeContact.parse(_contact_raw())
    result = EnumerationResult(contacts=(c,), count=1, complete=True, key_set_version=1)
    assert result.usable_as_delete_basis


def test_zahlabweichung_entwertet_die_loeschbasis():
    result = EnumerationResult(contacts=(), count=3, complete=True, key_set_version=1)
    assert not result.usable_as_delete_basis


def test_drop_everything_verlangt_voll_diff():
    r = ChangesResult(events=(ChangeEvent(type=ChangeEventType.DROP_EVERYTHING),),
                      current_token="T", key_set_version=1)
    assert r.requires_full_diff


def test_normales_delta_verlangt_keinen_voll_diff():
    r = ChangesResult(events=(ChangeEvent(type=ChangeEventType.UPDATE,
                                          provider_identifier="P"),),
                      current_token="T", key_set_version=1)
    assert not r.requires_full_diff


def test_unbekannter_ereignistyp_wird_other():
    assert ChangeEventType.parse("voellig-neu") is ChangeEventType.OTHER
