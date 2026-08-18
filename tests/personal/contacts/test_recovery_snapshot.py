"""Der Wiederherstellungsschnappschuss — die drei Familien ausserhalb von v1.

**Kontaktfrei.** Kein Sidecar, kein `CNContactStore`, kein Provider. Alle
Werte sind erfunden, alle Ablageorte liegen in `tmp_path`.

Zwei Aussagen tragen diese Datei, und die zweite ist die wichtigere:

1. Der Schnappschuss sichert, was Befund B-3 als Verlust benannt hat —
   `social_profiles`, `instant_messages`, `relations`.
2. Er entscheidet **nichts**. Weder macht sein Gelingen eine Löschung
   zulässig, noch hält sein Misslingen eine auf, und nichts vergleicht gegen
   ihn.
"""

from __future__ import annotations

import json
import os
import stat

import pytest

from personaljarvis.base.approvals import owner_decision_for_tests
from personaljarvis.contacts.application import ContactsMutationService
from personaljarvis.contacts.application.app_execution import AppExecutionService
from personaljarvis.contacts.application.delete_gate import (
    FIELD_STATE_CONTRACT,
    field_state_path,
)
from personaljarvis.contacts.application.errors import DeleteBackupMissing
from personaljarvis.contacts.application.recovery_snapshot import (
    EXCLUDED_FAMILIES,
    RECOVERY_ASSURANCE,
    RECOVERY_SNAPSHOT_CONTRACT,
    SNAPSHOT_FAMILIES,
    recovery_snapshot_path,
)
from personaljarvis.contacts.domain.capabilities import ContactCapabilitySet

from .conftest import new_id
from .test_delete_gate import JedeBeruehrungZaehlt
from .test_mutation_pipeline import (
    MENSCH,
    _container_bekannt,
    _delete,
    _lokalen_kontakt_anlegen,
)


# ── Aufbau ──────────────────────────────────────────────────────────────────
@pytest.fixture
def ziel() -> JedeBeruehrungZaehlt:
    return JedeBeruehrungZaehlt()


@pytest.fixture
def ablage(tmp_path):
    """Ablageort der v1-Sicherungen — der Beleg des Gates."""
    return tmp_path / "backups" / "contacts" / "field-state"


@pytest.fixture
def schnappschussablage(tmp_path):
    """Ablageort der Schnappschuesse — ein **eigener** Ordner, nicht derselbe."""
    return tmp_path / "backups" / "contacts" / "recovery-snapshot"


@pytest.fixture
def dienst(module, ziel, ablage, schnappschussablage) -> ContactsMutationService:
    caps = ContactCapabilitySet(create_supported=True, update_supported=True,
                                delete_supported=True)
    module._capabilities = caps
    module._mutation_service = ContactsMutationService(
        module, ziel, capabilities=caps, backup_dir=ablage,
        snapshot_dir=schnappschussablage)
    return module._mutation_service


def _drei_familien_anlegen(module, kontakt_id: str) -> None:
    """Legt in jeder der drei Familien zwei Eintraege — alles erfunden."""
    with module.unit_of_work() as uow:
        for position, (dienstname, name, url) in enumerate((
                ("Mastodon", "fixture_eins", "https://example.invalid/@eins"),
                ("Matrix", "fixture_zwei", None))):
            uow.execute(
                "INSERT INTO contact_social_profiles (id, contact_id, position,"
                " label_raw, label_normalized, service, username, url) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (new_id(), kontakt_id, position, "_$!<Other>!$_", "other",
                 dienstname, name, url))
        for position, (dienstname, name) in enumerate((
                ("XMPP", "eins@chat.invalid"), ("IRC", "fixture_eins"))):
            uow.execute(
                "INSERT INTO contact_instant_messages (id, contact_id, position,"
                " label_raw, label_normalized, service, username) "
                "VALUES (?,?,?,?,?,?,?)",
                (new_id(), kontakt_id, position, "_$!<Home>!$_", "home",
                 dienstname, name))
        # Ein aufloesbarer Bezug (auf einen zweiten lokalen Kontakt) und ein
        # roher — beide Formen kommen im Bestand vor.
        zweiter = _zweiten_kontakt_anlegen(uow)
        uow.execute(
            "INSERT INTO contact_relations (id, from_contact_id, to_contact_id,"
            " position, relation_type, label_raw, target_name_raw) "
            "VALUES (?,?,?,?,?,?,?)",
            (new_id(), kontakt_id, zweiter, 0, "spouse", "_$!<Spouse>!$_",
             None))
        uow.execute(
            "INSERT INTO contact_relations (id, from_contact_id, to_contact_id,"
            " position, relation_type, label_raw, target_name_raw) "
            "VALUES (?,?,?,?,?,?,?)",
            (new_id(), kontakt_id, None, 1, "assistant", None,
             "Fixture Drei"))


