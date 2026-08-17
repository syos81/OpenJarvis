"""Freigabepflichtige Mutationspipeline — kontaktfrei (Gate C).

**Es gibt in dieser Suite keinen Apple-Contacts-Zugriff.** Alle Abläufe laufen
gegen eine Fake-Bridge und temporäre SQLite-Datenbanken. Kein Sidecar wird
gestartet, kein `requestAuthorization` gesendet, kein Kontakt gelesen,
geändert oder gelöscht.
"""

from __future__ import annotations

import uuid

import pytest

from personaljarvis.base.approvals import (
    owner_decision_for_tests,
    ApprovalExpired,
    ApprovalNotPending,
    ApprovalPayloadMismatch,
    ApprovalState,
    ApprovalStore,
    SelfApprovalRejected,
)
from personaljarvis.base.audit import AuditStage, AuditTrail
from personaljarvis.base.command_bus import (
    ApplicationCommandBus,
    HandlerAlreadyRegistered,
    UnknownCommand,
)
from personaljarvis.base.outbox import (
    ExternalActionOutbox,
    OutboxNotClaimable,
    OutboxState,
)
from personaljarvis.contacts.application import (
    ContactDraft,
    ContactPatch,
    ContactsApprovalService,
    ContactsMutationService,
    ContactsReconcileService,
    CreateContact,
    DeleteContact,
    MutationState,
    ProviderOutcome,
    ProviderResponse,
    ReconcileObservation,
    ReconcileVerdict,
    UpdateContact,
    register_contacts_commands,
)
from personaljarvis.contacts.application.errors import (
    AlreadySettled,
    ForeignProviderAccount,
    InvalidCommand,
    MeCardNotWritable,
    MutationNotExecutable,
    RevisionConflict,
    TargetBindingError,
    UnifiedIdentifierNotWritable,
)
from personaljarvis.contacts.application.field_contract import (
    as_bridge_contact,
    parse_canonical_payload,
    parse_create_fields,
    project_bridge_contact,
    readback_digest,
)
from personaljarvis.contacts.domain.enums import InitiationContext
from personaljarvis.contacts.domain.models import ExternalIdentifier

from .conftest import WORKSPACE, make_contact, new_id

def _code_ohne_prosa(pfad) -> str:
    """Python-Quelltext ohne Kommentare und Zeichenkettenliterale.

    Die Verbote stehen als Kommentar IM Produktivcode ("kein `importlib`",
    "kein CNSaveRequest"). Eine reine Textsuche wuerde genau diese
    Abgrenzungsnotizen als Verstoss melden.
    """
    import tokenize
    from pathlib import Path as _P

    stuecke = []
    with open(_P(pfad), "rb") as fh:
        try:
            for tok in tokenize.tokenize(fh.readline):
                if tok.type in (tokenize.COMMENT, tokenize.STRING):
                    continue
                stuecke.append(tok.string)
        except tokenize.TokenError:            # pragma: no cover
            return _P(pfad).read_text()
    return " ".join(stuecke)


def _swift_code_ohne_prosa(pfad) -> str:
    """Swift-Quelltext ohne Zeilenkommentare."""
    from pathlib import Path as _P

    zeilen = []
    for roh in _P(pfad).read_text().splitlines():
        ohne = roh.split("//", 1)[0]
        zeilen.append(ohne)
    return "\n".join(zeilen)


KONTO = "apple-system"
CONTAINER = "container-1"
MENSCH = "lukas"


# ── Fake-Bridge ─────────────────────────────────────────────────────────────
class AttrappenProvider:
    """Simuliert alle geforderten Ausgänge — ohne jeden Store-Zugriff."""

    def __init__(self, outcome: str = ProviderOutcome.SUCCEEDED, *,
                 error_code: str | None = None,
                 provider_identifier: str | None = "erzeugt-1",
                 raises: Exception | None = None,
                 readback_abweichend: bool = False) -> None:
        self.outcome = outcome
        self.error_code = error_code
        self.provider_identifier = provider_identifier
        self.raises = raises
        #: Simuliert einen Provider, der etwas anderes zurueckliest, als
        #: geschrieben wurde — dann traegt der Beleg die Nachfuehrung nicht.
        self.readback_abweichend = readback_abweichend
        self.calls: list[dict] = []

    def apply(self, payload, *, mutation_id, idempotency_key, approval_id):
        self.calls.append({"command": payload.command,
                           "mutationId": mutation_id,
                           "idempotencyKey": idempotency_key,
                           "approvalId": approval_id,
                           "target": payload.target_provider_identifier})
        if self.raises is not None:
            raise self.raises
        if self.outcome != ProviderOutcome.SUCCEEDED:
            return ProviderResponse(self.outcome, error_code=self.error_code,
                                    provider_identifier=self.provider_identifier)
        # Ein angewandter Vorgang bringt IMMER einen Read-back mit — genau wie
        # der echte Sidecar. Ohne ihn gaebe es keinen Erfolg (ADR-0025 §4).
        felder = parse_canonical_payload(payload.fields)
        if self.readback_abweichend:
            felder = parse_create_fields({"given_name": "Anders"})
        zurueck = as_bridge_contact(
            felder, provider_identifier=self.provider_identifier)
        return ProviderResponse(
            self.outcome, error_code=self.error_code,
            provider_identifier=self.provider_identifier,
            container_identifier=payload.container_identifier,
            readback=zurueck,
            readback_digest=readback_digest(project_bridge_contact(zurueck)))


class AttrappenLeser:
    """Nur-Lese-Abgleich. Schreibt nachweislich nichts."""

    def __init__(self, beobachtung: ReconcileObservation | None = None, *,
                 raises: Exception | None = None) -> None:
        self.beobachtung = beobachtung
        self.raises = raises
        self.calls: list[dict] = []

    def observe(self, *, command, provider_identifier, expected_fields,
                idempotency_key):
        self.calls.append({"command": command, "target": provider_identifier,
                           "idempotencyKey": idempotency_key})
        if self.raises is not None:
            raise self.raises
        return self.beobachtung


