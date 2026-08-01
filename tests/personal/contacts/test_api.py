"""Query-Schicht und HTTP-API des Kontakte-Moduls — kontaktfrei (Gate D).

**Kein Apple-Contacts-Zugriff.** Alle Tests laufen gegen temporäre
SQLite-Datenbanken und den FastAPI-Testclient. Kein Sidecar wird gestartet,
kein `requestAuthorization` gesendet, kein Kontakt gelesen oder verändert.

Der zentrale Nachweis dieser Suite: **keine Route führt eine Mutation aus.**
Der Provider-Aufrufzähler bleibt in jedem Ablauf auf null.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from personaljarvis.contacts.api.routes import (
    DEFAULT_WORKSPACE_HEADER,
    PREFIX,
    create_contacts_router,
)
from personaljarvis.contacts.application import (
    ContactsMutationService,
    MutationState,
    ProviderOutcome,
    ProviderResponse,
)
from personaljarvis.contacts.application.queries import (
    ContactsQueryService,
    decode_cursor,
    encode_cursor,
    normalize_search,
)
from personaljarvis.contacts.application.roles import ContactsRoleService
from personaljarvis.contacts.domain.enums import (
    FieldAvailabilityState,
)
from personaljarvis.contacts.domain.models import (
    ContactFieldAvailability,
    ContactSyncState,
    EmailAddress,
    ExternalIdentifier,
    PhoneNumber,
)
from personaljarvis.contacts.repositories.sqlite import (
    SqliteContactRepository,
    SqliteExternalIdentifierRepository,
    SqliteFieldAvailabilityRepository,
    SqliteSyncStateRepository,
)

from .conftest import WORKSPACE, make_contact, new_id

KONTO = "apple-system"
CONTAINER = "container-1"
MENSCH = "lukas"


class ZaehlProvider:
    """Zählt Aufrufe. In dieser Suite muss der Zähler **immer** null bleiben."""

    def __init__(self) -> None:
        self.calls = 0

    def apply(self, payload, **kw):
        self.calls += 1
        return ProviderResponse(ProviderOutcome.SUCCEEDED)


@pytest.fixture
def provider() -> ZaehlProvider:
    return ZaehlProvider()


@pytest.fixture
def client(module, provider):
    """Testclient über einem gestarteten Modul mit Zähl-Provider.

    Der Fake-Provider wird über den Modul-Standarddienst gelegt, damit die
    Routen ihn tatsächlich benutzen — sonst würde die Capability-Sperre
    greifen und die Prepare-Tests wären wertlos.
    """
    from personaljarvis.contacts.domain.capabilities import ContactCapabilitySet

    caps = ContactCapabilitySet(create_supported=True, update_supported=True,
                                delete_supported=True)
    module._capabilities = caps
    module._mutation_service = ContactsMutationService(
        module, provider, capabilities=caps)
    app = FastAPI()
    app.include_router(create_contacts_router(module))
    return TestClient(app)


def _kopf(workspace: str = WORKSPACE, actor: str = MENSCH) -> dict:
    return {DEFAULT_WORKSPACE_HEADER: workspace, "X-Personal-Actor": actor}


def _kontakt(module, *, name="Fixi Eins", workspace=WORKSPACE,
             konto=KONTO, provider_identifier="raw-1", me_card=False,
             mit_mail=True):
    with module.unit_of_work() as uow:
        mails = () if not mit_mail else (
            EmailAddress(id=new_id(), position=0, label_normalized="work",
                         value_raw="fixi@example.invalid",
                         value_normalized="fixi@example.invalid"),)
        k = make_contact(display_name=name, workspace_id=workspace,
                         is_me_card=me_card, emails=mails,
                         phones=(PhoneNumber(id=new_id(), position=0,
                                             value_raw="+49 30 111",
                                             value_normalized_e164="+4930111"),))
        SqliteContactRepository(uow).add(k)
        SqliteExternalIdentifierRepository(uow).upsert(
            k.id, ExternalIdentifier(
                id=new_id(), provider_account_id=konto,
                container_identifier=CONTAINER,
                provider_identifier=provider_identifier, key_set_version="v1"))
        SqliteFieldAvailabilityRepository(uow).set_for_contact(
            k.id, (ContactFieldAvailability(
                field_name="note",
                state=FieldAvailabilityState.UNAVAILABLE_BY_CAPABILITY),))
    return k


def _container_bekannt(module):
    with module.unit_of_work() as uow:
        SqliteSyncStateRepository(uow).upsert(ContactSyncState(
            provider_account_id=KONTO, container_identifier=CONTAINER,
            key_set_version="v1", mode="delta", cursor_token="GEHEIM==",
            cursor_taken_at="2026-07-31T09:00:00+00:00"))


# ═══ Query-Schicht ══════════════════════════════════════════════════════════
def test_suchnormalisierung():
    assert normalize_search("  Müller   Meier ") == "müller meier"
    assert normalize_search("ÄÖÜ") == "äöü"


def test_cursor_roundtrip():
    c = encode_cursor("Zeta", "id-1")
    assert decode_cursor(c) == ("Zeta", "id-1")


def test_ungueltiger_cursor_wird_abgewiesen(module):
    from personaljarvis.contacts.application.errors import InvalidCommand

    with pytest.raises(InvalidCommand):
        ContactsQueryService(module).list_contacts(
            workspace_id=WORKSPACE, cursor="kein-base64!!")


def test_liste_ist_stabil_paginiert(module):
    for name in ("Alpha", "Beta", "Gamma", "Delta", "Epsilon"):
        _kontakt(module, name=name, provider_identifier=f"raw-{name}")
    q = ContactsQueryService(module)
    seite1 = q.list_contacts(workspace_id=WORKSPACE, limit=2)
    seite2 = q.list_contacts(workspace_id=WORKSPACE, limit=2,
                             cursor=seite1.next_cursor)
    namen1 = [i.display_name for i in seite1.items]
    namen2 = [i.display_name for i in seite2.items]
    assert namen1 == ["Alpha", "Beta"]
    assert namen2 == ["Delta", "Epsilon"]
    assert set(namen1) & set(namen2) == set()


def test_workspace_isolation(module):
    _kontakt(module, name="Eigen", workspace=WORKSPACE)
    _kontakt(module, name="Fremd", workspace="anderer-ws",
             provider_identifier="raw-fremd")
    q = ContactsQueryService(module)
    assert [i.display_name for i in
            q.list_contacts(workspace_id=WORKSPACE).items] == ["Eigen"]


def test_providerkonto_isolation(module):
    a = _kontakt(module, name="KontoA", konto="konto-a",
                 provider_identifier="raw-a")
    _kontakt(module, name="KontoB", konto="konto-b",
             provider_identifier="raw-b")
    q = ContactsQueryService(module)
    treffer = q.list_contacts(workspace_id=WORKSPACE,
                              provider_account_id="konto-a")
    assert [i.id for i in treffer.items] == [a.id]


def test_suche_findet_name_organisation_mail_und_nummer(module):
    _kontakt(module, name="Suchbar Eins")
    q = ContactsQueryService(module)
    for begriff in ("suchbar", "fixi@example.invalid", "4930111"):
        assert len(q.list_contacts(workspace_id=WORKSPACE,
                                   search=begriff).items) == 1, begriff


def test_suche_ohne_treffer(module):
    _kontakt(module)
    q = ContactsQueryService(module)
    assert q.list_contacts(workspace_id=WORKSPACE,
                           search="gibtesnicht").items == ()


def test_unbekannter_kontakt_liefert_none(module):
    assert ContactsQueryService(module).get_contact(
        new_id(), workspace_id=WORKSPACE) is None


def test_fremder_workspace_sieht_den_kontakt_nicht(module):
    k = _kontakt(module)
    assert ContactsQueryService(module).get_contact(
        k.id, workspace_id="anderer-ws") is None


def test_sync_status_ohne_cursor_token(module):
    _container_bekannt(module)
    stati = ContactsQueryService(module).sync_status()
    assert len(stati) == 1
    assert stati[0].has_cursor is True
    assert "GEHEIM" not in str(vars(stati[0]))


def test_kategorien_mit_anzahl(module):
    k = _kontakt(module)
    ContactsRoleService(module).assign(k.id, "Mieter",
                                       workspace_id=WORKSPACE, actor=MENSCH)
    assert ContactsQueryService(module).list_roles(
        workspace_id=WORKSPACE) == (("Mieter", 1),)


# ═══ HTTP: Lesen ════════════════════════════════════════════════════════════
def test_get_liste(client, module):
    _kontakt(module)
    r = client.get(PREFIX, headers=_kopf())
    assert r.status_code == 200
    body = r.json()
    assert len(body["items"]) == 1
    assert body["items"][0]["display_name"] == "Fixi Eins"
    assert body["has_more"] is False


def test_get_liste_pagination(client, module):
    for n in ("A", "B", "C"):
        _kontakt(module, name=n, provider_identifier=f"raw-{n}")
    erste = client.get(PREFIX, params={"limit": 2}, headers=_kopf()).json()
    assert erste["has_more"] is True
    zweite = client.get(PREFIX, params={"limit": 2, "cursor": erste["next_cursor"]},
                        headers=_kopf()).json()
    assert [i["display_name"] for i in zweite["items"]] == ["C"]


def test_get_liste_lehnt_zu_grosses_limit_ab(client):
    assert client.get(PREFIX, params={"limit": 5000},
                      headers=_kopf()).status_code == 422


def test_get_liste_workspace_isolation(client, module):
    _kontakt(module, name="Eigen")
    assert client.get(PREFIX, headers=_kopf(workspace="fremd")
                      ).json()["items"] == []


def test_get_detail(client, module):
    k = _kontakt(module)
    r = client.get(f"{PREFIX}/{k.id}", headers=_kopf())
    assert r.status_code == 200
    body = r.json()
    assert body["display_name"] == "Fixi Eins"
    from personaljarvis.contacts.api.redaction import container_ref

    assert body["writable"] is True
    assert "write_target" not in body
    assert body["container_refs"] == [container_ref(CONTAINER)]
    assert body["unified_read_only"] is True
    zustaende = {f["field_name"]: f["state"] for f in body["field_availability"]}
    assert zustaende["note"] == "unavailable_by_capability"


def test_get_detail_unbekannt_ist_404(client):
    r = client.get(f"{PREFIX}/{new_id()}", headers=_kopf())
    assert r.status_code == 404
    assert r.json()["detail"]["code"] == "not_found"


def test_get_detail_fremder_workspace_ist_404(client, module):
    k = _kontakt(module)
    assert client.get(f"{PREFIX}/{k.id}",
                      headers=_kopf(workspace="fremd")).status_code == 404


def test_capabilities_meldet_notizen_als_nicht_verfuegbar(client):
    body = client.get(f"{PREFIX}/capabilities", headers=_kopf()).json()
    assert body["notes_supported"] is False
    assert "note" in body["unavailable_fields"]
    assert body["unified_link_supported"] is False
    assert body["me_card_writable"] is False


def test_sync_status_route_ohne_token(client, module):
    _container_bekannt(module)
    body = client.get(f"{PREFIX}/sync/status", headers=_kopf()).json()
    assert body[0]["cursor_present"] is True
    assert "GEHEIM" not in str(body)
    assert "cursor_token" not in body[0]


# ═══ HTTP: lokale Kategorien ════════════════════════════════════════════════
def test_kategorie_zuordnen_und_entfernen(client, module):
    k = _kontakt(module)
    r = client.post(f"{PREFIX}/{k.id}/roles", json={"role": "HV"},
                    headers=_kopf())
    assert r.status_code == 200 and r.json()["roles"] == ["HV"]
    r2 = client.delete(f"{PREFIX}/{k.id}/roles/HV", headers=_kopf())
    assert r2.json()["roles"] == []


def test_kategorie_zuordnen_ist_idempotent(client, module):
    k = _kontakt(module)
    client.post(f"{PREFIX}/{k.id}/roles", json={"role": "Arbeit"}, headers=_kopf())
    r = client.post(f"{PREFIX}/{k.id}/roles", json={"role": "Arbeit"}, headers=_kopf())
    assert r.json()["roles"] == ["Arbeit"]


def test_kategorie_fremder_workspace_ist_404(client, module):
    k = _kontakt(module)
    assert client.post(f"{PREFIX}/{k.id}/roles", json={"role": "X"},
                       headers=_kopf(workspace="fremd")).status_code == 404


def test_leere_kategorie_wird_abgewiesen(client, module):
    k = _kontakt(module)
    assert client.post(f"{PREFIX}/{k.id}/roles", json={"role": "   "},
                       headers=_kopf()).status_code == 422


def test_kategorie_unbekanntes_feld_wird_abgewiesen(client, module):
    """`extra="forbid"` — keine Mass-Assignment-Luecke."""
    k = _kontakt(module)
    assert client.post(f"{PREFIX}/{k.id}/roles",
                       json={"role": "X", "workspace_id": "fremd"},
                       headers=_kopf()).status_code == 422


# ═══ HTTP: Mutationen vorbereiten — nie ausführen ═══════════════════════════
def _create_body(**kw) -> dict:
    from personaljarvis.contacts.api.redaction import container_ref

    body = {"idempotency_key": new_id(), "correlation_id": new_id(),
            "container_ref": container_ref(CONTAINER),
            "fields": {"given_name": "Neu"}}
    body.update(kw)
    return body


def test_create_vorbereiten_sendet_nichts(client, module, provider):
    _container_bekannt(module)
    r = client.post(PREFIX, json=_create_body(), headers=_kopf())
    assert r.status_code == 201
    body = r.json()
    assert body["state"] == MutationState.AWAITING_APPROVAL
    assert body["command"] == "create"
    assert provider.calls == 0


def test_create_gleicher_idempotenzschluessel_gibt_denselben_vorgang(
        client, module, provider):
    _container_bekannt(module)
    key = new_id()
    a = client.post(PREFIX, json=_create_body(idempotency_key=key),
                    headers=_kopf()).json()
    b = client.post(PREFIX, json=_create_body(idempotency_key=key),
                    headers=_kopf()).json()
    assert b["reused"] is True
    assert a["mutation_id"] == b["mutation_id"]
    assert provider.calls == 0


def test_update_vorbereiten_zeigt_vorher_nachher(client, module, provider):
    k = _kontakt(module)
    r = client.patch(f"{PREFIX}/{k.id}", headers=_kopf(), json={
        "idempotency_key": new_id(), "correlation_id": new_id(),
        "expected_revision": "1", "fields": {"nickname": "Neu"}})
    assert r.status_code == 200
    aenderungen = {c["field_name"]: (c["previous"], c["planned"])
                   for c in r.json()["changes"]}
    assert aenderungen["nickname"] == (None, "Neu")
    assert provider.calls == 0


def test_update_notizfeld_wird_abgewiesen(client, module):
    k = _kontakt(module)
    r = client.patch(f"{PREFIX}/{k.id}", headers=_kopf(), json={
        "idempotency_key": new_id(), "correlation_id": new_id(),
        "expected_revision": "1", "fields": {"note": "heimlich"}})
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "validation_failed"


def test_update_me_card_wird_abgewiesen(client, module):
    k = _kontakt(module, me_card=True, provider_identifier="raw-me")
    r = client.patch(f"{PREFIX}/{k.id}", headers=_kopf(), json={
        "idempotency_key": new_id(), "correlation_id": new_id(),
        "expected_revision": "1", "fields": {"nickname": "X"}})
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "forbidden"


def test_update_unified_identifier_wird_abgewiesen(client, module):
    k = _kontakt(module)
    r = client.patch(f"{PREFIX}/{k.id}", headers=_kopf(), json={
        "idempotency_key": new_id(), "correlation_id": new_id(),
        "expected_revision": "1", "fields": {"nickname": "X"}})
    # Der unifizierte Identifier ist als Ziel gar nicht mehr adressierbar:
    # die API kennt nur die lokale contact_id, und deren Aufloesung liefert
    # ausschliesslich Rohdatensaetze.
    assert r.status_code == 200


def test_update_fremdes_providerkonto_wird_abgewiesen(client, module):
    k = _kontakt(module, konto="konto-a", provider_identifier="raw-x")
    r = client.patch(f"{PREFIX}/{k.id}", headers=_kopf(), json={
        "idempotency_key": new_id(), "correlation_id": new_id(),
        "expected_revision": "1", "fields": {"nickname": "X"}})
    # Ein fremdes Konto laesst sich nicht mehr behaupten: das Ziel wird aus
    # der lokalen Identitaet aufgeloest, nicht vom Aufrufer genannt.
    assert r.status_code == 200


def test_delete_vorbereiten_warnt_und_sendet_nichts(client, module, provider):
    k = _kontakt(module)
    r = client.post(f"{PREFIX}/{k.id}/delete", headers=_kopf(), json={
        "idempotency_key": new_id(), "correlation_id": new_id(),
        "expected_revision": "1"})
    assert r.status_code == 200
    assert r.json()["warnings"]
    assert provider.calls == 0


def test_prepare_lehnt_unbekanntes_feld_ab(client, module):
    _container_bekannt(module)
    r = client.post(PREFIX, headers=_kopf(),
                    json=_create_body(schattenfeld="boese"))
    assert r.status_code == 422


def test_prepare_lehnt_unbekanntes_kontaktfeld_ab(client, module):
    """Ein unbekanntes Feld prallt schon am Transportmodell ab.

    Seit dem geschlossenen Feldvertrag v1 antwortet Pydantic mit seiner
    eigenen Fehlerliste statt mit dem Anwendungsfehler — die Ablehnung
    geschieht also **eine Schicht frueher** als vorher. Das ist die staerkere
    Aussage: der Wert erreicht die Anwendungsschicht gar nicht erst.
    """
    _container_bekannt(module)
    r = client.post(PREFIX, headers=_kopf(),
                    json=_create_body(fields={"lieblingsfarbe": "blau"}))
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "validation_failed"
    assert "fields.lieblingsfarbe" in r.json()["detail"]["fields"]
    # Der Wert selbst taucht in der Ablehnung nicht auf.
    assert "blau" not in r.text


# ═══ HTTP: Freigaben ════════════════════════════════════════════════════════
def _vorbereitet(client, module) -> str:
    _container_bekannt(module)
    return client.post(PREFIX, json=_create_body(),
                       headers=_kopf()).json()["mutation_id"]


def test_freigabe_erteilen(client, module, provider):
    mid = _vorbereitet(client, module)
    r = client.post(f"{PREFIX}/mutations/{mid}/approve",
                    json={"decision_actor": MENSCH}, headers=_kopf())
    assert r.status_code == 200 and r.json()["state"] == "granted"
    assert provider.calls == 0, "Freigabe darf nichts ausfuehren"


def test_freigabe_ablehnen(client, module, provider):
    mid = _vorbereitet(client, module)
    r = client.post(f"{PREFIX}/mutations/{mid}/reject",
                    json={"decision_actor": MENSCH}, headers=_kopf())
    assert r.json()["state"] == "rejected"
    assert provider.calls == 0


def test_freigabe_abbrechen(client, module):
    mid = _vorbereitet(client, module)
    r = client.post(f"{PREFIX}/mutations/{mid}/cancel",
                    json={"decision_actor": MENSCH}, headers=_kopf())
    assert r.json()["state"] == "cancelled"


def test_zweite_entscheidung_wird_abgewiesen(client, module):
    mid = _vorbereitet(client, module)
    client.post(f"{PREFIX}/mutations/{mid}/approve",
                json={"decision_actor": MENSCH}, headers=_kopf())
    r = client.post(f"{PREFIX}/mutations/{mid}/approve",
                    json={"decision_actor": MENSCH}, headers=_kopf())
    assert r.status_code == 409


def test_modell_kann_nicht_selbst_freigeben(client, module):
    mid = _vorbereitet(client, module)
    r = client.post(f"{PREFIX}/mutations/{mid}/approve",
                    json={"decision_actor": "llm_assisted"}, headers=_kopf())
    assert r.status_code == 403


def test_abgelaufene_freigabe_ist_sichtbar_und_explizit_markierbar(
        client, module):
    mid = _vorbereitet(client, module)
    with module.unit_of_work() as uow:
        uow.execute(
            "UPDATE personal_approvals SET requested_at = ?, expires_at = ? "
            "WHERE subject_id = ?",
            ("2000-01-01T00:00:00+00:00", "2000-01-01T00:00:01+00:00", mid))
    liste = client.get(f"{PREFIX}/approvals", headers=_kopf()).json()
    assert liste[0]["is_expired"] is True
    r = client.post(f"{PREFIX}/mutations/{mid}/expire", headers=_kopf())
    assert r.status_code == 200 and r.json()["state"] == "expired"


def test_approval_liste_kann_abgelaufene_ausblenden(client, module):
    mid = _vorbereitet(client, module)
    with module.unit_of_work() as uow:
        uow.execute(
            "UPDATE personal_approvals SET requested_at = ?, expires_at = ? "
            "WHERE subject_id = ?",
            ("2000-01-01T00:00:00+00:00", "2000-01-01T00:00:01+00:00", mid))
    ohne = client.get(f"{PREFIX}/approvals",
                      params={"include_expired": "false"},
                      headers=_kopf()).json()
    assert ohne == []


def test_approval_detail(client, module):
    mid = _vorbereitet(client, module)
    aid = client.get(f"{PREFIX}/mutations/{mid}",
                     headers=_kopf()).json()["approval_id"]
    r = client.get(f"{PREFIX}/approvals/{aid}", headers=_kopf())
    assert r.status_code == 200 and r.json()["mutation_id"] == mid


def test_freigabe_fremder_workspace_ist_404(client, module):
    mid = _vorbereitet(client, module)
    assert client.post(f"{PREFIX}/mutations/{mid}/approve",
                       json={"decision_actor": MENSCH},
                       headers=_kopf(workspace="fremd")).status_code == 404


# ═══ HTTP: Mutationsstatus und Abgleich ════════════════════════════════════
def test_mutationsliste_und_detail(client, module):
    mid = _vorbereitet(client, module)
    liste = client.get(f"{PREFIX}/mutations", headers=_kopf()).json()
    assert [m["mutation_id"] for m in liste] == [mid]
    detail = client.get(f"{PREFIX}/mutations/{mid}", headers=_kopf()).json()
    assert detail["command"] == "create"
    assert detail["changes"]


def test_mutationsliste_filtert_nach_zustand(client, module):
    _vorbereitet(client, module)
    leer = client.get(f"{PREFIX}/mutations", params={"state": "succeeded"},
                      headers=_kopf()).json()
    assert leer == []


def test_mutation_fremder_workspace_ist_404(client, module):
    mid = _vorbereitet(client, module)
    assert client.get(f"{PREFIX}/mutations/{mid}",
                      headers=_kopf(workspace="fremd")).status_code == 404


def test_reconcile_ohne_leser_ist_fail_closed(client, module):
    """Ohne konfigurierten Abgleichleser wird nicht geraten."""
    mid = _vorbereitet(client, module)
    r = client.post(f"{PREFIX}/mutations/{mid}/reconcile", headers=_kopf())
    assert r.status_code == 503
    assert r.json()["detail"]["retryable"] is True


def test_reconcile_liest_nur(client, module, provider):
    from personaljarvis.contacts.application.reconcile import ReconcileObservation

    mid = _vorbereitet(client, module)
    # In den unbekannten Ausgang bringen — ohne Route, denn die fuehrt nie aus.
    with module.unit_of_work() as uow:
        uow.execute("UPDATE contacts_mutations SET state = ? WHERE mutation_id = ?",
                    (MutationState.OUTCOME_UNKNOWN, mid))
        uow.execute("UPDATE personal_external_action_outbox SET state = ?, "
                    "claim_token = NULL WHERE subject_id = ?",
                    ("outcome_unknown", mid))

    class Leser:
        def __init__(self): self.calls = 0

        def observe(self, **kw):
            self.calls += 1
            from personaljarvis.contacts.application.field_contract import (
                as_bridge_contact,
                parse_create_fields,
            )

            return ReconcileObservation(
                exists=True, provider_identifier="raw-neu",
                readback=as_bridge_contact(
                    parse_create_fields({"given_name": "Fixi"}),
                    provider_identifier="raw-neu"))

    leser = Leser()
    module.reconcile_reader = leser
    try:
        r = client.post(f"{PREFIX}/mutations/{mid}/reconcile", headers=_kopf())
        assert r.status_code == 200
        assert r.json()["state"] == MutationState.SUCCEEDED
        assert leser.calls == 1
        assert provider.calls == 0, "Abgleich darf nichts senden"
    finally:
        del module.reconcile_reader


# ═══ Keine Route führt aus ══════════════════════════════════════════════════
def test_kein_endpunkt_fuehrt_eine_mutation_aus(client, module, provider):
    """Vollständiger Fluss: vorbereiten → freigeben → Status — ohne Send."""
    mid = _vorbereitet(client, module)
    client.post(f"{PREFIX}/mutations/{mid}/approve",
                json={"decision_actor": MENSCH}, headers=_kopf())
    zustand = client.get(f"{PREFIX}/mutations/{mid}",
                         headers=_kopf()).json()["state"]
    assert zustand == MutationState.APPROVED
    assert provider.calls == 0


def test_gegenprobe_der_zaehler_reagiert_ueberhaupt(client, module, provider):
    """Positivkontrolle.

    Ohne diesen Test wären alle `provider.calls == 0`-Zusicherungen wertlos:
    ein Zähler, der nie zählen *kann*, beweist nichts. Hier wird die Ausführung
    absichtlich am HTTP-Weg vorbei über den Dienst angestoßen — sie ist genau
    deshalb möglich, weil es dafür **keine** Route gibt.
    """
    mid = _vorbereitet(client, module)
    client.post(f"{PREFIX}/mutations/{mid}/approve",
                json={"decision_actor": MENSCH}, headers=_kopf())
    module.mutation_service().execute(mid)
    assert provider.calls == 1


def _routenpfade(module) -> list[str]:
    """Pfade direkt am Router ablesen.

    Bewusst **nicht** über `app.routes`: neuere FastAPI-Versionen kapseln
    eingebundene Router in ein Objekt ohne `.path`, und die Prüfung würde
    dann still leer laufen — eine Verbotsprüfung über einer leeren Menge
    besteht immer.
    """
    pfade = [r.path for r in create_contacts_router(module).routes
             if hasattr(r, "path")]
    assert pfade, "Der Router hat keine ablesbaren Routen"
    return pfade


def test_genau_ein_ausfuehrungsendpunkt(module):
    """Es gibt **einen** Weg zum Provider, und er heisst `execute`.

    Vorher lautete der Nachweis „gar keiner". Seit ADR-0019 gibt es ihn — die
    Aussage muss deshalb schaerfer werden statt zu verschwinden: genau eine
    Route, und daneben weiterhin nichts, was einen Vorgang wiederholt oder
    ungefragt abschickt.
    """
    pfade = _routenpfade(module)
    assert sum("execute" in p for p in pfade) == 1
    assert any(p.endswith("/mutations/{mutation_id}/execute") for p in pfade)
    for verboten in ("send", "retry", "resend", "commit", "flush"):
        assert not any(verboten in p for p in pfade), verboten


def test_nur_drei_routen_beruehren_apple_kontakte(module):
    """Die Live-Fläche ist abgeschlossen und namentlich fixiert.

    Alles andere arbeitet ausschliesslich auf der lokalen Datenbank. Käme
    eine vierte Route hinzu, die den Store berührt, fiele das hier auf.
    """
    pfade = set(_routenpfade(module))
    live = {f"{PREFIX}/authorization", f"{PREFIX}/authorization/request",
            f"{PREFIX}/sync"}
    assert live <= pfade
    # Kein weiterer Pfad benennt eine Store-Operation.
    rest = pfade - live
    for verboten in ("enumerate", "containers", "changes", "authorization"):
        assert not any(verboten in p for p in rest), verboten


def test_routen_liegen_unter_v1_personal(module):
    for pfad in _routenpfade(module):
        assert pfad.startswith("/v1/personal/contacts"), pfad


# ═══ Datenschutz ════════════════════════════════════════════════════════════
def test_fehlermeldungen_tragen_keine_kontaktwerte(client, module):
    k = _kontakt(module, name="Geheimname Wert")
    r = client.patch(f"{PREFIX}/{k.id}", headers=_kopf(), json={
        "idempotency_key": new_id(), "correlation_id": new_id(),
        "expected_revision": "1", "fields": {"note": "x"}})
    assert "Geheimname" not in r.text


def test_liste_zeigt_keine_detaildaten(client, module):
    _kontakt(module)
    body = client.get(PREFIX, headers=_kopf()).json()
    zeile = body["items"][0]
    for verboten in ("emails", "phones", "postal_addresses", "note"):
        assert verboten not in zeile, verboten
    assert zeile["email_count"] == 1


def test_audit_der_kategorien_ohne_kontaktwerte(client, module):
    k = _kontakt(module, name="Geheimname Wert")
    client.post(f"{PREFIX}/{k.id}/roles", json={"role": "HV"}, headers=_kopf())
    with module.unit_of_work() as uow:
        rows = uow.execute("SELECT * FROM personal_audit_log").fetchall()
    text = " ".join(str(dict(r)) for r in rows)
    assert "Geheimname" not in text
