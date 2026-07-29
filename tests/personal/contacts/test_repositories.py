"""Repository-Verträge und SQLite-Implementierungen. Kontaktfrei.

„Roundtrip" heißt hier ausschließlich **lokale kanonische Persistenz** — es
wird kein Apple-Kontakt gelesen, geschrieben oder gelöscht.
"""

from __future__ import annotations

import pytest

from personaljarvis.base.db.unit_of_work import UnitOfWork
from personaljarvis.contacts.domain import (
    NOTE_FIELD,
    ContactDate,
    ContactFieldAvailability,
    ContactMutation,
    ContactRelation,
    ContactRole,
    ContactSyncState,
    ContactTombstone,
    ContactType,
    EmailAddress,
    ExternalIdentifier,
    FieldAvailabilityState,
    InitiationContext,
    InstantMessageAddress,
    MutationOutcome,
    MutationState,
    Organization,
    OrganizationMembership,
    PhoneNumber,
    PostalAddress,
    SocialProfile,
    UrlAddress,
)
from personaljarvis.contacts.repositories import contracts
from personaljarvis.contacts.repositories.sqlite import (
    SqliteContactRepository,
    SqliteContactRoleRepository,
    SqliteExternalIdentifierRepository,
    SqliteFieldAvailabilityRepository,
    SqliteMutationRepository,
    SqliteOrganizationRepository,
    SqliteSyncStateRepository,
    SqliteTombstoneRepository,
)
from personaljarvis.errors import IntegrityError

from .conftest import WORKSPACE, make_contact, new_id


# ── Vertragstreue ────────────────────────────────────────────────────────────
def test_implementierungen_erfuellen_die_vertraege(uow):
    paare = [
        (SqliteContactRepository, contracts.ContactRepository),
        (SqliteContactRoleRepository, contracts.ContactRoleRepository),
        (SqliteExternalIdentifierRepository, contracts.ExternalIdentifierRepository),
        (SqliteFieldAvailabilityRepository, contracts.FieldAvailabilityRepository),
        (SqliteSyncStateRepository, contracts.SyncStateRepository),
        (SqliteTombstoneRepository, contracts.TombstoneRepository),
        (SqliteMutationRepository, contracts.MutationRepository),
        (SqliteOrganizationRepository, contracts.OrganizationRepository),
    ]
    for impl, vertrag in paare:
        assert isinstance(impl(uow), vertrag), impl.__name__


def test_repository_oeffnet_keine_eigene_verbindung(uow):
    repo = SqliteContactRepository(uow)
    assert repo._conn is uow.connection


# ── Vollständiger lokaler Roundtrip ──────────────────────────────────────────
def _voller_kontakt():
    cid = new_id()
    return make_contact(
        id=cid,
        nickname="Fixi",
        organization_name="Beispiel GmbH",
        department_name="Technik",
        job_title="Entwicklung",
        birthday_year=1990, birthday_month=5, birthday_day=17,
        image_available=True,
        thumbnail_blob_ref="blob://sha256/abc",
        postal_addresses=(PostalAddress(
            id=new_id(), position=0, label_raw="_$!<Home>!$_",
            label_normalized="home", street="Beispielweg 1", city="Berlin",
            postal_code="10000", country="Deutschland", iso_country_code="DE"),),
        dates=(ContactDate(id=new_id(), position=0, kind="anniversary",
                           year=2020, month=6, day=1),),
        urls=(UrlAddress(id=new_id(), position=0,
                         value_raw="https://example.invalid",
                         value_normalized="https://example.invalid"),),
        social_profiles=(SocialProfile(id=new_id(), position=0,
                                       service="Mastodon", username="fixi"),),
        instant_messages=(InstantMessageAddress(id=new_id(), position=0,
                                                service="XMPP", username="fixi"),),
        roles=(ContactRole(workspace_id=WORKSPACE, role="Arbeit"),),
    )


