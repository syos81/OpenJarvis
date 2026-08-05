"""Migration 0009 — Kalender-Schema (Eigentümer: `calendar`).

Setzt die in 16 §2 bereits benannten Entitäten um (`calendars`, `events`,
`event_attendees`, `event_external_ids`, Tombstones) und füllt sie nach dem
Entwurf des Fundament-Spikes §7 aus. Kein vereinfachtes MVP-Schema.

Vier Regeln, die im Schema **strukturell** verankert sind und deshalb von
keinem Codepfad umgangen werden können:

* **Die Wiederholungsregel wird roh gespeichert; Instanzen sind abgeleitet.**
  Es gibt keine Tabelle materialisierter Vorkommen. 9 von 16 Terminen im
  gemessenen Fenster waren Serien — das ist der Normalfall, nicht der
  Sonderfall, und ein Cache darf nie zur Wahrheit werden.
* **`time_zone` darf NULL sein und heisst dann „schwebend".** Ganztägige und
  schwebende Termine haben keine Zone. Eine NOT-NULL-Spalte hätte erzwungen,
  eine zu erfinden — und der Termin wäre beim nächsten Ortswechsel verrutscht.
  12 von 16 Terminen im gemessenen Fenster hatten keine Zone.
* **`external_uid` ist ausdrücklich NICHT eindeutig.** Bei Einladungen liegt
  derselbe Termin in mehreren Kalendern. Eindeutig ist allein das Tripel
  (provider_account, provider_calendar, provider_event) in
  `event_external_ids`.
* **`is_writable` ist Provider-Wahrheit, nicht Politik.** Geburtstags- und
  Abonnementkalender melden `0`; das Modul überstimmt das nie. Der
  Geburtstagskalender ist zusätzlich eine Projektion des Kontaktmoduls — wer
  einen Geburtstag ändern will, ändert den Kontakt.

Die Löschsemantik steht in `calendar_sync_windows`: ein Tombstone entsteht nur,
wenn der Kalender in einem Lauf **vollständig** gelesen wurde, das Fenster
**unverändert** war und der Termin **im Fenster** lag. Deshalb ist das zuletzt
vollständig beobachtete Fenster hier eine gespeicherte Tatsache und keine
Annahme des Codes.
"""

from __future__ import annotations

from personaljarvis.base.db.migrations.ledger import Migration

__all__ = ["MIGRATION"]

_CALENDAR_TYPES = "('local','calDAV','exchange','subscription','birthday','unknown')"
_EVENT_STATUS = "('none','confirmed','tentative','canceled','unknown')"
_AVAILABILITY = "('busy','free','tentative','unavailable','not_supported','unknown')"
_PARTICIPANT_STATUS = (
    "('unknown','pending','accepted','declined','tentative','delegated',"
    "'completed','in_process')"
)
_PARTICIPANT_ROLE = "('unknown','required','optional','chair','non_participant')"
_SYNC_STATES = (
    "('in_sync','local_pending','remote_pending','conflicted','attention_required')"
)

