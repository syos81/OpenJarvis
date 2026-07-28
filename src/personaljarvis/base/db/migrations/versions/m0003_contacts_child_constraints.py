"""Migration 0003 — Korrektur der Kindtabellen-Constraints (Eigentümer: `contacts`).

Gate-A-Audit 2026-07-28, zwei bestätigte Abweichungen der Migration 0002 vom
normativen Datenmodell (contacts.md §5.1):

1. **ON DELETE war CASCADE statt RESTRICT.** Der Plan verlangt für die sieben
   normalisierten Kindtabellen ausdrücklich RESTRICT: ein harter Löschversuch
   am Elternkontakt soll fail-closed scheitern, solange Kinddaten existieren —
   kein stiller Datenverlust. (Soft-Delete über Tombstones bleibt der einzige
   Produktpfad; das Repository löscht Kinddatensätze bei `update()` weiterhin
   ausdrücklich selbst.)

2. **`ux_contact_emails_value` machte einen gültigen Provider-Zustand
   unspeicherbar.** Apple Kontakte erlaubt denselben Wert unter mehreren
   Labels auf einer Karte (z. B. dieselbe Adresse als „privat" und
   „geschäftlich"); das Wert-Unique hätte den Import einer solchen Karte hart
   scheitern lassen (im Audit reproduziert). Der Doppel-Einfügungs-Schutz
   bleibt über das Positions-Unique erhalten; Wertgleichheit ist Fachlogik
   (Dubletten-Kandidaten), kein Constraint.

Da Migration 0002 veröffentlicht und damit unveränderlich ist (07 §6 Nr. 3),
erfolgt die Korrektur als eigene Vorwärtsmigration: Neuaufbau der sieben
Tabellen mit Datenübernahme. Auf jeder bis dahin existierenden Datenbank sind
diese Tabellen leer; der `INSERT … SELECT` ist dennoch enthalten, damit die
Migration auf jedem Stand korrekt ist.
"""

from __future__ import annotations

from personaljarvis.base.db.migrations.ledger import Migration

__all__ = ["MIGRATION"]

# Spaltendefinitionen wortgleich zu 0002 — einzige Änderung: RESTRICT.
_FK = "TEXT NOT NULL REFERENCES contacts(id) ON DELETE RESTRICT"

_TABLES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    (
        "contact_emails",
        f"""
        id               TEXT NOT NULL PRIMARY KEY,
        contact_id       {_FK},
        position         INTEGER NOT NULL,
        label_raw        TEXT,
        label_normalized TEXT,
        value_raw        TEXT NOT NULL,
        value_normalized TEXT NOT NULL,
        CHECK (length(id) = 36),
        CHECK (position >= 0),
        CHECK (value_raw <> '')
        """,
        (
            "CREATE UNIQUE INDEX ux_contact_emails_position ON contact_emails "
            "(contact_id, position)",
            # ux_contact_emails_value wird bewusst NICHT neu angelegt (Befund 2).
            "CREATE INDEX ix_contact_emails_normalized ON contact_emails "
            "(value_normalized)",
        ),
    ),
    (
        "contact_phones",
        f"""
        id                    TEXT NOT NULL PRIMARY KEY,
        contact_id            {_FK},
        position              INTEGER NOT NULL,
        label_raw             TEXT,
        label_normalized      TEXT,
        value_raw             TEXT NOT NULL,
        value_normalized_e164 TEXT,
        CHECK (length(id) = 36),
        CHECK (position >= 0),
        CHECK (value_raw <> '')
        """,
        (
            "CREATE UNIQUE INDEX ux_contact_phones_position ON contact_phones "
            "(contact_id, position)",
            "CREATE INDEX ix_contact_phones_e164 ON contact_phones "
            "(value_normalized_e164)",
        ),
    ),
    (
        "contact_postal_addresses",
        f"""
        id               TEXT NOT NULL PRIMARY KEY,
        contact_id       {_FK},
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
        """,
        (
            "CREATE UNIQUE INDEX ux_contact_postal_position ON "
            "contact_postal_addresses (contact_id, position)",
        ),
    ),
    (
        "contact_dates",
        f"""
        id               TEXT NOT NULL PRIMARY KEY,
        contact_id       {_FK},
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
        """,
        (
            "CREATE UNIQUE INDEX ux_contact_dates_position ON contact_dates "
            "(contact_id, position)",
        ),
    ),
    (
        "contact_urls",
        f"""
        id               TEXT NOT NULL PRIMARY KEY,
        contact_id       {_FK},
        position         INTEGER NOT NULL,
        label_raw        TEXT,
        label_normalized TEXT,
        value_raw        TEXT NOT NULL,
        value_normalized TEXT NOT NULL,
        CHECK (length(id) = 36),
        CHECK (position >= 0),
        CHECK (value_raw <> '')
        """,
        (
            "CREATE UNIQUE INDEX ux_contact_urls_position ON contact_urls "
            "(contact_id, position)",
        ),
    ),
    (
        "contact_social_profiles",
        f"""
        id               TEXT NOT NULL PRIMARY KEY,
        contact_id       {_FK},
        position         INTEGER NOT NULL,
        label_raw        TEXT,
        label_normalized TEXT,
        service          TEXT NOT NULL,
        username         TEXT,
        url              TEXT,
        CHECK (length(id) = 36),
        CHECK (position >= 0),
        CHECK (service <> '')
        """,
        (
            "CREATE UNIQUE INDEX ux_contact_social_position ON "
            "contact_social_profiles (contact_id, position)",
        ),
    ),
    (
        "contact_instant_messages",
        f"""
        id               TEXT NOT NULL PRIMARY KEY,
        contact_id       {_FK},
        position         INTEGER NOT NULL,
        label_raw        TEXT,
        label_normalized TEXT,
        service          TEXT NOT NULL,
        username         TEXT NOT NULL,
        CHECK (length(id) = 36),
        CHECK (position >= 0),
        CHECK (service <> ''),
        CHECK (username <> '')
        """,
        (
            "CREATE UNIQUE INDEX ux_contact_im_position ON "
            "contact_instant_messages (contact_id, position)",
        ),
    ),
)


def _rebuild(table: str, columns: str, indexes: tuple[str, ...]) -> tuple[str, ...]:
    """Neuaufbau einer referenzierenden (Kind-)Tabelle mit Datenübernahme.

    Der Elterntisch `contacts` bleibt unberührt — der Neuaufbau betrifft nur
    die referenzierende Seite und ist damit unter `PRAGMA foreign_keys=ON`
    transaktionssicher.
    """
    return (
        f"CREATE TABLE {table}_neu ({columns}) STRICT",
        f"INSERT INTO {table}_neu SELECT * FROM {table}",
        f"DROP TABLE {table}",
        f"ALTER TABLE {table}_neu RENAME TO {table}",
        *indexes,
    )


_STATEMENTS: tuple[str, ...] = tuple(
    statement
    for table, columns, indexes in _TABLES
    for statement in _rebuild(table, columns, indexes)
)

MIGRATION = Migration(
    migration_id="0003",
    module_owner="contacts",
    description=(
        "Kindtabellen: ON DELETE RESTRICT statt CASCADE; "
        "E-Mail-Wert-Unique entfernt (gültige Provider-Zustände speicherbar)"
    ),
    statements=_STATEMENTS,
    schema_version=3,
    depends_on=("0002",),
)
