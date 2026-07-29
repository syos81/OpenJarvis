"""Migration 0004 — freigabepflichtige Mutationspipeline (Eigentümer: `base`).

Gate C braucht drei Dinge, die es noch nicht gibt (AV-33: erst jetzt, nicht auf
Vorrat):

1. **Freigaben** (`personal_approvals`) — R1 verlangt einen Datensatz, an den
   Vorschau, Nutzentscheidung und Payload-Digest gebunden sind (10 §3).
2. **ExternalActionOutbox** (`personal_external_action_outbox`) — externe
   Schreiboperationen laufen nie direkt, sondern transaktional über die Outbox
   (11 §1/§3, ADR-0007).
3. **Erweiterte `contacts_mutations`** — die Tabelle aus 0002 kann weder
   Freigabezeitpunkt, Versuchszähler, Digest, Fehlercode noch Audit-/Outbox-
   Bezug speichern, und ihr Zustandsvorrat kennt `failed_before_send` nicht.

Migration 0002 ist veröffentlicht und damit unveränderlich (07 §6 Nr. 3); die
Erweiterung erfolgt als Neuaufbau mit Datenübernahme.

**Zustandsvorrat (verbindlich, präzisiert gegenüber contacts.md §7.2):**

```
prepared → awaiting_approval → approved → executing → succeeded
                             ↘ rejected                ↘ failed_before_send
                             ↘ expired                 ↘ outcome_unknown
                             ↘ cancelled                    ↓
                                                     reconcile_required
                                                       ↙      ↓        ↘
                                                succeeded  failed  manual_decision_required
```

`failed_before_send` und `outcome_unknown` sind bewusst **getrennt**:
Ersteres heißt „nachweislich nichts gesendet", Letzteres „möglicherweise
gesendet". **Beide sind ohne automatischen Rückweg:** `failed_before_send`
ist terminal (ein neuer Versuch ist eine neue freigabepflichtige Mutation),
und aus `outcome_unknown` führt ausschließlich der Abgleich weiter.

**Bekannte, dokumentierte Grenze der Datenübernahme:** Enthielte eine
Vor-0004-Datenbank einen `create`-Vorgang, schlüge der Übertrag am neuen
CHECK (`create` verlangt einen Container) **fail-closed** fehl — die gesamte
Migration rollt atomar zurück, nichts wird beschädigt. Produktiv kann ein
solcher Bestand nicht existieren (bis 0004 gab es keinen Schreibpfad für
Mutationen außerhalb temporärer Testdatenbanken); die Behebung wäre eine
Wiederherstellung bzw. manuelle Bereinigung vor dem Upgrade.

**Zur Ablage der Nutzlast:** `contacts_mutations.payload_json` hält die zur
Ausführung nötige Nutzlast (bei `update` den ausdrücklichen Patch). Ohne sie
liesse sich eine freigegebene, aufgeschobene Mutation nicht ausführen. Sie
liegt in der kanonischen Datenbank, in der die Kontaktdaten ohnehin leben, und
ist **nicht** abfragbarer Kernzustand — jede Abfrage läuft über die
normalisierten Spalten daneben. **Audit und Outbox erhalten ausschließlich den
Digest**, niemals die Nutzlast (10 §5, 12 §1).
"""

from __future__ import annotations

from personaljarvis.base.db.migrations.ledger import Migration

__all__ = ["MIGRATION", "MUTATION_STATES", "APPROVAL_STATES", "OUTBOX_STATES"]

#: Kanonischer Zustandsvorrat einer Mutation.
MUTATION_STATES: tuple[str, ...] = (
    "prepared", "awaiting_approval", "approved", "rejected", "expired",
    "cancelled", "executing", "succeeded", "failed_before_send",
    "outcome_unknown", "reconcile_required", "manual_decision_required",
    "failed",
)

#: Zustandsvorrat einer Freigabe.
APPROVAL_STATES: tuple[str, ...] = (
    "awaiting_approval", "granted", "rejected", "expired", "cancelled",
    "consumed",
)

#: Zustandsvorrat eines Outbox-Eintrags.
OUTBOX_STATES: tuple[str, ...] = (
    "pending", "claimed", "succeeded", "failed_before_send",
    "outcome_unknown", "abandoned",
)


def _in(werte: tuple[str, ...]) -> str:
    return "(" + ",".join(f"'{w}'" for w in werte) + ")"


