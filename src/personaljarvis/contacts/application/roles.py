"""Lokale Kategorien und Rollen (R0, Plan §8).

Rollen sind **rein lokal**: sie werden nie zum Provider gepusht und lösen
keine externe Wirkung aus. Damit sind sie nach 10 §1 R0 und brauchen weder
Freigabe noch Outbox — aber sehr wohl Workspace-Isolation und Audit.

Sie sind die Grundlage der UI-Kategorien **Privat · Arbeit · HV · Mieter ·
Vermieter** (Plan §10). Die Menge ist bewusst **nicht** fest verdrahtet: der
Nutzer darf eigene Kategorien vergeben.
"""

from __future__ import annotations

from personaljarvis.base.audit import AuditStage, AuditTrail
from personaljarvis.contacts.application.errors import (
    InvalidCommand,
    MutationNotFound,
)
from personaljarvis.contacts.domain.models import utc_now

__all__ = ["MAX_ROLE_LENGTH", "ContactsRoleService"]

#: Obergrenze einer Kategoriebezeichnung. Verhindert, dass ein Freitextfeld
#: zum Ablageort beliebiger Daten wird.
MAX_ROLE_LENGTH = 64


class ContactsRoleService:
    """Setzt und entfernt lokale Kategorien. Kein Provider-Zugriff."""

    def __init__(self, persistence) -> None:
        self._persistence = persistence

    @staticmethod
    def _validate(role: str) -> str:
        bereinigt = " ".join((role or "").split())
        if not bereinigt:
            raise InvalidCommand("Kategorie darf nicht leer sein")
        if len(bereinigt) > MAX_ROLE_LENGTH:
            raise InvalidCommand(
                f"Kategorie ist laenger als {MAX_ROLE_LENGTH} Zeichen")
        return bereinigt

    def _require_contact(self, uow, contact_id: str, workspace_id: str) -> None:
        zeile = uow.execute(
            "SELECT workspace_id FROM contacts WHERE id = ?",
            (contact_id,)).fetchone()
        if zeile is None or zeile["workspace_id"] != workspace_id:
            raise MutationNotFound("Kontakt existiert nicht in diesem Workspace")

    def assign(self, contact_id: str, role: str, *, workspace_id: str,
               actor: str) -> tuple[str, ...]:
        bereinigt = self._validate(role)
        with self._persistence.unit_of_work() as uow:
            self._require_contact(uow, contact_id, workspace_id)
            uow.execute(
                "INSERT OR IGNORE INTO contact_roles (contact_id, workspace_id, "
                "role, assigned_at) VALUES (?,?,?,?)",
                (contact_id, workspace_id, bereinigt, utc_now()))
            AuditTrail(uow, module="contacts").record(
                AuditStage.MUTATION_COMPLETED, subject_type="contacts.role",
                subject_id=contact_id,
                facts={"action": "assign", "role": bereinigt, "actor": actor,
                       "riskClass": "R0", "local": True})
            return self._roles(uow, contact_id, workspace_id)

    def remove(self, contact_id: str, role: str, *, workspace_id: str,
               actor: str) -> tuple[str, ...]:
        bereinigt = self._validate(role)
        with self._persistence.unit_of_work() as uow:
            self._require_contact(uow, contact_id, workspace_id)
            uow.execute(
                "DELETE FROM contact_roles WHERE contact_id = ? "
                "AND workspace_id = ? AND role = ?",
                (contact_id, workspace_id, bereinigt))
            AuditTrail(uow, module="contacts").record(
                AuditStage.MUTATION_COMPLETED, subject_type="contacts.role",
                subject_id=contact_id,
                facts={"action": "remove", "role": bereinigt, "actor": actor,
                       "riskClass": "R0", "local": True})
            return self._roles(uow, contact_id, workspace_id)

    @staticmethod
    def _roles(uow, contact_id: str, workspace_id: str) -> tuple[str, ...]:
        rows = uow.execute(
            "SELECT role FROM contact_roles WHERE contact_id = ? "
            "AND workspace_id = ? ORDER BY role",
            (contact_id, workspace_id)).fetchall()
        return tuple(r["role"] for r in rows)
