"""Migration 0007 — menschlicher Abschluss eines ungewissen Ausgangs.

Der Create-Livetest am 2026-08-01 hat eine Lücke offengelegt, die vorher nur
theoretisch war: Eine Mutation stand auf `outcome_unknown`, der Nutzer hat bei
Apple Contacts nachgesehen und die beabsichtigte Änderung dort **nicht**
gefunden — und es gab keinen Weg, dieses Wissen festzuhalten.

Alle vorhandenen Zustände wären falsch gewesen:

* `failed_before_send` behauptet „nachweislich nichts gesendet". Genau das war
  hier nicht der Fall — der Speicherauftrag war übergeben, der Prozess starb
  dabei. Diesen Zustand zu verwenden hiesse, die Historie umzuschreiben.
* `cancelled` heisst „vor der Ausführung zurückgezogen".
* `failed` entsteht ausschliesslich **nach** einem Abgleich am Provider und
  behauptet damit eine Systembeobachtung, die es hier nicht gibt.
* `succeeded` ist offensichtlich falsch.

Deshalb ein eigener Zustand: **`manually_resolved_not_applied`**. Er sagt
genau, was gilt — *ein Mensch hat den Provider ausserhalb von Jarvis geprüft
und die Änderung dort nicht beobachtet* — und er sagt es als **spätere,
eigene** Aussage. Der historische `outcome_unknown`-Zeitpunkt bleibt in der
Auditkette unverändert stehen: zum Zeitpunkt des technischen Fehlers war das
Ergebnis unbekannt, und das bleibt wahr.

Der Zustand ist **terminal**. Aus ihm führt kein Weg zu einem zweiten Send;
er liegt weder in `NEEDS_RECONCILE` noch in `IN_FLIGHT_STATES`.

**Warum Neuaufbau statt `ALTER TABLE`:** wie bei 0006 — SQLite kann einen
CHECK nicht ändern, und die Zustandsmenge steht in einem. Alle Spalten,
Constraints und Indizes werden wortgleich übernommen; die einzige Änderung ist
der erweiterte Zustands-CHECK.
"""

from __future__ import annotations

from personaljarvis.base.db.migrations.ledger import Migration

__all__ = ["MIGRATION", "MUTATION_STATES_0007"]

#: Zustandsvorrat ab 0007 — die Menge aus 0006 plus genau einem Zustand.
MUTATION_STATES_0007: tuple[str, ...] = (
    "prepared", "awaiting_approval", "approved", "rejected", "expired",
    "cancelled", "executing", "succeeded", "failed_before_send",
    "outcome_unknown", "provider_applied_pending_reconcile",
    "reconcile_required", "manual_decision_required",
    "manually_resolved_not_applied", "failed",
)


def _in(werte: tuple[str, ...]) -> str:
    return "(" + ",".join(f"'{w}'" for w in werte) + ")"


_STATEMENTS: tuple[str, ...] = (
    f"""
    CREATE TABLE contacts_mutations_0007 (
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
        CHECK (state IN {_in(MUTATION_STATES_0007)}),
        CHECK (outcome IS NULL OR outcome IN ('succeeded','failed','outcome_unknown')),
        CHECK (command <> 'create' OR container_identifier IS NOT NULL),
        CHECK (command = 'create' OR target_provider_identifier IS NOT NULL),
        CHECK (readback_digest IS NULL
               OR state IN ('provider_applied_pending_reconcile','succeeded'))
    ) STRICT
    """,
    # Vollstaendige, wertgleiche Uebernahme — der Vorrat waechst, er aendert
    # sich nicht. Kein Zustand wird abgebildet oder umbenannt.
    """
    INSERT INTO contacts_mutations_0007 (
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
    "ALTER TABLE contacts_mutations_0007 RENAME TO contacts_mutations",
    "CREATE UNIQUE INDEX ux_mutations_idempotency ON contacts_mutations "
    "(provider_account_id, idempotency_key)",
    "CREATE INDEX ix_mutations_state ON contacts_mutations (state)",
    "CREATE INDEX ix_mutations_target ON contacts_mutations (target_contact_id)",
    "CREATE INDEX ix_mutations_provider_target ON contacts_mutations "
    "(provider_account_id, target_provider_identifier)",
    "CREATE INDEX ix_mutations_correlation ON contacts_mutations (correlation_id)",
    # ── Containerart je Ablageort ───────────────────────────────────────────
    #
    # Warum sie hierher gehoert: Beim Create-Livetest am 2026-08-01 wurde der
    # Zielcontainer nach seiner Kontaktzahl gewaehlt, weil die Oberflaeche
    # nichts anderes anzuzeigen hatte. Ein Ablageort ist aber nicht durch
    # seine Groesse charakterisiert, sondern durch seine Art — lokal,
    # CardDAV, Exchange. Ohne diese Angabe kann niemand bewusst waehlen, und
    # eine Auswahl nach Reihenfolge oder Groesse ist keine Auswahl.
    #
    # Der Wert kommt aus `containers` und wird beim Synchronisieren
    # mitgeschrieben. `ALTER TABLE ADD COLUMN` genuegt: die Spalte ist neu,
    # nullbar und beruehrt keine Bedingung. Ein Neuaufbau waere hier ein
    # Risiko ohne Gegenwert.
    "ALTER TABLE contacts_sync_state ADD COLUMN container_type TEXT",
)

MIGRATION = Migration(
    migration_id="0007",
    module_owner="contacts",
    description=(
        "Terminaler Zustand manually_resolved_not_applied fuer den "
        "menschlichen Abschluss eines ungewissen Providerausgangs; "
        "Containerart je Ablageort"
    ),
    statements=_STATEMENTS,
    schema_version=7,
    depends_on=("0006",),
)
