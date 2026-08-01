"""Modulprivate SQLite-Implementierungen der Repository-Verträge.

Regeln, die hier strukturell eingehalten werden (07 §2/§3):

* Jedes Repository bekommt die **UnitOfWork** injiziert und benutzt deren
  Verbindung. Es öffnet nie eine eigene.
* Es gibt **keinen** Commit in dieser Datei. Der Abschluss gehört dem
  Orchestrator, der die UoW geöffnet hat.
* Constraints werden der Datenbank überlassen und nicht in Python
  nachgebaut — Fremdschlüssel, Unique- und Check-Bedingungen sind in
  Migration 0002 definiert.
* Reihenfolgen kommen aus `ORDER BY`, nie aus der Einfügereihenfolge.
"""

from __future__ import annotations

import sqlite3
from typing import Sequence

from personaljarvis.base.db.unit_of_work import UnitOfWork
from personaljarvis.contacts.domain.enums import (
    ContactType,
    FieldAvailabilityState,
    FieldCompleteness,
    InitiationContext,
    MutationOutcome,
    MutationState,
    SyncState,
)
from personaljarvis.contacts.domain.models import (
    Contact,
    ContactDate,
    ContactFieldAvailability,
    ContactMutation,
    ContactRelation,
    ContactRole,
    ContactSyncState,
    ContactTombstone,
    EmailAddress,
    ExternalIdentifier,
    InstantMessageAddress,
    Organization,
    OrganizationMembership,
    PhoneNumber,
    PostalAddress,
    SocialProfile,
    UrlAddress,
)
from personaljarvis.errors import IntegrityError

__all__ = [
    "SqliteContactRepository",
    "SqliteContactRoleRepository",
    "SqliteExternalIdentifierRepository",
    "SqliteFieldAvailabilityRepository",
    "SqliteSyncStateRepository",
    "SqliteTombstoneRepository",
    "SqliteMutationRepository",
    "SqliteOrganizationRepository",
]


def _b(value: bool) -> int:
    return 1 if value else 0


class _Base:
    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    @property
    def _conn(self) -> sqlite3.Connection:
        return self._uow.connection


# ── Kontakte ─────────────────────────────────────────────────────────────────
_CONTACT_COLUMNS = (
    "id, workspace_id, contact_type, given_name, middle_name, family_name, "
    "previous_family_name, name_prefix, name_suffix, phonetic_given_name, "
    "phonetic_family_name, nickname, display_name, organization_name, "
    "department_name, job_title, is_me_card, birthday_year, birthday_month, "
    "birthday_day, image_available, thumbnail_blob_ref, field_completeness, "
    "sync_state, conflict_state, local_revision, source_updated_at, "
    "imported_at, last_seen_at, last_mutation_id, last_approval_id, "
    "last_audit_id, created_at, updated_at, deleted_at, is_tombstone"
)


