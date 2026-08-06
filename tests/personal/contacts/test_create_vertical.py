"""Vertikaler Create-Pfad: Identitäten, Fähigkeiten, Ausführung, Nachführung.

**Kontaktfrei.** Kein Sidecar wird gestartet, kein `CNContactStore` berührt,
keine Autorisierung angefragt. Alle Provider sind Attrappen; alle Datenbanken
liegen in `tmp_path`.

Die zentrale Invariante dieser Suite: **genau ein Send je Mutation.** Jeder
Test, der einen zweiten Aufruf provozieren könnte — Doppelklick, Parallelität,
Neustart, Timeout —, prüft den Aufrufzähler des Providers.
"""

from __future__ import annotations

import threading

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
from personaljarvis.contacts.application.field_contract import (
    as_bridge_contact,
    parse_canonical_payload,
    parse_create_fields,
    project_bridge_contact,
    readback_digest,
)
from personaljarvis.contacts.application.models import ProviderOutcome
from personaljarvis.contacts.application.mutation_service import (
    MutationState,
    ProviderResponse,
)
from personaljarvis.contacts.application.queries import ContactsQueryService
from personaljarvis.contacts.application.reconcile import ReconcileObservation
from personaljarvis.contacts.domain.capabilities import ContactCapabilitySet
from personaljarvis.contacts.domain.models import ContactSyncState
from personaljarvis.contacts.repositories.sqlite import SqliteSyncStateRepository

from .conftest import WORKSPACE

KONTO = "apple-local"
CONTAINER = "01234567-89AB-CDEF-0123-456789ABCDEF:ABAccount"
MENSCH = "lukas"
ERZEUGT = "NEU-PID-1"


# ── Attrappen ───────────────────────────────────────────────────────────────
class ZaehlProvider:
    """Zählt jeden Sendeversuch. Der Zähler ist der eigentliche Nachweis."""

    def __init__(self, outcome: str = ProviderOutcome.SUCCEEDED, *,
                 error_code: str | None = None,
                 raises: Exception | None = None,
                 verzoegerung: float = 0.0) -> None:
        self.outcome = outcome
        self.error_code = error_code
        self.raises = raises
        self.verzoegerung = verzoegerung
        self.calls = 0
        self.lock = threading.Lock()

    def apply(self, payload, *, mutation_id, idempotency_key, approval_id):
        with self.lock:
            self.calls += 1
        if self.verzoegerung:
            import time

            time.sleep(self.verzoegerung)
        if self.raises is not None:
            raise self.raises
        if self.outcome != ProviderOutcome.SUCCEEDED:
            return ProviderResponse(self.outcome, error_code=self.error_code)
        felder = parse_canonical_payload(payload.fields)
        zurueck = as_bridge_contact(felder, provider_identifier=ERZEUGT)
        return ProviderResponse(
            ProviderOutcome.SUCCEEDED, provider_identifier=ERZEUGT,
            container_identifier=payload.container_identifier,
            readback=zurueck,
            readback_digest=readback_digest(project_bridge_contact(zurueck)))


CREATE_CAPS = ContactCapabilitySet(create_supported=True)


@pytest.fixture
def provider() -> ZaehlProvider:
    return ZaehlProvider()


@pytest.fixture
def modul(module, provider):
    """Modul mit bekanntem Container und freigeschaltetem `create`."""
    with module.unit_of_work() as uow:
        SqliteSyncStateRepository(uow).upsert(ContactSyncState(
            provider_account_id=KONTO, container_identifier=CONTAINER,
            key_set_version="v1", mode="delta", cursor_token="TOKEN",
            cursor_taken_at="2026-07-31T09:00:00+00:00"))
    module._capabilities = CREATE_CAPS
    module._mutation_service = ContactsMutationService(
        module, provider, capabilities=CREATE_CAPS)
    return module


@pytest.fixture
def client(modul):
    app = FastAPI()
    app.include_router(create_contacts_router(modul))
    return TestClient(app)


def _kopf() -> dict:
    return {DEFAULT_WORKSPACE_HEADER: WORKSPACE, "X-Personal-Actor": MENSCH}


def _create_body(**kw) -> dict:
    body = {"idempotency_key": "idem-" + str(id(kw)),
            "correlation_id": "corr-1",
            "container_ref": container_ref(CONTAINER),
            "fields": {"given_name": "ZZZ-JarvisTest", "family_name": "Anlage"}}
    body.update(kw)
    return body


def _vorbereitet(client, **kw) -> str:
    r = client.post(PREFIX, headers=_kopf(), json=_create_body(**kw))
    assert r.status_code == 201, r.text
    return r.json()["mutation_id"]


def _freigegeben(client, **kw) -> str:
    mid = _vorbereitet(client, **kw)
    r = client.post(f"{PREFIX}/mutations/{mid}/approve", headers=_kopf(),
                    json={"decision_actor": MENSCH})
    assert r.status_code == 200, r.text
    return mid


# ═══ Identitäten: keine rohe Kennung, in keiner Richtung ════════════════════
def test_create_zielt_ueber_die_maskierte_containerreferenz(client, provider):
    mid = _vorbereitet(client)
    assert mid
    assert provider.calls == 0


def test_rohe_containerkennung_wird_vom_muster_abgewiesen(client):
    r = client.post(PREFIX, headers=_kopf(),
                    json=_create_body(container_ref=CONTAINER))
    assert r.status_code == 422
    assert "ABAccount" not in r.text


def test_unbekannte_containerreferenz_scheitert_fail_closed(client, provider):
    r = client.post(PREFIX, headers=_kopf(),
                    json=_create_body(container_ref="C-000000"))
    # 409: der Zielcontainer ist nicht verfuegbar — fail-closed, nie ein Raten.
    assert r.status_code == 409
    assert provider.calls == 0


