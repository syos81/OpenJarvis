"""Das Löschgate: keine Löschung ohne belegt wiederherstellbaren Inhalt.

**Kontaktfrei.** Kein Sidecar, kein `CNContactStore`, kein Provider. Alle
Feldwerte sind erfunden, alle Ablageorte liegen in `tmp_path`.

Der zentrale Nachweis: **Ein Delete ohne gültige Sicherung kommt nicht bis zum
Provider.** Gemessen wird das nicht am Save und nicht am Delete, sondern an
*jeder* Berührung des Ausführungsziels — ein Weg, der am Gate vorbeiführte,
müsste sonst nur eine andere Methode heissen, um unbemerkt zu bleiben.

Die Sprache ist verbindlich: `content-recoverable, identity-irreversible`.
Der Inhalt ist wiederherstellbar, der Kontakt nicht.
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
    loeschbindung,
    pruefe_loeschsicherung,
)
from personaljarvis.contacts.application.errors import (
    DeleteBackupMissing,
    DeleteBackupUnverified,
    MutationNotExecutable,
)
from personaljarvis.contacts.domain.capabilities import ContactCapabilitySet

from .test_mutation_pipeline import (
    CONTAINER,
    MENSCH,
    _container_bekannt,
    _delete,
    _lokalen_kontakt_anlegen,
)


class JedeBeruehrungZaehlt:
    """Ein Ausführungsziel, das **jeden** Zugriff zählt.

    Nur `apply` zu zählen hiesse, dem Ablauf zu glauben, dass er kein anderes
    Wort für dasselbe kennt. Hier schlägt jeder Attributzugriff an — auch
    einer, den es heute noch gar nicht gibt.
    """

    def __init__(self) -> None:
        # Über `object.__setattr__`, damit das Zählwerk sich nicht selbst zählt.
        object.__setattr__(self, "beruehrungen", [])

    def __getattr__(self, name: str):
        self.beruehrungen.append(name)

        def _egal(*args, **kwargs):  # pragma: no cover - darf nie laufen
            raise AssertionError(
                f"Das Ausführungsziel wurde berührt: {name}")

        return _egal


@pytest.fixture
def ziel() -> JedeBeruehrungZaehlt:
    return JedeBeruehrungZaehlt()


@pytest.fixture
def ablage(tmp_path):
    """Der Ablageort der Sicherungen — ausserhalb des Repositorys, wie produktiv."""
    return tmp_path / "backups" / "contacts" / "field-state"


@pytest.fixture
def dienst(module, ziel, ablage) -> ContactsMutationService:
    caps = ContactCapabilitySet(create_supported=True, update_supported=True,
                                delete_supported=True)
    module._capabilities = caps
    module._mutation_service = ContactsMutationService(
        module, ziel, capabilities=caps, backup_dir=ablage)
    return module._mutation_service


def _freigegebene_loeschung(module, dienst) -> str:
    _container_bekannt(module)
    _lokalen_kontakt_anlegen(module)
    vorgang = dienst.prepare(_delete())
    dienst.grant(vorgang.mutation_id,
                 decision=owner_decision_for_tests(MENSCH))
    return vorgang.mutation_id


def _zeile(module, mutation_id: str):
    with module.unit_of_work() as uow:
        return uow.execute(
            "SELECT * FROM contacts_mutations WHERE mutation_id = ?",
            (mutation_id,)).fetchone()


def _bindung(module, mutation_id: str):
    """Ziel, Ablageort und Vorzustand — so, wie das Gate sie auflöst."""
    with module.unit_of_work() as uow:
        zeile = uow.execute(
            "SELECT * FROM contacts_mutations WHERE mutation_id = ?",
            (mutation_id,)).fetchone()
        return loeschbindung(uow, zeile)


def _gelesen(ablage, mutation_id: str) -> dict:
    return json.loads(
        field_state_path(mutation_id, basis=ablage).read_text(encoding="utf-8"))


# ═══ A · Der Kernnachweis ═══════════════════════════════════════════════════
def test_ohne_sicherung_kommt_ein_delete_nicht_bis_zum_provider(
        module, dienst, ziel, ablage, monkeypatch):
    """Der eine Satz, für den dieses Gate gebaut ist.

    Das Sichern wird stillgelegt — genau der Zustand, den es vor diesem Block
    gab: eine freigegebene, gültige Löschung ohne jede Sicherung des Inhalts.
    """
    mid = _freigegebene_loeschung(module, dienst)
    monkeypatch.setattr(
        "personaljarvis.contacts.application.mutation_service"
        ".schreibe_loeschsicherung",
        lambda *a, **kw: "")

    with pytest.raises(DeleteBackupMissing):
        dienst.execute(mid)

    assert ziel.beruehrungen == []
    # Und der Vorgang steht unverändert da: nichts verbraucht, nichts
    # beansprucht. Ein zweiter Anlauf ist möglich, sobald die Sicherung steht.
    assert _zeile(module, mid)["state"] == "approved"


def test_ohne_sicherung_gibt_der_kanal_keinen_auftrag_aus(
        module, dienst, ziel, ablage, monkeypatch):
    """Derselbe Nachweis am produktiven Löschweg — dem App-Prozess-Kanal.

    Ohne Auftrag berührt der App-Prozess den Provider nie; der Claim ist damit
    der Punkt, an dem eine Löschung ohne belegten Inhalt endet.
    """
    from personaljarvis.contacts.application.app_channel import (
        fake_debug_capabilities,
    )

    mid = _freigegebene_loeschung(module, dienst)
    kanal = AppExecutionService(
        module, channel_capabilities=fake_debug_capabilities(delete=True),
        backup_dir=ablage)
    monkeypatch.setattr(
        "personaljarvis.contacts.application.app_execution"
        ".schreibe_loeschsicherung",
        lambda *a, **kw: "")

    with pytest.raises(DeleteBackupMissing):
        kanal.claim(mid, confirm_delete=True)

    assert ziel.beruehrungen == []
    assert _zeile(module, mid)["state"] == "approved"


def test_mit_sicherung_laeuft_die_loeschung_weiter(module, dienst, ziel, ablage):
    """Die Gegenprobe: Das Gate sperrt nicht grundsätzlich, es sperrt Ungesichertes.

    Weiter heisst hier bis zum Ausführungsziel — dass dieses synthetische Ziel
    danach die Berührung meldet, ist genau der Beleg.
    """
    mid = _freigegebene_loeschung(module, dienst)
    dienst.execute(mid)

    assert ziel.beruehrungen == ["apply"]
    assert field_state_path(mid, basis=ablage).exists()


# ═══ B · Was die Sicherung enthält ══════════════════════════════════════════
def test_die_sicherung_traegt_werte_ziel_und_digest(module, dienst, ablage):
    mid = _freigegebene_loeschung(module, dienst)
    dienst._sichere_loeschziel(mid)

    doc = _gelesen(ablage, mid)
    assert doc["contract"] == FIELD_STATE_CONTRACT
    assert doc["mutationId"] == mid
    assert doc["containerIdentifier"] == CONTAINER
    assert doc["providerIdentifier"] == "raw-1"
    assert doc["fieldContractVersion"] == 1
    assert doc["capturedAt"]
    # Die Feldwerte selbst — ohne sie sichert das Gate nichts.
    assert doc["fields"]
    assert doc["fields"]["givenName"] == "Fixture"
    # Der Digest, an dem der Löschpfad seinen einen Re-Read misst.
    nutzlast = json.loads(_zeile(module, mid)["payload_json"])
    assert doc["expectedFieldsDigest"] == nutzlast["expectedFieldsDigest"]
    assert doc["fields"] == nutzlast["expectedPrevious"]


def test_die_sicherung_liegt_0600_in_einem_0700_ordner(module, dienst, ablage):
    mid = _freigegebene_loeschung(module, dienst)
    dienst._sichere_loeschziel(mid)

    pfad = field_state_path(mid, basis=ablage)
    assert stat.S_IMODE(pfad.lstat().st_mode) == 0o600
    assert stat.S_IMODE(pfad.parent.lstat().st_mode) == 0o700


def test_die_sicherung_wird_zurueckgelesen_und_verifiziert(module, dienst,
                                                           ablage, monkeypatch):
    """Geschrieben **und** zurückgelesen. „Vermutlich geschrieben" gibt es nicht."""
    mid = _freigegebene_loeschung(module, dienst)

    echt = json.loads

    def _verfaelscht(text, *a, **kw):
        ergebnis = echt(text, *a, **kw)
        if isinstance(ergebnis, dict) and ergebnis.get("contract") == \
                FIELD_STATE_CONTRACT:
            ergebnis["fields"] = {"givenName": "etwas anderes"}
        return ergebnis

    monkeypatch.setattr(
        "personaljarvis.contacts.application.delete_gate.json.loads",
        _verfaelscht)
    with pytest.raises(DeleteBackupUnverified):
        dienst._sichere_loeschziel(mid)


