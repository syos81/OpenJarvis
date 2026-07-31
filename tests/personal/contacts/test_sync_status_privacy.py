"""Der Statusvertrag gibt keine rohen Providerkennungen heraus.

**Kontaktfrei.** Kein Sidecar, kein `CNContactStore`, keine Autorisierung —
ausschließlich temporäre SQLite-Datenbanken und der FastAPI-Testclient.

Anlass: bis zum 2026-07-31 trug jede Antwort von `GET /sync/status` die rohe
Apple-Containerkennung (`…:ABAccount`) und die Kontokennung im Klartext. Am
2026-07-31 landete genau diese Kennung dadurch in einer Terminalausgabe. Die
Tests hier halten die Grenze fest — sie prüfen den Vertrag, nicht die
Formulierung eines Feldnamens.
"""

from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from personaljarvis.contacts.api.redaction import (
    PROVIDER_TYPE_UNKNOWN,
    account_ref,
    container_ref,
    provider_type,
)
from personaljarvis.contacts.api.routes import (
    DEFAULT_WORKSPACE_HEADER,
    PREFIX,
    create_contacts_router,
)
from personaljarvis.contacts.application.queries import ContactsQueryService
from personaljarvis.contacts.domain.models import ContactSyncState
from personaljarvis.contacts.repositories.sqlite import SqliteSyncStateRepository
from personaljarvis.contacts.sync.audit import container_ref as audit_container_ref

from .conftest import WORKSPACE

#: Der Realfall: eine Apple-interne Kontoidentität als Containerkennung.
ROH_CONTAINER = "01234567-89AB-CDEF-0123-456789ABCDEF:ABAccount"
ROH_CONTAINER_ZWEI = "FEDCBA98-7654-3210-FEDC-BA9876543210:ABAccount"
ROH_KONTO = "apple-local"
CURSOR = "TOKEN-GEHEIM=="


@pytest.fixture
def client(module):
    app = FastAPI()
    app.include_router(create_contacts_router(module))
    return TestClient(app)


def _kopf() -> dict:
    return {DEFAULT_WORKSPACE_HEADER: WORKSPACE, "X-Personal-Actor": "lukas"}


def _zustand(module, *, container=ROH_CONTAINER, konto=ROH_KONTO,
             modus="delta", cursor=CURSOR, voll_diff_am=None):
    with module.unit_of_work() as uow:
        SqliteSyncStateRepository(uow).upsert(ContactSyncState(
            provider_account_id=konto, container_identifier=container,
            key_set_version="v1", mode=modus, cursor_token=cursor,
            cursor_taken_at="2026-07-31T09:00:00+00:00" if cursor else None,
            last_full_diff_at=voll_diff_am))


def _status(client) -> list[dict]:
    antwort = client.get(f"{PREFIX}/sync/status", headers=_kopf())
    assert antwort.status_code == 200
    return antwort.json()


# ═══ Die Grenze selbst ══════════════════════════════════════════════════════
def test_status_enthaelt_keine_rohe_containerkennung(client, module):
    _zustand(module)
    text = json.dumps(_status(client))
    assert ROH_CONTAINER not in text
    # Auch kein Teilstring: eine halbe UUID ist genauso eine Kontoidentität.
    assert "ABAccount" not in text
    assert "01234567-89AB-CDEF" not in text


def test_status_enthaelt_keine_rohe_kontokennung(client, module):
    _zustand(module)
    text = json.dumps(_status(client))
    assert ROH_KONTO not in text
    assert "provider_account_id" not in text
    assert "container_identifier" not in text


def test_status_enthaelt_kein_cursor_token(client, module):
    _zustand(module)
    text = json.dumps(_status(client))
    assert CURSOR not in text
    assert "TOKEN" not in text
    assert "cursor_token" not in text
    # Der Zeitstempel darf bleiben — er ist kein Token.
    assert _status(client)[0]["cursor_taken_at"] is not None


def test_status_enthaelt_keine_dateipfade(client, module):
    _zustand(module)
    text = json.dumps(_status(client))
    assert "/Users/" not in text
    assert ".openjarvis" not in text
    assert "jarvis.db" not in text


def test_status_feldmenge_ist_abgeschlossen(client, module):
    """Ein neues Feld muss bewusst hinzugefügt werden, nicht durchrutschen."""
    _zustand(module)
    assert set(_status(client)[0]) == {
        "provider_type", "account_ref", "container_ref", "mode",
        "circuit_state", "key_set_version", "cursor_present",
        "cursor_taken_at", "last_full_diff_at", "last_successful_run_at",
        "requires_full_diff", "updated_at"}