def _zweiten_kontakt_anlegen(uow) -> str:
    from personaljarvis.contacts.repositories.sqlite import (
        SqliteContactRepository,
    )
    from tests.personal.contacts.conftest import make_contact

    zweiter = make_contact(display_name="Fixture Zwei", given_name="Fixture",
                           family_name="Zwei", emails=(), phones=())
    SqliteContactRepository(uow).add(zweiter)
    return zweiter.id


def _freigegebene_loeschung(module, dienst, *, mit_familien: bool = True) -> str:
    _container_bekannt(module)
    kontakt = _lokalen_kontakt_anlegen(module)
    if mit_familien:
        _drei_familien_anlegen(module, kontakt.id)
    vorgang = dienst.prepare(_delete())
    dienst.grant(vorgang.mutation_id,
                 decision=owner_decision_for_tests(MENSCH))
    return vorgang.mutation_id


def _schnappschuss(schnappschussablage, mutation_id: str) -> dict:
    pfad = recovery_snapshot_path(mutation_id, basis=schnappschussablage)
    return json.loads(pfad.read_text(encoding="utf-8"))


# ═══ A · Was gesichert wird ═════════════════════════════════════════════════
def test_die_drei_familien_stehen_in_der_datei(module, dienst, ziel,
                                               schnappschussablage):
    """Der Kernnachweis: Was B-3 als Verlust benannt hat, liegt jetzt daneben."""
    mid = _freigegebene_loeschung(module, dienst)
    dienst.execute(mid)

    doc = _schnappschuss(schnappschussablage, mid)
    assert doc["contract"] == RECOVERY_SNAPSHOT_CONTRACT
    # Die Datei wird sortiert geschrieben; der Vertrag ist der Bestand der
    # Familien, nicht ihre Reihenfolge im JSON.
    assert sorted(doc["families"]) == sorted(SNAPSHOT_FAMILIES)
    assert [e["service"] for e in doc["families"]["social_profiles"]] == [
        "Mastodon", "Matrix"]
    assert [e["username"] for e in doc["families"]["instant_messages"]] == [
        "eins@chat.invalid", "fixture_eins"]
    # Der aufloesbare Bezug traegt den Namen des Ziels, nicht nur eine
    # lokale Kennung — die waere nach dem Loeschen nichts zum Abtippen.
    arten = [(e["relation_type"], e["target_display_name"],
              e["target_name_raw"]) for e in doc["families"]["relations"]]
    assert arten == [("spouse", "Fixture Zwei", None),
                     ("assistant", None, "Fixture Drei")]


def test_die_zusicherung_steht_woertlich_in_der_datei(module, dienst,
                                                      schnappschussablage):
    """`gesichert, manuell rekonstruierbar` — nicht „wiederhergestellt"."""
    mid = _freigegebene_loeschung(module, dienst)
    dienst.execute(mid)
    doc = _schnappschuss(schnappschussablage, mid)
    assert doc["assurance"] == RECOVERY_ASSURANCE
    assert doc["assurance"] == "gesichert, manuell rekonstruierbar"
    assert doc["source"] == "local_mirror"


def test_was_draussen_bleibt_steht_mit_grund_in_der_datei(
        module, dienst, schnappschussablage):
    """Foto und Notiz fehlen — und die Datei sagt selbst, warum.

    Ein Verlust, den nur ein Befundregister kennt, ist beim Öffnen der Datei
    kein Verlust, sondern eine Lücke, die niemand bemerkt.
    """
    mid = _freigegebene_loeschung(module, dienst)
    dienst.execute(mid)
    doc = _schnappschuss(schnappschussablage, mid)

    benannt = {e["family"]: e for e in doc["excluded"]}
    assert set(benannt) == {"photo", "note"}
    assert benannt["note"]["reasonCode"] == "unavailable_by_capability"
    assert benannt["photo"]["reasonCode"] == (
        "not_text_not_manually_reconstructible")
    for eintrag in benannt.values():
        assert eintrag["reason"].strip()
    assert len(EXCLUDED_FAMILIES) == 2