# ═══ C · Bindung an genau diese Löschung ════════════════════════════════════
@pytest.mark.parametrize("feld,wert", [
    ("containerIdentifier", "ein-anderer-container"),
    ("providerIdentifier", "raw-fremd"),
    ("expectedFieldsDigest", "0" * 64),
    ("contract", "irgendwas-v9"),
])
def test_eine_sicherung_die_etwas_anderes_meint_zaehlt_nicht(
        module, dienst, ablage, feld, wert):
    """Nicht „eine Datei liegt da", sondern „diese Löschung ist gesichert"."""
    mid = _freigegebene_loeschung(module, dienst)
    dienst._sichere_loeschziel(mid)

    pfad = field_state_path(mid, basis=ablage)
    doc = _gelesen(ablage, mid)
    doc[feld] = wert
    pfad.write_text(json.dumps(doc), encoding="utf-8")
    os.chmod(pfad, 0o600)

    with pytest.raises(DeleteBackupUnverified):
        pruefe_loeschsicherung(_bindung(module, mid), basis=ablage)


def test_eine_sicherung_ohne_feldwerte_ist_keine(module, dienst, ablage):
    """Sie sähe nur so aus."""
    mid = _freigegebene_loeschung(module, dienst)
    dienst._sichere_loeschziel(mid)

    pfad = field_state_path(mid, basis=ablage)
    doc = _gelesen(ablage, mid)
    doc["fields"] = {}
    pfad.write_text(json.dumps(doc), encoding="utf-8")
    os.chmod(pfad, 0o600)

    with pytest.raises(DeleteBackupUnverified):
        pruefe_loeschsicherung(_bindung(module, mid), basis=ablage)