def test_mehrdeutige_referenz_scheitert_statt_zu_waehlen(modul, client, provider):
    """Eine Maskenkollision darf nie zur Wahl des ersten Treffers führen."""
    from unittest.mock import patch

    echt = container_ref

    def kollidierend(kennung: str) -> str:
        return "C-aaaaaa" if kennung.endswith("ABAccount") else echt(kennung)

    with modul.unit_of_work() as uow:
        SqliteSyncStateRepository(uow).upsert(ContactSyncState(
            provider_account_id=KONTO,
            container_identifier="ZWEITER-CONTAINER:ABAccount",
            key_set_version="v1", mode="delta", cursor_token="T2",
            cursor_taken_at="2026-07-31T09:00:00+00:00"))
    with patch("personaljarvis.contacts.api.redaction.container_ref",
               side_effect=kollidierend):
        r = client.post(PREFIX, headers=_kopf(),
                        json=_create_body(container_ref="C-aaaaaa"))
    assert r.status_code == 409
    assert "nicht eindeutig" in r.text
    assert provider.calls == 0


def test_interne_aufloesung_behaelt_die_echte_kennung(modul, client):
    """Innen roh, aussen maskiert — sonst faende der Sidecar den Container nicht."""
    mid = _vorbereitet(client)
    with modul.unit_of_work() as uow:
        zeile = uow.execute(
            "SELECT provider_account_id, container_identifier "
            "FROM contacts_mutations WHERE mutation_id = ?", (mid,)).fetchone()
    assert zeile["container_identifier"] == CONTAINER
    assert zeile["provider_account_id"] == KONTO


def test_keine_antwort_traegt_eine_rohe_kennung(client):
    mid = _freigegeben(client)
    for pfad in (PREFIX, f"{PREFIX}/mutations",
                 f"{PREFIX}/mutations/{mid}", f"{PREFIX}/approvals",
                 f"{PREFIX}/sync/status"):
        text = client.get(pfad, headers=_kopf()).text
        for verboten in (CONTAINER, KONTO, "ABAccount", ERZEUGT,
                         "provider_identifier", "container_identifier",
                         "provider_account_id"):
            assert verboten not in text, f"{verboten} in {pfad}"


# ═══ Fähigkeiten: fail-closed ═══════════════════════════════════════════════
def test_ohne_freigeschaltete_faehigkeit_wird_nicht_vorbereitet(module, provider):
    module._capabilities = ContactCapabilitySet()      # alles False
    module._mutation_service = ContactsMutationService(
        module, provider, capabilities=module._capabilities)
    with module.unit_of_work() as uow:
        SqliteSyncStateRepository(uow).upsert(ContactSyncState(
            provider_account_id=KONTO, container_identifier=CONTAINER,
            key_set_version="v1", mode="delta", cursor_token="T",
            cursor_taken_at="2026-07-31T09:00:00+00:00"))
    app = FastAPI()
    app.include_router(create_contacts_router(module))
    r = TestClient(app).post(PREFIX, headers=_kopf(), json=_create_body())
    assert r.status_code == 422
    assert provider.calls == 0


@pytest.mark.parametrize("handshake,erwartet", [
    ({"createImplemented": True, "mutationContractVersion": 1,
      "fieldContractVersion": 1}, True),
    ({"createImplemented": True, "mutationContractVersion": 0,
      "fieldContractVersion": 1}, False),
    ({"createImplemented": True, "mutationContractVersion": 2,
      "fieldContractVersion": 1}, False),
    ({"createImplemented": True, "fieldContractVersion": 1}, False),
    ({"createImplemented": True, "mutationContractVersion": 1}, False),
    # Ohne `createImplemented`: seit ADR-0026 **True**, denn das Flag des
    # Sidecars zaehlt fuer Schreibrechte nicht mehr — es ist dauerhaft falsch,
    # und der Sidecar hat gar keinen Schreibpfad. Entscheidend sind
    # Vertragsstand und App-Prozess-Kanal.
    ({"mutationContractVersion": 1, "fieldContractVersion": 1}, True),
    ({}, False),
])
def test_capability_bruecke_ist_versionsgenau(handshake, erwartet):
    """Der Vertragsstand sperrt weiterhin alles — auch bei offenem Kanal.

    Seit ADR-0026 §10 kommt das Schreibrecht nicht mehr aus dem Sidecar
    (der hat keinen Schreibpfad), sondern aus dem App-Prozess-Kanal. Der
    Vertragsstand bleibt aber eine harte Sperre davor: Ein Sidecar mit
    fremdem Vertragsstand schaltet nichts frei, egal wie offen der Kanal ist.
    Deshalb steht hier ein ausdruecklich offener Kanal — geprueft wird die
    Versionsgenauigkeit, nicht die Freigabe.
    """
    from personaljarvis.contacts.application.app_channel import (
        fake_debug_capabilities,
    )
    from personaljarvis.contacts.bridge.models import BridgeCapabilities
    from personaljarvis.contacts.domain.capabilities import derive_capabilities

    class Status:
        available = True
        protocol_version = 1
        capabilities = BridgeCapabilities.parse(handshake)

    caps = derive_capabilities(Status(), app_channel=fake_debug_capabilities())
    assert caps.create_supported is erwartet


def test_create_schaltet_update_und_delete_nicht_mit_frei():
    """Je Operation einzeln — ein Sammelflag gaebe es hier nicht.

    Der produktive Sidecar meldet `update`/`delete` als nicht implementiert
    (siehe Test darunter). Diese Ableitung stellt sicher, dass ein `create`
    allein sie auch dann nicht mitzieht, wenn beide Angaben fehlen — der
    haeufigste Weg, wie ein Sammelflag versehentlich zu viel freischaltet.
    """
    from personaljarvis.contacts.application.app_channel import (
        fake_debug_capabilities,
    )
    from personaljarvis.contacts.bridge.models import BridgeCapabilities
    from personaljarvis.contacts.domain.capabilities import derive_capabilities

    class Status:
        available = True
        protocol_version = 1
        capabilities = BridgeCapabilities.parse({
            "createImplemented": True, "mutationsImplemented": True,
            "mutationContractVersion": 1, "fieldContractVersion": 1})

    caps = derive_capabilities(Status(), app_channel=fake_debug_capabilities())
    assert caps.create_supported is True
    assert caps.update_supported is False
    assert caps.delete_supported is False