# ── Fixtures ────────────────────────────────────────────────────────────────
@pytest.fixture
def dienst(module):
    return lambda provider=None: ContactsMutationService(
        module, provider or AttrappenProvider())


def _create(**kw) -> CreateContact:
    defaults = dict(
        mutation_id=new_id(), idempotency_key=new_id(),
        provider_account_id=KONTO, workspace_id=WORKSPACE, actor=MENSCH,
        initiation_context=InitiationContext.USER_DIRECT,
        correlation_id=new_id(), container_identifier=CONTAINER,
        draft=ContactDraft({"given_name": "Fixi", "family_name": "Eins"}))
    defaults.update(kw)
    return CreateContact(**defaults)


def _update(**kw) -> UpdateContact:
    defaults = dict(
        mutation_id=new_id(), idempotency_key=new_id(),
        provider_account_id=KONTO, workspace_id=WORKSPACE, actor=MENSCH,
        initiation_context=InitiationContext.USER_DIRECT,
        correlation_id=new_id(), target_provider_identifier="raw-1",
        patch=ContactPatch({"nickname": "Neu"}))
    defaults.update(kw)
    return UpdateContact(**defaults)


def _delete(**kw) -> DeleteContact:
    defaults = dict(
        mutation_id=new_id(), idempotency_key=new_id(),
        provider_account_id=KONTO, workspace_id=WORKSPACE, actor=MENSCH,
        initiation_context=InitiationContext.USER_DIRECT,
        correlation_id=new_id(), target_provider_identifier="raw-1")
    defaults.update(kw)
    return DeleteContact(**defaults)


def _lokalen_kontakt_anlegen(module, *, provider_identifier="raw-1",
                             konto=KONTO, me_card=False, revision=1):
    from personaljarvis.contacts.repositories.sqlite import (
        SqliteContactRepository, SqliteExternalIdentifierRepository,
    )

    with module.unit_of_work() as uow:
        kontakt = make_contact(is_me_card=me_card)
        SqliteContactRepository(uow).add(kontakt)
        if revision != 1:
            uow.execute("UPDATE contacts SET local_revision = ? WHERE id = ?",
                        (revision, kontakt.id))
        SqliteExternalIdentifierRepository(uow).upsert(
            kontakt.id, ExternalIdentifier(
                id=new_id(), provider_account_id=konto,
                container_identifier=CONTAINER,
                provider_identifier=provider_identifier, key_set_version="v1"))
    return kontakt


def _container_bekannt(module, *, konto=KONTO, container=CONTAINER):
    from personaljarvis.contacts.domain.models import ContactSyncState
    from personaljarvis.contacts.repositories.sqlite import (
        SqliteSyncStateRepository,
    )

    with module.unit_of_work() as uow:
        SqliteSyncStateRepository(uow).upsert(ContactSyncState(
            provider_account_id=konto, container_identifier=container,
            key_set_version="v1", mode="delta"))


# ═══ Commands ═══════════════════════════════════════════════════════════════
def test_gueltige_commands():
    assert _create().command_name == "create"
    assert _update().command_name == "update"
    assert _delete().command_name == "delete"


def test_ungueltige_mutation_id():
    with pytest.raises(InvalidCommand, match="UUID"):
        _create(mutation_id="keine-uuid")


@pytest.mark.parametrize("feld", ["idempotency_key", "provider_account_id",
                                  "workspace_id", "actor", "correlation_id"])
def test_leere_pflichtfelder_abgelehnt(feld):
    with pytest.raises(InvalidCommand):
        _create(**{feld: "  "})


def test_update_ohne_ziel_id_abgelehnt():
    with pytest.raises(TargetBindingError, match="targetProviderIdentifier"):
        _update(target_provider_identifier="")


def test_delete_ohne_ziel_id_abgelehnt():
    with pytest.raises(TargetBindingError):
        _delete(target_provider_identifier="")


def test_unified_identifier_ist_nie_schreibziel():
    with pytest.raises(UnifiedIdentifierNotWritable):
        _update(target_provider_identifier="unified:abc")
    with pytest.raises(UnifiedIdentifierNotWritable):
        _delete(target_provider_identifier="unified:abc")


def test_command_kennt_kein_namensfeld():
    """Es gibt strukturell kein Feld, ueber das man per Name mutieren koennte."""
    import dataclasses

    for typ in (UpdateContact, DeleteContact):
        felder = {f.name for f in dataclasses.fields(typ)}
        for verboten in ("name", "display_name", "email", "phone", "query",
                         "search"):
            assert verboten not in felder, (typ.__name__, verboten)


def test_patch_lehnt_notizen_ab():
    """Ein Notizfeld zu schreiben wuerde eine unlesbare Notiz ueberschreiben."""
    with pytest.raises(InvalidCommand, match="nie schreibbar"):
        ContactPatch({"note": "irgendwas"})


@pytest.mark.parametrize("feld", ["id", "local_revision", "is_me_card",
                                  "unified_identifier"])
def test_patch_lehnt_unveraenderliche_felder_ab(feld):
    with pytest.raises(InvalidCommand, match="nie schreibbar"):
        ContactPatch({feld: "x"})


def test_patch_lehnt_unbekanntes_feld_ab():
    with pytest.raises(InvalidCommand, match="unbekannte Felder"):
        ContactPatch({"lieblingsfarbe": "blau"})


def test_leerer_patch_abgelehnt():
    with pytest.raises(InvalidCommand, match="ohne Feld"):
        ContactPatch({})


def test_create_ohne_container_abgelehnt():
    with pytest.raises(InvalidCommand, match="container"):
        _create(container_identifier="")


