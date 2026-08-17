"""Nativer Create-Pfad: Feldvertrag, Freigabe, Read-back, Spiegel.

**Kontaktfrei.** Kein `CNContactStore`, kein Sidecar, keine Livedatenbank:
alle Datenbanken sind temporär, alle Kontakte erfunden, alle Providerwerte
Attrappen. Kein Test dieser Datei darf einen Provider aufrufen — mehrere
prüfen genau das.

Die native Seite selbst (Objective-C und Rust) prüft ihre eigene Suite
(`cargo test contacts_create`, Fake-Operationen im Shim). Hier steht der
Kern: Was er aus einem Bericht macht, was er ablehnt, und was er lokal
nachführt.
"""

from __future__ import annotations

import json
import os
import stat
from datetime import datetime, timedelta, timezone

import pytest

from personaljarvis.base.approvals import owner_decision_for_tests

from personaljarvis.contacts.application.app_channel import (
    MODE_DISABLED,
    MODE_NATIVE_CREATE,
    app_channel_capabilities,
)
from personaljarvis.contacts.application.app_execution import (
    AppExecutionService,
    ChannelNotEnabled,
)
from personaljarvis.contacts.application.commands import (
    ContactDraft,
    CreateContact,
)
from personaljarvis.contacts.application.execution_contracts import (
    ExecutionReportV1,
    parse_execution_report,
)
from personaljarvis.contacts.application.field_contract import (
    canonical_payload,
    parse_canonical_payload,
    readback_digest,
)
from personaljarvis.contacts.application.mutation_service import (
    ContactsMutationService,
    MutationState,
)
from personaljarvis.contacts.application.write_release import (
    WRITE_RELEASE_CONTRACT,
    WRITE_RELEASE_FILENAME,
    read_write_release,
)
from personaljarvis.contacts.domain.capabilities import ContactCapabilitySet
from personaljarvis.contacts.domain.enums import InitiationContext
from personaljarvis.contacts.domain.models import ContactSyncState
from personaljarvis.contacts.repositories.sqlite import SqliteSyncStateRepository

from .conftest import WORKSPACE, new_id

KONTO = "apple-local"
CONTAINER = "01234567-89AB-CDEF-0123-456789ABCDEF:ABAccount"
MENSCH = "lukas"
KENNUNG = "FAKE:ABPerson-0001"

#: Der synthetische Testkontakt — dieselben Werte wie im Livetest.
ENTWURF = {
    "given_name": "Jarvis",
    "family_name": "Create Intel Test 2026-08-04",
    "organization_name": "OpenJarvis Synthetic Test",
    "emails": [{"label": "work",
                "value": "jarvis-create-intel-2026-08-04@example.invalid"}],
    "phones": [{"label": "mobile", "value": "+49 000 0000000"}],
}


class NieGerufenerProvider:
    def apply(self, *args, **kwargs):        # pragma: no cover - darf nie laufen
        raise AssertionError("Der Kern ruft im Create-Pfad keinen Provider")


CAPS = ContactCapabilitySet(create_supported=True)


@pytest.fixture
def modul(module):
    with module.unit_of_work() as uow:
        SqliteSyncStateRepository(uow).upsert(ContactSyncState(
            provider_account_id=KONTO, container_identifier=CONTAINER,
            key_set_version="v1", mode="delta", cursor_token="TOKEN",
            cursor_taken_at="2026-08-04T09:00:00+00:00"))
    module._capabilities = CAPS
    module._mutation_service = ContactsMutationService(
        module, NieGerufenerProvider(), capabilities=CAPS)
    return module


def freigabe_schreiben(pfad, *, operations=("create",), stunden=1,
                       contract=WRITE_RELEASE_CONTRACT, grund="Testlauf",
                       modus=0o600):
    pfad.write_text(json.dumps({
        "contract": contract,
        "operations": list(operations),
        "expires_at": (datetime.now(timezone.utc)
                       + timedelta(hours=stunden)).isoformat(),
        "reason": grund,
    }), encoding="utf-8")
    os.chmod(pfad, modus)
    return pfad


