"""Härtungs-Regressionen aus dem Gate-C-Audit — kontaktfrei.

Jeder Test hier fixiert einen im Audit **empirisch reproduzierten** Befund:

* B1: `failed_before_send` war ein Zombie — nicht terminal, nicht ausführbar,
  und sein Outbox-Eintrag stand dauerhaft als fällig.
* B2: Ein Prozessabbruch zwischen Beanspruchung und Ergebnis ließ die Mutation
  unlösbar in `executing` hängen (verwaister Claim ohne Erholungspfad).
* Parallelität: Idempotenz und Claiming müssen von den Datenbank-Constraints
  getragen werden, nicht von Python-Prüfungen — mit echten Threads belegt.
* Digest-Semantik: semantisch verschiedene Patches dürfen nie denselben
  Freigabe-Digest erhalten.

Kein Sidecar, kein Store, kein TCC — ausschließlich Fake-Bridge und
temporäre Datenbanken.
"""

from __future__ import annotations

import threading
import uuid
from pathlib import Path

import pytest

from personaljarvis.base.approvals import owner_decision_for_tests

from personaljarvis.base.audit import AuditStage, AuditTrail
from personaljarvis.base.outbox import ExternalActionOutbox, OutboxState
from personaljarvis.contacts.application import (
    ContactDraft,
    ContactsMutationService,
    ContactsReconcileService,
    CreateContact,
    MutationState,
    ProviderOutcome,
    ProviderResponse,
    ReconcileObservation,
)
from personaljarvis.contacts.application.errors import AlreadySettled
from personaljarvis.contacts.application.models import MutationPayload
from personaljarvis.contacts.domain.enums import InitiationContext
from personaljarvis.contacts.domain.models import ContactSyncState
from personaljarvis.contacts.lifecycle import ContactsModule
from personaljarvis.contacts.repositories.sqlite import SqliteSyncStateRepository

from .conftest import WORKSPACE, new_id

KONTO = "apple-system"
CONTAINER = "container-1"
MENSCH = "lukas"


class Provider:
    def __init__(self, outcome=ProviderOutcome.SUCCEEDED, *, error_code=None,
                 raises=None):
        self.outcome, self.error_code, self.raises = outcome, error_code, raises
        self.calls = 0

    def apply(self, payload, **kw):
        self.calls += 1
        if self.raises is not None:
            raise self.raises
        return ProviderResponse(self.outcome, error_code=self.error_code)


def _cmd(**kw) -> CreateContact:
    defaults = dict(
        mutation_id=new_id(), idempotency_key=new_id(),
        provider_account_id=KONTO, workspace_id=WORKSPACE, actor=MENSCH,
        initiation_context=InitiationContext.USER_DIRECT,
        correlation_id=new_id(), container_identifier=CONTAINER,
        draft=ContactDraft({"given_name": "Fixture"}))
    defaults.update(kw)
    return CreateContact(**defaults)


def _container(module):
    with module.unit_of_work() as uow:
        SqliteSyncStateRepository(uow).upsert(ContactSyncState(
            provider_account_id=KONTO, container_identifier=CONTAINER,
            key_set_version="v1", mode="delta"))


# ═══ B1: failed_before_send ist terminal und schließt die Outbox ════════════
def test_failed_before_send_ist_terminal_und_nie_mehr_faellig(module):
    _container(module)
    service = ContactsMutationService(
        module, Provider(ProviderOutcome.CONFLICT, error_code="conflict"))
    vorgang = service.prepare(_cmd())
    service.grant(vorgang.mutation_id, decision=owner_decision_for_tests(MENSCH))
    ergebnis = service.execute(vorgang.mutation_id)
    assert ergebnis.state == MutationState.FAILED_BEFORE_SEND
    assert MutationState.FAILED_BEFORE_SEND in MutationState.TERMINAL
    with module.unit_of_work() as uow:
        eintrag = ExternalActionOutbox(uow).require(vorgang.outbox_id)
        faellig = ExternalActionOutbox(uow).list_due(module="contacts")
        zeile = uow.execute(
            "SELECT completed_at FROM contacts_mutations WHERE mutation_id=?",
            (vorgang.mutation_id,)).fetchone()
    assert eintrag.state == OutboxState.ABANDONED
    assert all(e.outbox_id != vorgang.outbox_id for e in faellig)
    assert zeile["completed_at"] is not None