# ═══ Command Bus ════════════════════════════════════════════════════════════
def test_bus_registriert_genau_einen_handler_je_command(module, dienst):
    bus = ApplicationCommandBus()
    register_contacts_commands(bus, dienst())
    assert set(bus.registered_commands) == {CreateContact, UpdateContact,
                                            DeleteContact}


def test_bus_lehnt_doppelte_registrierung_ab(module, dienst):
    bus = ApplicationCommandBus()
    register_contacts_commands(bus, dienst())
    with pytest.raises(HandlerAlreadyRegistered):
        register_contacts_commands(bus, dienst())


def test_bus_lehnt_unbekannten_command_fail_closed_ab():
    bus = ApplicationCommandBus()

    class Fremd:
        pass

    with pytest.raises(UnknownCommand):
        bus.dispatch(Fremd())


def test_bus_dispatch_bereitet_nur_vor_und_sendet_nicht(module):
    """Ein Dispatch loest **nie** einen Provider-Aufruf aus."""
    provider = AttrappenProvider()
    bus = ApplicationCommandBus()
    register_contacts_commands(bus, ContactsMutationService(module, provider))
    _container_bekannt(module)
    vorgang = bus.dispatch(_create())
    assert vorgang.state == MutationState.AWAITING_APPROVAL
    assert provider.calls == []


def test_bus_hat_keine_dynamische_ausfuehrung():
    from pathlib import Path

    code = _code_ohne_prosa("src/personaljarvis/base/command_bus.py")
    for verboten in ("eval(", "exec(", "importlib", "__import__"):
        assert verboten not in code, verboten


# ═══ Vorbereitung und Freigabe ══════════════════════════════════════════════
def test_prepare_erzeugt_freigabe_und_outbox_ohne_send(module):
    provider = AttrappenProvider()
    service = ContactsMutationService(module, provider)
    _container_bekannt(module)
    vorgang = service.prepare(_create())
    assert vorgang.state == MutationState.AWAITING_APPROVAL
    assert provider.calls == []
    with module.unit_of_work() as uow:
        freigabe = ApprovalStore(uow).require(vorgang.approval_id)
        eintrag = ExternalActionOutbox(uow).require(vorgang.outbox_id)
    assert freigabe.state == ApprovalState.AWAITING
    assert eintrag.state == OutboxState.PENDING


def test_vorschau_zeigt_vorher_und_nachher(module):
    _lokalen_kontakt_anlegen(module)
    service = ContactsMutationService(module, AttrappenProvider())
    vorgang = service.prepare(_update(patch=ContactPatch({"nickname": "Neu"})))
    aenderungen = {c.field_name: (c.previous, c.planned)
                   for c in vorgang.preview.changes}
    assert aenderungen["nickname"] == (None, "Neu")
    assert vorgang.preview.target_label is not None


def test_delete_vorschau_nennt_ziel_und_warnt(module):
    _lokalen_kontakt_anlegen(module)
    service = ContactsMutationService(module, AttrappenProvider())
    vorgang = service.prepare(_delete())
    assert vorgang.preview.command == "delete"
    assert vorgang.preview.target_provider_identifier == "raw-1"
    assert vorgang.preview.warnings


def test_ausfuehrung_ohne_freigabe_abgelehnt(module):
    _container_bekannt(module)
    service = ContactsMutationService(module, AttrappenProvider())
    vorgang = service.prepare(_create())
    with pytest.raises(MutationNotExecutable, match="awaiting_approval"):
        service.execute(vorgang.mutation_id)


def test_freigabe_und_ausfuehrung(module):
    _container_bekannt(module)
    provider = AttrappenProvider(provider_identifier="raw-neu")
    service = ContactsMutationService(module, provider)
    vorgang = service.prepare(_create())
    service.grant(vorgang.mutation_id, decision=owner_decision_for_tests(MENSCH))
    ergebnis = service.execute(vorgang.mutation_id)
    assert ergebnis.state == MutationState.SUCCEEDED
    assert len(provider.calls) == 1


def test_modell_kann_sich_nicht_selbst_freigeben(module):
    _container_bekannt(module)
    service = ContactsMutationService(module, AttrappenProvider())
    vorgang = service.prepare(
        _create(initiation_context=InitiationContext.LLM_ASSISTED,
                actor="llm_assisted"))
    for versuch in ("llm_assisted", "automation", "system", "  "):
        with pytest.raises(SelfApprovalRejected):
            service.grant(vorgang.mutation_id, decision=owner_decision_for_tests(versuch))


def test_abgelehnte_freigabe_ist_endgueltig(module):
    _container_bekannt(module)
    service = ContactsMutationService(module, AttrappenProvider())
    vorgang = service.prepare(_create())
    service.reject(vorgang.mutation_id, decision_actor=MENSCH)
    with pytest.raises(ApprovalNotPending):
        service.grant(vorgang.mutation_id, decision=owner_decision_for_tests(MENSCH))
    with pytest.raises(AlreadySettled):
        service.execute(vorgang.mutation_id)


def test_stornierte_freigabe_ist_endgueltig(module):
    _container_bekannt(module)
    service = ContactsMutationService(module, AttrappenProvider())
    vorgang = service.prepare(_create())
    service.cancel(vorgang.mutation_id, decision_actor=MENSCH)
    with pytest.raises(ApprovalNotPending):
        service.grant(vorgang.mutation_id, decision=owner_decision_for_tests(MENSCH))