def _vorbereitet(modul, *, freigeben: bool = True, entwurf=None) -> str:
    service = modul.mutation_service()
    vorgang = service.prepare(CreateContact(
        mutation_id=new_id(), idempotency_key=new_id(),
        provider_account_id=KONTO, workspace_id=WORKSPACE, actor=MENSCH,
        initiation_context=InitiationContext.USER_DIRECT,
        correlation_id=new_id(), container_identifier=CONTAINER,
        draft=ContactDraft(dict(entwurf or ENTWURF))))
    if freigeben:
        service.grant(vorgang.mutation_id, decision=owner_decision_for_tests(MENSCH))
    return vorgang.mutation_id


def _rueckgabe(entwurf=None) -> dict:
    """Der kanonische Zustand, den ein Read-back liefern würde."""
    from personaljarvis.contacts.application.field_contract import (
        parse_create_fields,
    )
    return canonical_payload(parse_create_fields(dict(entwurf or ENTWURF)))


def _bericht(auftrag, **abweichungen) -> ExecutionReportV1:
    basis = {
        "operation_id": auftrag.operation_id,
        "mutation_id": auftrag.mutation_id,
        "operation_type": "create",
        "outcome": "applied",
        "send_attempted": True,
        "save_request_count": 1,
        "readback_status": "confirmed",
        "provider_identifier": KENNUNG,
        "provider_identifier_digest": "a" * 64,
        "readback_contact": _rueckgabe(),
        "provider_completed_at": "2026-08-04T10:00:00+00:00",
    }
    basis.update(abweichungen)
    return ExecutionReportV1(**basis)


def _zeile(modul, mutation_id):
    with modul.unit_of_work() as uow:
        return uow.execute(
            "SELECT * FROM contacts_mutations WHERE mutation_id = ?",
            (mutation_id,)).fetchone()


# ═══ A · Die Schreibfreigabe ════════════════════════════════════════════════
class TestSchreibfreigabe:
    def test_ohne_datei_gibt_es_keine_freigabe(self, tmp_path):
        assert read_write_release(tmp_path / WRITE_RELEASE_FILENAME) is None

    def test_eine_gueltige_freigabe_oeffnet_genau_create(self, tmp_path):
        os.chmod(tmp_path, 0o700)
        f = freigabe_schreiben(tmp_path / WRITE_RELEASE_FILENAME)
        freigabe = read_write_release(f)
        assert freigabe is not None
        assert freigabe.erlaubt("create") is True
        assert freigabe.erlaubt("update") is False
        assert freigabe.erlaubt("delete") is False

    def test_zu_offene_rechte_verwerfen_sie(self, tmp_path):
        os.chmod(tmp_path, 0o700)
        f = freigabe_schreiben(tmp_path / WRITE_RELEASE_FILENAME, modus=0o644)
        assert read_write_release(f) is None

    def test_ein_offenes_verzeichnis_verwirft_sie(self, tmp_path):
        f = freigabe_schreiben(tmp_path / WRITE_RELEASE_FILENAME)
        os.chmod(tmp_path, 0o755)
        assert read_write_release(f) is None

    def test_abgelaufen_ist_nicht_freigegeben(self, tmp_path):
        os.chmod(tmp_path, 0o700)
        f = freigabe_schreiben(tmp_path / WRITE_RELEASE_FILENAME, stunden=-1)
        assert read_write_release(f) is None

    def test_eine_freigabe_weit_in_der_zukunft_ist_ein_dauerzustand(self, tmp_path):
        os.chmod(tmp_path, 0o700)
        f = freigabe_schreiben(tmp_path / WRITE_RELEASE_FILENAME, stunden=48)
        assert read_write_release(f) is None

    def test_ein_fremder_vertrag_oeffnet_nichts(self, tmp_path):
        os.chmod(tmp_path, 0o700)
        f = freigabe_schreiben(tmp_path / WRITE_RELEASE_FILENAME,
                               contract="etwas-anderes")
        assert read_write_release(f) is None

    def test_ohne_begruendung_gibt_es_keine_freigabe(self, tmp_path):
        os.chmod(tmp_path, 0o700)
        f = freigabe_schreiben(tmp_path / WRITE_RELEASE_FILENAME, grund="  ")
        assert read_write_release(f) is None

    def test_jede_operation_bindet_einzeln(self, tmp_path):
        """Seit DEC-053 sind alle drei freigebbar — aber nur einzeln.

        Eine Datei, die `update` nennt, gibt kein `delete` frei. Das ist der
        Kern des Mechanismus: Wer eine Aenderung erlauben will, erlaubt damit
        keine Loeschung.
        """
        os.chmod(tmp_path, 0o700)
        f = freigabe_schreiben(tmp_path / WRITE_RELEASE_FILENAME,
                               operations=("update",))
        freigabe = read_write_release(f)
        assert freigabe is not None
        assert freigabe.erlaubt("update") is True
        assert freigabe.erlaubt("delete") is False
        assert freigabe.erlaubt("create") is False

    def test_eine_unbekannte_operation_macht_die_datei_ungueltig(self, tmp_path):
        os.chmod(tmp_path, 0o700)
        f = freigabe_schreiben(tmp_path / WRITE_RELEASE_FILENAME,
                               operations=("create", "merge"))
        assert read_write_release(f) is None

    def test_ein_symlink_ist_keine_freigabe(self, tmp_path):
        os.chmod(tmp_path, 0o700)
        echt = freigabe_schreiben(tmp_path / "echt.json")
        link = tmp_path / WRITE_RELEASE_FILENAME
        link.symlink_to(echt)
        assert read_write_release(link) is None

    def test_kein_umgebungsschalter_im_modul(self):
        from pathlib import Path
        quelle = (Path(__file__).resolve().parents[3]
                  / "src/personaljarvis/contacts/application/"
                  "write_release.py").read_text(encoding="utf-8")
        code = quelle.split('"""', 2)[-1]
        for verboten in ("os.environ", "getenv"):
            assert verboten not in code, verboten