class SqliteContactRepository(_Base):
    def add(self, contact: Contact) -> None:
        placeholders = ", ".join("?" * len(_CONTACT_COLUMNS.split(", ")))
        try:
            self._conn.execute(
                f"INSERT INTO contacts ({_CONTACT_COLUMNS}) VALUES ({placeholders})",
                self._row(contact),
            )
        except sqlite3.IntegrityError as exc:
            raise IntegrityError(f"Kontakt nicht speicherbar: {exc}") from exc
        self._write_children(contact)

    def update(self, contact: Contact) -> None:
        assignments = ", ".join(
            f"{c} = ?" for c in _CONTACT_COLUMNS.split(", ") if c != "id"
        )
        values = list(self._row(contact))
        contact_id = values.pop(0)
        try:
            cursor = self._conn.execute(
                f"UPDATE contacts SET {assignments} WHERE id = ?",
                (*values, contact_id),
            )
        except sqlite3.IntegrityError as exc:
            raise IntegrityError(f"Kontakt nicht änderbar: {exc}") from exc
        if cursor.rowcount == 0:
            raise IntegrityError("Kontakt existiert nicht")
        self._delete_children(contact.id)
        self._write_children(contact)

    def soft_delete(self, contact_id: str, deleted_at: str) -> None:
        cursor = self._conn.execute(
            "UPDATE contacts SET is_tombstone = 1, deleted_at = ?, updated_at = ? "
            "WHERE id = ?",
            (deleted_at, deleted_at, contact_id),
        )
        if cursor.rowcount == 0:
            raise IntegrityError("Kontakt existiert nicht")

    def get(self, contact_id: str) -> Contact | None:
        row = self._conn.execute(
            f"SELECT {_CONTACT_COLUMNS} FROM contacts WHERE id = ?", (contact_id,)
        ).fetchone()
        return self._hydrate(row) if row else None

    def list_by_workspace(
        self, workspace_id: str, *, include_tombstones: bool = False
    ) -> Sequence[Contact]:
        clause = "" if include_tombstones else " AND is_tombstone = 0"
        rows = self._conn.execute(
            f"SELECT {_CONTACT_COLUMNS} FROM contacts "
            f"WHERE workspace_id = ?{clause} ORDER BY display_name, id",
            (workspace_id,),
        ).fetchall()
        return tuple(self._hydrate(r) for r in rows)

    def search_by_display_name(
        self, workspace_id: str, fragment: str
    ) -> Sequence[Contact]:
        rows = self._conn.execute(
            f"SELECT {_CONTACT_COLUMNS} FROM contacts "
            "WHERE workspace_id = ? AND is_tombstone = 0 "
            "AND display_name LIKE ? ESCAPE '\\' ORDER BY display_name, id",
            (workspace_id, f"%{self._escape_like(fragment)}%"),
        ).fetchall()
        return tuple(self._hydrate(r) for r in rows)

    @staticmethod
    def _escape_like(value: str) -> str:
        return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")

    # ── Zeilenabbildung ─────────────────────────────────────────────────────
    @staticmethod
    def _row(c: Contact) -> tuple:
        return (
            c.id, c.workspace_id, c.contact_type.value, c.given_name, c.middle_name,
            c.family_name, c.previous_family_name, c.name_prefix, c.name_suffix,
            c.phonetic_given_name, c.phonetic_family_name, c.nickname,
            c.display_name, c.organization_name, c.department_name, c.job_title,
            _b(c.is_me_card), c.birthday_year, c.birthday_month, c.birthday_day,
            _b(c.image_available), c.thumbnail_blob_ref, c.field_completeness.value,
            c.sync_state.value, c.conflict_state, c.local_revision,
            c.source_updated_at, c.imported_at, c.last_seen_at, c.last_mutation_id,
            c.last_approval_id, c.last_audit_id, c.created_at, c.updated_at,
            c.deleted_at, _b(c.is_tombstone),
        )

    def _hydrate(self, row: sqlite3.Row) -> Contact:
        cid = row["id"]
        return Contact(
            id=cid,
            workspace_id=row["workspace_id"],
            contact_type=ContactType(row["contact_type"]),
            display_name=row["display_name"],
            given_name=row["given_name"],
            middle_name=row["middle_name"],
            family_name=row["family_name"],
            previous_family_name=row["previous_family_name"],
            name_prefix=row["name_prefix"],
            name_suffix=row["name_suffix"],
            phonetic_given_name=row["phonetic_given_name"],
            phonetic_family_name=row["phonetic_family_name"],
            nickname=row["nickname"],
            organization_name=row["organization_name"],
            department_name=row["department_name"],
            job_title=row["job_title"],
            is_me_card=bool(row["is_me_card"]),
            birthday_year=row["birthday_year"],
            birthday_month=row["birthday_month"],
            birthday_day=row["birthday_day"],
            image_available=bool(row["image_available"]),
            thumbnail_blob_ref=row["thumbnail_blob_ref"],
            field_completeness=FieldCompleteness(row["field_completeness"]),
            sync_state=SyncState(row["sync_state"]),
            conflict_state=row["conflict_state"],
            local_revision=row["local_revision"],
            source_updated_at=row["source_updated_at"],
            imported_at=row["imported_at"],
            last_seen_at=row["last_seen_at"],
            last_mutation_id=row["last_mutation_id"],
            last_approval_id=row["last_approval_id"],
            last_audit_id=row["last_audit_id"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            deleted_at=row["deleted_at"],
            is_tombstone=bool(row["is_tombstone"]),
            emails=self._emails(cid),
            phones=self._phones(cid),
            postal_addresses=self._addresses(cid),
            dates=self._dates(cid),
            urls=self._urls(cid),
            social_profiles=self._socials(cid),
            instant_messages=self._ims(cid),
            relations=self._relations(cid),
            roles=SqliteContactRoleRepository(self._uow).list_for_contact(cid),
            field_availability=SqliteFieldAvailabilityRepository(
                self._uow
            ).list_for_contact(cid),
            external_ids=SqliteExternalIdentifierRepository(
                self._uow
            ).list_for_contact(cid),
        )

    # ── Kinddatensätze ──────────────────────────────────────────────────────
    def _delete_children(self, contact_id: str) -> None:
        for table in (
            "contact_emails", "contact_phones", "contact_postal_addresses",
            "contact_dates", "contact_urls", "contact_social_profiles",
            "contact_instant_messages",
        ):
            self._conn.execute(f"DELETE FROM {table} WHERE contact_id = ?", (contact_id,))
        # Beziehungen hängen über `from_contact_id`, nicht über `contact_id` —
        # deshalb bewusst getrennt.
        self._conn.execute(
            "DELETE FROM contact_relations WHERE from_contact_id = ?", (contact_id,)
        )

    def _write_children(self, c: Contact) -> None:
        try:
            self._conn.executemany(
                "INSERT INTO contact_emails (id, contact_id, position, label_raw, "
                "label_normalized, value_raw, value_normalized) VALUES (?,?,?,?,?,?,?)",
                [(e.id, c.id, e.position, e.label_raw, e.label_normalized,
                  e.value_raw, e.value_normalized) for e in c.emails],
            )
            self._conn.executemany(
                "INSERT INTO contact_phones (id, contact_id, position, label_raw, "
                "label_normalized, value_raw, value_normalized_e164) VALUES (?,?,?,?,?,?,?)",
                [(p.id, c.id, p.position, p.label_raw, p.label_normalized,
                  p.value_raw, p.value_normalized_e164) for p in c.phones],
            )
            self._conn.executemany(
                "INSERT INTO contact_postal_addresses (id, contact_id, position, "
                "label_raw, label_normalized, street, sub_locality, city, state, "
                "postal_code, country, iso_country_code) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                [(a.id, c.id, a.position, a.label_raw, a.label_normalized, a.street,
                  a.sub_locality, a.city, a.state, a.postal_code, a.country,
                  a.iso_country_code) for a in c.postal_addresses],
            )
            self._conn.executemany(
                "INSERT INTO contact_dates (id, contact_id, position, kind, "
                "label_raw, label_normalized, year, month, day) VALUES (?,?,?,?,?,?,?,?,?)",
                [(d.id, c.id, d.position, d.kind, d.label_raw, d.label_normalized,
                  d.year, d.month, d.day) for d in c.dates],
            )
            self._conn.executemany(
                "INSERT INTO contact_urls (id, contact_id, position, label_raw, "
                "label_normalized, value_raw, value_normalized) VALUES (?,?,?,?,?,?,?)",
                [(u.id, c.id, u.position, u.label_raw, u.label_normalized,
                  u.value_raw, u.value_normalized) for u in c.urls],
            )
            self._conn.executemany(
                "INSERT INTO contact_social_profiles (id, contact_id, position, "
                "label_raw, label_normalized, service, username, url) VALUES (?,?,?,?,?,?,?,?)",
                [(s.id, c.id, s.position, s.label_raw, s.label_normalized,
                  s.service, s.username, s.url) for s in c.social_profiles],
            )
            self._conn.executemany(
                "INSERT INTO contact_instant_messages (id, contact_id, position, "
                "label_raw, label_normalized, service, username) VALUES (?,?,?,?,?,?,?)",
                [(i.id, c.id, i.position, i.label_raw, i.label_normalized,
                  i.service, i.username) for i in c.instant_messages],
            )
            self._conn.executemany(
                "INSERT INTO contact_relations (id, from_contact_id, to_contact_id, "
                "position, relation_type, label_raw, target_name_raw) VALUES (?,?,?,?,?,?,?)",
                [(r.id, c.id, r.to_contact_id, r.position, r.relation_type,
                  r.label_raw, r.target_name_raw) for r in c.relations],
            )
        except sqlite3.IntegrityError as exc:
            raise IntegrityError(f"Kinddatensatz nicht speicherbar: {exc}") from exc

    def _emails(self, cid: str) -> tuple[EmailAddress, ...]:
        rows = self._conn.execute(
            "SELECT id, position, label_raw, label_normalized, value_raw, "
            "value_normalized FROM contact_emails WHERE contact_id = ? ORDER BY position",
            (cid,)).fetchall()
        return tuple(EmailAddress(id=r["id"], position=r["position"],
                                  label_raw=r["label_raw"],
                                  label_normalized=r["label_normalized"],
                                  value_raw=r["value_raw"],
                                  value_normalized=r["value_normalized"]) for r in rows)

    def _phones(self, cid: str) -> tuple[PhoneNumber, ...]:
        rows = self._conn.execute(
            "SELECT id, position, label_raw, label_normalized, value_raw, "
            "value_normalized_e164 FROM contact_phones WHERE contact_id = ? ORDER BY position",
            (cid,)).fetchall()
        return tuple(PhoneNumber(id=r["id"], position=r["position"],
                                 label_raw=r["label_raw"],
                                 label_normalized=r["label_normalized"],
                                 value_raw=r["value_raw"],
                                 value_normalized_e164=r["value_normalized_e164"])
                     for r in rows)

    def _addresses(self, cid: str) -> tuple[PostalAddress, ...]:
        rows = self._conn.execute(
            "SELECT * FROM contact_postal_addresses WHERE contact_id = ? ORDER BY position",
            (cid,)).fetchall()
        return tuple(PostalAddress(
            id=r["id"], position=r["position"], label_raw=r["label_raw"],
            label_normalized=r["label_normalized"], street=r["street"],
            sub_locality=r["sub_locality"], city=r["city"], state=r["state"],
            postal_code=r["postal_code"], country=r["country"],
            iso_country_code=r["iso_country_code"]) for r in rows)

    def _dates(self, cid: str) -> tuple[ContactDate, ...]:
        rows = self._conn.execute(
            "SELECT * FROM contact_dates WHERE contact_id = ? ORDER BY position",
            (cid,)).fetchall()
        return tuple(ContactDate(
            id=r["id"], position=r["position"], label_raw=r["label_raw"],
            label_normalized=r["label_normalized"], kind=r["kind"], year=r["year"],
            month=r["month"], day=r["day"]) for r in rows)

    def _urls(self, cid: str) -> tuple[UrlAddress, ...]:
        rows = self._conn.execute(
            "SELECT * FROM contact_urls WHERE contact_id = ? ORDER BY position",
            (cid,)).fetchall()
        return tuple(UrlAddress(
            id=r["id"], position=r["position"], label_raw=r["label_raw"],
            label_normalized=r["label_normalized"], value_raw=r["value_raw"],
            value_normalized=r["value_normalized"]) for r in rows)

    def _socials(self, cid: str) -> tuple[SocialProfile, ...]:
        rows = self._conn.execute(
            "SELECT * FROM contact_social_profiles WHERE contact_id = ? ORDER BY position",
            (cid,)).fetchall()
        return tuple(SocialProfile(
            id=r["id"], position=r["position"], label_raw=r["label_raw"],
            label_normalized=r["label_normalized"], service=r["service"],
            username=r["username"], url=r["url"]) for r in rows)

    def _ims(self, cid: str) -> tuple[InstantMessageAddress, ...]:
        rows = self._conn.execute(
            "SELECT * FROM contact_instant_messages WHERE contact_id = ? ORDER BY position",
            (cid,)).fetchall()
        return tuple(InstantMessageAddress(
            id=r["id"], position=r["position"], label_raw=r["label_raw"],
            label_normalized=r["label_normalized"], service=r["service"],
            username=r["username"]) for r in rows)

    def _relations(self, cid: str) -> tuple[ContactRelation, ...]:
        rows = self._conn.execute(
            "SELECT * FROM contact_relations WHERE from_contact_id = ? ORDER BY position",
            (cid,)).fetchall()
        return tuple(ContactRelation(
            id=r["id"], position=r["position"], relation_type=r["relation_type"],
            to_contact_id=r["to_contact_id"], label_raw=r["label_raw"],
            target_name_raw=r["target_name_raw"]) for r in rows)


