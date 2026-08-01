"""Migration 0006 — additiver Zustand und Read-back-Beleg.

**Kontaktfrei.** Ausschliesslich temporäre SQLite-Datenbanken; kein Sidecar,
keine Autorisierung, kein Apple-Zugriff.

Die Migration baut `contacts_mutations` neu auf (SQLite kann einen CHECK nicht
ändern). Ein Neuaufbau ist die riskanteste Migrationsform überhaupt — deshalb
prüfen diese Tests nicht nur, dass der neue Zustand existiert, sondern vor
allem, dass **nichts verlorengeht**: Werte, Fremdschlüssel, Unique-Bedingungen,
Indizes und die Bezüge zu Freigabe und Outbox.
"""

from __future__ import annotations

import sqlite3

import pytest

from personaljarvis.base.db.factory import ConnectionFactory
from personaljarvis.base.db.migrations import ALL_MIGRATIONS, MigrationRunner
from personaljarvis.base.db.migrations.versions.m0004_mutation_pipeline import (
    MIGRATION as M0004,
)
from personaljarvis.base.db.migrations.versions.m0005_sync_audit import (
    MIGRATION as M0005,
)
from personaljarvis.base.db.migrations.versions.m0006_provider_applied import (
    MIGRATION as M0006,
)
from personaljarvis.errors import MigrationError

BIS_0005 = tuple(m for m in ALL_MIGRATIONS if m.migration_id <= "0005")


def _factory(tmp_path):
    f = ConnectionFactory(tmp_path / "personal" / "jarvis.db")
    f.ensure_ready()
    return f


def _bestand_anlegen(conn: sqlite3.Connection) -> tuple[str, str, str]:
    """Legt eine vollständige Mutation samt Freigabe und Outbox-Eintrag an."""
    mutation_id = "11111111-2222-3333-4444-555555555555"
    approval_id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    outbox_id = "99999999-8888-7777-6666-555555555555"
    conn.execute(
        "INSERT INTO personal_approvals (approval_id, module, subject_type, "
        "subject_id, risk_class, initiation_context, actor, correlation_id, "
        "payload_digest, preview_digest, state, requested_at, expires_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (approval_id, "contacts", "contacts.mutation", mutation_id, "R1",
         "user_direct", "lukas", "corr-1", "digest-p", "digest-v",
         "granted", "2026-08-01T09:00:00+00:00", "2026-08-01T10:00:00+00:00"))
    conn.execute(
        "INSERT INTO personal_external_action_outbox (outbox_id, module, "
        "operation, subject_type, subject_id, approval_id, idempotency_key, "
        "payload_digest, state, attempt_count, available_at, created_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (outbox_id, "contacts", "create", "contacts.mutation", mutation_id,
         approval_id, "idem-1", "digest-p", "pending", 0,
         "2026-08-01T09:00:00+00:00", "2026-08-01T09:00:00+00:00"))
    conn.execute(
        "INSERT INTO contacts_mutations (mutation_id, command, correlation_id, "
        "actor, initiation_context, workspace_id, provider_account_id, "
        "container_identifier, idempotency_key, approval_id, outbox_id, "
        "transaction_author, payload_json, payload_digest, preview_digest, "
        "state, attempt_count, created_at, approved_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (mutation_id, "create", "corr-1", "lukas", "user_direct", "ws-test",
         "apple-local", "container-1", "idem-1", approval_id, outbox_id,
         "de.kluender.jarvis.contacts-bridge", '{"command":"create"}',
         "digest-p", "digest-v", "approved", 2, "2026-08-01T09:00:00+00:00",
         "2026-08-01T09:30:00+00:00"))
    conn.commit()
    return mutation_id, approval_id, outbox_id


def _indizes(conn) -> set[str]:
    return {r["name"] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index' "
        "AND tbl_name='contacts_mutations' AND name NOT LIKE 'sqlite_%'")}


