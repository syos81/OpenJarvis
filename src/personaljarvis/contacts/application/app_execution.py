"""Claim und Settle des App-Prozess-Mutationskanals (ADR-0026, Phase A).

Der Kern sendet seit ADR-0026 nicht mehr selbst. Er tut zwei Dinge:

1. **Claim** — er beansprucht genau **einen** Ausführungsversuch, verbraucht
   die Freigabe gegen Nutzlast **und** Vorschau, und gibt einen kurzlebigen,
   gebundenen Auftrag heraus. Ab dem Moment der Ausgabe gilt der Versuch als
   möglicherweise gesendet: `provider_send_started` steht in derselben
   Transaktion, **bevor** die Antwort das Backend verlässt.
2. **Settle** — er nimmt genau **einen** typisierten Bericht entgegen,
   rechnet dessen Digest selbst nach und entscheidet den Zustand. Er ruft
   dabei nie einen Provider, nie Tauri und nie den Sidecar.

Was hier bewusst **nicht** passiert: ein zweiter Claim. Weder Verfall noch
Reload, Absturz oder ausbleibender Bericht öffnen einen neuen Versuch —
sobald ein Auftrag ausgegeben wurde, ist unbeweisbar, ob irgendwo gesendet
wurde, und der einzige ehrliche Weg heisst `outcome_unknown` → Abgleich.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from personaljarvis.base.approvals import (
    ApprovalPayloadMismatch,
    ApprovalStore,
)
from personaljarvis.base.audit import AuditTrail
from personaljarvis.base.outbox import (
    ExternalActionOutbox,
    OutboxNotClaimable,
    token_digest,
)
from personaljarvis.contacts.application.delete_gate import (
    loeschbindung,
    pruefe_loeschsicherung,
    schreibe_loeschsicherung,
)
from personaljarvis.contacts.application.errors import (
    AlreadySettled,
    MutationNotExecutable,
    MutationNotFound,
    WriteQuotaExhausted,
)
from personaljarvis.contacts.application.execution_contracts import (
    ExecutionOrderV1,
    ExecutionReportV1,
    report_digest,
)
from personaljarvis.contacts.application.recovery_snapshot import (
    SnapshotErgebnis,
    sichere_zusatzfamilien,
)
from personaljarvis.contacts.application.state_machine import pruefe_uebergang
from personaljarvis.contacts.application.write_quota import (
    activation_id,
    claim_quota,
)
from personaljarvis.contacts.domain.models import utc_now

__all__ = [
    "CLAIM_TTL_SECONDS",
    "AppExecutionService",
    "SettleErgebnis",
    "SettleConflict",
    "ChannelNotEnabled",
    "DeleteConfirmationRequired",
]

MODULE = "contacts"

#: Lebensdauer eines Claims (ADR-0026 §3). Der Verfall wirkt ausschliesslich
#: **vor** der nativen Validierung; nach Auftragsausgabe erlaubt er nie einen
#: neuen Versuch.
CLAIM_TTL_SECONDS = 600

_MUTATION_STATES_APPROVED = "approved"
_MUTATION_STATE_EXECUTING = "executing"


class SettleConflict(RuntimeError):
    """Ein zweiter, abweichender Bericht zu demselben Versuch."""


class ChannelNotEnabled(RuntimeError):
    """Der App-Prozess-Schreibkanal ist nicht freigeschaltet."""


class DeleteConfirmationRequired(RuntimeError):
    """R2: Löschen ohne die zusätzliche Bestätigung im Ausführungsschritt."""


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


class AppExecutionService:
    """Claim- und Settle-Seite des App-Prozess-Kanals.

    Der Dienst arbeitet ausschliesslich auf dem Kern: Datenbank, Outbox,
    Freigaben, Audit. Er kennt weder Tauri noch den Sidecar.
    """

    def __init__(self, persistence, *, channel_capabilities=None,
                 backup_dir=None, release_path=None,
                 snapshot_dir=None) -> None:
        self._persistence = persistence
        #: Wo die Freigabeurkunde liegt — die Kontingentgrenze haengt an ihr.
        #: Ein Parameter und ausdruecklich keine Umgebungsvariable, dieselbe
        #: Regel wie im Kanalhandschlag. `None` heisst der kanonische Ort.
        self._release_path = release_path
        #: Ablageort der Feldstandsicherungen. Ein Parameter und ausdruecklich
        #: keine Umgebungsvariable — dieselbe Regel wie beim Freigabepfad.
        #: `None` heisst: der kanonische Ort im Datenverzeichnis.
        self._backup_dir = backup_dir
        #: Ablageort der Wiederherstellungsschnappschuesse — ein eigener Ort,
        #: nicht der der Sicherungen. Dieselbe Regel: ein Parameter, keine
        #: Umgebungsvariable, `None` heisst der kanonische Ort.
        self._snapshot_dir = snapshot_dir
        #: Was der letzte Wiederherstellungsschnappschuss ergab.
        #:
        #: Bewusst **nicht** in der Auditkette: Die ist das Entscheidungs-
        #: protokoll der Pipeline, und dieser Schnappschuss entscheidet
        #: nichts — eine Stufe dort liesse ihn aussehen, als taete er es.
        #: Ihre Fakten werden ohnehin nur gehasht abgelegt und waeren als
        #: Auskunft unlesbar. Hier steht das Ergebnis lesbar und geprueft.
        self._letzter_schnappschuss = SnapshotErgebnis(
            written=False, reason_code="not_attempted")
        # Ein Aufrufbares statt eines Wertes ist hier bedeutungstragend: Die
        # Schreibfreigabe laeuft ab und kann jederzeit zurueckgenommen
        # werden. Wer den Faehigkeitssatz einmal beim Start festhaelt,
        # beansprucht spaeter Rechte, die es nicht mehr gibt — genau das fiel
        # im Livetest am 2026-08-04 auf, als der laufende Prozess den Kanal
        # nach dem Entzug weiterhin als offen meldete.
        self._caps_quelle = (channel_capabilities
                             if callable(channel_capabilities)
                             else (lambda: channel_capabilities))

    @property
    def _caps(self):
        return self._caps_quelle()

    def _aktivierung(self) -> str | None:
        """Der Fingerabdruck der geltenden Urkunde — die Kontingentgrenze.

        Dieselbe Ableitung wie im Mutationsdienst, damit beide Wege **eine**
        Aktivierung meinen. Zwei Ableitungen ergaeben zwei Kontingente, und der
        Eigentuemer haette zwanzig Schreibvorgaenge statt zehn.

        Ohne gueltige Dauerfreigabe gibt es keine Aktivierung und damit kein
        Kontingent: Dann traegt die befristete Freigabe den Vorgang, und ihre
        Grenze ist die Zeit.
        """
        from personaljarvis.contacts.application.write_release import (
            read_write_release,
        )

        return activation_id(read_write_release(self._release_path))

    # ── Das Loeschgate ──────────────────────────────────────────────────────
    #
    # Geloescht wird nur, was inhaltlich wiederherstellbar ist. Die Sicherung
    # haengt an **dieser** Mutation, nicht an der Datenbank, und sie entsteht
    # unmittelbar vor dem Vorgang — nicht schon bei der Freigabe. Sonst
    # entstuende fuer jede freigegebene, aber nie ausgefuehrte Loeschung eine
    # Klartextkopie eines Kontakts, den es weiterhin gibt.
    def _sichere_loeschziel(self, mutation_id: str, *,
                            confirm_delete: bool) -> None:
        """Schreibt die Feldstandsicherung — nur fuer eine bestaetigte Loeschung.

        Ohne die zweite Bestaetigung wird **nichts** geschrieben: Der Claim
        wuerde ohnehin abgewiesen, und eine Klartextkopie fuer einen Vorgang,
        der gar nicht laufen darf, waere reiner Schaden.

        Ein erneuter Anlauf derselben Mutation trifft dieselbe Datei und
        ueberschreibt sie, statt eine zweite anzulegen.
        """
        if not confirm_delete:
            return
        with self._persistence.unit_of_work() as uow:
            zeile = uow.execute(
                "SELECT * FROM contacts_mutations WHERE mutation_id = ?",
                (mutation_id,)).fetchone()
            if zeile is None or zeile["command"] != "delete":
                # Kein Loeschvorgang: Die Pruefungen im Claim sagen typisiert,
                # was los ist. Hier wird nur nichts gesichert.
                return
            # Aufgeloest **in** der Arbeitseinheit, geschrieben ausserhalb:
            # Die Datei entsteht ohne offene Transaktion.
            bindung = loeschbindung(uow, zeile)
            konto = zeile["provider_account_id"]
        schreibe_loeschsicherung(bindung, at=utc_now(), basis=self._backup_dir)
        # Danach, nie davor, und ohne Rueckwirkung: Der Schnappschuss der drei
        # Familien ausserhalb des Feldvertrags v1 (B-3). Sein Ergebnis wird
        # protokolliert und entscheidet nichts.
        self._letzter_schnappschuss = sichere_zusatzfamilien(
            self._persistence, bindung=bindung, provider_account_id=konto,
            at=utc_now(), basis=self._snapshot_dir)

    # ── Claim ───────────────────────────────────────────────────────────────
    def claim(self, mutation_id: str, *,
              confirm_delete: bool = False) -> ExecutionOrderV1:
        """Beansprucht genau einen Versuch und gibt den Auftrag heraus.

        Reihenfolge ist Absicht: Erst alle Prüfungen, die **vor** jedem Send
        scheitern dürfen, dann der Claim, dann `provider_send_started`. Wer
        die Audit-Stufe erst nach der Antwort schriebe, verlöre bei einem
        Absturz genau die Information, dass gesendet worden sein könnte.
        """
        if self._caps is None or not self._caps.channel_available:
            # Fail-closed: ohne Fähigkeitssatz gibt es keinen Auftrag. Ein
            # fehlender Handshake ist kein Freibrief.
            raise ChannelNotEnabled(
                "Der App-Prozess-Schreibkanal ist nicht freigeschaltet")

        # ── Das Loeschgate, teurer Teil ────────────────────────────────────
        #
        # Bewusst **vor** der Transaktion: Sichern heisst schreiben, zuruecklesen
        # und verifizieren, und das gehoert nicht in eine offene Schreibsperre.
        # Die Durchsetzung steht unten drin, wo sie billig ist.
        self._sichere_loeschziel(mutation_id, confirm_delete=confirm_delete)

        with self._persistence.unit_of_work() as uow:
            zeile = uow.execute(
                "SELECT * FROM contacts_mutations WHERE mutation_id = ?",
                (mutation_id,)).fetchone()
            if zeile is None:
                raise MutationNotFound("Vorgang existiert nicht")

            # Erst hier steht fest, **welche** Operation ansteht: geprüft
            # wird Schreibrecht UND die Fähigkeit genau dieser Operation.
            # Ein Kanal, der `create` kann, darf deshalb noch lange kein
            # `delete` beanspruchen.
            # R2: Löschen verlangt eine **zweite**, eigene Bestätigung im
            # Ausführungsschritt (ADR-0026 §8.3, DEC-053). Sie ersetzt die
            # Freigabe nicht, sie kommt hinzu.
            if zeile["command"] == "delete" and not confirm_delete:
                raise DeleteConfirmationRequired(
                    "Löschen verlangt die ausdrückliche Bestätigung im "
                    "Ausführungsschritt")
            if zeile["command"] != "delete" and confirm_delete:
                # Ein `confirm_delete` bei einer Nicht-Löschung ist kein
                # harmloser Zusatz, sondern ein falsch gebauter Aufruf.
                raise MutationNotExecutable(
                    "confirm_delete gehört ausschliesslich zu 'delete'")
            if not self._caps.darf_ausfuehren(zeile["command"]):
                raise ChannelNotEnabled(
                    f"Operation '{zeile['command']}' ist im App-Prozess-Kanal "
                    "nicht freigeschaltet")

            zustand = zeile["state"]
            if zustand != _MUTATION_STATES_APPROVED:
                # Ein bereits beanspruchter oder abgeschlossener Vorgang
                # bekommt nie einen zweiten Auftrag — auch nicht denselben.
                raise MutationNotExecutable(
                    f"Vorgang ist '{zustand}', nicht 'approved'")

            outbox = ExternalActionOutbox(uow)
            eintrag = outbox.require(zeile["outbox_id"])
            if eintrag.auftrag_ausgegeben:
                raise AlreadySettled(
                    "Für diesen Vorgang wurde bereits ein Ausführungsauftrag "
                    "ausgegeben")

            # ── Das Kontingent, genau hier ─────────────────────────────────
            #
            # Bis zum 2026-08-17 wurde ausschliesslich im aelteren Dienstweg
            # gebucht — und produktiv geht keine Mutation dort entlang. Im
            # Livetest schrieb Jarvis zweimal in den echten Container, und der
            # Zaehler stand danach unveraendert auf zehn von zehn. Der Zaehler
            # war echt, getestet und sichtbar; er sass nur auf dem Weg, den das
            # Produkt nicht geht.
            #
            # Nach bestandener Vorpruefung und vor dem Verbrauch der Freigabe:
            # Alles davor scheitert gefahrlos, alles danach kann senden.
            # Gebucht wird die Mutation, nicht das Ereignis — ein zweiter
            # Anlauf trifft dieselbe Zeile.
            stand = claim_quota(uow, self._aktivierung(), mutation_id,
                                at=utc_now())
            if stand.used > stand.limit:
                raise WriteQuotaExhausted(stand.als_text())

            # ── Das Loeschgate, Durchsetzung ───────────────────────────────
            #
            # Hier und nicht spaeter: **vor** dem Verbrauch der Freigabe und
            # vor der Auftragsausgabe. Ohne Auftrag beruehrt der App-Prozess
            # den Provider nie — das ist der Punkt, an dem eine Loeschung ohne
            # belegten Inhalt endet. Die Ausnahme rollt die Transaktion
            # zurueck: nichts verbraucht, nichts beansprucht, nichts gesendet.
            if zeile["command"] == "delete":
                pruefe_loeschsicherung(loeschbindung(uow, zeile),
                                       basis=self._backup_dir)

            # Freigabe gegen **beide** Digests verbrauchen (ADR-0026 §9).
            try:
                ApprovalStore(uow).consume(
                    zeile["approval_id"],
                    payload_digest=zeile["payload_digest"],
                    preview_digest=zeile["preview_digest"])
            except ApprovalPayloadMismatch as exc:
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

            pruefe_uebergang(zustand, _MUTATION_STATE_EXECUTING)
            uow.execute(
                "UPDATE contacts_mutations SET state = ?, "
                "execution_started_at = ?, attempt_count = ? "
                "WHERE mutation_id = ?",
                (_MUTATION_STATE_EXECUTING, jetzt,
                 outbox.require(zeile["outbox_id"]).attempt_count, mutation_id))

            audit = AuditTrail(uow, module=MODULE)
            fakten = {
                "operationId": operation_id,
                "operationType": zeile["command"],
                "attemptNumber": outbox.require(zeile["outbox_id"]).attempt_count,
                "channel": "app_process",
            }
            audit.record("execution_claimed", subject_type="contact_mutation",
                         subject_id=mutation_id, facts=fakten)
            audit.record("execution_order_issued",
                         subject_type="contact_mutation",
                         subject_id=mutation_id,
                         facts={**fakten, "expiresAt": laeuft_ab})
            # Ab hier gilt: es koennte gesendet werden. Die Stufe steht in
            # dieser Transaktion, damit sie einen Absturz ueberlebt.
            audit.record("provider_send_started",
                         subject_type="contact_mutation",
                         subject_id=mutation_id,
                         facts={**fakten, "automaticRetry": False})

            payload = _kanonischer_payload(zeile)
            return ExecutionOrderV1(
                operation_id=operation_id,
                mutation_id=mutation_id,
                claim_token=token,
                operation_type=zeile["command"],
                payload_digest=zeile["payload_digest"],
                preview_digest=zeile["preview_digest"] or "",
                canonical_payload=payload,
                issued_at=jetzt,
                expires_at=laeuft_ab,
                expected_revision=zeile["expected_revision"],
                provider_target={
                    "container_identifier": zeile["container_identifier"],
                    "provider_identifier": zeile["target_provider_identifier"],
                },
                transaction_author=zeile["transaction_author"],
            )

    # ── Settle ──────────────────────────────────────────────────────────────
    def settle(self, mutation_id: str, bericht: ExecutionReportV1, *,
               claim_token: str) -> SettleErgebnis:
        """Nimmt genau einen Bericht entgegen — idempotent, ohne Providerkontakt.

        Idempotenz ist bewusst inhaltsbasiert: derselbe Bericht darf beliebig
        oft ankommen (Netz, Reload, Wiederholung), ein **abweichender** nie.
        Der Digest wird serverseitig gerechnet; das Frontend liefert ihn nicht.
        """
        with self._persistence.unit_of_work() as uow:
            zeile = uow.execute(
                "SELECT * FROM contacts_mutations WHERE mutation_id = ?",
                (mutation_id,)).fetchone()
            if zeile is None:
                raise MutationNotFound("Vorgang existiert nicht")

            outbox = ExternalActionOutbox(uow)
            eintrag = outbox.require(zeile["outbox_id"])

            if bericht.mutation_id != mutation_id \
                    or eintrag.operation_id != bericht.operation_id:
                raise SettleConflict(
                    "Der Bericht gehört zu einem anderen Ausführungsversuch")

            digest = report_digest(bericht)

            # Wiederholung desselben Berichts: exakt dieselbe Antwort, keine
            # zweite Wirkung, kein zusaetzlicher Versuch.
            if eintrag.execution_report_digest == digest:
                return SettleErgebnis(
                    mutation_id=mutation_id, state=zeile["state"],
                    outcome=zeile["outcome"], idempotent=True,
                    error_class=eintrag.error_class)
            if eintrag.execution_report_digest is not None:
                raise SettleConflict(
                    "Zu diesem Versuch liegt bereits ein abweichender Bericht vor")

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
                "UPDATE contacts_mutations SET state = ?, outcome = ?, "
                "last_error_code = ? WHERE mutation_id = ?",
                (ziel, outcome, fehlerklasse, mutation_id))

            # Die Providerwahrheit festschreiben — **nur** wenn sie belegt
            # ist. Die rohe Kennung landet in der Spalte (ohne sie gaebe es
            # nach dem Create keinen Weg zurueck zu diesem Kontakt); in Audit
            # und Log steht ausschliesslich ihr Digest.
            if ziel == "provider_applied_pending_reconcile" \
                    and bericht.provider_identifier:
                uow.execute(
                    "UPDATE contacts_mutations SET "
                    "target_provider_identifier = ?, readback_digest = ? "
                    "WHERE mutation_id = ?",
                    (bericht.provider_identifier,
                     _readback_digest(bericht), mutation_id))

            audit = AuditTrail(uow, module=MODULE)
            audit.record("provider_result_received",
                         subject_type="contact_mutation",
                         subject_id=mutation_id,
                         facts={
                             "operationId": bericht.operation_id,
                             "outcome": bericht.outcome,
                             "sendAttempted": bericht.send_attempted,
                             "saveRequestCount": bericht.save_request_count,
                             "readbackStatus": bericht.readback_status,
                             "errorClass": fehlerklasse,
                             "channel": "app_process",
                         })
            audit.record("mutation_settled", subject_type="contact_mutation",
                         subject_id=mutation_id,
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
        # ein Fehler beim Spiegeln darf ihn nicht zurueckrollen. Sie loest
        # keinen Provideraufruf aus — die Wahrheit kommt aus dem Bericht.
        if ziel == "provider_applied_pending_reconcile":
            self._spiegel_nachfuehren(mutation_id, bericht)
        return ergebnis

    # ── Lokale Nachfuehrung ────────────────────────────────────────────────
    def _spiegel_nachfuehren(self, mutation_id: str,
                             bericht: ExecutionReportV1) -> None:
        """Fuehrt den kanonischen Bestand aus dem **gelesenen** Zustand nach.

        Erfunden wird nichts: Ohne Kennung und ohne gelesenen Zustand bleibt
        der Vorgang in der Zwischenlage, und der Abgleich uebernimmt — der
        liest, statt zu schreiben. Ein zweiter Providerkontakt findet hier
        unter keinen Umstaenden statt.
        """
        if not bericht.provider_identifier:
            return
        if bericht.operation_type == "delete":
            self._loeschung_nachfuehren(mutation_id, bericht)
            return
        if not bericht.readback_contact:
            return
        from personaljarvis.contacts.application.field_contract import (
            as_bridge_contact,
            parse_canonical_payload,
        )
        from personaljarvis.contacts.application.mutation_service import (
            ContactsMutationService,
        )
        try:
            felder = parse_canonical_payload(bericht.readback_contact)
            rueckgabe = as_bridge_contact(
                felder, provider_identifier=bericht.provider_identifier)
        except Exception:                                   # noqa: BLE001
            # Ein unbrauchbarer Read-back ist kein Grund, irgendetwas zu
            # erfinden: Der Vorgang bleibt in der Zwischenlage.
            return
        ContactsMutationService(self._persistence, None).finalize_pending(
            mutation_id, readback=rueckgabe)

    def _loeschung_nachfuehren(self, mutation_id: str,
                               bericht: ExecutionReportV1) -> None:
        """Schreibt den lokalen Grabstein — nur bei belegter Abwesenheit.

        Der Beleg ist `absent_confirmed`: gezielt über die Kennung gelesen
        und **nicht** gefunden, bei weiterhin gültigem Zugriff. „Nicht
        lesbar" hat der App-Prozess längst als `outcome_unknown` gemeldet und
        kommt hier gar nicht an.

        Die External Identity bleibt stehen. Sie ist der Beleg, wovon der
        Grabstein überhaupt spricht — wer sie löscht, verliert die Zuordnung
        und kann eine spätere Wiederkehr desselben Datensatzes nicht mehr
        erkennen.
        """
        if bericht.readback_status != "absent_confirmed":
            return
        from personaljarvis.contacts.application.mutation_service import (
            MODULE,
            SUBJECT_TYPE,
        )
        from personaljarvis.contacts.domain.models import utc_now as _jetzt

        jetzt = _jetzt()
        with self._persistence.unit_of_work() as uow:
            zeile = uow.execute(
                "SELECT contact_id, provider_account_id, container_identifier "
                "FROM contact_external_ids WHERE provider_identifier = ?",
                (bericht.provider_identifier,)).fetchone()
            if zeile is None:
                # Ohne lokale Identität gibt es nichts nachzuführen — und
                # nichts zu erfinden.
                return
            uow.execute(
                "UPDATE contacts SET is_tombstone = 1, deleted_at = ?, "
                "updated_at = ? WHERE id = ?",
                (jetzt, jetzt, zeile["contact_id"]))
            # Löschnachweis-Historie mit eigenem Grund: diese Löschung war
            # die eigene, nicht die eines fremden Geräts (ADR-0026 §8.3).
            uow.execute(
                "INSERT OR IGNORE INTO contacts_tombstones "
                "(provider_account_id, provider_identifier, contact_id, "
                "deleted_at, reason, retain_until) VALUES (?,?,?,?,?,?)",
                (zeile["provider_account_id"], bericht.provider_identifier,
                 zeile["contact_id"], jetzt, "deleted_by_own_mutation", jetzt))
            uow.execute(
                "UPDATE contacts_mutations SET state = ?, outcome = ?, "
                "completed_at = ? WHERE mutation_id = ?",
                ("succeeded", "succeeded", jetzt, mutation_id))
            AuditTrail(uow, module=MODULE).record(
                "mutation_completed", subject_type=SUBJECT_TYPE,
                subject_id=mutation_id,
                facts={"outcome": "succeeded", "localMirrorUpdated": True,
                       "tombstoned": True})


def _readback_digest(bericht: ExecutionReportV1) -> str | None:
    """Der Revisionsbeleg — serverseitig aus dem gelesenen Zustand gerechnet.

    Bewusst nicht aus dem Bericht uebernommen: Ein vom App-Prozess
    gemeldeter Digest waere eine Behauptung; hier ist er eine Rechnung.
    """
    if not bericht.readback_contact:
        return None
    from personaljarvis.contacts.application.field_contract import (
        parse_canonical_payload,
        readback_digest,
    )
    try:
        return readback_digest(parse_canonical_payload(bericht.readback_contact))
    except Exception:                                       # noqa: BLE001
        return None


def _bewerte(bericht: ExecutionReportV1) -> tuple[str, str | None, str | None]:
    """Übersetzt einen Bericht in den Zielzustand.

    Die Zuordnung ist absichtlich streng: Nur ein `not_sent` **ohne**
    Sendeversuch darf `failed_before_send` werden — das ist die einzige
    Aussage, die „nachweislich nichts übergeben" bedeutet. Alles andere,
    was nicht sauber angewandt ist, endet im ungewissen Ausgang.
    """
    if bericht.beweist_nichts_gesendet:
        return "failed_before_send", "failed", bericht.error_class
    if bericht.outcome == "applied" and bericht.readback_status in (
            "confirmed", "absent_confirmed"):
        return "provider_applied_pending_reconcile", None, None
    return "outcome_unknown", "outcome_unknown", bericht.error_class


def _kanonischer_payload(zeile) -> dict:
    """Die **vollstaendige** kanonische Nutzlast — genau das, was der
    `payload_digest` deckt.

    Nur `fields` mitzugeben waere verlockend (der native Save braucht nur
    sie), aber dann koennte Rust den Digest nicht nachrechnen — und genau
    diese Nachrechnung ist die Bindung zwischen dem, was der Mensch
    freigegeben hat, und dem, was ausgefuehrt wird (ADR-0026 §5).
    """
    import json
    roh = json.loads(zeile["payload_json"])
    return roh if isinstance(roh, dict) else {}