def test_abgelaufene_freigabe_wird_nicht_ausgefuehrt(module):
    _container_bekannt(module)
    provider = AttrappenProvider()
    service = ContactsMutationService(module, provider, approval_ttl_seconds=1)
    vorgang = service.prepare(_create())
    service.grant(vorgang.mutation_id, decision=owner_decision_for_tests(MENSCH))
    with module.unit_of_work() as uow:
        uow.execute("UPDATE personal_approvals SET requested_at = ?, "
                    "expires_at = ? WHERE approval_id = ?",
                    ("2000-01-01T00:00:00+00:00", "2000-01-01T00:00:01+00:00",
                     vorgang.approval_id))
    with pytest.raises(ApprovalExpired):
        service.execute(vorgang.mutation_id)
    assert provider.calls == []


def test_geaenderte_nutzlast_entwertet_die_freigabe(module):
    _container_bekannt(module)
    provider = AttrappenProvider()
    service = ContactsMutationService(module, provider)
    vorgang = service.prepare(_create())
    service.grant(vorgang.mutation_id, decision=owner_decision_for_tests(MENSCH))
    with module.unit_of_work() as uow:
        uow.execute("UPDATE contacts_mutations SET payload_json = ? "
                    "WHERE mutation_id = ?",
                    ('{"command":"create","providerAccountId":"apple-system",'
                     '"containerIdentifier":"container-1",'
                     '"targetProviderIdentifier":null,"expectedRevision":null,'
                     '"fields":{"given_name":"Manipuliert"}}',
                     vorgang.mutation_id))
    with pytest.raises(ApprovalPayloadMismatch):
        service.execute(vorgang.mutation_id)
    assert provider.calls == []


def test_freigabe_fuer_falsche_mutation_wirkt_nicht(module):
    _container_bekannt(module)
    service = ContactsMutationService(module, AttrappenProvider())
    a = service.prepare(_create())
    b = service.prepare(_create())
    service.grant(a.mutation_id, decision=owner_decision_for_tests(MENSCH))
    with pytest.raises(MutationNotExecutable):
        service.execute(b.mutation_id)


def test_doppelte_freigabe_abgelehnt(module):
    _container_bekannt(module)
    service = ContactsMutationService(module, AttrappenProvider())
    vorgang = service.prepare(_create())
    service.grant(vorgang.mutation_id, decision=owner_decision_for_tests(MENSCH))
    with pytest.raises(ApprovalNotPending):
        service.grant(vorgang.mutation_id, decision=owner_decision_for_tests(MENSCH))


def test_freigabeflaeche_listet_wartende_ohne_pii(module):
    _container_bekannt(module)
    service = ContactsMutationService(module, AttrappenProvider())
    service.prepare(_create())
    wartend = ContactsApprovalService(module).pending()
    assert len(wartend) == 1
    text = str(wartend[0])
    assert "Fixi" not in text and "Eins" not in text


# ═══ Idempotenz und Zielbindung ═════════════════════════════════════════════
def test_gleicher_idempotenzschluessel_gibt_denselben_vorgang(module):
    _container_bekannt(module)
    service = ContactsMutationService(module, AttrappenProvider())
    key = new_id()
    erster = service.prepare(_create(idempotency_key=key))
    zweiter = service.prepare(_create(idempotency_key=key))
    assert zweiter.reused is True
    assert zweiter.mutation_id == erster.mutation_id
    with module.unit_of_work() as uow:
        anzahl = uow.execute(
            "SELECT count(*) AS n FROM contacts_mutations").fetchone()["n"]
    assert anzahl == 1


def test_zweite_ausfuehrung_nach_erfolg_sendet_nicht_erneut(module):
    _container_bekannt(module)
    provider = AttrappenProvider()
    service = ContactsMutationService(module, provider)
    vorgang = service.prepare(_create())
    service.grant(vorgang.mutation_id, decision=owner_decision_for_tests(MENSCH))
    service.execute(vorgang.mutation_id)
    with pytest.raises(AlreadySettled):
        service.execute(vorgang.mutation_id)
    assert len(provider.calls) == 1


def test_fremdes_providerkonto_abgelehnt(module):
    _lokalen_kontakt_anlegen(module, konto="anderes-konto")
    service = ContactsMutationService(module, AttrappenProvider())
    with pytest.raises(ForeignProviderAccount):
        service.prepare(_update())


def test_me_card_ist_nicht_mutierbar(module):
    _lokalen_kontakt_anlegen(module, me_card=True)
    service = ContactsMutationService(module, AttrappenProvider())
    with pytest.raises(MeCardNotWritable):
        service.prepare(_update())


def test_veraltete_revision_endet_vor_dem_send(module):
    _lokalen_kontakt_anlegen(module, revision=7)
    provider = AttrappenProvider()
    service = ContactsMutationService(module, provider)
    vorgang = service.prepare(_update(expected_revision="3"))
    service.grant(vorgang.mutation_id, decision=owner_decision_for_tests(MENSCH))
    ergebnis = service.execute(vorgang.mutation_id)
    assert ergebnis.state == MutationState.FAILED_BEFORE_SEND
    assert ergebnis.error_code == "RevisionConflict"
    assert provider.calls == []


def test_unbekannter_container_endet_vor_dem_send(module):
    _container_bekannt(module, container="anderer-container")
    provider = AttrappenProvider()
    service = ContactsMutationService(module, provider)
    vorgang = service.prepare(_create())
    service.grant(vorgang.mutation_id, decision=owner_decision_for_tests(MENSCH))
    ergebnis = service.execute(vorgang.mutation_id)
    assert ergebnis.state == MutationState.FAILED_BEFORE_SEND
    assert ergebnis.error_code == "ContainerNotAvailable"
    assert provider.calls == []


# ═══ Outbox ═════════════════════════════════════════════════════════════════
def test_outbox_eintrag_entsteht_in_derselben_transaktion(module):
    _container_bekannt(module)
    service = ContactsMutationService(module, AttrappenProvider())
    vorgang = service.prepare(_create())
    with module.unit_of_work() as uow:
        eintrag = ExternalActionOutbox(uow).find_for_subject(
            "contacts.mutation", vorgang.mutation_id)
    assert eintrag is not None and eintrag.approval_id == vorgang.approval_id