def test_fehlender_handshake_faellt_auf_nur_lesen_zurueck():
    from personaljarvis.contacts.domain.capabilities import derive_capabilities

    for status in (None, type("S", (), {"available": False})()):
        caps = derive_capabilities(status)
        assert caps.read_supported is True
        assert not (caps.create_supported or caps.update_supported
                    or caps.delete_supported)


def test_der_sidecar_meldet_keinen_schreibpfad_mehr():
    """Statisch am Quelltext: seit ADR-0026 schreibt der Sidecar nicht mehr.

    Vier x86_64-Livetests starben im Sidecar-Save
    (`NSInternalInconsistencyException`, Koordinator ohne Stores); derselbe
    Save im App-Prozess gelang. Produktive Writes laufen deshalb dort — der
    Sidecar bleibt Lese-, Sync- und Diagnosewerkzeug.
    """
    from pathlib import Path

    quelle = (Path(__file__).resolve().parents[3]
              / "native/contacts-bridge/src/sidecar.swift").read_text()
    assert '"createImplemented": false' in quelle
    assert '"updateImplemented": false' in quelle
    assert '"deleteImplemented": false' in quelle
    assert '"mutationsImplemented": false' in quelle
    # Der Create-Einstieg lehnt **vor** jeder Store-Beruehrung ab.
    einstieg = quelle.split("func opCreate(")[1][:1200]
    assert "capability_denied" in einstieg


# ═══ Ausführung: eine eigene, ausdrückliche Aktion ══════════════════════════
def test_freigabe_allein_sendet_nichts(client, provider):
    _freigegeben(client)
    assert provider.calls == 0


def test_ausfuehrung_ohne_freigabe_scheitert(client, provider):
    mid = _vorbereitet(client)
    r = client.post(f"{PREFIX}/mutations/{mid}/execute", headers=_kopf(),
                    json={"user_initiated": True})
    assert r.status_code in (409, 422)
    assert provider.calls == 0


@pytest.mark.parametrize("koerper", [{}, {"user_initiated": False},
                                     {"user_initiated": "ja"},
                                     {"user_initiated": True, "extra": 1}])
def test_ohne_ausdrueckliche_nutzeraktion_wird_nicht_ausgefuehrt(
        client, provider, koerper):
    mid = _freigegeben(client)
    r = client.post(f"{PREFIX}/mutations/{mid}/execute", headers=_kopf(),
                    json=koerper)
    assert r.status_code == 422
    assert provider.calls == 0


def test_die_bestaetigung_ist_kein_query_parameter(client, provider):
    mid = _freigegeben(client)
    r = client.post(f"{PREFIX}/mutations/{mid}/execute?user_initiated=true",
                    headers=_kopf(), json={})
    assert r.status_code == 422
    assert provider.calls == 0


def test_erste_ausfuehrung_sendet_genau_einmal(client, provider):
    mid = _freigegeben(client)
    r = client.post(f"{PREFIX}/mutations/{mid}/execute", headers=_kopf(),
                    json={"user_initiated": True})
    assert r.status_code == 200, r.text
    assert provider.calls == 1
    assert r.json()["state"] == MutationState.SUCCEEDED
    assert r.json()["contact_id"]


def test_zweiter_klick_sendet_nicht_erneut(client, provider):
    mid = _freigegeben(client)
    client.post(f"{PREFIX}/mutations/{mid}/execute", headers=_kopf(),
                json={"user_initiated": True})
    zweiter = client.post(f"{PREFIX}/mutations/{mid}/execute", headers=_kopf(),
                          json={"user_initiated": True})
    assert zweiter.status_code == 409
    assert provider.calls == 1


def test_gleichzeitige_ausfuehrung_sendet_nur_einmal(modul, provider):
    """Zwei Aufrufe zur selben Zeit — genau einer gewinnt den Outbox-Claim."""
    provider.verzoegerung = 0.05
    app = FastAPI()
    app.include_router(create_contacts_router(modul))
    c = TestClient(app)
    mid = _freigegeben(c)

    ergebnisse: list[int] = []

    def lauf() -> None:
        r = c.post(f"{PREFIX}/mutations/{mid}/execute", headers=_kopf(),
                   json={"user_initiated": True})
        ergebnisse.append(r.status_code)

    faeden = [threading.Thread(target=lauf) for _ in range(4)]
    for f in faeden:
        f.start()
    for f in faeden:
        f.join()

    assert provider.calls == 1
    assert sorted(ergebnisse).count(200) == 1


def test_timeout_endet_in_outcome_unknown_ohne_zweiten_send(modul, provider):
    from personaljarvis.contacts.bridge.errors import (
        MutationOutcomeUnknown,
        ProcessDiagnostics,
    )

    provider.raises = MutationOutcomeUnknown(
        "request_timeout",
        ProcessDiagnostics(request_id=1, operation="create",
                           elapsed_seconds=120.0, child_exit_code=None,
                           child_signal=None, child_alive=True,
                           stdout_eof=False, stderr_eof=False,
                           detail="keine Antwort binnen 120.0 s"))
    app = FastAPI()
    app.include_router(create_contacts_router(modul))
    c = TestClient(app)
    mid = _freigegeben(c)
    r = c.post(f"{PREFIX}/mutations/{mid}/execute", headers=_kopf(),
               json={"user_initiated": True})
    assert r.status_code == 200
    assert r.json()["state"] == MutationState.OUTCOME_UNKNOWN
    assert r.json()["retryable"] is False
    assert provider.calls == 1

    # Und von dort führt kein Ausführungsweg zurück.
    zweiter = c.post(f"{PREFIX}/mutations/{mid}/execute", headers=_kopf(),
                     json={"user_initiated": True})
    assert zweiter.status_code == 409
    assert provider.calls == 1


