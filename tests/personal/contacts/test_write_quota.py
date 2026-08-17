"""Das Kontingent einer Schreibfreigabe.

Die eine Aussage: Standing Write ist Einzelobjekt-Schreiben, nicht die Freigabe
einer beliebig grossen Mutationsklasse. Gemessen am 2026-08-17 liefen unter
einer Freigabe 25 von 25 Mutationen durch — das ist die Zahl, gegen die diese
Datei steht.

Kontaktfrei: Attrappenprovider, temporäre Datenbank.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone

import pytest

from personaljarvis.base.db.unit_of_work import UnitOfWork
from personaljarvis.contacts.application import ContactsMutationService
from personaljarvis.contacts.application.errors import WriteQuotaExhausted
from personaljarvis.contacts.application.write_quota import (
    QUOTA_PER_ACTIVATION,
    QuotaState,
    activation_id,
    quota_state,
)
from personaljarvis.contacts.application.write_release import (
    MODE_STANDING,
    WRITE_RELEASE_CAPABILITY,
    WRITE_RELEASE_CONTRACT_V2,
    read_write_release,
)

from .test_mutation_pipeline import (
    AttrappenProvider,
    MENSCH,
    _container_bekannt,
    _create,
)


def _freigabe_schreiben(tmp_path, *, granted_at="2026-08-17T12:00:00Z"):
    """Eine gültige Dauerfreigabe — dieselbe Urkunde, die das Produkt schreibt."""
    ordner = tmp_path / "personal"
    ordner.mkdir(exist_ok=True)
    os.chmod(ordner, 0o700)
    pfad = ordner / "contacts-write-release.json"
    pfad.write_text(json.dumps({
        "contract": WRITE_RELEASE_CONTRACT_V2,
        "capability": WRITE_RELEASE_CAPABILITY,
        "mode": MODE_STANDING,
        "operations": ["create", "update"],
        "granted_at": granted_at,
        "reason": "Im Produkt eingeschaltet",
    }), encoding="utf-8")
    os.chmod(pfad, 0o600)
    return pfad


def _dienst(module, pfad):
    return ContactsMutationService(module, AttrappenProvider(
        provider_identifier="raw-neu"), release_path=pfad)


def _einmal_schreiben(dienst):
    from personaljarvis.base.approvals import owner_decision_for_tests

    vorgang = dienst.prepare(_create())
    dienst.grant(vorgang.mutation_id, decision=owner_decision_for_tests(MENSCH))
    return dienst.execute(vorgang.mutation_id)


# ── Die Zahl ─────────────────────────────────────────────────────────────────
def test_der_elfte_schreibvorgang_wird_abgewiesen(module, tmp_path):
    pfad = _freigabe_schreiben(tmp_path)
    _container_bekannt(module)
    dienst = _dienst(module, pfad)

    for _ in range(QUOTA_PER_ACTIVATION):
        _einmal_schreiben(dienst)

    with pytest.raises(WriteQuotaExhausted):
        _einmal_schreiben(dienst)


def test_der_zehnte_laeuft_noch_durch(module, tmp_path):
    """Die Grenze liegt bei zehn, nicht bei neun."""
    pfad = _freigabe_schreiben(tmp_path)
    _container_bekannt(module)
    dienst = _dienst(module, pfad)
    for _ in range(QUOTA_PER_ACTIVATION):
        ergebnis = _einmal_schreiben(dienst)
    assert str(ergebnis.state) == "succeeded"


# ── Was nicht zählt ──────────────────────────────────────────────────────────
def test_eine_vorschau_kostet_nichts(module, tmp_path):
    pfad = _freigabe_schreiben(tmp_path)
    _container_bekannt(module)
    dienst = _dienst(module, pfad)

    for _ in range(20):
        dienst.prepare(_create())

    with UnitOfWork(module._factory if hasattr(module, "_factory")
                    else module.factory) as uow:
        stand = quota_state(uow, activation_id(read_write_release(pfad)))
    assert stand.used == 0


def test_eine_abgebrochene_freigabe_kostet_nichts(module, tmp_path):
    """Vorbereitet und abgelehnt — der Provider wurde nie erreicht."""
    pfad = _freigabe_schreiben(tmp_path)
    _container_bekannt(module)
    dienst = _dienst(module, pfad)

    for _ in range(15):
        vorgang = dienst.prepare(_create())
        dienst.reject(vorgang.mutation_id, decision_actor=MENSCH)

    # Und danach laufen die vollen zehn noch.
    for _ in range(QUOTA_PER_ACTIVATION):
        _einmal_schreiben(dienst)
    with pytest.raises(WriteQuotaExhausted):
        _einmal_schreiben(dienst)


# ── Der Wiederholungsversuch ─────────────────────────────────────────────────
def test_derselbe_vorgang_verbraucht_nicht_zweimal(module, tmp_path):
    """Idempotenz aus dem Schema, nicht aus Disziplin."""
    from personaljarvis.contacts.application.write_quota import claim_quota

    pfad = _freigabe_schreiben(tmp_path)
    aktivierung = activation_id(read_write_release(pfad))
    fabrik = module._factory if hasattr(module, "_factory") else module.factory

    with UnitOfWork(fabrik) as uow:
        for _ in range(5):
            stand = claim_quota(uow, aktivierung, "dieselbe-mutation",
                                at="2026-08-17T12:00:00Z")
    assert stand.used == 1


# ── Ein frisches Kontingent ──────────────────────────────────────────────────
def test_eine_neu_erteilte_freigabe_traegt_ein_frisches_kontingent(module,
                                                                   tmp_path):
    """Ausschalten und erneut einschalten heisst: andere Urkunde, neue Zahl."""
    pfad = _freigabe_schreiben(tmp_path, granted_at="2026-08-17T12:00:00Z")
    _container_bekannt(module)
    dienst = _dienst(module, pfad)
    for _ in range(QUOTA_PER_ACTIVATION):
        _einmal_schreiben(dienst)
    with pytest.raises(WriteQuotaExhausted):
        _einmal_schreiben(dienst)

    # Der Eigentuemer schaltet aus und wieder ein — im Produkt mit
    # Systemauthentifizierung. Die neue Urkunde traegt eine andere Zeit.
    _freigabe_schreiben(tmp_path, granted_at="2026-08-17T18:30:00Z")
    _einmal_schreiben(dienst)


def test_dieselbe_urkunde_ergibt_dieselbe_aktivierung(tmp_path):
    pfad = _freigabe_schreiben(tmp_path)
    erst = activation_id(read_write_release(pfad))
    zweit = activation_id(read_write_release(pfad))
    assert erst == zweit and erst is not None


def test_eine_andere_urkunde_ergibt_eine_andere_aktivierung(tmp_path):
    pfad = _freigabe_schreiben(tmp_path, granted_at="2026-08-17T12:00:00Z")
    erst = activation_id(read_write_release(pfad))
    _freigabe_schreiben(tmp_path, granted_at="2026-08-17T12:00:01Z")
    assert activation_id(read_write_release(pfad)) != erst


# ── Kein Rücksetzweg ─────────────────────────────────────────────────────────
def test_es_gibt_keine_funktion_die_das_kontingent_zuruecksetzt():
    """Ein Ruecksetzweg waere genau der Weg, den ein Agent ginge.

    Geprueft wird der Modul- und der Routenbestand: keine Funktion, die
    loescht oder zuruecksetzt, und keine HTTP-Route, die das Kontingent
    beruehrt.
    """
    import re
    from pathlib import Path

    wurzel = Path(__file__).resolve().parents[3] / "src" / "personaljarvis"
    quelle = (wurzel / "contacts/application/write_quota.py").read_text(
        encoding="utf-8")
    assert "DELETE FROM contacts_write_quota" not in quelle
    assert not re.search(r"def \w*(reset|zuruecksetz|clear)\w*", quelle)

    routen = (wurzel / "contacts/api/routes.py").read_text(encoding="utf-8")
    assert "contacts_write_quota" not in routen
    assert "claim_quota" not in routen


def test_der_zaehler_spricht_in_ganzen_saetzen():
    """Der sichtbare Stand — beide Faelle wortgleich zur Vorgabe."""
    assert QuotaState(used=3, limit=10).als_text() == (
        "7 von 10 Schreibvorgängen verfügbar")
    assert QuotaState(used=10, limit=10).als_text() == (
        "10 von 10 verwendet – erneut freigeben erforderlich")


def test_ohne_dauerfreigabe_gibt_es_kein_kontingent(tmp_path):
    """Dann traegt die befristete Freigabe den Vorgang, und ihre Grenze ist
    die Zeit."""
    assert activation_id(None) is None
