"""Migration 0007 — terminaler Abschlusszustand und Containerart.

**Kontaktfrei.** Ausschliesslich temporäre SQLite-Datenbanken.

Zwei Änderungen mit sehr unterschiedlichem Risiko: der neue Zustand verlangt
einen Tabellenneuaufbau (SQLite kann einen CHECK nicht ändern), die neue
Spalte in `contacts_sync_state` nicht. Die Tests prüfen für den Neuaufbau vor
allem, dass **nichts verlorengeht** — und zwar an einem Bestand, wie ihn der
gescheiterte Livetest hinterlassen hat: eine Mutation auf `outcome_unknown`
mit verbrauchter Freigabe und ungewisser Outbox.
"""

from __future__ import annotations

import sqlite3

import pytest

from personaljarvis.base.db.factory import ConnectionFactory
from personaljarvis.base.db.migrations import ALL_MIGRATIONS, MigrationRunner
from personaljarvis.base.db.migrations.versions.m0006_provider_applied import (
    MIGRATION as M0006,
)
from personaljarvis.base.db.migrations.versions.m0007_manual_resolution import (
    MIGRATION as M0007,
)
from personaljarvis.errors import MigrationError

BIS_0006 = tuple(m for m in ALL_MIGRATIONS if m.migration_id <= "0006")

MUTATION = "11111111-2222-3333-4444-555555555555"
APPROVAL = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
OUTBOX = "99999999-8888-7777-6666-555555555555"


def _factory(tmp_path):
    f = ConnectionFactory(tmp_path / "personal" / "jarvis.db")
    f.ensure_ready()
    return f


def _livestand(conn: sqlite3.Connection) -> None:
    """Der Bestand, wie ihn der gescheiterte Livetest hinterlassen hat."""
    conn.execute(
        "INSERT INTO personal_approvals (approval_id, module, subject_type, "
        "subject_id, risk_class, initiation_context, actor, correlation_id, "
        "payload_digest, preview_digest, state, requested_at, expires_at, "
        "consumed_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (APPROVAL, "contacts", "contacts.mutation", MUTATION, "R1",
         "user_direct", "lukas", "corr-1", "digest-p", "digest-v", "consumed",
         "2026-08-01T09:00:00+00:00", "2026-08-01T09:15:00+00:00",
         "2026-08-01T09:17:00+00:00"))
    conn.execute(
        "INSERT INTO personal_external_action_outbox (outbox_id, module, "
        "operation, subject_type, subject_id, approval_id, idempotency_key, "
        "payload_digest, state, attempt_count, available_at, created_at, "
        "last_error_code) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (OUTBOX, "contacts", "create", "contacts.mutation", MUTATION, APPROVAL,
         "idem-1", "digest-p", "outcome_unknown", 1,
         "2026-08-01T09:00:00+00:00", "2026-08-01T09:00:00+00:00",
         "child_signalled"))
    conn.execute(
        "INSERT INTO contacts_mutations (mutation_id, command, correlation_id, "
        "actor, initiation_context, workspace_id, provider_account_id, "
        "container_identifier, idempotency_key, approval_id, outbox_id, "
        "transaction_author, payload_json, payload_digest, preview_digest, "
        "state, outcome, attempt_count, last_error_code, created_at, "
        "approved_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (MUTATION, "create", "corr-1", "lukas", "user_direct", "ws-test",
         "apple-local", "container-1", "idem-1", APPROVAL, OUTBOX,
         "de.kluender.jarvis.contacts-bridge", '{"command":"create"}',
         "digest-p", "digest-v", "outcome_unknown", "outcome_unknown", 1,
         "child_signalled", "2026-08-01T09:00:00+00:00",
         "2026-08-01T09:16:00+00:00"))
    conn.execute(
        "INSERT INTO contacts_sync_state (provider_account_id, "
        "container_identifier, key_set_version, mode, cursor_token, "
        "circuit_state, updated_at) VALUES (?,?,?,?,?,?,?)",
        ("apple-local", "container-1", "1", "delta", "TOKEN", "closed",
         "2026-08-01T09:00:00+00:00"))
    conn.commit()


def _indizes(conn) -> set[str]:
    return {r["name"] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index' "
        "AND tbl_name='contacts_mutations' AND name NOT LIKE 'sqlite_%'")}


@pytest.fixture
def aufgeruestet(tmp_path):
    factory = _factory(tmp_path)
    MigrationRunner(factory, BIS_0006).run()
    conn = factory.connect()
    _livestand(conn)
    vorher = _indizes(conn)
    MigrationRunner(factory, ALL_MIGRATIONS).run()
    return factory.connect(), vorher


# ═══ Grundlagen ═════════════════════════════════════════════════════════════
def test_frische_datenbank_laeuft_bis_0007(tmp_path):
    bericht = MigrationRunner(_factory(tmp_path), ALL_MIGRATIONS).run()
    assert bericht.applied[-1] == "0007"
    assert bericht.schema_version == 7


def test_0007_haengt_an_0006(tmp_path):
    assert M0007.depends_on == ("0006",)
    assert M0007.schema_version == 7


def test_0006_bleibt_unveraendert():
    """Eine veröffentlichte Migration wird nie geändert (07 §6 Nr. 3)."""
    assert "manually_resolved_not_applied" not in " ".join(M0006.statements)
    assert "container_type" not in " ".join(M0006.statements)


