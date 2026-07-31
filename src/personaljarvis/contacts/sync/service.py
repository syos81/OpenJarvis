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

import time
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
from personaljarvis.contacts.sync.audit import (
    OUTCOME_ABORTED,
    OUTCOME_COMMITTED,
    ContainerAudit,
    SyncAuditRecord,
    SyncAuditWriter,
    container_ref,
)
from personaljarvis.contacts.sync.echo import EchoSuppressionLedger
from personaljarvis.contacts.sync.errors import (
    AuthorizationRequired,
    CursorRejected,
    DeleteBasisInvalid,
    FullDiffRequired,
    IncompleteEnumeration,
    KeySetVersionChanged,
    SuspiciousEmptyEnumeration,
    SyncError,
    TransientEmptySnapshot,
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

#: Pause vor der einen erlaubten Gegenprobe. Kurz genug, um den Aufruf nicht zu
#: sprengen; lang genug, damit ein Provider, der gerade neu aufbaut, zu Ende
#: kommen kann. Kein Timer, keine Schleife — sie liegt in genau diesem Aufruf.
EMPTY_RECHECK_PAUSE_SECONDS = 2.0


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
                 *, workspace_id: str, provider_account_id: str,
                 empty_recheck_pause: float = EMPTY_RECHECK_PAUSE_SECONDS) -> None:
        self._client = client
        self._persistence = persistence
        self._workspace_id = workspace_id
        self._provider_account_id = provider_account_id
        #: Nur für Tests kürzbar. Produktiv bleibt die Pause die Konstante —
        #: sie ist der ganze Sinn der Gegenprobe.
        self._empty_recheck_pause = empty_recheck_pause

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
        """Vollabgleich **eines** Containers — ohne Löschmenge.

        Er frischt auf und setzt den Cursor neu. Tombstones entstehen hier
        ausdrücklich nicht: die Abwesenheit eines Datensatzes in *einem*
        Container beweist nichts, solange die übrigen Container des Kontos
        nicht ebenso vollständig aufgezählt sind — der Datensatz könnte dort
        liegen. Die Löschmenge entsteht allein in `full_diff_account`.
        """
        return self._snapshot_run(container_identifier, SyncRunKind.FULL_DIFF)

    def pending_full_diff(self, container_identifiers) -> tuple[str, ...]:
        """Welche Container brauchen einen Voll-Diff?

        Der Aufrufer entscheidet damit **einmal** für das ganze Konto: sobald
        einer davon betroffen ist, gehört der Lauf auf den kontoweiten Pfad —
        sonst entstünde eine Löschmenge aus einem halb geprüften Konto.
        """
        offen = []
        for kennung in container_identifiers:
            zustand = self._load_state(kennung)
            if (zustand is None
                    or derive_cursor_state(zustand) is not CursorState.ACTIVE):
                offen.append(kennung)
        return tuple(offen)

    # ── Kontoweiter Voll-Diff: der einzige Weg zu Tombstones ────────────────
    def full_diff_account(self, container_identifiers: Sequence[str], *,
                          confirm_empty: bool = False) -> SyncRunResult:
        """Vollabgleich über **alle** Container eines Providerkontos.

        Zwei Phasen, und die Reihenfolge ist der ganze Punkt:

        1. **Lesen und prüfen** — jeder Container wird aufgezählt und einzeln
           validiert. Erst wenn *alle* bestanden haben, existiert überhaupt
           eine Löschbasis.
        2. **Schreiben** — in einer Transaktion, für alle Container zusammen.

        Fällt ein Container aus oder liefert er ein verdächtiges Null-Ergebnis,
        endet der Lauf ohne jede Löschung. Das ist teurer als das frühere
        Verhalten und genau deshalb richtig: am 2026-07-30 hat ein einzelnes
        `count=0, complete=true` 116 Kontakte lokal gelöscht.

        `confirm_empty=True` ist der ausdrückliche Weg für ein tatsächlich
        geleertes Adressbuch. Er kommt nie aus einem gewöhnlichen Lauf.
        """
        audit: list[str] = ["sync.full_diff_account.started"]
        container = tuple(container_identifiers)
        spur = SyncAuditRecord(workspace_id=self._workspace_id,
                               provider_account_id=self._provider_account_id,
                               mode="full_diff_account",
                               container_count=len(container))
        if not container:
            return self._account_failed(
                DeleteBasisInvalid("Kein Container im Inventar"), audit, "",
                spur)

        gelesen: list[tuple[str, EnumerationResult, str | None, int]] = []
        try:
            self._require_authorized()
            for kennung in container:
                baseline_token, key_set_version = self._baseline(audit)
                spur.cursor_before_present |= bool(baseline_token)
                enumeration = self._client.enumerate(container_identifier=kennung)
                if key_set_version is None:
                    key_set_version = enumeration.key_set_version
                enumeration = self._validate_delete_basis(
                    kennung, enumeration, confirm_empty=confirm_empty, spur=spur)
                gelesen.append((kennung, enumeration, baseline_token,
                                key_set_version))
            audit.append("sync.delete_basis.complete")
        except (SyncError, BridgeError) as exc:
            # **Kein** Container wird geschrieben — auch die bereits gelesenen
            # nicht. Ein Teilbestand wäre eine halbe Wahrheit über den Provider.
            return self._account_failed(exc, audit, container[0], spur)

        return self._persist_account(gelesen, audit, spur,
                                     confirm_empty=confirm_empty)

    def _baseline(self, audit: list[str]) -> tuple[str | None, int | None]:
        """Cursor zuerst — Ereignisse dazwischen werden erneut angewandt."""
        if not self._client.capabilities.change_history_supported:
            audit.append("sync.cursor.unavailable")
            return None, None
        baseline = self._client.changes()
        audit.append("sync.cursor.baseline_taken")
        return baseline.current_token or None, baseline.key_set_version

    def enumerate_validated(self, container_identifier: str, *,
                            spur: SyncAuditRecord,
                            confirm_empty: bool = False) -> EnumerationResult:
        """Aufzählen **und** prüfen — inklusive Null-Gegenprobe.

        Öffentlich, damit die Wiederherstellung dieselben Schutzregeln benutzt
        statt sie nachzubauen. Eine zweite Umsetzung derselben Regel ist eine
        Regel, die irgendwann auseinanderläuft.
        """
        self._require_authorized()
        enumeration = self._client.enumerate(
            container_identifier=container_identifier)
        return self._validate_delete_basis(container_identifier, enumeration,
                                           confirm_empty=confirm_empty,
                                           spur=spur)

    def _local_count(self, container_identifier: str) -> int:
        """Wie viele aktive Datensätze der Container lokal hat."""
        with self._persistence.unit_of_work() as uow:
            repos = self._persistence.repositories(uow)
            return len(self._local_index(repos, container_identifier))

    def _pruefe(self, container_identifier: str, enumeration: EnumerationResult,
                *, versuch: int, vorher: int) -> ContainerAudit:
        return ContainerAudit(
            container_ref=container_ref(container_identifier), attempt=versuch,
            reported_count=enumeration.count,
            received_count=len(enumeration.contacts),
            complete=enumeration.complete,
            count_consistent=enumeration.count == len(enumeration.contacts),
            duplicate_identifiers=(
                len(enumeration.contacts)
                - len({c.provider_identifier for c in enumeration.contacts})),
            previous_count=vorher)

    def _validate_delete_basis(self, container_identifier: str,
                               enumeration: EnumerationResult, *,
                               confirm_empty: bool,
                               spur: SyncAuditRecord) -> EnumerationResult:
        """Darf diese Enumeration eine Löschmenge tragen?

        Drei Stufen, alle fail-closed:

        1. Vollständigkeit und Zählung müssen stimmen.
        2. Ein Null-Ergebnis auf einem zuvor gefüllten Container bekommt
           **genau eine** Gegenprobe. Das erste Ergebnis wird dabei verworfen —
           nicht gemittelt, nicht bevorzugt.
        3. Bleibt auch die Gegenprobe bei null, ist das immer noch kein
           Löschbeleg, sondern ein Fall für den ausdrücklichen Bestätigungsweg.

        Die Gegenprobe ist auf einen Versuch begrenzt und läuft ohne Timer und
        ohne Hintergrundschleife: sie ist Teil dieses einen Aufrufs.
        """
        vorher = self._local_count(container_identifier)
        spur.add_container(self._pruefe(container_identifier, enumeration,
                                        versuch=1, vorher=vorher))
        if not enumeration.usable_as_delete_basis:
            raise IncompleteEnumeration(
                "Enumeration ist unvollständig oder die Zählung weicht ab")

        if not (vorher > 0 and enumeration.count == 0) or confirm_empty:
            return enumeration

        # Null auf gefülltem Container: erstes Ergebnis verwerfen und **einmal**
        # nachfassen. Am 2026-07-30 war der Nullbefund nicht reproduzierbar —
        # eine einzige Gegenprobe hätte den Bestand gerettet.
        del enumeration
        time.sleep(self._empty_recheck_pause)
        zweite = self._client.enumerate(container_identifier=container_identifier)
        spur.add_container(self._pruefe(container_identifier, zweite,
                                        versuch=2, vorher=vorher))
        if not zweite.usable_as_delete_basis:
            raise IncompleteEnumeration(
                "Die Gegenprobe war unvollständig oder wich in der Zählung ab")
        if zweite.count == 0:
            spur.suspicious_empty = True
            raise SuspiciousEmptyEnumeration(
                f"Container war zuvor gefüllt ({vorher}) und liefert auch in "
                "der Gegenprobe 0; das ist kein Löschbeleg")

        # Der erste Lauf war ein Augenblickszustand. Der laufende Sync wird
        # **nicht** still fortgesetzt: er endet, und der nächste ausdrückliche
        # Lauf arbeitet auf einer Grundlage, die niemand anzweifeln muss.
        raise TransientEmptySnapshot(
            f"Erste Enumeration war leer, die Gegenprobe lieferte "
            f"{zweite.count}; der Lauf wird verworfen")

    # ── Vollaufnahme (Initialimport und Voll-Diff teilen den Ablauf) ────────
    #
    # Ein Einzelcontainer-Lauf traegt **nie** eine Loeschmenge. Frueher lag
    # dafuer ein `delete_basis`-Schalter auf diesem Pfad, den kein Aufrufer je
    # auf `True` setzte: ein abgeschalteter Loeschzweig, der jederzeit
    # versehentlich haette eingeschaltet werden koennen. Loeschungen entstehen
    # ausschliesslich in `full_diff_account` (kontoweite Abwesenheit) und im
    # Delta-Pfad bei einem ausdruecklichen Provider-DELETE-Ereignis.
    def _snapshot_run(self, container_identifier: str,
                      kind: SyncRunKind) -> SyncRunResult:
        audit: list[str] = [f"sync.{kind.value}.started"]
        spur = self._neue_spur(kind, container_identifier)
        vorher = self._load_state(container_identifier)
        spur.cursor_before_present = bool(vorher is not None
                                          and vorher.cursor_token)
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
            # Die Zaehlwerte werden festgehalten, **bevor** ueber sie geurteilt
            # wird: gerade der verworfene Lauf soll zeigen, was ankam.
            spur.add_container(self._pruefe(
                container_identifier, enumeration, versuch=1,
                vorher=self._local_count(container_identifier)))
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
                                requires_full_diff=True, spur=spur)

        # 3. Schreiben — genau eine Transaktion, genau ein Abschluss.
        return self._persist_snapshot(container_identifier, kind, enumeration,
                                      baseline_token, key_set_version, audit,
                                      spur)

    def _persist_snapshot(self, container_identifier: str, kind: SyncRunKind,
                          enumeration: EnumerationResult,
                          baseline_token: str | None, key_set_version: int,
                          audit: list[str],
                          spur: SyncAuditRecord) -> SyncRunResult:
        jetzt = utc_now()
        imported = updated = unchanged = 0

        with self._persistence.unit_of_work() as uow:
            repos = self._persistence.repositories(uow)
            lokal = self._local_index(repos, container_identifier)

            for roh in enumeration.contacts:
                ergebnis, _ = self._write_contact(
                    repos, roh, container_identifier,
                    lokal.get(roh.provider_identifier), jetzt)
                if ergebnis == IMPORTED:
                    imported += 1
                elif ergebnis == UPDATED:
                    updated += 1
                else:
                    unchanged += 1

            # Keine Löschmenge auf diesem Pfad. Die Abwesenheit eines
            # Datensatzes in *einem* Container ist kein Beweis — er kann in
            # einem Container liegen, der hier nicht geprüft wurde.
            audit.append("sync.delete_basis.absent")

            self._upsert_state(repos, container_identifier,
                               cursor_token=baseline_token,
                               cursor_taken_at=jetzt if baseline_token else None,
                               last_full_diff_at=jetzt,
                               key_set_version=str(key_set_version),
                               mode=(SyncMode.DELTA if baseline_token
                                     else SyncMode.FULL_DIFF_REQUIRED),
                               circuit_state=CircuitState.CLOSED, updated_at=jetzt)

            # Dieselbe Transaktion wie Bestand und Cursor.
            spur.imported, spur.updated, spur.unchanged = imported, updated, unchanged
            spur.tombstoned = 0
            spur.cursor_after_present = bool(baseline_token)
            spur.full_diff_required = not baseline_token
            SyncAuditWriter(uow).write(spur.finish(OUTCOME_COMMITTED))

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
            # Konstant 0 und nicht gezaehlt: dieser Pfad kann keine Loeschung
            # erzeugen. Eine Variable stuende hier fuer eine Moeglichkeit, die
            # es nicht gibt.
            tombstoned=0, events_processed=0,
            cursor_advanced=bool(baseline_token),
            requires_full_diff=not baseline_token,
            audit_events=tuple(audit),
        )

    def _persist_account(self, gelesen, audit: list[str],
                         spur: SyncAuditRecord, *,
                         confirm_empty: bool) -> SyncRunResult:
        """Schreibt alle Container in **einer** Transaktion.

        Erst hier entsteht die Löschmenge — nachdem jeder Container die
        Prüfung bestanden hat.
        """
        jetzt = utc_now()
        imported = updated = unchanged = tombstoned = 0

        with self._persistence.unit_of_work() as uow:
            repos = self._persistence.repositories(uow)
            for kennung, enumeration, token, key_set_version in gelesen:
                lokal = self._local_index(repos, kennung)
                gesehen: set[str] = set()
                for roh in enumeration.contacts:
                    gesehen.add(roh.provider_identifier)
                    ergebnis, _ = self._write_contact(
                        repos, roh, kennung,
                        lokal.get(roh.provider_identifier), jetzt)
                    if ergebnis == IMPORTED:
                        imported += 1
                    elif ergebnis == UPDATED:
                        updated += 1
                    else:
                        unchanged += 1
                for pid, contact_id in lokal.items():
                    if pid in gesehen:
                        continue
                    self._tombstone(repos, contact_id, pid,
                                    TOMBSTONE_REASON_ABSENT, jetzt)
                    tombstoned += 1
                self._upsert_state(
                    repos, kennung, cursor_token=token,
                    cursor_taken_at=jetzt if token else None,
                    last_full_diff_at=jetzt,
                    key_set_version=str(key_set_version),
                    mode=(SyncMode.DELTA if token else SyncMode.FULL_DIFF_REQUIRED),
                    circuit_state=CircuitState.CLOSED, updated_at=jetzt)
            # Die Spur gehoert in dieselbe Transaktion: rollt der Lauf zurueck,
            # verschwindet sie mit ihm statt einen Lauf zu behaupten.
            spur.imported, spur.updated = imported, updated
            spur.unchanged, spur.tombstoned = unchanged, tombstoned
            spur.cursor_after_present = all(t for _, _, t, _ in gelesen)
            spur.full_diff_required = not spur.cursor_after_present
            SyncAuditWriter(uow).write(spur.finish(OUTCOME_COMMITTED))

        if tombstoned:
            audit.append("sync.tombstones.created")
        if confirm_empty:
            audit.append("sync.delete_basis.confirmed_empty")
        audit.append("sync.full_diff_account.succeeded")
        alle_token = all(t for _, _, t, _ in gelesen)
        return SyncRunResult(
            kind=SyncRunKind.FULL_DIFF, succeeded=True,
            cursor_state=(CursorState.ACTIVE if alle_token
                          else CursorState.FULL_DIFF_REQUIRED),
            provider_account_id=self._provider_account_id,
            container_identifier=gelesen[0][0],
            imported=imported, updated=updated, unchanged=unchanged,
            tombstoned=tombstoned, cursor_advanced=alle_token,
            requires_full_diff=not alle_token, audit_events=tuple(audit))

    def _account_failed(self, exc: Exception, audit: list[str],
                        container_identifier: str,
                        spur: SyncAuditRecord) -> SyncRunResult:
        """Kontoweiter Abbruch: kein Schreibvorgang, kein Cursorfortschritt.

        Der Modus bleibt `full_diff_required` — der nächste Versuch ist wieder
        ein ausdrücklicher Voll-Diff, kein Delta auf einem Cursor, den niemand
        mehr belegen kann.
        """
        audit.append("sync.full_diff_account.failed")
        audit.append("sync.delete_basis.rejected")
        spur.error_class = type(exc).__name__
        spur.error_code = self._safe_detail(exc)
        spur.full_diff_required = True
        # Eigene, kurze Transaktion: der Lauf hat nichts geschrieben, aber
        # **dass** er abbrach, ist genau die Information, die am 2026-07-30
        # gefehlt hat.
        with self._persistence.unit_of_work() as uow:
            SyncAuditWriter(uow).write(spur.finish(OUTCOME_ABORTED))
        return SyncRunResult(
            kind=SyncRunKind.FULL_DIFF, succeeded=False,
            cursor_state=CursorState.FAILED,
            provider_account_id=self._provider_account_id,
            container_identifier=container_identifier,
            cursor_advanced=False, requires_full_diff=True,
            error_class=type(exc).__name__, detail=self._safe_detail(exc),
            audit_events=tuple(audit))

    # ── Delta ───────────────────────────────────────────────────────────────
    def delta_sync(self, container_identifier: str) -> SyncRunResult:
        """Inkrementeller Lauf über die Änderungshistorie des Providers."""
        audit: list[str] = ["sync.delta.started"]
        kind = SyncRunKind.DELTA
        spur = self._neue_spur(SyncRunKind.DELTA, container_identifier)
        try:
            self._require_authorized()
            zustand = self._load_state(container_identifier)
            cursor = derive_cursor_state(zustand)
            spur.cursor_before_present = bool(
                zustand is not None and zustand.cursor_token)
            if zustand is None or cursor is not CursorState.ACTIVE:
                raise FullDiffRequired(
                    f"Der Cursor ist nicht tragfähig (Zustand: {cursor.value})",
                    code="cursor_unusable")
            assert zustand.cursor_token is not None

            container = self._client.containers()
            if not any(c.identifier == container_identifier for c in container):
                raise FullDiffRequired(
                    "Der Container ist im Providerinventar nicht mehr enthalten",
                    code="container_missing")
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

            # Die Ereignisse werden gezaehlt, **bevor** ueber sie geurteilt
            # wird: auch ein abgebrochener Lauf soll zeigen, was hereinkam.
            self._zaehle_ereignisse(spur, aenderungen.events)

            if aenderungen.key_set_version != int(zustand.key_set_version or -1):
                raise KeySetVersionChanged(
                    "Der Schlüsselsatz des Providers hat gewechselt")
            if aenderungen.requires_full_diff:
                audit.append("sync.delta.drop_everything")
                spur.drop_everything_seen = True
                raise FullDiffRequired(
                    "Der Provider hat die Historie verworfen (dropEverything)",
                    code="drop_everything")
            for ereignis in aenderungen.events:
                if ereignis.type is ChangeEventType.OTHER:
                    raise UnknownChangeEvent(
                        "Unbekannter Ereignistyp; es wird nicht geraten")

        except (SyncError, BridgeError) as exc:
            # Ein gescheiterter Lauf hinterlaesst keinen Teilbestand: es wurde
            # bis hierhin ausschliesslich gelesen.
            return self._failed(kind, container_identifier, exc, audit,
                                requires_full_diff=True, spur=spur)

        return self._apply_events(container_identifier, aenderungen.events,
                                  aenderungen.current_token,
                                  aenderungen.key_set_version, eindeutig, audit,
                                  spur)

    def _neue_spur(self, kind: SyncRunKind,
                   container_identifier: str) -> SyncAuditRecord:
        """Eine Spur je fachlichem Lauf — angelegt, bevor irgendetwas geschieht.

        Ein Lauf, der erst beim Erfolg eine Spur bekaeme, waere genau dann
        unsichtbar, wenn er interessant wird.
        """
        return SyncAuditRecord(
            workspace_id=self._workspace_id,
            provider_account_id=self._provider_account_id,
            mode=kind.value, container_count=1)

    @staticmethod
    def _zaehle_ereignisse(spur: SyncAuditRecord,
                           events: Sequence[ChangeEvent]) -> None:
        """Aggregiert die Ereignisarten — Zahlen, nie Identifier."""
        for ereignis in events:
            if ereignis.type is ChangeEventType.ADD:
                spur.events_add += 1
            elif ereignis.type is ChangeEventType.UPDATE:
                spur.events_update += 1
            elif ereignis.type is ChangeEventType.DELETE:
                spur.events_delete += 1
            else:
                # `dropEverything` und Unbekanntes. Ersteres traegt zusaetzlich
                # das eigene Kennzeichen `drop_everything_seen`.
                spur.events_other += 1
                if ereignis.type is ChangeEventType.DROP_EVERYTHING:
                    spur.drop_everything_seen = True

    def _apply_events(self, container_identifier: str,
                      events: Sequence[ChangeEvent], current_token: str,
                      key_set_version: int, eindeutig: bool,
                      audit: list[str],
                      spur: SyncAuditRecord) -> SyncRunResult:
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

            # Dieselbe Transaktion wie Bestand und Cursor. Ein `committed`, das
            # einen Rollback ueberlebte, behauptete einen Lauf, den es nicht
            # gab — genau die Art Aussage, wegen der diese Spur existiert.
            spur.imported, spur.updated = imported, updated
            spur.unchanged, spur.tombstoned = unchanged, tombstoned
            spur.cursor_after_present = bool(current_token)
            SyncAuditWriter(uow).write(spur.finish(OUTCOME_COMMITTED))

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
                requires_full_diff: bool,
                spur: SyncAuditRecord | None = None) -> SyncRunResult:
        """Beendet einen Lauf ohne Teilbestand.

        Der Modus wird nur fortgeschrieben, wenn bereits ein Zustand existiert:
        ohne vorherigen Lauf gibt es keinen `key_set_version`, und eine Zeile
        zu erfinden hiesse, einen nie erfolgten Import zu behaupten.

        Die Spur wird in einer **eigenen** kurzen Arbeitseinheit festgehalten:
        der Lauf hat fachlich nichts geschrieben, aber *dass* er abbrach, ist
        genau die Auskunft, die am 2026-07-30 fehlte.
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

        if spur is not None:
            spur.error_class = fehlerklasse
            spur.error_code = self._safe_detail(exc)
            spur.full_diff_required = requires_full_diff
            # Kein Cursorfortschritt bei einem Abbruch — und wo der Modus auf
            # `full_diff_required` ging, ist der alte Cursor sogar verworfen.
            spur.cursor_after_present = False
            with self._persistence.unit_of_work() as uow:
                SyncAuditWriter(uow).write(spur.finish(OUTCOME_ABORTED))

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
        # Eine ausdrueckliche Kennung unterscheidet Faelle, die sich eine
        # Klasse teilen (etwa die drei Ursachen von `FullDiffRequired`).
        if isinstance(exc, SyncError) and exc.code:
            return exc.code
        return type(exc).__name__