def test_claiming_verhindert_doppelausfuehrung(module):
    _container_bekannt(module)
    service = ContactsMutationService(module, AttrappenProvider())
    vorgang = service.prepare(_create())
    with module.unit_of_work() as uow:
        outbox = ExternalActionOutbox(uow)
        outbox.claim(vorgang.outbox_id)
        with pytest.raises(OutboxNotClaimable):
            outbox.claim(vorgang.outbox_id)


def test_abschluss_ohne_gueltigen_claim_abgelehnt(module):
    _container_bekannt(module)
    service = ContactsMutationService(module, AttrappenProvider())
    vorgang = service.prepare(_create())
    with module.unit_of_work() as uow:
        outbox = ExternalActionOutbox(uow)
        outbox.claim(vorgang.outbox_id)
        with pytest.raises(OutboxNotClaimable):
            outbox.mark_succeeded(vorgang.outbox_id, "falsches-token")


def test_outcome_unknown_ist_nie_faellig(module):
    """Die Outbox liefert unbekannte Ausgaenge nie zur erneuten Ausfuehrung."""
    _container_bekannt(module)
    provider = AttrappenProvider(ProviderOutcome.OUTCOME_UNKNOWN,
                                 error_code="timeout_after_send")
    service = ContactsMutationService(module, provider)
    vorgang = service.prepare(_create())
    service.grant(vorgang.mutation_id, decision=owner_decision_for_tests(MENSCH))
    service.execute(vorgang.mutation_id)
    with module.unit_of_work() as uow:
        faellig = ExternalActionOutbox(uow).list_due(module="contacts")
    assert all(e.outbox_id != vorgang.outbox_id for e in faellig)


def test_abgeschlossene_eintraege_werden_nicht_geloescht(module):
    _container_bekannt(module)
    service = ContactsMutationService(module, AttrappenProvider())
    vorgang = service.prepare(_create())
    service.grant(vorgang.mutation_id, decision=owner_decision_for_tests(MENSCH))
    service.execute(vorgang.mutation_id)
    with module.unit_of_work() as uow:
        eintrag = ExternalActionOutbox(uow).require(vorgang.outbox_id)
    assert eintrag.state == OutboxState.SUCCEEDED
    assert eintrag.settled_at is not None


def test_attempt_count_zaehlt_ohne_retry_recht(module):
    _container_bekannt(module)
    service = ContactsMutationService(module, AttrappenProvider())
    vorgang = service.prepare(_create())
    with module.unit_of_work() as uow:
        outbox = ExternalActionOutbox(uow)
        _, token = outbox.claim(vorgang.outbox_id)
        outbox.mark_failed_before_send(vorgang.outbox_id, token,
                                       error_code="probe")
        eintrag, _ = outbox.claim(vorgang.outbox_id)
    assert eintrag.attempt_count == 2


# ═══ Ausführungsvertrag: alle Ausgänge ══════════════════════════════════════
@pytest.mark.parametrize("outcome,erwartet,gesendet", [
    (ProviderOutcome.SUCCEEDED, MutationState.SUCCEEDED, True),
    (ProviderOutcome.REJECTED_BEFORE_SEND, MutationState.FAILED_BEFORE_SEND, True),
    (ProviderOutcome.FAILED_BEFORE_SEND, MutationState.FAILED_BEFORE_SEND, True),
    (ProviderOutcome.CONFLICT, MutationState.FAILED_BEFORE_SEND, True),
    (ProviderOutcome.OUTCOME_UNKNOWN, MutationState.OUTCOME_UNKNOWN, True),
])
def test_alle_provider_ausgaenge(module, outcome, erwartet, gesendet):
    _container_bekannt(module)
    provider = AttrappenProvider(outcome, error_code="probe")
    service = ContactsMutationService(module, provider)
    vorgang = service.prepare(_create())
    service.grant(vorgang.mutation_id, decision=owner_decision_for_tests(MENSCH))
    ergebnis = service.execute(vorgang.mutation_id)
    assert ergebnis.state == erwartet
    assert (len(provider.calls) == 1) is gesendet


@pytest.mark.parametrize("fehler", [
    TimeoutError("Zeitueberschreitung"),
    ChildProcessError("Child beendet"),
    OSError("Verbindung weg"),
])
def test_ausnahme_im_provider_gilt_als_unbekannter_ausgang(module, fehler):
    """Wer nicht weiss, ob gesendet wurde, muss vom Schlimmsten ausgehen."""
    _container_bekannt(module)
    service = ContactsMutationService(module, AttrappenProvider(raises=fehler))
    vorgang = service.prepare(_create())
    service.grant(vorgang.mutation_id, decision=owner_decision_for_tests(MENSCH))
    ergebnis = service.execute(vorgang.mutation_id)
    assert ergebnis.state == MutationState.OUTCOME_UNKNOWN
    assert ergebnis.requires_reconcile is True


def test_kein_automatischer_retry_aus_outcome_unknown(module):
    _container_bekannt(module)
    provider = AttrappenProvider(ProviderOutcome.OUTCOME_UNKNOWN)
    service = ContactsMutationService(module, provider)
    vorgang = service.prepare(_create())
    service.grant(vorgang.mutation_id, decision=owner_decision_for_tests(MENSCH))
    service.execute(vorgang.mutation_id)
    with pytest.raises(MutationNotExecutable, match="Abgleich"):
        service.execute(vorgang.mutation_id)
    assert len(provider.calls) == 1


# ═══ Reconcile ══════════════════════════════════════════════════════════════
def _in_unbekannten_zustand(module, command):
    provider = AttrappenProvider(ProviderOutcome.OUTCOME_UNKNOWN)
    service = ContactsMutationService(module, provider)
    vorgang = service.prepare(command)
    service.grant(vorgang.mutation_id, decision=owner_decision_for_tests(MENSCH))
    service.execute(vorgang.mutation_id)
    return vorgang



