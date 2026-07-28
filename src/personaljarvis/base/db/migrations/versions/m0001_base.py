"""Migration 0001 — Basisinfrastruktur (Eigentümer: `base`).

Umfang nach AV-33: **nur** was das Kontakte-Modul in Gate A tatsächlich
braucht. Das ist die Verknüpfungsinfrastruktur aus 06 §5 (ResourceIdentity,
ResourceLink, EntityAlias) und der Audit-Rahmen aus 10 §5. Outboxen,
Approvals und R2-Strukturen entstehen mit den Gates, die sie brauchen.
"""

from __future__ import annotations

from personaljarvis.base.db.migrations.ledger import Migration

__all__ = ["MIGRATION"]

_STATEMENTS: tuple[str, ...] = (
    # ── ResourceIdentity: typisierte kanonische Adresse jeder Entität ────────
    """
    CREATE TABLE personal_resource_identity (
        resource_id   TEXT NOT NULL PRIMARY KEY,
        resource_type TEXT NOT NULL,
        created_at    TEXT NOT NULL,
        CHECK (length(resource_id) = 36),
        CHECK (resource_type <> '')
    ) STRICT
    """,
    # ── ResourceLink: gerichtete typisierte Kante, Eigentümer ist die Basis ──
    """
    CREATE TABLE personal_resource_link (
        link_id          TEXT NOT NULL PRIMARY KEY,
        from_resource_id TEXT NOT NULL REFERENCES personal_resource_identity(resource_id) ON DELETE RESTRICT,
        to_resource_id   TEXT NOT NULL REFERENCES personal_resource_identity(resource_id) ON DELETE RESTRICT,
        link_type        TEXT NOT NULL,
        created_by_module TEXT NOT NULL,
        created_at       TEXT NOT NULL,
        CHECK (from_resource_id <> to_resource_id)
    ) STRICT
    """,
    "CREATE UNIQUE INDEX ux_resource_link ON personal_resource_link "
    "(from_resource_id, to_resource_id, link_type)",
    "CREATE INDEX ix_resource_link_to ON personal_resource_link (to_resource_id)",
    # ── EntityAlias: azyklisch per Konstruktion (06 §5) ──────────────────────
    """
    CREATE TABLE personal_entity_alias (
        old_id       TEXT NOT NULL PRIMARY KEY,
        canonical_id TEXT NOT NULL,
        resource_type TEXT NOT NULL,
        created_at   TEXT NOT NULL,
        CHECK (old_id <> canonical_id)
    ) STRICT
    """,
    "CREATE INDEX ix_entity_alias_canonical ON personal_entity_alias (canonical_id)",
    # ── Audit-Log: append-only, hash-verkettet (10 §5) ───────────────────────
    """
    CREATE TABLE personal_audit_log (
        audit_id     TEXT    NOT NULL PRIMARY KEY,
        sequence     INTEGER NOT NULL,
        occurred_at  TEXT    NOT NULL,
        module       TEXT    NOT NULL,
        stage        TEXT    NOT NULL,
        subject_type TEXT    NOT NULL,
        subject_id   TEXT,
        payload_hash TEXT    NOT NULL,
        prev_hash    TEXT,
        CHECK (sequence > 0)
    ) STRICT
    """,
    "CREATE UNIQUE INDEX ux_audit_sequence ON personal_audit_log (sequence)",
    "CREATE INDEX ix_audit_subject ON personal_audit_log (subject_type, subject_id)",
)

MIGRATION = Migration(
    migration_id="0001",
    module_owner="base",
    description="Verknüpfungsinfrastruktur und Audit-Rahmen",
    statements=_STATEMENTS,
    schema_version=1,
)