# ═══ B · Capability-Handshake ═══════════════════════════════════════════════
class TestCapabilities:
    def test_ohne_freigabe_meldet_der_kanal_nichts_schreibbares(self, tmp_path):
        caps = app_channel_capabilities(
            release_path=tmp_path / WRITE_RELEASE_FILENAME)
        assert caps.channel_mode == MODE_DISABLED
        assert caps.create_supported is False
        assert caps.provider_write_enabled is False
        # Der native Code ist trotzdem vorhanden — das ist der Bauzustand.
        assert caps.native_create_available is True

    def test_mit_freigabe_meldet_der_kanal_genau_create(self, tmp_path):
        os.chmod(tmp_path, 0o700)
        f = freigabe_schreiben(tmp_path / WRITE_RELEASE_FILENAME)
        caps = app_channel_capabilities(release_path=f)
        assert caps.channel_mode == MODE_NATIVE_CREATE
        assert caps.create_supported is True
        assert caps.provider_write_enabled is True
        assert caps.update_supported is False
        assert caps.delete_supported is False
        assert caps.darf_ausfuehren("create") is True
        assert caps.darf_ausfuehren("update") is False

    def test_keine_umgebungsvariable_oeffnet_den_kanal(self, tmp_path,
                                                       monkeypatch):
        for name in ("OPENJARVIS_CONTACTS_WRITE_ENABLED",
                     "PERSONAL_JARVIS_PROVIDER_WRITE",
                     "CONTACTS_CREATE_ENABLED"):
            monkeypatch.setenv(name, "1")
        caps = app_channel_capabilities(
            release_path=tmp_path / WRITE_RELEASE_FILENAME)
        assert caps.provider_write_enabled is False