def _readback(provider_identifier: str = "raw-neu"):
    """Ein kanonischer Read-back, wie ihn der echte Leser mitbringt.

    Seit ADR-0025 §5 schliesst eine per Abgleich belegte **Neuanlage** nur mit
    Read-back ab: ohne ihn gaebe es keinen lokalen Spiegel, und die
    Echo-Unterdrueckung wuerde das eigene Add-Ereignis spaeter herausfiltern.
    """
    from personaljarvis.contacts.application.field_contract import (
        as_bridge_contact,
        parse_create_fields,
    )

    return as_bridge_contact(
        parse_create_fields({"given_name": "Fixi", "family_name": "Eins"}),
        provider_identifier=provider_identifier)

def test_create_eindeutig_gefunden(module):
    """Belegt gefunden **und** kanonisch zurueckgelesen — dann erst fertig."""
    _container_bekannt(module)
    vorgang = _in_unbekannten_zustand(module, _create())
    leser = AttrappenLeser(ReconcileObservation(
        exists=True, provider_identifier="raw-neu", readback=_readback()))
    ergebnis = ContactsReconcileService(module, leser).reconcile(
        vorgang.mutation_id)
    assert ergebnis.verdict == ReconcileVerdict.APPLIED
    assert ergebnis.state == MutationState.SUCCEEDED
    # Der lokale Spiegel entsteht mit — sonst waere `succeeded` eine Luege.
    with module.unit_of_work() as uow:
        zeile = uow.execute(
            "SELECT target_contact_id, readback_digest FROM contacts_mutations "
            "WHERE mutation_id = ?", (vorgang.mutation_id,)).fetchone()
    assert zeile["target_contact_id"]
    assert zeile["readback_digest"]


def test_create_gefunden_aber_ohne_readback_bleibt_offen(module):
    """Ohne kanonischen Zustand wird nichts abgeschlossen und nichts erfunden."""
    _container_bekannt(module)
    vorgang = _in_unbekannten_zustand(module, _create())
    leser = AttrappenLeser(ReconcileObservation(
        exists=True, provider_identifier="raw-neu"))
    ergebnis = ContactsReconcileService(module, leser).reconcile(
        vorgang.mutation_id)
    assert ergebnis.state == MutationState.MANUAL_DECISION_REQUIRED
    with module.unit_of_work() as uow:
        anzahl = uow.execute("SELECT COUNT(*) c FROM contacts").fetchone()
    assert anzahl["c"] == 0


def test_create_ohne_stabilen_bezug_ist_mehrdeutig(module):
    """Ohne belegte Identitaet wird **nicht** geraten und nicht nach Namen gesucht."""
    _container_bekannt(module)
    vorgang = _in_unbekannten_zustand(module, _create())
    leser = AttrappenLeser(ReconcileObservation(exists=True,
                                                provider_identifier=None))
    ergebnis = ContactsReconcileService(module, leser).reconcile(
        vorgang.mutation_id)
    assert ergebnis.verdict == ReconcileVerdict.AMBIGUOUS
    assert ergebnis.state == MutationState.MANUAL_DECISION_REQUIRED


def test_create_nicht_angewandt(module):
    _container_bekannt(module)
    vorgang = _in_unbekannten_zustand(module, _create())
    leser = AttrappenLeser(ReconcileObservation(exists=False))
    ergebnis = ContactsReconcileService(module, leser).reconcile(
        vorgang.mutation_id)
    assert ergebnis.verdict == ReconcileVerdict.NOT_APPLIED
    assert ergebnis.state == MutationState.FAILED


def test_update_entspricht_erwartung(module):
    _lokalen_kontakt_anlegen(module)
    vorgang = _in_unbekannten_zustand(
        module, _update(patch=ContactPatch({"nickname": "Neu"})))
    leser = AttrappenLeser(ReconcileObservation(
        exists=True, fields={"nickname": "Neu"}))
    ergebnis = ContactsReconcileService(module, leser).reconcile(
        vorgang.mutation_id)
    assert ergebnis.verdict == ReconcileVerdict.APPLIED


def test_update_abweichend_ist_nicht_angewandt(module):
    _lokalen_kontakt_anlegen(module)
    vorgang = _in_unbekannten_zustand(
        module, _update(patch=ContactPatch({"nickname": "Neu"})))
    leser = AttrappenLeser(ReconcileObservation(
        exists=True, fields={"nickname": "Alt"}))
    ergebnis = ContactsReconcileService(module, leser).reconcile(
        vorgang.mutation_id)
    assert ergebnis.verdict == ReconcileVerdict.NOT_APPLIED


def test_update_teilweise_angewandt_ist_mehrdeutig(module):
    _lokalen_kontakt_anlegen(module)
    vorgang = _in_unbekannten_zustand(module, _update(
        patch=ContactPatch({"nickname": "Neu", "job_title": "Neu"})))
    leser = AttrappenLeser(ReconcileObservation(
        exists=True, fields={"nickname": "Neu", "job_title": "Alt"}))
    ergebnis = ContactsReconcileService(module, leser).reconcile(
        vorgang.mutation_id)
    assert ergebnis.verdict == ReconcileVerdict.AMBIGUOUS


def test_delete_bestaetigt(module):
    _lokalen_kontakt_anlegen(module)
    vorgang = _in_unbekannten_zustand(module, _delete())
    leser = AttrappenLeser(ReconcileObservation(exists=False))
    ergebnis = ContactsReconcileService(module, leser).reconcile(
        vorgang.mutation_id)
    assert ergebnis.verdict == ReconcileVerdict.APPLIED