def test_die_datei_liegt_mit_0600_in_einem_0700_ordner(
        module, dienst, schnappschussablage):
    """Dieselbe Ordnung wie bei der v1-Sicherung — es sind dieselben Werte."""
    mid = _freigegebene_loeschung(module, dienst)
    dienst.execute(mid)

    pfad = recovery_snapshot_path(mid, basis=schnappschussablage)
    assert stat.S_IMODE(pfad.lstat().st_mode) == 0o600
    assert stat.S_IMODE(pfad.parent.lstat().st_mode) == 0o700
    assert pfad.lstat().st_uid == os.geteuid()


def test_ohne_zusatzfamilien_entsteht_keine_datei(module, dienst,
                                                  schnappschussablage):
    """Drei leere Listen wären eine Klartextablage ohne Klartext.

    Und sie sähe später aus wie ein Verlust, den es nicht gab.
    """
    mid = _freigegebene_loeschung(module, dienst, mit_familien=False)
    dienst.execute(mid)

    assert not recovery_snapshot_path(mid, basis=schnappschussablage).exists()
    ergebnis = dienst._letzter_schnappschuss
    assert ergebnis.written is False
    assert ergebnis.reason_code == "nothing_beyond_v1"


# ═══ B · Er entscheidet nichts ══════════════════════════════════════════════
def test_ein_gescheiterter_schnappschuss_haelt_die_loeschung_nicht_auf(
        module, dienst, ziel, schnappschussablage, monkeypatch):
    """Die tragende Aussage: keine Rückwirkung auf das Gate.

    Der Schreibweg wird stillgelegt. Die v1-Sicherung steht, also läuft die
    Löschung weiter — dass das Ausführungsziel danach die Berührung meldet,
    ist genau der Beleg.
    """
    mid = _freigegebene_loeschung(module, dienst)
    monkeypatch.setattr(
        "personaljarvis.contacts.application.recovery_snapshot"
        ".schreibe_schnappschuss",
        lambda *a, **kw: (_ for _ in ()).throw(OSError("Platte voll")))

    dienst.execute(mid)

    # Weiter heisst hier bis zum Ausfuehrungsziel — dieselbe Messung wie in
    # der Gegenprobe des Loeschgates.
    assert ziel.beruehrungen == ["apply"]
    assert not recovery_snapshot_path(mid, basis=schnappschussablage).exists()
    assert dienst._letzter_schnappschuss.written is False
    assert dienst._letzter_schnappschuss.reason_code == "write_failed"


def test_ein_gelungener_schnappschuss_ersetzt_die_v1_sicherung_nicht(
        module, dienst, ziel, ablage, schnappschussablage, monkeypatch):
    """Die andere Richtung: Er macht keine Löschung zulässig, die es nicht ist.

    Der Schnappschuss wird geschrieben, die v1-Sicherung nicht. Das Gate
    schliesst trotzdem — und das Ausführungsziel bleibt unberührt.
    """
    mid = _freigegebene_loeschung(module, dienst)
    monkeypatch.setattr(
        "personaljarvis.contacts.application.mutation_service"
        ".schreibe_loeschsicherung",
        lambda *a, **kw: "")

    with pytest.raises(DeleteBackupMissing):
        dienst.execute(mid)

    # Der Schnappschuss liegt da — und er hilft nicht.
    assert recovery_snapshot_path(mid, basis=schnappschussablage).exists()
    assert not field_state_path(mid, basis=ablage).exists()
    assert ziel.beruehrungen == []


def test_der_claim_gelingt_auch_wenn_der_schnappschuss_scheitert(
        module, dienst, ablage, schnappschussablage, monkeypatch):
    """Derselbe Nachweis am produktiven Löschweg — dem App-Prozess-Kanal.

    Ein Nachweis nur am Dienst belegte den anderen Weg nicht; das ist dieselbe
    Fehlerklasse, an der der Kontingentzähler am 2026-08-17 vorbeimass.

    Stillgelegt wird der **innere** Schreibschritt, nicht `sichere_zusatzfamilien`
    selbst: Wer den Fänger ersetzt, prüft nicht, ob er fängt.
    """
    from personaljarvis.contacts.application.app_channel import (
        fake_debug_capabilities,
    )

    mid = _freigegebene_loeschung(module, dienst)
    kanal = AppExecutionService(
        module, channel_capabilities=fake_debug_capabilities(delete=True),
        backup_dir=ablage, snapshot_dir=schnappschussablage)
    monkeypatch.setattr(
        "personaljarvis.contacts.application.recovery_snapshot"
        ".schreibe_schnappschuss",
        lambda *a, **kw: (_ for _ in ()).throw(OSError("Platte voll")))

    auftrag = kanal.claim(mid, confirm_delete=True)

    assert auftrag.operation_type == "delete"
    assert kanal._letzter_schnappschuss.written is False
    assert kanal._letzter_schnappschuss.reason_code == "write_failed"
    assert not recovery_snapshot_path(mid, basis=schnappschussablage).exists()