def test_vollstaendiger_roundtrip(uow):
    repo = SqliteContactRepository(uow)
    rollen = SqliteContactRoleRepository(uow)
    verfuegbar = SqliteFieldAvailabilityRepository(uow)

    original = _voller_kontakt()
    repo.add(original)
    rollen.set_roles(original.id, original.roles)
    verfuegbar.set_for_contact(original.id, original.field_availability)

    geladen = repo.get(original.id)
    assert geladen is not None
    assert geladen.display_name == original.display_name
    assert geladen.nickname == "Fixi"
    assert geladen.birthday_month == 5 and geladen.birthday_day == 17
    assert geladen.thumbnail_blob_ref == "blob://sha256/abc"
    assert [e.value_raw for e in geladen.emails] == ["eins@example.invalid"]
    assert geladen.phones[0].value_normalized_e164 == "+4930000000"
    assert geladen.postal_addresses[0].city == "Berlin"
    assert geladen.dates[0].kind == "anniversary"
    assert geladen.urls[0].value_raw == "https://example.invalid"
    assert geladen.social_profiles[0].service == "Mastodon"
    assert geladen.instant_messages[0].username == "fixi"
    assert [r.role for r in geladen.roles] == ["Arbeit"]
    assert geladen.availability_of(NOTE_FIELD) is (
        FieldAvailabilityState.UNAVAILABLE_BY_CAPABILITY)


def test_rueckgabe_ist_domaenenobjekt_kein_sqlite_row(uow):
    repo = SqliteContactRepository(uow)
    c = make_contact()
    repo.add(c)
    geladen = repo.get(c.id)
    assert type(geladen).__name__ == "Contact"
    assert geladen.contact_type is ContactType.PERSON


def test_unbekannter_kontakt_liefert_none(uow):
    assert SqliteContactRepository(uow).get(new_id()) is None


def test_update_ersetzt_kinddatensaetze(uow):
    repo = SqliteContactRepository(uow)
    c = make_contact()
    repo.add(c)
    neu = c.with_changes(emails=(EmailAddress(
        id=new_id(), position=0, value_raw="zwei@example.invalid",
        value_normalized="zwei@example.invalid"),))
    repo.update(neu)
    geladen = repo.get(c.id)
    assert [e.value_raw for e in geladen.emails] == ["zwei@example.invalid"]
    assert geladen.local_revision == 2


def test_update_unbekannter_kontakt_scheitert(uow):
    with pytest.raises(IntegrityError, match="existiert nicht"):
        SqliteContactRepository(uow).update(make_contact())


def test_soft_delete_setzt_tombstone(uow):
    repo = SqliteContactRepository(uow)
    c = make_contact()
    repo.add(c)
    repo.soft_delete(c.id, "2026-07-28T00:00:00+00:00")
    geladen = repo.get(c.id)
    assert geladen.is_tombstone is True
    assert geladen.deleted_at == "2026-07-28T00:00:00+00:00"


def test_liste_blendet_tombstones_standardmaessig_aus(uow):
    repo = SqliteContactRepository(uow)
    a, b = make_contact(display_name="A"), make_contact(display_name="B")
    repo.add(a); repo.add(b)
    repo.soft_delete(b.id, "2026-07-28T00:00:00+00:00")
    assert [c.display_name for c in repo.list_by_workspace(WORKSPACE)] == ["A"]
    assert len(repo.list_by_workspace(WORKSPACE, include_tombstones=True)) == 2


def test_liste_ist_deterministisch_sortiert(uow):
    repo = SqliteContactRepository(uow)
    for name in ("Zeta", "Alpha", "Mitte"):
        repo.add(make_contact(display_name=name))
    assert [c.display_name for c in repo.list_by_workspace(WORKSPACE)] == [
        "Alpha", "Mitte", "Zeta"]


def test_suche_findet_teilzeichenkette(uow):
    repo = SqliteContactRepository(uow)
    repo.add(make_contact(display_name="Alpha Beta"))
    repo.add(make_contact(display_name="Gamma"))
    treffer = repo.search_by_display_name(WORKSPACE, "lpha")
    assert [c.display_name for c in treffer] == ["Alpha Beta"]


