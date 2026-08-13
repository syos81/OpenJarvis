"""Kalender-Mutationspipeline B3 P1: prepare, approve, claim, settle.

**Kalenderfrei und sendefrei.** Kein Sidecar, kein EventKit, kein Provider —
die Kernaussage dieser Suite ist gerade, dass das Backend nie selbst sendet.
Alle Datenbanken liegen in `tmp_path`, alle Daten sind synthetisch.

Die Invariante, die jeder Test verteidigt: **ein Claim, ein Auftrag,
höchstens ein Bericht** — und ohne verifiziertes Backup kein Auftrag.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import replace

import pytest

from personaljarvis.base.db.unit_of_work import UnitOfWork
from personaljarvis.base.digest import digest_of
from personaljarvis.base.outbox import ExternalActionOutbox
from personaljarvis.calendar.domain import CanonicalCalendar, CanonicalEvent
from personaljarvis.calendar.mutations.contracts import (
    ATTACHMENT_OBSERVABILITY,
    ELIGIBILITY_FLAG_NAMES,
    IDENTIFIER_CONTRACT,
    assess_restorability,
    canonical_delete_payload,
    control_binding_digest_of,
    semantic_state_digest_of,
    validate_control_observation,
    ExecutionReportV1,
    InvalidMutationFields,
    eligibility_digest_of,
    fingerprint_of,
    preimage_fingerprint_of,
    restore_preimage_digest_of,
    restore_preimage_of,
    validate_changes,
    validate_eligibility_probe,
    validate_fields,
)
from personaljarvis.calendar.mutations.service import (
    AlreadySettled,
    BackupMissing,
    CalendarMutationService,
    CalendarNotFound,
    CalendarNotWritable,
    DeleteNotEligible,
    DeleteNotRestorable,
    EventNotFound,
    PositiveControlMissing,
    origin_continuity_of,
    MutationNotExecutable,
    SettleConflict,
    backup_probe_from_path,
)
from personaljarvis.calendar.repositories import (
    CalendarRepository,
    EventRepository,
)

from .conftest import PROVIDER_ACCOUNT, WORKSPACE

KALENDER = "cal-1"

FELDER = {
    "title": "Zahnarzt",
    "starts_at_utc": "2026-08-12T09:00:00Z",
    "ends_at_utc": "2026-08-12T10:00:00Z",
    "is_all_day": False,
    "location": None,
    "notes": None,
    "time_zone": "Europe/Berlin",
}

READBACK = {**FELDER, "provider_calendar_id": KALENDER}

EVENT_ID = "EK-EVENT-1"

#: Der Vorzustand des Bestandstermins als Preimage-Feldsatz — die eine
#: kanonische Feldmenge des Fingerprints (sieben Felder plus Identität).
PREIMAGE = {**FELDER, "provider_calendar_id": KALENDER,
            "event_identifier": EVENT_ID}

#: Paritätspin: derselbe synthetische Zustand ist in calendar_write.rs als
#: Konstante gepinnt. Weicht eine Seite ab, rechnen Python und Rust
#: verschiedene Fingerprints — und genau das soll dieser Pin verraten.
PREIMAGE_FINGERPRINT_PIN = (
    "a6394e8dd0a8804bb41c6ab1ca6b7840b568c1bd6901f3f21db8a5622cb198b1")


def _kalender_anlegen(factory, provider_id=KALENDER, *, writable=True) -> str:
    with UnitOfWork(factory) as uow:
        kalender_id, _ = CalendarRepository(uow).upsert_seen(
            CanonicalCalendar(
                id="", workspace_id=WORKSPACE,
                provider_account_id=PROVIDER_ACCOUNT,
                provider_calendar_id=provider_id, display_name="Privat",
                calendar_type="calDAV", is_writable=writable),
            seen_at="2026-08-09T00:00:00Z")
    return kalender_id


def _termin_anlegen(factory, kalender_id, provider_event_id=EVENT_ID,
                    **abweichungen) -> None:
    """Seedet einen Bestandstermin (events + event_external_ids)."""
    felder = {**FELDER, **abweichungen}
    with UnitOfWork(factory) as uow:
        EventRepository(uow).upsert_seen(
            CanonicalEvent(
                id="", calendar_id=kalender_id,
                provider_event_id=provider_event_id,
                provider_calendar_id=KALENDER,
                starts_at_utc=felder["starts_at_utc"],
                ends_at_utc=felder["ends_at_utc"],
                title=felder["title"], notes=felder["notes"],
                location=felder["location"], time_zone=felder["time_zone"],
                is_all_day=felder["is_all_day"]),
            PROVIDER_ACCOUNT, "2026-08-09T00:00:00Z")


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

    def test_validate_fields_ende_gleich_beginn_faellt(self):
        # Direkt an der autoritativen Regel (ends > starts), ohne UI.
        with pytest.raises(InvalidMutationFields):
            validate_fields({**FELDER, "ends_at_utc": FELDER["starts_at_utc"]})

    def test_validate_fields_ende_vor_beginn_faellt(self):
        with pytest.raises(InvalidMutationFields):
            validate_fields({**FELDER, "ends_at_utc": "2026-08-12T08:00:00Z"})

    def test_nicht_schreibbarer_kalender_faellt(self, dienst, factory):
        _kalender_anlegen(factory, "cal-ro", writable=False)
        with pytest.raises(CalendarNotWritable):
            dienst.prepare_create("cal-ro", dict(FELDER))

    def test_unbekannter_kalender_faellt(self, dienst):
        with pytest.raises(CalendarNotFound):
            dienst.prepare_create("cal-fremd", dict(FELDER))

    def test_delete_ohne_probe_faellt(self, dienst):
        # P3 schaltet `delete` frei — aber NIE ohne gültige, am nativen
        # Event erhobene Eligibility-Probe. Eine leere Probe ist ein
        # Schemafehler, keine stille Freigabe.
        with pytest.raises(InvalidMutationFields):
            dienst.prepare_delete(KALENDER, EVENT_ID, {})


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


@pytest.fixture
def update_dienst(factory) -> CalendarMutationService:
    kalender_id = _kalender_anlegen(factory)
    _termin_anlegen(factory, kalender_id)
    return CalendarMutationService(factory, backup_probe=lambda: True)


def _update_bericht(auftrag, readback, **abweichungen) -> ExecutionReportV1:
    basis = ExecutionReportV1(
        operation_id=auftrag.operation_id,
        mutation_id=auftrag.mutation_id,
        operation_type="update",
        outcome="applied",
        send_attempted=True,
        save_request_count=1,
        readback_status="confirmed",
        readback_event=readback,
        provider_identifier=EVENT_ID,
        fingerprint_checked=True,
        fingerprint_matched=True,
        provider_completed_at="2026-08-09T12:00:00Z",
    )
    return replace(basis, **abweichungen)


# ── Update: Delta-Semantik (B3 P2) ──────────────────────────────────────────
class TestPrepareUpdate:
    def test_titel_delta_traegt_nur_den_titel(self, update_dienst, factory):
        vorgang = update_dienst.prepare_update(
            KALENDER, EVENT_ID, {"title": "Kieferorthopäde"})
        zeile = _mutation_row(factory, vorgang.mutation_id)
        assert zeile["state"] == "prepared"
        assert zeile["command"] == "update"
        payload = json.loads(zeile["payload_json"])
        # DELTA, kein Full Replace: genau das eine Feld reist.
        assert payload["command"] == "update"
        assert payload["changes"] == {"title": "Kieferorthopäde"}
        assert payload["provider_target"] == {
            "provider_calendar_id": KALENDER, "event_identifier": EVENT_ID}
        # Der Vorzustand ist gebunden und festgehalten.
        assert payload["expected_fingerprint"] \
            == preimage_fingerprint_of(PREIMAGE)
        assert zeile["base_fingerprint"] == payload["expected_fingerprint"]
        assert json.loads(zeile["preimage_json"]) == PREIMAGE
        assert zeile["event_identifier"] == EVENT_ID
        # Die Vorschau zeigt alt → neu je Feld plus Identität.
        assert vorgang.preview["command"] == "update"
        assert vorgang.preview["calendar_display_name"] == "Privat"
        assert vorgang.preview["title"] == "Zahnarzt"
        assert vorgang.preview["changes"] == {
            "title": {"from": "Zahnarzt", "to": "Kieferorthopäde"}}

    def test_leeres_delta_faellt(self, update_dienst):
        with pytest.raises(InvalidMutationFields):
            update_dienst.prepare_update(KALENDER, EVENT_ID, {})

    def test_unbekanntes_delta_feld_faellt(self, update_dienst):
        with pytest.raises(InvalidMutationFields):
            update_dienst.prepare_update(
                KALENDER, EVENT_ID, {"farbe": "rot"})
        with pytest.raises(InvalidMutationFields):
            update_dienst.prepare_update(
                KALENDER, EVENT_ID,
                {"title": "ok", "url": "https://x.invalid"})

    def test_null_ist_fachlicher_wert_nicht_platzhalter(self, update_dienst):
        # `{"title": null}` heisst „Titel löschen" — gültig. Nicht-ändern
        # heisst weglassen, nie null senden.
        vorgang = update_dienst.prepare_update(
            KALENDER, EVENT_ID, {"title": None})
        assert vorgang.preview["changes"] == {
            "title": {"from": "Zahnarzt", "to": None}}

    def test_unbekannter_termin_faellt(self, update_dienst):
        with pytest.raises(EventNotFound):
            update_dienst.prepare_update(
                KALENDER, "EK-FREMD", {"title": "x"})

    def test_leerer_event_identifier_faellt(self, update_dienst):
        with pytest.raises(InvalidMutationFields):
            update_dienst.prepare_update(KALENDER, "", {"title": "x"})

    def test_nicht_schreibbarer_kalender_faellt(self, factory):
        kalender_id = _kalender_anlegen(factory, writable=False)
        _termin_anlegen(factory, kalender_id)
        dienst = CalendarMutationService(factory, backup_probe=lambda: True)
        with pytest.raises(CalendarNotWritable):
            dienst.prepare_update(KALENDER, EVENT_ID, {"title": "x"})

    def test_zeitverschiebung_mit_dauererhalt(self, update_dienst):
        # Offline-Zeitverschiebung: starts+ends aus dem Dauererhalt reisen
        # als Delta; die Zone bleibt UNBERÜHRT (kein time_zone im Delta).
        vorgang = update_dienst.prepare_update(KALENDER, EVENT_ID, {
            "starts_at_utc": "2026-08-12T11:00:00Z",
            "ends_at_utc": "2026-08-12T12:00:00Z"})
        aenderungen = vorgang.preview["changes"]
        assert set(aenderungen) == {"starts_at_utc", "ends_at_utc"}
        assert "time_zone" not in aenderungen

    def test_bewusste_ende_aenderung_ist_moeglich(self, update_dienst):
        vorgang = update_dienst.prepare_update(
            KALENDER, EVENT_ID, {"ends_at_utc": "2026-08-12T11:30:00Z"})
        assert vorgang.preview["changes"] == {"ends_at_utc": {
            "from": "2026-08-12T10:00:00Z", "to": "2026-08-12T11:30:00Z"}}

    def test_zusammengefuehrtes_ende_vor_beginn_faellt(self, update_dienst):
        # Nur das Ende geändert, aber vor den BESTEHENDEN Beginn gelegt:
        # der zusammengeführte Zustand ist ungültig.
        with pytest.raises(InvalidMutationFields):
            update_dienst.prepare_update(
                KALENDER, EVENT_ID,
                {"ends_at_utc": "2026-08-12T08:00:00Z"})


class TestPreimageFingerprint:
    def test_pin_stimmt_mit_der_rust_seite_ueberein(self):
        # Paritätspin: dieselben Werte stehen in calendar_write.rs.
        assert preimage_fingerprint_of(PREIMAGE) == PREIMAGE_FINGERPRINT_PIN

    def test_fehlend_wird_nie_still_null(self):
        ohne = {k: v for k, v in PREIMAGE.items() if k != "location"}
        with pytest.raises(InvalidMutationFields):
            preimage_fingerprint_of(ohne)
        # Der Gegenbeweis: MIT explizitem null ist es ein gültiger Zustand.
        assert preimage_fingerprint_of({**ohne, "location": None}) \
            == PREIMAGE_FINGERPRINT_PIN

    def test_unbekanntes_feld_faellt(self):
        with pytest.raises(InvalidMutationFields):
            preimage_fingerprint_of({**PREIMAGE, "last_seen_at": "x"})

    def test_jedes_feld_aendert_den_fingerprint(self):
        basis = preimage_fingerprint_of(PREIMAGE)
        for feld, wert in [("title", "Anders"), ("location", "Raum 2"),
                           ("notes", "n"), ("is_all_day", True),
                           ("time_zone", None),
                           ("starts_at_utc", "2026-08-12T09:30:00Z"),
                           ("provider_calendar_id", "cal-2"),
                           ("event_identifier", "EK-EVENT-2")]:
            assert preimage_fingerprint_of({**PREIMAGE, feld: wert}) \
                != basis, feld

    def test_validate_changes_normalisiert_nur_das_delta(self):
        assert validate_changes({"title": "Neu"}) == {"title": "Neu"}
        with pytest.raises(InvalidMutationFields):
            validate_changes({"time_zone": "Mars/Olympus_Mons"})
        with pytest.raises(InvalidMutationFields):
            validate_changes({"is_all_day": "ja"})
        with pytest.raises(InvalidMutationFields):
            validate_changes("kein objekt")


class TestUpdateAusfuehrung:
    def _vorbereitet(self, dienst, changes) -> str:
        vorgang = dienst.prepare_update(KALENDER, EVENT_ID, changes)
        dienst.approve(vorgang.mutation_id, decision_actor="lukas")
        return vorgang.mutation_id

    def test_claim_traegt_fingerprint_und_zielkennung(self, update_dienst):
        mutation_id = self._vorbereitet(update_dienst, {"title": "Neu"})
        auftrag = update_dienst.claim(mutation_id)
        assert auftrag.operation_type == "update"
        assert auftrag.payload_digest_matches()
        assert auftrag.expected_fingerprint \
            == preimage_fingerprint_of(PREIMAGE)
        assert auftrag.provider_target == {
            "provider_calendar_id": KALENDER, "event_identifier": EVENT_ID}

    def test_titel_update_erhaelt_alle_anderen_felder(self, update_dienst,
                                                      factory):
        # Der Titel ändert sich; start/ende/zone/ganztags/Kalender bleiben —
        # belegt über den GELESENEN Zustand im Spiegel, nicht behauptet.
        mutation_id = self._vorbereitet(update_dienst,
                                        {"title": "Kieferorthopäde"})
        auftrag = update_dienst.claim(mutation_id)
        readback = {**FELDER, "title": "Kieferorthopäde",
                    "provider_calendar_id": KALENDER}
        ergebnis = update_dienst.settle(
            mutation_id, _update_bericht(auftrag, readback),
            claim_token=auftrag.claim_token)
        assert ergebnis.state == "succeeded"

        zeile = _mutation_row(factory, mutation_id)
        # Rücknahmeinformation eines update: das Delta rückwärts — die
        # B3-editierbaren Felder des Vorzustands.
        assert json.loads(zeile["rollback_hint_json"]) == {
            "undo": "update", "preimage": FELDER}
        assert zeile["event_identifier"] == EVENT_ID

        with UnitOfWork(factory) as uow:
            termin = uow.execute(
                "SELECT e.title, e.starts_at_utc, e.ends_at_utc, "
                "e.is_all_day, e.time_zone, e.location, e.notes "
                "FROM events e JOIN event_external_ids x ON x.event_id = e.id "
                "WHERE x.provider_event_id = ?", (EVENT_ID,)).fetchone()
        assert termin["title"] == "Kieferorthopäde"
        assert termin["starts_at_utc"] == FELDER["starts_at_utc"]
        assert termin["ends_at_utc"] == FELDER["ends_at_utc"]
        assert termin["is_all_day"] == 0
        assert termin["time_zone"] == "Europe/Berlin"
        assert termin["location"] is None
        # Es bleibt DERSELBE Termin — kein zweiter entstand.
        with UnitOfWork(factory) as uow:
            anzahl = uow.execute(
                "SELECT COUNT(*) AS n FROM events WHERE is_tombstone = 0"
            ).fetchone()
        assert anzahl["n"] == 1

    def test_revision_conflict_bleibt_failed_before_send(self, update_dienst,
                                                         factory):
        # Der native Pfad hat den frischen Zustand gelesen, der Fingerprint
        # wich ab: beweisbar nichts gesendet, Klasse revision_conflict.
        mutation_id = self._vorbereitet(update_dienst, {"title": "Neu"})
        auftrag = update_dienst.claim(mutation_id)
        bericht = _update_bericht(
            auftrag, None, outcome="not_sent", send_attempted=False,
            save_request_count=0, readback_status="not_checked",
            provider_identifier=None, fingerprint_checked=True,
            fingerprint_matched=False, error_class="revision_conflict",
            provider_completed_at=None)
        ergebnis = update_dienst.settle(mutation_id, bericht,
                                        claim_token=auftrag.claim_token)
        assert ergebnis.state == "failed_before_send"
        zeile = _mutation_row(factory, mutation_id)
        assert zeile["last_error_code"] == "revision_conflict"
        # Der Bestandstermin blieb unangetastet.
        with UnitOfWork(factory) as uow:
            termin = uow.execute(
                "SELECT e.title FROM events e "
                "JOIN event_external_ids x ON x.event_id = e.id "
                "WHERE x.provider_event_id = ?", (EVENT_ID,)).fetchone()
        assert termin["title"] == "Zahnarzt"

    def test_manipulierter_payload_nach_freigabe_faellt(self, update_dienst,
                                                        factory):
        mutation_id = self._vorbereitet(update_dienst, {"title": "Neu"})
        with UnitOfWork(factory) as uow:
            uow.execute(
                "UPDATE calendar_mutations SET payload_digest = ? "
                "WHERE mutation_id = ?", ("0" * 64, mutation_id))
        with pytest.raises(MutationNotExecutable):
            update_dienst.claim(mutation_id)

    def test_floating_bleibt_floating(self, factory):
        # Ein schwebender Termin (time_zone null) bekommt einen neuen Titel —
        # die Schwebe bleibt, kein Layer erfindet eine Zone.
        kalender_id = _kalender_anlegen(factory)
        _termin_anlegen(factory, kalender_id, time_zone=None)
        dienst = CalendarMutationService(factory, backup_probe=lambda: True)
        vorgang = dienst.prepare_update(KALENDER, EVENT_ID, {"title": "Neu"})
        assert json.loads(
            _mutation_row(factory, vorgang.mutation_id)["preimage_json"]
        )["time_zone"] is None
        dienst.approve(vorgang.mutation_id, decision_actor="lukas")
        auftrag = dienst.claim(vorgang.mutation_id)
        readback = {**FELDER, "title": "Neu", "time_zone": None,
                    "provider_calendar_id": KALENDER}
        ergebnis = dienst.settle(
            vorgang.mutation_id, _update_bericht(auftrag, readback),
            claim_token=auftrag.claim_token)
        assert ergebnis.state == "succeeded"
        with UnitOfWork(factory) as uow:
            termin = uow.execute(
                "SELECT e.time_zone, e.title FROM events e "
                "JOIN event_external_ids x ON x.event_id = e.id "
                "WHERE x.provider_event_id = ?", (EVENT_ID,)).fetchone()
        assert termin["title"] == "Neu"
        assert termin["time_zone"] is None


class TestZeitzone:
    """B3-P1-Zeitzonenkorrektur: `time_zone` ist Pflichtfeld (nullable) des
    Schreibvertrags. Fehlend ist ein Schemafehler, `null` die ausdrücklich
    angeforderte schwebende Semantik — kein Layer erfindet eine Zone."""

    def test_verankerter_create_traegt_die_zone_durch(self, dienst, factory):
        # Python-Hälfte der Kette: Payload → Order → Settle-Readback →
        # Spiegel-Zeile. (Order → Rust-Felder → Fake-Save → Readback belegt
        # das Rust-Testpaar in calendar_write.rs.)
        mutation_id = _vorbereitet(dienst)
        auftrag = dienst.claim(mutation_id)
        assert auftrag.canonical_payload["fields"]["time_zone"] \
            == "Europe/Berlin"
        dienst.settle(mutation_id, _bericht(auftrag),
                      claim_token=auftrag.claim_token)
        with UnitOfWork(factory) as uow:
            termin = uow.execute(
                "SELECT e.time_zone FROM events e "
                "JOIN event_external_ids x ON x.event_id = e.id "
                "WHERE x.provider_event_id = ?", ("EK-EVENT-1",)).fetchone()
        assert termin is not None
        assert termin["time_zone"] == "Europe/Berlin"

    def test_fingerprint_bindet_ausschliesslich_die_zone(self):
        # Dieselbe Uhrzeit, NUR die Zone geändert ⇒ anderer Zustand.
        anders = {**FELDER, "time_zone": "America/New_York"}
        assert fingerprint_of(FELDER, KALENDER) \
            != fingerprint_of(anders, KALENDER)

    def test_bewusst_schwebender_create_bleibt_null(self, dienst, factory):
        # `null` reist als `null` bis in den Spiegel — kein Layer ersetzt
        # die schwebende Semantik still durch die Systemzone.
        schwebend = {**FELDER, "time_zone": None}
        vorgang = dienst.prepare_create(KALENDER, dict(schwebend))
        assert vorgang.preview["time_zone"] is None
        dienst.approve(vorgang.mutation_id, decision_actor="lukas")
        auftrag = dienst.claim(vorgang.mutation_id)
        assert auftrag.canonical_payload["fields"]["time_zone"] is None
        bericht = _bericht(
            auftrag, mutation_id=vorgang.mutation_id,
            readback_event={**schwebend, "provider_calendar_id": KALENDER})
        ergebnis = dienst.settle(vorgang.mutation_id, bericht,
                                 claim_token=auftrag.claim_token)
        assert ergebnis.state == "succeeded"
        with UnitOfWork(factory) as uow:
            termin = uow.execute(
                "SELECT e.time_zone FROM events e "
                "JOIN event_external_ids x ON x.event_id = e.id "
                "WHERE x.provider_event_id = ?", ("EK-EVENT-1",)).fetchone()
        assert termin is not None
        assert termin["time_zone"] is None

    def test_fehlender_time_zone_schluessel_faellt(self, dienst):
        # Weglassen ist NIE Defaulting: dieselbe Fehlerklasse wie jeder
        # andere Schemafehler.
        ohne = {k: v for k, v in FELDER.items() if k != "time_zone"}
        with pytest.raises(InvalidMutationFields):
            dienst.prepare_create(KALENDER, ohne)

    def test_ungueltiger_iana_name_faellt(self, dienst):
        with pytest.raises(InvalidMutationFields):
            dienst.prepare_create(
                KALENDER, {**FELDER, "time_zone": "Mars/Olympus_Mons"})
        with pytest.raises(InvalidMutationFields):
            dienst.prepare_create(KALENDER, {**FELDER, "time_zone": ""})

    def test_zeitzonen_waechter_ueber_alle_schichten(self):
        """Cross-Layer-Wächter (Bauart des Vokabular-Wächters): `time_zone`
        muss in JEDEM Träger der Kette mechanisch vorkommen — Quelltext-Scan,
        ein leerer Scan bewiese nichts (R10)."""
        import inspect
        import re
        from pathlib import Path

        from personaljarvis.calendar.mutations import contracts

        wurzel = Path(__file__).resolve().parents[3]
        rust = (wurzel / "frontend" / "src-tauri" / "src"
                / "calendar_write.rs").read_text(encoding="utf-8")
        objc = (wurzel / "frontend" / "src-tauri" / "objc"
                / "JCCalendarWrite.m").read_text(encoding="utf-8")
        formular = (wurzel / "frontend" / "src" / "personal" / "calendar"
                    / "TerminFormular.tsx").read_text(encoding="utf-8")

        def struktur(name: str, quelle: str) -> str:
            treffer = re.search(rf"struct {name} \{{([\s\S]*?)\n\}}", quelle)
            return treffer.group(1) if treffer else ""

        # R10: erst belegen, dass die Scans auf Material laufen.
        for material in (struktur("EventFelder", rust),
                         struktur("ReadbackEvent", rust), objc, formular,
                         inspect.getsource(contracts.fingerprint_of)):
            assert material, "leerer Scan bewiese nichts (R10)"

        stellen = {
            "contracts.FIELD_NAMES":
                "time_zone" in contracts.FIELD_NAMES,
            "contracts.fingerprint_of":
                "time_zone" in inspect.getsource(contracts.fingerprint_of),
            "rust.EventFelder":
                "time_zone" in struktur("EventFelder", rust),
            "rust.ReadbackEvent":
                "time_zone" in struktur("ReadbackEvent", rust),
            "objc.timeZoneWithName": "timeZoneWithName" in objc,
            "ui.systemZeitzone": "systemZeitzone()" in formular,
        }
        fehlend = sorted(name for name, da in stellen.items() if not da)
        assert fehlend == [], (
            f"time_zone fehlt in diesen Trägern: {fehlend}")


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


# ── Delete: drei getrennte Nachweise (B3 P3) ────────────────────────────────

#: Eine gültige, am nativen Event erhobene Probe OHNE belegte unsupported
#: Eigenschaft — wortgleich mit `unauffaellige_probe()` in calendar_write.rs.
PROBE = {
    "schema_version": 1,
    "event_identifier": EVENT_ID,
    "provider_calendar_id": KALENDER,
    "eligible": True,
    "unsupported_feature_flags": [],
    "counts": {"alarms": 0, "attendees": 0, "recurrence_rules": 0},
}

#: Eine produktiv gelesene positive Kontrolle desselben Kalenders — ab B3 P3
#: VORBEDINGUNG des Deletes, nicht nur Nachpruefung.
KONTROLLE = {
    "read_operation_success": True,
    "control_present": True,
    "control_event_identifier": "EK-KONTROLLE-1",
    "control_provider_calendar_id": KALENDER,
    "observed_at_utc": "2026-08-10T17:16:22Z",
}


def _freigabe_anlegen(uow, payload_digest: str = "d",
                      preview_digest: str = "p") -> str:
    """Eine verbrauchsfaehige Freigabe fuer direkt gesetzte Testzeilen."""
    from personaljarvis.base.approvals import owner_decision, ApprovalStore
    approval_id = str(uuid.uuid4())
    ApprovalStore(uow).request(
        approval_id=approval_id, module="calendar",
        subject_type="calendar.mutation", subject_id=approval_id,
        risk_class="R1", initiation_context="user_direct", actor="lukas",
        correlation_id=approval_id, payload_digest=payload_digest,
        preview_digest=preview_digest,
        ttl_seconds=900)
    ApprovalStore(uow).grant(approval_id, decision=owner_decision("lukas"))
    return approval_id


#: Paritätspins: DIESELBEN Konstanten stehen in calendar_write.rs
#: (`ELIGIBILITY_DIGEST_PIN` / `RESTORE_PREIMAGE_DIGEST_PIN`). Weicht eine
#: Seite ab, rechnen Python und Rust verschiedene Kanonisierungen — und die
#: Approval-Bindung des Deletes wäre wertlos.
ELIGIBILITY_DIGEST_PIN = (
    "d5b92ebce7a158d4213ffe8b946c4f5f93c91917fd37756478d5b4cad4261f33")
RESTORE_PREIMAGE_DIGEST_PIN = (
    "a33587d4e03bba7fd50481a7b386440e229dc9762cb65b022739e6210978ab09")


@pytest.fixture
def delete_dienst(factory) -> CalendarMutationService:
    kalender_id = _kalender_anlegen(factory)
    _termin_anlegen(factory, kalender_id)
    return CalendarMutationService(factory, backup_probe=lambda: True)


def _delete_bericht(auftrag, **abweichungen) -> ExecutionReportV1:
    basis = ExecutionReportV1(
        operation_id=auftrag.operation_id,
        mutation_id=auftrag.mutation_id,
        operation_type="delete",
        outcome="applied",
        send_attempted=True,
        save_request_count=1,
        # Der Erfolgsbeleg eines Deletes ist die BESTÄTIGTE Abwesenheit.
        readback_status="absent_confirmed",
        readback_event=None,
        provider_identifier=EVENT_ID,
        fingerprint_checked=True,
        fingerprint_matched=True,
        provider_completed_at="2026-08-09T12:00:00Z",
    )
    return replace(basis, **abweichungen)


class TestPrepareDelete:
    """B3 P3 FINALER Vertrag: DELETE ist nur zulaessig, wenn die vollstaendige
    aktuelle Wiederherstellbarkeit POSITIV belegt ist. Auf dem real
    verwendeten SDK ist die Abwesenheit von Anhaengen nicht beobachtbar —
    damit blockiert der Pfad, und zwar auch fuer einen von Jarvis selbst
    erzeugten Termin. Unbekannt ist blockiert, nicht 'wird schon'."""

    def test_delete_blockiert_weil_wiederherstellbarkeit_unbelegt(
            self, delete_dienst, factory):
        with pytest.raises(DeleteNotRestorable) as exc:
            delete_dienst.prepare_delete(KALENDER, EVENT_ID, dict(PROBE),
                                         dict(KONTROLLE))
        gruende = str(exc.value)
        assert "attachments_absent_unproven" in gruende
        # Strukturell: KEINE Mutation, KEINE Freigabe, KEIN Outbox-Eintrag.
        with UnitOfWork(factory) as uow:
            for tabelle, wo in (
                ("calendar_mutations", ""),
                ("personal_approvals",
                 " WHERE subject_type = 'calendar.mutation'"),
                ("personal_external_action_outbox",
                 " WHERE module = 'calendar'"),
            ):
                n = uow.execute(
                    f"SELECT COUNT(*) AS n FROM {tabelle}{wo}").fetchone()["n"]
                assert n == 0, tabelle

    def test_jarvis_herkunft_ueberstimmt_die_attachment_luecke_nicht(self):
        # Auch bei bewiesener Herkunft und eligible Probe bleibt die
        # Wiederherstellbarkeit unbelegt, solange Anhaenge unbeobachtbar sind.
        urteil = assess_restorability(
            origin_continuity="proven", eligibility_probe=dict(PROBE),
            restore_preimage_present=True)
        assert urteil["restorability_proven"] is False
        assert urteil["attachments_absent"] == "unproven"
        assert "attachments_absent_unproven" in urteil["blocking_reasons"]

    def test_unsupported_eigenschaft_blockiert_zusaetzlich(self):
        blockiert = {**PROBE, "eligible": False,
                     "unsupported_feature_flags": ["recurrence_rules"],
                     "counts": {"alarms": 0, "attendees": 0,
                                "recurrence_rules": 1}}
        urteil = assess_restorability(
            origin_continuity="proven", eligibility_probe=blockiert,
            restore_preimage_present=True)
        assert urteil["restorability_proven"] is False
        assert "unsupported_property_present" in urteil["blocking_reasons"]

    def test_fehlende_restore_preimage_blockiert(self):
        urteil = assess_restorability(
            origin_continuity="proven", eligibility_probe=dict(PROBE),
            restore_preimage_present=False)
        assert "restore_preimage_missing" in urteil["blocking_reasons"]

    def test_unsupported_probe_blockiert_vor_jeder_mutation(
            self, delete_dienst, factory):
        probe = {**PROBE, "eligible": False,
                 "unsupported_feature_flags": ["recurrence_rules"],
                 "counts": {"alarms": 0, "attendees": 0,
                            "recurrence_rules": 1}}
        with pytest.raises(DeleteNotEligible):
            delete_dienst.prepare_delete(KALENDER, EVENT_ID, probe,
                                         dict(KONTROLLE))
        with UnitOfWork(factory) as uow:
            n = uow.execute(
                "SELECT COUNT(*) AS n FROM calendar_mutations").fetchone()["n"]
        assert n == 0

    def test_probe_eines_anderen_ziels_faellt(self, delete_dienst):
        with pytest.raises(InvalidMutationFields):
            delete_dienst.prepare_delete(
                KALENDER, EVENT_ID,
                {**PROBE, "event_identifier": "EK-ANDERES"}, dict(KONTROLLE))


class TestPositiveKontrolleVorbedingung:
    """Entscheidung 10/11: die positive Kontrolle ist VORBEDINGUNG des
    Deletes. Ohne sie gibt es keine Vorschau und keine Freigabe — und es
    wird NIE ein Termin nur als Kontrollobjekt erzeugt."""

    def test_a_kontrolle_vorhanden_passiert_die_kontrollpruefung(
            self, delete_dienst):
        # Die Kontrollpruefung laeuft VOR der Herkunfts-/Restorability-
        # Pruefung: mit gueltiger Kontrolle faellt der Vorgang erst an der
        # Wiederherstellbarkeit, nicht mehr an der Kontrolle.
        with pytest.raises(DeleteNotRestorable):
            delete_dienst.prepare_delete(KALENDER, EVENT_ID, dict(PROBE),
                                         dict(KONTROLLE))

    def test_b_fehlende_kontrolle_verhindert_vorschau(self, delete_dienst,
                                                       factory):
        with pytest.raises(PositiveControlMissing):
            delete_dienst.prepare_delete(KALENDER, EVENT_ID, dict(PROBE),
                                         None)
        with UnitOfWork(factory) as uow:
            n = uow.execute(
                "SELECT COUNT(*) AS n FROM personal_approvals "
                "WHERE subject_type = 'calendar.mutation'").fetchone()["n"]
        assert n == 0

    def test_e_kontrolle_in_fremdem_kalender_blockiert(self, delete_dienst):
        with pytest.raises(PositiveControlMissing):
            delete_dienst.prepare_delete(
                KALENDER, EVENT_ID, dict(PROBE),
                {**KONTROLLE, "control_provider_calendar_id": "cal-fremd"})

    def test_kontrolle_darf_nicht_das_ziel_selbst_sein(self, delete_dienst):
        with pytest.raises(PositiveControlMissing):
            delete_dienst.prepare_delete(
                KALENDER, EVENT_ID, dict(PROBE),
                {**KONTROLLE, "control_event_identifier": EVENT_ID})

    def test_f_unvollstaendige_kontrollbeobachtung_faellt(self):
        for defekt in (
            "kein objekt",
            {},
            {k: v for k, v in KONTROLLE.items() if k != "control_present"},
            {**KONTROLLE, "read_operation_success": False},
            {**KONTROLLE, "control_present": False},
            {**KONTROLLE, "heimlich": 1},
            {**KONTROLLE, "control_event_identifier": ""},
            {**KONTROLLE, "observed_at_utc": "2026-08-10 17:16:22"},
        ):
            with pytest.raises(InvalidMutationFields):
                validate_control_observation(defekt)

    def test_c_die_bindung_gilt_genau_einem_kontrollpaar(self):
        # Eine andere Kontrolle ergibt einen anderen Bindungsdigest — eine
        # nachtraeglich gewaehlte Kontrolle passt nie zur Freigabe.
        andere = {**KONTROLLE,
                  "control_event_identifier": "EK-KONTROLLE-2"}
        assert control_binding_digest_of(KONTROLLE) \
            != control_binding_digest_of(andere)


class TestOriginContinuity:
    """Entscheidung 5/6/7: Herkunft folgt NIE allein aus der Eventkennung.
    Zwei getrennte Bindungen muessen halten — Identitaet UND identitaetsfreier
    Zustand."""

    def _linie(self, factory, **abweichungen):
        """Seedet eine gesettelte CREATE-Linie mit Zustandsdigest."""
        werte = {"command": "create", "state": "succeeded",
                 "event_identifier": EVENT_ID,
                 "target_provider_calendar_id": KALENDER,
                 "semantic_state_digest": semantic_state_digest_of(FELDER)}
        werte.update(abweichungen)
        with UnitOfWork(factory) as uow:
            uow.execute(
                "INSERT INTO calendar_mutations (mutation_id, command, state, "
                "payload_json, payload_digest, preview_json, preview_digest, "
                "approval_id, outbox_id, target_provider_calendar_id, "
                "event_identifier, semantic_state_digest, created_at, "
                "attempt_count) VALUES (?,?,?,'{}','d','{}','p',?,?,?,?,?,?,0)",
                (str(uuid.uuid4()), werte["command"], werte["state"],
                 _freigabe_anlegen(uow), str(uuid.uuid4()),
                 werte["target_provider_calendar_id"],
                 werte["event_identifier"], werte["semantic_state_digest"],
                 "2026-08-09T12:00:00Z"))

    def _pruefe(self, factory, zustand=None):
        with UnitOfWork(factory) as uow:
            return origin_continuity_of(uow, KALENDER, EVENT_ID,
                                        zustand or dict(FELDER))

    def test_1_vollstaendige_linie_ist_proven(self, factory):
        _kalender_anlegen(factory)
        self._linie(factory)
        assert self._pruefe(factory)["origin_continuity"] == "proven"

    def test_6_ohne_create_settle_blockiert(self, factory):
        _kalender_anlegen(factory)
        self._linie(factory, command="update")
        ergebnis = self._pruefe(factory)
        assert ergebnis["origin_continuity"] == "unproven"
        assert "no_successful_create_settle" in ergebnis["blocking_reasons"]

    def test_5_kalenderidentitaet_geaendert_blockiert(self, factory):
        _kalender_anlegen(factory)
        self._linie(factory, target_provider_calendar_id="cal-anders")
        ergebnis = self._pruefe(factory)
        assert "calendar_identity_changed" in ergebnis["blocking_reasons"]

    def test_7_fehlende_semantische_bindung_blockiert(self, factory):
        # Historische Zeilen ohne Zustandsdigest: NULL heisst nicht
        # 'unveraendert', sondern 'nicht rekonstruierbar'.
        _kalender_anlegen(factory)
        self._linie(factory, semantic_state_digest=None)
        ergebnis = self._pruefe(factory)
        assert "semantic_state_binding_missing" in ergebnis["blocking_reasons"]

    @pytest.mark.parametrize("feld,wert", [
        ("title", "Extern umbenannt"),
        ("starts_at_utc", "2026-08-12T11:00:00Z"),
        ("time_zone", "America/New_York"),
    ])
    def test_3_4_8_externe_zustandsaenderung_blockiert(self, factory, feld,
                                                       wert):
        _kalender_anlegen(factory)
        self._linie(factory)
        ergebnis = self._pruefe(factory, {**FELDER, feld: wert})
        assert ergebnis["origin_continuity"] == "unproven"
        assert "semantic_state_digest_mismatch" in ergebnis["blocking_reasons"]

    def test_9_serialisierungsreihenfolge_aendert_den_digest_nicht(self):
        umgekehrt = dict(reversed(list(FELDER.items())))
        assert semantic_state_digest_of(umgekehrt) \
            == semantic_state_digest_of(FELDER)

    def test_semantischer_digest_ist_identitaetsfrei(self):
        # Weder Eventkennung noch Kalender duerfen ihn beeinflussen —
        # sonst koennte eine Identitaetsaenderung eine Zustandsaenderung
        # verdecken.
        mit_identitaet = {**FELDER, "event_identifier": "EK-X",
                          "provider_calendar_id": "cal-x"}
        assert semantic_state_digest_of(mit_identitaet) \
            == semantic_state_digest_of(FELDER)
        # Und er ist NICHT der readback_digest (der bindet den Kalender mit).
        assert semantic_state_digest_of(FELDER) \
            != fingerprint_of(FELDER, KALENDER)


class TestDeleteSettle:
    """Der Settle-Vertrag des Deletes bleibt gueltig und geprueft, obwohl der
    produktive Vorbereitungspfad derzeit blockiert: die Zeile wird direkt
    gesetzt, damit die Auswertung isoliert pruefbar bleibt."""

    def _vorbereitet(self, dienst, factory) -> str:
        mutation_id = str(uuid.uuid4())
        payload = canonical_delete_payload(
            KALENDER, EVENT_ID, preimage_fingerprint_of(PREIMAGE),
            eligibility_digest_of(PROBE), restore_preimage_digest_of(PREIMAGE),
            control_binding_digest_of(KONTROLLE))
        with UnitOfWork(factory) as uow:
            approval_id = _freigabe_anlegen(uow, digest_of(payload), "p")
            outbox = ExternalActionOutbox(uow).enqueue(
                module="calendar", operation="delete",
                subject_type="calendar.mutation", subject_id=mutation_id,
                approval_id=approval_id, idempotency_key=mutation_id,
                payload_digest=digest_of(payload))
            uow.execute(
                "INSERT INTO calendar_mutations (mutation_id, command, state, "
                "payload_json, payload_digest, preview_json, preview_digest, "
                "approval_id, outbox_id, target_provider_calendar_id, "
                "event_identifier, base_fingerprint, preimage_json, "
                "created_at, attempt_count) "
                "VALUES (?,'delete','approved',?,?,'{}','p',?,?,?,?,?,?,?,0)",
                (mutation_id,
                 json.dumps(payload, sort_keys=True, separators=(",", ":")),
                 digest_of(payload), approval_id, outbox.outbox_id, KALENDER,
                 EVENT_ID, preimage_fingerprint_of(PREIMAGE),
                 json.dumps(PREIMAGE, sort_keys=True, separators=(",", ":")),
                 "2026-08-10T16:36:26Z"))
        return mutation_id

    def test_absent_confirmed_wird_succeeded_mit_tombstone(self, delete_dienst,
                                                            factory):
        mutation_id = self._vorbereitet(delete_dienst, factory)
        auftrag = delete_dienst.claim(mutation_id)
        ergebnis = delete_dienst.settle(mutation_id, _delete_bericht(auftrag),
                                        claim_token=auftrag.claim_token)
        assert ergebnis.state == "succeeded"
        with UnitOfWork(factory) as uow:
            termin = uow.execute(
                "SELECT e.is_tombstone, e.deleted_at FROM events e "
                "JOIN event_external_ids x ON x.event_id = e.id "
                "WHERE x.provider_event_id = ?", (EVENT_ID,)).fetchone()
        assert termin["is_tombstone"] == 1
        assert termin["deleted_at"] is not None

    def test_leere_zielsuche_allein_ist_kein_beweis(self, delete_dienst,
                                                     factory):
        mutation_id = self._vorbereitet(delete_dienst, factory)
        auftrag = delete_dienst.claim(mutation_id)
        bericht = _delete_bericht(auftrag, readback_status="unavailable",
                                  outcome="unknown",
                                  error_class="readback_failed")
        ergebnis = delete_dienst.settle(mutation_id, bericht,
                                        claim_token=auftrag.claim_token)
        assert ergebnis.state == "outcome_unknown"
        with UnitOfWork(factory) as uow:
            termin = uow.execute(
                "SELECT e.is_tombstone FROM events e "
                "JOIN event_external_ids x ON x.event_id = e.id "
                "WHERE x.provider_event_id = ?", (EVENT_ID,)).fetchone()
        assert termin["is_tombstone"] == 0

    def test_unsupported_field_bleibt_failed_before_send(self, delete_dienst,
                                                          factory):
        mutation_id = self._vorbereitet(delete_dienst, factory)
        auftrag = delete_dienst.claim(mutation_id)
        bericht = _delete_bericht(
            auftrag, outcome="not_sent", send_attempted=False,
            save_request_count=0, readback_status="not_checked",
            provider_identifier=None, error_class="unsupported_field",
            provider_completed_at=None)
        ergebnis = delete_dienst.settle(mutation_id, bericht,
                                        claim_token=auftrag.claim_token)
        assert ergebnis.state == "failed_before_send"
        with UnitOfWork(factory) as uow:
            termin = uow.execute(
                "SELECT e.is_tombstone FROM events e "
                "JOIN event_external_ids x ON x.event_id = e.id "
                "WHERE x.provider_event_id = ?", (EVENT_ID,)).fetchone()
        assert termin["is_tombstone"] == 0

class TestEmissionsWaechter:
    """P3-Livebefund (Stufe probe_unparseable): Clang boxt nackte
    Vergleichsausdrücke in @() als 0/1-ZAHLEN, nicht als JSON-true/false —
    vier Probe-Wahrheitswerte fielen deshalb fail-closed am Rust-Vertrag.
    Dieser Wächter hält die Reparaturregel mechanisch fest: im Schreib-Shim
    wird NIE ein Vergleichs- oder Logikausdruck direkt geboxt; Wahrheits-
    werte laufen über BOOL-typisierte Variablen oder BOOL-Properties."""

    def test_kein_vergleichsausdruck_wird_direkt_geboxt(self):
        import re
        from pathlib import Path

        wurzel = Path(__file__).resolve().parents[3]
        quelle = (wurzel / "frontend" / "src-tauri" / "objc"
                  / "JCCalendarWrite.m").read_text(encoding="utf-8")
        # Kommentare ausblenden: der Wächter prüft Code, nicht Prosa.
        quelle = re.sub(r"//[^\n]*", "", quelle)
        # R10: erst belegen, dass der Scan auf Material läuft — die
        # Boxing-Stellen existieren.
        geboxt = re.findall(r"@\(([^)]*)\)", quelle)
        assert len(geboxt) >= 10, "leerer Scan bewiese nichts (R10)"
        verstoesse = sorted({
            ausdruck.strip() for ausdruck in geboxt
            if re.search(r"!=|==|<|>|&&|\|\|", ausdruck)
        })
        assert verstoesse == [], (
            "Vergleichs-/Logikausdruck direkt geboxt (emittiert 0/1 statt "
            f"true/false): {verstoesse}")


class TestEligibilityVertrag:
    def test_pins_stimmen_mit_der_rust_seite_ueberein(self):
        assert eligibility_digest_of(PROBE) == ELIGIBILITY_DIGEST_PIN
        assert restore_preimage_digest_of(PREIMAGE) \
            == RESTORE_PREIMAGE_DIGEST_PIN

    def test_probe_wird_fail_closed_geprueft(self):
        for defekt in (
            "kein objekt",
            {},
            {**PROBE, "heimlich": True},
            {k: v for k, v in PROBE.items() if k != "counts"},
            {**PROBE, "schema_version": 2},
            {**PROBE, "unsupported_feature_flags": ["farbe"]},
            {**PROBE, "unsupported_feature_flags": ["url", "alarms"]},  # unsortiert
            {**PROBE, "counts": {"alarms": 0}},
            {**PROBE, "counts": {**PROBE["counts"], "alarms": -1}},
            {**PROBE, "counts": {**PROBE["counts"], "alarms": True}},
            {**PROBE, "eligible": False},  # Widerspruch zu leeren Flags
            {**PROBE, "eligible": True,
             "unsupported_feature_flags": ["alarms"]},  # Widerspruch
            {**PROBE, "event_identifier": ""},
        ):
            with pytest.raises(InvalidMutationFields):
                validate_eligibility_probe(defekt)

    def test_jedes_flag_ist_im_geschlossenen_vokabular_pruefbar(self):
        # Jede Flagge der geschlossenen Menge ist einzeln bindbar — und
        # macht die Probe nicht-eligible.
        for flag in ELIGIBILITY_FLAG_NAMES:
            probe = {**PROBE, "eligible": False,
                     "unsupported_feature_flags": [flag]}
            geprueft = validate_eligibility_probe(probe)
            assert geprueft["eligible"] is False
            assert geprueft["unsupported_feature_flags"] == [flag]

    def test_flags_aendern_den_digest(self):
        blocked = {**PROBE, "eligible": False,
                   "unsupported_feature_flags": ["alarms"],
                   "counts": {"alarms": 1, "attendees": 0,
                              "recurrence_rules": 0}}
        assert eligibility_digest_of(blocked) != eligibility_digest_of(PROBE)


class TestRestoreOffline:
    """Auftrag D: der Restore-Pfad wird OFFLINE belegt — aus der Preimage
    kann der bestehende Create-Pfad einen fachlich äquivalenten Termin
    erzeugen. Kein Live-Restore; NICHT behauptet wird eine gleiche interne
    EventKit-ID."""

    def _restore_ueber_create(self, factory, preimage):
        """Führt das Restore-Artefakt durch den ECHTEN Create-Pfad und
        liefert den vorbereiteten kanonischen Payload."""
        dienst = CalendarMutationService(factory, backup_probe=lambda: True)
        restore = restore_preimage_of(preimage)
        vorgang = dienst.prepare_create(
            restore["provider_calendar_id"], dict(restore["fields"]))
        zeile = _mutation_row(factory, vorgang.mutation_id)
        return json.loads(zeile["payload_json"])

    def test_einfacher_zeitgebundener_termin(self, factory):
        # D1: Preimage → Restore → fachlich gleiche B3-Felder.
        _kalender_anlegen(factory)
        payload = self._restore_ueber_create(factory, PREIMAGE)
        assert payload["command"] == "create"
        assert payload["fields"] == {name: PREIMAGE[name]
                                     for name in sorted(payload["fields"])}
        assert payload["provider_target"]["provider_calendar_id"] == KALENDER

    def test_floating_bleibt_null(self, factory):
        # D2: null bleibt null — kein Layer erfindet eine Zone.
        _kalender_anlegen(factory)
        preimage = {**PREIMAGE, "time_zone": None}
        payload = self._restore_ueber_create(factory, preimage)
        assert payload["fields"]["time_zone"] is None

    def test_zonenverankerter_termin_behaelt_die_zone(self, factory):
        # D3: eine abweichende Zone bleibt exakt erhalten.
        _kalender_anlegen(factory)
        preimage = {**PREIMAGE, "time_zone": "America/New_York"}
        payload = self._restore_ueber_create(factory, preimage)
        assert payload["fields"]["time_zone"] == "America/New_York"

    def test_ganztaegiger_termin_behaelt_die_semantik(self, factory):
        # D4: bestehende Ganztagssemantik (schwebend, Mitternachtsinstants,
        # exklusives Ende) bleibt.
        _kalender_anlegen(factory)
        preimage = {**PREIMAGE, "is_all_day": True, "time_zone": None,
                    "starts_at_utc": "2026-08-12T00:00:00Z",
                    "ends_at_utc": "2026-08-13T00:00:00Z"}
        payload = self._restore_ueber_create(factory, preimage)
        assert payload["fields"]["is_all_day"] is True
        assert payload["fields"]["time_zone"] is None
        assert payload["fields"]["starts_at_utc"] == "2026-08-12T00:00:00Z"
        assert payload["fields"]["ends_at_utc"] == "2026-08-13T00:00:00Z"

    def test_unsupported_event_ist_vor_der_mutation_blocked(self,
                                                            delete_dienst):
        # D5: reicht die Restore-Fähigkeit nicht (belegte unsupported
        # Eigenschaft), ist der Delete BEREITS VOR der Mutation blocked —
        # nicht erst am nativen Pfad.
        probe = {**PROBE, "eligible": False,
                 "unsupported_feature_flags": ["attendees", "organizer"],
                 "counts": {"alarms": 0, "attendees": 3,
                            "recurrence_rules": 0}}
        with pytest.raises(DeleteNotEligible):
            delete_dienst.prepare_delete(KALENDER, EVENT_ID, probe)

    def test_defektes_preimage_ist_nicht_wiederherstellbar(self):
        # Ein Vorzustand, den der Create-Vertrag nicht trüge (Ende ≤
        # Beginn), ist kein Restore-Artefakt — und damit nicht löschbar.
        defekt = {**PREIMAGE, "ends_at_utc": PREIMAGE["starts_at_utc"]}
        with pytest.raises(InvalidMutationFields):
            restore_preimage_of(defekt)