def test_failed_before_send_ist_terminal(modul):
    provider = ZaehlProvider(ProviderOutcome.REJECTED_BEFORE_SEND,
                             error_code="invalid_request")
    modul._mutation_service = ContactsMutationService(
        modul, provider, capabilities=CREATE_CAPS)
    app = FastAPI()
    app.include_router(create_contacts_router(modul))
    c = TestClient(app)
    mid = _freigegeben(c)
    r = c.post(f"{PREFIX}/mutations/{mid}/execute", headers=_kopf(),
               json={"user_initiated": True})
    assert r.json()["state"] == MutationState.FAILED_BEFORE_SEND
    assert c.post(f"{PREFIX}/mutations/{mid}/execute", headers=_kopf(),
                  json={"user_initiated": True}).status_code == 409
    assert provider.calls == 1


def test_prozessabbruch_setzt_nie_auf_sendbar_zurueck(modul, provider):
    """`recover_interrupted` fasst eine bewiesene Providerwirkung nicht an."""
    app = FastAPI()
    app.include_router(create_contacts_router(modul))
    c = TestClient(app)
    mid = _freigegeben(c)
    c.post(f"{PREFIX}/mutations/{mid}/execute", headers=_kopf(),
           json={"user_initiated": True})
    # Zustand kuenstlich auf die Zwischenlage zuruecksetzen, als waere C2
    # nach dem Providererfolg abgebrochen.
    with modul.unit_of_work() as uow:
        uow.execute("UPDATE contacts_mutations SET state = ?, completed_at = NULL "
                    "WHERE mutation_id = ?",
                    (MutationState.PROVIDER_APPLIED_PENDING_RECONCILE, mid))

    erholt = modul.mutation_service().recover_interrupted()
    assert mid not in erholt
    with modul.unit_of_work() as uow:
        zustand = uow.execute(
            "SELECT state FROM contacts_mutations WHERE mutation_id = ?",
            (mid,)).fetchone()["state"]
    assert zustand == MutationState.PROVIDER_APPLIED_PENDING_RECONCILE
    assert provider.calls == 1


# ═══ C1/C2: lokale Nachführung ══════════════════════════════════════════════
def _lokaler_kontakt(modul):
    with modul.unit_of_work() as uow:
        return uow.execute(
            "SELECT c.id, c.display_name, e.provider_identifier, "
            "e.container_identifier, e.provider_account_id "
            "FROM contacts c JOIN contact_external_ids e ON e.contact_id = c.id "
            "WHERE e.provider_identifier = ?", (ERZEUGT,)).fetchall()


def test_erfolg_legt_genau_einen_lokalen_kontakt_an(modul, client, provider):
    mid = _freigegeben(client)
    client.post(f"{PREFIX}/mutations/{mid}/execute", headers=_kopf(),
                json={"user_initiated": True})
    zeilen = _lokaler_kontakt(modul)
    assert len(zeilen) == 1
    assert zeilen[0]["display_name"] == "ZZZ-JarvisTest Anlage"
    assert zeilen[0]["container_identifier"] == CONTAINER
    assert zeilen[0]["provider_account_id"] == KONTO


def test_erfolg_verknuepft_die_mutation_mit_dem_kontakt(modul, client):
    mid = _freigegeben(client)
    antwort = client.post(f"{PREFIX}/mutations/{mid}/execute", headers=_kopf(),
                          json={"user_initiated": True}).json()
    with modul.unit_of_work() as uow:
        zeile = uow.execute(
            "SELECT target_contact_id, readback_digest, state "
            "FROM contacts_mutations WHERE mutation_id = ?", (mid,)).fetchone()
    assert zeile["target_contact_id"] == antwort["contact_id"]
    assert len(zeile["readback_digest"]) == 64
    assert zeile["state"] == MutationState.SUCCEEDED


def test_read_back_ist_die_quelle_der_nachfuehrung(modul, client):
    """Gespiegelt wird, was der Provider zurueckgab — nicht der Entwurf."""
    mid = _freigegeben(client)
    client.post(f"{PREFIX}/mutations/{mid}/execute", headers=_kopf(),
                json={"user_initiated": True})
    zeilen = _lokaler_kontakt(modul)
    assert zeilen[0]["provider_identifier"] == ERZEUGT


def test_nachfuehrung_erzeugt_kein_duplikat(modul, client, provider):
    mid = _freigegeben(client)
    client.post(f"{PREFIX}/mutations/{mid}/execute", headers=_kopf(),
                json={"user_initiated": True})
    # Eine zweite Nachfuehrung ist erlaubt und muss denselben Datensatz treffen.
    modul.mutation_service().finalize_pending(mid)
    assert len(_lokaler_kontakt(modul)) == 1
    assert provider.calls == 1


def test_nachfuehrung_laeuft_ohne_provideraufruf(modul, client, provider):
    """Der Beleg traegt sie: der Entwurf ist beweisbar der Providerzustand."""
    mid = _freigegeben(client)
    client.post(f"{PREFIX}/mutations/{mid}/execute", headers=_kopf(),
                json={"user_initiated": True})
    with modul.unit_of_work() as uow:
        uow.execute("DELETE FROM contact_external_ids WHERE provider_identifier = ?",
                    (ERZEUGT,))
        uow.execute("UPDATE contacts_mutations SET state = ?, completed_at = NULL "
                    "WHERE mutation_id = ?",
                    (MutationState.PROVIDER_APPLIED_PENDING_RECONCILE, mid))

    vorher = provider.calls
    ergebnis = modul.mutation_service().finalize_pending(mid)
    assert ergebnis.state == MutationState.SUCCEEDED
    assert provider.calls == vorher
    assert len(_lokaler_kontakt(modul)) == 1


def test_ohne_passenden_beleg_wird_nichts_geraten(modul, client):
    mid = _freigegeben(client)
    client.post(f"{PREFIX}/mutations/{mid}/execute", headers=_kopf(),
                json={"user_initiated": True})
    with modul.unit_of_work() as uow:
        uow.execute("UPDATE contacts_mutations SET state = ?, "
                    "readback_digest = ?, completed_at = NULL "
                    "WHERE mutation_id = ?",
                    (MutationState.PROVIDER_APPLIED_PENDING_RECONCILE,
                     "f" * 64, mid))
    from personaljarvis.contacts.application.errors import MutationNotExecutable

    with pytest.raises(MutationNotExecutable, match="Abgleich"):
        modul.mutation_service().finalize_pending(mid)


