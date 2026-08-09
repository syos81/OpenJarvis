"""Kalender-Mutationspipeline B3 P1: prepare, approve, claim, settle.

**Kalenderfrei und sendefrei.** Kein Sidecar, kein EventKit, kein Provider —
die Kernaussage dieser Suite ist gerade, dass das Backend nie selbst sendet.
Alle Datenbanken liegen in `tmp_path`, alle Daten sind synthetisch.

Die Invariante, die jeder Test verteidigt: **ein Claim, ein Auftrag,
höchstens ein Bericht** — und ohne verifiziertes Backup kein Auftrag.
"""

from __future__ import annotations

import json
from dataclasses import replace

import pytest

from personaljarvis.base.db.unit_of_work import UnitOfWork
from personaljarvis.calendar.domain import CanonicalCalendar
from personaljarvis.calendar.mutations.contracts import (
    ExecutionReportV1,
    InvalidMutationFields,
    fingerprint_of,
)
from personaljarvis.calendar.mutations.service import (
    AlreadySettled,
    BackupMissing,
    CalendarMutationService,
    CalendarNotFound,
    CalendarNotWritable,
    MutationNotExecutable,
    PositionNotEnabled,
    SettleConflict,
    backup_probe_from_path,
)
from personaljarvis.calendar.repositories import CalendarRepository

from .conftest import PROVIDER_ACCOUNT, WORKSPACE

KALENDER = "cal-1"

FELDER = {
    "title": "Zahnarzt",
    "starts_at_utc": "2026-08-12T09:00:00Z",
    "ends_at_utc": "2026-08-12T10:00:00Z",
    "is_all_day": False,
    "location": None,
    "notes": None,
}

READBACK = {**FELDER, "provider_calendar_id": KALENDER}


def _kalender_anlegen(factory, provider_id=KALENDER, *, writable=True) -> None:
    with UnitOfWork(factory) as uow:
        CalendarRepository(uow).upsert_seen(
            CanonicalCalendar(
                id="", workspace_id=WORKSPACE,
                provider_account_id=PROVIDER_ACCOUNT,
                provider_calendar_id=provider_id, display_name="Privat",
                calendar_type="calDAV", is_writable=writable),
            seen_at="2026-08-09T00:00:00Z")


@pytest.fixture
def dienst(factory) -> CalendarMutationService:
    _kalender_anlegen(factory)
    return CalendarMutationService(factory, backup_probe=lambda: True)


def _vorbereitet(dienst, *, freigeben=True) -> str:
    vorgang = dienst.prepare_create(KALENDER, dict(FELDER))
    if freigeben:
        dienst.approve(vorgang.mutation_id, decision_actor="lukas")
    return vorgang.mutation_id


def _bericht(auftrag, **abweichungen) -> ExecutionReportV1:
    basis = ExecutionReportV1(
        operation_id=auftrag.operation_id,
        mutation_id=auftrag.mutation_id,
        operation_type="create",
        outcome="applied",
        send_attempted=True,
        save_request_count=1,
        readback_status="confirmed",
        readback_event=dict(READBACK),
        provider_identifier="EK-EVENT-1",
        fingerprint_checked=False,
        provider_completed_at="2026-08-09T12:00:00Z",
    )
    return replace(basis, **abweichungen)


def _mutation_row(factory, mutation_id):
    with UnitOfWork(factory) as uow:
        return uow.execute(
            "SELECT * FROM calendar_mutations WHERE mutation_id = ?",
            (mutation_id,)).fetchone()


def _outbox_row(factory, outbox_id):
    with UnitOfWork(factory) as uow:
        return uow.execute(
            "SELECT * FROM personal_external_action_outbox WHERE outbox_id = ?",
            (outbox_id,)).fetchone()


