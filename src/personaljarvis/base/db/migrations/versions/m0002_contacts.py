"""Migration 0002 — Kontakte-Schema (Eigentümer: `contacts`).

Setzt das normative Datenmodell aus `docs/personal-jarvis/modules/contacts.md`
§5 um. Kein vereinfachtes MVP-Schema.

Zwei Regeln, die im Schema strukturell verankert sind:

* **Notizen sind kein Fachfeld.** Es gibt keine Spalte `note`. Der Zustand des
  Feldes lebt ausschließlich in `contact_field_availability` und ist dort für
  `note` dauerhaft `unavailable_by_capability` (08 §4). Damit kann kein
  Codepfad eine nicht lesbare Notiz als leer speichern.
* **Thumbnails sind Metadaten plus Referenz.** Die Binärdaten gehören in den
  Blob-Store (06 §2); die Datenbank hält nur `thumbnail_blob_ref`.
"""

from __future__ import annotations

from personaljarvis.base.db.migrations.ledger import Migration

__all__ = ["MIGRATION"]

_CONTACT_TYPES = "('person','organization')"
_AVAILABILITY = "('present','absent','unavailable_by_capability')"
_SYNC_STATES = (
    "('in_sync','local_pending','remote_pending','conflicted','attention_required')"
)
_MUTATION_STATES = (
    "('draft','validated','previewed','pending_approval','approved','executing',"
    "'verifying','completed','failed','outcome_unknown','reconcile_required',"
    "'manual_decision_required','denied','expired','aborted')"
)
_MUTATION_OUTCOMES = "('succeeded','failed','outcome_unknown')"
_SYNC_MODES = "('delta','full_diff_required')"
_CIRCUIT_STATES = "('closed','open','half_open','reauth_required')"
_COMPLETENESS = "('full','partial')"