# ── Rollen ───────────────────────────────────────────────────────────────────
class SqliteContactRoleRepository(_Base):
    def set_roles(self, contact_id: str, roles: Sequence[ContactRole]) -> None:
        self._conn.execute("DELETE FROM contact_roles WHERE contact_id = ?", (contact_id,))
        try:
            self._conn.executemany(
                "INSERT INTO contact_roles (contact_id, workspace_id, role, "
                "assigned_at) VALUES (?,?,?,?)",
                [(contact_id, r.workspace_id, r.role, r.assigned_at) for r in roles],
            )
        except sqlite3.IntegrityError as exc:
            raise IntegrityError(f"Rolle nicht speicherbar: {exc}") from exc

    def list_for_contact(self, contact_id: str) -> tuple[ContactRole, ...]:
        rows = self._conn.execute(
            "SELECT workspace_id, role, assigned_at FROM contact_roles "
            "WHERE contact_id = ? ORDER BY workspace_id, role",
            (contact_id,)).fetchall()
        return tuple(ContactRole(workspace_id=r["workspace_id"], role=r["role"],
                                 assigned_at=r["assigned_at"]) for r in rows)

    def list_contact_ids_by_role(self, workspace_id: str, role: str) -> tuple[str, ...]:
        rows = self._conn.execute(
            "SELECT contact_id FROM contact_roles WHERE workspace_id = ? AND role = ? "
            "ORDER BY contact_id", (workspace_id, role)).fetchall()
        return tuple(r["contact_id"] for r in rows)


