"""Migrations-Ledger, Runner und Schema (07 §6, AV-37). Kontaktfrei."""

from __future__ import annotations

import pytest

from personaljarvis.base.db.migrations import ALL_MIGRATIONS, LEDGER_TABLE
from personaljarvis.base.db.migrations.ledger import Migration, read_ledger
from personaljarvis.base.db.migrations.runner import MigrationRunner
from personaljarvis.errors import LedgerError, MigrationError

ERWARTETE_TABELLEN = {
    # Basis (0001)
    "personal_resource_identity", "personal_resource_link",
    "personal_entity_alias", "personal_audit_log",
    # Kontakte (0002)
    "contacts", "contact_field_availability", "contact_external_ids",
    "contact_roles", "contact_emails", "contact_phones",
    "contact_postal_addresses", "contact_dates", "contact_urls",
    "contact_social_profiles", "contact_instant_messages", "contact_relations",
    "organizations", "organization_memberships", "contacts_sync_state",
    "contacts_tombstones", "contacts_mutations",
    # Basis (0004)
    "personal_approvals", "personal_external_action_outbox",
}

ERWARTETE_INDIZES = {
    "ux_resource_link", "ix_resource_link_to", "ix_entity_alias_canonical",
    "ux_audit_sequence", "ix_audit_subject",
    "ix_contacts_workspace", "ix_contacts_display_name", "ix_contacts_updated_at",
    "ix_contacts_sync_state", "ix_field_availability_state",
    "ux_external_provider_identity", "ix_external_contact", "ix_external_container",
    "ix_contact_roles_role", "ux_contact_emails_position",
    "ix_contact_emails_normalized", "ux_contact_phones_position",
    "ix_contact_phones_e164", "ux_contact_postal_position",
    "ux_contact_dates_position", "ux_contact_urls_position",
    "ux_contact_social_position", "ux_contact_im_position",
    "ux_contact_relations_position", "ix_contact_relations_to",
    "ux_organizations_name", "ix_org_membership_contact",
    "ux_mutations_idempotency", "ix_mutations_state", "ix_mutations_target",
    "ix_tombstones_contact",
}


def _tabellen(conn) -> set[str]:
    return {
        r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%'"
        )
    }


def _indizes(conn) -> set[str]:
    return {
        r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' "
            "AND name NOT LIKE 'sqlite_%'"
        )
    }


# ── Lauf auf leerer Datenbank ────────────────────────────────────────────────
def test_leere_datenbank_wird_vollstaendig_migriert(factory):
    report = MigrationRunner(factory, ALL_MIGRATIONS).run()
    assert report.applied == ("0001", "0002", "0003", "0004")
    assert report.schema_version == 4
    conn = factory.connect()
    assert ERWARTETE_TABELLEN <= _tabellen(conn)
    assert LEDGER_TABLE in _tabellen(conn)


def test_alle_erwarteten_indizes_vorhanden(migrated_factory):
    vorhanden = _indizes(migrated_factory.connect())
    fehlend = ERWARTETE_INDIZES - vorhanden
    assert not fehlend, f"fehlende Indizes: {sorted(fehlend)}"


def test_wiederholter_lauf_ist_idempotent(factory):
    runner = MigrationRunner(factory, ALL_MIGRATIONS)
    runner.run()
    zweiter = runner.run()
    assert zweiter.applied == ()
    assert zweiter.already_applied == ("0001", "0002", "0003", "0004")


def test_ledger_speichert_pflichtfelder(migrated_factory):
    conn = migrated_factory.connect()
    row = conn.execute(
        f"SELECT * FROM {LEDGER_TABLE} WHERE migration_id = '0002'"
    ).fetchone()
    assert row["checksum"] and len(row["checksum"]) == 64
    assert row["applied_at"].endswith("+00:00")
    assert row["schema_version"] == 2
    assert row["module_owner"] == "contacts"


def test_ledger_und_schema_sind_konsistent(migrated_factory):
    conn = migrated_factory.connect()
    ledger = read_ledger(conn)
    assert set(ledger) == {"0001", "0002", "0003", "0004"}
    for migration in ALL_MIGRATIONS:
        assert ledger[migration.migration_id].checksum == migration.checksum