_STATEMENTS: tuple[str, ...] = (
    # ── Kontakte ────────────────────────────────────────────────────────────
    f"""
    CREATE TABLE contacts (
        id                    TEXT NOT NULL PRIMARY KEY,
        workspace_id          TEXT NOT NULL,
        contact_type          TEXT NOT NULL,
        given_name            TEXT,
        middle_name           TEXT,
        family_name           TEXT,
        previous_family_name  TEXT,
        name_prefix           TEXT,
        name_suffix           TEXT,
        phonetic_given_name   TEXT,
        phonetic_family_name  TEXT,
        nickname              TEXT,
        display_name          TEXT NOT NULL,
        organization_name     TEXT,
        department_name       TEXT,
        job_title             TEXT,
        is_me_card            INTEGER NOT NULL DEFAULT 0,
        birthday_year         INTEGER,
        birthday_month        INTEGER,
        birthday_day          INTEGER,
        image_available       INTEGER NOT NULL DEFAULT 0,
        thumbnail_blob_ref    TEXT,
        field_completeness    TEXT NOT NULL DEFAULT 'full',
        sync_state            TEXT NOT NULL DEFAULT 'in_sync',
        conflict_state        TEXT,
        local_revision        INTEGER NOT NULL DEFAULT 1,
        source_updated_at     TEXT,
        imported_at           TEXT,
        last_seen_at          TEXT,
        last_mutation_id      TEXT,
        last_approval_id      TEXT,
        last_audit_id         TEXT,
        created_at            TEXT NOT NULL,
        updated_at            TEXT NOT NULL,
        deleted_at            TEXT,
        is_tombstone          INTEGER NOT NULL DEFAULT 0,
        CHECK (length(id) = 36),
        CHECK (contact_type IN {_CONTACT_TYPES}),
        CHECK (is_me_card IN (0,1)),
        CHECK (image_available IN (0,1)),
        CHECK (is_tombstone IN (0,1)),
        CHECK (local_revision > 0),
        CHECK (display_name <> ''),
        CHECK (field_completeness IN {_COMPLETENESS}),
        CHECK (sync_state IN {_SYNC_STATES}),
        CHECK (birthday_month IS NULL OR (birthday_month BETWEEN 1 AND 12)),
        CHECK (birthday_day IS NULL OR (birthday_day BETWEEN 1 AND 31)),
        CHECK ((birthday_month IS NULL) = (birthday_day IS NULL)),
        CHECK (is_tombstone = 0 OR deleted_at IS NOT NULL)
    ) STRICT
    """,
    "CREATE INDEX ix_contacts_workspace ON contacts (workspace_id, is_tombstone)",
    "CREATE INDEX ix_contacts_display_name ON contacts (display_name)",
    "CREATE INDEX ix_contacts_updated_at ON contacts (updated_at)",
    "CREATE INDEX ix_contacts_sync_state ON contacts (sync_state)",
    # ── Feldverfügbarkeit: der Ort, der „nicht lesbar" von „leer" trennt ─────
    f"""
    CREATE TABLE contact_field_availability (
        contact_id TEXT NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
        field      TEXT NOT NULL,
        state      TEXT NOT NULL,
        observed_at TEXT NOT NULL,
        PRIMARY KEY (contact_id, field),
        CHECK (state IN {_AVAILABILITY}),
        CHECK (field <> '')
    ) STRICT
    """,
    "CREATE INDEX ix_field_availability_state ON contact_field_availability (state)",
    # ── Externe Identitäten ─────────────────────────────────────────────────
    """
    CREATE TABLE contact_external_ids (
        id                   TEXT NOT NULL PRIMARY KEY,
        contact_id           TEXT NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
        provider_account_id  TEXT NOT NULL,
        container_identifier TEXT NOT NULL,
        provider_identifier  TEXT NOT NULL,
        unified_identifier   TEXT,
        provider_revision    TEXT,
        key_set_version      TEXT NOT NULL,
        last_seen_at         TEXT NOT NULL,
        CHECK (length(id) = 36),
        CHECK (provider_identifier <> '')
    ) STRICT
    """,
    "CREATE UNIQUE INDEX ux_external_provider_identity ON contact_external_ids "
    "(provider_account_id, provider_identifier)",
    "CREATE INDEX ix_external_contact ON contact_external_ids (contact_id)",
    "CREATE INDEX ix_external_container ON contact_external_ids "
    "(provider_account_id, container_identifier)",
    # ── Rollen: Grundlage der UI-Kategorien, rein lokal ──────────────────────
    """
    CREATE TABLE contact_roles (
        contact_id   TEXT NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
        workspace_id TEXT NOT NULL,
        role         TEXT NOT NULL,
        assigned_at  TEXT NOT NULL,
        PRIMARY KEY (contact_id, workspace_id, role),
        CHECK (role <> '')
    ) STRICT
    """,
    "CREATE INDEX ix_contact_roles_role ON contact_roles (workspace_id, role)",
    # ── Gelabelte Mehrfachwerte ─────────────────────────────────────────────
    """
    CREATE TABLE contact_emails (
        id               TEXT NOT NULL PRIMARY KEY,
        contact_id       TEXT NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
        position         INTEGER NOT NULL,
        label_raw        TEXT,
        label_normalized TEXT,
        value_raw        TEXT NOT NULL,
        value_normalized TEXT NOT NULL,
        CHECK (length(id) = 36),
        CHECK (position >= 0),
        CHECK (value_raw <> '')
    ) STRICT
    """,
    "CREATE UNIQUE INDEX ux_contact_emails_value ON contact_emails "
    "(contact_id, value_normalized)",
    "CREATE UNIQUE INDEX ux_contact_emails_position ON contact_emails "
    "(contact_id, position)",
    "CREATE INDEX ix_contact_emails_normalized ON contact_emails (value_normalized)",
    """
    CREATE TABLE contact_phones (
        id                    TEXT NOT NULL PRIMARY KEY,
        contact_id            TEXT NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
        position              INTEGER NOT NULL,
        label_raw             TEXT,
        label_normalized      TEXT,
        value_raw             TEXT NOT NULL,
        value_normalized_e164 TEXT,
        CHECK (length(id) = 36),
        CHECK (position >= 0),
        CHECK (value_raw <> '')
    ) STRICT
    """,
    "CREATE UNIQUE INDEX ux_contact_phones_position ON contact_phones "
    "(contact_id, position)",
    "CREATE INDEX ix_contact_phones_e164 ON contact_phones (value_normalized_e164)",
    """
    CREATE TABLE contact_postal_addresses (
        id               TEXT NOT NULL PRIMARY KEY,
        contact_id       TEXT NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
        position         INTEGER NOT NULL,
        label_raw        TEXT,
        label_normalized TEXT,
        street           TEXT,
        sub_locality     TEXT,
        city             TEXT,
        state            TEXT,
        postal_code      TEXT,
        country          TEXT,
        iso_country_code TEXT,
        CHECK (length(id) = 36),
        CHECK (position >= 0)
    ) STRICT
    """,
    "CREATE UNIQUE INDEX ux_contact_postal_position ON contact_postal_addresses "
    "(contact_id, position)",
    """
    CREATE TABLE contact_dates (
        id               TEXT NOT NULL PRIMARY KEY,
        contact_id       TEXT NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
        position         INTEGER NOT NULL,
        kind             TEXT NOT NULL,
        label_raw        TEXT,
        label_normalized TEXT,
        year             INTEGER,
        month            INTEGER,
        day              INTEGER,
        CHECK (length(id) = 36),
        CHECK (position >= 0),
        CHECK (kind <> ''),
        CHECK (month IS NULL OR (month BETWEEN 1 AND 12)),
        CHECK (day IS NULL OR (day BETWEEN 1 AND 31))
    ) STRICT
    """,
    "CREATE UNIQUE INDEX ux_contact_dates_position ON contact_dates "
    "(contact_id, position)",
    """
    CREATE TABLE contact_urls (
        id               TEXT NOT NULL PRIMARY KEY,
        contact_id       TEXT NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
        position         INTEGER NOT NULL,
        label_raw        TEXT,
        label_normalized TEXT,
        value_raw        TEXT NOT NULL,
        value_normalized TEXT NOT NULL,
        CHECK (length(id) = 36),
        CHECK (position >= 0),
        CHECK (value_raw <> '')
    ) STRICT
    """,
    "CREATE UNIQUE INDEX ux_contact_urls_position ON contact_urls "
    "(contact_id, position)",
    """
    CREATE TABLE contact_social_profiles (
        id               TEXT NOT NULL PRIMARY KEY,
        contact_id       TEXT NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
        position         INTEGER NOT NULL,
        label_raw        TEXT,
        label_normalized TEXT,
        service          TEXT NOT NULL,
        username         TEXT,
        url              TEXT,
        CHECK (length(id) = 36),
        CHECK (position >= 0),
        CHECK (service <> '')
    ) STRICT
    """,
    "CREATE UNIQUE INDEX ux_contact_social_position ON contact_social_profiles "
    "(contact_id, position)",
    """
    CREATE TABLE contact_instant_messages (
        id               TEXT NOT NULL PRIMARY KEY,
        contact_id       TEXT NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
        position         INTEGER NOT NULL,
        label_raw        TEXT,
        label_normalized TEXT,
        service          TEXT NOT NULL,
        username         TEXT NOT NULL,
        CHECK (length(id) = 36),
        CHECK (position >= 0),
        CHECK (service <> ''),
        CHECK (username <> '')
    ) STRICT
    """,
    "CREATE UNIQUE INDEX ux_contact_im_position ON contact_instant_messages "
    "(contact_id, position)",
    # ── Beziehungen: unauflösbarer Bezug bleibt Rohtext ─────────────────────
    """
    CREATE TABLE contact_relations (
        id               TEXT NOT NULL PRIMARY KEY,
        from_contact_id  TEXT NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
        to_contact_id    TEXT REFERENCES contacts(id) ON DELETE SET NULL,
        position         INTEGER NOT NULL,
        relation_type    TEXT NOT NULL,
        label_raw        TEXT,
        target_name_raw  TEXT,
        CHECK (length(id) = 36),
        CHECK (position >= 0),
        CHECK (relation_type <> ''),
        CHECK (from_contact_id <> to_contact_id),
        CHECK (to_contact_id IS NOT NULL OR target_name_raw IS NOT NULL)
    ) STRICT
    """,
    "CREATE UNIQUE INDEX ux_contact_relations_position ON contact_relations "
    "(from_contact_id, position)",
    "CREATE INDEX ix_contact_relations_to ON contact_relations (to_contact_id)",
    # ── Organisationen ──────────────────────────────────────────────────────
    """
    CREATE TABLE organizations (
        id           TEXT NOT NULL PRIMARY KEY,
        workspace_id TEXT NOT NULL,
        name         TEXT NOT NULL,
        created_at   TEXT NOT NULL,
        updated_at   TEXT NOT NULL,
        CHECK (length(id) = 36),
        CHECK (name <> '')
    ) STRICT
    """,
    "CREATE UNIQUE INDEX ux_organizations_name ON organizations (workspace_id, name)",
    """
    CREATE TABLE organization_memberships (
        organization_id TEXT NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
        contact_id      TEXT NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
        role            TEXT,
        confirmed_at    TEXT NOT NULL,
        PRIMARY KEY (organization_id, contact_id)
    ) STRICT
    """,
    "CREATE INDEX ix_org_membership_contact ON organization_memberships (contact_id)",
    # ── Sync-Zustand je (Konto × Container) ─────────────────────────────────
    f"""
    CREATE TABLE contacts_sync_state (
        provider_account_id  TEXT NOT NULL,
        container_identifier TEXT NOT NULL,
        cursor_token         TEXT,
        cursor_taken_at      TEXT,
        last_full_diff_at    TEXT,
        key_set_version      TEXT NOT NULL,
        mode                 TEXT NOT NULL,
        circuit_state        TEXT NOT NULL DEFAULT 'closed',
        updated_at           TEXT NOT NULL,
        PRIMARY KEY (provider_account_id, container_identifier),
        CHECK (mode IN {_SYNC_MODES}),
        CHECK (circuit_state IN {_CIRCUIT_STATES})
    ) STRICT
    """,
    # ── Tombstones: kein Wiederauferstehen (11 §3) ──────────────────────────
    """
    CREATE TABLE contacts_tombstones (
        provider_account_id TEXT NOT NULL,
        provider_identifier TEXT NOT NULL,
        contact_id          TEXT,
        deleted_at          TEXT NOT NULL,
        reason              TEXT NOT NULL,
        retain_until        TEXT,
        PRIMARY KEY (provider_account_id, provider_identifier),
        CHECK (reason <> '')
    ) STRICT
    """,
    "CREATE INDEX ix_tombstones_contact ON contacts_tombstones (contact_id)",
    # ── Mutationen: Vorgangsbindung, Idempotenz, outcome_unknown ────────────
    f"""
    CREATE TABLE contacts_mutations (
        mutation_id            TEXT NOT NULL PRIMARY KEY,
        command                TEXT NOT NULL,
        target_contact_id      TEXT REFERENCES contacts(id) ON DELETE SET NULL,
        target_provider_identifier TEXT,
        provider_account_id    TEXT,
        idempotency_key        TEXT NOT NULL,
        approval_id            TEXT,
        expected_revision      TEXT,
        state                  TEXT NOT NULL,
        outcome                TEXT,
        initiation_context     TEXT NOT NULL,
        created_at             TEXT NOT NULL,
        settled_at             TEXT,
        CHECK (length(mutation_id) = 36),
        CHECK (command <> ''),
        CHECK (idempotency_key <> ''),
        CHECK (state IN {_MUTATION_STATES}),
        CHECK (outcome IS NULL OR outcome IN {_MUTATION_OUTCOMES}),
        CHECK (target_contact_id IS NOT NULL OR target_provider_identifier IS NOT NULL)
    ) STRICT
    """,
    "CREATE UNIQUE INDEX ux_mutations_idempotency ON contacts_mutations "
    "(idempotency_key)",
    "CREATE INDEX ix_mutations_state ON contacts_mutations (state)",
    "CREATE INDEX ix_mutations_target ON contacts_mutations (target_contact_id)",
)

MIGRATION = Migration(
    migration_id="0002",
    module_owner="contacts",
    description="Kanonisches Kontakte-Schema",
    statements=_STATEMENTS,
    schema_version=2,
    depends_on=("0001",),
)