def test_eine_weltlesbare_sicherung_zaehlt_nicht(module, dienst, ablage):
    mid = _freigegebene_loeschung(module, dienst)
    dienst._sichere_loeschziel(mid)
    os.chmod(field_state_path(mid, basis=ablage), 0o644)

    with pytest.raises(DeleteBackupUnverified):
        pruefe_loeschsicherung(_bindung(module, mid), basis=ablage)


def test_die_sicherung_einer_anderen_mutation_traegt_diese_nicht(
        module, dienst, ablage):
    erste = _freigegebene_loeschung(module, dienst)
    dienst._sichere_loeschziel(erste)

    # Ein zweiter, eigener Kontakt — ein zweiter offener Vorgang auf denselben
    # waere gar nicht erst moeglich.
    _lokalen_kontakt_anlegen(module, provider_identifier="raw-2")
    vorgang = dienst.prepare(_delete(target_provider_identifier="raw-2"))
    dienst.grant(vorgang.mutation_id,
                 decision=owner_decision_for_tests(MENSCH))
    zweite = vorgang.mutation_id

    # Für die zweite Löschung liegt nichts vor — dass daneben eine Sicherung
    # existiert, hilft ihr nicht.
    with pytest.raises(DeleteBackupMissing):
        pruefe_loeschsicherung(_bindung(module, zweite), basis=ablage)


def test_ohne_gebundenen_vorzustand_wird_nicht_geloescht(module, dienst, ablage):
    """Fail-closed statt „dann eben ohne Vergleichsmassstab"."""
    mid = _freigegebene_loeschung(module, dienst)
    zeile = dict(_zeile(module, mid))
    nutzlast = json.loads(zeile["payload_json"])
    nutzlast.pop("expectedPrevious")
    zeile["payload_json"] = json.dumps(nutzlast)

    with module.unit_of_work() as uow:
        with pytest.raises(DeleteBackupUnverified):
            loeschbindung(uow, zeile)


def test_ohne_bekannten_ablageort_wird_nicht_geloescht(module, dienst, ablage):
    """Was sich nicht eindeutig zuordnen lässt, wird nicht gelöscht."""
    mid = _freigegebene_loeschung(module, dienst)
    with module.unit_of_work() as uow:
        uow.execute("DELETE FROM contact_external_ids")
        zeile = uow.execute(
            "SELECT * FROM contacts_mutations WHERE mutation_id = ?",
            (mid,)).fetchone()
        with pytest.raises(DeleteBackupUnverified):
            loeschbindung(uow, zeile)