def test_zweites_execute_nach_failed_before_send_ist_already_settled(module):
    _container(module)
    provider = Provider(ProviderOutcome.REJECTED_BEFORE_SEND, error_code="nein")
    service = ContactsMutationService(module, provider)
    vorgang = service.prepare(_cmd())
    service.grant(vorgang.mutation_id, decision=owner_decision_for_tests(MENSCH))
    service.execute(vorgang.mutation_id)
    with pytest.raises(AlreadySettled):
        service.execute(vorgang.mutation_id)
    assert provider.calls == 1


def test_precheck_fehlschlag_schliesst_outbox_ebenfalls(module):
    """Auch der Weg über die Vorprüfung (Container fehlt) endet terminal."""
    _container(module)
    service = ContactsMutationService(module, Provider())
    vorgang = service.prepare(_cmd(container_identifier="verschwunden"))
    service.grant(vorgang.mutation_id, decision=owner_decision_for_tests(MENSCH))
    ergebnis = service.execute(vorgang.mutation_id)
    assert ergebnis.state == MutationState.FAILED_BEFORE_SEND
    with module.unit_of_work() as uow:
        assert ExternalActionOutbox(uow).require(
            vorgang.outbox_id).state == OutboxState.ABANDONED


# ═══ B2: verwaister Claim nach Prozessabbruch ═══════════════════════════════
def _abgestuerzt(module) -> str:
    """Simuliert einen Prozessabbruch mitten im Provider-Aufruf.

    `SystemExit` ist eine BaseException und wird vom Ausführungspfad bewusst
    **nicht** gefangen — genau wie ein echter Prozessabbruch hinterlässt sie
    die Mutation in `executing` mit beanspruchtem Outbox-Eintrag.
    """
    service = ContactsMutationService(
        module, Provider(raises=SystemExit("Abbruch")))
    vorgang = service.prepare(_cmd())
    service.grant(vorgang.mutation_id, decision=owner_decision_for_tests(MENSCH))
    with pytest.raises(SystemExit):
        service.execute(vorgang.mutation_id)
    return vorgang.mutation_id


def test_prozessabbruch_hinterlaesst_executing_und_claim(module):
    _container(module)
    mutation_id = _abgestuerzt(module)
    with module.unit_of_work() as uow:
        zeile = uow.execute(
            "SELECT m.state AS ms, o.state AS os, o.claim_token_digest "
            "FROM contacts_mutations m JOIN personal_external_action_outbox o "
            "ON o.outbox_id = m.outbox_id WHERE m.mutation_id = ?",
            (mutation_id,)).fetchone()
    assert zeile["ms"] == MutationState.EXECUTING
    assert zeile["os"] == OutboxState.CLAIMED
    # Seit 0008 nur der Digest — der Rohtoken existiert nur im Auftrag.
    assert zeile["claim_token_digest"] is not None
    assert len(zeile["claim_token_digest"]) == 64


def test_recover_interrupted_fuehrt_nach_outcome_unknown(module):
    """Die unbekannte Phase wird NIE als failed_before_send eingestuft."""
    _container(module)
    mutation_id = _abgestuerzt(module)
    service = ContactsMutationService(module, Provider())
    erholt = service.recover_interrupted()
    assert erholt == (mutation_id,)
    with module.unit_of_work() as uow:
        zeile = uow.execute(
            "SELECT m.state AS ms, o.state AS os FROM contacts_mutations m "
            "JOIN personal_external_action_outbox o ON o.outbox_id = m.outbox_id "
            "WHERE m.mutation_id = ?", (mutation_id,)).fetchone()
        stufen = [r["stage"] for r in uow.execute(
            "SELECT stage FROM personal_audit_log WHERE subject_id = ? "
            "ORDER BY sequence", (mutation_id,)).fetchall()]
    assert zeile["ms"] == MutationState.OUTCOME_UNKNOWN
    assert zeile["os"] == OutboxState.OUTCOME_UNKNOWN
    assert AuditStage.OUTCOME_UNKNOWN in stufen