# ═══ C · Claim nur mit Freigabe ═════════════════════════════════════════════
class TestClaim:
    def test_ohne_freigabe_gibt_es_keinen_auftrag(self, modul, tmp_path):
        dienst = AppExecutionService(
            modul, channel_capabilities=app_channel_capabilities(
                release_path=tmp_path / WRITE_RELEASE_FILENAME))
        mutation_id = _vorbereitet(modul)
        with pytest.raises(ChannelNotEnabled):
            dienst.claim(mutation_id)

    def test_mit_freigabe_entsteht_genau_ein_auftrag(self, modul, tmp_path):
        os.chmod(tmp_path, 0o700)
        f = freigabe_schreiben(tmp_path / WRITE_RELEASE_FILENAME)
        dienst = AppExecutionService(
            modul, channel_capabilities=app_channel_capabilities(release_path=f))
        mutation_id = _vorbereitet(modul)
        auftrag = dienst.claim(mutation_id)
        assert auftrag.operation_type == "create"
        assert auftrag.payload_digest_matches() is True
        # Ein zweiter Claim ist ausgeschlossen — auch mit gueltiger Freigabe.
        with pytest.raises(Exception):
            dienst.claim(mutation_id)

    def test_der_auftrag_traegt_den_ausdruecklichen_container(self, modul,
                                                              tmp_path):
        os.chmod(tmp_path, 0o700)
        f = freigabe_schreiben(tmp_path / WRITE_RELEASE_FILENAME)
        dienst = AppExecutionService(
            modul, channel_capabilities=app_channel_capabilities(release_path=f))
        auftrag = dienst.claim(_vorbereitet(modul))
        assert auftrag.provider_target["container_identifier"] == CONTAINER


# ═══ D · Bericht mit Kennung und Read-back ══════════════════════════════════
class TestBerichtsvertrag:
    def test_die_rohe_kennung_ist_teil_des_vertrags(self):
        bericht = parse_execution_report({
            "operation_id": "0" * 36, "mutation_id": "1" * 36,
            "operation_type": "create", "outcome": "applied",
            "send_attempted": True, "save_request_count": 1,
            "readback_status": "confirmed",
            "provider_identifier": KENNUNG,
            "provider_identifier_digest": "a" * 64,
            "readback_contact": _rueckgabe(),
        })
        assert bericht.provider_identifier == KENNUNG
        assert bericht.readback_contact["givenName"] == "Jarvis"

    def test_eine_unbrauchbare_kennung_wird_abgewiesen(self):
        for kaputt in ("", 42, "x" * 600):
            with pytest.raises(Exception):
                parse_execution_report({
                    "operation_id": "0" * 36, "mutation_id": "1" * 36,
                    "operation_type": "create", "outcome": "applied",
                    "send_attempted": True, "save_request_count": 1,
                    "readback_status": "confirmed",
                    "provider_identifier": kaputt,
                })

    def test_ein_unbekanntes_feld_bleibt_verboten(self):
        with pytest.raises(Exception):
            parse_execution_report({
                "operation_id": "0" * 36, "mutation_id": "1" * 36,
                "operation_type": "create", "outcome": "not_sent",
                "send_attempted": False, "save_request_count": 0,
                "readback_status": "not_attempted",
                "provider_secret": "x",
            })


