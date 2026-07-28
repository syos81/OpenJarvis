"""Orchestrator der Lese-Synchronisation (Plan §6).

Was dieser Dienst zusichert:

* **Kein Lauf startet von selbst.** Es gibt keinen Timer, keinen Hintergrund-
  Thread und keinen Start beim Import oder beim Modulstart. Jeder Lauf ist ein
  ausdrücklicher Aufruf (Gate B, Plan §13).
* **Kein Sidecarstart.** Der Dienst bekommt einen bereits gestarteten Client;
  er startet, beendet und autorisiert nichts. `requestAuthorization` ruft er
  **nie** auf — die Autorisierung ist eine Nutzeraktion (Plan §8).
* **Providerlesen ausserhalb der Transaktion.** Erst wird vollständig gelesen,
  dann wird in **einer** UnitOfWork geschrieben. Damit hängt keine
  Schreibsperre an einem langsamen Fremdprozess, und ein abgebrochener Lauf
  hinterlässt keinen Teilbestand.
* **Kein stiller Voll-Diff.** Wird der Delta-Pfad untragfähig, endet der Lauf
  mit `requires_full_diff` und der Modus wird persistiert. Der Voll-Diff ist
  dann der **nächste ausdrückliche** Aufruf, keine verdeckte Eskalation.

Reihenfolge bei Vollaufnahmen — bewusst **Cursor zuerst, dann Enumeration**:
eine Änderung zwischen beiden Schritten wird dadurch beim nächsten Delta
erneut gemeldet und noch einmal angewandt. Andersherum ginge sie verloren.
Doppelt anwenden ist folgenlos, verlieren nicht.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Protocol, Sequence

from personaljarvis.base.db.unit_of_work import UnitOfWork
from personaljarvis.contacts.bridge import protocol
from personaljarvis.contacts.bridge.client import ContactsBridgeClient
from personaljarvis.contacts.bridge.errors import (
    BridgeError,
    BridgeOperationError,
    BridgeProcessError,
)
from personaljarvis.contacts.bridge.models import (
    AuthorizationStatus,
    BridgeContact,
    ChangeEvent,
    ChangeEventType,
    ContainerInfo,
    EnumerationResult,
)
from personaljarvis.contacts.domain.enums import CircuitState, SyncMode
from personaljarvis.contacts.domain.models import (
    Contact,
    ContactSyncState,
    ContactTombstone,
    utc_now,
)
from personaljarvis.contacts.sync.echo import EchoSuppressionLedger
from personaljarvis.contacts.sync.errors import (
    AuthorizationRequired,
    CursorRejected,
    FullDiffRequired,
    IncompleteEnumeration,
    KeySetVersionChanged,
    SyncError,
    UnknownChangeEvent,
)
from personaljarvis.contacts.sync.mapper import (
    content_equals,
    map_bridge_contact,
    merge_into_existing,
)
from personaljarvis.contacts.sync.state import (
    CursorState,
    SyncRunKind,
    SyncRunResult,
    derive_cursor_state,
)

__all__ = [
    "ContactsSyncService",
    "SyncPersistence",
    "TOMBSTONE_REASON_ABSENT",
    "TOMBSTONE_REASON_EVENT",
]

#: Grund eines Tombstones aus einem Voll-Diff: der Datensatz fehlte in einer
#: **vollständigen** Enumeration. Nie aus einer abgebrochenen.
TOMBSTONE_REASON_ABSENT = "absent_in_complete_enumeration"
#: Grund aus einem ausdrücklichen Löschereignis des Providers.
TOMBSTONE_REASON_EVENT = "provider_delete_event"

#: Ergebnis eines einzelnen Schreibvorgangs.
IMPORTED, UPDATED, UNCHANGED = "imported", "updated", "unchanged"


class SyncPersistence(Protocol):
    """Der Ausschnitt des Modullebenszyklus, den der Dienst braucht.

    `ContactsModule` erfüllt diesen Vertrag strukturell; der Dienst importiert
    den Lebenszyklus ausdrücklich **nicht** (sonst entstünde ein Zyklus,
    sobald der Lebenszyklus den Dienst bereitstellt).
    """

    def unit_of_work(self) -> UnitOfWork: ...

    def repositories(self, uow: UnitOfWork): ...


class ContactsSyncService:
    """Initialimport, Delta-Sync und Voll-Diff für **einen** Providerzugang."""

    def __init__(self, client: ContactsBridgeClient, persistence: SyncPersistence,
                 *, workspace_id: str, provider_account_id: str) -> None:
        self._client = client
        self._persistence = persistence
        self._workspace_id = workspace_id
        self._provider_account_id = provider_account_id

    # ── Vorbedingungen ──────────────────────────────────────────────────────
    def _require_started(self) -> None:
        if self._client.handshake is None:
            raise SyncError(
                "Die Bridge ist nicht gestartet; der Sync-Dienst startet "
                "ausdrücklich keinen Prozess"
            )

    def _require_authorized(self) -> None:
        """Prüft den Status — und fordert ihn **nie** an.

        `authorizationStatus` ist kontaktfrei: der Sidecar benutzt dafür
        ausschliesslich die statische Klassenabfrage.
        """
        self._require_started()
        status = self._client.authorization_status()
        if status is not AuthorizationStatus.AUTHORIZED:
            raise AuthorizationRequired(
                f"Der Providerzugang ist nicht autorisiert (Status: {status.value})"
            )

    # ── Containerinventar ───────────────────────────────────────────────────
    def inventory_containers(self) -> tuple[ContainerInfo, ...]:
        """Liest das Containerinventar.

        Legt **keine** Sync-Zustände an: eine Zeile in `contacts_sync_state`
        entsteht erst mit dem ersten erfolgreichen Lauf. Sonst wäre nach dem
        blossen Inventar nicht mehr unterscheidbar, ob ein Container schon
        importiert wurde.
        """
        self._require_authorized()
        return self._client.containers()

    # ── Öffentliche Läufe ───────────────────────────────────────────────────
    def sync(self, container_identifier: str) -> SyncRunResult:
        """Wählt den passenden Lauf anhand des persistierten Zustands.

        Ausdrücklich ohne Eskalation innerhalb eines Aufrufs: wird der Delta-
        Pfad untragfähig, endet dieser Lauf und der **nächste** Aufruf macht
        den Voll-Diff. So bleibt jeder Voll-Diff eine sichtbare Entscheidung.
        """
        zustand = self._load_state(container_identifier)
        cursor = derive_cursor_state(zustand)
        if zustand is None:
            return self.initial_import(container_identifier)
        if cursor in (CursorState.FULL_DIFF_REQUIRED, CursorState.ABSENT):
            return self.full_diff(container_identifier)
        return self.delta_sync(container_identifier)

    def initial_import(self, container_identifier: str) -> SyncRunResult:
        """Erste Vollaufnahme eines Containers."""
        return self._snapshot_run(container_identifier, SyncRunKind.INITIAL_IMPORT)

    def full_diff(self, container_identifier: str) -> SyncRunResult:
        """Vollabgleich inklusive Löschmenge — der einzige Weg zu Tombstones
        aus Abwesenheit."""
        return self._snapshot_run(container_identifier, SyncRunKind.FULL_DIFF)

    # ── Vollaufnahme (Initialimport und Voll-Diff teilen den Ablauf) ────────
    def _snapshot_run(self, container_identifier: str,
                      kind: SyncRunKind) -> SyncRunResult:
        audit: list[str] = [f"sync.{kind.value}.started"]
        try:
            self._require_authorized()

            # 1. Cursor zuerst. Ereignisse werden hier bewusst verworfen: der
            #    Bestand kommt gleich vollständig aus der Enumeration.
            baseline_token: str | None = None
            key_set_version: int | None = None
            if self._client.capabilities.change_history_supported:
                baseline = self._client.changes()
                baseline_token = baseline.current_token or None
                key_set_version = baseline.key_set_version
                audit.append("sync.cursor.baseline_taken")
            else:
                audit.append("sync.cursor.unavailable")

            # 2. Vollständige Enumeration.
            enumeration = self._client.enumerate(
                container_identifier=container_identifier)
            if not enumeration.usable_as_delete_basis:
                raise IncompleteEnumeration(
                    "Enumeration ist unvollständig oder die Zählung weicht ab; "
                    "der Lauf wird verworfen"
                )
            audit.append("sync.enumeration.complete")
            if key_set_version is None:
                key_set_version = enumeration.key_set_version

        except (SyncError, BridgeError) as exc:
            # Ein gescheiterter Lauf hinterlaesst keinen Teilbestand: es wurde
            # bis hierhin ausschliesslich gelesen.
            return self._failed(kind, container_identifier, exc, audit,
                                requires_full_diff=True)

        # 3. Schreiben — genau eine Transaktion, genau ein Abschluss.
        return self._persist_snapshot(container_identifier, kind, enumeration,
                                      baseline_token, key_set_version, audit)

    def _persist_snapshot(self, container_identifier: str, kind: SyncRunKind,
                          enumeration: EnumerationResult,
                          baseline_token: str | None, key_set_version: int,
                          audit: list[str]) -> SyncRunResult:
        jetzt = utc_now()
        imported = updated = unchanged = tombstoned = 0

        with self._persistence.unit_of_work() as uow:
            repos = self._persistence.repositories(uow)
            lokal = self._local_index(repos, container_identifier)
            gesehen: set[str] = set()

            for roh in enumeration.contacts:
                gesehen.add(roh.provider_identifier)
                ergebnis, _ = self._write_contact(
                    repos, roh, container_identifier,
                    lokal.get(roh.provider_identifier), jetzt)
                if ergebnis == IMPORTED:
                    imported += 1
                elif ergebnis == UPDATED:
                    updated += 1
                else:
                    unchanged += 1

            # Löschmenge — **nur** aus einer vollständigen Enumeration.
            for pid, contact_id in lokal.items():
                if pid in gesehen:
                    continue
                self._tombstone(repos, contact_id, pid, TOMBSTONE_REASON_ABSENT,
                                jetzt)
                tombstoned += 1

            if tombstoned:
                audit.append("sync.tombstones.created")

            self._upsert_state(repos, container_identifier,
                               cursor_token=baseline_token,
                               cursor_taken_at=jetzt if baseline_token else None,
                               last_full_diff_at=jetzt,
                               key_set_version=str(key_set_version),
                               mode=(SyncMode.DELTA if baseline_token
                                     else SyncMode.FULL_DIFF_REQUIRED),
                               circuit_state=CircuitState.CLOSED, updated_at=jetzt)

        if baseline_token:
            audit.append("sync.cursor.advanced")
        audit.append(f"sync.{kind.value}.succeeded")
        return SyncRunResult(
            kind=kind, succeeded=True,
            cursor_state=(CursorState.ACTIVE if baseline_token
                          else CursorState.FULL_DIFF_REQUIRED),
            provider_account_id=self._provider_account_id,
            container_identifier=container_identifier,
            imported=imported, updated=updated, unchanged=unchanged,
            tombstoned=tombstoned, events_processed=0,
            cursor_advanced=bool(baseline_token),
            requires_full_diff=not baseline_token,
            audit_events=tuple(audit),
        )

    # ── Delta ───────────────────────────────────────────────────────────────
    def delta_sync(self, container_identifier: str) -> SyncRunResult:
        """Inkrementeller Lauf über die Änderungshistorie des Providers."""
        audit: list[str] = ["sync.delta.started"]
        kind = SyncRunKind.DELTA
        try:
            self._require_authorized()
            zustand = self._load_state(container_identifier)
            cursor = derive_cursor_state(zustand)
            if zustand is None or cursor is not CursorState.ACTIVE:
                raise FullDiffRequired(
                    f"Der Cursor ist nicht tragfähig (Zustand: {cursor.value})")
            assert zustand.cursor_token is not None

            container = self._client.containers()
            if not any(c.identifier == container_identifier for c in container):
                raise FullDiffRequired(
                    "Der Container ist im Providerinventar nicht mehr enthalten")
            # Bei genau einem Container ist jedes Ereignis eindeutig zuzuordnen;
            # sonst braucht ein Ereignis eine ausdrückliche Containerangabe.
            eindeutig = len(container) == 1

            try:
                aenderungen = self._client.changes(
                    starting_token=zustand.cursor_token)
            except BridgeOperationError as exc:
                if exc.code == protocol.ErrorCode.INVALID_TOKEN:
                    raise CursorRejected(
                        "Der gespeicherte Cursor wurde abgelehnt") from exc
                raise

            if aenderungen.key_set_version != int(zustand.key_set_version or -1):
                raise KeySetVersionChanged(
                    "Der Schlüsselsatz des Providers hat gewechselt")
            if aenderungen.requires_full_diff:
                audit.append("sync.delta.drop_everything")
                raise FullDiffRequired(
                    "Der Provider hat die Historie verworfen (dropEverything)")
            for ereignis in aenderungen.events:
                if ereignis.type is ChangeEventType.OTHER:
                    raise UnknownChangeEvent(
                        "Unbekannter Ereignistyp; es wird nicht geraten")

        except (SyncError, BridgeError) as exc:
            # Ein gescheiterter Lauf hinterlaesst keinen Teilbestand: es wurde
            # bis hierhin ausschliesslich gelesen.
            return self._failed(kind, container_identifier, exc, audit,
                                requires_full_diff=True)

        return self._apply_events(container_identifier, aenderungen.events,
                                  aenderungen.current_token,
                                  aenderungen.key_set_version, eindeutig, audit)

    def _apply_events(self, container_identifier: str,
                      events: Sequence[ChangeEvent], current_token: str,
                      key_set_version: int, eindeutig: bool,
                      audit: list[str]) -> SyncRunResult:
        jetzt = utc_now()
        imported = updated = unchanged = tombstoned = verarbeitet = 0

        with self._persistence.unit_of_work() as uow:
            repos = self._persistence.repositories(uow)
            lokal = self._local_index(repos, container_identifier)
            echo = EchoSuppressionLedger.from_repository(repos.mutations)
            if not echo.is_empty:
                audit.append("sync.echo.ledger_active")

            for ereignis in events:
                pid = ereignis.provider_identifier
                if echo.suppresses(pid):
                    # Das eigene Schreiben kommt nicht als Fremdänderung zurück.
                    audit.append("sync.echo.suppressed")
                    continue

                if ereignis.type is ChangeEventType.DELETE:
                    contact_id = lokal.get(pid) if pid else None
                    if contact_id is None:
                        unchanged += 1        # nichts Lokales zu löschen
                    else:
                        self._tombstone(repos, contact_id, pid,
                                        TOMBSTONE_REASON_EVENT, jetzt)
                        lokal.pop(pid, None)
                        tombstoned += 1
                    verarbeitet += 1
                    continue

                if not self._belongs_here(ereignis, container_identifier,
                                          lokal, eindeutig):
                    continue

                roh = self._fetch(pid)
                if roh is None:
                    # Zwischen Ereignis und Abruf verschwunden: das zugehörige
                    # Löschereignis folgt; hier wird nichts geraten.
                    unchanged += 1
                    verarbeitet += 1
                    continue

                ergebnis, geschrieben = self._write_contact(
                    repos, roh, container_identifier,
                    lokal.get(roh.provider_identifier), jetzt)
                if ergebnis == IMPORTED:
                    # Ein zweites Ereignis zum selben Datensatz im selben Lauf
                    # trifft jetzt auf die Zuordnung und legt nichts doppelt an.
                    lokal[roh.provider_identifier] = geschrieben
                    imported += 1
                elif ergebnis == UPDATED:
                    updated += 1
                else:
                    unchanged += 1
                verarbeitet += 1

            self._upsert_state(repos, container_identifier,
                               cursor_token=current_token or None,
                               cursor_taken_at=jetzt,
                               last_full_diff_at=None, keep_full_diff_at=True,
                               key_set_version=str(key_set_version),
                               mode=SyncMode.DELTA,
                               circuit_state=CircuitState.CLOSED, updated_at=jetzt)

        audit.extend(("sync.cursor.advanced", "sync.delta.succeeded"))
        return SyncRunResult(
            kind=SyncRunKind.DELTA, succeeded=True,
            cursor_state=CursorState.ACTIVE,
            provider_account_id=self._provider_account_id,
            container_identifier=container_identifier,
            imported=imported, updated=updated, unchanged=unchanged,
            tombstoned=tombstoned, events_processed=verarbeitet,
            cursor_advanced=True, requires_full_diff=False,
            audit_events=tuple(audit),
        )

    def _belongs_here(self, ereignis: ChangeEvent, container_identifier: str,
                      lokal: dict[str, str], eindeutig: bool) -> bool:
        """Ob ein Add-/Update-Ereignis zum synchronisierten Container gehört.

        Die Änderungshistorie ist speicherweit, der Cursor aber je Container
        geführt. `add` trägt die Containerangabe, `update` nicht — dort
        entscheidet die lokale Zuordnung. Bleibt die Zuordnung offen, wird
        nicht geraten: der Aufrufer läuft in den Voll-Diff.
        """
        if eindeutig:
            return True
        pid = ereignis.provider_identifier
        if ereignis.container_identifier:
            return ereignis.container_identifier == container_identifier
        return bool(pid) and pid in lokal

    def _fetch(self, provider_identifier: str | None) -> BridgeContact | None:
        if not provider_identifier:
            return None
        try:
            return self._client.get(provider_identifier)
        except BridgeOperationError as exc:
            if exc.code == protocol.ErrorCode.NOT_FOUND:
                return None
            raise

    # ── Schreiben eines Datensatzes ─────────────────────────────────────────
    def _write_contact(self, repos, roh: BridgeContact, container_identifier: str,
                       contact_id: str | None,
                       jetzt: str) -> tuple[str, str]:
        """Legt an oder aktualisiert.

        Gibt das Ergebnis (`IMPORTED`/`UPDATED`/`UNCHANGED`) und die
        Kontaktkennung zurück, unter der geschrieben wurde.
        """
        abbildung = map_bridge_contact(
            roh, workspace_id=self._workspace_id,
            provider_account_id=self._provider_account_id,
            container_identifier=container_identifier,
            contact_id=contact_id, observed_at=jetzt)

        if contact_id is None:
            repos.contacts.add(abbildung.contact)
            self._write_side_records(repos, abbildung.contact.id, abbildung)
            return IMPORTED, abbildung.contact.id

        bestand: Contact | None = repos.contacts.get(contact_id)
        if bestand is None:
            # Verwaiste Zuordnung: die externe Identität zeigt ins Leere. Der
            # Datensatz wird neu angelegt, die Zuordnung danach umgehängt.
            neu = map_bridge_contact(
                roh, workspace_id=self._workspace_id,
                provider_account_id=self._provider_account_id,
                container_identifier=container_identifier, observed_at=jetzt)
            repos.contacts.add(neu.contact)
            self._write_side_records(repos, neu.contact.id, neu)
            return IMPORTED, neu.contact.id

        if bestand.is_me_card:
            # Die Me-Karte ist in v1 schreibgeschützt (Plan §7.3). Ihre
            # Zuordnung und Feldzustände bleiben aktuell, ihr Inhalt nicht.
            self._write_side_records(repos, contact_id, abbildung)
            return UNCHANGED, contact_id

        zusammengefuehrt = merge_into_existing(bestand, abbildung, roh)
        self._write_side_records(repos, contact_id, abbildung)
        if content_equals(bestand, zusammengefuehrt):
            return UNCHANGED, contact_id

        repos.contacts.update(zusammengefuehrt)
        return UPDATED, contact_id

    @staticmethod
    def _write_side_records(repos, contact_id: str, abbildung) -> None:
        """Externe Identität und Feldzustände liegen in eigenen Tabellen.

        `ContactRepository.add/update` schreibt sie nicht mit — deshalb hier
        ausdrücklich über ihre eigenen Verträge.
        """
        repos.external_ids.upsert(contact_id, abbildung.external_identifier)
        repos.field_availability.set_for_contact(contact_id,
                                                 abbildung.field_availability)

    def _tombstone(self, repos, contact_id: str, provider_identifier: str | None,
                   reason: str, jetzt: str) -> None:
        """Löscht lokal weich und hält die Löschung nachvollziehbar fest.

        Der Tombstone ist ein **Ereignisbeleg**, kein Zustandsflag: taucht der
        Datensatz beim Provider wieder auf, wird er neu importiert, und der
        Beleg der früheren Löschung bleibt bestehen. Deshalb wird ein
        vorhandener Eintrag nicht ersetzt, sondern übersprungen.
        """
        repos.contacts.soft_delete(contact_id, jetzt)
        if not provider_identifier:
            return
        if repos.tombstones.exists(self._provider_account_id, provider_identifier):
            return
        repos.tombstones.add(ContactTombstone(
            provider_account_id=self._provider_account_id,
            provider_identifier=provider_identifier,
            reason=reason, deleted_at=jetzt, contact_id=contact_id))

    # ── Zustand ─────────────────────────────────────────────────────────────
    def _load_state(self, container_identifier: str) -> ContactSyncState | None:
        with self._persistence.unit_of_work() as uow:
            repos = self._persistence.repositories(uow)
            return repos.sync_state.get(self._provider_account_id,
                                        container_identifier)

    def _upsert_state(self, repos, container_identifier: str, *,
                      cursor_token: str | None, cursor_taken_at: str | None,
                      last_full_diff_at: str | None, key_set_version: str,
                      mode: SyncMode, circuit_state: CircuitState,
                      updated_at: str, keep_full_diff_at: bool = False) -> None:
        vorher = repos.sync_state.get(self._provider_account_id,
                                      container_identifier)
        if keep_full_diff_at and vorher is not None:
            last_full_diff_at = vorher.last_full_diff_at
        repos.sync_state.upsert(ContactSyncState(
            provider_account_id=self._provider_account_id,
            container_identifier=container_identifier,
            key_set_version=key_set_version, mode=mode.value,
            cursor_token=cursor_token, cursor_taken_at=cursor_taken_at,
            last_full_diff_at=last_full_diff_at,
            circuit_state=circuit_state.value, updated_at=updated_at))

    def _local_index(self, repos, container_identifier: str) -> dict[str, str]:
        """Provider-Identifier → lokale Kontaktkennung für **diesen** Container.

        Tombstones bleiben aussen vor: ein bereits gelöschter Datensatz darf
        weder erneut gelöscht noch als „fehlend" gezählt werden.
        """
        index: dict[str, str] = {}
        for kontakt in repos.contacts.list_by_workspace(self._workspace_id):
            for extern in kontakt.external_ids:
                if (extern.provider_account_id == self._provider_account_id
                        and extern.container_identifier == container_identifier):
                    index[extern.provider_identifier] = kontakt.id
        return index

    # ── Fehlerabschluss ─────────────────────────────────────────────────────
    def _failed(self, kind: SyncRunKind, container_identifier: str,
                exc: Exception, audit: list[str], *,
                requires_full_diff: bool) -> SyncRunResult:
        """Beendet einen Lauf ohne Teilbestand.

        Der Modus wird nur fortgeschrieben, wenn bereits ein Zustand existiert:
        ohne vorherigen Lauf gibt es keinen `key_set_version`, und eine Zeile
        zu erfinden hiesse, einen nie erfolgten Import zu behaupten.
        """
        fehlerklasse = type(exc).__name__
        audit.append(f"sync.{kind.value}.failed")
        cursor = CursorState.FAILED
        reauth = isinstance(exc, AuthorizationRequired)

        vorher = self._load_state(container_identifier)
        if vorher is not None and requires_full_diff:
            jetzt = utc_now()
            with self._persistence.unit_of_work() as uow:
                repos = self._persistence.repositories(uow)
                repos.sync_state.upsert(replace(
                    vorher,
                    mode=SyncMode.FULL_DIFF_REQUIRED.value,
                    # Ein untragfähiger Cursor wird verworfen statt aufbewahrt —
                    # sonst versucht ihn irgendwann doch jemand.
                    cursor_token=None, cursor_taken_at=None,
                    circuit_state=(CircuitState.REAUTH_REQUIRED.value if reauth
                                   else vorher.circuit_state),
                    updated_at=jetzt))
            cursor = CursorState.FULL_DIFF_REQUIRED
            audit.append("sync.mode.full_diff_required")

        return SyncRunResult(
            kind=kind, succeeded=False, cursor_state=cursor,
            provider_account_id=self._provider_account_id,
            container_identifier=container_identifier,
            cursor_advanced=False, requires_full_diff=requires_full_diff,
            error_class=fehlerklasse,
            # Ausdrücklich technisch: keine Namen, keine Werte, keine
            # Provider-Identifier, kein Cursor-Token.
            detail=self._safe_detail(exc), audit_events=tuple(audit),
        )

    @staticmethod
    def _safe_detail(exc: Exception) -> str:
        """Technische Kurzbeschreibung — nie die Ausnahmemeldung selbst.

        Auch wenn die Bridge-Fehlertexte PII-frei sind: hier wird ausschliesslich
        die Klasse beziehungsweise der Vertragscode weitergegeben. Was nie
        eingesammelt wird, kann auch nie in ein Protokoll geraten.
        """
        if isinstance(exc, BridgeOperationError):
            return f"bridge:{exc.code}"
        if isinstance(exc, BridgeProcessError):
            return f"process:{exc.failure_class}"
        return type(exc).__name__
