"""Migration 0008 — Transportzustand des App-Prozess-Mutationskanals.

ADR-0020 verlegt den produktiven Schreibkanal vom CLI-Sidecar in den
Tauri-App-Prozess. Damit wandert der Provideraufruf aus dem Backend heraus,
und der Kern muss drei Dinge festhalten können, die es vorher nicht gab:

1. **Welcher eine Versuch** gerade unterwegs ist (`operation_id`) und wann
   sein Auftrag **ausgegeben** wurde (`execution_order_issued_at`). Ab der
   Ausgabe ist ein zweiter Claim ausgeschlossen — auch nach Verfall, denn ob
   irgendwo gesendet wurde, ist von da an prinzipiell unbeweisbar.
2. **Womit der Rückläufer gebunden ist**: `claim_token_digest` statt des
   bisherigen Klartext-Tokens (ADR-0020 §3 — der Rohtoken existiert nur
   flüchtig im Auftrag) und `execution_report_digest`, der das Settle
   idempotent macht: derselbe Bericht darf beliebig oft ankommen, ein
   **anderer** nie.
3. **Wie es ausging**, PII-arm: `error_class` aus einer geschlossenen Menge,
   `error_digest` als SHA-256 des Rohgrunds, `provider_completed_at`.

Dazu zwei Altlasten aus dem Audit vom 2026-08-03:

* `contacts_mutations` bekommt `manually_resolved_applied` in den
  Zustands-CHECK (ADR-0020 §4.1) — das Gegenstück zu
  `manually_resolved_not_applied`: ein Mensch hat die Änderung beim Provider
  **gesehen**, ohne dass der Abgleich sie beweisen kann. Ohne eigenen
  Zustand müsste man `succeeded` behaupten und damit einen Beleg erfinden.
* `personal_audit_log.stage` bekommt den fehlenden CHECK. Die geschlossene
  Stufenmenge lebte bisher nur in Python; eine Datenbank, die jede
  Zeichenkette annimmt, kann eine Auditkette nicht garantieren.

**Warum Neuaufbau statt `ALTER TABLE`:** SQLite kann einen CHECK nicht
ändern, und bei allen drei Tabellen steht die geschlossene Menge in genau
einem. Spalten, Constraints und Indizes werden wortgleich übernommen;
`claim_token` wird dabei **nicht** übertragen — der Klartext verschwindet
ersatzlos (er war nie für die Dauer gedacht, und ein laufender Claim
übersteht eine Migration ohnehin nicht: der Prozess, der ihn hält, ist
gestoppt).
"""

from __future__ import annotations

from personaljarvis.base.db.migrations.ledger import Migration
from personaljarvis.base.db.migrations.versions.m0007_manual_resolution import (
    MUTATION_STATES_0007,
)

__all__ = [
    "MIGRATION",
    "MUTATION_STATES_0008",
    "OUTBOX_STATES_0008",
    "AUDIT_STAGES_0008",
    "EXECUTION_ERROR_CLASSES",
]

#: Zustandsvorrat ab 0008 — die Menge aus 0007 plus genau einem Zustand.
MUTATION_STATES_0008: tuple[str, ...] = (
    *MUTATION_STATES_0007, "manually_resolved_applied",
)

#: Outbox-Zustände, unverändert gegenüber 0004.
OUTBOX_STATES_0008: tuple[str, ...] = (
    "pending", "claimed", "succeeded", "failed_before_send",
    "outcome_unknown", "abandoned",
)

#: Auditstufen — wortgleich mit `personaljarvis.base.audit.AuditStage.ALL`
#: plus den beiden Stufen des App-Kanals. Der Statiktest hält beide Listen
#: deckungsgleich; hier steht die Datenbankwahrheit.
AUDIT_STAGES_0008: tuple[str, ...] = (
    "mutation_prepared", "approval_requested", "approval_granted",
    "approval_rejected", "approval_expired", "approval_cancelled",
    "execution_claimed", "provider_send_started", "provider_result_received",
    "failed_before_send", "outcome_unknown", "reconcile_started",
    "reconcile_succeeded", "manual_decision_required",
    "mutation_outcome_manually_resolved", "mutation_completed",
    "execution_order_issued", "mutation_settled",
)

#: Geschlossene Fehlerklassen des Transportkanals (ADR-0020 §9).
EXECUTION_ERROR_CLASSES: tuple[str, ...] = (
    # vor Sendebeginn
    "invalid_claim", "expired_claim_before_send", "digest_mismatch",
    "schema_mismatch", "capability_denied", "not_authorized",
    "target_not_found", "revision_conflict", "invalid_payload",
    "unsupported_field", "container_unavailable", "write_stack_unavailable",
    "provider_channel_disabled_before_send",
    # nach Sendebeginn
    "provider_exception", "provider_save_error", "readback_failed",
    "response_lost", "app_process_crash", "backend_unreachable_for_settle",
)