# ── Externe Identitäten ──────────────────────────────────────────────────────
class SqliteExternalIdentifierRepository(_Base):
    def upsert(self, contact_id: str, identifier: ExternalIdentifier) -> None:
        try:
            self._conn.execute(
                "INSERT INTO contact_external_ids (id, contact_id, "
                "provider_account_id, container_identifier, provider_identifier, "
                "unified_identifier, provider_revision, key_set_version, "
                "last_seen_at) VALUES (?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(provider_account_id, provider_identifier) DO UPDATE SET "
                "contact_id=excluded.contact_id, "
                "container_identifier=excluded.container_identifier, "
                "unified_identifier=excluded.unified_identifier, "
                "provider_revision=excluded.provider_revision, "
                "key_set_version=excluded.key_set_version, "
                "last_seen_at=excluded.last_seen_at",
                (identifier.id, contact_id, identifier.provider_account_id,
                 identifier.container_identifier, identifier.provider_identifier,
                 identifier.unified_identifier, identifier.provider_revision,
                 identifier.key_set_version, identifier.last_seen_at),
            )
        except sqlite3.IntegrityError as exc:
            raise IntegrityError(f"Externe Identität nicht speicherbar: {exc}") from exc

    def list_for_contact(self, contact_id: str) -> tuple[ExternalIdentifier, ...]:
        rows = self._conn.execute(
            "SELECT * FROM contact_external_ids WHERE contact_id = ? "
            "ORDER BY provider_account_id, provider_identifier",
            (contact_id,)).fetchall()
        return tuple(ExternalIdentifier(
            id=r["id"], provider_account_id=r["provider_account_id"],
            container_identifier=r["container_identifier"],
            provider_identifier=r["provider_identifier"],
            unified_identifier=r["unified_identifier"],
            provider_revision=r["provider_revision"],
            key_set_version=r["key_set_version"],
            last_seen_at=r["last_seen_at"]) for r in rows)

    def find_contact_id(
        self, provider_account_id: str, provider_identifier: str
    ) -> str | None:
        row = self._conn.execute(
            "SELECT contact_id FROM contact_external_ids WHERE "
            "provider_account_id = ? AND provider_identifier = ?",
            (provider_account_id, provider_identifier)).fetchone()
        return row["contact_id"] if row else None