# ── Fail-closed-Pfade ────────────────────────────────────────────────────────
def test_pruefsummenabweichung_ist_fail_closed(migrated_factory):
    conn = migrated_factory.connect()
    conn.execute(
        f"UPDATE {LEDGER_TABLE} SET checksum = ? WHERE migration_id = '0002'",
        ("0" * 64,),
    )
    with pytest.raises(LedgerError, match="Prüfsumme"):
        MigrationRunner(migrated_factory, ALL_MIGRATIONS).run()


def test_unbekannte_angewandte_id_ist_fail_closed(migrated_factory):
    conn = migrated_factory.connect()
    conn.execute(
        f"INSERT INTO {LEDGER_TABLE} VALUES ('9999','fremd','aus der Zukunft',"
        "'x','2026-01-01T00:00:00+00:00',99,'unknown')"
    )
    with pytest.raises(LedgerError, match="nicht kennt"):
        MigrationRunner(migrated_factory, ALL_MIGRATIONS).run()


def test_manipulierter_ledger_wird_nicht_still_repariert(migrated_factory):
    conn = migrated_factory.connect()
    conn.execute(f"DELETE FROM {LEDGER_TABLE} WHERE migration_id = '0002'")
    # Ohne Ledger-Eintrag gilt 0002 als offen und wird erneut angewandt —
    # dabei kollidiert das bereits bestehende Schema. Fail-closed statt still.
    with pytest.raises(MigrationError, match="0002"):
        MigrationRunner(migrated_factory, ALL_MIGRATIONS).run()


def test_doppelte_id_wird_abgelehnt(factory):
    doppelt = ALL_MIGRATIONS + (ALL_MIGRATIONS[-1],)
    with pytest.raises(MigrationError, match="Doppelte Migrations-ID"):
        MigrationRunner(factory, doppelt)


def test_falsche_reihenfolge_wird_abgelehnt(factory):
    """Verdrehte Reihenfolge scheitert — hier zuerst an der Abhängigkeit."""
    verdreht = tuple(reversed(ALL_MIGRATIONS))
    with pytest.raises(MigrationError):
        MigrationRunner(factory, verdreht)


def test_nicht_monotone_ids_werden_abgelehnt(factory):
    """Monotonie wird auch ohne Abhängigkeiten erzwungen."""
    zweite = Migration("0002", "base", "b", ("CREATE TABLE b (x INTEGER)",), 2)
    erste = Migration("0001", "base", "a", ("CREATE TABLE a (x INTEGER)",), 1)
    with pytest.raises(MigrationError, match="nicht monoton"):
        MigrationRunner(factory, (zweite, erste))


def test_abhaengigkeit_auf_groessere_id_wird_abgelehnt(factory):
    kaputt = Migration(
        migration_id="0001", module_owner="base", description="kaputt",
        statements=("CREATE TABLE x (a INTEGER)",), schema_version=1,
        depends_on=("0002",),
    )
    with pytest.raises(MigrationError, match="kleiner als die eigene ID"):
        MigrationRunner(factory, (kaputt,))


def test_leere_migration_wird_abgelehnt(factory):
    leer = Migration(
        migration_id="0001", module_owner="base", description="leer",
        statements=(), schema_version=1,
    )
    with pytest.raises(MigrationError, match="keine Anweisung"):
        MigrationRunner(factory, (leer,))


def test_fehler_mitten_in_der_migration_rollt_atomar_zurueck(factory):
    """Belegt die geprüfte SQLite-Eigenschaft: DDL ist transaktional."""
    kaputt = Migration(
        migration_id="0001", module_owner="base", description="bricht ab",
        statements=(
            "CREATE TABLE haelt_nicht (a INTEGER)",
            "CREATE TABLE haelt_nicht (a INTEGER)",  # zweites Mal -> Fehler
        ),
        schema_version=1,
    )
    with pytest.raises(MigrationError, match="zurückgerollt"):
        MigrationRunner(factory, (kaputt,)).run()
    conn = factory.connect()
    assert "haelt_nicht" not in _tabellen(conn)
    assert read_ledger(conn) == {}