def test_die_ereignisfolge_ist_vollstaendig(modul, client):
    mid = _freigegeben(client)
    client.post(f"{PREFIX}/mutations/{mid}/execute", headers=_kopf(),
                json={"user_initiated": True})
    with modul.unit_of_work() as uow:
        stufen = [r["stage"] for r in uow.execute(
            "SELECT stage FROM personal_audit_log WHERE subject_id = ? "
            "ORDER BY sequence", (mid,)).fetchall()]
    assert stufen == [
        "mutation_prepared", "approval_requested", "approval_granted",
        "execution_claimed", "provider_send_started",
        "provider_result_received", "mutation_completed"]


# ═══ Datenschutz ════════════════════════════════════════════════════════════
def test_audit_traegt_keinen_kontaktwert_und_keine_kennung(modul, client):
    mid = _freigegeben(client)
    client.post(f"{PREFIX}/mutations/{mid}/execute", headers=_kopf(),
                json={"user_initiated": True})
    with modul.unit_of_work() as uow:
        text = " ".join(str(dict(r)) for r in uow.execute(
            "SELECT * FROM personal_audit_log").fetchall())
    for verboten in ("ZZZ-JarvisTest", "Anlage", CONTAINER, ERZEUGT,
                     "ABAccount", "/Users/"):
        assert verboten not in text, verboten


def test_fehlerantwort_traegt_keinen_feldwert(client):
    r = client.post(PREFIX, headers=_kopf(),
                    json=_create_body(fields={"given_name": "Geheimname"}
                                      | {"lieblingsfarbe": "blau"}))
    assert r.status_code == 422
    assert "Geheimname" not in r.text
    assert "blau" not in r.text


def test_oeffentliche_mutationsmodelle_kennen_keine_rohkennung():
    from personaljarvis.contacts.api import schemas as S

    for modell in (S.CreateContactIn, S.UpdateContactIn, S.DeleteContactIn,
                   S.PreparedMutationOut, S.MutationOut, S.MutationDetailOut,
                   S.ReconcileOut, S.ContactDetailOut, S.ContactSummaryOut,
                   S.ExecutionResultOut):
        for feld in ("provider_identifier", "container_identifier",
                     "provider_account_id", "target_provider_identifier",
                     "write_target", "cursor_token"):
            assert feld not in modell.model_fields, f"{modell.__name__}.{feld}"


# ═══ Komposition ════════════════════════════════════════════════════════════
def test_ohne_registrierten_provider_wird_nichts_gesendet(module):
    """Der Standard bleibt der Provider, der nachweislich nichts sendet."""
    from personaljarvis.contacts.lifecycle import _UnavailableProvider

    antwort = _UnavailableProvider().apply(
        None, mutation_id="m", idempotency_key="k", approval_id="a")
    assert antwort.outcome == ProviderOutcome.FAILED_BEFORE_SEND
    assert antwort.error_code == "not_implemented"
    assert module.mutation_service()._provider.__class__ is _UnavailableProvider


def test_registrierung_startet_keinen_prozess_und_fuehrt_nichts_aus(tmp_path):
    """Die Kompositionswurzel verdrahtet — sie loest nichts aus."""
    import inspect

    import personaljarvis as PJ

    quelle = inspect.getsource(PJ._register_mutation_bridge)
    code = "\n".join(z.split("#", 1)[0] for z in quelle.splitlines())
    for verboten in (".execute(", ".apply(", "SidecarProcess(", ".start()",
                     "finalize_pending", "Thread", "Timer", "schedule"):
        assert verboten not in code, verboten


def test_der_registrierte_provider_wird_tatsaechlich_benutzt(module):
    marker = ZaehlProvider()
    module.mutation_provider = marker
    module._mutation_service = None
    assert module.mutation_service()._provider is marker


def test_kein_hintergrundexecutor_und_kein_scheduler():
    """Im gesamten Kontaktmodul gibt es keinen zeitgesteuerten Sendeweg."""
    from pathlib import Path

    wurzel = Path(__file__).resolve().parents[3] / "src/personaljarvis"
    for datei in wurzel.rglob("*.py"):
        code = "\n".join(z.split("#", 1)[0] for z in
                         datei.read_text().splitlines())
        for verboten in ("threading.Timer", "sched.scheduler",
                         "BackgroundTasks", "apscheduler", "add_job",
                         "asyncio.create_task"):
            assert verboten not in code, f"{datei.name}: {verboten}"


# ═══ Abgleich nach ungewissem Ausgang ═══════════════════════════════════════
#
# Der teuerste reale Fall: der Provider hat angelegt, aber die Antwort ging
# verloren. Der Vorgang steht auf `outcome_unknown`; erst der **lesende**
# Abgleich klaert ihn. Frueher setzte dieser Weg direkt `succeeded` — der
# lokale Kontakt fehlte dann, und die Echo-Unterdrueckung haette ihn beim
# naechsten Delta-Lauf ausgefiltert.
class LeseAttrappe:
    """Rein lesender Abgleichleser. Zaehlt jeden Lesezugriff."""

    def __init__(self, *, exists: bool | None = True, mit_readback=True,
                 felder=None) -> None:
        self.exists = exists
        self.mit_readback = mit_readback
        self.felder = felder or {"given_name": "ZZZ-JarvisTest",
                                 "family_name": "Anlage"}
        self.calls = 0

    def observe(self, *, command, provider_identifier, expected_fields,
                idempotency_key):
        self.calls += 1
        if self.exists is not True:
            return ReconcileObservation(exists=self.exists)
        zurueck = (as_bridge_contact(parse_create_fields(self.felder),
                                     provider_identifier=ERZEUGT)
                   if self.mit_readback else None)
        return ReconcileObservation(
            exists=True, provider_identifier=ERZEUGT,
            fields=dict(self.felder), readback=zurueck)