# ═══ Maskierung ═════════════════════════════════════════════════════════════
def test_maskierung_ist_deterministisch(client, module):
    _zustand(module)
    erst, zweit = _status(client)[0], _status(client)[0]
    assert erst["container_ref"] == zweit["container_ref"]
    assert erst["account_ref"] == zweit["account_ref"]
    assert erst["container_ref"] == container_ref(ROH_CONTAINER)
    assert erst["account_ref"] == account_ref(ROH_KONTO)


def test_verschiedene_container_ergeben_verschiedene_kuerzel(client, module):
    _zustand(module, container=ROH_CONTAINER)
    _zustand(module, container=ROH_CONTAINER_ZWEI)
    kuerzel = {z["container_ref"] for z in _status(client)}
    assert len(kuerzel) == 2


def test_kuerzel_ist_identisch_zur_auditspur(module):
    """Ein `C-…` bezeichnet in Bericht, Datenbank und API denselben Container."""
    assert container_ref(ROH_CONTAINER) == audit_container_ref(ROH_CONTAINER)


def test_kuerzel_ist_nicht_zurueckrechenbar():
    """Kein Teil der Kennung überlebt die Bildung."""
    kurz = container_ref(ROH_CONTAINER)
    assert kurz.startswith("C-") and len(kurz) == 8
    assert not any(teil in kurz for teil in ROH_CONTAINER.split("-"))
    assert account_ref(ROH_KONTO).startswith("A-")


def test_unbekanntes_konto_bekommt_gattung_ohne_teilstring():
    assert provider_type(ROH_KONTO) == "apple_contacts"
    assert provider_type("google-primary") == PROVIDER_TYPE_UNKNOWN
    assert "google" not in provider_type("google-primary")


# ═══ Abgeleitete Felder ═════════════════════════════════════════════════════
def test_cursor_present_statt_token(client, module):
    _zustand(module)
    assert _status(client)[0]["cursor_present"] is True
    _zustand(module, cursor=None, modus="full_diff_required")
    assert _status(client)[0]["cursor_present"] is False


def test_requires_full_diff_folgt_dem_cursorzustand(client, module):
    _zustand(module)
    assert _status(client)[0]["requires_full_diff"] is False
    _zustand(module, modus="full_diff_required")
    assert _status(client)[0]["requires_full_diff"] is True


def test_letzter_erfolgreicher_lauf_ist_der_juengere_stempel(client, module):
    _zustand(module, voll_diff_am="2026-07-31T11:00:00+00:00")
    assert _status(client)[0]["last_successful_run_at"] == (
        "2026-07-31T11:00:00+00:00")
    _zustand(module, voll_diff_am="2026-07-31T07:00:00+00:00")
    assert _status(client)[0]["last_successful_run_at"] == (
        "2026-07-31T09:00:00+00:00")


# ═══ Innen bleibt roh ═══════════════════════════════════════════════════════
def test_interne_sicht_behaelt_die_echten_kennungen(module):
    """Sonst fände die Sync-Schicht ihren eigenen Container nicht wieder."""
    _zustand(module)
    zustand = ContactsQueryService(module).sync_status()[0]
    assert zustand.container_identifier == ROH_CONTAINER
    assert zustand.provider_account_id == ROH_KONTO


def test_persistenz_speichert_die_echte_kennung(module):
    _zustand(module)
    with module.unit_of_work() as uow:
        zeile = uow.execute(
            "SELECT container_identifier FROM contacts_sync_state").fetchone()
    assert zeile["container_identifier"] == ROH_CONTAINER


def test_filter_nimmt_weiter_die_rohe_kennung(client, module):
    """Der Filter ist Eingabe eines Aufrufers, der die Kennung kennt."""
    _zustand(module)
    treffer = client.get(f"{PREFIX}/sync/status",
                         params={"provider_account_id": ROH_KONTO},
                         headers=_kopf()).json()
    assert len(treffer) == 1
    leer = client.get(f"{PREFIX}/sync/status",
                      params={"provider_account_id": "gibt-es-nicht"},
                      headers=_kopf()).json()
    assert leer == []


# ═══ Keine zweite Austrittsstelle ═══════════════════════════════════════════
def test_lauf_ergebnis_bleibt_aggregatfrei_von_kennungen():
    from personaljarvis.contacts.api.schemas import SyncRunOut

    assert "provider_account_id" not in SyncRunOut.model_fields
    assert "container_identifier" not in SyncRunOut.model_fields


def test_statusvertrag_kennt_die_alten_feldnamen_nicht_mehr():
    from personaljarvis.contacts.api.schemas import SyncStatusOut

    for feld in ("provider_account_id", "container_identifier", "has_cursor"):
        assert feld not in SyncStatusOut.model_fields
