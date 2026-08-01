"""Migration 0006 — bestätigte Providerwirkung vor der lokalen Nachführung.

Ein `create` beim Provider hat eine Zwischenlage, die der Zustandsvorrat aus
0004 nicht ausdrücken kann: **Apple hat den Kontakt angelegt und der Read-back
belegt es, aber der kanonische Spiegel ist noch nicht nachgeführt.** Ohne
eigenen Zustand wäre dieser Fall von `outcome_unknown` nicht zu unterscheiden
— und genau diese Unterscheidung ist sicherheitsrelevant: aus
`outcome_unknown` weiß niemand, ob gesendet wurde; hier ist bewiesen, dass
gesendet **und** angewandt wurde. `recover_interrupted()` würde einen Abbruch
nach bestätigtem Save sonst fälschlich als unbekannt einstufen und den
Vorgang in einen Abgleich schicken, der nichts mehr zu klären hat.

Deshalb: `provider_applied_pending_reconcile`. Aus ihm führt **nie** ein
weiterer Send; die Auflösung ist ausschließlich die Wiederholung der
**lokalen** Nachführung (ADR-0019 §5).

`readback_digest` hält den Beleg fest: einen Fingerabdruck des vom Provider
zurückgelesenen Zustands über die kanonischen, schreibbaren Felder des
Feldvertrags v1. Apple stellt keine Revisionsnummer bereit — dieser Digest
ist der stabile Revisionsbeleg. Er enthält **keine** Kontaktwerte im Klartext,
keine Provider-Identifier, keine lokalen Kennungen und keine Zeitstempel.

**Warum Neuaufbau statt `ALTER TABLE`:** SQLite kann einen CHECK-Constraint
nicht ändern. Die Zustandsmenge steht im CHECK von `contacts_mutations`; ein
neuer Zustand verlangt deshalb dasselbe Neuaufbaumuster wie 0004. Alle Spalten,
Constraints und Indizes werden wortgleich übernommen — die einzige Änderung
sind der erweiterte Zustands-CHECK und die neue Spalte.

**Datenübernahme:** vollständig und wertgleich; kein Zustand wird abgebildet
oder umbenannt, denn der Vorrat wächst nur. Fremdschlüssel, Unique-Indizes und
sekundäre Indizes werden anschließend identisch neu angelegt.

**Idempotenz:** wie jede Migration über das Ledger — ein zweiter Lauf sieht
0006 als angewandt und führt nichts aus (07 §6).
"""

from __future__ import annotations

from personaljarvis.base.db.migrations.ledger import Migration

__all__ = ["MIGRATION", "MUTATION_STATES_0006"]

#: Zustandsvorrat ab 0006 — die Menge aus 0004 plus genau einem Zustand.
MUTATION_STATES_0006: tuple[str, ...] = (
    "prepared", "awaiting_approval", "approved", "rejected", "expired",
    "cancelled", "executing", "succeeded", "failed_before_send",
    "outcome_unknown", "provider_applied_pending_reconcile",
    "reconcile_required", "manual_decision_required", "failed",
)


def _in(werte: tuple[str, ...]) -> str:
    return "(" + ",".join(f"'{w}'" for w in werte) + ")"