# ── Feldverfügbarkeit ────────────────────────────────────────────────────────
class SqliteFieldAvailabilityRepository(_Base):
    def set_for_contact(
        self, contact_id: str, entries: Sequence[ContactFieldAvailability]
    ) -> None:
        self._conn.execute(
            "DELETE FROM contact_field_availability WHERE contact_id = ?", (contact_id,)
        )
        try:
            self._conn.executemany(
                "INSERT INTO contact_field_availability (contact_id, field, state, "
                "observed_at) VALUES (?,?,?,?)",
                [(contact_id, e.field_name, e.state.value, e.observed_at)
                 for e in entries],
            )
        except sqlite3.IntegrityError as exc:
            raise IntegrityError(f"Feldverfügbarkeit nicht speicherbar: {exc}") from exc

    def list_for_contact(
        self, contact_id: str
    ) -> tuple[ContactFieldAvailability, ...]:
        rows = self._conn.execute(
            "SELECT field, state, observed_at FROM contact_field_availability "
            "WHERE contact_id = ? ORDER BY field", (contact_id,)).fetchall()
        return tuple(ContactFieldAvailability(
            field_name=r["field"], state=FieldAvailabilityState(r["state"]),
            observed_at=r["observed_at"]) for r in rows)


# ── Sync-Zustand ─────────────────────────────────────────────────────────────
class SqliteSyncStateRepository(_Base):
    def upsert(self, state: ContactSyncState) -> None:
        try:
            self._conn.execute(
                "INSERT INTO contacts_sync_state (provider_account_id, "
                "container_identifier, cursor_token, cursor_taken_at, "
                "last_full_diff_at, key_set_version, mode, circuit_state, "
                "updated_at, container_type) VALUES (?,?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(provider_account_id, container_identifier) DO UPDATE SET "
                "cursor_token=excluded.cursor_token, "
                "cursor_taken_at=excluded.cursor_taken_at, "
                "last_full_diff_at=excluded.last_full_diff_at, "
                "key_set_version=excluded.key_set_version, mode=excluded.mode, "
                "circuit_state=excluded.circuit_state, "
                "updated_at=excluded.updated_at, "
                # Eine bereits erhobene Art wird nie verschlechtert — weder
                # durch `NULL` noch durch `'unknown'`. Beides heisst „dieser
                # Aufruf weiss es nicht", nicht „die alte Auskunft ist falsch".
                # Der Schutz sitzt hier, weil es genau einen Schreibweg gibt:
                # eine Regel an einer Stelle laeuft nicht auseinander.
                "container_type=CASE "
                "WHEN excluded.container_type IS NULL "
                "OR excluded.container_type = 'unknown' "
                "THEN contacts_sync_state.container_type "
                "ELSE excluded.container_type END",
                (state.provider_account_id, state.container_identifier,
                 state.cursor_token, state.cursor_taken_at, state.last_full_diff_at,
                 state.key_set_version, state.mode, state.circuit_state,
                 state.updated_at, state.container_type),
            )
        except sqlite3.IntegrityError as exc:
            raise IntegrityError(f"Sync-Zustand nicht speicherbar: {exc}") from exc

    def get(
        self, provider_account_id: str, container_identifier: str
    ) -> ContactSyncState | None:
        row = self._conn.execute(
            "SELECT * FROM contacts_sync_state WHERE provider_account_id = ? "
            "AND container_identifier = ?",
            (provider_account_id, container_identifier)).fetchone()
        return self._hydrate(row) if row else None

    def list_all(self) -> tuple[ContactSyncState, ...]:
        rows = self._conn.execute(
            "SELECT * FROM contacts_sync_state "
            "ORDER BY provider_account_id, container_identifier").fetchall()
        return tuple(self._hydrate(r) for r in rows)

    @staticmethod
    def _hydrate(r: sqlite3.Row) -> ContactSyncState:
        return ContactSyncState(
            provider_account_id=r["provider_account_id"],
            container_identifier=r["container_identifier"],
            container_type=r["container_type"],
            cursor_token=r["cursor_token"], cursor_taken_at=r["cursor_taken_at"],
            last_full_diff_at=r["last_full_diff_at"],
            key_set_version=r["key_set_version"], mode=r["mode"],
            circuit_state=r["circuit_state"], updated_at=r["updated_at"])