# ═══ D · Zeitpunkt, Wiederholung, Aufbewahrung ══════════════════════════════
def test_die_freigabe_allein_schreibt_noch_keine_kopie(module, dienst, ablage):
    """Nicht bei der Freigabe, sondern unmittelbar vor der Mutation.

    Sonst entstünde für jede freigegebene, aber nie ausgeführte Löschung eine
    Klartextkopie eines Kontakts, den es weiterhin gibt.
    """
    mid = _freigegebene_loeschung(module, dienst)
    assert not field_state_path(mid, basis=ablage).exists()


def test_ohne_die_zweite_bestaetigung_entsteht_keine_kopie(module, dienst,
                                                           ablage):
    """Ein Vorgang, der gar nicht laufen darf, braucht keine Klartextkopie."""
    from personaljarvis.contacts.application.app_channel import (
        fake_debug_capabilities,
    )
    from personaljarvis.contacts.application.app_execution import (
        DeleteConfirmationRequired,
    )

    mid = _freigegebene_loeschung(module, dienst)
    kanal = AppExecutionService(
        module, channel_capabilities=fake_debug_capabilities(delete=True),
        backup_dir=ablage)
    with pytest.raises(DeleteConfirmationRequired):
        kanal.claim(mid, confirm_delete=False)
    assert not field_state_path(mid, basis=ablage).exists()


def test_ein_zweiter_anlauf_ueberschreibt_dieselbe_datei(module, dienst, ablage):
    """Kein zweiter Ablageort für denselben Kontakt.

    Ein erneuter Anlauf derselben Mutation trifft dieselbe Datei. Eine zweite
    wäre eine zweite Klartextkopie desselben Menschen.
    """
    mid = _freigegebene_loeschung(module, dienst)
    dienst._sichere_loeschziel(mid)
    dienst._sichere_loeschziel(mid)
    dienst._sichere_loeschziel(mid)

    dateien = sorted(p.name for p in ablage.iterdir())
    assert dateien == [f"{mid}.json"]


def test_nach_der_loeschung_bleibt_die_sicherung_liegen(module, dienst, ziel,
                                                        ablage):
    """Kein automatisches Löschen, keine Frist. Löschen ist Eigentümersache."""
    mid = _freigegebene_loeschung(module, dienst)
    dienst.execute(mid)
    assert field_state_path(mid, basis=ablage).exists()


def test_es_gibt_keine_funktion_die_sicherungen_aufraeumt():
    """Ein Aufräumweg wäre genau der Weg, den ein Agent ginge."""
    import re
    from pathlib import Path

    quelle = (Path(__file__).resolve().parents[3] / "src" / "personaljarvis"
              / "contacts" / "application" / "delete_gate.py").read_text(
                  encoding="utf-8")
    assert not re.search(r"def \w*(aufraeum|cleanup|purge|loesch\w*sicherung"
                         r"en|prune)\w*", quelle)
    assert "unlink" not in quelle.replace("temp.unlink(missing_ok=True)", "")
    assert "rmtree" not in quelle


# ═══ E · Die Werte gehen nicht nach draussen ════════════════════════════════
def test_kein_feldwert_steht_im_auditprotokoll(module, dienst, ziel, ablage):
    """Der Digest darf nach aussen, die Werte nie.

    Geprüft wird der **ganze** Protokolleintrag, nicht ein einzelnes Feld:
    Eine Zusicherung über eine Spalte, die es morgen nicht mehr gibt, wäre
    keine.
    """
    mid = _freigegebene_loeschung(module, dienst)
    dienst.execute(mid)

    with module.unit_of_work() as uow:
        zeilen = uow.execute(
            "SELECT * FROM personal_audit_log WHERE subject_id = ?",
            (mid,)).fetchall()
    assert zeilen                     # es gibt Einträge, sonst prüft das nichts
    alles = " ".join(str(wert) for z in zeilen for wert in tuple(z))
    for wert in ("Fixture", "eins@example.invalid", "+49 30"):
        assert wert not in alles


