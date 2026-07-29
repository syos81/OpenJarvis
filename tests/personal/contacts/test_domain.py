"""Domänentypen, Capabilities und Egress-Labels. Kontaktfrei."""

from __future__ import annotations

import dataclasses

import pytest

from personaljarvis.contacts.domain import (
    NOTE_FIELD,
    Contact,
    ContactCapabilitySet,
    ContactFieldAvailability,
    ContactMutation,
    ContactRelation,
    ContactRole,
    ContactType,
    EmailAddress,
    ExternalIdentifier,
    FieldAvailabilityState,
    InitiationContext,
    MutationState,
    SensitivityLabel,
    default_capabilities,
    label_for,
)
from personaljarvis.errors import CapabilityError, IntegrityError

from .conftest import make_contact, new_id


# ── Gültige und ungültige Kontakte ───────────────────────────────────────────
def test_gueltiger_kontakt():
    c = make_contact()
    assert c.contact_type is ContactType.PERSON
    assert c.local_revision == 1
    assert c.is_tombstone is False


def test_ungueltige_id_wird_abgelehnt():
    with pytest.raises(IntegrityError, match="UUID"):
        make_contact(id="keine-uuid")


def test_leerer_anzeigename_wird_abgelehnt():
    with pytest.raises(IntegrityError, match="display_name"):
        make_contact(display_name="  ")


def test_geburtstag_braucht_monat_und_tag_gemeinsam():
    with pytest.raises(IntegrityError, match="Monat und Tag"):
        make_contact(birthday_month=5, birthday_day=None)


def test_geburtstag_ohne_jahr_ist_gueltig():
    c = make_contact(birthday_year=None, birthday_month=5, birthday_day=17)
    assert c.birthday_year is None and c.birthday_month == 5


def test_ungueltiger_monat_wird_abgelehnt():
    with pytest.raises(IntegrityError, match="Geburtsmonat"):
        make_contact(birthday_month=13, birthday_day=1)


def test_tombstone_braucht_datum():
    with pytest.raises(IntegrityError, match="deleted_at"):
        make_contact(is_tombstone=True)


def test_domaentypen_sind_unveraenderlich():
    c = make_contact()
    with pytest.raises(dataclasses.FrozenInstanceError):
        c.display_name = "anders"


def test_listen_eingaben_werden_zu_tupeln(  # Audit-Befund: scheinbare Unveränderlichkeit
):
    """frozen=True schützt nur die Feldbindung — Listen-Eingaben müssen kopiert
    werden, sonst bleibt der Inhalt mutierbar und das Objekt unhashbar."""
    rolle = ContactRole(workspace_id="ws-test", role="Privat")
    verf = ContactFieldAvailability(
        field_name=NOTE_FIELD,
        state=FieldAvailabilityState.UNAVAILABLE_BY_CAPABILITY)
    ext = ExternalIdentifier(
        id=new_id(), provider_account_id="acc", container_identifier="c1",
        provider_identifier="raw-1", key_set_version="v1")
    c = make_contact(roles=[rolle], field_availability=[verf], external_ids=[ext])
    assert isinstance(c.roles, tuple)
    assert isinstance(c.field_availability, tuple)
    assert isinstance(c.external_ids, tuple)
    with pytest.raises(AttributeError):
        c.roles.append(rolle)  # type: ignore[attr-defined]
    hash(c)  # hashbar, weil vollständig aus Tupeln


def test_capability_set_koerziert_listen():
    caps = ContactCapabilitySet(unavailable_fields=["note"])
    assert isinstance(caps.unavailable_fields, tuple)
    hash(caps)


# ── Deterministische Reihenfolge ─────────────────────────────────────────────
def test_reihenfolge_kommt_aus_position_nicht_aus_der_eingabe():
    zweite = EmailAddress(id=new_id(), position=1, value_raw="b@example.invalid",
                          value_normalized="b@example.invalid")
    erste = EmailAddress(id=new_id(), position=0, value_raw="a@example.invalid",
                         value_normalized="a@example.invalid")
    c = make_contact(emails=(zweite, erste))
    assert [e.position for e in c.emails] == [0, 1]
    assert c.emails[0].value_raw == "a@example.invalid"


def test_doppelte_position_wird_abgelehnt():
    a = EmailAddress(id=new_id(), position=0, value_raw="a@example.invalid",
                     value_normalized="a@example.invalid")
    b = EmailAddress(id=new_id(), position=0, value_raw="b@example.invalid",
                     value_normalized="b@example.invalid")
    with pytest.raises(IntegrityError, match="nicht eindeutig"):
        make_contact(emails=(a, b))