# ── Tombstones ───────────────────────────────────────────────────────────────
class SqliteTombstoneRepository(_Base):
    def add(self, tombstone: ContactTombstone) -> None:
        try:
            self._conn.execute(
                "INSERT INTO contacts_tombstones (provider_account_id, "
                "provider_identifier, contact_id, deleted_at, reason, retain_until) "
                "VALUES (?,?,?,?,?,?)",
                (tombstone.provider_account_id, tombstone.provider_identifier,
                 tombstone.contact_id, tombstone.deleted_at, tombstone.reason,
                 tombstone.retain_until),
            )
        except sqlite3.IntegrityError as exc:
            raise IntegrityError(f"Tombstone nicht speicherbar: {exc}") from exc

    def exists(self, provider_account_id: str, provider_identifier: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM contacts_tombstones WHERE provider_account_id = ? "
            "AND provider_identifier = ?",
            (provider_account_id, provider_identifier)).fetchone()
        return row is not None

    def list_all(self) -> tuple[ContactTombstone, ...]:
        rows = self._conn.execute(
            "SELECT * FROM contacts_tombstones "
            "ORDER BY provider_account_id, provider_identifier").fetchall()
        return tuple(ContactTombstone(
            provider_account_id=r["provider_account_id"],
            provider_identifier=r["provider_identifier"], reason=r["reason"],
            deleted_at=r["deleted_at"], contact_id=r["contact_id"],
            retain_until=r["retain_until"]) for r in rows)


