"""Wiederbelebung fälschlich getombstoneter Kontakte.

Anlass: Am 2026-07-30 setzte ein Voll-Diff 116 Kontakte lokal auf gelöscht,
weil eine Enumeration `count=0, complete=true` meldete. Bei Apple selbst ist
nichts passiert — die Provider-Identifier sind unverändert, und dieselben
Datensätze liegen weiter im Store.

Genau darauf setzt dieser Dienst auf: **wiedergefundene Datensätze bekommen
keine neue lokale Identität.** Sie werden auf demselben kanonischen Datensatz
reaktiviert. Ein Neuimport hätte 116 neue Kontakt-IDs erzeugt und alles
weggeworfen, was lokal daran hängt — Rollen, Freigaben, Auditbezüge.

Verbindliche Eigenschaften:

* **Nie automatisch.** Kein Start, kein Seitenaufruf, kein Timer.
* **Zuerst prüfen, dann schreiben.** Sämtliche Container werden vollständig
  aufgezählt und validiert, bevor auch nur eine Zeile angefasst wird; für die
  Löschbasis gilt derselbe Schutz wie im Voll-Diff.
* **Alles oder nichts.** Ein Fehler rollt den gesamten Lauf zurück.
* **Keine harte Löschung.** Ein irrtümlicher Tombstone wird als abgeglichen
  markiert, nicht entfernt: die Löschung *hat* stattgefunden, sie war nur
  falsch begründet, und dieser Beleg bleibt.
* **Cursor zuletzt.** Der Sync-Zustand wird erst nach dem erfolgreichen
  Gesamt-Commit fortgeschrieben.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field

from personaljarvis.contacts.bridge.errors import BridgeError
from personaljarvis.contacts.domain.enums import CircuitState, SyncMode
from personaljarvis.contacts.domain.models import utc_now
from personaljarvis.contacts.sync.audit import (
    OUTCOME_ABORTED,
    OUTCOME_COMMITTED,
    SyncAuditRecord,
    SyncAuditWriter,
)
from personaljarvis.contacts.sync.errors import (
    AuthorizationRequired,
    SyncError,
)

__all__ = [
    "ContactsRecoveryService",
    "RecoveryResult",
    "RecoveryNotApplicable",
    "RecoveryBusy",
    "RECONCILED_REASON",
    "RECOVERABLE_REASONS",
]

#: Grund, mit dem ein irrtümlicher Tombstone als abgeglichen markiert wird.
#: Der Datensatz bleibt — was falsch war, war die Begründung, nicht das
#: Ereignis.
RECONCILED_REASON = "reconciled_after_suspicious_empty_enumeration"

#: Der **einzige** Löschgrund, den diese Wiederherstellung anfassen darf.
#: Sie ist die Antwort auf einen konkret erkannten Fehlerzustand, kein
#: allgemeines Reparaturwerkzeug — ein Tombstone aus einem echten
#: Löschereignis bleibt unberührt.
RECOVERABLE_REASONS = frozenset({"absent_in_complete_enumeration"})


class RecoveryNotApplicable(Exception):
    """Die lokalen Vorbedingungen tragen keinen Wiederherstellungslauf.

    Trägt eine stabile technische Kennung und nie einen Kontaktwert.
    """

    retryable = False

    def __init__(self, technical_code: str, message: str) -> None:
        super().__init__(message)
        self.technical_code = technical_code


class RecoveryBusy(Exception):
    """Es läuft bereits ein Wiederherstellungslauf."""

    retryable = True
    technical_code = "recovery_busy"


@dataclass(frozen=True)
class RecoveryResult:
    """Ergebnis — aggregiert, PII-frei."""

    succeeded: bool
    containers: int = 0
    examined: int = 0
    reactivated: int = 0
    updated: int = 0
    still_absent: int = 0
    tombstones_reconciled: int = 0
    error_class: str | None = None
    detail: str = ""
    completed_at: str = ""
    audit_events: tuple[str, ...] = field(default_factory=tuple)


class ContactsRecoveryService:
    """Reaktiviert lokal gelöschte Kontakte, die der Provider noch kennt."""

    #: Prozessweit — zwei Instanzen dürfen nicht gleichzeitig reparieren.
    _riegel = threading.Lock()

    def __init__(self, sync_service, persistence, *, workspace_id: str,
                 provider_account_id: str) -> None:
        #: Der Sync-Dienst liefert Inventar, Enumeration und Prüfungen — die
        #: Schutzregeln werden hier nicht ein zweites Mal nachgebaut.
        self._sync = sync_service
        self._persistence = persistence
        self._workspace_id = workspace_id
        self._provider_account_id = provider_account_id

    # ── Lokale Vorprüfung: vor jedem Store-Zugriff ─────────────────────────
    def check_preconditions(self, *, sync_running: bool = False) -> int:
        """Prüft **rein lokal**, ob ein Lauf überhaupt zulässig ist.

        Kein Sidecar, keine Enumeration, keine Änderung. Erst wenn alles hier
        trägt, darf der Kontakte-Store überhaupt berührt werden — eine
        Reparatur, die auf einer falschen Annahme startet, ist teurer als gar
        keine.

        Gibt die Anzahl wiederherstellbarer Tombstones zurück.
        """
        if sync_running:
            raise RecoveryNotApplicable(
                "sync_in_progress",
                "Waehrend eines laufenden Abgleichs wird nicht repariert")

        with self._persistence.unit_of_work() as uow:
            gruende = dict(uow.execute(
                "SELECT reason, COUNT(*) FROM contacts_tombstones "
                "WHERE provider_account_id = ? GROUP BY reason",
                (self._provider_account_id,)).fetchall())
            frueher = uow.execute(
                "SELECT COUNT(*) FROM contacts_sync_audit "
                "WHERE provider_account_id = ? AND mode = 'recovery' "
                "AND outcome = 'committed'",
                (self._provider_account_id,)).fetchone()[0]

        if not gruende:
            raise RecoveryNotApplicable(
                "no_tombstones", "Es gibt nichts wiederherzustellen")

        wiederherstellbar = sum(n for grund, n in gruende.items()
                                if grund in RECOVERABLE_REASONS)
        fremd = {g for g in gruende if g not in RECOVERABLE_REASONS
                 and g != RECONCILED_REASON}
        if fremd:
            # Ein Tombstone aus einem echten Löschereignis darf hier nicht
            # mitrepariert werden — das waere eine stille Wiederauferstehung.
            raise RecoveryNotApplicable(
                "unexpected_tombstone_reason",
                "Es liegen Loeschungen vor, die nicht zu diesem Vorfall gehoeren")
        if wiederherstellbar == 0:
            raise RecoveryNotApplicable(
                "already_reconciled",
                "Alle betroffenen Loeschungen sind bereits abgeglichen")
        if frueher:
            raise RecoveryNotApplicable(
                "already_recovered",
                "Ein Wiederherstellungslauf wurde bereits abgeschlossen")
        if not (self._workspace_id and self._provider_account_id):
            raise RecoveryNotApplicable(
                "ambiguous_scope", "Workspace oder Providerkonto fehlt")
        return wiederherstellbar

    def recover(self, *, sync_running: bool = False) -> RecoveryResult:
        """Ein Lauf, ausdrücklich ausgelöst — nie automatisch."""
        if not self._riegel.acquire(blocking=False):
            raise RecoveryBusy("Es laeuft bereits ein Wiederherstellungslauf")
        try:
            self.check_preconditions(sync_running=sync_running)
            return self._recover_unter_riegel()
        finally:
            self._riegel.release()

    def _recover_unter_riegel(self) -> RecoveryResult:
        audit: list[str] = ["recovery.started"]
        spur = SyncAuditRecord(workspace_id=self._workspace_id,
                               provider_account_id=self._provider_account_id,
                               mode="recovery")
        try:
            container = self._sync.inventory_containers()
            spur.container_count = len(container)
            if not container:
                raise SyncError("Kein Container im Inventar")

            # Phase 1 — ausschliesslich lesen und prüfen.
            gelesen = []
            for eintrag in container:
                enumeration = self._sync.enumerate_validated(
                    eintrag.identifier, spur=spur)
                gelesen.append((eintrag.identifier, enumeration))
            audit.append("recovery.enumeration.complete")
        except (SyncError, BridgeError, AuthorizationRequired) as exc:
            with self._persistence.unit_of_work() as uow:
                spur.error_class = type(exc).__name__
                SyncAuditWriter(uow).write(spur.finish(OUTCOME_ABORTED))
            audit.append("recovery.aborted")
            return RecoveryResult(succeeded=False,
                                  error_class=type(exc).__name__,
                                  detail=type(exc).__name__,
                                  completed_at=utc_now(),
                                  audit_events=tuple(audit))

        return self._persist(gelesen, audit, spur)

    def _persist(self, gelesen, audit: list[str],
                 spur: SyncAuditRecord) -> RecoveryResult:
        """Phase 2 — eine Transaktion, ein Abschluss."""
        jetzt = utc_now()
        geprueft = reaktiviert = aktualisiert = abgeglichen = 0

        with self._persistence.unit_of_work() as uow:
            repos = self._persistence.repositories(uow)
            for kennung, enumeration in gelesen:
                for roh in enumeration.contacts:
                    geprueft += 1
                    contact_id = repos.external_ids.find_contact_id(
                        self._provider_account_id, roh.provider_identifier)
                    if contact_id is None:
                        # Unbekannt — der Wiederbelebung ist das kein Fall.
                        # Ein Import gehört in den Sync, nicht hierher.
                        continue
                    bestand = repos.contacts.get(contact_id)
                    if bestand is None:
                        continue
                    if bestand.is_tombstone:
                        # **Dieselbe** Kontakt-ID: alles, was lokal daran
                        # hängt, bleibt bestehen.
                        uow.execute(
                            "UPDATE contacts SET is_tombstone = 0, "
                            "deleted_at = NULL, last_seen_at = ?, "
                            "updated_at = ? WHERE id = ?",
                            (jetzt, jetzt, contact_id))
                        reaktiviert += 1
                        abgeglichen += self._reconcile_tombstone(
                            uow, roh.provider_identifier, jetzt)
                    else:
                        aktualisiert += 1

            self._advance_state(repos, gelesen, jetzt)
            spur.reactivated = reaktiviert
            spur.updated = aktualisiert
            SyncAuditWriter(uow).write(spur.finish(OUTCOME_COMMITTED))

        audit.extend(("recovery.reactivated", "recovery.succeeded"))
        offen = self._offene_tombstones()
        return RecoveryResult(
            succeeded=True, containers=len(gelesen), examined=geprueft,
            reactivated=reaktiviert, updated=aktualisiert,
            still_absent=offen, tombstones_reconciled=abgeglichen,
            completed_at=jetzt, audit_events=tuple(audit))

    def _reconcile_tombstone(self, uow, provider_identifier: str,
                             jetzt: str) -> int:
        """Markiert den irrtümlichen Tombstone als abgeglichen.

        Keine harte Löschung: dass der Datensatz einmal als abwesend gewertet
        wurde, ist ein Ereignis. Falsch war die Begründung — und genau die wird
        korrigiert, damit der Beleg lesbar bleibt.
        """
        cursor = uow.execute(
            "UPDATE contacts_tombstones SET reason = ?, retain_until = ? "
            "WHERE provider_account_id = ? AND provider_identifier = ? "
            "AND reason != ?",
            (RECONCILED_REASON, jetzt, self._provider_account_id,
             provider_identifier, RECONCILED_REASON))
        return cursor.rowcount or 0

    def _advance_state(self, repos, gelesen, jetzt: str) -> None:
        """Sync-Zustand **zuletzt** — nach allem Fachlichen.

        Der Modus bleibt `full_diff_required`: der nächste gewöhnliche Lauf
        soll auf einem frisch geprüften Bestand aufsetzen, nicht auf einem
        Cursor aus der Zeit vor der Reparatur.
        """
        for kennung, _ in gelesen:
            vorher = repos.sync_state.get(self._provider_account_id, kennung)
            if vorher is None:
                continue
            repos.sync_state.upsert(type(vorher)(
                provider_account_id=vorher.provider_account_id,
                container_identifier=vorher.container_identifier,
                key_set_version=vorher.key_set_version,
                mode=SyncMode.FULL_DIFF_REQUIRED.value,
                cursor_token=None, cursor_taken_at=None,
                last_full_diff_at=vorher.last_full_diff_at,
                circuit_state=CircuitState.CLOSED.value, updated_at=jetzt))

    def _offene_tombstones(self) -> int:
        with self._persistence.unit_of_work() as uow:
            zeile = uow.execute(
                "SELECT COUNT(*) FROM contacts_tombstones "
                "WHERE provider_account_id = ? AND reason != ?",
                (self._provider_account_id, RECONCILED_REASON)).fetchone()
        return zeile[0] if zeile else 0
