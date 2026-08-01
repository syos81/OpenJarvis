"""Menschlicher Abschluss eines ungewissen Ausgangs. **Kontaktfrei.**

Kein Sidecar, kein `CNContactStore`, kein Provider — dieser Weg berührt den
Provider per Konstruktion nicht. Alle Datenbanken liegen in `tmp_path`.

**Anlass.** Beim Create-Livetest am 2026-08-01 stand eine Mutation auf
`outcome_unknown`, der Nutzer hat bei Apple Contacts nachgesehen und die
Änderung dort nicht gefunden — und es gab keinen Weg, dieses Wissen
festzuhalten. `reject`/`cancel`/`expire` verlangen eine wartende Freigabe (die
war verbraucht), `execute` ist gesperrt, `reconcile` verlangt Providerzugriff,
und `manual_decision_required` war eine Sackgasse.

Die Tests halten drei Dinge fest: der Abschluss **funktioniert**, er
**sendet nie**, und er **schreibt die Historie nicht um**.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from personaljarvis.contacts.api.redaction import container_ref
from personaljarvis.contacts.api.routes import (
    DEFAULT_WORKSPACE_HEADER,
    PREFIX,
    create_contacts_router,
)
from personaljarvis.contacts.application import ContactsMutationService
from personaljarvis.contacts.application.mutation_service import (
    ManualResolution,
    MutationState,
)
from personaljarvis.contacts.domain.capabilities import ContactCapabilitySet
from personaljarvis.contacts.domain.models import ContactSyncState
from personaljarvis.contacts.repositories.sqlite import SqliteSyncStateRepository

from .conftest import WORKSPACE
from .test_create_vertical import KONTO, MENSCH, ZaehlProvider

CONTAINER = "01234567-89AB-CDEF-0123-456789ABCDEF:ABAccount"
CREATE_CAPS = ContactCapabilitySet(create_supported=True)

GUELTIG = {"user_initiated": True, "decision": "not_observed",
           "evidence": "manual_provider_inspection"}


def _kopf() -> dict:
    return {DEFAULT_WORKSPACE_HEADER: WORKSPACE, "X-Personal-Actor": MENSCH}


@pytest.fixture
def aufbau(module):
    """Modul mit bekanntem Container, freigeschaltetem `create` und Client."""
    def bauen(provider: ZaehlProvider):
        with module.unit_of_work() as uow:
            SqliteSyncStateRepository(uow).upsert(ContactSyncState(
                provider_account_id=KONTO, container_identifier=CONTAINER,
                key_set_version="v1", mode="delta", cursor_token="T",
                cursor_taken_at="2026-07-31T09:00:00+00:00"))
        module._capabilities = CREATE_CAPS
        module._mutation_service = ContactsMutationService(
            module, provider, capabilities=CREATE_CAPS)
        app = FastAPI()
        app.include_router(create_contacts_router(module))
        return TestClient(app)
    return bauen


def _create_body(**kw) -> dict:
    body = {"idempotency_key": "idem-" + str(id(kw)), "correlation_id": "corr",
            "container_ref": container_ref(CONTAINER),
            "fields": {"given_name": "ZZZ-JarvisTest"}}
    body.update(kw)
    return body


def _bis(client, zustand: str, provider: ZaehlProvider) -> str:
    """Bringt eine Mutation ueber den regulaeren Weg in den Zielzustand."""
    r = client.post(PREFIX, headers=_kopf(), json=_create_body())
    mid = r.json()["mutation_id"]
    client.post(f"{PREFIX}/mutations/{mid}/approve", headers=_kopf(),
                json={"decision_actor": MENSCH})
    if zustand == MutationState.APPROVED:
        return mid
    client.post(f"{PREFIX}/mutations/{mid}/execute", headers=_kopf(),
                json={"user_initiated": True})
    return mid


def _abbruch_provider() -> ZaehlProvider:
    from personaljarvis.contacts.bridge.errors import (
        MutationOutcomeUnknown,
        ProcessDiagnostics,
    )

    return ZaehlProvider(raises=MutationOutcomeUnknown(
        "child_signalled",
        ProcessDiagnostics(request_id=1, operation="create",
                           elapsed_seconds=0.9, child_exit_code=-6,
                           child_signal=6, child_alive=False,
                           stdout_eof=True, stderr_eof=True,
                           detail="Child durch Signal beendet")))


def _zeile(module, mid):
    with module.unit_of_work() as uow:
        return uow.execute(
            "SELECT state, outcome, last_error_code, completed_at "
            "FROM contacts_mutations WHERE mutation_id = ?", (mid,)).fetchone()


def _stufen(module, mid) -> list[str]:
    with module.unit_of_work() as uow:
        return [r["stage"] for r in uow.execute(
            "SELECT stage FROM personal_audit_log WHERE subject_id = ? "
            "ORDER BY sequence", (mid,)).fetchall()]


# ═══ Der Abschluss selbst ═══════════════════════════════════════════════════
def test_aus_outcome_unknown_wird_manuell_abgeschlossen(module, aufbau):
    provider = _abbruch_provider()
    client = aufbau(provider)
    mid = _bis(client, MutationState.OUTCOME_UNKNOWN, provider)
    assert _zeile(module, mid)["state"] == MutationState.OUTCOME_UNKNOWN

    r = client.post(f"{PREFIX}/mutations/{mid}/resolve-outcome",
                    headers=_kopf(), json=GUELTIG)
    assert r.status_code == 200, r.text
    assert r.json()["state"] == MutationState.MANUALLY_RESOLVED_NOT_APPLIED
    assert r.json()["retryable"] is False
    # Genau ein Sendversuch — und der lag vor dem Abschluss.
    assert provider.calls == 1
    assert r.json()["attempt_count"] == 1

    zeile = _zeile(module, mid)
    assert zeile["state"] == MutationState.MANUALLY_RESOLVED_NOT_APPLIED
    assert zeile["outcome"] == "failed"
    assert zeile["last_error_code"] == ManualResolution.ERROR_CODE
    assert zeile["completed_at"] is not None


def test_aus_manual_decision_required_wird_abgeschlossen(module, aufbau):
    provider = _abbruch_provider()
    client = aufbau(provider)
    mid = _bis(client, MutationState.OUTCOME_UNKNOWN, provider)
    with module.unit_of_work() as uow:
        uow.execute("UPDATE contacts_mutations SET state = ? "
                    "WHERE mutation_id = ?",
                    (MutationState.MANUAL_DECISION_REQUIRED, mid))

    r = client.post(f"{PREFIX}/mutations/{mid}/resolve-outcome",
                    headers=_kopf(), json=GUELTIG)
    assert r.status_code == 200
    assert _zeile(module, mid)["state"] == \
        MutationState.MANUALLY_RESOLVED_NOT_APPLIED
    assert provider.calls == 1


def test_der_zustand_ist_terminal_und_nicht_abgleichbedueftig():
    assert (MutationState.MANUALLY_RESOLVED_NOT_APPLIED
            in MutationState.TERMINAL)
    assert (MutationState.MANUALLY_RESOLVED_NOT_APPLIED
            not in MutationState.NEEDS_RECONCILE)
    assert (MutationState.MANUALLY_RESOLVED_NOT_APPLIED
            not in MutationState.PENDING_LOCAL_CATCHUP)


def test_der_zustand_liegt_nicht_in_der_echo_sperrmenge():
    """Ein abgeschlossener Vorgang ist nicht mehr unterwegs."""
    from personaljarvis.contacts.domain.enums import MutationState as E
    from personaljarvis.contacts.sync.echo import IN_FLIGHT_STATES

    assert E.MANUALLY_RESOLVED_NOT_APPLIED not in IN_FLIGHT_STATES


# ═══ Kein Providerkontakt ═══════════════════════════════════════════════════
def test_der_abschluss_sendet_nicht_und_liest_nicht(module, aufbau):
    provider = _abbruch_provider()
    client = aufbau(provider)
    mid = _bis(client, MutationState.OUTCOME_UNKNOWN, provider)

    class VerbotenerLeser:
        def observe(self, **kw):
            raise AssertionError("Der Abschluss liest nie am Provider")

    module.reconcile_reader = VerbotenerLeser()
    vorher = provider.calls
    client.post(f"{PREFIX}/mutations/{mid}/resolve-outcome", headers=_kopf(),
                json=GUELTIG)
    assert provider.calls == vorher


def test_der_dienst_startet_keinen_prozess():
    """Statisch: der Abschluss kennt weder Sidecar noch Bridge."""
    import inspect

    from personaljarvis.contacts.application.mutation_service import (
        ContactsMutationService as S,
    )

    quelle = inspect.getsource(S.resolve_outcome_manually)
    for verboten in ("SidecarProcess", "_provider", "apply(", "observe(",
                     "resolve_sidecar", "client"):
        assert verboten not in quelle, verboten


# ═══ Geschlossener Vertrag ══════════════════════════════════════════════════
@pytest.mark.parametrize("koerper", [
    {},
    {"decision": "not_observed", "evidence": "manual_provider_inspection"},
    {"user_initiated": False, "decision": "not_observed",
     "evidence": "manual_provider_inspection"},
    {"user_initiated": True, "decision": "applied",
     "evidence": "manual_provider_inspection"},
    {"user_initiated": True, "decision": "not_observed", "evidence": "bauchgefuehl"},
    {"user_initiated": True, "decision": "not_observed",
     "evidence": "manual_provider_inspection", "grund": "war halt so"},
])
def test_vertragsverstoesse_werden_abgewiesen(module, aufbau, koerper):
    provider = _abbruch_provider()
    client = aufbau(provider)
    mid = _bis(client, MutationState.OUTCOME_UNKNOWN, provider)
    r = client.post(f"{PREFIX}/mutations/{mid}/resolve-outcome",
                    headers=_kopf(), json=koerper)
    assert r.status_code == 422
    assert _zeile(module, mid)["state"] == MutationState.OUTCOME_UNKNOWN


def test_es_gibt_keinen_freitext():
    from personaljarvis.contacts.api import schemas as S

    felder = S.ResolveOutcomeIn.model_fields
    assert set(felder) == {"user_initiated", "decision", "evidence"}
    for name in felder:
        assert "Literal" in str(felder[name].annotation), name


# ═══ Unzulässige Ausgangszustände ═══════════════════════════════════════════
@pytest.mark.parametrize("zustand", [
    MutationState.AWAITING_APPROVAL, MutationState.APPROVED,
    MutationState.EXECUTING, MutationState.SUCCEEDED,
    MutationState.PROVIDER_APPLIED_PENDING_RECONCILE,
    MutationState.FAILED_BEFORE_SEND,
])
def test_aus_anderen_zustaenden_wird_nicht_abgeschlossen(module, aufbau,
                                                         zustand):
    provider = _abbruch_provider()
    client = aufbau(provider)
    mid = _bis(client, MutationState.OUTCOME_UNKNOWN, provider)
    with module.unit_of_work() as uow:
        uow.execute("UPDATE contacts_mutations SET state = ? "
                    "WHERE mutation_id = ?", (zustand, mid))
    r = client.post(f"{PREFIX}/mutations/{mid}/resolve-outcome",
                    headers=_kopf(), json=GUELTIG)
    assert r.status_code == 409
    assert _zeile(module, mid)["state"] == zustand


def test_ohne_verbrauchte_freigabe_gibt_es_nichts_abzuschliessen(module, aufbau):
    """Ohne Sendversuch gibt es keinen ungewissen Ausgang."""
    provider = _abbruch_provider()
    client = aufbau(provider)
    mid = _bis(client, MutationState.APPROVED, provider)
    with module.unit_of_work() as uow:
        uow.execute("UPDATE contacts_mutations SET state = ? "
                    "WHERE mutation_id = ?", (MutationState.OUTCOME_UNKNOWN, mid))
    r = client.post(f"{PREFIX}/mutations/{mid}/resolve-outcome",
                    headers=_kopf(), json=GUELTIG)
    assert r.status_code in (409, 422)
    assert provider.calls == 0


# ═══ Danach ═════════════════════════════════════════════════════════════════
def test_zweiter_abschluss_veraendert_nichts(module, aufbau):
    provider = _abbruch_provider()
    client = aufbau(provider)
    mid = _bis(client, MutationState.OUTCOME_UNKNOWN, provider)
    client.post(f"{PREFIX}/mutations/{mid}/resolve-outcome", headers=_kopf(),
                json=GUELTIG)
    vorher = dict(_zeile(module, mid))
    stufen_vorher = _stufen(module, mid)

    zweiter = client.post(f"{PREFIX}/mutations/{mid}/resolve-outcome",
                          headers=_kopf(), json=GUELTIG)
    assert zweiter.status_code == 409
    assert dict(_zeile(module, mid)) == vorher
    assert _stufen(module, mid) == stufen_vorher


def test_execute_bleibt_danach_gesperrt(module, aufbau):
    provider = _abbruch_provider()
    client = aufbau(provider)
    mid = _bis(client, MutationState.OUTCOME_UNKNOWN, provider)
    client.post(f"{PREFIX}/mutations/{mid}/resolve-outcome", headers=_kopf(),
                json=GUELTIG)
    r = client.post(f"{PREFIX}/mutations/{mid}/execute", headers=_kopf(),
                    json={"user_initiated": True})
    assert r.status_code == 409
    assert provider.calls == 1


def test_freigabe_bleibt_verbraucht_und_outbox_terminal(module, aufbau):
    provider = _abbruch_provider()
    client = aufbau(provider)
    mid = _bis(client, MutationState.OUTCOME_UNKNOWN, provider)
    client.post(f"{PREFIX}/mutations/{mid}/resolve-outcome", headers=_kopf(),
                json=GUELTIG)
    with module.unit_of_work() as uow:
        freigabe = uow.execute(
            "SELECT state FROM personal_approvals").fetchone()["state"]
        outbox = uow.execute(
            "SELECT state, claim_token FROM personal_external_action_outbox"
        ).fetchone()
    assert freigabe == "consumed"
    assert outbox["state"] == "abandoned"       # terminal
    assert outbox["claim_token"] is None


def test_recover_interrupted_fasst_den_zustand_nicht_an(module, aufbau):
    provider = _abbruch_provider()
    client = aufbau(provider)
    mid = _bis(client, MutationState.OUTCOME_UNKNOWN, provider)
    client.post(f"{PREFIX}/mutations/{mid}/resolve-outcome", headers=_kopf(),
                json=GUELTIG)
    assert mid not in module.mutation_service().recover_interrupted()
    assert _zeile(module, mid)["state"] == \
        MutationState.MANUALLY_RESOLVED_NOT_APPLIED


# ═══ Die Historie bleibt stehen ═════════════════════════════════════════════
def test_die_auditkette_bleibt_vollstaendig_und_waechst_nur(module, aufbau):
    """Der Abschluss ist ein **spaeteres** Ereignis, kein Ersatz."""
    provider = _abbruch_provider()
    client = aufbau(provider)
    mid = _bis(client, MutationState.OUTCOME_UNKNOWN, provider)
    vorher = _stufen(module, mid)
    assert "outcome_unknown" in vorher

    client.post(f"{PREFIX}/mutations/{mid}/resolve-outcome", headers=_kopf(),
                json=GUELTIG)
    nachher = _stufen(module, mid)
    # Die alte Kette steht unveraendert am Anfang der neuen.
    assert nachher[:len(vorher)] == vorher
    assert nachher[-1] == "mutation_outcome_manually_resolved"


def test_das_auditereignis_ist_pii_arm(module, aufbau):
    provider = _abbruch_provider()
    client = aufbau(provider)
    mid = _bis(client, MutationState.OUTCOME_UNKNOWN, provider)
    client.post(f"{PREFIX}/mutations/{mid}/resolve-outcome", headers=_kopf(),
                json=GUELTIG)
    with module.unit_of_work() as uow:
        text = " ".join(str(dict(r)) for r in uow.execute(
            "SELECT * FROM personal_audit_log").fetchall())
    for verboten in ("ZZZ-JarvisTest", CONTAINER, "ABAccount", "/Users/"):
        assert verboten not in text, verboten


def test_die_antwort_traegt_keine_rohe_kennung(module, aufbau):
    provider = _abbruch_provider()
    client = aufbau(provider)
    mid = _bis(client, MutationState.OUTCOME_UNKNOWN, provider)
    r = client.post(f"{PREFIX}/mutations/{mid}/resolve-outcome",
                    headers=_kopf(), json=GUELTIG)
    for verboten in (CONTAINER, KONTO, "ABAccount", "provider_identifier"):
        assert verboten not in r.text