def test_der_ablageort_liegt_ausserhalb_des_repositorys():
    """Kontaktwerte sind keine Evidenz und gehören auch nicht dorthin."""
    from pathlib import Path

    from personaljarvis.contacts.application.delete_gate import (
        default_field_state_dir,
    )

    # Ausdruecklich der **produktive** Ort, nicht der dieses Laufs: Die Suite
    # leitet `field_state_dir` um, und genau deshalb muss die Aussage ueber
    # das Produkt an einem eigenen Begriff haengen.
    ort = default_field_state_dir()
    wurzel = Path(__file__).resolve().parents[3]
    assert wurzel not in ort.parents and ort != wurzel
    assert ort.parts[-3:] == ("backups", "contacts", "field-state")
    # Und ausdrücklich nicht im gitignorierten Laufzeitbereich der Gates.
    assert ".gate-runtime" not in str(ort)


# ═══ F · Jede Löschung braucht ihre eigene Owner-Freigabe ═══════════════════
#
# Standing Write erteilt eine **Klasse** von Operationen. Es sagt nichts über
# einen einzelnen Vorgang — und genau das war der Befund vom 2026-08-17, als
# unter einer Freigabe 25 von 25 Mutationen durchliefen. Geprüft wird deshalb
# mechanisch, nicht angenommen.
def test_standing_write_allein_traegt_keine_loeschung(module, dienst, ziel,
                                                      ablage, tmp_path):
    """Freigegebene Urkunde, gesicherter Inhalt — und trotzdem keine Löschung.

    Was fehlt, ist die Entscheidung zu **diesem** Vorgang.
    """
    import os

    from personaljarvis.contacts.application.write_release import (
        MODE_STANDING,
        WRITE_RELEASE_CAPABILITY,
        WRITE_RELEASE_CONTRACT_V2,
    )

    ordner = tmp_path / "personal"
    ordner.mkdir(parents=True, exist_ok=True)
    os.chmod(ordner, 0o700)
    urkunde = ordner / "contacts-write-release.json"
    urkunde.write_text(json.dumps({
        "contract": WRITE_RELEASE_CONTRACT_V2,
        "capability": WRITE_RELEASE_CAPABILITY,
        "mode": MODE_STANDING,
        "operations": ["create", "update", "delete"],
        "granted_at": "2026-08-17T20:00:00Z",
        "reason": "Im Produkt eingeschaltet",
    }), encoding="utf-8")
    os.chmod(urkunde, 0o600)

    caps = ContactCapabilitySet(create_supported=True, update_supported=True,
                                delete_supported=True)
    mit_urkunde = ContactsMutationService(
        module, ziel, capabilities=caps, release_path=urkunde,
        backup_dir=ablage)
    _container_bekannt(module)
    _lokalen_kontakt_anlegen(module)
    vorgang = mit_urkunde.prepare(_delete())
    # Kein `grant` — die Dauerfreigabe soll es ausdrücklich nicht ersetzen.

    with pytest.raises(MutationNotExecutable):
        mit_urkunde.execute(vorgang.mutation_id)
    assert ziel.beruehrungen == []


def test_ein_beleg_traegt_genau_einen_vorgang_und_genau_einmal(monkeypatch,
                                                               tmp_path):
    """Der Belegweg selbst — ohne die Öffnung, die diese Suite sonst benutzt.

    Drei Aussagen in einer: ohne Beleg keine Entscheidung; ein Beleg für einen
    anderen Vorgang trägt diesen nicht; und derselbe Beleg trägt keinen
    zweiten Lauf.
    """
    import os
    from datetime import datetime, timezone

    # Die autouse-Oeffnung dieser Suite zurücknehmen: Hier wird gerade die
    # Herkunft geprüft, und die darf nicht vorausgesetzt sein.
    monkeypatch.undo()

    from personaljarvis.base.approvals import (
        SelfApprovalRejected,
        owner_decision_attested,
    )
    from personaljarvis.base.owner_attestation import ATTESTATION_CONTRACT

    ordner = tmp_path / "owner-approvals"
    ordner.mkdir(parents=True)
    os.chmod(ordner, 0o700)

    def _frage(mid: str):
        return owner_decision_attested(
            capability="contacts.write", mutation_id=mid,
            payload_digest="p" * 64, preview_digest="v" * 64,
            actor=MENSCH, verzeichnis=ordner)

    # 1. Ohne Beleg gibt es keine Entscheidung.
    with pytest.raises(SelfApprovalRejected):
        _frage("vorgang-a")

    datei = ordner / "vorgang-a.json"
    datei.write_text(json.dumps({
        "contract": ATTESTATION_CONTRACT,
        "capability": "contacts.write",
        "mutation_id": "vorgang-a",
        "payload_digest": "p" * 64,
        "preview_digest": "v" * 64,
        "attested_at": datetime.now(timezone.utc).isoformat(),
        "method": "testbeleg",
    }), encoding="utf-8")
    os.chmod(datei, 0o600)

    # 2. Er trägt genau seinen Vorgang — kein Nachbarvorgang zehrt von ihm.
    with pytest.raises(SelfApprovalRejected):
        _frage("vorgang-b")

    # 3. Und er trägt ihn genau einmal.
    assert _frage("vorgang-a").actor == MENSCH
    with pytest.raises(SelfApprovalRejected):
        _frage("vorgang-a")


