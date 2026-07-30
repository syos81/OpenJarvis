"""Migration 0005 — technische Auditspur der Lese-Synchronisation.

Anlass: Am 2026-07-30 setzte ein Voll-Diff 116 Kontakte lokal auf gelöscht,
weil eine Enumeration `count=0, complete=true` meldete. Der Vorgang war
hinterher **nicht rekonstruierbar** — `personal_audit_log` speichert nur
Hashes, die Sidecar-Diagnose lebt im Prozess, und die Laufergebnisse existierten
nur als Rückgabewert. Was fehlte, war nicht die Sicherung, sondern die Spur.

Diese Tabellen schliessen genau das. Sie sind **technisch, nicht fachlich**:

* Sie ersetzen `contacts_sync_state` nicht. Der fachliche Zustand — Cursor,
  Modus, Schlüsselsatz — bleibt dort. Hier steht, *was ein Lauf getan hat*.
* Sie tragen keinen Kontaktwert. Kein Name, keine Adresse, keine Nummer, kein
  Provider-Identifier, keine rohe Containerkennung, kein Cursor und kein Token
  — auch kein Hash davon. Containerkennungen erscheinen ausschliesslich als
  `container_ref`, ein nicht zurückrechenbares Kürzel.
* Sie sind additiv. Kein Bestandsschema wird angefasst.

`CHECK`-Bedingungen halten die Wertemengen geschlossen; ein unbekannter
Ausgang oder Modus kann nicht unbemerkt hineingeraten.
"""

from __future__ import annotations

from personaljarvis.base.db.migrations.ledger import Migration

_RUNS = """
CREATE TABLE contacts_sync_audit (
    run_id                 TEXT    NOT NULL PRIMARY KEY,
    workspace_id           TEXT    NOT NULL,
    provider_account_id    TEXT    NOT NULL,
    mode                   TEXT    NOT NULL,
    container_count        INTEGER NOT NULL,
    started_at             TEXT    NOT NULL,
    completed_at           TEXT,
    outcome                TEXT    NOT NULL,
    cursor_before_present  INTEGER NOT NULL,
    cursor_after_present   INTEGER NOT NULL,
    full_diff_required     INTEGER NOT NULL,
    drop_everything_seen   INTEGER NOT NULL,
    suspicious_empty       INTEGER NOT NULL,
    events_total           INTEGER NOT NULL DEFAULT 0,
    events_add             INTEGER NOT NULL DEFAULT 0,
    events_update          INTEGER NOT NULL DEFAULT 0,
    events_delete          INTEGER NOT NULL DEFAULT 0,
    events_other           INTEGER NOT NULL DEFAULT 0,
    imported               INTEGER NOT NULL DEFAULT 0,
    updated                INTEGER NOT NULL DEFAULT 0,
    unchanged              INTEGER NOT NULL DEFAULT 0,
    tombstoned             INTEGER NOT NULL DEFAULT 0,
    reactivated            INTEGER NOT NULL DEFAULT 0,
    error_class            TEXT,
    error_code             TEXT,
    CHECK (mode IN ('initial_import','delta','full_diff','full_diff_account',
                    'recovery')),
    CHECK (outcome IN ('committed','rolled_back','aborted','running')),
    CHECK (cursor_before_present IN (0,1)),
    CHECK (cursor_after_present  IN (0,1)),
    CHECK (full_diff_required    IN (0,1)),
    CHECK (drop_everything_seen  IN (0,1)),
    CHECK (suspicious_empty      IN (0,1)),
    CHECK (container_count >= 0)
) STRICT
"""

_CONTAINERS = """
CREATE TABLE contacts_sync_audit_containers (
    run_id                TEXT    NOT NULL,
    container_ref         TEXT    NOT NULL,
    attempt               INTEGER NOT NULL,
    reported_count        INTEGER NOT NULL,
    received_count        INTEGER NOT NULL,
    complete              INTEGER NOT NULL,
    count_consistent      INTEGER NOT NULL,
    duplicate_identifiers INTEGER NOT NULL DEFAULT 0,
    previous_count        INTEGER NOT NULL DEFAULT 0,
    error_class           TEXT,
    PRIMARY KEY (run_id, container_ref, attempt),
    FOREIGN KEY (run_id) REFERENCES contacts_sync_audit (run_id)
        ON DELETE RESTRICT,
    CHECK (complete         IN (0,1)),
    CHECK (count_consistent IN (0,1)),
    -- `attempt` trägt die Null-Gegenprobe: 1 ist der erste Lauf, 2 die eine
    -- erlaubte Wiederholung. Mehr gibt es nicht.
    CHECK (attempt IN (1,2))
) STRICT
"""

MIGRATION = Migration(
    migration_id="0005",
    module_owner="contacts",
    description=(
        "Technische Auditspur der Lese-Synchronisation: Laufergebnisse und "
        "Enumerationszahlen je Container, PII-frei"
    ),
    statements=(
        _RUNS.strip(),
        _CONTAINERS.strip(),
        "CREATE INDEX ix_sync_audit_konto "
        "ON contacts_sync_audit (provider_account_id, started_at)",
        "CREATE INDEX ix_sync_audit_ausgang "
        "ON contacts_sync_audit (outcome, started_at)",
    ),
    schema_version=5,
    depends_on=("0004",),
)
