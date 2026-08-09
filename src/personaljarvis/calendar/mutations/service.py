"""Freigabepflichtige Kalender-Mutationspipeline (B3 P1: `create`).

Dasselbe Claim-Settle-Muster wie der Kontakte-App-Kanal, mit drei bewussten
Eigenheiten des Kalenders:

1. **Positionsstufe.** `ENABLED_COMMANDS` schaltet in P1 ausschliesslich
   `create` frei. `prepare_update` und `prepare_delete` existieren als
   Vertragsstellen und verweigern mit `position_not_enabled` — keine stille
   Teilimplementierung.
2. **Backup-Gate.** Ein Claim setzt einen **verifizierten** Backup-Nachweis
   voraus (fail-closed): fehlt er, ist er unlesbar oder nicht verifiziert,
   gibt es keinen Auftrag (`backup_missing`). Der erste Schreibpfad in einen
   echten Kalender verdient ein Sicherheitsnetz, bevor er existiert.
3. **Rücknahmeinformation.** Nach belegter Providerwirkung eines `create`
   steht die erzeugte Kennung in der Mutationszeile samt maschinenlesbarem
   `rollback_hint_json` — das IST der Weg zurück.

Wie bei den Kontakten gilt: ein Claim, ein Auftrag, höchstens ein Bericht.
Nach ausgegebenem Auftrag öffnet nichts einen zweiten Versuch.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from personaljarvis.base.approvals import (
    ApprovalError,
    ApprovalStore,
    DEFAULT_TTL_SECONDS,
)
from personaljarvis.base.audit import AuditStage, AuditTrail
from personaljarvis.base.db.factory import ConnectionFactory
from personaljarvis.base.db.unit_of_work import UnitOfWork
from personaljarvis.base.digest import digest_of
from personaljarvis.base.outbox import (
    ExternalActionOutbox,
    OutboxNotClaimable,
    token_digest,
)
from personaljarvis.calendar.domain import CanonicalEvent
from personaljarvis.calendar.mutations.contracts import (
    ExecutionOrderV1,
    ExecutionReportV1,
    FIELD_NAMES,
    InvalidMutationFields,
    canonical_create_payload,
    fingerprint_of,
    report_digest,
    validate_fields,
)
from personaljarvis.calendar.repositories import EventRepository
from personaljarvis.errors import PersonalJarvisError


def utc_now() -> str:
    """UTC-Zeitstempel in ISO-8601 (07 §4). Bewusst lokal definiert: der
    Kalender importiert keinen Kontakte-Code (Modulgrenze, `test_boundaries`)."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()

__all__ = [
    "MODULE",
    "SUBJECT_TYPE",
    "CLAIM_TTL_SECONDS",
    "ENABLED_COMMANDS",
    "BACKUP_PROOF_PATH",
    "backup_probe_from_path",
    "CalendarMutationError",
    "MutationNotFound",
    "CalendarNotFound",
    "CalendarNotWritable",
    "MutationNotExecutable",
    "AlreadySettled",
    "SettleConflict",
    "PositionNotEnabled",
    "BackupMissing",
    "UnzulaessigerUebergang",
    "pruefe_uebergang",
    "PreparedCalendarMutation",
    "SettleErgebnis",
    "CalendarMutationService",
]

MODULE = "calendar"
SUBJECT_TYPE = "calendar.mutation"

#: Lebensdauer eines Claims — wortgleich mit dem Kontakte-Kanal (ADR-0026 §3).
CLAIM_TTL_SECONDS = 600

#: Positionsstufe B3 P1: ausschliesslich `create`. Diese Konstante ist die
#: **eine** Stelle, an der eine spätere Position weitere Kommandos freischaltet.
ENABLED_COMMANDS: frozenset[str] = frozenset({"create"})

#: Ablageort des Backup-Nachweises. PII-arm: Zähler und Digests, keine Termine.
BACKUP_PROOF_PATH = (Path.home() / ".openjarvis" / "personal" / "backups"
                     / "calendar" / "latest.json")