def _timeout_provider() -> ZaehlProvider:
    from personaljarvis.contacts.bridge.errors import (
        MutationOutcomeUnknown,
        ProcessDiagnostics,
    )

    return ZaehlProvider(raises=MutationOutcomeUnknown(
        "request_timeout",
        ProcessDiagnostics(request_id=1, operation="create",
                           elapsed_seconds=120.0, child_exit_code=None,
                           child_signal=None, child_alive=True,
                           stdout_eof=False, stderr_eof=False,
                           detail="keine Antwort binnen 120.0 s")))


def _mit_timeout(module, leser) -> tuple:
    """Bereitet vor, gibt frei, laeuft in einen Timeout — und stellt bereit."""
    provider = _timeout_provider()
    with module.unit_of_work() as uow:
        SqliteSyncStateRepository(uow).upsert(ContactSyncState(
            provider_account_id=KONTO, container_identifier=CONTAINER,
            key_set_version="v1", mode="delta", cursor_token="TOKEN",
            cursor_taken_at="2026-07-31T09:00:00+00:00"))
    module._capabilities = CREATE_CAPS
    module._mutation_service = ContactsMutationService(
        module, provider, capabilities=CREATE_CAPS)
    module.reconcile_reader = leser
    app = FastAPI()
    app.include_router(create_contacts_router(module))
    c = TestClient(app)
    mid = _freigegeben(c)
    r = c.post(f"{PREFIX}/mutations/{mid}/execute", headers=_kopf(),
               json={"user_initiated": True})
    assert r.json()["state"] == MutationState.OUTCOME_UNKNOWN
    return c, mid, provider


def _mutationszeile(module, mid):
    with module.unit_of_work() as uow:
        return uow.execute(
            "SELECT state, target_contact_id, readback_digest, "
            "target_provider_identifier FROM contacts_mutations "
            "WHERE mutation_id = ?", (mid,)).fetchone()


# ── A. Timeout, aber der Provider hat tatsaechlich angelegt ────────────────
def test_abgleich_nach_timeout_fuehrt_bis_succeeded(module):
    leser = LeseAttrappe()
    c, mid, provider = _mit_timeout(module, leser)

    ergebnis = c.post(f"{PREFIX}/mutations/{mid}/reconcile",
                      headers=_kopf()).json()
    assert ergebnis["verdict"] == "applied"
    assert ergebnis["state"] == MutationState.SUCCEEDED

    zeile = _mutationszeile(module, mid)
    assert zeile["state"] == MutationState.SUCCEEDED
    assert zeile["target_contact_id"]
    assert len(zeile["readback_digest"]) == 64
    assert zeile["target_provider_identifier"] == ERZEUGT
    # Genau ein lokaler Kontakt, genau eine externe Identitaet — und **kein**
    # Voll-Diff als Voraussetzung.
    assert len(_lokaler_kontakt(module)) == 1
    # Genau ein Sendversuch insgesamt, ein Lesezugriff.
    assert provider.calls == 1
    assert leser.calls == 1
    assert ergebnis["contact_id"] == zeile["target_contact_id"]


def test_abgleich_nach_timeout_schliesst_die_auditkette(module):
    c, mid, _ = _mit_timeout(module, LeseAttrappe())
    c.post(f"{PREFIX}/mutations/{mid}/reconcile", headers=_kopf())
    with module.unit_of_work() as uow:
        stufen = [r["stage"] for r in uow.execute(
            "SELECT stage FROM personal_audit_log WHERE subject_id = ? "
            "ORDER BY sequence", (mid,)).fetchall()]
    assert stufen == [
        "mutation_prepared", "approval_requested", "approval_granted",
        "execution_claimed", "provider_send_started",
        "provider_result_received", "outcome_unknown", "reconcile_started",
        "reconcile_succeeded", "mutation_completed"]


# ── B. Abgleich ohne Read-back ────────────────────────────────────────────
def test_abgleich_ohne_readback_schliesst_nicht_ab(module):
    """Belegt gefunden, aber kein kanonischer Zustand — dann entscheidet ein Mensch."""
    leser = LeseAttrappe(mit_readback=False)
    c, mid, provider = _mit_timeout(module, leser)

    ergebnis = c.post(f"{PREFIX}/mutations/{mid}/reconcile",
                      headers=_kopf()).json()
    assert ergebnis["state"] == MutationState.MANUAL_DECISION_REQUIRED
    assert ergebnis["verdict"] == "ambiguous"

    zeile = _mutationszeile(module, mid)
    assert zeile["state"] == MutationState.MANUAL_DECISION_REQUIRED
    assert zeile["target_contact_id"] is None
    assert zeile["readback_digest"] is None
    # Nichts erfunden, nichts gesendet.
    assert _lokaler_kontakt(module) == []
    assert provider.calls == 1


def test_abgleich_ohne_providerkontakt_endet_nicht_in_succeeded(module):
    leser = LeseAttrappe(exists=None)
    c, mid, provider = _mit_timeout(module, leser)
    ergebnis = c.post(f"{PREFIX}/mutations/{mid}/reconcile",
                      headers=_kopf()).json()
    assert ergebnis["state"] != MutationState.SUCCEEDED
    assert _lokaler_kontakt(module) == []
    assert provider.calls == 1


# ── C. Lokaler Commit scheitert ───────────────────────────────────────────
def test_fehlgeschlagene_nachfuehrung_behaelt_den_providerbeleg(module,
                                                                monkeypatch):
    leser = LeseAttrappe()
    c, mid, provider = _mit_timeout(module, leser)

    def platzt(self, uow, zeile, quelle):
        raise RuntimeError("Datenbank fuer diesen Lauf nicht schreibbar")

    monkeypatch.setattr(ContactsMutationService, "_spiegeln", platzt)
    with pytest.raises(RuntimeError):
        c.post(f"{PREFIX}/mutations/{mid}/reconcile", headers=_kopf())

    zeile = _mutationszeile(module, mid)
    assert zeile["state"] == MutationState.PROVIDER_APPLIED_PENDING_RECONCILE
    assert zeile["readback_digest"], "Der Providerbeleg darf nicht verlorengehen"
    assert zeile["target_provider_identifier"] == ERZEUGT
    assert _lokaler_kontakt(module) == []

    # Danach ist der Abschluss ohne jeden Provideraufruf nachholbar.
    monkeypatch.undo()
    vorher = provider.calls
    ergebnis = module.mutation_service().finalize_pending(mid)
    assert ergebnis.state == MutationState.SUCCEEDED
    assert provider.calls == vorher
    assert len(_lokaler_kontakt(module)) == 1