def test_delete_nicht_bestaetigt(module):
    _lokalen_kontakt_anlegen(module)
    vorgang = _in_unbekannten_zustand(module, _delete())
    leser = AttrappenLeser(ReconcileObservation(exists=True))
    ergebnis = ContactsReconcileService(module, leser).reconcile(
        vorgang.mutation_id)
    assert ergebnis.verdict == ReconcileVerdict.NOT_APPLIED


def test_lesefehler_beim_abgleich_ist_mehrdeutig(module):
    _container_bekannt(module)
    vorgang = _in_unbekannten_zustand(module, _create())
    leser = AttrappenLeser(raises=OSError("Bridge weg"))
    ergebnis = ContactsReconcileService(module, leser).reconcile(
        vorgang.mutation_id)
    assert ergebnis.state == MutationState.MANUAL_DECISION_REQUIRED


def test_abgleich_nur_aus_unbekanntem_zustand(module):
    _container_bekannt(module)
    service = ContactsMutationService(module, AttrappenProvider())
    vorgang = service.prepare(_create())
    service.grant(vorgang.mutation_id, decision=owner_decision_for_tests(MENSCH))
    service.execute(vorgang.mutation_id)
    with pytest.raises(MutationNotExecutable, match="braucht keinen Abgleich"):
        ContactsReconcileService(module, AttrappenLeser()).reconcile(
            vorgang.mutation_id)


def test_abgleich_sucht_nie_nach_namen(module):
    """Der Leser bekommt Kommando, Ziel-ID und Idempotenzschluessel — sonst nichts."""
    _container_bekannt(module)
    vorgang = _in_unbekannten_zustand(module, _create())
    leser = AttrappenLeser(ReconcileObservation(exists=False))
    ContactsReconcileService(module, leser).reconcile(vorgang.mutation_id)
    assert set(leser.calls[0]) == {"command", "target", "idempotencyKey"}


def test_wartende_abgleiche_werden_gelistet(module):
    _container_bekannt(module)
    vorgang = _in_unbekannten_zustand(module, _create())
    assert vorgang.mutation_id in ContactsReconcileService(
        module, AttrappenLeser()).pending()


# ═══ Audit ══════════════════════════════════════════════════════════════════
def _stufen(module, mutation_id: str) -> list[str]:
    with module.unit_of_work() as uow:
        rows = uow.execute(
            "SELECT stage FROM personal_audit_log WHERE subject_id = ? "
            "ORDER BY sequence", (mutation_id,)).fetchall()
    return [r["stage"] for r in rows]


def test_vollstaendige_ereignisfolge_bei_erfolg(module):
    _container_bekannt(module)
    service = ContactsMutationService(module, AttrappenProvider())
    vorgang = service.prepare(_create())
    service.grant(vorgang.mutation_id, decision=owner_decision_for_tests(MENSCH))
    service.execute(vorgang.mutation_id)
    stufen = _stufen(module, vorgang.mutation_id)
    for erwartet in (AuditStage.MUTATION_PREPARED, AuditStage.APPROVAL_REQUESTED,
                     AuditStage.APPROVAL_GRANTED, AuditStage.EXECUTION_CLAIMED,
                     AuditStage.PROVIDER_SEND_STARTED,
                     AuditStage.PROVIDER_RESULT_RECEIVED,
                     AuditStage.MUTATION_COMPLETED):
        assert erwartet in stufen, erwartet


def test_ereignisfolge_bei_unbekanntem_ausgang_und_abgleich(module):
    _container_bekannt(module)
    vorgang = _in_unbekannten_zustand(module, _create())
    ContactsReconcileService(module, AttrappenLeser(
        ReconcileObservation(exists=True, provider_identifier="raw-neu",
                             readback=_readback()))
    ).reconcile(vorgang.mutation_id)
    stufen = _stufen(module, vorgang.mutation_id)
    for erwartet in (AuditStage.OUTCOME_UNKNOWN, AuditStage.RECONCILE_STARTED,
                     AuditStage.RECONCILE_SUCCEEDED,
                     AuditStage.MUTATION_COMPLETED):
        assert erwartet in stufen, erwartet


def test_hashkette_ist_intakt(module):
    _container_bekannt(module)
    service = ContactsMutationService(module, AttrappenProvider())
    vorgang = service.prepare(_create())
    service.grant(vorgang.mutation_id, decision=owner_decision_for_tests(MENSCH))
    service.execute(vorgang.mutation_id)
    with module.unit_of_work() as uow:
        assert AuditTrail(uow, module="contacts").verify_chain() is True


def test_manipulierte_kette_faellt_auf(module):
    _container_bekannt(module)
    service = ContactsMutationService(module, AttrappenProvider())
    service.prepare(_create())
    with module.unit_of_work() as uow:
        uow.execute("UPDATE personal_audit_log SET payload_hash = ? "
                    "WHERE sequence = 1", ("0" * 64,))
        assert AuditTrail(uow, module="contacts").verify_chain() is False


def test_audit_enthaelt_keine_kontaktwerte_und_keine_nutzlast(module):
    _container_bekannt(module)
    service = ContactsMutationService(module, AttrappenProvider())
    vorgang = service.prepare(_create(draft=ContactDraft(
        {"given_name": "Geheim", "family_name": "Wert"})))
    service.grant(vorgang.mutation_id, decision=owner_decision_for_tests(MENSCH))
    service.execute(vorgang.mutation_id)
    with module.unit_of_work() as uow:
        rows = uow.execute("SELECT * FROM personal_audit_log").fetchall()
    text = " ".join(str(dict(r)) for r in rows)
    for verboten in ("Geheim", "Wert", "given_name", "note"):
        assert verboten not in text, verboten


def test_unbekannte_audit_stufe_abgelehnt(module):
    with module.unit_of_work() as uow:
        with pytest.raises(ValueError, match="Unbekannte Audit-Stufe"):
            AuditTrail(uow, module="contacts").record(
                "erfunden", subject_type="x", subject_id="y", facts={})