# ═══ Der Livebestand überlebt ═══════════════════════════════════════════════
def test_die_gescheiterte_mutation_bleibt_vollstaendig(aufgeruestet):
    conn, _ = aufgeruestet
    zeile = conn.execute("SELECT * FROM contacts_mutations WHERE mutation_id = ?",
                         (MUTATION,)).fetchone()
    assert zeile["state"] == "outcome_unknown"
    assert zeile["outcome"] == "outcome_unknown"
    assert zeile["last_error_code"] == "child_signalled"
    assert zeile["attempt_count"] == 1
    assert zeile["approval_id"] == APPROVAL
    assert zeile["outbox_id"] == OUTBOX
    assert zeile["approved_at"] == "2026-08-01T09:16:00+00:00"


def test_freigabe_und_outbox_bleiben(aufgeruestet):
    conn, _ = aufgeruestet
    assert conn.execute("SELECT state FROM personal_approvals").fetchone()[
        "state"] == "consumed"
    outbox = conn.execute(
        "SELECT state, attempt_count FROM personal_external_action_outbox"
    ).fetchone()
    assert outbox["state"] == "outcome_unknown"
    assert outbox["attempt_count"] == 1


def test_alle_indizes_bleiben(aufgeruestet):
    conn, vorher = aufgeruestet
    assert _indizes(conn) == vorher
    assert "ux_mutations_idempotency" in vorher


def test_die_belegspalte_aus_0006_bleibt(aufgeruestet):
    conn, _ = aufgeruestet
    spalten = {r["name"] for r in conn.execute(
        "PRAGMA table_info(contacts_mutations)")}
    assert "readback_digest" in spalten


# ═══ Der neue Zustand ═══════════════════════════════════════════════════════
def test_neuer_zustand_ist_speicher_und_lesbar(aufgeruestet):
    conn, _ = aufgeruestet
    conn.execute("UPDATE contacts_mutations SET state = ?, outcome = ?, "
                 "completed_at = ? WHERE mutation_id = ?",
                 ("manually_resolved_not_applied", "failed",
                  "2026-08-01T12:00:00+00:00", MUTATION))
    conn.commit()
    assert conn.execute("SELECT state FROM contacts_mutations").fetchone()[
        "state"] == "manually_resolved_not_applied"


def test_unbekannter_zustand_bleibt_abgewiesen(aufgeruestet):
    conn, _ = aufgeruestet
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE contacts_mutations SET state = 'erfunden' "
                     "WHERE mutation_id = ?", (MUTATION,))


def test_beleg_ohne_passenden_zustand_bleibt_abgewiesen(aufgeruestet):
    """Der CHECK aus 0006 gilt unveraendert weiter."""
    conn, _ = aufgeruestet
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE contacts_mutations SET readback_digest = ? "
                     "WHERE mutation_id = ?", ("d" * 64, MUTATION))


def test_zielbindung_bleibt_erzwungen(aufgeruestet):
    conn, _ = aufgeruestet
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE contacts_mutations SET container_identifier = NULL "
                     "WHERE mutation_id = ?", (MUTATION,))


# ═══ Die Containerart ═══════════════════════════════════════════════════════
def test_containerart_ist_da_und_nullbar(aufgeruestet):
    conn, _ = aufgeruestet
    spalten = {r["name"] for r in conn.execute(
        "PRAGMA table_info(contacts_sync_state)")}
    assert "container_type" in spalten
    # Bestandszeilen bleiben ohne Angabe — „noch nicht erhoben", nicht „lokal".
    assert conn.execute(
        "SELECT container_type FROM contacts_sync_state").fetchone()[
            "container_type"] is None


def test_containerart_ist_speicher_und_lesbar(aufgeruestet):
    conn, _ = aufgeruestet
    conn.execute("UPDATE contacts_sync_state SET container_type = 'local'")
    conn.commit()
    assert conn.execute(
        "SELECT container_type FROM contacts_sync_state").fetchone()[
            "container_type"] == "local"


def test_der_sync_zustand_bleibt_sonst_unveraendert(aufgeruestet):
    conn, _ = aufgeruestet
    zeile = conn.execute("SELECT * FROM contacts_sync_state").fetchone()
    assert zeile["mode"] == "delta"
    assert zeile["cursor_token"] == "TOKEN"
    assert zeile["circuit_state"] == "closed"


# ═══ Wiederholbarkeit und Rollback ══════════════════════════════════════════
def test_zweiter_lauf_ist_idempotent(tmp_path):
    factory = _factory(tmp_path)
    MigrationRunner(factory, ALL_MIGRATIONS).run()
    zweiter = MigrationRunner(factory, ALL_MIGRATIONS).run()
    assert zweiter.applied == ()
    assert "0007" in zweiter.already_applied


def test_fehlerhafte_migration_rollt_vollstaendig_zurueck(tmp_path):
    from dataclasses import replace

    factory = _factory(tmp_path)
    MigrationRunner(factory, BIS_0006).run()
    conn = factory.connect()
    _livestand(conn)

    kaputt = replace(M0007, statements=(*M0007.statements,
                                        "SELECT gibt_es_nicht()"))
    with pytest.raises(MigrationError):
        MigrationRunner(factory, (*BIS_0006, kaputt)).run()

    conn = factory.connect()
    zeile = conn.execute("SELECT state, attempt_count FROM contacts_mutations"
                         ).fetchone()
    assert zeile["state"] == "outcome_unknown"
    assert zeile["attempt_count"] == 1
    assert "container_type" not in {
        r["name"] for r in conn.execute("PRAGMA table_info(contacts_sync_state)")}
    assert conn.execute(
        "SELECT COUNT(*) c FROM personal_migration_ledger WHERE migration_id='0007'"
    ).fetchone()["c"] == 0