def test_suche_behandelt_jokerzeichen_als_text(uow):
    repo = SqliteContactRepository(uow)
    repo.add(make_contact(display_name="Alpha"))
    assert repo.search_by_display_name(WORKSPACE, "%") == ()


# ── Constraints werden der Datenbank überlassen ──────────────────────────────
def test_gleicher_email_wert_unter_zwei_labels_ist_speicherbar(uow):
    """Apple erlaubt denselben Wert unter mehreren Labels auf einer Karte —
    ein gültiger Provider-Zustand muss speicherbar sein (Audit-Befund 2,
    Migration 0003)."""
    repo = SqliteContactRepository(uow)
    a = EmailAddress(id=new_id(), position=0, label_normalized="home",
                     value_raw="gleich@example.invalid",
                     value_normalized="gleich@example.invalid")
    b = EmailAddress(id=new_id(), position=1, label_normalized="work",
                     value_raw="gleich@example.invalid",
                     value_normalized="gleich@example.invalid")
    c = make_contact(emails=(a, b))
    repo.add(c)
    geladen = repo.get(c.id)
    assert [e.label_normalized for e in geladen.emails] == ["home", "work"]
    assert {e.value_normalized for e in geladen.emails} == {"gleich@example.invalid"}


def test_doppelte_position_wird_von_der_datenbank_abgelehnt(uow):
    """Der Doppel-Einfügungs-Schutz bleibt: (contact_id, position) ist unique.

    Die Domäne verhindert das bereits bei der Konstruktion; hier wird die
    Datenbankschicht direkt geprüft, damit der Constraint selbst belegt ist.
    """
    import sqlite3

    repo = SqliteContactRepository(uow)
    c = make_contact()
    repo.add(c)
    with pytest.raises(sqlite3.IntegrityError):
        uow.execute(
            "INSERT INTO contact_emails (id, contact_id, position, value_raw, "
            "value_normalized) VALUES (?,?,?,?,?)",
            (new_id(), c.id, 0, "b@example.invalid", "b@example.invalid"),
        )


def test_doppelte_kontakt_id_wird_abgelehnt(uow):
    repo = SqliteContactRepository(uow)
    c = make_contact()
    repo.add(c)
    with pytest.raises(IntegrityError):
        repo.add(c)


# ── Rollen ───────────────────────────────────────────────────────────────────
def test_rollen_roundtrip_und_kategorienfilter(uow):
    repo = SqliteContactRepository(uow)
    rollen = SqliteContactRoleRepository(uow)
    a, b = make_contact(display_name="A"), make_contact(display_name="B")
    repo.add(a); repo.add(b)
    rollen.set_roles(a.id, (ContactRole(workspace_id=WORKSPACE, role="Mieter"),
                            ContactRole(workspace_id=WORKSPACE, role="Privat")))
    rollen.set_roles(b.id, (ContactRole(workspace_id=WORKSPACE, role="Vermieter"),))
    assert [r.role for r in rollen.list_for_contact(a.id)] == ["Mieter", "Privat"]
    assert rollen.list_contact_ids_by_role(WORKSPACE, "Vermieter") == (b.id,)


def test_alle_geforderten_kategorien_sind_speicherbar(uow):
    repo = SqliteContactRepository(uow)
    rollen = SqliteContactRoleRepository(uow)
    c = make_contact()
    repo.add(c)
    kategorien = ("Privat", "Arbeit", "HV", "Mieter", "Vermieter")
    rollen.set_roles(c.id, tuple(
        ContactRole(workspace_id=WORKSPACE, role=k) for k in kategorien))
    assert {r.role for r in rollen.list_for_contact(c.id)} == set(kategorien)


