"""Der Freigabevertrag — befristet, dauerhaft, und die Grenze dazwischen.

Diese Datei prüft genau die Eigenschaften, deren Verletzung einen
Schreibpfad in fremde Kontaktdaten öffnen würde, ohne dass jemand es merkt:

* Eine **befristete** Freigabe bleibt befristet. Kein Zusatzfeld macht aus
  ihr nachträglich eine dauerhafte.
* Eine **dauerhafte** Freigabe überlebt einen Neustart — aber sie ist nicht
  universell: sie nennt Fähigkeit und Operationen so einzeln wie die
  befristete.
* Eine Freigabe gilt für **eine** Fähigkeit. Wer für eine andere fragt,
  bekommt nichts.

Kalenderfrei und kontaktfrei: ausschliesslich erfundene Werte in `tmp_path`.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone

import pytest

from personaljarvis.contacts.application.write_release import (
    MODE_STANDING,
    MODE_TEMPORARY,
    WRITE_RELEASE_CAPABILITY,
    WRITE_RELEASE_CONTRACT,
    WRITE_RELEASE_CONTRACT_V2,
    read_write_release,
)

JETZT = datetime(2026, 8, 17, 12, 0, tzinfo=timezone.utc)
#: „Neustart" heisst hier: dieselbe Datei, viel später noch einmal gelesen.
VIEL_SPAETER = JETZT + timedelta(days=97)


@pytest.fixture
def ort(tmp_path):
    """Ein 0700-Verzeichnis, wie der Vertrag es verlangt."""
    verzeichnis = tmp_path / "personal"
    verzeichnis.mkdir()
    os.chmod(verzeichnis, 0o700)
    return verzeichnis / "contacts-write-release.json"


def schreiben(pfad, dokument, *, modus=0o600):
    pfad.write_text(json.dumps(dokument), encoding="utf-8")
    os.chmod(pfad, modus)
    return pfad


def befristet(*, stunden=1, operations=("create",), **rest):
    dokument = {
        "contract": WRITE_RELEASE_CONTRACT,
        "operations": list(operations),
        "expires_at": (JETZT + timedelta(hours=stunden)).isoformat(),
        "reason": "Testlauf",
    }
    dokument.update(rest)
    return dokument


def dauerhaft(*, operations=("create",), **rest):
    dokument = {
        "contract": WRITE_RELEASE_CONTRACT_V2,
        "capability": WRITE_RELEASE_CAPABILITY,
        "mode": MODE_STANDING,
        "operations": list(operations),
        "granted_at": JETZT.isoformat(),
        "reason": "Im Produkt eingeschaltet",
    }
    dokument.update(rest)
    return dokument


# ── v1 bleibt, was es war ────────────────────────────────────────────────────
def test_die_befristete_freigabe_gilt_unveraendert(ort):
    freigabe = read_write_release(schreiben(ort, befristet()), jetzt=JETZT)
    assert freigabe is not None
    assert freigabe.mode == MODE_TEMPORARY
    assert freigabe.capability == WRITE_RELEASE_CAPABILITY
    assert freigabe.erlaubt("create") and not freigabe.erlaubt("delete")


def test_die_befristete_freigabe_laeuft_weiterhin_ab(ort):
    schreiben(ort, befristet(stunden=1))
    assert read_write_release(ort, jetzt=JETZT) is not None
    assert read_write_release(ort, jetzt=JETZT + timedelta(hours=2)) is None


def test_eine_befristete_freigabe_ueber_vier_stunden_gilt_nicht(ort):
    assert read_write_release(schreiben(ort, befristet(stunden=5)),
                              jetzt=JETZT) is None


# ── Keine Umdeutung: der Kern der Persistenz ─────────────────────────────────
def test_ein_v1_dokument_wird_nie_zur_dauerfreigabe(ort):
    """Der eigentliche Schutz. Ein alter, befristeter Grant bleibt befristet —
    auch wenn jemand ihm das Wort `standing` hinzufügt."""
    schreiben(ort, befristet(stunden=1, mode=MODE_STANDING))
    freigabe = read_write_release(ort, jetzt=JETZT)
    assert freigabe is not None
    assert freigabe.mode == MODE_TEMPORARY
    # Und der Ablauf greift trotz des Wortes weiterhin.
    assert read_write_release(ort, jetzt=VIEL_SPAETER) is None


def test_ein_v1_dokument_ohne_ablauf_gilt_nicht(ort):
    dokument = befristet(mode=MODE_STANDING)
    dokument.pop("expires_at")
    assert read_write_release(schreiben(ort, dokument), jetzt=JETZT) is None


# ── v2 dauerhaft ─────────────────────────────────────────────────────────────
def test_die_dauerfreigabe_ueberlebt_den_neustart(ort):
    """Dieselbe Datei, viel später gelesen: sie gilt weiterhin."""
    schreiben(ort, dauerhaft())
    for zeitpunkt in (JETZT, JETZT + timedelta(hours=5), VIEL_SPAETER):
        freigabe = read_write_release(ort, jetzt=zeitpunkt)
        assert freigabe is not None, zeitpunkt
        assert freigabe.mode == MODE_STANDING
        assert freigabe.expires_at is None


def test_die_dauerfreigabe_ist_nicht_universell(ort):
    """Dauerhaft heisst nicht: alles. Sie nennt ihre Operationen einzeln."""
    freigabe = read_write_release(schreiben(ort, dauerhaft(
        operations=("create", "update"))), jetzt=VIEL_SPAETER)
    assert freigabe is not None
    assert freigabe.erlaubt("create") and freigabe.erlaubt("update")
    assert not freigabe.erlaubt("delete")


def test_eine_dauerfreigabe_mit_ablauf_gilt_nicht(ort):
    """Zwei widersprechende Aussagen — also gilt keine."""
    assert read_write_release(
        schreiben(ort, dauerhaft(expires_at=(JETZT + timedelta(hours=1)).isoformat())),
        jetzt=JETZT) is None


def test_eine_dauerfreigabe_ohne_ausstellungszeit_gilt_nicht(ort):
    dokument = dauerhaft()
    dokument.pop("granted_at")
    assert read_write_release(schreiben(ort, dokument), jetzt=JETZT) is None


def test_eine_zurueckgenommene_dauerfreigabe_gilt_nicht(ort):
    assert read_write_release(
        schreiben(ort, dauerhaft(revoked_at=JETZT.isoformat())),
        jetzt=VIEL_SPAETER) is None


def test_ein_unbekannter_modus_gilt_nicht(ort):
    assert read_write_release(schreiben(ort, dauerhaft(mode="forever")),
                              jetzt=JETZT) is None


def test_v2_befristet_verhaelt_sich_wie_v1(ort):
    dokument = dauerhaft(mode=MODE_TEMPORARY,
                         expires_at=(JETZT + timedelta(hours=1)).isoformat())
    dokument.pop("granted_at")
    schreiben(ort, dokument)
    assert read_write_release(ort, jetzt=JETZT) is not None
    assert read_write_release(ort, jetzt=JETZT + timedelta(hours=2)) is None


# ── Die Fähigkeitsbindung ────────────────────────────────────────────────────
def test_eine_kontaktfreigabe_oeffnet_keine_andere_faehigkeit(ort):
    """Der Punkt der ganzen Uebung: Contacts gibt nie Calendar frei."""
    schreiben(ort, dauerhaft())
    assert read_write_release(ort, jetzt=JETZT) is not None
    assert read_write_release(ort, jetzt=JETZT, capability="calendar") is None


def test_eine_freigabe_mit_fremder_faehigkeit_gilt_nicht(ort):
    assert read_write_release(schreiben(ort, dauerhaft(capability="calendar")),
                              jetzt=JETZT) is None


def test_eine_v2_freigabe_ohne_faehigkeit_gilt_nicht(ort):
    dokument = dauerhaft()
    dokument.pop("capability")
    assert read_write_release(schreiben(ort, dokument), jetzt=JETZT) is None


# ── Die Dateibedingungen gelten unveraendert fuer beide Vertraege ────────────
def test_eine_zu_offene_dauerfreigabe_gilt_nicht(ort):
    assert read_write_release(schreiben(ort, dauerhaft(), modus=0o644),
                              jetzt=JETZT) is None


def test_eine_dauerfreigabe_in_einem_offenen_verzeichnis_gilt_nicht(ort):
    os.chmod(ort.parent, 0o755)
    try:
        assert read_write_release(schreiben(ort, dauerhaft()), jetzt=JETZT) is None
    finally:
        os.chmod(ort.parent, 0o700)


def test_eine_leere_begruendung_gilt_nicht(ort):
    assert read_write_release(schreiben(ort, dauerhaft(reason="   ")),
                              jetzt=JETZT) is None