def test_audit_faellt_mit_der_transaktion_zurueck(module):
    """Scheitert die UoW, bleibt kein Audit-Eintrag stehen."""
    with module.unit_of_work() as uow:
        vorher = uow.execute(
            "SELECT count(*) AS n FROM personal_audit_log").fetchone()["n"]
    with pytest.raises(RuntimeError):
        with module.unit_of_work() as uow:
            AuditTrail(uow, module="contacts").record(
                AuditStage.MUTATION_PREPARED, subject_type="contacts.mutation",
                subject_id=new_id(), facts={})
            raise RuntimeError("Abbruch")
    with module.unit_of_work() as uow:
        nachher = uow.execute(
            "SELECT count(*) AS n FROM personal_audit_log").fetchone()["n"]
    assert nachher == vorher


# ═══ Lifecycle ══════════════════════════════════════════════════════════════
def test_lifecycle_stellt_dienste_bereit(module):
    assert module.command_bus() is not None
    assert module.approval_service() is not None
    assert module.mutation_service() is not None
    assert module.reconcile_service(AttrappenLeser()) is not None
    with module.unit_of_work() as uow:
        assert module.outbox(uow) is not None
        assert module.audit_trail(uow) is not None


def test_lifecycle_startet_keinen_executor(module):
    """Kein Hintergrundlauf, kein Timer, keine Mutation beim Start."""
    with module.unit_of_work() as uow:
        offen = uow.execute(
            "SELECT count(*) AS n FROM personal_external_action_outbox "
            "WHERE state = 'claimed'").fetchone()["n"]
    assert offen == 0


def test_dienste_vor_dem_start_nicht_abrufbar(db_path):
    from personaljarvis.contacts.lifecycle import ContactsModule
    from personaljarvis.errors import PersonalJarvisError

    m = ContactsModule(db_path)
    for aufruf in (m.command_bus, m.approval_service, m.mutation_service):
        with pytest.raises(PersonalJarvisError, match="nicht gestartet"):
            aufruf()


def test_standarddienst_verweigert_mutationen_mangels_capability(module):
    """Der Modul-Standarddienst kann nichts absenden.

    Die Bridge meldet `mutationsImplemented=false`; die Capability-Pruefung
    lehnt deshalb bereits die Vorbereitung ab. Das ist die gewollte
    fail-closed-Kette bis zur echten Freischaltung in einem spaeteren Gate.
    """
    from personaljarvis.contacts.application.errors import CapabilityNotDeclared

    _container_bekannt(module)
    service = module.mutation_service()
    with pytest.raises(CapabilityNotDeclared, match="nicht deklariert"):
        service.prepare(_create())


def test_standardprovider_sendet_nichts(module):
    """Selbst wenn die Capability spaeter faellt: der Standardprovider sendet nie."""
    from personaljarvis.contacts.lifecycle import _UnavailableProvider

    antwort = _UnavailableProvider().apply(
        None, mutation_id="m", idempotency_key="k", approval_id="a")
    assert antwort.outcome == ProviderOutcome.FAILED_BEFORE_SEND
    assert antwort.error_code == "not_implemented"


# ═══ Strukturelle Kontaktfreiheit ═══════════════════════════════════════════
def test_application_schicht_kennt_keine_apple_typen():
    from pathlib import Path

    for datei in Path("src/personaljarvis/contacts/application").rglob("*.py"):
        code = _code_ohne_prosa(datei)
        for verboten in ("CNContact", "CNContactStore", "requestAuthorization",
                         "CNSaveRequest"):
            assert verboten not in code, f"{datei.name}: {verboten}"


def test_application_schicht_startet_keinen_prozess():
    from pathlib import Path

    for datei in Path("src/personaljarvis/contacts/application").rglob("*.py"):
        code = _code_ohne_prosa(datei)
        for verboten in ("subprocess", "Popen", "os.system"):
            assert verboten not in code, f"{datei.name}: {verboten}"


def test_sidecar_schreibt_nur_ueber_create():
    """Der Sidecar kennt genau einen Schreibpfad, und der heisst `create`.

    Update und Delete bleiben `not_implemented` — Phase M4 bzw. M5, Delete
    zusaetzlich hinter der offenen Entscheidung DEC-D06 (ADR-0025 §7/§9).
    """
    code = _swift_code_ohne_prosa("native/contacts-bridge/src/sidecar.swift")
    assert "opMutationNotImplemented" in code
    assert "notImplemented" in code
    # Genau ein Schreibvorgang, und er steht in opCreate. Seit 2026-08-01
    # fuehrt er durch die Objective-C-@try/@catch-Grenze — ein direkter
    # `store.execute(` in Swift waere wieder der Pfad, auf dem eine
    # NSException den Prozess ohne Diagnose toetet.
    assert code.count("CNSaveRequest()") == 1
    assert code.count("store.execute(") == 0
    assert code.count("JCExecuteSaveRequestGuarded(") == 1
    assert "func opCreate" in code
    # Update und Delete laufen weiterhin in den Nicht-implementiert-Zweig.
    assert 'case "update", "delete":' in code
    assert '"updateImplemented": false' in code
    assert '"deleteImplemented": false' in code


def test_bridge_client_verweigert_update_und_delete():
    from personaljarvis.contacts.bridge.client import ContactsBridgeClient

    for name in ("update", "delete"):
        with pytest.raises(NotImplementedError, match="ADR-0025"):
            getattr(ContactsBridgeClient, name)(None)


def test_bridge_client_create_verlangt_den_vollen_vertrag():
    """`create` nimmt keine Teilangabe entgegen — alle Pflichtfelder oder nichts."""
    from personaljarvis.contacts.bridge.client import ContactsBridgeClient

    with pytest.raises(TypeError):
        ContactsBridgeClient(None).create()
