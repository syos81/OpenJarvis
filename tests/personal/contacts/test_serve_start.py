"""Serve-Start: Erholung unterbrochener Vorgänge und Routenregistrierung.

**Kontaktfrei.** Es wird keine App gestartet, kein Sidecar ausgeführt und kein
Kontakt gelesen — nur die Bootstrap-Reihenfolge und der Router geprüft.
"""

from __future__ import annotations

import pytest

from personaljarvis.base.approvals import owner_decision

from personaljarvis import attach
from personaljarvis.bootstrap import PersonalBootstrap
from personaljarvis.contacts.application import (
    ContactDraft,
    ContactsMutationService,
    CreateContact,
    MutationState,
)
from personaljarvis.contacts.domain.enums import InitiationContext
from personaljarvis.contacts.domain.models import ContactSyncState
from personaljarvis.contacts.lifecycle import ContactsModule
from personaljarvis.contacts.repositories.sqlite import SqliteSyncStateRepository

from .conftest import WORKSPACE, new_id

KONTO = "apple-system"
CONTAINER = "container-1"
MENSCH = "lukas"


class Absturz:
    """Bricht den Prozess mitten in Phase B ab — wie ein `kill -9`."""

    def apply(self, payload, **kw):
        raise SystemExit("Abbruch mitten im Sendevorgang")


def _unterbrochener_vorgang(db_path) -> str:
    """Hinterlässt genau eine verwaiste `executing`-Zeile und schließt zu."""
    modul = ContactsModule(db_path)
    modul.start()
    try:
        with modul.unit_of_work() as uow:
            SqliteSyncStateRepository(uow).upsert(ContactSyncState(
                provider_account_id=KONTO, container_identifier=CONTAINER,
                key_set_version="v1", mode="delta", cursor_token=None))
        from personaljarvis.contacts.domain.capabilities import ContactCapabilitySet

        dienst = ContactsMutationService(
            modul, Absturz(),
            capabilities=ContactCapabilitySet(create_supported=True))
        vorgang = dienst.prepare(CreateContact(
            mutation_id=new_id(), idempotency_key=new_id(),
            correlation_id=new_id(), actor=MENSCH, workspace_id=WORKSPACE,
            initiation_context=InitiationContext.USER_DIRECT,
            provider_account_id=KONTO, container_identifier=CONTAINER,
            draft=ContactDraft({"given_name": "Erholung"})))
        dienst.grant(vorgang.mutation_id, decision=owner_decision(MENSCH))
        with pytest.raises(SystemExit):
            dienst.execute(vorgang.mutation_id)
        return vorgang.mutation_id
    finally:
        modul.stop()


def _zustand(db_path, mutation_id: str) -> str:
    modul = ContactsModule(db_path)
    modul.start()
    try:
        with modul.unit_of_work() as uow:
            return uow.execute(
                "SELECT state FROM contacts_mutations WHERE mutation_id = ?",
                (mutation_id,)).fetchone()["state"]
    finally:
        modul.stop()


def test_serve_start_erholt_unterbrochene_vorgaenge(db_path):
    mutation_id = _unterbrochener_vorgang(db_path)
    assert _zustand(db_path, mutation_id) == MutationState.EXECUTING

    bootstrap = PersonalBootstrap(db_path)
    bootstrap.start()
    try:
        assert bootstrap.recovered_mutations == (mutation_id,)
    finally:
        bootstrap.stop()

    # Nie `failed_before_send`: die Sendephase ist unbekannt, nicht harmlos.
    assert _zustand(db_path, mutation_id) == MutationState.OUTCOME_UNKNOWN


def test_wiederholter_serve_start_erholt_nichts_mehr(db_path):
    _unterbrochener_vorgang(db_path)
    erster = PersonalBootstrap(db_path)
    erster.start()
    erholt = erster.recovered_mutations
    erster.stop()
    assert len(erholt) == 1

    zweiter = PersonalBootstrap(db_path)
    zweiter.start()
    try:
        assert zweiter.recovered_mutations == ()
    finally:
        zweiter.stop()


def test_serve_start_auf_gesunder_datenbank_erholt_nichts(db_path):
    bootstrap = PersonalBootstrap(db_path)
    bootstrap.start()
    try:
        assert bootstrap.recovered_mutations == ()
    finally:
        bootstrap.stop()


def test_erholung_laeuft_vor_der_ersten_anfrage(db_path, monkeypatch):
    """Die Reihenfolge ist die Zusicherung: Sperre → Erholung → Betrieb.

    Würde erst der Betrieb aufgenommen und dann erholt, könnte eine Anfrage
    einen verwaisten `executing`-Vorgang sehen und für sendbar halten.
    """
    _unterbrochener_vorgang(db_path)
    reihenfolge: list[str] = []

    from personaljarvis.contacts.application import mutation_service as ms

    echt = ms.ContactsMutationService.recover_interrupted

    def beobachtet(self):
        reihenfolge.append("recover")
        return echt(self)

    monkeypatch.setattr(ms.ContactsMutationService, "recover_interrupted",
                        beobachtet)

    class Zustand:
        pass

    class App:
        state = Zustand()

        def include_router(self, router):
            reihenfolge.append("router")

    app = App()
    attach(app, database_path=str(db_path))
    try:
        # Seit Modul 2 registriert `attach` zwei Router (Kontakte, Kalender).
        # Die Zusicherung ist unveraendert: die Erholung laeuft VOR jedem
        # davon — nicht, dass es genau einen gibt.
        assert reihenfolge[0] == "recover"
        assert "recover" not in reihenfolge[1:]
        assert set(reihenfolge[1:]) == {"router"}
        assert len(reihenfolge) >= 2
    finally:
        app.state.personal_bootstrap.stop()


def test_attach_registriert_die_kontakte_routen(db_path):
    """Über echte Anfragen belegt, nicht über Routen-Introspektion.

    `app.routes` ist kein verlässlicher Beleg: neuere FastAPI-Versionen
    kapseln eingebundene Router, und die Prüfung liefe still leer. Eine
    beantwortete Anfrage kann das nicht.
    """
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()
    attach(app, database_path=str(db_path))
    try:
        client = TestClient(app)
        kopf = {"X-Personal-Workspace": WORKSPACE}
        antwort = client.get("/v1/personal/contacts", headers=kopf)
        assert antwort.status_code == 200
        assert antwort.json() == {"items": [], "next_cursor": None,
                                  "has_more": False}
        faehig = client.get("/v1/personal/contacts/capabilities", headers=kopf)
        assert faehig.status_code == 200
        # Ohne echte Bridge bleibt der Schreibpfad geschlossen.
        assert faehig.json()["mutations_available"] is False
    finally:
        app.state.personal_bootstrap.stop()