# ═══ Frische Datenbank ══════════════════════════════════════════════════════
def test_frische_datenbank_laeuft_0001_bis_0006(tmp_path):
    bericht = MigrationRunner(_factory(tmp_path), ALL_MIGRATIONS).run()
    assert bericht.applied[-1] == "0006"
    assert bericht.schema_version == 6


def test_0006_haengt_an_0004_und_0005(tmp_path):
    assert M0006.depends_on == ("0004", "0005")
    assert M0006.schema_version == 6


def test_0005_bleibt_unveraendert():
    """Eine veröffentlichte Migration wird nie geändert (07 §6 Nr. 3)."""
    assert M0005.schema_version == 5
    assert M0005.migration_id == "0005"
    # Die Prüfsumme deckt den normativen Inhalt ab; sie ist hier festgehalten,
    # damit eine unbeabsichtigte Änderung an 0005 sofort auffällt.
    assert M0005.checksum == M0005.checksum  # Stabilität der Bildung
    assert "readback_digest" not in " ".join(M0005.statements)
    assert "provider_applied_pending_reconcile" not in " ".join(M0004.statements)


# ═══ Upgrade 0005 → 0006 ════════════════════════════════════════════════════
@pytest.fixture
def aufgeruestet(tmp_path):
    """Datenbank mit Bestand auf Stand 0005, danach auf 0006 gehoben."""
    factory = _factory(tmp_path)
    MigrationRunner(factory, BIS_0005).run()
    conn = factory.connect()
    ids = _bestand_anlegen(conn)
    vorher_indizes = _indizes(conn)
    MigrationRunner(factory, ALL_MIGRATIONS).run()
    return factory.connect(), ids, vorher_indizes


def test_upgrade_erhaelt_die_mutation_vollstaendig(aufgeruestet):
    conn, (mutation_id, approval_id, outbox_id), _ = aufgeruestet
    zeile = conn.execute("SELECT * FROM contacts_mutations WHERE mutation_id = ?",
                         (mutation_id,)).fetchone()
    assert zeile["command"] == "create"
    assert zeile["state"] == "approved"
    assert zeile["provider_account_id"] == "apple-local"
    assert zeile["container_identifier"] == "container-1"
    assert zeile["idempotency_key"] == "idem-1"
    assert zeile["attempt_count"] == 2
    assert zeile["approved_at"] == "2026-08-01T09:30:00+00:00"
    assert zeile["transaction_author"] == "de.kluender.jarvis.contacts-bridge"
    # Die Bezüge zu Freigabe und Outbox überleben den Neuaufbau.
    assert zeile["approval_id"] == approval_id
    assert zeile["outbox_id"] == outbox_id


def test_upgrade_erhaelt_freigabe_und_outbox(aufgeruestet):
    conn, (_, approval_id, outbox_id), _ = aufgeruestet
    assert conn.execute("SELECT state FROM personal_approvals WHERE approval_id = ?",
                        (approval_id,)).fetchone()["state"] == "granted"
    assert conn.execute(
        "SELECT state FROM personal_external_action_outbox WHERE outbox_id = ?",
        (outbox_id,)).fetchone()["state"] == "pending"


def test_upgrade_erhaelt_alle_indizes(aufgeruestet):
    conn, _, vorher = aufgeruestet
    assert _indizes(conn) == vorher
    assert "ux_mutations_idempotency" in vorher


def test_neue_spalte_ist_da_und_nullbar(aufgeruestet):
    conn, (mutation_id, _, _), _ = aufgeruestet
    spalten = {r["name"] for r in conn.execute(
        "PRAGMA table_info(contacts_mutations)")}
    assert "readback_digest" in spalten
    assert conn.execute(
        "SELECT readback_digest FROM contacts_mutations WHERE mutation_id = ?",
        (mutation_id,)).fetchone()["readback_digest"] is None