# ── D. Wiederholter Abgleich ──────────────────────────────────────────────
def test_zweiter_abgleich_erzeugt_nichts_neues(module):
    leser = LeseAttrappe()
    c, mid, provider = _mit_timeout(module, leser)
    erste = c.post(f"{PREFIX}/mutations/{mid}/reconcile", headers=_kopf()).json()

    zweite = c.post(f"{PREFIX}/mutations/{mid}/reconcile", headers=_kopf())
    # Aus `succeeded` gibt es keinen Abgleich mehr — der Vorgang ist fertig.
    assert zweite.status_code == 409
    assert provider.calls == 1
    assert len(_lokaler_kontakt(module)) == 1
    assert _mutationszeile(module, mid)["target_contact_id"] == \
        erste["contact_id"]


def test_wiederholte_nachfuehrung_bleibt_bei_demselben_kontakt(module):
    c, mid, provider = _mit_timeout(module, LeseAttrappe())
    c.post(f"{PREFIX}/mutations/{mid}/reconcile", headers=_kopf())
    erste = _mutationszeile(module, mid)["target_contact_id"]

    module.mutation_service().finalize_pending(mid)
    module.mutation_service().finalize_pending(mid)
    assert _mutationszeile(module, mid)["target_contact_id"] == erste
    assert len(_lokaler_kontakt(module)) == 1
    assert provider.calls == 1


# ── E. Neustart im Zwischenzustand ────────────────────────────────────────
def test_neustart_im_zwischenzustand_sendet_nicht(module, monkeypatch):
    leser = LeseAttrappe()
    c, mid, provider = _mit_timeout(module, leser)

    def platzt(self, uow, zeile, quelle):
        raise RuntimeError("Abbruch zwischen C1 und C2")

    monkeypatch.setattr(ContactsMutationService, "_spiegeln", platzt)
    with pytest.raises(RuntimeError):
        c.post(f"{PREFIX}/mutations/{mid}/reconcile", headers=_kopf())
    monkeypatch.undo()

    # „Neustart": die Erholung laeuft und fasst den Zwischenzustand nicht an.
    erholt = module.mutation_service().recover_interrupted()
    assert mid not in erholt
    assert _mutationszeile(module, mid)["state"] == \
        MutationState.PROVIDER_APPLIED_PENDING_RECONCILE
    assert provider.calls == 1

    # Die lokale Nachfuehrung bleibt moeglich — ohne Provideraufruf.
    assert module.mutation_service().finalize_pending(mid).state == \
        MutationState.SUCCEEDED
    assert provider.calls == 1
    assert len(_lokaler_kontakt(module)) == 1


# ═══ Sendversuchszählung ════════════════════════════════════════════════════
#
# Befund des Livetests: `contacts_mutations.attempt_count` stand auf 0,
# waehrend die Outbox 1 zaehlte und tatsaechlich genau ein Sendversuch lief.
# Zwei Zahlen fuer dieselbe Sache, und die oeffentlich sichtbare war die
# falsche.
#
# Festgelegte Bedeutung: **`attempt_count` ist die Zahl tatsaechlich
# begonnener externer Sendversuche.** Kanonisch ist die Outbox — sie erhoeht
# beim Claim, und der Claim ist der Moment, ab dem gesendet wird.
def _zaehler(modul, mid) -> tuple[int, int, int]:
    """(Vorgangsspalte, Outbox, oeffentliche Antwort)."""
    with modul.unit_of_work() as uow:
        vorgang = uow.execute(
            "SELECT attempt_count FROM contacts_mutations WHERE mutation_id = ?",
            (mid,)).fetchone()["attempt_count"]
        outbox = uow.execute(
            "SELECT o.attempt_count FROM personal_external_action_outbox o "
            "JOIN contacts_mutations m ON m.outbox_id = o.outbox_id "
            "WHERE m.mutation_id = ?", (mid,)).fetchone()["attempt_count"]
    oeffentlich = ContactsQueryService(modul).get_mutation(
        mid, workspace_id=WORKSPACE).attempt_count
    return vorgang, outbox, oeffentlich


def _einig(modul, mid, erwartet: int) -> None:
    vorgang, outbox, oeffentlich = _zaehler(modul, mid)
    assert outbox == erwartet, f"Outbox {outbox} != {erwartet}"
    assert oeffentlich == erwartet, f"oeffentlich {oeffentlich} != {erwartet}"
    assert vorgang == erwartet, f"Vorgangsspalte {vorgang} != {erwartet}"


def test_vor_der_ausfuehrung_zaehlt_nichts(modul, client, provider):
    mid = _vorbereitet(client)
    _einig(modul, mid, 0)                       # Prepare
    client.post(f"{PREFIX}/mutations/{mid}/approve", headers=_kopf(),
                json={"decision_actor": MENSCH})
    _einig(modul, mid, 0)                       # Freigabe
    assert provider.calls == 0


def test_ein_send_zaehlt_ueberall_eins(modul, client, provider):
    mid = _freigegeben(client)
    client.post(f"{PREFIX}/mutations/{mid}/execute", headers=_kopf(),
                json={"user_initiated": True})
    assert provider.calls == 1
    _einig(modul, mid, 1)


