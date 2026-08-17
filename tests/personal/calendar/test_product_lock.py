"""Das Produktschloss des Kalenders — die Ebene über jeder Freigabe.

Diese Datei öffnet die Produktreife **nicht**. Sie ist damit die einzige
Kalender-Mutationssuite, die den Zustand prüft, in dem das Produkt heute
tatsächlich ausgeliefert wird.

Die eine Aussage, die hier bewiesen wird und ohne die das Schloss nur
behauptet wäre: *Eine formal einwandfreie, unverbrauchte Einzelfreigabe des
Eigentümers liegt vor — und es entsteht trotzdem kein Schreibauftrag.*

Kalenderfrei und sendefrei wie die Nachbarsuite: keine Bridge, kein EventKit,
kein Provider, ausschliesslich synthetische Werte in `tmp_path`.
"""

from __future__ import annotations

import pytest

from personaljarvis.base.db.unit_of_work import UnitOfWork
from personaljarvis.base.product_readiness import (
    PRODUCT_WRITE_READINESS,
    product_write_ready,
    readiness_reason,
)
from personaljarvis.calendar.domain import CanonicalCalendar
from personaljarvis.calendar.mutations.service import (
    CalendarMutationService,
    ProductWriteNotReady,
)
from personaljarvis.calendar.repositories import CalendarRepository

from .conftest import PROVIDER_ACCOUNT, WORKSPACE

KALENDER = "cal-lock"

FELDER = {
    "title": "Zahnarzt",
    "starts_at_utc": "2026-08-12T09:00:00Z",
    "ends_at_utc": "2026-08-12T10:00:00Z",
    "time_zone": "Europe/Berlin",
    "is_all_day": False,
    "notes": None,
    "location": None,
}


def _kalender_anlegen(factory) -> str:
    with UnitOfWork(factory) as uow:
        kalender_id, _ = CalendarRepository(uow).upsert_seen(
            CanonicalCalendar(
                id="", workspace_id=WORKSPACE,
                provider_account_id=PROVIDER_ACCOUNT,
                provider_calendar_id=KALENDER, display_name="Privat",
                calendar_type="calDAV", is_writable=True),
            seen_at="2026-08-09T00:00:00Z")
    return kalender_id


@pytest.fixture
def dienst(factory) -> CalendarMutationService:
    _kalender_anlegen(factory)
    # Backup-Nachweis ausdrücklich vorhanden: Sonst schlüge der Claim schon an
    # der nächsten Prüfung fehl und der Test bewiese das falsche Schloss.
    return CalendarMutationService(factory, backup_probe=lambda: True)


def _mutation_row(factory, mutation_id):
    with UnitOfWork(factory) as uow:
        return uow.connection.execute(
            "SELECT state FROM calendar_mutations WHERE mutation_id = ?",
            (mutation_id,)).fetchone()


# ── Der Produktzustand selbst ────────────────────────────────────────────────
def test_calendar_ist_im_produkt_nicht_schreibreif():
    """Der ausgelieferte Vorgabewert, ungefiltert gelesen."""
    assert product_write_ready("calendar") is False
    assert PRODUCT_WRITE_READINESS["calendar"].ready is False
    # Der Grund ist Pflicht, damit niemand das Schloss beim Aufräumen öffnet,
    # ohne zu wissen, wogegen es stand.
    assert "Occurrence" in readiness_reason("calendar")


def test_contacts_ist_schreibreif_und_bleibt_davon_unberuehrt():
    """Zwei Ebenen, zwei Fachbereiche: das Kalenderschloss sperrt Kontakte
    nicht mit."""
    assert product_write_ready("contacts") is True


def test_eine_unbekannte_faehigkeit_ist_nicht_reif():
    assert product_write_ready("kalendar") is False
    assert product_write_ready("") is False


# ── Die verlangte Aussage ────────────────────────────────────────────────────
def test_eine_gueltige_freigabe_reicht_trotzdem_nicht(dienst, factory):
    """Alles, was der Eigentümer tun kann, ist getan — und es reicht nicht.

    Vorbereitet, freigegeben, Backup-Nachweis vorhanden, Operation in der
    Position freigeschaltet, Freigabe unverbraucht. Der Claim scheitert
    ausschliesslich an der Produktreife.
    """
    vorgang = dienst.prepare_create(KALENDER, dict(FELDER))
    dienst.approve(vorgang.mutation_id, decision_actor="lukas")
    assert _mutation_row(factory, vorgang.mutation_id)["state"] == "approved"

    with pytest.raises(ProductWriteNotReady) as fehler:
        dienst.claim(vorgang.mutation_id)
    assert fehler.value.reason_code == "product_write_not_ready"

    # Fail-closed und ohne Nebenwirkung: die Freigabe ist **nicht** verbraucht,
    # der Vorgang bleibt für B2 unangetastet beanspruchbar.
    assert _mutation_row(factory, vorgang.mutation_id)["state"] == "approved"


def test_das_schloss_greift_vor_dem_backup_gate(factory):
    """Reihenfolge ist Aussage: unreif bleibt unreif, auch ohne Backup.

    Stünde das Backup-Gate zuerst, meldete ein unreifes Modul `backup_missing`
    — und jemand würde ein Backup besorgen statt die Reparatur zu bauen.
    """
    _kalender_anlegen(factory)
    ohne_backup = CalendarMutationService(factory, backup_probe=lambda: False)
    vorgang = ohne_backup.prepare_create(KALENDER, dict(FELDER))
    ohne_backup.approve(vorgang.mutation_id, decision_actor="lukas")
    with pytest.raises(ProductWriteNotReady):
        ohne_backup.claim(vorgang.mutation_id)