def test_ledgereintrag_faellt_mit_der_migration_zurueck(factory):
    kaputt = Migration(
        migration_id="0001", module_owner="base", description="bricht ab",
        statements=("CREATE TABLE a (x INTEGER)", "UNSINN"),
        schema_version=1,
    )
    with pytest.raises(MigrationError):
        MigrationRunner(factory, (kaputt,)).run()
    assert read_ledger(factory.connect()) == {}


def test_keine_down_migration_im_vertrag():
    for migration in ALL_MIGRATIONS:
        assert not hasattr(migration, "downgrade")
        assert not hasattr(migration, "down_statements")


def test_pruefsumme_ist_formatunabhaengig():
    a = Migration("0001", "base", "d", ("CREATE  TABLE t (a INTEGER)",), 1)
    b = Migration("0001", "base", "d", ("CREATE TABLE t   (a INTEGER)",), 1)
    assert a.checksum == b.checksum


def test_pruefsumme_aendert_sich_mit_dem_inhalt():
    a = Migration("0001", "base", "d", ("CREATE TABLE t (a INTEGER)",), 1)
    b = Migration("0001", "base", "d", ("CREATE TABLE t (b INTEGER)",), 1)
    assert a.checksum != b.checksum


# ── Constraints des Schemas ──────────────────────────────────────────────────
def test_fremdschluessel_greifen(migrated_factory):
    import sqlite3

    conn = migrated_factory.connect()
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO contact_emails (id, contact_id, position, value_raw, "
            "value_normalized) VALUES ('11111111-1111-4111-8111-111111111111',"
            "'22222222-2222-4222-8222-222222222222',0,'a@example.invalid',"
            "'a@example.invalid')"
        )


def test_check_constraint_lehnt_unbekannten_verfuegbarkeitszustand_ab(
    migrated_factory,
):
    import sqlite3

    conn = migrated_factory.connect()
    conn.execute(
        "INSERT INTO contacts (id, workspace_id, contact_type, display_name, "
        "created_at, updated_at) VALUES "
        "('33333333-3333-4333-8333-333333333333','ws','person','X',"
        "'2026-01-01T00:00:00+00:00','2026-01-01T00:00:00+00:00')"
    )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO contact_field_availability VALUES "
            "('33333333-3333-4333-8333-333333333333','note','vielleicht_leer',"
            "'2026-01-01T00:00:00+00:00')"
        )


def test_check_constraint_erzwingt_tombstone_mit_datum(migrated_factory):
    import sqlite3

    conn = migrated_factory.connect()
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO contacts (id, workspace_id, contact_type, display_name, "
            "is_tombstone, created_at, updated_at) VALUES "
            "('44444444-4444-4444-8444-444444444444','ws','person','X',1,"
            "'2026-01-01T00:00:00+00:00','2026-01-01T00:00:00+00:00')"
        )


def test_check_constraint_erzwingt_mutationsziel(migrated_factory):
    import sqlite3

    conn = migrated_factory.connect()
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO contacts_mutations (mutation_id, command, "
            "correlation_id, actor, initiation_context, workspace_id, "
            "provider_account_id, idempotency_key, transaction_author, "
            "payload_json, payload_digest, preview_digest, state, created_at) "
            "VALUES ('55555555-5555-4555-8555-555555555555','create','c','t',"
            "'user_direct','ws','konto-a','k','autor','{}','d','d',"
            "'prepared','2026-01-01T00:00:00+00:00')"
        )