# ═══ E · Settle und lokale Nachführung ══════════════════════════════════════
class TestSettleUndSpiegel:
    @pytest.fixture
    def bereit(self, modul, tmp_path):
        os.chmod(tmp_path, 0o700)
        f = freigabe_schreiben(tmp_path / WRITE_RELEASE_FILENAME)
        dienst = AppExecutionService(
            modul, channel_capabilities=app_channel_capabilities(release_path=f))
        mutation_id = _vorbereitet(modul)
        return dienst, mutation_id, dienst.claim(mutation_id)

    def test_applied_fuehrt_den_lokalen_bestand_nach(self, modul, bereit):
        dienst, mutation_id, auftrag = bereit
        ergebnis = dienst.settle(mutation_id, _bericht(auftrag),
                                 claim_token=auftrag.claim_token)
        assert ergebnis.state == MutationState.PROVIDER_APPLIED_PENDING_RECONCILE

        zeile = _zeile(modul, mutation_id)
        assert zeile["state"] == MutationState.SUCCEEDED
        assert zeile["target_provider_identifier"] == KENNUNG
        assert zeile["target_contact_id"]
        erwartet = readback_digest(parse_canonical_payload(_rueckgabe()))
        assert zeile["readback_digest"] == erwartet

        with modul.unit_of_work() as uow:
            kontakte = uow.execute("SELECT * FROM contacts").fetchall()
            ids = uow.execute(
                "SELECT * FROM contact_external_ids").fetchall()
        assert len(kontakte) == 1
        assert len(ids) == 1
        assert ids[0]["provider_identifier"] == KENNUNG

    def test_dasselbe_settle_bleibt_idempotent(self, modul, bereit):
        dienst, mutation_id, auftrag = bereit
        bericht = _bericht(auftrag)
        dienst.settle(mutation_id, bericht, claim_token=auftrag.claim_token)
        zweites = dienst.settle(mutation_id, bericht,
                                claim_token=auftrag.claim_token)
        assert zweites.idempotent is True
        with modul.unit_of_work() as uow:
            assert uow.execute(
                "SELECT COUNT(*) c FROM contact_external_ids").fetchone()["c"] == 1
            assert uow.execute(
                "SELECT COUNT(*) c FROM contacts").fetchone()["c"] == 1

    def test_ein_abweichender_zweiter_bericht_wird_abgelehnt(self, modul, bereit):
        from personaljarvis.contacts.application.app_execution import (
            SettleConflict,
        )
        dienst, mutation_id, auftrag = bereit
        dienst.settle(mutation_id, _bericht(auftrag),
                      claim_token=auftrag.claim_token)
        with pytest.raises(SettleConflict):
            dienst.settle(mutation_id,
                          _bericht(auftrag, provider_identifier="FAKE:ANDERS"),
                          claim_token=auftrag.claim_token)

    def test_ohne_kennung_wird_nichts_gespiegelt(self, modul, bereit):
        dienst, mutation_id, auftrag = bereit
        dienst.settle(mutation_id,
                      _bericht(auftrag, outcome="outcome_unknown",
                               readback_status="failed",
                               provider_identifier=None,
                               readback_contact=None,
                               error_class="readback_failed"),
                      claim_token=auftrag.claim_token)
        zeile = _zeile(modul, mutation_id)
        assert zeile["state"] == MutationState.OUTCOME_UNKNOWN
        assert zeile["target_provider_identifier"] is None
        with modul.unit_of_work() as uow:
            assert uow.execute(
                "SELECT COUNT(*) c FROM contacts").fetchone()["c"] == 0

    def test_ohne_read_back_bleibt_der_vorgang_in_der_zwischenlage(self, modul,
                                                                   bereit):
        dienst, mutation_id, auftrag = bereit
        dienst.settle(mutation_id, _bericht(auftrag, readback_contact=None),
                      claim_token=auftrag.claim_token)
        zeile = _zeile(modul, mutation_id)
        assert zeile["state"] == \
            MutationState.PROVIDER_APPLIED_PENDING_RECONCILE
        assert zeile["target_provider_identifier"] == KENNUNG
        with modul.unit_of_work() as uow:
            assert uow.execute(
                "SELECT COUNT(*) c FROM contacts").fetchone()["c"] == 0

    def test_settle_ruft_keinen_provider(self, modul, bereit):
        # `NieGerufenerProvider.apply` wirft; ein sauberer Durchlauf beweist,
        # dass das Setteln ohne Providerkontakt auskommt.
        dienst, mutation_id, auftrag = bereit
        dienst.settle(mutation_id, _bericht(auftrag),
                      claim_token=auftrag.claim_token)

    def test_die_auditkette_ist_vollstaendig_und_pii_arm(self, modul, bereit):
        dienst, mutation_id, auftrag = bereit
        dienst.settle(mutation_id, _bericht(auftrag),
                      claim_token=auftrag.claim_token)
        with modul.unit_of_work() as uow:
            zeilen = uow.execute(
                "SELECT * FROM personal_audit_log WHERE subject_id = ? "
                "ORDER BY sequence", (mutation_id,)).fetchall()
            spalten = [r[1] for r in uow.execute(
                "PRAGMA table_info(personal_audit_log)")]
        stufen = [z["stage"] for z in zeilen]
        for pflicht in ("mutation_prepared", "approval_granted",
                        "execution_claimed", "execution_order_issued",
                        "provider_send_started", "provider_result_received",
                        "mutation_settled", "mutation_completed"):
            assert pflicht in stufen, pflicht
        # Die Kette traegt ausschliesslich Hashes: Es gibt gar keine Spalte,
        # in der ein Kontaktwert oder eine rohe Kennung stehen koennte.
        assert "payload_hash" in spalten
        assert not {"facts", "facts_json", "payload", "detail"} & set(spalten)
        gesamt = " ".join(str(tuple(z)) for z in zeilen)
        assert KENNUNG not in gesamt
        assert "Create Intel Test" not in gesamt
        # Die Kette ist verkettet und lueckenlos.
        assert all(z["prev_hash"] for z in zeilen[1:])

    def test_der_spiegel_erfindet_keine_providerdaten(self, modul, bereit):
        """Ein Read-back, der nicht dem Entwurf entspricht, gewinnt."""
        dienst, mutation_id, auftrag = bereit
        anders = dict(ENTWURF, given_name="Anders")
        dienst.settle(mutation_id,
                      _bericht(auftrag, readback_contact=_rueckgabe(anders)),
                      claim_token=auftrag.claim_token)
        with modul.unit_of_work() as uow:
            kontakt = uow.execute("SELECT * FROM contacts").fetchone()
        assert kontakt["given_name"] == "Anders"