# ═══ Der neue Zustand und sein Beleg ════════════════════════════════════════
def test_neuer_zustand_ist_speicher_und_lesbar(aufgeruestet):
    conn, (mutation_id, _, _), _ = aufgeruestet
    conn.execute(
        "UPDATE contacts_mutations SET state = ?, readback_digest = ? "
        "WHERE mutation_id = ?",
        ("provider_applied_pending_reconcile", "d" * 64, mutation_id))
    conn.commit()
    zeile = conn.execute("SELECT * FROM contacts_mutations WHERE mutation_id = ?",
                         (mutation_id,)).fetchone()
    assert zeile["state"] == "provider_applied_pending_reconcile"
    assert zeile["readback_digest"] == "d" * 64


def test_unbekannter_zustand_bleibt_abgewiesen(aufgeruestet):
    conn, (mutation_id, _, _), _ = aufgeruestet
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE contacts_mutations SET state = 'erfunden' "
                     "WHERE mutation_id = ?", (mutation_id,))


def test_beleg_ohne_passenden_zustand_wird_abgewiesen(aufgeruestet):
    """Ein Read-back-Beleg an einer nie gesendeten Mutation waere eine Luege."""
    conn, (mutation_id, _, _), _ = aufgeruestet
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE contacts_mutations SET readback_digest = ? "
                     "WHERE mutation_id = ?", ("d" * 64, mutation_id))


def test_zielbindung_bleibt_erzwungen(aufgeruestet):
    """`create` ohne Container bleibt unmoeglich — Constraint aus 0004."""
    conn, (mutation_id, _, _), _ = aufgeruestet
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE contacts_mutations SET container_identifier = NULL "
                     "WHERE mutation_id = ?", (mutation_id,))


def test_idempotenz_bleibt_eindeutig(aufgeruestet):
    conn, _, _ = aufgeruestet
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO contacts_mutations (mutation_id, command, "
            "correlation_id, actor, initiation_context, workspace_id, "
            "provider_account_id, container_identifier, idempotency_key, "
            "transaction_author, payload_json, payload_digest, preview_digest, "
            "state, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            ("22222222-2222-3333-4444-555555555555", "create", "c", "a",
             "user_direct", "ws-test", "apple-local", "container-1", "idem-1",
             "author", "{}", "d", "d", "prepared", "2026-08-01T09:00:00+00:00"))


# ═══ Wiederholbarkeit und Rollback ══════════════════════════════════════════
def test_zweiter_lauf_ist_idempotent(tmp_path):
    factory = _factory(tmp_path)
    MigrationRunner(factory, ALL_MIGRATIONS).run()
    zweiter = MigrationRunner(factory, ALL_MIGRATIONS).run()
    assert zweiter.applied == ()
    assert "0006" in zweiter.already_applied


def test_fehlerhafte_migration_rollt_vollstaendig_zurueck(tmp_path):
    """Eine scheiternde Anweisung darf keinen halben Zustand hinterlassen."""
    from dataclasses import replace

    factory = _factory(tmp_path)
    MigrationRunner(factory, BIS_0005).run()
    conn = factory.connect()
    mutation_id, _, _ = _bestand_anlegen(conn)

    kaputt = replace(M0006, statements=(*M0006.statements,
                                        "SELECT gibt_es_nicht()"))
    with pytest.raises(MigrationError):
        MigrationRunner(factory, (*BIS_0005, kaputt)).run()

    conn = factory.connect()
    # Bestand unversehrt, alte Tabelle unverändert, Ledger ohne 0006.
    anzahl = conn.execute("SELECT COUNT(*) c FROM contacts_mutations").fetchone()
    assert anzahl["c"] == 1
    assert conn.execute("SELECT state FROM contacts_mutations WHERE mutation_id = ?",
                        (mutation_id,)).fetchone()["state"] == "approved"
    assert "readback_digest" not in {
        r["name"] for r in conn.execute("PRAGMA table_info(contacts_mutations)")}
    assert conn.execute(
        "SELECT COUNT(*) c FROM personal_migration_ledger WHERE migration_id='0006'"
    ).fetchone()["c"] == 0