# ═══ G · Deckung: was verglichen wird, was gesichert wird ═══════════════════
#
# Die Ableitung „was gesichert wurde, ist genau das, was gelöscht wurde" trägt
# nur so weit, wie der Vergleich reicht. Deshalb wird hier beides gegeneinander
# geprüft, statt es abzuleiten — in beide Richtungen.
def test_die_sicherung_enthaelt_nichts_das_der_vergleich_nicht_prueft(
        module, dienst, ablage):
    """Kein Überhang: Jeder gesicherte Wert ist ein verglichener Wert.

    Der Vergleich im App-Prozess ist `[ist isEqualToDictionary:erwartetVorher]`
    — eine **vollständige** Wörterbuchgleichheit über beide Schlüsselmengen.
    Sein Operand `erwartetVorher` ist `expectedPrevious`, und genau dieses
    Wörterbuch steht in der Sicherung. Ein Feld, das nur mitgeschrieben und
    nicht erzwungen wäre, gibt es damit nicht.
    """
    mid = _freigegebene_loeschung(module, dienst)
    dienst._sichere_loeschziel(mid)

    doc = _gelesen(ablage, mid)
    nutzlast = json.loads(_zeile(module, mid)["payload_json"])
    assert doc["fields"] == nutzlast["expectedPrevious"]

    # Und der Digest deckt genau dieses Wörterbuch — dieselbe Formel, die der
    # native Pfad nachrechnet, bevor er den Vorzustand als gebunden annimmt.
    from personaljarvis.base.digest import digest_of

    assert doc["expectedFieldsDigest"] == digest_of({
        "fieldContractVersion": doc["fieldContractVersion"],
        "fields": doc["fields"]})


def test_der_vergleich_rechnet_dieselbe_formel_wie_die_sicherung():
    """Die Klammer im nativen Pfad — am Quelltext, nicht als Annahme."""
    from pathlib import Path

    wurzel = Path(__file__).resolve().parents[3]
    rust = (wurzel / "frontend/src-tauri/src/contacts_create.rs").read_text(
        encoding="utf-8")
    # Der Vorzustand wird gegen seinen Digest gebunden …
    assert '"fieldContractVersion": order.field_contract_version' in rust
    assert '"fields": vorher' in rust
    assert 'expectedFieldsDigest' in rust

    objc = (wurzel / "frontend/src-tauri/objc/JCContactsCreate.m").read_text(
        encoding="utf-8")
    # … und dann Feld für Feld gegen den unmittelbaren Read verglichen.
    assert "[ist isEqualToDictionary:erwartetVorher]" in objc
    assert "JCContactsWriteOutcomeRevisionConflict" in objc


#: Was Jarvis von einem Kontakt liest und lokal haelt, **ohne** dass es zum
#: Feldvertrag v1 gehoert. Diese Familien stehen weder in `expectedPrevious`
#: noch in der Sicherung noch im Vergleich — eine Wiederherstellung aus der
#: Sicherung bringt sie nicht zurueck.
#:
#: Der Eintrag hier ist kein Auftrag, das zu aendern. Er haelt die Grenze
#: fest, damit niemand „Kontaktinhalt wiederherstellbar" fuer mehr liest, als
#: es sagt.
AUSSERHALB_V1 = ("social_profiles", "instant_messages", "relations",
                 "image_available", "thumbnail_blob_ref", "note")