# ── Vorbereiten ─────────────────────────────────────────────────────────────
class TestPrepare:
    def test_gueltiges_create_ist_prepared(self, dienst, factory):
        vorgang = dienst.prepare_create(KALENDER, dict(FELDER))
        zeile = _mutation_row(factory, vorgang.mutation_id)
        assert zeile["state"] == "prepared"
        assert zeile["command"] == "create"
        # Der Digest deckt exakt die gespeicherte kanonische Nutzlast.
        payload = json.loads(zeile["payload_json"])
        assert payload["fields"]["location"] is None  # null bleibt enthalten
        assert payload["expected_fingerprint"] is None
        assert vorgang.preview["calendar_display_name"] == "Privat"

    def test_unbekanntes_feld_faellt(self, dienst):
        with pytest.raises(InvalidMutationFields):
            dienst.prepare_create(KALENDER, {**FELDER, "farbe": "rot"})

    def test_falscher_typ_faellt(self, dienst):
        with pytest.raises(InvalidMutationFields):
            dienst.prepare_create(KALENDER, {**FELDER, "title": 5})
        with pytest.raises(InvalidMutationFields):
            dienst.prepare_create(KALENDER, {**FELDER, "is_all_day": "ja"})

    def test_zeitformat_ohne_z_faellt(self, dienst):
        with pytest.raises(InvalidMutationFields):
            dienst.prepare_create(KALENDER, {
                **FELDER, "starts_at_utc": "2026-08-12T09:00:00+00:00"})

    def test_ende_vor_beginn_faellt(self, dienst):
        with pytest.raises(InvalidMutationFields):
            dienst.prepare_create(KALENDER, {
                **FELDER, "ends_at_utc": "2026-08-12T09:00:00Z"})

    def test_nicht_schreibbarer_kalender_faellt(self, dienst, factory):
        _kalender_anlegen(factory, "cal-ro", writable=False)
        with pytest.raises(CalendarNotWritable):
            dienst.prepare_create("cal-ro", dict(FELDER))

    def test_unbekannter_kalender_faellt(self, dienst):
        with pytest.raises(CalendarNotFound):
            dienst.prepare_create("cal-fremd", dict(FELDER))

    def test_update_und_delete_sind_nicht_freigeschaltet(self, dienst):
        with pytest.raises(PositionNotEnabled):
            dienst.prepare_update("EK-EVENT-1", dict(FELDER))
        with pytest.raises(PositionNotEnabled):
            dienst.prepare_delete("EK-EVENT-1")


# ── Claim ───────────────────────────────────────────────────────────────────
class TestClaim:
    def test_ohne_freigabe_kein_claim(self, dienst):
        mutation_id = _vorbereitet(dienst, freigeben=False)
        with pytest.raises(MutationNotExecutable):
            dienst.claim(mutation_id)

    def test_claim_konsumiert_freigabe_genau_einmal(self, dienst, factory):
        mutation_id = _vorbereitet(dienst)
        auftrag = dienst.claim(mutation_id)
        assert auftrag.payload_digest_matches()
        assert auftrag.expected_fingerprint is None
        assert auftrag.provider_target["provider_calendar_id"] == KALENDER
        assert _mutation_row(factory, mutation_id)["state"] == "executing"
        # Der zweite Claim bekommt nie erneut einen Rohtoken.
        with pytest.raises(AlreadySettled):
            dienst.claim(mutation_id)

    def test_manipulierter_payload_digest_faellt(self, dienst, factory):
        mutation_id = _vorbereitet(dienst)
        with UnitOfWork(factory) as uow:
            uow.execute(
                "UPDATE calendar_mutations SET payload_digest = ? "
                "WHERE mutation_id = ?", ("0" * 64, mutation_id))
        with pytest.raises(MutationNotExecutable):
            dienst.claim(mutation_id)

    def test_ohne_backup_nachweis_kein_claim(self, factory):
        _kalender_anlegen(factory, "cal-b")
        gesperrt = CalendarMutationService(factory, backup_probe=lambda: False)
        vorgang = gesperrt.prepare_create("cal-b", dict(FELDER))
        gesperrt.approve(vorgang.mutation_id, decision_actor="lukas")
        with pytest.raises(BackupMissing):
            gesperrt.claim(vorgang.mutation_id)
        # Fail-closed: der Vorgang bleibt unberuehrt beanspruchbar fuer
        # spaeter — es wurde nichts konsumiert.
        zeile = _mutation_row(factory, vorgang.mutation_id)
        assert zeile["state"] == "approved"

    def test_backup_probe_liest_fail_closed(self, tmp_path):
        pfad = tmp_path / "latest.json"
        probe = backup_probe_from_path(pfad)
        assert probe() is False                       # fehlend
        pfad.write_text("kein json", encoding="utf-8")
        assert probe() is False                       # unlesbar
        pfad.write_text(json.dumps({"verified": False}), encoding="utf-8")
        assert probe() is False                       # nicht verifiziert
        pfad.write_text(json.dumps({
            "created_at_utc": "2026-08-09T00:00:00Z", "sha256": "0" * 64,
            "entry_count": 12, "source_calendar_digest": "1" * 64,
            "verified": True}), encoding="utf-8")
        assert probe() is True


