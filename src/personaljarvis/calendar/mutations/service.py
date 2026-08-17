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
    owner_decision,
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
from personaljarvis.base.product_readiness import (
    product_write_ready,
    readiness_reason,
)
from personaljarvis.calendar.domain import CanonicalEvent
from personaljarvis.calendar.mutations.contracts import (
    ExecutionOrderV1,
    ExecutionReportV1,
    FIELD_NAMES,
    InvalidMutationFields,
    canonical_create_payload,
    assess_restorability,
    canonical_delete_payload,
    canonical_update_payload,
    control_binding_digest_of,
    eligibility_digest_of,
    fingerprint_of,
    preimage_fingerprint_of,
    report_digest,
    restore_preimage_of,
    semantic_state_digest_of,
    validate_changes,
    validate_control_observation,
    validate_eligibility_probe,
    validate_fields,
)
from personaljarvis.calendar.repositories import EventRepository
from personaljarvis.errors import PersonalJarvisError


def utc_now() -> str:
    """UTC-Zeitstempel in ISO-8601 (07 §4). Bewusst lokal definiert: der
    Kalender importiert keinen Kontakte-Code (Modulgrenze, `test_boundaries`).

    Suffix ausdrücklich `Z` statt `+00:00`: das ist das eine Vertragsformat
    dieses Moduls (B3-Livebefund vom 2026-08-09 — der native Adapter und der
    Server müssen denselben Zeittext sprechen)."""
    return (datetime.now(timezone.utc).replace(microsecond=0)
            .isoformat().replace("+00:00", "Z"))

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
    "EventNotFound",
    "CalendarNotWritable",
    "MutationNotExecutable",
    "AlreadySettled",
    "SettleConflict",
    "PositionNotEnabled",
    "BackupMissing",
    "DeleteNotEligible",
    "DeleteNotRestorable",
    "PositiveControlMissing",
    "origin_continuity_of",
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

#: Positionsstufe B3 P3: `create`, `update` und `delete`. Diese Konstante
#: ist die **eine** Stelle, an der eine Position Kommandos freischaltet.
ENABLED_COMMANDS: frozenset[str] = frozenset({"create", "update", "delete"})

#: Die Fähigkeit, deren Produktreife dieser Pfad braucht. Der Name steht hier
#: einmal und wird nirgends zusammengesetzt: eine getippte Fähigkeit fände
#: keinen Eintrag und wäre damit unreif — fail-closed.
CAPABILITY = "calendar"

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


class EventNotFound(CalendarMutationError):
    """Der zu ändernde Termin existiert nicht (mehr) im produktiven Bestand.
    Ohne Preimage gibt es kein Update — erfunden wird nichts."""

    reason_code = "event_not_found"


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


class ProductWriteNotReady(CalendarMutationError):
    """Das Modul darf grundsätzlich nicht mutieren — unabhängig davon, was der
    Eigentümer freigegeben hat.

    Bewusst ein eigener Fehler **über** der Freigabe: Eine formal einwandfreie
    Einzelfreigabe ist eine Aussage über den Willen des Eigentümers, keine über
    den Bauzustand des Schreibpfads. Solange der Bestand Serienvorkommen
    überschreibt, entsteht hier kein Auftrag — mit Freigabe so wenig wie ohne.
    """

    reason_code = "product_write_not_ready"


class BackupMissing(CalendarMutationError):
    reason_code = "backup_missing"


class DeleteNotRestorable(CalendarMutationError):
    """Die vollständige aktuelle Wiederherstellbarkeit ist nicht POSITIV
    belegt (B3 P3, Entscheidung 8: `no_known_blocker` ist verworfen,
    Unbekannt ist blockiert). Die Meldung nennt ausschliesslich
    geschlossene Blockadegründe, nie einen Inhalt."""

    reason_code = "delete_not_restorable"


class PositiveControlMissing(CalendarMutationError):
    """Ohne produktiv gelesene, gebundene positive Kontrolle desselben
    Kalenders gibt es keine Delete-Vorschau und keine Freigabe (B3 P3,
    Entscheidung 10/11). Es wird NIE ein Termin nur als Kontrollobjekt
    erzeugt."""

    reason_code = "positive_control_missing"