def _in(werte: tuple[str, ...]) -> str:
    return "(" + ",".join(f"'{w}'" for w in werte) + ")"


_STATEMENTS: tuple[str, ...] = (
    # ── 1. Outbox: Transportzustand des einen Versuchs ──────────────────────
    f"""
    CREATE TABLE personal_external_action_outbox_0008 (
        outbox_id                 TEXT NOT NULL PRIMARY KEY,
        module                    TEXT NOT NULL,
        operation                 TEXT NOT NULL,
        subject_type              TEXT NOT NULL,
        subject_id                TEXT NOT NULL,
        approval_id               TEXT NOT NULL
                                  REFERENCES personal_approvals(approval_id)
                                  ON DELETE RESTRICT,
        idempotency_key           TEXT NOT NULL,
        payload_digest            TEXT NOT NULL,
        state                     TEXT NOT NULL,
        attempt_count             INTEGER NOT NULL DEFAULT 0,
        available_at              TEXT NOT NULL,
        claimed_at                TEXT,
        claim_token_digest        TEXT,
        operation_id              TEXT,
        claim_expires_at          TEXT,
        execution_order_issued_at TEXT,
        execution_report_digest   TEXT,
        provider_completed_at     TEXT,
        error_class               TEXT,
        error_digest              TEXT,
        settled_at                TEXT,
        last_error_code           TEXT,
        created_at                TEXT NOT NULL,
        CHECK (length(outbox_id) = 36),
        CHECK (operation <> ''),
        CHECK (idempotency_key <> ''),
        CHECK (state IN {_in(OUTBOX_STATES_0008)}),
        CHECK (attempt_count >= 0),
        -- Ein Claim ohne Bindung waere ein Freibrief: der Ruecklaeufer
        -- liesse sich nicht mehr dem ausgegebenen Auftrag zuordnen.
        CHECK (state <> 'claimed' OR claim_token_digest IS NOT NULL),
        CHECK (claim_token_digest IS NULL OR length(claim_token_digest) = 64),
        CHECK (execution_report_digest IS NULL
               OR length(execution_report_digest) = 64),
        CHECK (operation_id IS NULL OR length(operation_id) = 36),
        -- Zeitliche Invarianten, soweit SQLite sie sicher ausdruecken kann
        -- (ISO-8601-Zeichenketten in UTC sind lexikografisch vergleichbar).
        CHECK (claim_expires_at IS NULL OR claimed_at IS NULL
               OR claim_expires_at > claimed_at),
        CHECK (execution_order_issued_at IS NULL OR claimed_at IS NULL
               OR execution_order_issued_at >= claimed_at),
        -- Bewusst KEIN "Auftrag setzt Token voraus": Beim Abschluss wird
        -- der verbrauchte Token-Digest geleert, waehrend der Ausgabezeitpunkt
        -- als Historie stehen bleibt — genau so soll es sein. Die Bindung
        -- waehrend des Claims sichert der Zustands-CHECK oben.
        CHECK (error_class IS NULL OR error_class IN {_in(EXECUTION_ERROR_CLASSES)}),
        CHECK (error_digest IS NULL OR length(error_digest) = 64)
    ) STRICT
    """,
    # Der Klartext-Token wird bewusst NICHT uebernommen. Ein laufender Claim
    # ueberlebt eine Migration nicht (der haltende Prozess ist gestoppt);
    # der Zustand bleibt erhalten und faellt in den Wiederanlauf.
    """
    INSERT INTO personal_external_action_outbox_0008 (
        outbox_id, module, operation, subject_type, subject_id, approval_id,
        idempotency_key, payload_digest, state, attempt_count, available_at,
        claimed_at, settled_at, last_error_code, created_at
    )
    SELECT
        outbox_id, module, operation, subject_type, subject_id, approval_id,
        idempotency_key, payload_digest, state, attempt_count, available_at,
        claimed_at, settled_at, last_error_code, created_at
    FROM personal_external_action_outbox
    """,
    "DROP TABLE personal_external_action_outbox",
    "ALTER TABLE personal_external_action_outbox_0008 "
    "RENAME TO personal_external_action_outbox",
    "CREATE UNIQUE INDEX ux_outbox_subject ON personal_external_action_outbox "
    "(subject_type, subject_id)",
    "CREATE UNIQUE INDEX ux_outbox_idempotency ON personal_external_action_outbox "
    "(module, idempotency_key)",
    # Eine `operation_id` bezeichnet genau einen Ausfuehrungsversuch.
    "CREATE UNIQUE INDEX ux_outbox_operation ON personal_external_action_outbox "
    "(operation_id)",
    "CREATE INDEX ix_outbox_state ON personal_external_action_outbox (state)",

    # ── 2. Mutationen: manually_resolved_applied ────────────────────────────
    f"""
    CREATE TABLE contacts_mutations_0008 (
        mutation_id                TEXT NOT NULL PRIMARY KEY,
        command                    TEXT NOT NULL,
        correlation_id             TEXT NOT NULL,
        actor                      TEXT NOT NULL,
        initiation_context         TEXT NOT NULL,
        workspace_id               TEXT NOT NULL,
        provider_account_id        TEXT NOT NULL,
        container_identifier       TEXT,
        target_contact_id          TEXT,
        target_provider_identifier TEXT,
        expected_revision          TEXT,
        idempotency_key            TEXT NOT NULL,
        approval_id                TEXT,
        outbox_id                  TEXT,
        audit_id                   TEXT,
        transaction_author         TEXT NOT NULL,
        payload_json               TEXT NOT NULL,
        payload_digest             TEXT NOT NULL,
        preview_digest             TEXT,
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
        CHECK (state IN {_in(MUTATION_STATES_0008)}),
        CHECK (outcome IS NULL
               OR outcome IN ('succeeded','failed','outcome_unknown')),
        CHECK (command <> 'create' OR container_identifier IS NOT NULL),
        CHECK (command = 'create' OR target_provider_identifier IS NOT NULL),
        CHECK (readback_digest IS NULL
               OR state IN ('provider_applied_pending_reconcile','succeeded'))
    ) STRICT
    """,
    """
    INSERT INTO contacts_mutations_0008 (
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
        payload_json, payload_digest, preview_digest, readback_digest,
        state, outcome, attempt_count, last_error_code, created_at,
        approved_at, execution_started_at, completed_at
    FROM contacts_mutations
    """,
    "DROP TABLE contacts_mutations",
    "ALTER TABLE contacts_mutations_0008 RENAME TO contacts_mutations",
    "CREATE UNIQUE INDEX ux_mutations_idempotency ON contacts_mutations "
    "(provider_account_id, idempotency_key)",
    "CREATE INDEX ix_mutations_state ON contacts_mutations (state)",
    "CREATE INDEX ix_mutations_target ON contacts_mutations (target_contact_id)",
    "CREATE INDEX ix_mutations_provider_target ON contacts_mutations "
    "(provider_account_id, target_provider_identifier)",
    "CREATE INDEX ix_mutations_correlation ON contacts_mutations (correlation_id)",

    # ── 3. Auditkette: geschlossene Stufenmenge in der Datenbank ────────────
    f"""
    CREATE TABLE personal_audit_log_0008 (
        audit_id     TEXT    NOT NULL PRIMARY KEY,
        sequence     INTEGER NOT NULL,
        occurred_at  TEXT    NOT NULL,
        module       TEXT    NOT NULL,
        stage        TEXT    NOT NULL,
        subject_type TEXT    NOT NULL,
        subject_id   TEXT,
        payload_hash TEXT    NOT NULL,
        prev_hash    TEXT,
        CHECK (sequence > 0),
        CHECK (stage IN {_in(AUDIT_STAGES_0008)}),
        CHECK (module <> ''),
        CHECK (payload_hash <> '')
    ) STRICT
    """,
    """
    INSERT INTO personal_audit_log_0008 (
        audit_id, sequence, occurred_at, module, stage, subject_type,
        subject_id, payload_hash, prev_hash
    )
    SELECT
        audit_id, sequence, occurred_at, module, stage, subject_type,
        subject_id, payload_hash, prev_hash
    FROM personal_audit_log
    """,
    "DROP TABLE personal_audit_log",
    "ALTER TABLE personal_audit_log_0008 RENAME TO personal_audit_log",
    "CREATE UNIQUE INDEX ux_audit_sequence ON personal_audit_log (sequence)",
    "CREATE INDEX ix_audit_subject ON personal_audit_log "
    "(subject_type, subject_id)",
)

MIGRATION = Migration(
    migration_id="0008",
    module_owner="contacts",
    description=(
        "Transportzustand des App-Prozess-Mutationskanals (operation_id, "
        "claim_token_digest statt Klartext, Verfall, Auftragsausgabe, "
        "Report-Digest, Fehlerklasse); Zustand manually_resolved_applied; "
        "geschlossene Auditstufen in der Datenbank"
    ),
    statements=_STATEMENTS,
    schema_version=8,
    depends_on=("0007",),
)