def test_erholter_vorgang_ist_abgleichbar_aber_nie_erneut_sendbar(module):
    _container(module)
    mutation_id = _abgestuerzt(module)
    provider = Provider()
    service = ContactsMutationService(module, provider)
    service.recover_interrupted()
    from personaljarvis.contacts.application.errors import MutationNotExecutable

    with pytest.raises(MutationNotExecutable, match="Abgleich"):
        service.execute(mutation_id)
    assert provider.calls == 0

    class Leser:
        def observe(self, **kw):
            from personaljarvis.contacts.application.field_contract import (
                as_bridge_contact,
                parse_create_fields,
            )

            return ReconcileObservation(
                exists=True, provider_identifier="raw-neu",
                readback=as_bridge_contact(
                    parse_create_fields({"given_name": "Fixi"}),
                    provider_identifier="raw-neu"))

    ergebnis = ContactsReconcileService(module, Leser()).reconcile(mutation_id)
    assert ergebnis.state == MutationState.SUCCEEDED
    assert provider.calls == 0, "Der Abgleich sendet nie"


def test_recover_auf_gesunder_datenbank_ist_leer(module):
    _container(module)
    service = ContactsMutationService(module, Provider())
    vorgang = service.prepare(_cmd())
    service.grant(vorgang.mutation_id, decision=owner_decision_for_tests(MENSCH))
    service.execute(vorgang.mutation_id)
    assert service.recover_interrupted() == ()


# ═══ Echte Parallelität: die Datenbank trägt die Korrektheit ════════════════
def test_parallele_vorbereitung_desselben_idempotenzschluessels(module, db_path):
    """Zwei „Prozesse" (getrennte Factories) — genau eine Mutation entsteht."""
    _container(module)
    zweites = ContactsModule(db_path)
    zweites.start()
    try:
        key = new_id()
        ergebnisse: dict = {}

        def vorbereiten(name, modul):
            try:
                s = ContactsMutationService(modul, Provider())
                v = s.prepare(_cmd(mutation_id=str(uuid.uuid4()),
                                   idempotency_key=key))
                ergebnisse[name] = (v.mutation_id, v.reused)
            except Exception as exc:                    # noqa: BLE001
                ergebnisse[name] = ("fehler", type(exc).__name__)

        t1 = threading.Thread(target=vorbereiten, args=("A", module))
        t2 = threading.Thread(target=vorbereiten, args=("B", zweites))
        t1.start(); t2.start(); t1.join(); t2.join()

        assert ergebnisse["A"][0] != "fehler", ergebnisse
        assert ergebnisse["B"][0] != "fehler", ergebnisse
        assert ergebnisse["A"][0] == ergebnisse["B"][0]
        assert {ergebnisse["A"][1], ergebnisse["B"][1]} == {True, False}
        with module.unit_of_work() as uow:
            anzahl = uow.execute(
                "SELECT count(*) AS n FROM contacts_mutations").fetchone()["n"]
        assert anzahl == 1
    finally:
        zweites.stop()


def test_paralleles_claiming_hat_genau_einen_gewinner(module, db_path):
    _container(module)
    service = ContactsMutationService(module, Provider())
    vorgang = service.prepare(_cmd())
    zweites = ContactsModule(db_path)
    zweites.start()
    try:
        resultate: dict = {}

        def beanspruchen(name, modul):
            from personaljarvis.base.outbox import OutboxNotClaimable

            try:
                with modul.unit_of_work() as uow:
                    ExternalActionOutbox(uow).claim(vorgang.outbox_id)
                resultate[name] = "gewonnen"
            except OutboxNotClaimable:
                resultate[name] = "abgewiesen"

        t1 = threading.Thread(target=beanspruchen, args=("A", module))
        t2 = threading.Thread(target=beanspruchen, args=("B", zweites))
        t1.start(); t2.start(); t1.join(); t2.join()

        assert sorted(resultate.values()) == ["abgewiesen", "gewonnen"]
        with module.unit_of_work() as uow:
            eintrag = ExternalActionOutbox(uow).require(vorgang.outbox_id)
        assert eintrag.attempt_count == 1
    finally:
        zweites.stop()