def test_die_sicherung_deckt_den_feldvertrag_v1_und_nicht_mehr(module, dienst,
                                                               ablage):
    """Der Unterschuss — benannt, nicht geschlossen.

    Der Kontakt traegt mehr, als v1 kennt. `note` ist ausdruecklich nie
    schreibbar (Entitlement), die uebrigen Familien werden gelesen und lokal
    gehalten, gehoeren aber nicht zum Vertrag. „Kontaktinhalt
    wiederherstellbar" gilt fuer den Feldvertrag v1 — nicht fuer alles, was an
    einem Kontakt haengt.
    """
    from personaljarvis.contacts.application.field_contract import (
        LIST_FIELDS,
        SCALAR_FIELDS,
    )

    mid = _freigegebene_loeschung(module, dienst)
    dienst._sichere_loeschziel(mid)
    doc = _gelesen(ablage, mid)

    erlaubt = ({"contactType", "birthday"}
               | set(SCALAR_FIELDS.values())
               | {kanonisch for kanonisch, _ in LIST_FIELDS.values()})
    assert set(doc["fields"]) <= erlaubt

    # Und keine der Familien ausserhalb des Vertrags steht darin — auch nicht
    # zufaellig unter einem anderen Namen.
    flach = json.dumps(doc["fields"]).lower()
    for familie in AUSSERHALB_V1:
        assert familie not in flach


def test_die_nicht_gedeckten_familien_werden_sehr_wohl_gelesen():
    """Genau das macht die Grenze zu einem Befund und nicht zu einer Fussnote.

    Waeren diese Familien Jarvis unbekannt, waere ihr Fehlen in der Sicherung
    folgenlos. Sie werden gelesen und lokal gehalten — der Verlust beim
    Loeschen ist also real und nicht theoretisch.
    """
    from pathlib import Path

    wurzel = Path(__file__).resolve().parents[3]
    sidecar = (wurzel / "native/contacts-bridge/src/sidecar.swift").read_text(
        encoding="utf-8")
    for schluessel in ("socialProfiles", "instantMessages", "relations"):
        assert schluessel in sidecar

    schema = (wurzel / "src/personaljarvis/base/db/migrations/versions"
              / "m0002_contacts.py").read_text(encoding="utf-8")
    for tabelle in ("contact_social_profiles", "contact_instant_messages",
                    "contact_relations"):
        assert f"CREATE TABLE {tabelle}" in schema


# ═══ H · Kein Testlauf beruehrt die produktive Ablage ═══════════════════════
def test_die_umleitung_der_sicherungsablage_ist_in_kraft(tmp_path):
    """Der Waechter ueber der autouse-Umleitung in `conftest.py`.

    Ohne ihn koennte die Umleitung verschwinden, ohne dass ein Test rot wird —
    die Sicherungen landeten dann still im Benutzerverzeichnis, und genau das
    ist am 2026-08-17 passiert. Dieser Test wird rot, sobald die Vorgabe
    wieder auf das Datenverzeichnis zeigt.
    """
    from pathlib import Path

    from personaljarvis.contacts.application.delete_gate import (
        field_state_dir,
        field_state_path,
    )

    vorgabe = field_state_dir()
    assert vorgabe.is_relative_to(tmp_path.parent.parent), (
        f"Die Sicherungsablage zeigt auf {vorgabe} — das ist kein Testort")
    assert ".openjarvis" not in str(vorgabe)
    assert Path.home() / ".openjarvis" not in vorgabe.parents

    # Und der Weg ueber `field_state_path` erbt die Umleitung, nicht nur der
    # direkte Aufruf: Sonst schriebe das Gate weiter am Waechter vorbei.
    assert field_state_path("irgendeine-kennung").parent == vorgabe

    # Ein ausdruecklich uebergebener Ort bleibt unberuehrt — umgeleitet wird
    # die Vorgabe, nicht der Parameter.
    eigen = tmp_path / "woanders"
    assert field_state_path("k", basis=eigen).parent == eigen


# ═══ I · Das Kontingent wirkt auf dem produktiven Weg ═══════════════════════
#
# Der Befund aus dem Livetest vom 2026-08-17: Jarvis schrieb zweimal in den
# echten Container, und der Zaehler stand danach unveraendert auf zehn von
# zehn. `claim_quota` sass ausschliesslich im aelteren Dienstweg — produktiv
# geht dort keine Mutation entlang. Diese Tests messen den Weg, den das
# Produkt tatsaechlich geht: Claim ueber den App-Prozess-Kanal.
def _kanal(module, ablage, urkunde, *, delete=False):
    from personaljarvis.contacts.application.app_channel import (
        fake_debug_capabilities,
    )

    return AppExecutionService(
        module,
        channel_capabilities=fake_debug_capabilities(update=True,
                                                     delete=delete),
        backup_dir=ablage, release_path=urkunde)