def test_negative_position_wird_abgelehnt():
    with pytest.raises(IntegrityError, match="position"):
        EmailAddress(id=new_id(), position=-1, value_raw="a@example.invalid",
                     value_normalized="a@example.invalid")


# ── Rohlabel bleibt erhalten ─────────────────────────────────────────────────
def test_rohlabel_und_normalisiertes_label_stehen_nebeneinander():
    c = make_contact()
    mail = c.emails[0]
    assert mail.label_raw == "_$!<Work>!$_"
    assert mail.label_normalized == "work"


def test_egress_label_ist_getrennt_vom_rohlabel():
    assert label_for("emails") is SensitivityLabel.S2
    assert label_for("contact_type") is SensitivityLabel.S0


def test_unbekanntes_feld_gilt_fail_closed_als_s2():
    assert label_for("noch-nie-gesehen") is SensitivityLabel.S2


# ── Feldverfügbarkeit ────────────────────────────────────────────────────────
def test_unavailable_ist_nicht_absent():
    unavailable = ContactFieldAvailability(
        field_name=NOTE_FIELD,
        state=FieldAvailabilityState.UNAVAILABLE_BY_CAPABILITY)
    absent = ContactFieldAvailability(
        field_name="nickname", state=FieldAvailabilityState.ABSENT)
    assert unavailable.state is not absent.state
    assert unavailable.is_unavailable is True
    assert unavailable.is_known_empty is False
    assert absent.is_known_empty is True
    assert absent.is_unavailable is False


def test_notiz_gilt_nie_als_leer():
    c = make_contact()
    assert c.availability_of(NOTE_FIELD) is (
        FieldAvailabilityState.UNAVAILABLE_BY_CAPABILITY)
    assert c.is_field_known_empty(NOTE_FIELD) is False
    assert c.is_field_readable(NOTE_FIELD) is False


def test_kontakt_hat_kein_notizfeld():
    felder = {f.name for f in dataclasses.fields(Contact)}
    assert "note" not in felder and "notes" not in felder


# ── Capabilities ─────────────────────────────────────────────────────────────
def test_grundzustand_sagt_notizen_nicht_zu():
    caps = default_capabilities()
    assert caps.notes_supported is False
    assert NOTE_FIELD in caps.unavailable_fields


def test_notizen_lassen_sich_nicht_einschalten():
    with pytest.raises(CapabilityError, match="Entitlement"):
        ContactCapabilitySet(notes_supported=True)


def test_link_unlink_laesst_sich_nicht_zusagen():
    with pytest.raises(CapabilityError, match="Verknüpfen"):
        ContactCapabilitySet(unified_link_supported=True)


def test_me_card_ist_nicht_schreibbar_konfigurierbar():
    with pytest.raises(CapabilityError, match="schreibgeschützt"):
        ContactCapabilitySet(me_card_writable=True)


def test_note_muss_als_nicht_verfuegbar_gefuehrt_werden():
    with pytest.raises(CapabilityError, match="nicht verfügbar"):
        ContactCapabilitySet(unavailable_fields=())


def test_capability_verweigert_nicht_deklarierte_operation():
    caps = default_capabilities()
    caps.require("read")
    for op in ("create", "update", "delete", "change_history", "unified_read"):
        with pytest.raises(CapabilityError, match="nicht deklariert"):
            caps.require(op)


def test_capability_kennt_keine_unbekannte_operation():
    with pytest.raises(CapabilityError, match="Unbekannte Operation"):
        default_capabilities().require("zaubern")


def test_verfuegbarkeit_aus_capability_abgeleitet():
    caps = default_capabilities()
    assert caps.availability_for(NOTE_FIELD) is (
        FieldAvailabilityState.UNAVAILABLE_BY_CAPABILITY)
    assert caps.availability_for("given_name") is None


# ── Me-Karte ─────────────────────────────────────────────────────────────────
def test_me_card_ist_nicht_mutierbar():
    me = make_contact(is_me_card=True)
    with pytest.raises(IntegrityError, match="schreibgeschützt"):
        me.with_changes(nickname="neu")


def test_me_card_darf_lokale_rollen_bekommen():
    me = make_contact(is_me_card=True)
    mit_rolle = me.with_roles((ContactRole(workspace_id="ws-test", role="Privat"),))
    assert mit_rolle.roles[0].role == "Privat"
    assert mit_rolle.local_revision == me.local_revision


