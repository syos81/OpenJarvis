"""Lesende Abfragen des Kontakte-Moduls (Plan §9.2).

Verbindliche Eigenschaften:

* **Nur Repository- bzw. Datenbankzugriffe.** Kein Bridge-Aufruf, keine
  Store-Operation, kein Sidecar. Eine Abfrage kann strukturell nichts
  auslösen.
* **Workspace- und Providerkonto-Isolation.** Jede Abfrage nennt ihren
  Workspace; Providerkonto-Filter sind zusätzlich möglich. Es gibt keine
  Abfrage ohne Workspace.
* **Stabile Pagination.** Der Cursor ist ein zusammengesetzter Schlüssel
  `(display_name, id)` — bei gleichem Anzeigenamen entscheidet die ID. Damit
  überspringt oder wiederholt eine Seite keinen Datensatz, auch wenn sich der
  Bestand zwischen zwei Seiten ändert. Der Cursor ist **kein** Offset.
* **`unavailable_by_capability` bleibt von leer unterschieden.** Die
  Feldverfügbarkeit wird mitgeliefert; Notizen erscheinen nie als leerer Wert.
* **Kein Sync-Cursor nach außen.** `cursor_token` und Change-History-Token
  verlassen diese Schicht niemals — der Sync-Status meldet nur Alter, Modus
  und Circuit-Zustand.
"""

from __future__ import annotations

import base64
import binascii
import json
import unicodedata
from dataclasses import dataclass
from typing import Any

from personaljarvis.contacts.application.errors import (
    ContainerNotAvailable,
    InvalidCommand,
    TargetBindingError,
)
from personaljarvis.contacts.domain.enums import FieldAvailabilityState
from personaljarvis.contacts.domain.models import Contact
from personaljarvis.contacts.repositories.sqlite import (
    SqliteContactRepository,
)

__all__ = [
    "MAX_PAGE_SIZE",
    "DEFAULT_PAGE_SIZE",
    "ContactSummary",
    "ContactPage",
    "MutationSummary",
    "ApprovalSummary",
    "SyncStatusView",
    "encode_cursor",
    "decode_cursor",
    "normalize_search",
    "ContactsQueryService",
]

#: Obergrenze einer Seite. Eine größere Anfrage wird abgewiesen, nicht
#: stillschweigend gekappt — sonst hielte der Aufrufer eine Teilmenge für
#: vollständig.
MAX_PAGE_SIZE = 200
DEFAULT_PAGE_SIZE = 50


def normalize_search(text: str) -> str:
    """Suchtext normalisieren: NFKC, casefold, Leerraum zusammenziehen.

    Damit findet „Müller" auch bei zerlegter Unicode-Eingabe und
    unterschiedlicher Groß-/Kleinschreibung.
    """
    zusammengezogen = " ".join((text or "").split())
    return unicodedata.normalize("NFKC", zusammengezogen).casefold()


def encode_cursor(display_name: str, contact_id: str) -> str:
    """Opaker Seitenzeiger. Trägt keine Provider- oder Sync-Information."""
    roh = json.dumps({"d": display_name, "i": contact_id},
                     separators=(",", ":"), ensure_ascii=False)
    return base64.urlsafe_b64encode(roh.encode("utf-8")).decode("ascii")


def decode_cursor(cursor: str) -> tuple[str, str]:
    try:
        roh = base64.urlsafe_b64decode(cursor.encode("ascii")).decode("utf-8")
        daten = json.loads(roh)
        return str(daten["d"]), str(daten["i"])
    except (binascii.Error, UnicodeDecodeError, ValueError, KeyError,
            TypeError) as exc:
        raise InvalidCommand("Ungueltiger Seitenzeiger") from exc


@dataclass(frozen=True)
class ContactSummary:
    """Listenzeile — bewusst ohne Detaildaten wie Adressen oder Beziehungen."""

    id: str
    display_name: str
    organization_name: str | None
    contact_type: str
    is_me_card: bool
    field_completeness: str
    sync_state: str
    conflict_state: str | None
    roles: tuple[str, ...]
    provider_account_ids: tuple[str, ...]
    email_count: int
    phone_count: int
    address_count: int
    has_unavailable_fields: bool