def test_abbruch_zaehlt_ebenfalls_genau_eins(modul):
    from personaljarvis.contacts.bridge.errors import (
        MutationOutcomeUnknown,
        ProcessDiagnostics,
    )

    provider = ZaehlProvider(raises=MutationOutcomeUnknown(
        "child_signalled",
        ProcessDiagnostics(request_id=1, operation="create",
                           elapsed_seconds=0.9, child_exit_code=-6,
                           child_signal=6, child_alive=False,
                           stdout_eof=True, stderr_eof=True, detail="Signal")))
    modul._mutation_service = ContactsMutationService(
        modul, provider, capabilities=CREATE_CAPS)
    app = FastAPI()
    app.include_router(create_contacts_router(modul))
    c = TestClient(app)
    mid = _freigegeben(c)
    antwort = c.post(f"{PREFIX}/mutations/{mid}/execute", headers=_kopf(),
                     json={"user_initiated": True}).json()
    assert antwort["state"] == MutationState.OUTCOME_UNKNOWN
    assert antwort["attempt_count"] == 1
    _einig(modul, mid, 1)


def test_abgewiesener_zweiter_execute_zaehlt_nicht(modul, client, provider):
    mid = _freigegeben(client)
    client.post(f"{PREFIX}/mutations/{mid}/execute", headers=_kopf(),
                json={"user_initiated": True})
    client.post(f"{PREFIX}/mutations/{mid}/execute", headers=_kopf(),
                json={"user_initiated": True})
    assert provider.calls == 1
    _einig(modul, mid, 1)


def test_nachfuehrung_und_neustart_zaehlen_nicht(modul, client, provider):
    mid = _freigegeben(client)
    client.post(f"{PREFIX}/mutations/{mid}/execute", headers=_kopf(),
                json={"user_initiated": True})
    modul.mutation_service().finalize_pending(mid)      # C2 erneut
    modul.mutation_service().recover_interrupted()      # „Neustart"
    assert provider.calls == 1
    _einig(modul, mid, 1)


def test_abgleich_zaehlt_nicht(modul):
    """Der Abgleich liest — er sendet nie, also zaehlt er auch nicht."""
    from personaljarvis.contacts.bridge.errors import (
        MutationOutcomeUnknown,
        ProcessDiagnostics,
    )

    provider = ZaehlProvider(raises=MutationOutcomeUnknown(
        "request_timeout",
        ProcessDiagnostics(request_id=1, operation="create",
                           elapsed_seconds=120.0, child_exit_code=None,
                           child_signal=None, child_alive=True,
                           stdout_eof=False, stderr_eof=False, detail="Timeout")))
    modul._mutation_service = ContactsMutationService(
        modul, provider, capabilities=CREATE_CAPS)
    modul.reconcile_reader = LeseAttrappe()
    app = FastAPI()
    app.include_router(create_contacts_router(modul))
    c = TestClient(app)
    mid = _freigegeben(c)
    c.post(f"{PREFIX}/mutations/{mid}/execute", headers=_kopf(),
           json={"user_initiated": True})
    _einig(modul, mid, 1)
    c.post(f"{PREFIX}/mutations/{mid}/reconcile", headers=_kopf())
    assert provider.calls == 1
    _einig(modul, mid, 1)


def test_die_outbox_ist_die_kanonische_quelle(modul, client, provider):
    """Weichen die beiden je ab, gewinnt die Outbox — sichtbar und belegt."""
    mid = _freigegeben(client)
    client.post(f"{PREFIX}/mutations/{mid}/execute", headers=_kopf(),
                json={"user_initiated": True})
    # Die Vorgangsspalte kuenstlich verfaelschen: die oeffentliche Antwort
    # darf ihr nicht folgen.
    with modul.unit_of_work() as uow:
        uow.execute("UPDATE contacts_mutations SET attempt_count = 99 "
                    "WHERE mutation_id = ?", (mid,))
    body = client.get(f"{PREFIX}/mutations/{mid}", headers=_kopf()).json()
    assert body["attempt_count"] == 1


# ═══ Ablageorte: fachlich unterscheidbar ════════════════════════════════════
def test_die_containerart_erscheint_maskiert_im_status(modul, client):
    """Ohne sie liesse sich ein Ziel nur an Reihenfolge oder Groesse waehlen."""
    with modul.unit_of_work() as uow:
        SqliteSyncStateRepository(uow).upsert(ContactSyncState(
            provider_account_id=KONTO, container_identifier=CONTAINER,
            key_set_version="v1", mode="delta", cursor_token="T",
            cursor_taken_at="2026-07-31T09:00:00+00:00",
            container_type="cardDAV"))
        SqliteSyncStateRepository(uow).upsert(ContactSyncState(
            provider_account_id=KONTO, container_identifier="_local:ABAccount",
            key_set_version="v1", mode="delta", cursor_token="T",
            cursor_taken_at="2026-07-31T09:00:00+00:00",
            container_type="local"))
    zeilen = client.get(f"{PREFIX}/sync/status", headers=_kopf()).json()
    arten = {z["container_ref"]: z["container_type"] for z in zeilen}
    assert set(arten.values()) == {"local", "cardDAV"}
    # Die Auswahl haengt an der Art, nicht an der Position.
    assert arten[container_ref("_local:ABAccount")] == "local"
    assert arten[container_ref(CONTAINER)] == "cardDAV"


def test_ohne_erhobene_art_wird_nicht_geraten(modul, client):
    """`unknown` heisst „noch nicht erhoben" — nie „lokal"."""
    zeilen = client.get(f"{PREFIX}/sync/status", headers=_kopf()).json()
    assert zeilen[0]["container_type"] == "unknown"


def test_die_art_traegt_keine_kennung(modul, client):
    with modul.unit_of_work() as uow:
        SqliteSyncStateRepository(uow).upsert(ContactSyncState(
            provider_account_id=KONTO, container_identifier=CONTAINER,
            key_set_version="v1", mode="delta", cursor_token="T",
            cursor_taken_at="2026-07-31T09:00:00+00:00",
            container_type="cardDAV"))
    text = client.get(f"{PREFIX}/sync/status", headers=_kopf()).text
    for verboten in (CONTAINER, "ABAccount", KONTO):
        assert verboten not in text