# ── Mutationen ───────────────────────────────────────────────────────────────
class SqliteMutationRepository(_Base):
    def add(self, mutation: ContactMutation) -> None:
        try:
            self._conn.execute(
                "INSERT INTO contacts_mutations (mutation_id, command, "
                "correlation_id, actor, initiation_context, workspace_id, "
                "provider_account_id, container_identifier, target_contact_id, "
                "target_provider_identifier, expected_revision, "
                "idempotency_key, approval_id, outbox_id, audit_id, "
                "transaction_author, payload_json, payload_digest, "
                "preview_digest, state, outcome, attempt_count, "
                "last_error_code, created_at, completed_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                self._row(mutation),
            )
        except sqlite3.IntegrityError as exc:
            raise IntegrityError(f"Mutation nicht speicherbar: {exc}") from exc

    def update_state(self, mutation: ContactMutation) -> None:
        cursor = self._conn.execute(
            "UPDATE contacts_mutations SET state = ?, outcome = ?, "
            "completed_at = ?, last_error_code = ? WHERE mutation_id = ?",
            (mutation.state.value,
             mutation.outcome.value if mutation.outcome else None,
             mutation.completed_at, mutation.last_error_code,
             mutation.mutation_id),
        )
        if cursor.rowcount == 0:
            raise IntegrityError("Mutation existiert nicht")

    def get(self, mutation_id: str) -> ContactMutation | None:
        row = self._conn.execute(
            "SELECT * FROM contacts_mutations WHERE mutation_id = ?", (mutation_id,)
        ).fetchone()
        return self._hydrate(row) if row else None

    def find_by_idempotency_key(self, key: str) -> ContactMutation | None:
        row = self._conn.execute(
            "SELECT * FROM contacts_mutations WHERE idempotency_key = ?", (key,)
        ).fetchone()
        return self._hydrate(row) if row else None

    def list_requiring_reconcile(self) -> tuple[ContactMutation, ...]:
        rows = self._conn.execute(
            "SELECT * FROM contacts_mutations WHERE state IN "
            "('outcome_unknown','reconcile_required') "
            "ORDER BY created_at, mutation_id"
        ).fetchall()
        return tuple(self._hydrate(r) for r in rows)

    #: Fallwerte fuer Felder, die eine Mutation aus der Domaene nicht traegt.
    #: Die Application-Schicht setzt sie; ein direkter Repository-Aufruf ist
    #: der Testweg und bekommt technisch eindeutige Platzhalter.
    _AUTOR = "de.kluender.jarvis.contacts-bridge"

    @classmethod
    def _row(cls, m: ContactMutation) -> tuple:
        return (m.mutation_id, m.command,
                m.correlation_id or m.mutation_id,
                m.actor or "repository",
                m.initiation_context.value,
                m.workspace_id or "unbekannt",
                m.provider_account_id or "unbekannt",
                m.container_identifier, m.target_contact_id,
                m.target_provider_identifier, m.expected_revision,
                m.idempotency_key, m.approval_id, m.outbox_id, m.audit_id,
                cls._AUTOR, "{}", "ohne-digest", "ohne-digest",
                m.state.value, m.outcome.value if m.outcome else None,
                m.attempt_count, m.last_error_code, m.created_at,
                m.completed_at)

    @staticmethod
    def _hydrate(r: sqlite3.Row) -> ContactMutation:
        return ContactMutation(
            mutation_id=r["mutation_id"], command=r["command"],
            idempotency_key=r["idempotency_key"], state=MutationState(r["state"]),
            initiation_context=InitiationContext(r["initiation_context"]),
            target_contact_id=r["target_contact_id"],
            target_provider_identifier=r["target_provider_identifier"],
            provider_account_id=r["provider_account_id"],
            approval_id=r["approval_id"], expected_revision=r["expected_revision"],
            outcome=MutationOutcome(r["outcome"]) if r["outcome"] else None,
            created_at=r["created_at"], completed_at=r["completed_at"],
            correlation_id=r["correlation_id"], actor=r["actor"],
            workspace_id=r["workspace_id"],
            container_identifier=r["container_identifier"],
            outbox_id=r["outbox_id"], audit_id=r["audit_id"],
            attempt_count=r["attempt_count"],
            last_error_code=r["last_error_code"])