def test_der_produktive_loeschweg_schreibt_den_schnappschuss(
        module, dienst, ablage, schnappschussablage):
    """Die Gegenprobe: ungestört schreibt derselbe Weg die drei Familien.

    Ohne sie sagte der Test davor nur, dass ein kaputter Weg nichts tut.
    """
    from personaljarvis.contacts.application.app_channel import (
        fake_debug_capabilities,
    )

    mid = _freigegebene_loeschung(module, dienst)
    kanal = AppExecutionService(
        module, channel_capabilities=fake_debug_capabilities(delete=True),
        backup_dir=ablage, snapshot_dir=schnappschussablage)

    auftrag = kanal.claim(mid, confirm_delete=True)

    assert auftrag.operation_type == "delete"
    assert kanal._letzter_schnappschuss.written is True
    assert kanal._letzter_schnappschuss.counts == {
        "social_profiles": 2, "instant_messages": 2, "relations": 2}
    doc = _schnappschuss(schnappschussablage, mid)
    assert doc["contract"] == RECOVERY_SNAPSHOT_CONTRACT


def test_er_traegt_keinen_vergleichsmassstab(module, dienst,
                                             schnappschussablage):
    """Kein Vorzustandsdigest, kein Gate-Vertrag — nichts misst gegen ihn.

    Eine Datei, die aussieht wie ein Beleg, wird irgendwann als einer gelesen.
    """
    mid = _freigegebene_loeschung(module, dienst)
    dienst.execute(mid)
    doc = _schnappschuss(schnappschussablage, mid)

    assert doc["contract"] != FIELD_STATE_CONTRACT
    assert "expectedFieldsDigest" not in doc
    assert "fieldContractVersion" not in doc
    assert "fields" not in doc


def test_der_loeschpfad_liest_den_schnappschussordner_nicht(
        module, dienst, ziel, ablage, schnappschussablage, monkeypatch):
    """Die Durchsetzung sieht ausschliesslich in die v1-Ablage.

    Gemessen am Ordner, nicht am Aufruf: Ein Weg, der doch hineinsähe, müsste
    sonst nur anders heissen.
    """
    mid = _freigegebene_loeschung(module, dienst)
    dienst.execute(mid)

    from pathlib import Path

    gelesen: list[str] = []
    echt_read = Path.read_text

    def _read_text(self, *a, **kw):
        gelesen.append(str(self))
        return echt_read(self, *a, **kw)

    monkeypatch.setattr(Path, "read_text", _read_text)

    zweite = _freigegebene_loeschung(module, dienst)
    dienst.execute(zweite)

    beruehrt = [p for p in gelesen if "recovery-snapshot" in p]
    # Genau ein Zugriff ist zulaessig: der Rueckleseschritt des Schreibens.
    assert len(beruehrt) == 1, beruehrt


# ═══ C · Die Werte verlassen das Modul nicht ════════════════════════════════
def test_das_ergebnis_traegt_zahlen_und_gruende_aber_keine_werte(
        module, dienst, schnappschussablage):
    """Was ins Protokoll darf, sind Zahlen — nie Feldwerte."""
    mid = _freigegebene_loeschung(module, dienst)
    dienst.execute(mid)

    ergebnis = dienst._letzter_schnappschuss
    assert ergebnis.written is True
    assert ergebnis.counts == {"social_profiles": 2, "instant_messages": 2,
                               "relations": 2}
    assert len(ergebnis.content_digest) == 64
    text = repr(ergebnis)
    for wert in ("Mastodon", "fixture_eins", "eins@chat.invalid",
                 "Fixture Zwei", "Fixture Drei"):
        assert wert not in text, wert