# ── Fehler ──────────────────────────────────────────────────────────────────
class CalendarMutationError(PersonalJarvisError):
    """Wurzel aller Kalender-Mutationsfehler. Meldungen sind rein technisch:
    niemals Titel, Ort, Notiz oder eine Providerkennung."""

    reason_code = "calendar_mutation_error"


class MutationNotFound(CalendarMutationError):
    reason_code = "mutation_not_found"


class CalendarNotFound(CalendarMutationError):
    reason_code = "calendar_not_found"


class CalendarNotWritable(CalendarMutationError):
    reason_code = "calendar_not_writable"


class MutationNotExecutable(CalendarMutationError):
    reason_code = "mutation_not_executable"


class AlreadySettled(CalendarMutationError):
    reason_code = "already_settled"


class SettleConflict(CalendarMutationError):
    reason_code = "settle_conflict"


class PositionNotEnabled(CalendarMutationError):
    """Die Operation existiert im Vertrag, ist aber in dieser Position nicht
    freigeschaltet. Bewusst ein eigener Fehler: „noch nicht" ist etwas anderes
    als „falsch aufgerufen"."""

    reason_code = "position_not_enabled"


class BackupMissing(CalendarMutationError):
    reason_code = "backup_missing"


# ── Zustandsautomat ────────────────────────────────────────────────────────
#: Bewusst ein **eigener** Automat: die Kontakte-Tabelle kennt Freigabe- und
#: Abgleichszustände, die es hier (noch) nicht gibt — sie zu erben hiesse,
#: Übergänge zuzulassen, die dieser Vertrag nicht kennt.
ZUSTAENDE: tuple[str, ...] = (
    "prepared", "approved", "cancelled", "executing",
    "provider_applied_pending_reconcile", "failed_before_send",
    "outcome_unknown", "succeeded",
)

TERMINAL: frozenset[str] = frozenset({
    "succeeded", "cancelled", "failed_before_send",
})

ERLAUBTE_UEBERGAENGE: dict[str, frozenset[str]] = {
    "prepared": frozenset({"approved", "cancelled"}),
    "approved": frozenset({"executing", "cancelled"}),
    "executing": frozenset({
        "provider_applied_pending_reconcile", "failed_before_send",
        "outcome_unknown",
    }),
    "provider_applied_pending_reconcile": frozenset({"succeeded"}),
    # Aus `outcome_unknown` führt in P1 kein automatischer Weg — dort wartet
    # der Vorgang auf einen späteren Abgleich, nie auf einen Retry.
    "outcome_unknown": frozenset(),
    "succeeded": frozenset(),
    "cancelled": frozenset(),
    "failed_before_send": frozenset(),
}


class UnzulaessigerUebergang(RuntimeError):
    def __init__(self, von: str, nach: str) -> None:
        super().__init__(f"Unzulässiger Übergang: {von} → {nach}")
        self.von = von
        self.nach = nach


def pruefe_uebergang(von: str, nach: str) -> None:
    """Wirft, wenn der Übergang nicht in der Tabelle steht."""
    if von not in ERLAUBTE_UEBERGAENGE or nach not in ZUSTAENDE \
            or nach not in ERLAUBTE_UEBERGAENGE[von]:
        raise UnzulaessigerUebergang(von, nach)


# ── Backup-Gate ────────────────────────────────────────────────────────────
def backup_probe_from_path(path: Path) -> Callable[[], bool]:
    """Baut die fail-closed Nachweisprüfung über einer Datei.

    Fehlend, unlesbar, kein Objekt oder `verified != true` ⇒ `False`. Es gibt
    keinen Pfad, auf dem ein kaputter Nachweis als vorhanden gilt.
    """
    def probe() -> bool:
        try:
            daten = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return False
        return isinstance(daten, dict) and daten.get("verified") is True
    return probe


# ── Ergebnisobjekte ────────────────────────────────────────────────────────
@dataclass(frozen=True, slots=True)
class PreparedCalendarMutation:
    mutation_id: str
    approval_id: str
    outbox_id: str
    state: str
    payload_digest: str
    preview: dict[str, Any]
    preview_digest: str