# ── Cancel ──────────────────────────────────────────────────────────────────
class TestCancel:
    @pytest.mark.parametrize("freigeben", [False, True])
    def test_cancel_mutiert_nicht(self, dienst, factory, freigeben):
        mutation_id = _vorbereitet(dienst, freigeben=freigeben)
        dienst.cancel(mutation_id, decision_actor="lukas")
        zeile = _mutation_row(factory, mutation_id)
        assert zeile["state"] == "cancelled"
        eintrag = _outbox_row(factory, zeile["outbox_id"])
        # Die Outbox wurde nie beansprucht und ist endgueltig raus.
        assert eintrag["state"] == "abandoned"
        assert eintrag["claimed_at"] is None
        assert eintrag["attempt_count"] == 0
        with pytest.raises(MutationNotExecutable):
            dienst.claim(mutation_id)


# ── Settle ──────────────────────────────────────────────────────────────────
class TestSettle:
    def test_applied_confirmed_wird_succeeded_mit_spiegel(self, dienst, factory):
        mutation_id = _vorbereitet(dienst)
        auftrag = dienst.claim(mutation_id)
        ergebnis = dienst.settle(mutation_id, _bericht(auftrag),
                                 claim_token=auftrag.claim_token)
        assert ergebnis.state == "succeeded"
        assert ergebnis.outcome == "succeeded"

        zeile = _mutation_row(factory, mutation_id)
        assert zeile["event_identifier"] == "EK-EVENT-1"
        assert json.loads(zeile["rollback_hint_json"]) == {
            "undo": "delete", "event_identifier": "EK-EVENT-1"}
        assert zeile["readback_digest"] == fingerprint_of(FELDER, KALENDER)
        assert zeile["completed_at"] is not None

        # Der lokale Spiegel traegt genau den **gelesenen** Zustand.
        with UnitOfWork(factory) as uow:
            termin = uow.execute(
                "SELECT e.title, e.starts_at_utc, e.ends_at_utc, e.is_all_day "
                "FROM events e JOIN event_external_ids x ON x.event_id = e.id "
                "WHERE x.provider_event_id = ?", ("EK-EVENT-1",)).fetchone()
        assert termin is not None
        assert termin["title"] == "Zahnarzt"
        assert termin["starts_at_utc"] == FELDER["starts_at_utc"]

    def test_settle_ist_inhaltsbasiert_idempotent(self, dienst):
        mutation_id = _vorbereitet(dienst)
        auftrag = dienst.claim(mutation_id)
        bericht = _bericht(auftrag)
        dienst.settle(mutation_id, bericht, claim_token=auftrag.claim_token)
        wieder = dienst.settle(mutation_id, bericht,
                               claim_token=auftrag.claim_token)
        assert wieder.idempotent is True
        assert wieder.state == "succeeded"

    def test_abweichender_bericht_ist_konflikt(self, dienst):
        mutation_id = _vorbereitet(dienst)
        auftrag = dienst.claim(mutation_id)
        dienst.settle(mutation_id, _bericht(auftrag),
                      claim_token=auftrag.claim_token)
        anders = _bericht(auftrag,
                          provider_completed_at="2026-08-09T13:00:00Z")
        with pytest.raises(SettleConflict):
            dienst.settle(mutation_id, anders,
                          claim_token=auftrag.claim_token)

    def test_falsches_claim_token_ist_konflikt(self, dienst):
        mutation_id = _vorbereitet(dienst)
        auftrag = dienst.claim(mutation_id)
        with pytest.raises(SettleConflict):
            dienst.settle(mutation_id, _bericht(auftrag),
                          claim_token="f" * 64)

    def test_not_sent_ohne_versuch_ist_failed_before_send(self, dienst, factory):
        mutation_id = _vorbereitet(dienst)
        auftrag = dienst.claim(mutation_id)
        bericht = _bericht(
            auftrag, outcome="not_sent", send_attempted=False,
            save_request_count=0, readback_status="not_checked",
            readback_event=None, provider_identifier=None,
            error_class="invalid_payload")
        ergebnis = dienst.settle(mutation_id, bericht,
                                 claim_token=auftrag.claim_token)
        assert ergebnis.state == "failed_before_send"
        assert ergebnis.outcome == "failed"
        zeile = _mutation_row(factory, mutation_id)
        assert zeile["state"] == "failed_before_send"
        assert zeile["last_error_code"] == "invalid_payload"

    def test_unknown_bleibt_outcome_unknown(self, dienst, factory):
        mutation_id = _vorbereitet(dienst)
        auftrag = dienst.claim(mutation_id)
        bericht = _bericht(
            auftrag, outcome="unknown", readback_status="unavailable",
            readback_event=None, provider_identifier=None,
            error_class="provider_exception")
        ergebnis = dienst.settle(mutation_id, bericht,
                                 claim_token=auftrag.claim_token)
        assert ergebnis.state == "outcome_unknown"
        assert _mutation_row(factory, mutation_id)["state"] == "outcome_unknown"

    @pytest.mark.parametrize("leer", [None, {}])
    def test_r10_leerer_readback_wird_nie_succeeded(self, dienst, factory, leer):
        """R10: Ein `applied` ohne brauchbaren Read-back beweist keinen
        Endzustand — der Vorgang bleibt in der Zwischenlage."""
        mutation_id = _vorbereitet(dienst)
        auftrag = dienst.claim(mutation_id)
        bericht = _bericht(auftrag, readback_event=leer)
        ergebnis = dienst.settle(mutation_id, bericht,
                                 claim_token=auftrag.claim_token)
        assert ergebnis.state == "provider_applied_pending_reconcile"
        zeile = _mutation_row(factory, mutation_id)
        assert zeile["state"] == "provider_applied_pending_reconcile"
        assert zeile["readback_digest"] is None
        # Erfunden wird nichts: kein Termin im Spiegel.
        with UnitOfWork(factory) as uow:
            anzahl = uow.execute(
                "SELECT COUNT(*) AS n FROM event_external_ids "
                "WHERE provider_event_id = ?", ("EK-EVENT-1",)).fetchone()
        assert anzahl["n"] == 0