def _urkunde(tmp_path, *, granted_at="2026-08-17T20:42:27Z"):
    import os

    from personaljarvis.contacts.application.write_release import (
        MODE_STANDING,
        WRITE_RELEASE_CAPABILITY,
        WRITE_RELEASE_CONTRACT_V2,
    )

    ordner = tmp_path / "urkunde"
    ordner.mkdir(exist_ok=True)
    os.chmod(ordner, 0o700)
    pfad = ordner / "contacts-write-release.json"
    pfad.write_text(json.dumps({
        "contract": WRITE_RELEASE_CONTRACT_V2,
        "capability": WRITE_RELEASE_CAPABILITY,
        "mode": MODE_STANDING,
        "operations": ["create", "update"],
        "granted_at": granted_at,
        "reason": "Im Produkt eingeschaltet nach Eigentuemerauthentisierung",
    }), encoding="utf-8")
    os.chmod(pfad, 0o600)
    return pfad


def _stand(module, urkunde):
    from personaljarvis.base.db.unit_of_work import UnitOfWork
    from personaljarvis.contacts.application.write_quota import (
        activation_id,
        quota_state,
    )
    from personaljarvis.contacts.application.write_release import (
        read_write_release,
    )

    fabrik = module._factory if hasattr(module, "_factory") else module.factory
    with UnitOfWork(fabrik) as uow:
        return quota_state(uow, activation_id(read_write_release(urkunde)))


def _freigegebene_aenderung(module, dienst) -> str:
    from personaljarvis.contacts.application.commands import ContactPatch

    from .test_mutation_pipeline import _update

    _container_bekannt(module)
    kontakt = _lokalen_kontakt_anlegen(module)
    vorgang = dienst.prepare(_update(patch=ContactPatch({"nickname": "Neu"})))
    dienst.grant(vorgang.mutation_id,
                 decision=owner_decision_for_tests(MENSCH))
    assert kontakt is not None
    return vorgang.mutation_id


def test_ein_claim_verbraucht_kontingent(module, dienst, ablage, tmp_path):
    """Der Nachweis, der im Livetest gefehlt hat."""
    urkunde = _urkunde(tmp_path)
    kanal = _kanal(module, ablage, urkunde)
    assert _stand(module, urkunde).used == 0

    kanal.claim(_freigegebene_aenderung(module, dienst))

    assert _stand(module, urkunde).used == 1


def test_der_elfte_claim_wird_abgewiesen(module, dienst, ablage, tmp_path):
    """Die Grenze wirkt dort, wo produktiv geschrieben wird."""
    from personaljarvis.contacts.application.errors import WriteQuotaExhausted
    from personaljarvis.contacts.application.write_quota import (
        QUOTA_PER_ACTIVATION,
    )

    urkunde = _urkunde(tmp_path)
    kanal = _kanal(module, ablage, urkunde)
    for _ in range(QUOTA_PER_ACTIVATION):
        kanal.claim(_freigegebene_aenderung(module, dienst))

    letzte = _freigegebene_aenderung(module, dienst)
    with pytest.raises(WriteQuotaExhausted):
        kanal.claim(letzte)

    # Nichts verbraucht, nichts beansprucht: Der Vorgang bleibt ausfuehrbar,
    # sobald der Eigentuemer neu freigibt.
    assert _zeile(module, letzte)["state"] == "approved"


def test_beide_wege_meinen_dieselbe_aktivierung(module, dienst, ablage,
                                                tmp_path):
    """Sonst haette der Eigentuemer zwanzig Schreibvorgaenge statt zehn."""
    urkunde = _urkunde(tmp_path)
    kanal = _kanal(module, ablage, urkunde)
    ueber_kanal = kanal._aktivierung()

    from personaljarvis.contacts.application import ContactsMutationService

    ueber_dienst = ContactsMutationService(
        module, ziel_attrappe(), release_path=urkunde)._aktivierung()
    assert ueber_kanal == ueber_dienst is not None


def ziel_attrappe():
    return JedeBeruehrungZaehlt()