# ── Organisationen ───────────────────────────────────────────────────────────
class SqliteOrganizationRepository(_Base):
    def add(self, organization: Organization) -> None:
        try:
            self._conn.execute(
                "INSERT INTO organizations (id, workspace_id, name, created_at, "
                "updated_at) VALUES (?,?,?,?,?)",
                (organization.id, organization.workspace_id, organization.name,
                 organization.created_at, organization.updated_at),
            )
        except sqlite3.IntegrityError as exc:
            raise IntegrityError(f"Organisation nicht speicherbar: {exc}") from exc

    def get(self, organization_id: str) -> Organization | None:
        row = self._conn.execute(
            "SELECT * FROM organizations WHERE id = ?", (organization_id,)).fetchone()
        if not row:
            return None
        return Organization(id=row["id"], workspace_id=row["workspace_id"],
                            name=row["name"], created_at=row["created_at"],
                            updated_at=row["updated_at"])

    def add_membership(self, membership: OrganizationMembership) -> None:
        try:
            self._conn.execute(
                "INSERT INTO organization_memberships (organization_id, contact_id, "
                "role, confirmed_at) VALUES (?,?,?,?)",
                (membership.organization_id, membership.contact_id,
                 membership.role, membership.confirmed_at),
            )
        except sqlite3.IntegrityError as exc:
            raise IntegrityError(f"Mitgliedschaft nicht speicherbar: {exc}") from exc

    def list_memberships(
        self, organization_id: str
    ) -> tuple[OrganizationMembership, ...]:
        rows = self._conn.execute(
            "SELECT * FROM organization_memberships WHERE organization_id = ? "
            "ORDER BY contact_id", (organization_id,)).fetchall()
        return tuple(OrganizationMembership(
            organization_id=r["organization_id"], contact_id=r["contact_id"],
            role=r["role"], confirmed_at=r["confirmed_at"]) for r in rows)