@dataclass(frozen=True)
class ContactPage:
    items: tuple[ContactSummary, ...]
    next_cursor: str | None
    has_more: bool
    total_estimate: int | None = None


@dataclass(frozen=True)
class MutationSummary:
    mutation_id: str
    command: str
    state: str
    outcome: str | None
    initiation_context: str
    actor: str
    correlation_id: str
    provider_account_id: str
    target_contact_id: str | None
    target_display_name: str | None
    container_identifier: str | None
    expected_revision: str | None
    attempt_count: int
    last_error_code: str | None
    created_at: str
    approved_at: str | None
    completed_at: str | None
    approval_id: str | None
    approval_state: str | None
    approval_expires_at: str | None
    payload_digest: str = ""
    preview_digest: str = ""

    @property
    def requires_reconcile(self) -> bool:
        return self.state in ("outcome_unknown", "reconcile_required")

    @property
    def needs_manual_decision(self) -> bool:
        return self.state == "manual_decision_required"


@dataclass(frozen=True)
class ApprovalSummary:
    approval_id: str
    mutation_id: str
    command: str
    state: str
    initiation_context: str
    actor: str
    correlation_id: str
    requested_at: str
    expires_at: str
    decided_at: str | None
    decision_actor: str | None
    preview_digest: str
    is_expired: bool


@dataclass(frozen=True)
class SyncStatusView:
    """Sync-Zustand **ohne** Cursor-Token — der verlässt die Schicht nie."""

    provider_account_id: str
    container_identifier: str
    container_type: str | None
    mode: str
    circuit_state: str
    key_set_version: str
    has_cursor: bool
    cursor_taken_at: str | None
    last_full_diff_at: str | None
    updated_at: str