class TestVertragsEinheit:
    """B3-Livebefund vom 2026-08-09: Vorschau und Freigabe liefen auf zwei
    unabhängig definierten Vertragshälften — der Adapter vergab fünf
    Fehlerklassen, die der Server abwies. Dieses Paar hält die eine Wahrheit
    mechanisch fest."""

    def test_jede_adapterklasse_ist_im_kanonischen_vokabular(self):
        # Schärfung: jede error_class, die der native Adapter vergeben kann,
        # muss der Settle-Parser akzeptieren. Die Klassen werden aus der
        # Rust-Quelle gelesen, nicht behauptet.
        import re
        from pathlib import Path

        from personaljarvis.calendar.mutations.contracts import ERROR_CLASSES

        wurzel = Path(__file__).resolve().parents[3]
        quelle = (wurzel / "frontend" / "src-tauri" / "src"
                  / "calendar_write.rs").read_text(encoding="utf-8")
        vergeben = set()
        for muster in (r'not_sent\(&order,\s*"([a-z_]+)"',
                       r'ungebunden\("([a-z_]+)"\)',
                       r'unknown_mit\(&order,\s*"([a-z_]+)"',
                       r'error_class:\s*Some\("([a-z_]+)"'):
            vergeben.update(re.findall(muster, quelle))
        assert vergeben, "leerer Scan bewiese nichts (R10)"
        fremd = sorted(vergeben - set(ERROR_CLASSES))
        assert fremd == [], (
            f"Adapterklassen ausserhalb des Vokabulars: {fremd}")

    def test_eine_unbekannte_klasse_bleibt_abgewiesen(self):
        # Gegentest: das Vokabular bleibt geschlossen — eine erfundene
        # Klasse wird weiterhin zurückgewiesen, nie still übernommen.
        import pytest

        from personaljarvis.calendar.mutations.contracts import (
            CalendarExecutionContractError,
            parse_execution_report,
        )

        bericht = {
            "schema_version": 1, "operation_id": "o", "mutation_id": "m",
            "operation_type": "create", "outcome": "not_sent",
            "send_attempted": False, "save_request_count": 0,
            "readback_status": "not_checked", "readback_event": None,
            "provider_identifier": None, "fingerprint_checked": False,
            "fingerprint_matched": None, "error_class": "voellig_erfunden",
            "error_digest": None, "provider_completed_at": None,
        }
        with pytest.raises(CalendarExecutionContractError):
            parse_execution_report(bericht)

    def test_auftragszeiten_tragen_das_vertragsformat(self):
        # Die eine Zeitform: Z-Suffix, Sekundenpraezision — beidseitig.
        from personaljarvis.calendar.mutations.service import (
            _plus_sekunden,
            utc_now,
        )
        jetzt = utc_now()
        assert jetzt.endswith("Z") and len(jetzt) == 20
        spaeter = _plus_sekunden(jetzt, 600)
        assert spaeter.endswith("Z") and len(spaeter) == 20