_STATEMENTS: tuple[str, ...] = (
    f"""
    CREATE TABLE contacts_mutations_0006 (
        mutation_id                TEXT NOT NULL PRIMARY KEY,
        command                    TEXT NOT NULL,
        correlation_id             TEXT NOT NULL,
        actor                      TEXT NOT NULL,
        initiation_context         TEXT NOT NULL,
        workspace_id               TEXT NOT NULL,
        provider_account_id        TEXT NOT NULL,
        container_identifier       TEXT,
        target_contact_id          TEXT REFERENCES contacts(id) ON DELETE SET NULL,
        target_provider_identifier TEXT,
        expected_revision          TEXT,
        idempotency_key            TEXT NOT NULL,
        approval_id                TEXT,
        outbox_id                  TEXT,
        audit_id                   TEXT,
        transaction_author         TEXT NOT NULL,
        payload_json               TEXT NOT NULL,
        payload_digest             TEXT NOT NULL,
        preview_digest             TEXT NOT NULL,
        readback_digest            TEXT,
        state                      TEXT NOT NULL,
        outcome                    TEXT,
        attempt_count              INTEGER NOT NULL DEFAULT 0,
        last_error_code            TEXT,
        created_at                 TEXT NOT NULL,
        approved_at                TEXT,
        execution_started_at       TEXT,
        completed_at               TEXT,
        CHECK (length(mutation_id) = 36),
        CHECK (command IN ('create','update','delete')),
        CHECK (correlation_id <> ''),
        CHECK (actor <> ''),
        CHECK (provider_account_id <> ''),
        CHECK (idempotency_key <> ''),
        CHECK (payload_digest <> ''),
        CHECK (transaction_author <> ''),
        CHECK (attempt_count >= 0),
        CHECK (state IN {_in(MUTATION_STATES_0006)}),
        CHECK (outcome IS NULL OR outcome IN ('succeeded','failed','outcome_unknown')),
        -- Unveraendert aus 0004: create braucht einen Container, update und
        -- delete eine stabile Provider-ID. Niemals ein Name.
        CHECK (command <> 'create' OR container_identifier IS NOT NULL),
        CHECK (command = 'create' OR target_provider_identifier IS NOT NULL),
        -- Neu: der Beleg gehoert genau zu den Zustaenden, die ihn haben
        -- koennen. Ein Digest an einer nie gesendeten Mutation waere eine
        -- Behauptung ohne Grundlage.
        CHECK (readback_digest IS NULL
               OR state IN ('provider_applied_pending_reconcile','succeeded'))
    ) STRICT
    """,
    # Vollstaendige, wertgleiche Uebernahme. Kein Zustand wird abgebildet:
    # der Vorrat waechst, er aendert sich nicht.
    """
    INSERT INTO contacts_mutations_0006 (
        mutation_id, command, correlation_id, actor, initiation_context,
        workspace_id, provider_account_id, container_identifier,
        target_contact_id, target_provider_identifier, expected_revision,
        idempotency_key, approval_id, outbox_id, audit_id, transaction_author,
        payload_json, payload_digest, preview_digest, readback_digest,
        state, outcome, attempt_count, last_error_code, created_at,
        approved_at, execution_started_at, completed_at
    )
    SELECT
        mutation_id, command, correlation_id, actor, initiation_context,
        workspace_id, provider_account_id, container_identifier,
        target_contact_id, target_provider_identifier, expected_revision,
        idempotency_key, approval_id, outbox_id, audit_id, transaction_author,
        payload_json, payload_digest, preview_digest, NULL,
        state, outcome, attempt_count, last_error_code, created_at,
        approved_at, execution_started_at, completed_at
    FROM contacts_mutations
    """,
    "DROP TABLE contacts_mutations",
    "ALTER TABLE contacts_mutations_0006 RENAME TO contacts_mutations",
    # Indizes wortgleich zu 0004 wiederherstellen.
    "CREATE UNIQUE INDEX ux_mutations_idempotency ON contacts_mutations "
    "(provider_account_id, idempotency_key)",
    "CREATE INDEX ix_mutations_state ON contacts_mutations (state)",
    "CREATE INDEX ix_mutations_target ON contacts_mutations (target_contact_id)",
    "CREATE INDEX ix_mutations_provider_target ON contacts_mutations "
    "(provider_account_id, target_provider_identifier)",
    "CREATE INDEX ix_mutations_correlation ON contacts_mutations (correlation_id)",
)

MIGRATION = Migration(
    migration_id="0006",
    module_owner="contacts",
    description=(
        "Zustand provider_applied_pending_reconcile und Read-back-Beleg "
        "fuer die freigabepflichtige Kontaktanlage"
    ),
    statements=_STATEMENTS,
    schema_version=6,
    depends_on=("0004", "0005"),
)