# ═══ E2 · Der Kanal ist ein Jetzt-Zustand, kein Startwert ══════════════════
class TestKanalIstAktuell:
    """Ein eingefrorener Fähigkeitssatz überlebt seine Freigabe.

    Im Livetest am 2026-08-04 fiel es auf: Nach dem Entzug der Freigabe
    meldete der laufende Prozess den Kanal weiter als offen, weil die Route
    ihn einmal beim Start berechnet hatte. Der native Save hätte trotzdem
    verweigert — der App-Prozess liest die Datei bei jedem Lauf neu —, aber
    ein Handshake, der mehr behauptet als gilt, ist genau die Art Fehler,
    die man später glaubt.
    """

    def test_die_route_folgt_dem_entzug(self, module, tmp_path):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from personaljarvis.contacts.api.routes import create_contacts_router

        ordner = module._factory._path.parent
        os.chmod(ordner, 0o700)
        freigabe = freigabe_schreiben(ordner / WRITE_RELEASE_FILENAME)

        app = FastAPI()
        app.include_router(create_contacts_router(module))
        client = TestClient(app)

        offen = client.get("/v1/personal/contacts/app-channel").json()
        assert offen["channel_mode"] == MODE_NATIVE_CREATE
        assert offen["create_supported"] is True

        freigabe.unlink()
        zu = client.get("/v1/personal/contacts/app-channel").json()
        assert zu["channel_mode"] == MODE_DISABLED
        assert zu["create_supported"] is False
        assert zu["provider_write_enabled"] is False

    def test_der_claim_folgt_dem_entzug(self, modul, tmp_path):
        ordner = modul._factory._path.parent
        os.chmod(ordner, 0o700)
        freigabe = freigabe_schreiben(ordner / WRITE_RELEASE_FILENAME)
        dienst = AppExecutionService(
            modul,
            channel_capabilities=lambda: app_channel_capabilities(
                database_path=modul._factory._path))
        mutation_id = _vorbereitet(modul)

        freigabe.unlink()
        with pytest.raises(ChannelNotEnabled):
            dienst.claim(mutation_id)