_STATEMENTS: tuple[str, ...] = (
    # ── Freigaben ───────────────────────────────────────────────────────────
    f"""
    CREATE TABLE personal_approvals (
        approval_id        TEXT NOT NULL PRIMARY KEY,
        module             TEXT NOT NULL,
        subject_type       TEXT NOT NULL,
        subject_id         TEXT NOT NULL,
        risk_class         TEXT NOT NULL,
        initiation_context TEXT NOT NULL,
        actor              TEXT NOT NULL,
        correlation_id     TEXT NOT NULL,
        payload_digest     TEXT NOT NULL,
        preview_digest     TEXT NOT NULL,
        state              TEXT NOT NULL,
        requested_at       TEXT NOT NULL,
        expires_at         TEXT NOT NULL,
        decided_at         TEXT,
        consumed_at        TEXT,
        decision_actor     TEXT,
        CHECK (length(approval_id) = 36),
        CHECK (module <> ''),
        CHECK (subject_id <> ''),
        CHECK (risk_class IN ('R0','R1','R2')),
        CHECK (payload_digest <> ''),
        CHECK (state IN {_in(APPROVAL_STATES)}),
        CHECK (expires_at > requested_at)
    ) STRICT
    """,
    "CREATE UNIQUE INDEX ux_approvals_subject ON personal_approvals "
    "(subject_type, subject_id)",
    "CREATE INDEX ix_approvals_state ON personal_approvals (state)",
    # ── ExternalActionOutbox ────────────────────────────────────────────────
    f"""
    CREATE TABLE personal_external_action_outbox (
        outbox_id       TEXT NOT NULL PRIMARY KEY,
        module          TEXT NOT NULL,
        operation       TEXT NOT NULL,
        subject_type    TEXT NOT NULL,
        subject_id      TEXT NOT NULL,
        approval_id     TEXT NOT NULL REFERENCES personal_approvals(approval_id) ON DELETE RESTRICT,
        idempotency_key TEXT NOT NULL,
        payload_digest  TEXT NOT NULL,
        state           TEXT NOT NULL,
        attempt_count   INTEGER NOT NULL DEFAULT 0,
        available_at    TEXT NOT NULL,
        claimed_at      TEXT,
        claim_token     TEXT,
        settled_at      TEXT,
        last_error_code TEXT,
        created_at      TEXT NOT NULL,
        CHECK (length(outbox_id) = 36),
        CHECK (operation <> ''),
        CHECK (idempotency_key <> ''),
        CHECK (state IN {_in(OUTBOX_STATES)}),
        CHECK (attempt_count >= 0),
        CHECK (state <> 'claimed' OR claim_token IS NOT NULL)
    ) STRICT
    """,
    "CREATE UNIQUE INDEX ux_outbox_subject ON personal_external_action_outbox "
    "(subject_type, subject_id)",
    "CREATE UNIQUE INDEX ux_outbox_idempotency ON personal_external_action_outbox "
    "(module, idempotency_key)",
    "CREATE INDEX ix_outbox_state ON personal_external_action_outbox "
    "(state, available_at)",
    # ── contacts_mutations: Neuaufbau mit Datenübernahme ────────────────────
    f"""
    CREATE TABLE contacts_mutations_neu (
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
        CHECK (state IN {_in(MUTATION_STATES)}),
        CHECK (outcome IS NULL OR outcome IN ('succeeded','failed','outcome_unknown')),
        -- Zielbindung: create braucht einen Container, update/delete eine
        -- stabile Provider-ID. Niemals ein Name, niemals ein Suchergebnis.
        CHECK (command <> 'create' OR container_identifier IS NOT NULL),
        CHECK (command = 'create' OR target_provider_identifier IS NOT NULL)
    ) STRICT
    """,
    # Bestand aus 0002 übernehmen. Auf jeder bis hier existierenden Datenbank
    # ist die Tabelle leer; der Übertrag ist dennoch enthalten, damit die
    # Migration auf jedem Stand korrekt ist. Alte Zustände werden auf den
    # neuen Vorrat abgebildet.
    """
    INSERT INTO contacts_mutations_neu (
        mutation_id, command, correlation_id, actor, initiation_context,
        workspace_id, provider_account_id, container_identifier,
        target_contact_id, target_provider_identifier, expected_revision,
        idempotency_key, approval_id, transaction_author, payload_json,
        payload_digest, preview_digest, state, outcome, created_at, completed_at
    )
    SELECT
        mutation_id,
        CASE WHEN command IN ('create','update','delete') THEN command ELSE 'update' END,
        mutation_id,
        'unbekannt-vor-0004',
        initiation_context,
        'unbekannt-vor-0004',
        COALESCE(provider_account_id, 'unbekannt-vor-0004'),
        NULL,
        target_contact_id,
        COALESCE(target_provider_identifier, 'unbekannt-vor-0004'),
        expected_revision,
        idempotency_key,
        approval_id,
        'de.kluender.jarvis.contacts-bridge',
        '{}',
        'uebernommen-ohne-digest',
        'uebernommen-ohne-digest',
        CASE state
            WHEN 'draft' THEN 'prepared'
            WHEN 'validated' THEN 'prepared'
            WHEN 'previewed' THEN 'prepared'
            WHEN 'pending_approval' THEN 'awaiting_approval'
            WHEN 'denied' THEN 'rejected'
            WHEN 'aborted' THEN 'cancelled'
            WHEN 'verifying' THEN 'executing'
            WHEN 'completed' THEN 'succeeded'
            WHEN 'failed' THEN 'failed_before_send'
            ELSE state
        END,
        outcome, created_at, settled_at
    FROM contacts_mutations
    """,
    "DROP TABLE contacts_mutations",
    "ALTER TABLE contacts_mutations_neu RENAME TO contacts_mutations",
    "CREATE UNIQUE INDEX ux_mutations_idempotency ON contacts_mutations "
    "(provider_account_id, idempotency_key)",
    "CREATE INDEX ix_mutations_state ON contacts_mutations (state)",
    "CREATE INDEX ix_mutations_target ON contacts_mutations (target_contact_id)",
    "CREATE INDEX ix_mutations_provider_target ON contacts_mutations "
    "(provider_account_id, target_provider_identifier)",
    "CREATE INDEX ix_mutations_correlation ON contacts_mutations (correlation_id)",
)

MIGRATION = Migration(
    migration_id="0004",
    module_owner="base",
    description=(
        "Freigaben, ExternalActionOutbox und erweiterte Mutationszustände "
        "für die freigabepflichtige Mutationspipeline"
    ),
    statements=_STATEMENTS,
    schema_version=4,
    depends_on=("0002", "0003"),
)