# ── Externe Identitäten ──────────────────────────────────────────────────────
def test_externe_identitaet_roundtrip_und_upsert(uow):
    repo = SqliteContactRepository(uow)
    ext = SqliteExternalIdentifierRepository(uow)
    c = make_contact()
    repo.add(c)
    ident = ExternalIdentifier(
        id=new_id(), provider_account_id="apple-system",
        container_identifier="_local:ABAccount", provider_identifier="raw-1",
        unified_identifier="unified-9", key_set_version="v1")
    ext.upsert(c.id, ident)
    assert ext.find_contact_id("apple-system", "raw-1") == c.id
    geladen = ext.list_for_contact(c.id)[0]
    assert geladen.unified_identifier == "unified-9"
    assert geladen.write_target == "raw-1"
    # Zweiter Upsert derselben Provider-Identität aktualisiert statt zu doppeln.
    ext.upsert(c.id, ExternalIdentifier(
        id=new_id(), provider_account_id="apple-system",
        container_identifier="_local:ABAccount", provider_identifier="raw-1",
        key_set_version="v2"))
    alle = ext.list_for_contact(c.id)
    assert len(alle) == 1 and alle[0].key_set_version == "v2"


# ── Feldverfügbarkeit ────────────────────────────────────────────────────────
def test_feldverfuegbarkeit_unterscheidet_leer_von_nicht_lesbar(uow):
    repo = SqliteContactRepository(uow)
    verf = SqliteFieldAvailabilityRepository(uow)
    c = make_contact()
    repo.add(c)
    verf.set_for_contact(c.id, (
        ContactFieldAvailability(field_name=NOTE_FIELD,
                                 state=FieldAvailabilityState.UNAVAILABLE_BY_CAPABILITY),
        ContactFieldAvailability(field_name="nickname",
                                 state=FieldAvailabilityState.ABSENT),
    ))
    zustaende = {e.field_name: e.state for e in verf.list_for_contact(c.id)}
    assert zustaende[NOTE_FIELD] is FieldAvailabilityState.UNAVAILABLE_BY_CAPABILITY
    assert zustaende["nickname"] is FieldAvailabilityState.ABSENT


# ── Sync-Zustand ─────────────────────────────────────────────────────────────
def test_sync_state_roundtrip_und_upsert(uow):
    repo = SqliteSyncStateRepository(uow)
    zustand = ContactSyncState(
        provider_account_id="apple-system", container_identifier="c1",
        key_set_version="v1", mode="delta", cursor_token="dG9rZW4=")
    repo.upsert(zustand)
    geladen = repo.get("apple-system", "c1")
    assert geladen.cursor_token == "dG9rZW4="
    assert geladen.mode == "delta"
    repo.upsert(ContactSyncState(
        provider_account_id="apple-system", container_identifier="c1",
        key_set_version="v1", mode="full_diff_required"))
    assert repo.get("apple-system", "c1").mode == "full_diff_required"
    assert len(repo.list_all()) == 1


def test_unbekannter_sync_modus_wird_abgelehnt(uow):
    with pytest.raises(IntegrityError):
        SqliteSyncStateRepository(uow).upsert(ContactSyncState(
            provider_account_id="a", container_identifier="c",
            key_set_version="v1", mode="irgendwie"))


# ── Tombstones ───────────────────────────────────────────────────────────────
def test_tombstone_roundtrip(uow):
    repo = SqliteTombstoneRepository(uow)
    repo.add(ContactTombstone(provider_account_id="apple-system",
                              provider_identifier="raw-9",
                              reason="vom Provider gelöscht"))
    assert repo.exists("apple-system", "raw-9") is True
    assert repo.exists("apple-system", "raw-8") is False
    assert len(repo.list_all()) == 1


def test_doppelter_tombstone_wird_abgelehnt(uow):
    repo = SqliteTombstoneRepository(uow)
    t = ContactTombstone(provider_account_id="a", provider_identifier="r",
                         reason="x")
    repo.add(t)
    with pytest.raises(IntegrityError):
        repo.add(t)


# ── Mutationen ───────────────────────────────────────────────────────────────
def _mutation(**kw) -> ContactMutation:
    defaults = dict(mutation_id=new_id(), command="update",
                    idempotency_key=new_id(), state=MutationState.PREPARED,
                    initiation_context=InitiationContext.USER_DIRECT,
                    target_provider_identifier="raw-1")
    defaults.update(kw)
    return ContactMutation(**defaults)


