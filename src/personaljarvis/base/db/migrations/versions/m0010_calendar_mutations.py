"""Migration 0010 — Kalender-Mutationsvorgänge (Eigentümer: `calendar`).

Block B3 P1 bringt den ersten Schreibpfad des Kalendermoduls: `create` über
den App-Prozess-Kanal, nach demselben Claim-Settle-Muster wie die Kontakte.
Freigaben, Outbox und Audit sind die **bestehenden** Basistabellen; neu ist
ausschliesslich der Vorgang selbst.

Zustandsvorrat (verbindlich):

```
prepared → approved → executing → provider_applied_pending_reconcile → succeeded
        ↘ cancelled ↙          ↘ failed_before_send
                                ↘ outcome_unknown
```

`failed_before_send` heisst „nachweislich nichts übergeben" und ist terminal;
`outcome_unknown` heisst „möglicherweise gesendet" und hat in P1 **keinen**
automatischen Rückweg — dort wartet der Vorgang auf einen späteren Abgleich.

Drei Spalten sind Rücknahme- und Beweisinformation, keine Fachdaten:

* `event_identifier` — die vom Provider erzeugte Kennung. Ohne sie gäbe es
  nach dem Create keinen Weg zurück zu genau diesem Termin.
* `rollback_hint_json` — die maschinenlesbare Rücknahmeanweisung
  (`{"undo":"delete","event_identifier":...}`), gesetzt erst nach belegter
  Providerwirkung.
* `base_fingerprint`/`preimage_json` — reserviert für `update`/`delete`
  (P2/P3): erwarteter Vorzustand und Vorbild. In P1 bleiben sie NULL; die
  Spalten stehen hier, weil eine veröffentlichte Migration unveränderlich
  ist und der Vertrag der Positionen bereits feststeht.
"""

from __future__ import annotations

from personaljarvis.base.db.migrations.ledger import Migration

__all__ = ["MIGRATION", "CALENDAR_MUTATION_STATES"]

#: Kanonischer Zustandsvorrat eines Kalender-Mutationsvorgangs.
CALENDAR_MUTATION_STATES: tuple[str, ...] = (
    "prepared", "approved", "cancelled", "executing",
    "provider_applied_pending_reconcile", "failed_before_send",
    "outcome_unknown", "succeeded",
)


def _in(werte: tuple[str, ...]) -> str:
    return "(" + ",".join(f"'{w}'" for w in werte) + ")"


_STATEMENTS: tuple[str, ...] = (
    f"""
    CREATE TABLE calendar_mutations (
        mutation_id                 TEXT NOT NULL PRIMARY KEY,
        command                     TEXT NOT NULL,
        state                       TEXT NOT NULL,
        payload_json                TEXT NOT NULL,
        payload_digest              TEXT NOT NULL,
        preview_json                TEXT NOT NULL,
        preview_digest              TEXT NOT NULL,
        approval_id                 TEXT NOT NULL
                                    REFERENCES personal_approvals(approval_id)
                                    ON DELETE RESTRICT,
        outbox_id                   TEXT NOT NULL,
        target_provider_calendar_id TEXT NOT NULL,
        event_identifier            TEXT,
        base_fingerprint            TEXT,
        preimage_json               TEXT,
        readback_digest             TEXT,
        rollback_hint_json          TEXT,
        outcome                     TEXT,
        last_error_code             TEXT,
        created_at                  TEXT NOT NULL,
        execution_started_at        TEXT,
        completed_at                TEXT,
        attempt_count               INTEGER NOT NULL DEFAULT 0,
        CHECK (length(mutation_id) = 36),
        CHECK (command IN ('create','update','delete')),
        CHECK (state IN {_in(CALENDAR_MUTATION_STATES)}),
        CHECK (payload_digest <> ''),
        CHECK (preview_digest <> ''),
        CHECK (target_provider_calendar_id <> ''),
        CHECK (attempt_count >= 0),
        CHECK (outcome IS NULL
               OR outcome IN ('succeeded','failed','outcome_unknown')),
        CHECK (readback_digest IS NULL OR length(readback_digest) = 64),
        -- Ein Read-back-Beleg existiert nur bei bewiesener Providerwirkung.
        CHECK (readback_digest IS NULL
               OR state IN ('provider_applied_pending_reconcile','succeeded')),
        -- Ein create hat vor der Ausführung keine Terminkennung; update und
        -- delete brauchen sie von Anfang an (P2/P3).
        CHECK (command = 'create' OR event_identifier IS NOT NULL)
    ) STRICT
    """,
    "CREATE INDEX ix_calendar_mutations_state ON calendar_mutations (state)",
    "CREATE INDEX ix_calendar_mutations_target ON calendar_mutations "
    "(target_provider_calendar_id)",
    "CREATE INDEX ix_calendar_mutations_event ON calendar_mutations "
    "(event_identifier)",
)

MIGRATION = Migration(
    migration_id="0010",
    module_owner="calendar",
    description="Kalender-Mutationsvorgänge für den App-Prozess-Kanal (P1: create)",
    statements=_STATEMENTS,
    schema_version=10,
    depends_on=("0004", "0008", "0009"),
)