class ContactsQueryService:
    """Alle lesenden Abfragen. Kein Schreibpfad, kein Provider-Zugriff."""

    def __init__(self, persistence) -> None:
        self._persistence = persistence

    # ── Kontakte ────────────────────────────────────────────────────────────
    def list_contacts(self, *, workspace_id: str, search: str | None = None,
                      role: str | None = None,
                      provider_account_id: str | None = None,
                      cursor: str | None = None,
                      limit: int = DEFAULT_PAGE_SIZE) -> ContactPage:
        """Seite von Kontaktzeilen, stabil sortiert nach (Anzeigename, ID)."""
        if limit < 1 or limit > MAX_PAGE_SIZE:
            raise InvalidCommand(
                f"limit muss zwischen 1 und {MAX_PAGE_SIZE} liegen")
        if not workspace_id or not workspace_id.strip():
            raise InvalidCommand("workspace_id ist erforderlich")

        bedingungen = ["c.workspace_id = ?", "c.is_tombstone = 0"]
        werte: list[Any] = [workspace_id]

        if cursor:
            letzter_name, letzte_id = decode_cursor(cursor)
            bedingungen.append("(c.display_name, c.id) > (?, ?)")
            werte.extend([letzter_name, letzte_id])

        if role:
            bedingungen.append(
                "EXISTS (SELECT 1 FROM contact_roles r WHERE r.contact_id = c.id "
                "AND r.workspace_id = ? AND r.role = ?)")
            werte.extend([workspace_id, role])

        if provider_account_id:
            bedingungen.append(
                "EXISTS (SELECT 1 FROM contact_external_ids e "
                "WHERE e.contact_id = c.id AND e.provider_account_id = ?)")
            werte.append(provider_account_id)

        if search and search.strip():
            begriff = f"%{self._escape_like(normalize_search(search))}%"
            # Gesucht wird über Anzeigename, Organisation und die
            # normalisierten Mehrfachwerte. **Nicht** über Notizen — die sind
            # mangels Entitlement gar nicht lesbar (08 §4).
            bedingungen.append(
                "(LOWER(c.display_name) LIKE ? ESCAPE '\\' "
                "OR LOWER(COALESCE(c.organization_name, '')) LIKE ? ESCAPE '\\' "
                "OR EXISTS (SELECT 1 FROM contact_emails m WHERE m.contact_id = c.id "
                "AND LOWER(m.value_normalized) LIKE ? ESCAPE '\\') "
                "OR EXISTS (SELECT 1 FROM contact_phones p WHERE p.contact_id = c.id "
                "AND LOWER(COALESCE(p.value_normalized_e164, p.value_raw)) "
                "LIKE ? ESCAPE '\\'))")
            werte.extend([begriff, begriff, begriff, begriff])

        wo = " AND ".join(bedingungen)
        with self._persistence.unit_of_work() as uow:
            rows = uow.execute(
                f"SELECT c.id, c.display_name, c.organization_name, "
                f"c.contact_type, c.is_me_card, c.field_completeness, "
                f"c.sync_state, c.conflict_state FROM contacts c WHERE {wo} "
                f"ORDER BY c.display_name, c.id LIMIT ?",
                (*werte, limit + 1)).fetchall()

            mehr = len(rows) > limit
            sichtbar = rows[:limit]
            eintraege = tuple(self._summary(uow, r, workspace_id)
                              for r in sichtbar)
            naechster = (encode_cursor(sichtbar[-1]["display_name"],
                                       sichtbar[-1]["id"])
                         if mehr and sichtbar else None)
            return ContactPage(items=eintraege, next_cursor=naechster,
                               has_more=mehr)

    def get_contact(self, contact_id: str, *,
                    workspace_id: str) -> Contact | None:
        """Vollständiger Kontakt inklusive Feldverfügbarkeit.

        Die Workspace-Prüfung ist Teil der Abfrage, nicht des Aufrufers: ein
        fremder Workspace bekommt `None`, nicht den Datensatz.
        """
        with self._persistence.unit_of_work() as uow:
            zeile = uow.execute(
                "SELECT workspace_id FROM contacts WHERE id = ?",
                (contact_id,)).fetchone()
            if zeile is None or zeile["workspace_id"] != workspace_id:
                return None
            return SqliteContactRepository(uow).get(contact_id)

    def list_roles(self, *, workspace_id: str) -> tuple[tuple[str, int], ...]:
        """Alle vergebenen Kategorien mit Anzahl — Grundlage der Filterleiste."""
        with self._persistence.unit_of_work() as uow:
            rows = uow.execute(
                "SELECT r.role, count(*) AS n FROM contact_roles r "
                "JOIN contacts c ON c.id = r.contact_id "
                "WHERE r.workspace_id = ? AND c.is_tombstone = 0 "
                "GROUP BY r.role ORDER BY r.role", (workspace_id,)).fetchall()
            return tuple((r["role"], r["n"]) for r in rows)

    def contact_roles(self, contact_id: str, *,
                      workspace_id: str) -> tuple[str, ...]:
        with self._persistence.unit_of_work() as uow:
            rows = uow.execute(
                "SELECT role FROM contact_roles WHERE contact_id = ? "
                "AND workspace_id = ? ORDER BY role",
                (contact_id, workspace_id)).fetchall()
            return tuple(r["role"] for r in rows)

    # ── Mutationen ──────────────────────────────────────────────────────────
    def list_mutations(self, *, workspace_id: str, state: str | None = None,
                       limit: int = DEFAULT_PAGE_SIZE
                       ) -> tuple[MutationSummary, ...]:
        if limit < 1 or limit > MAX_PAGE_SIZE:
            raise InvalidCommand(
                f"limit muss zwischen 1 und {MAX_PAGE_SIZE} liegen")
        bedingungen = ["m.workspace_id = ?"]
        werte: list[Any] = [workspace_id]
        if state:
            bedingungen.append("m.state = ?")
            werte.append(state)
        with self._persistence.unit_of_work() as uow:
            rows = uow.execute(
                f"SELECT m.*, c.display_name AS ziel_name, a.state AS a_state, "
                f"a.expires_at AS a_expires, "
                # Kanonische Quelle der Sendversuche (siehe `_mutation`).
                f"o.attempt_count AS sendversuche "
                f"FROM contacts_mutations m "
                f"LEFT JOIN contacts c ON c.id = m.target_contact_id "
                f"LEFT JOIN personal_approvals a ON a.approval_id = m.approval_id "
                f"LEFT JOIN personal_external_action_outbox o "
                f"ON o.outbox_id = m.outbox_id "
                f"WHERE {' AND '.join(bedingungen)} "
                f"ORDER BY m.created_at DESC, m.mutation_id LIMIT ?",
                (*werte, limit)).fetchall()
            return tuple(self._mutation(r) for r in rows)

    def get_mutation(self, mutation_id: str, *,
                     workspace_id: str) -> MutationSummary | None:
        with self._persistence.unit_of_work() as uow:
            zeile = uow.execute(
                "SELECT m.*, c.display_name AS ziel_name, a.state AS a_state, "
                "a.expires_at AS a_expires, o.attempt_count AS sendversuche "
                "FROM contacts_mutations m "
                "LEFT JOIN contacts c ON c.id = m.target_contact_id "
                "LEFT JOIN personal_approvals a ON a.approval_id = m.approval_id "
                "LEFT JOIN personal_external_action_outbox o "
                "ON o.outbox_id = m.outbox_id "
                "WHERE m.mutation_id = ? AND m.workspace_id = ?",
                (mutation_id, workspace_id)).fetchone()
            return self._mutation(zeile) if zeile else None

    def mutation_changes(self, mutation_id: str, *, workspace_id: str
                         ) -> tuple[dict, ...]:
        """Die geplanten Feldänderungen — für die Vorschau im Freigabe-Board.

        Die Nutzlast liegt in derselben kanonischen Datenbank wie die Kontakte;
        sie wird hier **gelesen**, nicht erneut gespeichert und nie in Audit
        oder Outbox geschrieben.
        """
        with self._persistence.unit_of_work() as uow:
            zeile = uow.execute(
                "SELECT payload_json, command, target_contact_id "
                "FROM contacts_mutations WHERE mutation_id = ? "
                "AND workspace_id = ?", (mutation_id, workspace_id)).fetchone()
            if zeile is None:
                return ()
            nutzlast = json.loads(zeile["payload_json"])
            felder = nutzlast.get("fields") or {}
            vorher: dict = {}
            if zeile["target_contact_id"]:
                alt = uow.execute("SELECT * FROM contacts WHERE id = ?",
                                  (zeile["target_contact_id"],)).fetchone()
                if alt is not None:
                    vorher = dict(alt)
            return tuple(
                {"field": name, "previous": vorher.get(name), "planned": wert}
                for name, wert in sorted(felder.items()))

    # ── Freigaben ───────────────────────────────────────────────────────────
    def list_approvals(self, *, workspace_id: str,
                       state: str | None = None,
                       include_expired: bool = True,
                       now: str | None = None) -> tuple[ApprovalSummary, ...]:
        from personaljarvis.contacts.domain.models import utc_now

        jetzt = now or utc_now()
        bedingungen = ["m.workspace_id = ?", "a.module = 'contacts'"]
        werte: list[Any] = [workspace_id]
        if state:
            bedingungen.append("a.state = ?")
            werte.append(state)
        with self._persistence.unit_of_work() as uow:
            rows = uow.execute(
                f"SELECT a.*, m.command, m.mutation_id "
                f"FROM personal_approvals a "
                f"JOIN contacts_mutations m ON m.approval_id = a.approval_id "
                f"WHERE {' AND '.join(bedingungen)} "
                f"ORDER BY a.requested_at DESC, a.approval_id",
                tuple(werte)).fetchall()
            eintraege = tuple(self._approval(r, jetzt) for r in rows)
            if include_expired:
                return eintraege
            return tuple(e for e in eintraege if not e.is_expired)

    def get_approval(self, approval_id: str, *, workspace_id: str,
                     now: str | None = None) -> ApprovalSummary | None:
        from personaljarvis.contacts.domain.models import utc_now

        with self._persistence.unit_of_work() as uow:
            zeile = uow.execute(
                "SELECT a.*, m.command, m.mutation_id FROM personal_approvals a "
                "JOIN contacts_mutations m ON m.approval_id = a.approval_id "
                "WHERE a.approval_id = ? AND m.workspace_id = ?",
                (approval_id, workspace_id)).fetchone()
            return self._approval(zeile, now or utc_now()) if zeile else None

    # ── Sync-Status ─────────────────────────────────────────────────────────
    def resolve_contact_target(self, contact_id: str, *, workspace_id: str
                               ) -> tuple[str, str]:
        """Lokale Kontaktkennung → (Providerkonto, Providerkennung).

        Fail-closed: ohne externe Identität gibt es kein Ziel, und bei mehreren
        wäre unklar, welcher Rohdatensatz gemeint ist. Beides ist ein Fehler —
        nie eine Auswahl.
        """
        with self._persistence.unit_of_work() as uow:
            rows = uow.execute(
                "SELECT e.provider_account_id, e.provider_identifier "
                "FROM contact_external_ids e JOIN contacts c ON c.id = e.contact_id "
                "WHERE e.contact_id = ? AND c.workspace_id = ? "
                "ORDER BY e.provider_account_id, e.provider_identifier",
                (contact_id, workspace_id)).fetchall()
        if not rows:
            raise TargetBindingError(
                "Dieser Kontakt hat keine Provideridentität und ist deshalb "
                "kein Mutationsziel")
        if len(rows) > 1:
            raise TargetBindingError(
                "Dieser Kontakt hat mehrere Provideridentitäten; das Ziel ist "
                "nicht eindeutig")
        return rows[0]["provider_account_id"], rows[0]["provider_identifier"]

    def resolve_container_ref(self, container_ref: str) -> tuple[str, str]:
        """Maskierte Containerreferenz → (Providerkonto, Containerkennung).

        Fail-closed in beide Richtungen: kein Treffer und mehrere Treffer sind
        beides ein Fehler. Es wird **nie** der erste Treffer genommen — eine
        Kollision der Maskierung darf niemals dazu führen, dass ein Kontakt im
        falschen Container landet (ADR-0025 §2).

        Die Kandidatenmenge ist der **synchronisierte** Bestand: ein Container,
        der nie vollständig gelesen wurde, ist kein gültiges Ziel — dann fehlten
        Fähigkeiten und Feldzustände.

        Seit dem 2026-08-01 entsteht eine Zeile in `contacts_sync_state` schon
        durch das blosse Containerinventar. Die Existenz der Zeile reicht hier
        deshalb nicht mehr. Entscheidend sind die beiden Erfolgsstempel — genau
        die, aus denen der Statusvertrag `last_successful_run_at` bildet: sie
        werden ausschliesslich nach einem abgeschlossenen Lauf gesetzt, und der
        Inventarschritt setzt sie nie. Eine Regel, ein Wortlaut, beide Schichten.
        """
        from personaljarvis.contacts.api.redaction import (
            container_ref as maskieren,
        )

        with self._persistence.unit_of_work() as uow:
            rows = uow.execute(
                "SELECT DISTINCT provider_account_id, container_identifier "
                "FROM contacts_sync_state "
                "WHERE cursor_taken_at IS NOT NULL "
                "OR last_full_diff_at IS NOT NULL "
                "ORDER BY provider_account_id, container_identifier"
            ).fetchall()
        treffer = [(r["provider_account_id"], r["container_identifier"])
                   for r in rows
                   if maskieren(r["container_identifier"]) == container_ref]
        if not treffer:
            raise ContainerNotAvailable(
                "Der gewaehlte Ablageort wurde noch nicht vollstaendig "
                "synchronisiert und ist deshalb kein gueltiges Ziel.")
        if len(treffer) > 1:
            raise ContainerNotAvailable(
                "Die Containerreferenz ist nicht eindeutig; es wird nichts "
                "geraten.")
        return treffer[0]

    def sync_status(self, *, provider_account_id: str | None = None
                    ) -> tuple[SyncStatusView, ...]:
        bedingung = ""
        werte: tuple = ()
        if provider_account_id:
            bedingung = " WHERE provider_account_id = ?"
            werte = (provider_account_id,)
        with self._persistence.unit_of_work() as uow:
            rows = uow.execute(
                f"SELECT * FROM contacts_sync_state{bedingung} "
                f"ORDER BY provider_account_id, container_identifier",
                werte).fetchall()
            return tuple(SyncStatusView(
                provider_account_id=r["provider_account_id"],
                container_identifier=r["container_identifier"],
                container_type=r["container_type"],
                mode=r["mode"], circuit_state=r["circuit_state"],
                key_set_version=r["key_set_version"],
                # Der Token selbst verlaesst diese Schicht nicht.
                has_cursor=r["cursor_token"] is not None,
                cursor_taken_at=r["cursor_taken_at"],
                last_full_diff_at=r["last_full_diff_at"],
                updated_at=r["updated_at"]) for r in rows)

    # ── Hilfen ──────────────────────────────────────────────────────────────
    @staticmethod
    def _escape_like(value: str) -> str:
        return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")

    @staticmethod
    def _summary(uow, row, workspace_id: str) -> ContactSummary:
        cid = row["id"]
        zaehler = uow.execute(
            "SELECT (SELECT count(*) FROM contact_emails WHERE contact_id = ?) AS e,"
            " (SELECT count(*) FROM contact_phones WHERE contact_id = ?) AS p,"
            " (SELECT count(*) FROM contact_postal_addresses"
            "  WHERE contact_id = ?) AS a,"
            " (SELECT count(*) FROM contact_field_availability WHERE contact_id = ?"
            "  AND state = ?) AS u",
            (cid, cid, cid, cid,
             FieldAvailabilityState.UNAVAILABLE_BY_CAPABILITY.value)).fetchone()
        rollen = tuple(r["role"] for r in uow.execute(
            "SELECT role FROM contact_roles WHERE contact_id = ? "
            "AND workspace_id = ? ORDER BY role", (cid, workspace_id)))
        konten = tuple(r["provider_account_id"] for r in uow.execute(
            "SELECT DISTINCT provider_account_id FROM contact_external_ids "
            "WHERE contact_id = ? ORDER BY provider_account_id", (cid,)))
        return ContactSummary(
            id=cid, display_name=row["display_name"],
            organization_name=row["organization_name"],
            contact_type=row["contact_type"],
            is_me_card=bool(row["is_me_card"]),
            field_completeness=row["field_completeness"],
            sync_state=row["sync_state"], conflict_state=row["conflict_state"],
            roles=rollen, provider_account_ids=konten,
            email_count=zaehler["e"], phone_count=zaehler["p"],
            address_count=zaehler["a"],
            has_unavailable_fields=zaehler["u"] > 0)

    @staticmethod
    def _mutation(row) -> MutationSummary:
        return MutationSummary(
            mutation_id=row["mutation_id"], command=row["command"],
            state=row["state"], outcome=row["outcome"],
            initiation_context=row["initiation_context"], actor=row["actor"],
            correlation_id=row["correlation_id"],
            provider_account_id=row["provider_account_id"],
            target_contact_id=row["target_contact_id"],
            target_display_name=row["ziel_name"],
            container_identifier=row["container_identifier"],
            expected_revision=row["expected_revision"],
            # **Kanonisch die Outbox.** Sie erhoeht den Zaehler beim Claim,
            # also genau dann, wenn ein Sendversuch beginnt. Die gleichnamige
            # Spalte im Vorgang wird dabei mitgeschrieben und ist ein
            # Abbild — nie eine zweite Wahrheit. Fehlt der Outbox-Eintrag
            # (Vorgang ohne Warteschlange), gilt der Vorgangswert.
            attempt_count=(row["sendversuche"]
                           if row["sendversuche"] is not None
                           else row["attempt_count"]),
            last_error_code=row["last_error_code"],
            created_at=row["created_at"], approved_at=row["approved_at"],
            completed_at=row["completed_at"], approval_id=row["approval_id"],
            approval_state=row["a_state"], approval_expires_at=row["a_expires"],
            payload_digest=row["payload_digest"],
            preview_digest=row["preview_digest"])

    @staticmethod
    def _approval(row, jetzt: str) -> ApprovalSummary:
        abgelaufen = (row["state"] == "awaiting_approval"
                      and jetzt >= row["expires_at"])
        return ApprovalSummary(
            approval_id=row["approval_id"], mutation_id=row["mutation_id"],
            command=row["command"], state=row["state"],
            initiation_context=row["initiation_context"], actor=row["actor"],
            correlation_id=row["correlation_id"],
            requested_at=row["requested_at"], expires_at=row["expires_at"],
            decided_at=row["decided_at"], decision_actor=row["decision_actor"],
            preview_digest=row["preview_digest"], is_expired=abgelaufen)