def test_unique_constraint_auf_idempotenzschluessel(migrated_factory):
    import sqlite3

    conn = migrated_factory.connect()
    for i in (6, 7):
        sql = (
            "INSERT INTO contacts_mutations (mutation_id, command, "
            "correlation_id, actor, initiation_context, workspace_id, "
            "provider_account_id, container_identifier, idempotency_key, "
            "transaction_author, payload_json, payload_digest, "
            "preview_digest, state, created_at) VALUES "
            f"('{i}{i}{i}{i}{i}{i}{i}{i}-{i}{i}{i}{i}-4{i}{i}{i}-8{i}{i}{i}-"
            f"{i}{i}{i}{i}{i}{i}{i}{i}{i}{i}{i}{i}','create','corr','tester',"
            "'user_direct','ws','konto-a','container-1','derselbe','autor',"
            "'{}','d','d','prepared','2026-01-01T00:00:00+00:00')"
        )
        if i == 6:
            conn.execute(sql)
        else:
            with pytest.raises(sqlite3.IntegrityError):
                conn.execute(sql)


def test_loeschregel_restrict_bei_kinddatensaetzen(migrated_factory):
    """Plan §5.1: harter Löschversuch am Elternkontakt scheitert fail-closed,
    solange Kinddaten existieren (Migration 0003, Audit-Befund 1)."""
    import sqlite3

    conn = migrated_factory.connect()
    cid = "88888888-8888-4888-8888-888888888888"
    conn.execute(
        "INSERT INTO contacts (id, workspace_id, contact_type, display_name, "
        "created_at, updated_at) VALUES (?,?,?,?,?,?)",
        (cid, "ws", "person", "X", "2026-01-01T00:00:00+00:00",
         "2026-01-01T00:00:00+00:00"),
    )
    conn.execute(
        "INSERT INTO contact_emails (id, contact_id, position, value_raw, "
        "value_normalized) VALUES (?,?,?,?,?)",
        ("99999999-9999-4999-8999-999999999999", cid, 0, "a@example.invalid",
         "a@example.invalid"),
    )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("DELETE FROM contacts WHERE id = ?", (cid,))
    # Nach ausdrücklicher Kind-Löschung ist der Eltern-Löschpfad frei.
    conn.execute("DELETE FROM contact_emails WHERE contact_id = ?", (cid,))
    conn.execute("DELETE FROM contacts WHERE id = ?", (cid,))
    assert conn.execute("SELECT count(*) FROM contacts").fetchone()[0] == 0


def test_migration_0003_uebernimmt_bestandsdaten(factory):
    """Der Neuaufbau in 0003 kopiert vorhandene Kinddaten verlustfrei."""
    runner_bis_0002 = MigrationRunner(factory, ALL_MIGRATIONS[:2])
    runner_bis_0002.run()
    conn = factory.connect()
    cid = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
    conn.execute(
        "INSERT INTO contacts (id, workspace_id, contact_type, display_name, "
        "created_at, updated_at) VALUES (?,?,?,?,?,?)",
        (cid, "ws", "person", "X", "2026-01-01T00:00:00+00:00",
         "2026-01-01T00:00:00+00:00"),
    )
    conn.execute(
        "INSERT INTO contact_emails (id, contact_id, position, label_raw, "
        "value_raw, value_normalized) VALUES (?,?,?,?,?,?)",
        ("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb", cid, 0, "_$!<Home>!$_",
         "x@example.invalid", "x@example.invalid"),
    )
    MigrationRunner(factory, ALL_MIGRATIONS).run()
    row = factory.connect().execute(
        "SELECT label_raw, value_raw FROM contact_emails WHERE contact_id = ?",
        (cid,)).fetchone()
    assert row["label_raw"] == "_$!<Home>!$_"
    assert row["value_raw"] == "x@example.invalid"


def test_kein_note_feld_in_der_kontakttabelle(migrated_factory):
    """Notizen sind strukturell kein Fachfeld (08 §4)."""
    conn = migrated_factory.connect()
    spalten = {r[1] for r in conn.execute("PRAGMA table_info(contacts)")}
    assert "note" not in spalten
    assert "notes" not in spalten


def test_keine_binaerspalte_fuer_thumbnails(migrated_factory):
    conn = migrated_factory.connect()
    spalten = {r[1]: r[2] for r in conn.execute("PRAGMA table_info(contacts)")}
    assert spalten["thumbnail_blob_ref"] == "TEXT"
    assert not any(t.upper() == "BLOB" for t in spalten.values())