class DeleteNotEligible(CalendarMutationError):
    """Der Termin trägt eine belegte, semantisch relevante Eigenschaft
    ausserhalb des wiederherstellbaren B3-Vertrags (B3 P3, Grundregel:
    blocked — nicht warnen und trotzdem löschen). Es entsteht KEINE
    Mutation, KEINE Freigabe, KEIN Outbox-Eintrag. Die Meldung nennt nur
    Flagnamen, nie Inhalte."""

    reason_code = "delete_not_eligible"


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


# ── Herkunftskontinuität ───────────────────────────────────────────────────
def origin_continuity_of(uow: UnitOfWork, provider_calendar_id: str,
                         event_identifier: str,
                         aktueller_zustand: dict[str, Any]) -> dict[str, Any]:
    """Bestimmt die Herkunftskontinuität aus der PERSISTIERTEN B3-Linie.

    `jarvis_origin` folgt niemals allein aus der Eventkennung (B3 P3,
    Entscheidung 5): autoritativ ist ausschliesslich die lokale, erfolgreich
    gesettelte CREATE-Linie. Zwei getrennte Bindungen müssen halten
    (Entscheidung 6):

    * IDENTITY_BINDING — dieselbe `provider_calendar_id` UND derselbe
      `event_identifier` über die gesamte Linie.
    * SEMANTIC_STATE_BINDING — der identitätsfreie Zustandsdigest des
      aktuell beobachteten Zustands gegen den des letzten erfolgreichen
      Settle. Weicht er ab, wurde extern geändert (Entscheidung 7):
      kein Reclaim, keine Warnfreigabe, keine Wahrscheinlichkeit.

    Fehlt ein notwendiges Bindeglied, ist das Ergebnis `unproven` — nie ein
    heuristischer Ersatz. Insbesondere: der historisch persistierte
    `readback_digest` bindet die Kalenderidentität mit und ist damit NICHT
    der identitätsfreie Zustandsdigest; wo dieser fehlt, bleibt die
    semantische Bindung unbeweisbar.
    """
    gruende: list[str] = []
    zeilen = uow.execute(
        "SELECT command, state, event_identifier, "
        "target_provider_calendar_id, readback_digest, semantic_state_digest "
        "FROM calendar_mutations WHERE event_identifier = ? "
        "AND state = 'succeeded' ORDER BY created_at",
        (event_identifier,)).fetchall()
    linie = [dict(z) for z in zeilen]
    if not any(z["command"] == "create" for z in linie):
        gruende.append("no_successful_create_settle")
    for z in linie:
        if z["target_provider_calendar_id"] != provider_calendar_id:
            gruende.append("calendar_identity_changed")
            break
    letzter = linie[-1] if linie else None
    semantisch = letzter["semantic_state_digest"] if letzter else None
    if semantisch is None:
        # Kein identitätsfreier Zustandsdigest in der Linie: die semantische
        # Bindung ist nicht rekonstruierbar (der vorhandene readback_digest
        # bindet die Kalenderidentität mit).
        gruende.append("semantic_state_binding_missing")
    else:
        try:
            aktuell = semantic_state_digest_of(aktueller_zustand)
        except InvalidMutationFields:
            gruende.append("current_semantic_state_unreadable")
        else:
            if aktuell != semantisch:
                gruende.append("semantic_state_digest_mismatch")
    return {
        "origin_continuity": "unproven" if gruende else "proven",
        "blocking_reasons": sorted(set(gruende)),
        "identity_binding": {
            "provider_calendar_id": provider_calendar_id,
            "event_identifier": event_identifier,
            "settled_stages": [z["command"] for z in linie],
        },
        "semantic_state_digest": semantisch,
    }


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
    return ((basis + timedelta(seconds=sekunden))
            .isoformat().replace("+00:00", "Z"))


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
                # Der Zeitzonenanker gehört in die Freigabe: `null` heisst
                # hier ausdrücklich schwebend, nie „wird schon passen".
                "time_zone": felder["time_zone"],
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

    def prepare_update(self, provider_calendar_id: str, event_identifier: str,
                       changes: dict[str, Any], *,
                       actor: str = "lukas",
                       initiation_context: str = "user_direct",
                       correlation_id: str | None = None,
                       ) -> PreparedCalendarMutation:
        """Bereitet ein DELTA-Update vor (B3 P2, Eigentümerentscheidung).

        Kein Full Replace: `changes` trägt ausschliesslich die zu ändernden
        der sieben Vertragsfelder. Das Event wird aus dem **produktiven**
        Bestand (events + event_external_ids) geladen; sein vollständiger
        stabiler Read-Zustand wird als `preimage_json` festgehalten und als
        `expected_fingerprint` in den Auftrag gebunden — der native Pfad
        liest vor der Mutation frisch nach und verweigert bei Abweichung
        (`revision_conflict`), bevor irgendetwas gespeichert wird.
        """
        if "update" not in ENABLED_COMMANDS:  # pragma: no cover - Konstante
            raise PositionNotEnabled(
                "'update' ist in dieser Position nicht freigeschaltet")
        if not isinstance(provider_calendar_id, str) or not provider_calendar_id:
            raise InvalidMutationFields(
                "provider_calendar_id ist keine brauchbare Kennung")
        if not isinstance(event_identifier, str) or not event_identifier:
            raise InvalidMutationFields(
                "event_identifier ist keine brauchbare Kennung")
        delta = validate_changes(changes)

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

            termin = uow.execute(
                "SELECT e.title, e.starts_at_utc, e.ends_at_utc, "
                "e.is_all_day, e.location, e.notes, e.time_zone "
                "FROM event_external_ids x JOIN events e ON e.id = x.event_id "
                "WHERE x.provider_calendar_id = ? AND x.provider_event_id = ? "
                "AND e.is_tombstone = 0",
                (provider_calendar_id, event_identifier)).fetchone()
            if termin is None:
                raise EventNotFound(
                    "Der zu ändernde Termin existiert nicht im Bestand")

            # Der Vorzustand — exakt die Feldmenge, die auch der native Pfad
            # frisch nachlesen kann (sieben Felder plus Identität). SQLite
            # liefert 0/1; der Fingerprint verlangt echte Wahrheitswerte.
            preimage: dict[str, Any] = {
                "title": termin["title"],
                "starts_at_utc": termin["starts_at_utc"],
                "ends_at_utc": termin["ends_at_utc"],
                "is_all_day": bool(termin["is_all_day"]),
                "location": termin["location"],
                "notes": termin["notes"],
                "time_zone": termin["time_zone"],
                "provider_calendar_id": provider_calendar_id,
                "event_identifier": event_identifier,
            }
            # Der ZUSAMMENGEFÜHRTE Zustand muss ein gültiger Termin sein —
            # erst hier ist `ends > starts` entscheidbar (z. B. bewusste
            # Ende-Änderung ohne Beginn im Delta). Die normalisierten Werte
            # der geänderten Felder kommen aus derselben Prüfung wie beim
            # Create — eine Wahrheit, keine zweite Validierung.
            zusammen = validate_fields({
                **{name: preimage[name] for name in FIELD_NAMES}, **delta})
            delta = {name: zusammen[name] for name in delta}
            expected_fingerprint = preimage_fingerprint_of(preimage)

            payload = canonical_update_payload(
                delta, provider_calendar_id, event_identifier,
                expected_fingerprint)
            payload_digest = digest_of(payload)
            # Die Vorschau ist das Delta, das der Mensch freigibt: je Feld
            # aktueller Wert → neuer Wert, plus die Identität des Termins
            # (Kalendername, Titel, Datum/Zeit) — freigegeben wird, was man
            # **sieht**, nicht ein Digest.
            preview = {
                "command": "update",
                "calendar_display_name": kalender["display_name"],
                "title": preimage["title"],
                "starts_at_utc": preimage["starts_at_utc"],
                "ends_at_utc": preimage["ends_at_utc"],
                "is_all_day": preimage["is_all_day"],
                "location": preimage["location"],
                "time_zone": preimage["time_zone"],
                "changes": {
                    name: {"from": preimage[name], "to": delta[name]}
                    for name in FIELD_NAMES if name in delta
                },
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
                module=MODULE, operation="update", subject_type=SUBJECT_TYPE,
                subject_id=mutation_id, approval_id=approval_id,
                idempotency_key=mutation_id, payload_digest=payload_digest)

            jetzt = utc_now()
            uow.execute(
                "INSERT INTO calendar_mutations (mutation_id, command, state, "
                "payload_json, payload_digest, preview_json, preview_digest, "
                "approval_id, outbox_id, target_provider_calendar_id, "
                "event_identifier, base_fingerprint, preimage_json, "
                "created_at, attempt_count) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (mutation_id, "update", "prepared",
                 json.dumps(payload, sort_keys=True, separators=(",", ":"),
                            ensure_ascii=False),
                 payload_digest,
                 json.dumps(preview, sort_keys=True, separators=(",", ":"),
                            ensure_ascii=False),
                 preview_digest, approval_id, outbox.outbox_id,
                 provider_calendar_id, event_identifier, expected_fingerprint,
                 json.dumps(preimage, sort_keys=True, separators=(",", ":"),
                            ensure_ascii=False),
                 jetzt, 0))

            audit = AuditTrail(uow, module=MODULE)
            audit.record(AuditStage.MUTATION_PREPARED,
                         subject_type=SUBJECT_TYPE, subject_id=mutation_id,
                         facts={"command": "update",
                                "payloadDigest": payload_digest,
                                "baseFingerprint": expected_fingerprint})
            audit.record(AuditStage.APPROVAL_REQUESTED,
                         subject_type=SUBJECT_TYPE, subject_id=mutation_id,
                         facts={"approvalId": approval_id,
                                "previewDigest": preview_digest})

            return PreparedCalendarMutation(
                mutation_id=mutation_id, approval_id=approval_id,
                outbox_id=outbox.outbox_id, state="prepared",
                payload_digest=payload_digest, preview=preview,
                preview_digest=preview_digest)

    def prepare_delete(self, provider_calendar_id: str, event_identifier: str,
                       eligibility_probe: dict[str, Any],
                       control_observation: dict[str, Any] | None = None, *,
                       actor: str = "lukas",
                       initiation_context: str = "user_direct",
                       correlation_id: str | None = None,
                       ) -> PreparedCalendarMutation:
        """Bereitet einen Delete vor (B3 P3) — oder blockiert VOR jeder
        Mutation.

        Drei getrennte Nachweise werden hier gebunden (verbindliche
        Eigentümerentscheidung):

        1. `expected_fingerprint` — der vollständige stabile Read-Zustand
           (neun Felder) aus dem produktiven Bestand.
        2. `eligibility_digest` — die am NATIVEN Event erhobene
           Delete-Safety-Probe. Sie kommt vom App-Prozess durch die
           Oberfläche; gerade DESHALB rechnet der native Pfad sie vor dem
           Execute neu und vergleicht den Digest — eine manipulierte Probe
           bricht dort, nicht hier. Jede belegte unsupported Eigenschaft
           blockiert hier fail-closed: keine Mutation, keine Freigabe.
        3. `restore_preimage_digest` — das Restore-Artefakt. Es wird hier
           tatsächlich erzeugt, gegen den Create-Vertrag validiert und in
           `rollback_hint_json` abgelegt, BEVOR irgendetwas gelöscht wird.
        """
        if "delete" not in ENABLED_COMMANDS:  # pragma: no cover - Konstante
            raise PositionNotEnabled(
                "'delete' ist in dieser Position nicht freigeschaltet")
        if not isinstance(provider_calendar_id, str) or not provider_calendar_id:
            raise InvalidMutationFields(
                "provider_calendar_id ist keine brauchbare Kennung")
        if not isinstance(event_identifier, str) or not event_identifier:
            raise InvalidMutationFields(
                "event_identifier ist keine brauchbare Kennung")
        probe = validate_eligibility_probe(eligibility_probe)
        # Die Probe muss GENAU dieses Ziel vermessen haben — eine Probe eines
        # anderen Events bindet nichts.
        if probe["event_identifier"] != event_identifier \
                or probe["provider_calendar_id"] != provider_calendar_id:
            raise InvalidMutationFields(
                "Die Eligibility-Probe gehört zu einem anderen Ziel")
        if not probe["eligible"]:
            # Grundregel: blocked, nicht warnen-und-löschen. Nur Flagnamen.
            raise DeleteNotEligible(
                "Nicht verlustfrei wiederherstellbar: "
                + ", ".join(probe["unsupported_feature_flags"]))

        # Positive Kontrolle als VORBEDINGUNG (Entscheidung 10/11): ohne
        # produktiv gelesene, eigenständige Kontrolle desselben Kalenders
        # gibt es keine Vorschau und keine Freigabe. Es wird NIE ein Termin
        # nur als Kontrollobjekt erzeugt.
        if control_observation is None:
            raise PositiveControlMissing(
                "Keine produktiv gelesene positive Kontrolle gebunden")
        kontrolle = validate_control_observation(control_observation)
        if kontrolle["control_provider_calendar_id"] != provider_calendar_id:
            raise PositiveControlMissing(
                "Die Kontrolle liegt nicht im Zielkalender")
        if kontrolle["control_event_identifier"] == event_identifier:
            raise PositiveControlMissing(
                "Die Kontrolle ist das Ziel selbst")

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

            termin = uow.execute(
                "SELECT e.title, e.starts_at_utc, e.ends_at_utc, "
                "e.is_all_day, e.location, e.notes, e.time_zone "
                "FROM event_external_ids x JOIN events e ON e.id = x.event_id "
                "WHERE x.provider_calendar_id = ? AND x.provider_event_id = ? "
                "AND e.is_tombstone = 0",
                (provider_calendar_id, event_identifier)).fetchone()
            if termin is None:
                raise EventNotFound(
                    "Der zu löschende Termin existiert nicht im Bestand")

            preimage: dict[str, Any] = {
                "title": termin["title"],
                "starts_at_utc": termin["starts_at_utc"],
                "ends_at_utc": termin["ends_at_utc"],
                "is_all_day": bool(termin["is_all_day"]),
                "location": termin["location"],
                "notes": termin["notes"],
                "time_zone": termin["time_zone"],
                "provider_calendar_id": provider_calendar_id,
                "event_identifier": event_identifier,
            }
            expected_fingerprint = preimage_fingerprint_of(preimage)
            eligibility_digest = eligibility_digest_of(probe)
            # Das Restore-Artefakt entsteht JETZT — validiert gegen den
            # Create-Vertrag. Fällt es, gibt es keinen Delete-Vorgang.
            restore = restore_preimage_of(preimage)
            restore_digest = digest_of(restore)

            # Herkunft und Wiederherstellbarkeit — POSITIV zu belegen, sonst
            # blockiert (Entscheidung 5/8). `no_known_blocker` genügt nicht.
            herkunft = origin_continuity_of(
                uow, provider_calendar_id, event_identifier,
                {name: preimage[name] for name in FIELD_NAMES})
            urteil = assess_restorability(
                origin_continuity=herkunft["origin_continuity"],
                eligibility_probe=probe, restore_preimage_present=True)
            if not urteil["restorability_proven"]:
                raise DeleteNotRestorable(
                    "Wiederherstellbarkeit nicht belegt: "
                    + ", ".join(urteil["blocking_reasons"]
                                + herkunft["blocking_reasons"]))

            payload = canonical_delete_payload(
                provider_calendar_id, event_identifier, expected_fingerprint,
                eligibility_digest, restore_digest,
                control_binding_digest_of(kontrolle))
            payload_digest = digest_of(payload)
            # Die Vorschau ist, was der Mensch freigibt: die verständliche
            # Terminidentität, der Hinweis auf die Löschung, die belegte
            # Wiederherstellbarkeit und das vorhandene Restore-Artefakt.
            preview = {
                "command": "delete",
                "calendar_display_name": kalender["display_name"],
                "title": preimage["title"],
                "starts_at_utc": preimage["starts_at_utc"],
                "ends_at_utc": preimage["ends_at_utc"],
                "is_all_day": preimage["is_all_day"],
                "location": preimage["location"],
                "time_zone": preimage["time_zone"],
                "deletion": {
                    "eligible": True,
                    "unsupported_feature_flags": [],
                    "restore_preimage_present": True,
                },
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
                module=MODULE, operation="delete", subject_type=SUBJECT_TYPE,
                subject_id=mutation_id, approval_id=approval_id,
                idempotency_key=mutation_id, payload_digest=payload_digest)

            jetzt = utc_now()
            uow.execute(
                "INSERT INTO calendar_mutations (mutation_id, command, state, "
                "payload_json, payload_digest, preview_json, preview_digest, "
                "approval_id, outbox_id, target_provider_calendar_id, "
                "event_identifier, base_fingerprint, preimage_json, "
                "rollback_hint_json, created_at, attempt_count) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (mutation_id, "delete", "prepared",
                 json.dumps(payload, sort_keys=True, separators=(",", ":"),
                            ensure_ascii=False),
                 payload_digest,
                 json.dumps(preview, sort_keys=True, separators=(",", ":"),
                            ensure_ascii=False),
                 preview_digest, approval_id, outbox.outbox_id,
                 provider_calendar_id, event_identifier, expected_fingerprint,
                 json.dumps(preimage, sort_keys=True, separators=(",", ":"),
                            ensure_ascii=False),
                 # Das Restore-Artefakt liegt VOR der Löschung in der Zeile.
                 json.dumps({"undo": "create", "restore_preimage": restore,
                             "restore_preimage_digest": restore_digest},
                            sort_keys=True, separators=(",", ":"),
                            ensure_ascii=False),
                 jetzt, 0))

            audit = AuditTrail(uow, module=MODULE)
            audit.record(AuditStage.MUTATION_PREPARED,
                         subject_type=SUBJECT_TYPE, subject_id=mutation_id,
                         facts={"command": "delete",
                                "payloadDigest": payload_digest,
                                "baseFingerprint": expected_fingerprint,
                                "eligibilityDigest": eligibility_digest,
                                "restorePreimageDigest": restore_digest})
            audit.record(AuditStage.APPROVAL_REQUESTED,
                         subject_type=SUBJECT_TYPE, subject_id=mutation_id,
                         facts={"approvalId": approval_id,
                                "previewDigest": preview_digest})

            return PreparedCalendarMutation(
                mutation_id=mutation_id, approval_id=approval_id,
                outbox_id=outbox.outbox_id, state="prepared",
                payload_digest=payload_digest, preview=preview,
                preview_digest=preview_digest)

    # ── 2. Entscheiden ──────────────────────────────────────────────────────
    def approve(self, mutation_id: str, *, decision_actor: str) -> str:
        """Menschliche Freigabe. Verbraucht wird sie erst beim Claim."""
        with self._uow() as uow:
            zeile = self._require(uow, mutation_id)
            if zeile["state"] != "prepared":
                raise MutationNotExecutable(
                    f"Vorgang ist '{zeile['state']}', nicht 'prepared'")
            # Derselbe Freigabekern, dieselbe Grenze: Seit 2026-08-13
            # verlangt `grant` die gesiegelte Eigentuemerentscheidung statt
            # eines Namens. Eine Grenze, die nur fuer ein Modul gilt, ist
            # keine.
            ApprovalStore(uow).grant(zeile["approval_id"],
                                     decision=owner_decision(decision_actor))
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
        scheitern dürfen (Produktreife, Backup-Gate, Positionsstufe, Zustand),
        dann der Claim, dann `provider_send_started` in derselben Transaktion.
        """
        # Zuerst die Reife, vor allem anderen und vor jeder Freigabe: Der
        # Claim ist die **einzige** Tür zum Provider — ohne Auftrag sendet
        # niemand. Eine gültige, unverbrauchte Einzelfreigabe kommt hier
        # deshalb an und darf trotzdem nichts bewirken.
        if not product_write_ready(CAPABILITY):
            raise ProductWriteNotReady(readiness_reason(CAPABILITY))

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
            # Die Rücknahmeinformation ist je Kommando eine andere: nach
            # einem create ist die rohe Kennung der Weg zurück; nach einem
            # update sind es die B3-editierbaren Felder des festgehaltenen
            # Vorzustands — das Delta rückwärts; nach einem delete ist es das
            # beim Vorbereiten erzeugte Restore-Artefakt (deterministisch
            # aus dem Preimage nachgerechnet — dieselbe Wahrheit).
            if ziel == "provider_applied_pending_reconcile" \
                    and bericht.provider_identifier:
                if zeile["command"] == "update":
                    preimage = json.loads(zeile["preimage_json"])
                    hinweis = {"undo": "update",
                               "preimage": {name: preimage.get(name)
                                            for name in FIELD_NAMES}}
                elif zeile["command"] == "delete":
                    preimage = json.loads(zeile["preimage_json"])
                    restore = restore_preimage_of(preimage)
                    hinweis = {"undo": "create", "restore_preimage": restore,
                               "restore_preimage_digest": digest_of(restore)}
                else:
                    hinweis = {"undo": "delete",
                               "event_identifier": bericht.provider_identifier}
                # Der identitätsfreie Zustandsdigest entsteht aus dem
                # GELESENEN Zustand — er ist die zweite, von der Identität
                # unabhängige Herkunftsbindung (B3 P3).
                gelesen = self._readback_lesen(bericht)
                semantisch = (semantic_state_digest_of(gelesen[0])
                              if gelesen is not None else None)
                uow.execute(
                    "UPDATE calendar_mutations SET semantic_state_digest = ? "
                    "WHERE mutation_id = ?", (semantisch, mutation_id))
                uow.execute(
                    "UPDATE calendar_mutations SET event_identifier = ?, "
                    "readback_digest = ?, rollback_hint_json = ? "
                    "WHERE mutation_id = ?",
                    (bericht.provider_identifier,
                     self._readback_digest(bericht, zeile),
                     json.dumps(hinweis, sort_keys=True,
                                separators=(",", ":"), ensure_ascii=False),
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
        """Zustand und Vorschau eines Vorgangs — keine Rohkennungen im Log.

        `approval_state` ist der **wirksame** Zustand der Freigabe, nicht der
        gespeicherte: eine erteilte, aber abgelaufene Freigabe liest sich hier
        als `expired`. Der Ausführungsweg der Oberfläche prüft ihn, bevor er
        beansprucht — dieselbe Zeitlogik, die `consume()` fail-closed anwendet,
        statt einer zweiten, irgendwann abweichenden Formulierung.
        """
        with self._uow() as uow:
            zeile = self._require(uow, mutation_id)
            freigabe = ApprovalStore(uow).require(zeile["approval_id"])
            return {
                "mutation_id": zeile["mutation_id"],
                "command": zeile["command"],
                "state": zeile["state"],
                "approval_state": freigabe.effective_state(),
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
        """Liest den Read-back fail-closed: sieben Felder plus
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
        if bericht.operation_type == "delete":
            self._spiegel_tombstone(mutation_id, bericht)
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
                # Die Zone kommt aus dem GELESENEN Zustand — `None` bleibt
                # `None` (schwebend), nie eine erfundene Systemzone.
                time_zone=felder["time_zone"],
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

    def _spiegel_tombstone(self, mutation_id: str,
                           bericht: ExecutionReportV1) -> None:
        """Führt den Spiegel nach einem provider-bestätigten Delete nach.

        Nur `absent_confirmed` zählt: eine leere Zielsuche allein ist KEIN
        Beweis — der Bericht muss die Abwesenheit über den gezielten
        Read-back bestätigt haben, sonst bleibt der Vorgang in der
        Zwischenlage und ein späterer Abgleich liest.
        """
        if bericht.readback_status != "absent_confirmed":
            return
        jetzt = utc_now()
        with self._uow() as uow:
            zeile = self._require(uow, mutation_id)
            if zeile["state"] != "provider_applied_pending_reconcile":
                return
            getroffen = EventRepository(uow).tombstone_confirmed_deleted(
                zeile["target_provider_calendar_id"],
                bericht.provider_identifier, jetzt)
            pruefe_uebergang(zeile["state"], "succeeded")
            uow.execute(
                "UPDATE calendar_mutations SET state = 'succeeded', "
                "outcome = 'succeeded', completed_at = ? WHERE mutation_id = ?",
                (jetzt, mutation_id))
            AuditTrail(uow, module=MODULE).record(
                AuditStage.MUTATION_COMPLETED, subject_type=SUBJECT_TYPE,
                subject_id=mutation_id,
                # Ehrlich: ob der Spiegel eine lebende Zeile getroffen hat.
                facts={"outcome": "succeeded",
                       "localMirrorUpdated": bool(getroffen)})