def test_normaler_kontakt_ist_kontrolliert_aenderbar():
    c = make_contact()
    neu = c.with_changes(nickname="Fixi")
    assert neu.nickname == "Fixi"
    assert neu.local_revision == c.local_revision + 1
    assert c.nickname is None  # Original unberührt


def test_id_und_revision_sind_nicht_direkt_setzbar():
    c = make_contact()
    for feld in ("id", "local_revision"):
        with pytest.raises(IntegrityError, match="nicht änderbar"):
            c.with_changes(**{feld: 99 if feld == "local_revision" else new_id()})


# ── Unified Identifier ───────────────────────────────────────────────────────
def test_unified_identifier_ist_nie_schreibziel():
    ident = ExternalIdentifier(
        id=new_id(), provider_account_id="acc", container_identifier="c1",
        provider_identifier="raw-1", unified_identifier="unified-9",
        key_set_version="v1")
    assert ident.unified_identifier == "unified-9"
    assert ident.write_target == "raw-1"


def test_externe_identitaet_verlangt_pflichtfelder():
    with pytest.raises(IntegrityError, match="provider_identifier"):
        ExternalIdentifier(id=new_id(), provider_account_id="acc",
                           container_identifier="c1", provider_identifier="",
                           key_set_version="v1")


# ── Beziehungen ──────────────────────────────────────────────────────────────
def test_beziehung_ohne_ziel_braucht_rohnamen():
    with pytest.raises(IntegrityError, match="Ziel oder einen Rohnamen"):
        ContactRelation(id=new_id(), position=0, relation_type="spouse")


def test_beziehung_mit_rohnamen_bleibt_erhalten():
    r = ContactRelation(id=new_id(), position=0, relation_type="spouse",
                        target_name_raw="unaufgeloest")
    assert r.to_contact_id is None
    assert r.target_name_raw == "unaufgeloest"


# ── Mutationen ───────────────────────────────────────────────────────────────
def test_mutation_ohne_ziel_wird_abgelehnt():
    with pytest.raises(IntegrityError, match="ausdrückliches Ziel"):
        ContactMutation(mutation_id=new_id(), command="update",
                        idempotency_key="k", state=MutationState.PREPARED,
                        initiation_context=InitiationContext.USER_DIRECT)


def test_mutation_ohne_idempotenzschluessel_wird_abgelehnt():
    with pytest.raises(IntegrityError, match="idempotency_key"):
        ContactMutation(mutation_id=new_id(), command="update",
                        idempotency_key="", state=MutationState.PREPARED,
                        initiation_context=InitiationContext.USER_DIRECT,
                        target_provider_identifier="raw-1")


def _mutation(state: MutationState) -> ContactMutation:
    return ContactMutation(
        mutation_id=new_id(), command="update", idempotency_key="k",
        state=state, initiation_context=InitiationContext.USER_DIRECT,
        target_provider_identifier="raw-1")


def test_outcome_unknown_gilt_nicht_als_abgeschlossen():
    m = _mutation(MutationState.OUTCOME_UNKNOWN)
    assert m.is_settled is False
    assert m.requires_reconcile is True


def test_outcome_unknown_erlaubt_keinen_automatischen_retry():
    for state in (MutationState.OUTCOME_UNKNOWN, MutationState.RECONCILE_REQUIRED):
        assert _mutation(state).may_retry_automatically is False


def test_kein_zustand_erlaubt_automatischen_retry():
    """Es gibt keinen automatischen Mutationsretry — in keinem Zustand.

    Auch `failed_before_send` ist terminal (Gate-C-Audit): ein neuer Versuch
    ist eine neue freigabepflichtige Mutation.
    """
    for state in MutationState:
        assert _mutation(state).may_retry_automatically is False, state


def test_failed_before_send_ist_abgeschlossen():
    m = _mutation(MutationState.FAILED_BEFORE_SEND)
    assert m.is_settled is True


def test_endgueltiger_fehlschlag_ist_abgeschlossen_und_nicht_wiederholbar():
    """`failed` entsteht erst nach dem Abgleich — es ist ein Endzustand."""
    m = _mutation(MutationState.FAILED)
    assert m.is_settled is True
    assert m.may_retry_automatically is False


def test_alle_geforderten_mutationszustaende_existieren():
    for name in ("OUTCOME_UNKNOWN", "RECONCILE_REQUIRED", "MANUAL_DECISION_REQUIRED"):
        assert hasattr(MutationState, name)