_STATEMENTS: tuple[str, ...] = (
    # ── Kalender ────────────────────────────────────────────────────────────
    f"""
    CREATE TABLE calendars (
        id                   TEXT NOT NULL PRIMARY KEY,
        workspace_id         TEXT NOT NULL,
        provider_account_id  TEXT NOT NULL,
        provider_calendar_id TEXT NOT NULL,
        display_name         TEXT NOT NULL,
        calendar_type        TEXT NOT NULL,
        source_identifier    TEXT,
        source_title         TEXT,
        source_type          TEXT,
        color                TEXT,
        is_writable          INTEGER NOT NULL DEFAULT 0,
        is_subscribed        INTEGER NOT NULL DEFAULT 0,
        is_immutable         INTEGER NOT NULL DEFAULT 0,
        supports_events      INTEGER NOT NULL DEFAULT 1,
        sync_enabled         INTEGER NOT NULL DEFAULT 1,
        first_seen_at        TEXT NOT NULL,
        last_seen_at         TEXT NOT NULL,
        created_at           TEXT NOT NULL,
        updated_at           TEXT NOT NULL,
        deleted_at           TEXT,
        is_tombstone         INTEGER NOT NULL DEFAULT 0,
        CHECK (length(id) = 36),
        CHECK (display_name <> ''),
        CHECK (provider_calendar_id <> ''),
        CHECK (calendar_type IN {_CALENDAR_TYPES}),
        CHECK (is_writable IN (0,1)),
        CHECK (is_subscribed IN (0,1)),
        CHECK (is_immutable IN (0,1)),
        CHECK (supports_events IN (0,1)),
        CHECK (sync_enabled IN (0,1)),
        CHECK (is_tombstone IN (0,1)),
        CHECK (is_tombstone = 0 OR deleted_at IS NOT NULL)
    ) STRICT
    """,
    "CREATE UNIQUE INDEX ux_calendars_provider ON calendars "
    "(provider_account_id, provider_calendar_id)",
    "CREATE INDEX ix_calendars_workspace ON calendars (workspace_id, is_tombstone)",

    # ── Termine ─────────────────────────────────────────────────────────────
    #
    # `recurrence_rule_raw` ist ein JSON-Text: EventKit gibt keinen
    # RFC-5545-String heraus, und die Bestandteile zu deuten wäre genau die
    # Fachlogik, die im Sidecar verboten ist. Gespeichert wird, was der
    # Provider sagt — ausgewertet wird später und andernorts.
    #
    # `field_digest` ist die Änderungserkennung. Bewusst NICHT
    # `last_modified_at`: der Zeitstempel kommt vom Server und ist bei CalDAV
    # nicht verlässlich. Der Digest ist lokal und ehrlich.
    f"""
    CREATE TABLE events (
        id                   TEXT NOT NULL PRIMARY KEY,
        calendar_id          TEXT NOT NULL REFERENCES calendars(id) ON DELETE CASCADE,
        title                TEXT,
        notes                TEXT,
        location             TEXT,
        url                  TEXT,
        starts_at_utc        TEXT NOT NULL,
        ends_at_utc          TEXT NOT NULL,
        time_zone            TEXT,
        is_all_day           INTEGER NOT NULL DEFAULT 0,
        status               TEXT NOT NULL DEFAULT 'none',
        availability         TEXT NOT NULL DEFAULT 'unknown',
        recurrence_rule_raw  TEXT,
        recurrence_rule_count INTEGER NOT NULL DEFAULT 0,
        series_id            TEXT,
        is_detached          INTEGER NOT NULL DEFAULT 0,
        occurrence_start_utc TEXT,
        has_alarms           INTEGER NOT NULL DEFAULT 0,
        alarms_raw           TEXT,
        has_attendees        INTEGER NOT NULL DEFAULT 0,
        provider_created_at  TEXT,
        provider_modified_at TEXT,
        field_digest         TEXT NOT NULL,
        sync_state           TEXT NOT NULL DEFAULT 'in_sync',
        first_seen_at        TEXT NOT NULL,
        last_seen_at         TEXT NOT NULL,
        created_at           TEXT NOT NULL,
        updated_at           TEXT NOT NULL,
        deleted_at           TEXT,
        is_tombstone         INTEGER NOT NULL DEFAULT 0,
        CHECK (length(id) = 36),
        CHECK (starts_at_utc <> ''),
        CHECK (ends_at_utc <> ''),
        CHECK (is_all_day IN (0,1)),
        CHECK (is_detached IN (0,1)),
        CHECK (has_alarms IN (0,1)),
        CHECK (has_attendees IN (0,1)),
        CHECK (is_tombstone IN (0,1)),
        CHECK (status IN {_EVENT_STATUS}),
        CHECK (availability IN {_AVAILABILITY}),
        CHECK (sync_state IN {_SYNC_STATES}),
        CHECK (field_digest <> ''),
        CHECK (is_tombstone = 0 OR deleted_at IS NOT NULL),
        -- Eine abgeloeste Instanz MUSS ihren urspruenglichen Beginn kennen,
        -- sonst ist sie ihrer Serie nicht mehr zuzuordnen.
        CHECK (is_detached = 0 OR occurrence_start_utc IS NOT NULL)
    ) STRICT
    """,
    "CREATE INDEX ix_events_calendar_window ON events "
    "(calendar_id, starts_at_utc, is_tombstone)",
    "CREATE INDEX ix_events_window ON events (starts_at_utc, ends_at_utc)",
    "CREATE INDEX ix_events_series ON events (series_id)",
    "CREATE INDEX ix_events_sync_state ON events (sync_state)",

    # ── Providerbindung ─────────────────────────────────────────────────────
    #
    # Eindeutig ist das TRIPEL. `external_uid` (die CalDAV-UID) steht daneben
    # in einer ausdruecklich NICHT eindeutigen Spalte: sie beantwortet „ist das
    # derselbe Termin wie der in deinem Kalender?", nicht „welcher Datensatz
    # ist das?".
    """
    CREATE TABLE event_external_ids (
        event_id             TEXT NOT NULL REFERENCES events(id) ON DELETE CASCADE,
        provider_account_id  TEXT NOT NULL,
        provider_calendar_id TEXT NOT NULL,
        provider_event_id    TEXT NOT NULL,
        calendar_item_id     TEXT,
        external_uid         TEXT,
        first_seen_at        TEXT NOT NULL,
        last_seen_at         TEXT NOT NULL,
        PRIMARY KEY (provider_account_id, provider_calendar_id, provider_event_id),
        CHECK (provider_event_id <> '')
    ) STRICT
    """,
    "CREATE INDEX ix_event_external_event ON event_external_ids (event_id)",
    # Bewusst KEIN UNIQUE: dieselbe UID darf mehrfach vorkommen.
    "CREATE INDEX ix_event_external_uid ON event_external_ids (external_uid)",

    # ── Teilnehmer ──────────────────────────────────────────────────────────
    #
    # `contact_id` ist NULLABLE und bleibt es. Die Zuordnung zu einem Kontakt
    # ist ein spaeterer, eigener Schritt und laeuft NIE ueber Namensaehnlichkeit
    # — dieselbe Regel wie beim Kontakt-Abgleich. Bis dahin traegt der Datensatz
    # die Rohadresse und sonst nichts.
    f"""
    CREATE TABLE event_attendees (
        id                 TEXT NOT NULL PRIMARY KEY,
        event_id           TEXT NOT NULL REFERENCES events(id) ON DELETE CASCADE,
        contact_id         TEXT,
        raw_address        TEXT,
        display_name       TEXT,
        role               TEXT NOT NULL DEFAULT 'unknown',
        participant_status TEXT NOT NULL DEFAULT 'unknown',
        participant_type   TEXT NOT NULL DEFAULT 'unknown',
        is_organizer       INTEGER NOT NULL DEFAULT 0,
        is_current_user    INTEGER NOT NULL DEFAULT 0,
        created_at         TEXT NOT NULL,
        updated_at         TEXT NOT NULL,
        CHECK (length(id) = 36),
        CHECK (is_organizer IN (0,1)),
        CHECK (is_current_user IN (0,1)),
        CHECK (role IN {_PARTICIPANT_ROLE}),
        CHECK (participant_status IN {_PARTICIPANT_STATUS}),
        -- Ein Teilnehmer ohne jede Kennung waere ein leerer Datensatz.
        CHECK (raw_address IS NOT NULL OR display_name IS NOT NULL)
    ) STRICT
    """,
    "CREATE INDEX ix_event_attendees_event ON event_attendees (event_id)",
    "CREATE INDEX ix_event_attendees_contact ON event_attendees (contact_id)",

    # ── Fensterwahrheit ─────────────────────────────────────────────────────
    #
    # Die Transaktionsgrenze ist der KALENDER, nicht der Lauf: ein
    # abgebrochener Lauf hinterlaesst vollstaendig verarbeitete Kalender und
    # unberuehrte — nie halb verarbeitete. Deshalb steht das zuletzt
    # vollstaendig beobachtete Fenster je Kalender hier.
    #
    # Ohne diese Tabelle waere die Tombstone-Regel nicht erfuellbar: „nicht
    # gesehen" ist ohne Fensterangabe nicht von „geloescht" zu unterscheiden.
    """
    CREATE TABLE calendar_sync_windows (
        calendar_id            TEXT NOT NULL PRIMARY KEY
                               REFERENCES calendars(id) ON DELETE CASCADE,
        window_start_utc       TEXT NOT NULL,
        window_end_utc         TEXT NOT NULL,
        last_complete_run_at   TEXT NOT NULL,
        last_run_event_count   INTEGER NOT NULL DEFAULT 0,
        CHECK (window_start_utc < window_end_utc)
    ) STRICT
    """,

    # ── Tombstones ──────────────────────────────────────────────────────────
    #
    # Ein Tombstone haelt fest, unter WELCHEM Fenster die Loeschung abgeleitet
    # wurde. Ohne diese Angabe waere spaeter nicht mehr pruefbar, ob die
    # Ableitung zulaessig war.
    """
    CREATE TABLE event_tombstones (
        provider_account_id  TEXT NOT NULL,
        provider_calendar_id TEXT NOT NULL,
        provider_event_id    TEXT NOT NULL,
        event_id             TEXT,
        deleted_at           TEXT NOT NULL,
        observed_window_start_utc TEXT NOT NULL,
        observed_window_end_utc   TEXT NOT NULL,
        PRIMARY KEY (provider_account_id, provider_calendar_id, provider_event_id)
    ) STRICT
    """,
    "CREATE INDEX ix_event_tombstones_event ON event_tombstones (event_id)",

    # ── Laufprotokoll ───────────────────────────────────────────────────────
    #
    # Jeder Lauf nennt sein Fenster; ein Bericht ohne Fensterangabe ist
    # wertlos. `complete` unterscheidet die Laeufe, aus denen ueberhaupt eine
    # Loeschung folgen darf, von denen, aus denen nichts folgt.
    """
    CREATE TABLE calendar_sync_runs (
        id                 TEXT NOT NULL PRIMARY KEY,
        provider_account_id TEXT NOT NULL,
        started_at         TEXT NOT NULL,
        finished_at        TEXT,
        window_start_utc   TEXT NOT NULL,
        window_end_utc     TEXT NOT NULL,
        calendars_total    INTEGER NOT NULL DEFAULT 0,
        calendars_complete INTEGER NOT NULL DEFAULT 0,
        events_seen        INTEGER NOT NULL DEFAULT 0,
        events_created     INTEGER NOT NULL DEFAULT 0,
        events_updated     INTEGER NOT NULL DEFAULT 0,
        events_unchanged   INTEGER NOT NULL DEFAULT 0,
        events_tombstoned  INTEGER NOT NULL DEFAULT 0,
        window_changed     INTEGER NOT NULL DEFAULT 0,
        outcome            TEXT,
        CHECK (length(id) = 36),
        CHECK (window_changed IN (0,1)),
        CHECK (outcome IS NULL OR outcome IN ('completed','partial','failed'))
    ) STRICT
    """,
    "CREATE INDEX ix_calendar_sync_runs_started ON calendar_sync_runs (started_at)",
)

MIGRATION = Migration(
    migration_id="0009",
    module_owner="calendar",
    description="Kanonisches Kalender-Schema",
    statements=_STATEMENTS,
    schema_version=9,
    depends_on=("0008",),
)