# ═══ F · Sidecar bleibt schreibfrei ═════════════════════════════════════════
class TestSidecar:
    def test_der_sidecar_meldet_keine_schreibfaehigkeit(self):
        from pathlib import Path
        quelle = (Path(__file__).resolve().parents[3]
                  / "native/contacts-bridge/src/sidecar.swift").read_text(
            encoding="utf-8")
        for feld in ("createImplemented", "updateImplemented",
                     "deleteImplemented", "mutationsImplemented"):
            assert f'"{feld}": false' in quelle, feld

    def test_der_native_create_liegt_nicht_im_sidecar(self):
        from pathlib import Path
        quelle = (Path(__file__).resolve().parents[3]
                  / "native/contacts-bridge/src/sidecar.swift").read_text(
            encoding="utf-8")
        einstieg = quelle.split("func opCreate(")[1][:1200]
        assert "capability_denied" in einstieg


# ═══ G · Der native Code liegt im App-Prozess ═══════════════════════════════
class TestNativerOrt:
    def test_der_shim_gehoert_zur_app_und_nicht_zum_paket(self):
        from pathlib import Path
        wurzel = Path(__file__).resolve().parents[3]
        assert (wurzel / "frontend/src-tauri/objc/JCContactsCreate.m").is_file()
        assert (wurzel / "frontend/src-tauri/src/contacts_create.rs").is_file()
        import ast
        for datei in (wurzel / "src/personaljarvis").rglob("*.py"):
            # Kommentare und Docstrings nennen die Symbole als Abgrenzung —
            # geprueft wird der ausfuehrbare Code, nicht die Begruendung.
            baum = ast.parse(datei.read_text(encoding="utf-8"))
            for knoten in ast.walk(baum):
                if isinstance(knoten, ast.Constant) and isinstance(
                        knoten.value, str):
                    continue
                if isinstance(knoten, ast.Name):
                    assert "CNSaveRequest" not in knoten.id, datei
                    assert "CNMutableContact" not in knoten.id, datei

    def test_der_shim_schreibt_genau_ein_mal(self):
        from pathlib import Path
        quelle = (Path(__file__).resolve().parents[3]
                  / "frontend/src-tauri/objc/JCContactsCreate.m").read_text(
            encoding="utf-8")
        code = "\n".join(z for z in quelle.splitlines()
                         if not z.lstrip().startswith("//"))
        # Genau **ein** Save je Operation, nicht einer im ganzen Shim: Create
        # und der geteilte Update-/Delete-Pfad haben je eine Stelle. Mehr
        # waere ein zweiter Weg zum Provider — und genau den soll es nicht
        # geben.
        assert code.count("executeSaveRequest") == 2
        assert code.count("[req addContact:") == 1
        assert code.count("[req updateContact:") == 1
        assert code.count("[req deleteContact:") == 1
        assert code.count("CNSaveRequest alloc") == 2

    def test_der_shim_liest_ueber_die_kennung_und_nie_ueber_den_namen(self):
        from pathlib import Path
        quelle = (Path(__file__).resolve().parents[3]
                  / "frontend/src-tauri/objc/JCContactsCreate.m").read_text(
            encoding="utf-8")
        assert "predicateForContactsWithIdentifiers" in quelle
        assert "predicateForContactsMatchingName" not in quelle

    def test_der_shim_liest_keine_zurueckgestellten_felder(self):
        from pathlib import Path
        quelle = (Path(__file__).resolve().parents[3]
                  / "frontend/src-tauri/objc/JCContactsCreate.m").read_text(
            encoding="utf-8")
        for verboten in ("CNContactNoteKey", "CNContactImageDataKey",
                         "CNContactThumbnailImageDataKey",
                         "CNContactSocialProfilesKey",
                         "CNContactInstantMessageAddressesKey",
                         "CNContactRelationsKey",
                         "CNContactNonGregorianBirthdayKey"):
            assert verboten not in quelle, verboten


def test_die_dateirechte_der_freigabe_sind_teil_des_vertrags(tmp_path):
    """Der Vertrag steht in der Datei — und in ihren Rechten."""
    os.chmod(tmp_path, 0o700)
    f = freigabe_schreiben(tmp_path / WRITE_RELEASE_FILENAME)
    assert stat.S_IMODE(f.stat().st_mode) == 0o600
    assert read_write_release(f) is not None