@dataclass(frozen=True, slots=True)
class SettleErgebnis:
    mutation_id: str
    state: str
    outcome: str | None
    idempotent: bool
    error_class: str | None = None


def _plus_sekunden(zeitpunkt: str, sekunden: int) -> str:
    basis = datetime.fromisoformat(zeitpunkt.replace("Z", "+00:00"))
    if basis.tzinfo is None:
        basis = basis.replace(tzinfo=timezone.utc)
    return (basis + timedelta(seconds=sekunden)).isoformat()


def _bewerte(bericht: ExecutionReportV1) -> tuple[str, str | None, str | None]:
    """Übersetzt einen Bericht in den Zielzustand — absichtlich streng.

    Nur ein `not_sent` **ohne** Sendeversuch darf `failed_before_send`
    werden. Alles, was nicht sauber angewandt und rückgelesen ist, endet im
    ungewissen Ausgang.
    """
    if bericht.beweist_nichts_gesendet:
        return "failed_before_send", "failed", bericht.error_class
    if bericht.outcome == "applied" and bericht.readback_status in (
            "confirmed", "absent_confirmed"):
        return "provider_applied_pending_reconcile", None, None
    return "outcome_unknown", "outcome_unknown", bericht.error_class


class CalendarMutationService:
    """Vorbereitung, Freigabebindung, Claim und Settle der Kalender-Mutationen.

    Der Dienst arbeitet ausschliesslich auf dem Kern: Datenbank, Outbox,
    Freigaben, Audit. Er kennt weder Tauri noch den Sidecar und ruft nie
    einen Provider.
    """

    def __init__(self, factory: ConnectionFactory, *,
                 backup_probe: Callable[[], bool] | None = None,
                 approval_ttl_seconds: int = DEFAULT_TTL_SECONDS) -> None:
        self._factory = factory
        self._backup_probe = backup_probe or backup_probe_from_path(
            BACKUP_PROOF_PATH)
        self._ttl = approval_ttl_seconds

    def _uow(self) -> UnitOfWork:
        return UnitOfWork(self._factory)

    # ── 1. Vorbereiten ──────────────────────────────────────────────────────
    def prepare_create(self, provider_calendar_id: str,
                       fields: dict[str, Any], *,
                       actor: str = "lukas",
                       initiation_context: str = "user_direct",
                       correlation_id: str | None = None,
                       ) -> PreparedCalendarMutation:
        """Validiert, bindet das Ziel, erzeugt Vorschau, Freigabe und
        Outbox-Eintrag in **einer** UnitOfWork. Es wird nichts gesendet."""
        if "create" not in ENABLED_COMMANDS:  # pragma: no cover - Konstante
            raise PositionNotEnabled("'create' ist nicht freigeschaltet")
        if not isinstance(provider_calendar_id, str) or not provider_calendar_id:
            raise InvalidMutationFields(
                "provider_calendar_id ist keine brauchbare Kennung")
        felder = validate_fields(fields)

        mutation_id = str(uuid.uuid4())
        with self._uow() as uow:
            kalender = uow.execute(
                "SELECT id, display_name, is_writable FROM calendars "
                "WHERE provider_calendar_id = ? AND is_tombstone = 0",
                (provider_calendar_id,)).fetchone()
            if kalender is None:
                raise CalendarNotFound("Zielkalender existiert nicht im Bestand")
            if not kalender["is_writable"]:
                raise CalendarNotWritable(
                    "Zielkalender ist laut Provider nicht beschreibbar")

            payload = canonical_create_payload(felder, provider_calendar_id)
            payload_digest = digest_of(payload)
            # Die Vorschau ist, was der Mensch freigibt. Sie trägt die
            # Fachwerte absichtlich im Klartext — freigegeben wird, was man
            # **sieht**, nicht ein Digest.
            preview = {
                "command": "create",
                "calendar_display_name": kalender["display_name"],
                "title": felder["title"],
                "starts_at_utc": felder["starts_at_utc"],
                "ends_at_utc": felder["ends_at_utc"],
                "is_all_day": felder["is_all_day"],
                "location": felder["location"],
            }
            preview_digest = digest_of(preview)

            approval_id = str(uuid.uuid4())
            ApprovalStore(uow).request(
                approval_id=approval_id, module=MODULE,
                subject_type=SUBJECT_TYPE, subject_id=mutation_id,
                risk_class="R1", initiation_context=initiation_context,
                actor=actor, correlation_id=correlation_id or mutation_id,
                payload_digest=payload_digest, preview_digest=preview_digest,
                ttl_seconds=self._ttl)

            outbox = ExternalActionOutbox(uow).enqueue(
                module=MODULE, operation="create", subject_type=SUBJECT_TYPE,
                subject_id=mutation_id, approval_id=approval_id,
                idempotency_key=mutation_id, payload_digest=payload_digest)

            jetzt = utc_now()
            uow.execute(
                "INSERT INTO calendar_mutations (mutation_id, command, state, "
                "payload_json, payload_digest, preview_json, preview_digest, "
                "approval_id, outbox_id, target_provider_calendar_id, "
                "created_at, attempt_count) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (mutation_id, "create", "prepared",
                 json.dumps(payload, sort_keys=True, separators=(",", ":"),
                            ensure_ascii=False),
                 payload_digest,
                 json.dumps(preview, sort_keys=True, separators=(",", ":"),
                            ensure_ascii=False),
                 preview_digest, approval_id, outbox.outbox_id,
                 provider_calendar_id, jetzt, 0))

            audit = AuditTrail(uow, module=MODULE)
            audit.record(AuditStage.MUTATION_PREPARED,
                         subject_type=SUBJECT_TYPE, subject_id=mutation_id,
                         facts={"command": "create",
                                "payloadDigest": payload_digest})
            audit.record(AuditStage.APPROVAL_REQUESTED,
                         subject_type=SUBJECT_TYPE, subject_id=mutation_id,
                         facts={"approvalId": approval_id,
                                "previewDigest": preview_digest})

            return PreparedCalendarMutation(
                mutation_id=mutation_id, approval_id=approval_id,
                outbox_id=outbox.outbox_id, state="prepared",
                payload_digest=payload_digest, preview=preview,
                preview_digest=preview_digest)

    def prepare_update(self, event_identifier: str,
                       fields: dict[str, Any], **_: Any) -> None:
        """P2-Vertragsstelle. In P1 ausdrücklich verweigert — keine stille
        Teilimplementierung."""
        if "update" not in ENABLED_COMMANDS:
            raise PositionNotEnabled(
                "'update' ist in dieser Position nicht freigeschaltet")
        raise NotImplementedError  # pragma: no cover - erst ab P2 erreichbar

    def prepare_delete(self, event_identifier: str, **_: Any) -> None:
        """P3-Vertragsstelle. In P1 ausdrücklich verweigert."""
        if "delete" not in ENABLED_COMMANDS:
            raise PositionNotEnabled(
                "'delete' ist in dieser Position nicht freigeschaltet")
        raise NotImplementedError  # pragma: no cover - erst ab P3 erreichbar

    # ── 2. Entscheiden ──────────────────────────────────────────────────────
    def approve(self, mutation_id: str, *, decision_actor: str) -> str:
        """Menschliche Freigabe. Verbraucht wird sie erst beim Claim."""
        with self._uow() as uow:
            zeile = self._require(uow, mutation_id)
            if zeile["state"] != "prepared":
                raise MutationNotExecutable(
                    f"Vorgang ist '{zeile['state']}', nicht 'prepared'")
            ApprovalStore(uow).grant(zeile["approval_id"],
                                     decision_actor=decision_actor)
            pruefe_uebergang(zeile["state"], "approved")
            uow.execute(
                "UPDATE calendar_mutations SET state = 'approved' "
                "WHERE mutation_id = ?", (mutation_id,))
            AuditTrail(uow, module=MODULE).record(
                AuditStage.APPROVAL_GRANTED, subject_type=SUBJECT_TYPE,
                subject_id=mutation_id,
                facts={"approvalId": zeile["approval_id"],
                       "decisionActor": decision_actor})
            return "approved"

    def cancel(self, mutation_id: str, *, decision_actor: str) -> str:
        """Bricht aus `prepared`/`approved` ab. Es wurde und wird nichts
        gesendet; der Outbox-Eintrag wird endgültig aus der Warteschlange
        genommen, ohne je beansprucht worden zu sein."""
        with self._uow() as uow:
            zeile = self._require(uow, mutation_id)
            zustand = zeile["state"]
            if zustand not in ("prepared", "approved"):
                raise MutationNotExecutable(
                    f"Vorgang ist '{zustand}' und nicht mehr abbrechbar")
            pruefe_uebergang(zustand, "cancelled")
            approvals = ApprovalStore(uow)
            freigabe = approvals.get(zeile["approval_id"])
            if freigabe is not None and freigabe.state == "awaiting_approval":
                approvals.cancel(zeile["approval_id"],
                                 decision_actor=decision_actor)
            ExternalActionOutbox(uow).abandon(zeile["outbox_id"],
                                              error_code="cancelled")
            uow.execute(
                "UPDATE calendar_mutations SET state = 'cancelled', "
                "completed_at = ? WHERE mutation_id = ?",
                (utc_now(), mutation_id))
            AuditTrail(uow, module=MODULE).record(
                AuditStage.APPROVAL_CANCELLED, subject_type=SUBJECT_TYPE,
                subject_id=mutation_id,
                facts={"approvalId": zeile["approval_id"],
                       "decisionActor": decision_actor})
            return "cancelled"

    # ── 3. Claim ────────────────────────────────────────────────────────────
    def claim(self, mutation_id: str) -> ExecutionOrderV1:
        """Beansprucht genau einen Versuch und gibt den Auftrag heraus.

        Reihenfolge ist Absicht: erst alle Prüfungen, die **vor** jedem Send
        scheitern dürfen (Backup-Gate, Positionsstufe, Zustand), dann der
        Claim, dann `provider_send_started` in derselben Transaktion.
        """
        # Fail-closed **vor** jeder Beanspruchung: ohne verifizierten
        # Backup-Nachweis existiert kein Schreibauftrag.
        if not self._backup_probe():
            raise BackupMissing(
                "Kein verifizierter Kalender-Backup-Nachweis vorhanden")

        with self._uow() as uow:
            zeile = self._require(uow, mutation_id)
            if zeile["command"] not in ENABLED_COMMANDS:
                raise PositionNotEnabled(
                    f"Operation '{zeile['command']}' ist in dieser Position "
                    "nicht freigeschaltet")
            outbox = ExternalActionOutbox(uow)
            eintrag = outbox.require(zeile["outbox_id"])
            # Vor der Zustandsprüfung: Ein bereits ausgegebener Auftrag ist
            # ein eigener, endgültiger Konflikt — auch nach Verfall, denn ob
            # irgendwo gesendet wurde, ist ab der Ausgabe unbeweisbar.
            if eintrag.auftrag_ausgegeben:
                raise AlreadySettled(
                    "Für diesen Vorgang wurde bereits ein Ausführungsauftrag "
                    "ausgegeben")

            zustand = zeile["state"]
            if zustand != "approved":
                raise MutationNotExecutable(
                    f"Vorgang ist '{zustand}', nicht 'approved'")

            # Freigabe gegen **beide** Digests verbrauchen.
            try:
                ApprovalStore(uow).consume(
                    zeile["approval_id"],
                    payload_digest=zeile["payload_digest"],
                    preview_digest=zeile["preview_digest"])
            except ApprovalError as exc:
                raise MutationNotExecutable(str(exc)) from exc

            try:
                _, token = outbox.claim(zeile["outbox_id"])
            except OutboxNotClaimable as exc:
                raise MutationNotExecutable(str(exc)) from exc

            jetzt = utc_now()
            operation_id = str(uuid.uuid4())
            laeuft_ab = _plus_sekunden(jetzt, CLAIM_TTL_SECONDS)

            uow.execute(
                "UPDATE personal_external_action_outbox SET operation_id = ?, "
                "claim_expires_at = ?, execution_order_issued_at = ? "
                "WHERE outbox_id = ?",
                (operation_id, laeuft_ab, jetzt, zeile["outbox_id"]))

            pruefe_uebergang(zustand, "executing")
            uow.execute(
                "UPDATE calendar_mutations SET state = 'executing', "
                "execution_started_at = ?, attempt_count = ? "
                "WHERE mutation_id = ?",
                (jetzt, outbox.require(zeile["outbox_id"]).attempt_count,
                 mutation_id))

            audit = AuditTrail(uow, module=MODULE)
            fakten = {
                "operationId": operation_id,
                "operationType": zeile["command"],
                "attemptNumber": outbox.require(zeile["outbox_id"]).attempt_count,
                "channel": "app_process",
            }
            audit.record(AuditStage.EXECUTION_CLAIMED,
                         subject_type=SUBJECT_TYPE, subject_id=mutation_id,
                         facts=fakten)
            audit.record(AuditStage.EXECUTION_ORDER_ISSUED,
                         subject_type=SUBJECT_TYPE, subject_id=mutation_id,
                         facts={**fakten, "expiresAt": laeuft_ab})
            # Ab hier gilt: es koennte gesendet werden. Die Stufe steht in
            # dieser Transaktion, damit sie einen Absturz ueberlebt.
            audit.record(AuditStage.PROVIDER_SEND_STARTED,
                         subject_type=SUBJECT_TYPE, subject_id=mutation_id,
                         facts={**fakten, "automaticRetry": False})

            payload = json.loads(zeile["payload_json"])
            return ExecutionOrderV1(
                operation_id=operation_id,
                mutation_id=mutation_id,
                claim_token=token,
                operation_type=zeile["command"],
                payload_digest=zeile["payload_digest"],
                preview_digest=zeile["preview_digest"],
                canonical_payload=payload,
                issued_at=jetzt,
                expires_at=laeuft_ab,
                provider_target={
                    "provider_calendar_id": zeile["target_provider_calendar_id"],
                    "event_identifier": zeile["event_identifier"],
                },
                expected_fingerprint=zeile["base_fingerprint"],
            )

    # ── 4. Settle ───────────────────────────────────────────────────────────
    def settle(self, mutation_id: str, bericht: ExecutionReportV1, *,
               claim_token: str) -> SettleErgebnis:
        """Nimmt genau einen Bericht entgegen — idempotent, ohne
        Providerkontakt. Der Digest wird serverseitig gerechnet."""
        with self._uow() as uow:
            zeile = self._require(uow, mutation_id)
            outbox = ExternalActionOutbox(uow)
            eintrag = outbox.require(zeile["outbox_id"])

            if bericht.mutation_id != mutation_id \
                    or eintrag.operation_id != bericht.operation_id:
                raise SettleConflict(
                    "Der Bericht gehört zu einem anderen Ausführungsversuch")

            digest = report_digest(bericht)

            # Wiederholung desselben Berichts: dieselbe Antwort, keine
            # zweite Wirkung.
            if eintrag.execution_report_digest == digest:
                return SettleErgebnis(
                    mutation_id=mutation_id, state=zeile["state"],
                    outcome=zeile["outcome"], idempotent=True,
                    error_class=eintrag.error_class)
            if eintrag.execution_report_digest is not None:
                raise SettleConflict(
                    "Zu diesem Versuch liegt bereits ein abweichender "
                    "Bericht vor")

            if eintrag.claim_token_digest is None \
                    or eintrag.claim_token_digest != token_digest(claim_token):
                raise SettleConflict("Ungültige Claim-Bindung")

            ziel, outcome, fehlerklasse = _bewerte(bericht)
            pruefe_uebergang(zeile["state"], ziel)

            uow.execute(
                "UPDATE personal_external_action_outbox SET "
                "execution_report_digest = ?, provider_completed_at = ?, "
                "error_class = ?, error_digest = ? WHERE outbox_id = ?",
                (digest, bericht.provider_completed_at, fehlerklasse,
                 bericht.error_digest, zeile["outbox_id"]))

            jetzt = utc_now()
            if ziel == "failed_before_send":
                outbox.mark_failed_before_send(
                    zeile["outbox_id"], claim_token,
                    error_code=fehlerklasse or "not_sent")
                outbox.abandon(zeile["outbox_id"],
                               error_code=fehlerklasse or "not_sent")
            elif ziel == "outcome_unknown":
                outbox.mark_outcome_unknown(
                    zeile["outbox_id"], claim_token,
                    error_code=fehlerklasse or "outcome_unknown")
            else:  # provider_applied_pending_reconcile
                outbox.mark_succeeded(zeile["outbox_id"], claim_token)

            uow.execute(
                "UPDATE calendar_mutations SET state = ?, outcome = ?, "
                "last_error_code = ?, completed_at = ? WHERE mutation_id = ?",
                (ziel, outcome, fehlerklasse,
                 jetzt if ziel in TERMINAL else None, mutation_id))

            # Die Providerwahrheit festschreiben — nur wenn sie belegt ist.
            # Die rohe Kennung IST die Rücknahmeinformation eines create:
            # ohne sie gäbe es keinen Weg zurück zu diesem Termin.
            if ziel == "provider_applied_pending_reconcile" \
                    and bericht.provider_identifier:
                uow.execute(
                    "UPDATE calendar_mutations SET event_identifier = ?, "
                    "readback_digest = ?, rollback_hint_json = ? "
                    "WHERE mutation_id = ?",
                    (bericht.provider_identifier,
                     self._readback_digest(bericht, zeile),
                     json.dumps({"undo": "delete",
                                 "event_identifier": bericht.provider_identifier},
                                sort_keys=True, separators=(",", ":")),
                     mutation_id))

            audit = AuditTrail(uow, module=MODULE)
            audit.record(AuditStage.PROVIDER_RESULT_RECEIVED,
                         subject_type=SUBJECT_TYPE, subject_id=mutation_id,
                         facts={
                             "operationId": bericht.operation_id,
                             "outcome": bericht.outcome,
                             "sendAttempted": bericht.send_attempted,
                             "saveRequestCount": bericht.save_request_count,
                             "readbackStatus": bericht.readback_status,
                             "errorClass": fehlerklasse,
                             "channel": "app_process",
                         })
            audit.record(AuditStage.MUTATION_SETTLED,
                         subject_type=SUBJECT_TYPE, subject_id=mutation_id,
                         facts={
                             "operationId": bericht.operation_id,
                             "state": ziel,
                             "resend": False,
                             "reportDigest": digest,
                         })
            ergebnis = SettleErgebnis(mutation_id=mutation_id, state=ziel,
                                      outcome=outcome, idempotent=False,
                                      error_class=fehlerklasse)

        # Die lokale Nachfuehrung laeuft **nach** der Settle-Transaktion und
        # in ihrer eigenen: Der Providerbeleg steht dann bereits fest, und
        # ein Fehler beim Spiegeln darf ihn nicht zurueckrollen.
        if ziel == "provider_applied_pending_reconcile":
            self._spiegel_nachfuehren(mutation_id, bericht)
            with self._uow() as uow:
                zeile = self._require(uow, mutation_id)
            ergebnis = SettleErgebnis(
                mutation_id=mutation_id, state=zeile["state"],
                outcome=zeile["outcome"], idempotent=False,
                error_class=fehlerklasse)
        return ergebnis

    # ── Lesen ───────────────────────────────────────────────────────────────
    def get(self, mutation_id: str) -> dict[str, Any]:
        """Zustand und Vorschau eines Vorgangs — keine Rohkennungen im Log."""
        with self._uow() as uow:
            zeile = self._require(uow, mutation_id)
            return {
                "mutation_id": zeile["mutation_id"],
                "command": zeile["command"],
                "state": zeile["state"],
                "outcome": zeile["outcome"],
                "preview": json.loads(zeile["preview_json"]),
                "payload_digest": zeile["payload_digest"],
                "preview_digest": zeile["preview_digest"],
                "target_provider_calendar_id":
                    zeile["target_provider_calendar_id"],
                "last_error_code": zeile["last_error_code"],
                "attempt_count": zeile["attempt_count"],
                "created_at": zeile["created_at"],
                "execution_started_at": zeile["execution_started_at"],
                "completed_at": zeile["completed_at"],
            }

    # ── intern ──────────────────────────────────────────────────────────────
    @staticmethod
    def _require(uow: UnitOfWork, mutation_id: str):
        zeile = uow.execute(
            "SELECT * FROM calendar_mutations WHERE mutation_id = ?",
            (mutation_id,)).fetchone()
        if zeile is None:
            raise MutationNotFound("Vorgang existiert nicht")
        return zeile

    @staticmethod
    def _readback_lesen(bericht: ExecutionReportV1) -> tuple[dict[str, Any], str] | None:
        """Liest den Read-back fail-closed: sechs Felder plus
        `provider_calendar_id`, sonst nichts. Unbrauchbar ⇒ `None` — dann
        bleibt der Vorgang in der Zwischenlage, erfunden wird nichts."""
        roh = bericht.readback_event
        if not isinstance(roh, dict) or not roh:
            return None
        erlaubt = set(FIELD_NAMES) | {"provider_calendar_id"}
        if set(roh) - erlaubt:
            return None
        kalender = roh.get("provider_calendar_id")
        if not isinstance(kalender, str) or not kalender:
            return None
        try:
            felder = validate_fields(
                {name: roh[name] for name in FIELD_NAMES if name in roh})
        except InvalidMutationFields:
            return None
        return felder, kalender

    def _readback_digest(self, bericht: ExecutionReportV1,
                         zeile) -> str | None:
        """Der Read-back-Beleg — serverseitig gerechnet, nie übernommen."""
        gelesen = self._readback_lesen(bericht)
        if gelesen is None:
            return None
        felder, kalender = gelesen
        return fingerprint_of(felder, kalender)

    def _spiegel_nachfuehren(self, mutation_id: str,
                             bericht: ExecutionReportV1) -> None:
        """Führt den kanonischen Bestand aus dem **gelesenen** Zustand nach.

        Ohne Kennung, ohne brauchbaren Read-back oder ohne auflösbaren
        Kalender bleibt der Vorgang in `provider_applied_pending_reconcile` —
        ein späterer Abgleich liest, statt dass hier etwas erfunden würde.
        Ein zweiter Providerkontakt findet unter keinen Umständen statt.
        """
        if not bericht.provider_identifier:
            return
        gelesen = self._readback_lesen(bericht)
        if gelesen is None:
            return
        felder, provider_calendar_id = gelesen

        jetzt = utc_now()
        with self._uow() as uow:
            zeile = self._require(uow, mutation_id)
            if zeile["state"] != "provider_applied_pending_reconcile":
                return
            kalender = uow.execute(
                "SELECT id, provider_account_id FROM calendars "
                "WHERE provider_calendar_id = ? AND is_tombstone = 0",
                (provider_calendar_id,)).fetchone()
            if kalender is None:
                return

            ereignis = CanonicalEvent(
                id="", calendar_id=kalender["id"],
                provider_event_id=bericht.provider_identifier,
                provider_calendar_id=provider_calendar_id,
                starts_at_utc=felder["starts_at_utc"],
                ends_at_utc=felder["ends_at_utc"],
                title=felder["title"], notes=felder["notes"],
                location=felder["location"],
                is_all_day=felder["is_all_day"],
            )
            EventRepository(uow).upsert_seen(
                ereignis, kalender["provider_account_id"], jetzt)

            pruefe_uebergang(zeile["state"], "succeeded")
            uow.execute(
                "UPDATE calendar_mutations SET state = 'succeeded', "
                "outcome = 'succeeded', completed_at = ? WHERE mutation_id = ?",
                (jetzt, mutation_id))
            AuditTrail(uow, module=MODULE).record(
                AuditStage.MUTATION_COMPLETED, subject_type=SUBJECT_TYPE,
                subject_id=mutation_id,
                facts={"outcome": "succeeded", "localMirrorUpdated": True})
