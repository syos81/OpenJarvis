"""Phase A des App-Prozess-Mutationskanals: Claim, Transport, Settle.

**Kontaktfrei.** Kein Sidecar, kein `CNContactStore`, kein Provider — die
Kernaussage dieser Suite ist gerade, dass in Phase A **nichts** gesendet
wird. Alle Datenbanken liegen in `tmp_path`, alle Daten sind synthetisch.

Die Invariante, die jeder Test hier verteidigt: **ein Claim, ein Auftrag,
höchstens ein Bericht** — und nach ausgegebenem Auftrag nie ein zweiter
Versuch, egal was schiefgeht.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from personaljarvis.contacts.application import ContactsMutationService
from personaljarvis.contacts.application.app_execution import (
    AppExecutionService,
    ChannelNotEnabled,
    SettleConflict,
)
from personaljarvis.contacts.application.commands import (
    ContactDraft,
    CreateContact,
)
from personaljarvis.contacts.application.errors import (
    AlreadySettled,
    MutationNotExecutable,
)
from personaljarvis.contacts.application.execution_contracts import (
    EXECUTION_SCHEMA_VERSION,
    MAX_REPORT_BYTES,
    ExecutionContractError,
    ExecutionReportV1,
    parse_execution_report,
    report_digest,
)
from personaljarvis.contacts.application.mutation_service import MutationState
from personaljarvis.contacts.domain.capabilities import ContactCapabilitySet
from personaljarvis.contacts.domain.enums import InitiationContext
from personaljarvis.contacts.domain.models import ContactSyncState
from personaljarvis.contacts.repositories.sqlite import SqliteSyncStateRepository

from .conftest import WORKSPACE, new_id

KONTO = "apple-local"
CONTAINER = "01234567-89AB-CDEF-0123-456789ABCDEF:ABAccount"
MENSCH = "lukas"


class NieGerufenerProvider:
    """Jeder Aufruf ist ein Vertragsbruch — Phase A sendet nicht."""

    def __init__(self) -> None:
        self.calls = 0

    def apply(self, *args, **kwargs):  # pragma: no cover - darf nie laufen
        self.calls += 1
        raise AssertionError("Phase A darf keinen Provider aufrufen")


CAPS = ContactCapabilitySet(create_supported=True)


def Kanal(verfuegbar: bool = True):
    """Der Fähigkeitssatz für einen synthetischen Lauf.

    Seit der Härtung gibt es keinen halben Zustand mehr: Ein Kanal, der
    ausführen darf, sagt das über `provider_write_enabled` **und** die
    Operation. `fake_debug_capabilities` ist die einzige Stelle, die das
    erzeugt — und sie ist von keinem Build erreichbar.

    Der **gesperrte** Fall braucht einen ausdrücklichen Pfad. Ohne ihn fiele
    `app_channel_capabilities()` auf `default_release_path()` zurück und läse
    die echte Freigabedatei des ausführenden Rechners: Der Test wäre dann nur
    so lange grün, wie dort zufällig keine gültige Freigabe liegt, und würde
    während eines Abnahmelaufs unversehens einen **offenen** Kanal prüfen.
    Genau das trat am 2026-08-12 auf dem M2 ein. Ein Pfad, der nicht
    existieren kann, macht die Sperre deterministisch.
    """
    from personaljarvis.contacts.application.app_channel import (
        app_channel_capabilities,
        fake_debug_capabilities,
    )
    if verfuegbar:
        return fake_debug_capabilities()
    return app_channel_capabilities(
        release_path=Path(__file__).resolve().parent
        / "_gibt-es-nicht" / "contacts-write-release.json")


@pytest.fixture
def provider() -> NieGerufenerProvider:
    return NieGerufenerProvider()


@pytest.fixture
def modul(module, provider):
    with module.unit_of_work() as uow:
        SqliteSyncStateRepository(uow).upsert(ContactSyncState(
            provider_account_id=KONTO, container_identifier=CONTAINER,
            key_set_version="v1", mode="delta", cursor_token="TOKEN",
            cursor_taken_at="2026-08-03T09:00:00+00:00"))
    module._capabilities = CAPS
    module._mutation_service = ContactsMutationService(
        module, provider, capabilities=CAPS)
    return module


@pytest.fixture
def dienst(modul) -> AppExecutionService:
    return AppExecutionService(modul, channel_capabilities=Kanal())


def _vorbereitet(modul, *, freigeben: bool = True) -> str:
    service = modul.mutation_service()
    vorgang = service.prepare(CreateContact(
        mutation_id=new_id(), idempotency_key=new_id(),
        provider_account_id=KONTO, workspace_id=WORKSPACE, actor=MENSCH,
        initiation_context=InitiationContext.USER_DIRECT,
        correlation_id=new_id(),
        container_identifier=CONTAINER,
        draft=ContactDraft({"given_name": "Testperson",
                            "family_name": "Alpha"})))
    if freigeben:
        service.grant(vorgang.mutation_id, decision_actor=MENSCH)
    return vorgang.mutation_id


def _bericht(auftrag, **abweichungen) -> ExecutionReportV1:
    basis = {
        "operation_id": auftrag.operation_id,
        "mutation_id": auftrag.mutation_id,
        "operation_type": auftrag.operation_type,
        "outcome": "applied",
        "send_attempted": True,
        "save_request_count": 1,
        "readback_status": "confirmed",
        "provider_identifier_digest": "a" * 64,
        "readback_digest": "b" * 64,
        "provider_completed_at": "2026-08-03T10:00:00+00:00",
    }
    basis.update(abweichungen)
    return ExecutionReportV1(**basis)


def _outbox_zeile(modul, mutation_id: str):
    with modul.unit_of_work() as uow:
        return uow.execute(
            "SELECT o.* FROM personal_external_action_outbox o "
            "JOIN contacts_mutations m ON m.outbox_id = o.outbox_id "
            "WHERE m.mutation_id = ?", (mutation_id,)).fetchone()


def _zustand(modul, mutation_id: str) -> str:
    with modul.unit_of_work() as uow:
        return uow.execute(
            "SELECT state FROM contacts_mutations WHERE mutation_id = ?",
            (mutation_id,)).fetchone()["state"]


# ═══ A · Schema ═════════════════════════════════════════════════════════════
class TestSchema:
    def test_gueltiger_bericht_wird_gelesen(self):
        bericht = parse_execution_report({
            "operation_id": "0" * 36, "mutation_id": "1" * 36,
            "operation_type": "create", "outcome": "applied",
            "send_attempted": True, "save_request_count": 1,
            "readback_status": "confirmed",
        })
        assert bericht.outcome == "applied"
        assert bericht.schema_version == EXECUTION_SCHEMA_VERSION

    def test_unbekanntes_feld_wird_abgewiesen(self):
        with pytest.raises(ExecutionContractError) as exc:
            parse_execution_report({
                "operation_id": "0" * 36, "mutation_id": "1" * 36,
                "operation_type": "create", "outcome": "not_sent",
                "send_attempted": False, "save_request_count": 0,
                "readback_status": "not_attempted",
                "heimlich": "wert",
            })
        assert exc.value.error_class == "schema_mismatch"

    def test_fremde_schemaversion_wird_abgewiesen(self):
        with pytest.raises(ExecutionContractError):
            parse_execution_report({
                "schema_version": 2, "operation_id": "0" * 36,
                "mutation_id": "1" * 36, "operation_type": "create",
                "outcome": "applied", "send_attempted": True,
                "save_request_count": 1, "readback_status": "confirmed",
            })

    def test_groessenlimit_wird_durchgesetzt(self):
        riesig = json.dumps({"operation_id": "0" * MAX_REPORT_BYTES})
        with pytest.raises(ExecutionContractError):
            parse_execution_report(riesig)

    @pytest.mark.parametrize("feld,wert", [
        ("outcome", "vielleicht"),
        ("operation_type", "merge"),
        ("readback_status", "irgendwie"),
        ("error_class", "kaputt"),
    ])
    def test_unbekannte_geschlossene_werte(self, feld, wert):
        roh = {
            "operation_id": "0" * 36, "mutation_id": "1" * 36,
            "operation_type": "create", "outcome": "applied",
            "send_attempted": True, "save_request_count": 1,
            "readback_status": "confirmed",
        }
        roh[feld] = wert
        with pytest.raises(ExecutionContractError):
            parse_execution_report(roh)

    def test_mehr_als_ein_speicherauftrag_ist_vertragsbruch(self):
        with pytest.raises(ExecutionContractError):
            parse_execution_report({
                "operation_id": "0" * 36, "mutation_id": "1" * 36,
                "operation_type": "create", "outcome": "applied",
                "send_attempted": True, "save_request_count": 2,
                "readback_status": "confirmed",
            })

    def test_widerspruch_applied_ohne_sendeversuch(self):
        with pytest.raises(ExecutionContractError):
            parse_execution_report({
                "operation_id": "0" * 36, "mutation_id": "1" * 36,
                "operation_type": "create", "outcome": "applied",
                "send_attempted": False, "save_request_count": 0,
                "readback_status": "confirmed",
            })


# ═══ B · Claim ══════════════════════════════════════════════════════════════
class TestClaim:
    def test_genau_ein_claim_gibt_einen_auftrag_aus(self, modul, dienst, provider):
        mutation_id = _vorbereitet(modul)
        auftrag = dienst.claim(mutation_id)

        assert auftrag.mutation_id == mutation_id
        assert auftrag.operation_type == "create"
        assert len(auftrag.claim_token) == 64
        assert auftrag.payload_digest_matches()
        assert _zustand(modul, mutation_id) == MutationState.EXECUTING
        assert provider.calls == 0

    def test_zweiter_claim_wird_abgewiesen(self, modul, dienst):
        mutation_id = _vorbereitet(modul)
        dienst.claim(mutation_id)
        with pytest.raises((AlreadySettled, MutationNotExecutable)):
            dienst.claim(mutation_id)

    def test_nur_der_digest_wird_persistiert(self, modul, dienst):
        mutation_id = _vorbereitet(modul)
        auftrag = dienst.claim(mutation_id)
        zeile = _outbox_zeile(modul, mutation_id)

        assert zeile["claim_token_digest"] is not None
        assert len(zeile["claim_token_digest"]) == 64
        # Der Rohtoken darf nirgends in der Zeile auftauchen.
        assert auftrag.claim_token not in json.dumps(dict(zeile))

    def test_auftragsausgabe_wird_festgehalten(self, modul, dienst):
        mutation_id = _vorbereitet(modul)
        dienst.claim(mutation_id)
        zeile = _outbox_zeile(modul, mutation_id)
        assert zeile["operation_id"] is not None
        assert zeile["execution_order_issued_at"] is not None
        assert zeile["claim_expires_at"] > zeile["claimed_at"]

    def test_nicht_genehmigte_mutation_bekommt_keinen_auftrag(self, modul, dienst):
        mutation_id = _vorbereitet(modul, freigeben=False)
        with pytest.raises(MutationNotExecutable):
            dienst.claim(mutation_id)

    def test_terminale_mutation_bekommt_keinen_auftrag(self, modul, dienst):
        mutation_id = _vorbereitet(modul, freigeben=False)
        modul.mutation_service().reject(mutation_id, decision_actor=MENSCH)
        with pytest.raises(MutationNotExecutable):
            dienst.claim(mutation_id)

    def test_ohne_kanalfaehigkeit_kein_claim(self, modul):
        mutation_id = _vorbereitet(modul)
        gesperrt = AppExecutionService(modul, channel_capabilities=Kanal(False))
        with pytest.raises(ChannelNotEnabled):
            gesperrt.claim(mutation_id)
        assert _zustand(modul, mutation_id) == MutationState.APPROVED

    def test_freigabe_wird_verbraucht(self, modul, dienst):
        mutation_id = _vorbereitet(modul)
        dienst.claim(mutation_id)
        with modul.unit_of_work() as uow:
            zustand = uow.execute(
                "SELECT a.state FROM personal_approvals a "
                "JOIN contacts_mutations m ON m.approval_id = a.approval_id "
                "WHERE m.mutation_id = ?", (mutation_id,)).fetchone()["state"]
        assert zustand == "consumed"

    def test_send_started_steht_vor_der_antwort(self, modul, dienst):
        """Die Stufe muss den Claim ueberleben — sonst faellt der Beleg weg."""
        mutation_id = _vorbereitet(modul)
        dienst.claim(mutation_id)
        with modul.unit_of_work() as uow:
            stufen = [r["stage"] for r in uow.execute(
                "SELECT stage FROM personal_audit_log WHERE subject_id = ? "
                "ORDER BY sequence", (mutation_id,)).fetchall()]
        assert "execution_claimed" in stufen
        assert "execution_order_issued" in stufen
        assert "provider_send_started" in stufen


# ═══ C · Replay und Absturz ═════════════════════════════════════════════════
class TestReplayUndAbsturz:
    def test_nach_ausgabe_kein_neuer_claim_trotz_verfall(self, modul, dienst):
        mutation_id = _vorbereitet(modul)
        dienst.claim(mutation_id)
        # Verfall simulieren: Der Claim liegt weit in der Vergangenheit —
        # `claimed_at` wandert mit, damit die zeitliche Invariante
        # (`claim_expires_at > claimed_at`) gewahrt bleibt.
        with modul.unit_of_work() as uow:
            uow.execute(
                "UPDATE personal_external_action_outbox "
                "SET claimed_at = ?, claim_expires_at = ?, "
                "execution_order_issued_at = ? WHERE outbox_id = "
                "(SELECT outbox_id FROM contacts_mutations WHERE mutation_id = ?)",
                ("2000-01-01T00:00:00+00:00", "2000-01-01T00:10:00+00:00",
                 "2000-01-01T00:00:00+00:00", mutation_id))
        with pytest.raises((AlreadySettled, MutationNotExecutable)):
            dienst.claim(mutation_id)

    def test_ausbleibender_bericht_fuehrt_ueber_recover_nach_unbekannt(
            self, modul, dienst, provider):
        mutation_id = _vorbereitet(modul)
        dienst.claim(mutation_id)
        # Neustart: der haltende Prozess ist tot, das Rohtoken verloren.
        erholt = modul.mutation_service().recover_interrupted()
        assert mutation_id in erholt
        assert _zustand(modul, mutation_id) == MutationState.OUTCOME_UNKNOWN
        assert provider.calls == 0

    def test_nach_recover_kein_zweiter_claim(self, modul, dienst):
        mutation_id = _vorbereitet(modul)
        dienst.claim(mutation_id)
        modul.mutation_service().recover_interrupted()
        with pytest.raises(MutationNotExecutable):
            dienst.claim(mutation_id)


# ═══ E · Settle ═════════════════════════════════════════════════════════════
class TestSettle:
    def test_erster_bericht_wird_angewandt(self, modul, dienst, provider):
        mutation_id = _vorbereitet(modul)
        auftrag = dienst.claim(mutation_id)
        ergebnis = dienst.settle(mutation_id, _bericht(auftrag),
                                 claim_token=auftrag.claim_token)

        assert ergebnis.state == "provider_applied_pending_reconcile"
        assert ergebnis.idempotent is False
        assert provider.calls == 0

    def test_identischer_zweiter_bericht_ist_noop(self, modul, dienst):
        mutation_id = _vorbereitet(modul)
        auftrag = dienst.claim(mutation_id)
        bericht = _bericht(auftrag)
        erst = dienst.settle(mutation_id, bericht, claim_token=auftrag.claim_token)
        zweit = dienst.settle(mutation_id, bericht, claim_token=auftrag.claim_token)

        assert zweit.idempotent is True
        assert zweit.state == erst.state
        assert zweit.outcome == erst.outcome

    def test_abweichender_zweiter_bericht_wird_abgelehnt(self, modul, dienst):
        mutation_id = _vorbereitet(modul)
        auftrag = dienst.claim(mutation_id)
        dienst.settle(mutation_id, _bericht(auftrag),
                      claim_token=auftrag.claim_token)
        with pytest.raises(SettleConflict):
            dienst.settle(mutation_id,
                          _bericht(auftrag, outcome="outcome_unknown",
                                   readback_status="failed",
                                   error_class="readback_failed"),
                          claim_token=auftrag.claim_token)

    def test_falscher_claim_token_wird_abgelehnt(self, modul, dienst):
        mutation_id = _vorbereitet(modul)
        auftrag = dienst.claim(mutation_id)
        with pytest.raises(SettleConflict):
            dienst.settle(mutation_id, _bericht(auftrag), claim_token="f" * 64)

    def test_fremde_operation_wird_abgelehnt(self, modul, dienst):
        mutation_id = _vorbereitet(modul)
        auftrag = dienst.claim(mutation_id)
        with pytest.raises(SettleConflict):
            dienst.settle(mutation_id, _bericht(auftrag, operation_id="9" * 36),
                          claim_token=auftrag.claim_token)

    def test_not_sent_ohne_versuch_wird_failed_before_send(self, modul, dienst):
        mutation_id = _vorbereitet(modul)
        auftrag = dienst.claim(mutation_id)
        ergebnis = dienst.settle(
            mutation_id,
            _bericht(auftrag, outcome="not_sent", send_attempted=False,
                     save_request_count=0, readback_status="not_attempted",
                     error_class="provider_channel_disabled_before_send",
                     provider_identifier_digest=None, readback_digest=None),
            claim_token=auftrag.claim_token)
        assert ergebnis.state == MutationState.FAILED_BEFORE_SEND

    @pytest.mark.parametrize("abweichung", [
        {"outcome": "outcome_unknown", "readback_status": "failed",
         "error_class": "readback_failed"},
        {"outcome": "outcome_unknown", "readback_status": "not_attempted",
         "error_class": "provider_exception"},
        {"outcome": "applied", "readback_status": "failed"},
    ])
    def test_unklare_ausgaenge_werden_outcome_unknown(self, modul, dienst,
                                                      abweichung):
        mutation_id = _vorbereitet(modul)
        auftrag = dienst.claim(mutation_id)
        ergebnis = dienst.settle(mutation_id, _bericht(auftrag, **abweichung),
                                 claim_token=auftrag.claim_token)
        assert ergebnis.state == MutationState.OUTCOME_UNKNOWN

    def test_settle_erhoeht_den_versuchszaehler_nicht(self, modul, dienst):
        mutation_id = _vorbereitet(modul)
        auftrag = dienst.claim(mutation_id)
        vorher = _outbox_zeile(modul, mutation_id)["attempt_count"]
        dienst.settle(mutation_id, _bericht(auftrag),
                      claim_token=auftrag.claim_token)
        dienst.settle(mutation_id, _bericht(auftrag),
                      claim_token=auftrag.claim_token)
        assert _outbox_zeile(modul, mutation_id)["attempt_count"] == vorher == 1

    def test_settle_schreibt_die_berichtsbindung(self, modul, dienst):
        mutation_id = _vorbereitet(modul)
        auftrag = dienst.claim(mutation_id)
        bericht = _bericht(auftrag)
        dienst.settle(mutation_id, bericht, claim_token=auftrag.claim_token)
        zeile = _outbox_zeile(modul, mutation_id)
        assert zeile["execution_report_digest"] == report_digest(bericht)

    def test_settle_ruft_nie_einen_provider(self, modul, dienst, provider):
        mutation_id = _vorbereitet(modul)
        auftrag = dienst.claim(mutation_id)
        dienst.settle(mutation_id, _bericht(auftrag),
                      claim_token=auftrag.claim_token)
        assert provider.calls == 0


# ═══ I · Sicherheit ═════════════════════════════════════════════════════════
class TestSicherheit:
    def test_kein_rohtoken_im_audit(self, modul, dienst):
        mutation_id = _vorbereitet(modul)
        auftrag = dienst.claim(mutation_id)
        dienst.settle(mutation_id, _bericht(auftrag),
                      claim_token=auftrag.claim_token)
        with modul.unit_of_work() as uow:
            zeilen = uow.execute(
                "SELECT * FROM personal_audit_log").fetchall()
        gesamt = json.dumps([dict(z) for z in zeilen])
        assert auftrag.claim_token not in gesamt

    def test_kein_rohtoken_in_der_datenbank(self, modul, dienst):
        mutation_id = _vorbereitet(modul)
        auftrag = dienst.claim(mutation_id)
        with modul.unit_of_work() as uow:
            tabellen = [r[0] for r in uow.execute(
                "SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
            for tabelle in tabellen:
                inhalt = json.dumps([dict(z) for z in uow.execute(
                    f"SELECT * FROM {tabelle}").fetchall()], default=str)
                assert auftrag.claim_token not in inhalt, tabelle

    def test_auftrag_traegt_beide_digests(self, modul, dienst):
        mutation_id = _vorbereitet(modul)
        auftrag = dienst.claim(mutation_id)
        assert len(auftrag.payload_digest) == 64
        assert len(auftrag.preview_digest) == 64