def test_parallele_audit_schreiber_erzeugen_keine_zweige(module, db_path):
    """Kein zweiter Writer kann denselben prev_hash festschreiben."""
    zweites = ContactsModule(db_path)
    zweites.start()
    try:
        def schreiben(modul, praefix):
            for i in range(8):
                with modul.unit_of_work() as uow:
                    AuditTrail(uow, module="contacts").record(
                        AuditStage.MUTATION_PREPARED, subject_type="probe",
                        subject_id=f"{praefix}-{i}", facts={"i": i})

        t1 = threading.Thread(target=schreiben, args=(module, "A"))
        t2 = threading.Thread(target=schreiben, args=(zweites, "B"))
        t1.start(); t2.start(); t1.join(); t2.join()

        with module.unit_of_work() as uow:
            assert AuditTrail(uow, module="contacts").verify_chain() is True
            zeile = uow.execute(
                "SELECT count(*) AS n, count(DISTINCT sequence) AS u, "
                "count(DISTINCT prev_hash) AS p FROM personal_audit_log "
                "WHERE prev_hash IS NOT NULL").fetchone()
        assert zeile["n"] == zeile["u"]
        # Jeder prev_hash kommt genau einmal vor — es gibt keine zwei Zweige.
        assert zeile["p"] == zeile["n"]
    finally:
        zweites.stop()


# ═══ Digest-Semantik ════════════════════════════════════════════════════════
def _payload(fields) -> MutationPayload:
    return MutationPayload(command="update", provider_account_id=KONTO,
                           container_identifier=None,
                           target_provider_identifier="raw-1",
                           expected_revision="1", fields=fields)


def test_semantisch_verschiedene_patches_haben_verschiedene_digests():
    a = _payload({"nickname": "Anna"})
    b = _payload({"nickname": "Bernd"})       # anderer Wert
    c = _payload({"nickname": None})          # ausdrückliches Leeren
    d = _payload({"job_title": "Anna"})       # anderes Feld, gleicher Wert
    digests = {a.digest, b.digest, c.digest, d.digest}
    assert len(digests) == 4


def test_digest_ist_deterministisch_und_reihenfolgefest():
    from personaljarvis.base.digest import digest_of

    assert digest_of({"a": 1, "b": [1, 2]}) == digest_of({"b": [1, 2], "a": 1})
    assert digest_of({"x": [1, 2]}) != digest_of({"x": [2, 1]})


def test_revision_und_ziel_gehen_in_den_digest_ein():
    a = _payload({"nickname": "Anna"})
    b = MutationPayload(command="update", provider_account_id=KONTO,
                        container_identifier=None,
                        target_provider_identifier="raw-2",
                        expected_revision="1", fields={"nickname": "Anna"})
    c = MutationPayload(command="update", provider_account_id=KONTO,
                        container_identifier=None,
                        target_provider_identifier="raw-1",
                        expected_revision="2", fields={"nickname": "Anna"})
    assert len({a.digest, b.digest, c.digest}) == 3


# ═══ Testisolation: kein Griff ins echte Home ═══════════════════════════════
def test_bootstrap_mit_injiziertem_pfad_sperrt_neben_der_datenbank(tmp_path):
    """Audit-Befund: Die Sperre folgte nicht der injizierten Datenbank.

    Ein Bootstrap mit Testpfad erwarb `serve.lock` am globalen Standardpfad —
    ein Testlauf fasste damit das echte Home an und haette mit einem laufenden
    Serve-Prozess um dessen Sperre konkurriert.
    """
    from personaljarvis.bootstrap import PersonalBootstrap

    heim = Path.home() / ".openjarvis" / "personal" / "serve.lock"
    vorher = heim.exists()
    bootstrap = PersonalBootstrap(tmp_path / "personal" / "jarvis.db")
    bootstrap.start()
    try:
        assert bootstrap.process_lock is not None
        lock_pfad = Path(bootstrap.process_lock.path)
        assert lock_pfad == tmp_path / "personal" / "serve.lock"
        assert lock_pfad.exists()
        assert heim.exists() == vorher, (
            "Der Bootstrap hat die Sperre am echten Standardpfad erworben")
    finally:
        bootstrap.stop()