def test_mutation_roundtrip(uow):
    repo = SqliteMutationRepository(uow)
    m = _mutation()
    repo.add(m)
    geladen = repo.get(m.mutation_id)
    assert geladen.command == "update"
    assert geladen.state is MutationState.PREPARED
    assert geladen.initiation_context is InitiationContext.USER_DIRECT


def test_idempotenzschluessel_ist_eindeutig(uow):
    repo = SqliteMutationRepository(uow)
    key = "derselbe-schluessel"
    repo.add(_mutation(idempotency_key=key))
    with pytest.raises(IntegrityError):
        repo.add(_mutation(idempotency_key=key))


def test_mutation_ueber_idempotenzschluessel_auffindbar(uow):
    repo = SqliteMutationRepository(uow)
    m = _mutation(idempotency_key="k-1")
    repo.add(m)
    assert repo.find_by_idempotency_key("k-1").mutation_id == m.mutation_id
    assert repo.find_by_idempotency_key("k-2") is None


def test_outcome_unknown_erscheint_in_der_reconcile_liste(uow):
    repo = SqliteMutationRepository(uow)
    offen = _mutation(state=MutationState.OUTCOME_UNKNOWN,
                      outcome=MutationOutcome.OUTCOME_UNKNOWN)
    fertig = _mutation(state=MutationState.SUCCEEDED,
                       outcome=MutationOutcome.SUCCEEDED)
    repo.add(offen); repo.add(fertig)
    ids = [m.mutation_id for m in repo.list_requiring_reconcile()]
    assert ids == [offen.mutation_id]


def test_zustandswechsel_wird_gespeichert(uow):
    repo = SqliteMutationRepository(uow)
    m = _mutation(state=MutationState.OUTCOME_UNKNOWN)
    repo.add(m)
    import dataclasses

    reconciled = dataclasses.replace(
        m, state=MutationState.SUCCEEDED, outcome=MutationOutcome.SUCCEEDED,
        completed_at="2026-07-28T00:00:00+00:00")
    repo.update_state(reconciled)
    assert repo.get(m.mutation_id).state is MutationState.SUCCEEDED
    assert repo.list_requiring_reconcile() == ()


# ── Organisationen ───────────────────────────────────────────────────────────
def test_organisation_und_mitgliedschaft(uow):
    repo = SqliteContactRepository(uow)
    orgs = SqliteOrganizationRepository(uow)
    c = make_contact()
    repo.add(c)
    org = Organization(id=new_id(), workspace_id=WORKSPACE, name="Beispiel GmbH")
    orgs.add(org)
    orgs.add_membership(OrganizationMembership(
        organization_id=org.id, contact_id=c.id, role="Geschäftsführung"))
    assert orgs.get(org.id).name == "Beispiel GmbH"
    mitglieder = orgs.list_memberships(org.id)
    assert len(mitglieder) == 1 and mitglieder[0].contact_id == c.id


def test_doppelte_organisation_im_workspace_wird_abgelehnt(uow):
    orgs = SqliteOrganizationRepository(uow)
    orgs.add(Organization(id=new_id(), workspace_id=WORKSPACE, name="Gleich"))
    with pytest.raises(IntegrityError):
        orgs.add(Organization(id=new_id(), workspace_id=WORKSPACE, name="Gleich"))


# ── Transaktionsverhalten ────────────────────────────────────────────────────
def test_rollback_ueber_unit_of_work_verwirft_alles(migrated_factory):
    c = make_contact()
    with pytest.raises(RuntimeError):
        with UnitOfWork(migrated_factory) as uow:
            SqliteContactRepository(uow).add(c)
            raise RuntimeError("Abbruch")
    with UnitOfWork(migrated_factory) as uow:
        assert SqliteContactRepository(uow).get(c.id) is None


def test_repository_committet_nicht_selbst(migrated_factory):
    c = make_contact()
    uow = UnitOfWork(migrated_factory)
    with uow:
        SqliteContactRepository(uow).add(c)
        uow.rollback()
    with UnitOfWork(migrated_factory) as zweite:
        assert SqliteContactRepository(zweite).get(c.id) is None
