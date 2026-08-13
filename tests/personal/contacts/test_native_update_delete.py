"""Nativer Update- und Delete-Pfad: Patch, Konflikt, Schutz, Abwesenheit.

**Kontaktfrei.** Kein `CNContactStore`, kein Sidecar, keine Livedatenbank —
temporäre Datenbanken, erfundene Kontakte, Attrappen als Providerwerte. Die
Objective-C-Seite prüft ihre eigene Suite gegen Fake-Operationen im Shim
(`cargo test contacts_create`); hier steht der Kern.

Der rote Faden dieser Datei ist der **Vorher-Vergleich**: Update und Delete
ändern etwas, das schon existiert, und dürfen das nur, wenn der Zustand noch
der ist, den der Mensch freigegeben hat. Alles andere endet vor dem Save.
"""

from __future__ import annotations

import os

import pytest

from personaljarvis.base.approvals import owner_decision

from personaljarvis.contacts.application.app_channel import (
    MODE_DISABLED,
    MODE_NATIVE_CREATE,
    app_channel_capabilities,
)
from personaljarvis.contacts.application.app_execution import (
    AppExecutionService,
    ChannelNotEnabled,
    DeleteConfirmationRequired,
)
from personaljarvis.contacts.application.commands import (
    ContactPatch,
    DeleteContact,
    UpdateContact,
)
from personaljarvis.contacts.application.errors import MutationNotExecutable
from personaljarvis.contacts.application.field_contract import (
    canonical_payload,
    project_local_contact,
    readback_digest,
)
from personaljarvis.contacts.application.mutation_service import MutationState
from personaljarvis.contacts.application.write_release import (
    WRITE_RELEASE_FILENAME,
)
from personaljarvis.contacts.domain.enums import InitiationContext

from .conftest import WORKSPACE, new_id
from .test_native_create import (
    CAPS,
    CONTAINER,
    KONTO,
    MENSCH,
    NieGerufenerProvider,
    _bericht,
    _vorbereitet,
    freigabe_schreiben,
)


@pytest.fixture
def modul(module):
    """Dasselbe vorbereitete Modul wie im Create-Pfad.

    Bewusst hier definiert statt importiert: Ein importierter Fixture-Name
    kollidiert für jeden Linter mit den gleichnamigen Testparametern, und
    zweiundzwanzig `noqa`-Kommentare wären ein hoher Preis für eine
    gesparte Fixture-Definition.
    """
    from personaljarvis.contacts.application.mutation_service import (
        ContactsMutationService,
    )
    from personaljarvis.contacts.domain.models import ContactSyncState
    from personaljarvis.contacts.repositories.sqlite import (
        SqliteSyncStateRepository,
    )

    with module.unit_of_work() as uow:
        SqliteSyncStateRepository(uow).upsert(ContactSyncState(
            provider_account_id=KONTO, container_identifier=CONTAINER,
            key_set_version="v1", mode="delta", cursor_token="TOKEN",
            cursor_taken_at="2026-08-04T09:00:00+00:00"))
    module._capabilities = CAPS
    module._mutation_service = ContactsMutationService(
        module, NieGerufenerProvider(), capabilities=CAPS)
    return module


def _angelegt(modul, tmp_path) -> tuple[str, str]:
    """Legt über den Create-Pfad einen Kontakt an und gibt (contact_id, pid)."""
    os.chmod(tmp_path, 0o700)
    f = freigabe_schreiben(tmp_path / WRITE_RELEASE_FILENAME)
    dienst = AppExecutionService(
        modul, channel_capabilities=app_channel_capabilities(release_path=f))
    mutation_id = _vorbereitet(modul)
    auftrag = dienst.claim(mutation_id)
    dienst.settle(mutation_id, _bericht(auftrag), claim_token=auftrag.claim_token)
    with modul.unit_of_work() as uow:
        zeile = uow.execute(
            "SELECT target_contact_id, target_provider_identifier "
            "FROM contacts_mutations WHERE mutation_id = ?",
            (mutation_id,)).fetchone()
    return zeile["target_contact_id"], zeile["target_provider_identifier"]


def _update_vorbereitet(modul, pid: str, patch: dict) -> str:
    _modul_darf(modul, "update", "delete")
    service = modul.mutation_service()
    vorgang = service.prepare(UpdateContact(
        mutation_id=new_id(), idempotency_key=new_id(),
        provider_account_id=KONTO, workspace_id=WORKSPACE, actor=MENSCH,
        initiation_context=InitiationContext.USER_DIRECT,
        correlation_id=new_id(), target_provider_identifier=pid,
        patch=ContactPatch(dict(patch))))
    service.grant(vorgang.mutation_id, decision=owner_decision(MENSCH))
    return vorgang.mutation_id


def _delete_vorbereitet(modul, pid: str) -> str:
    _modul_darf(modul, "update", "delete")
    service = modul.mutation_service()
    vorgang = service.prepare(DeleteContact(
        mutation_id=new_id(), idempotency_key=new_id(),
        provider_account_id=KONTO, workspace_id=WORKSPACE, actor=MENSCH,
        initiation_context=InitiationContext.USER_DIRECT,
        correlation_id=new_id(), target_provider_identifier=pid))
    service.grant(vorgang.mutation_id, decision=owner_decision(MENSCH))
    return vorgang.mutation_id


def _modul_darf(modul, *operationen) -> None:
    """Erklärt dem Modul, welche Operationen der Kanal gerade trägt.

    Produktiv leitet `capability_set_from_handshake` das aus derselben
    Freigabedatei ab; im Test wird es gesetzt, damit `prepare` überhaupt
    stattfindet — geprüft wird der Kanal an anderer Stelle.
    """
    from personaljarvis.contacts.domain.capabilities import ContactCapabilitySet

    caps = ContactCapabilitySet(
        create_supported=True,
        update_supported="update" in operationen,
        delete_supported="delete" in operationen)
    modul._capabilities = caps
    modul._mutation_service._capabilities = caps


def _dienst(modul, tmp_path, operations):
    _modul_darf(modul, *operations)
    os.chmod(tmp_path, 0o700)
    f = freigabe_schreiben(tmp_path / WRITE_RELEASE_FILENAME,
                           operations=operations)
    return AppExecutionService(
        modul, channel_capabilities=app_channel_capabilities(release_path=f))


# ═══ A · Der Vorzustand hängt an der Freigabe ═══════════════════════════════
class TestVorzustandGebunden:
    def test_update_traegt_den_lokalen_zustand_und_seinen_digest(
            self, modul, tmp_path):
        contact_id, pid = _angelegt(modul, tmp_path)
        mutation_id = _update_vorbereitet(modul, pid,
                                          {"job_title": "Neu"})
        with modul.unit_of_work() as uow:
            zeile = uow.execute(
                "SELECT payload_json FROM contacts_mutations "
                "WHERE mutation_id = ?", (mutation_id,)).fetchone()
            erwartet = project_local_contact(uow, contact_id)
        import json
        payload = json.loads(zeile["payload_json"])
        assert payload["expectedPrevious"] == canonical_payload(erwartet)
        assert payload["expectedFieldsDigest"] == readback_digest(erwartet)

    def test_delete_traegt_denselben_beleg(self, modul, tmp_path):
        contact_id, pid = _angelegt(modul, tmp_path)
        mutation_id = _delete_vorbereitet(modul, pid)
        import json
        with modul.unit_of_work() as uow:
            payload = json.loads(uow.execute(
                "SELECT payload_json FROM contacts_mutations "
                "WHERE mutation_id = ?", (mutation_id,)).fetchone()["payload_json"])
            erwartet = project_local_contact(uow, contact_id)
        assert payload["expectedPrevious"] == canonical_payload(erwartet)
        assert payload["expectedFieldsDigest"] == readback_digest(erwartet)

    def test_create_hat_keinen_vorzustand(self, modul, tmp_path):
        """Ein `null` im Payload änderte den Digest ohne jede Aussage."""
        import json
        mutation_id = _vorbereitet(modul, freigeben=False)
        with modul.unit_of_work() as uow:
            payload = json.loads(uow.execute(
                "SELECT payload_json FROM contacts_mutations "
                "WHERE mutation_id = ?", (mutation_id,)).fetchone()["payload_json"])
        assert "expectedPrevious" not in payload
        assert "expectedFieldsDigest" not in payload

    def test_der_auftrag_reicht_den_vorzustand_weiter(self, modul, tmp_path):
        contact_id, pid = _angelegt(modul, tmp_path)
        dienst = _dienst(modul, tmp_path, ("update",))
        mutation_id = _update_vorbereitet(modul, pid, {"job_title": "Neu"})
        auftrag = dienst.claim(mutation_id)
        assert auftrag.operation_type == "update"
        assert auftrag.canonical_payload["expectedPrevious"]
        assert auftrag.canonical_payload["expectedFieldsDigest"]
        assert auftrag.provider_target["provider_identifier"] == pid
        # Der Digest deckt den Vorzustand mit ab.
        assert auftrag.payload_digest_matches()


# ═══ B · Die Freigabe bindet je Operation ══════════════════════════════════
class TestFreigabeJeOperation:
    def test_update_ohne_freigabe_gibt_keinen_auftrag(self, modul, tmp_path):
        contact_id, pid = _angelegt(modul, tmp_path)
        dienst = _dienst(modul, tmp_path, ("create",))
        mutation_id = _update_vorbereitet(modul, pid, {"job_title": "X"})
        with pytest.raises(ChannelNotEnabled):
            dienst.claim(mutation_id)

    def test_delete_ohne_freigabe_gibt_keinen_auftrag(self, modul, tmp_path):
        contact_id, pid = _angelegt(modul, tmp_path)
        dienst = _dienst(modul, tmp_path, ("update",))
        mutation_id = _delete_vorbereitet(modul, pid)
        with pytest.raises(ChannelNotEnabled):
            dienst.claim(mutation_id, confirm_delete=True)

    def test_die_faehigkeiten_folgen_der_datei(self, tmp_path):
        os.chmod(tmp_path, 0o700)
        f = freigabe_schreiben(tmp_path / WRITE_RELEASE_FILENAME,
                               operations=("update", "delete"))
        caps = app_channel_capabilities(release_path=f)
        assert caps.channel_mode == MODE_NATIVE_CREATE
        assert caps.create_supported is False
        assert caps.update_supported is True
        assert caps.delete_supported is True
        f.unlink()
        zu = app_channel_capabilities(release_path=f)
        assert zu.channel_mode == MODE_DISABLED
        assert zu.update_supported is False and zu.delete_supported is False


# ═══ C · Die zusätzliche Löschbestätigung (R2, DEC-053) ════════════════════
class TestLoeschbestaetigung:
    def test_delete_ohne_bestaetigung_wird_abgewiesen(self, modul, tmp_path):
        contact_id, pid = _angelegt(modul, tmp_path)
        dienst = _dienst(modul, tmp_path, ("delete",))
        mutation_id = _delete_vorbereitet(modul, pid)
        with pytest.raises(DeleteConfirmationRequired):
            dienst.claim(mutation_id)

    def test_die_abweisung_beansprucht_nichts(self, modul, tmp_path):
        """Eine fehlende Bestätigung darf keinen Versuch verbrauchen."""
        contact_id, pid = _angelegt(modul, tmp_path)
        dienst = _dienst(modul, tmp_path, ("delete",))
        mutation_id = _delete_vorbereitet(modul, pid)
        with pytest.raises(DeleteConfirmationRequired):
            dienst.claim(mutation_id)
        with modul.unit_of_work() as uow:
            zeile = uow.execute(
                "SELECT state, attempt_count FROM contacts_mutations "
                "WHERE mutation_id = ?", (mutation_id,)).fetchone()
        assert zeile["state"] == MutationState.APPROVED
        assert zeile["attempt_count"] == 0
        # Und danach geht es mit Bestätigung noch.
        auftrag = dienst.claim(mutation_id, confirm_delete=True)
        assert auftrag.operation_type == "delete"

    def test_bestaetigung_bei_update_ist_ein_fehler(self, modul, tmp_path):
        contact_id, pid = _angelegt(modul, tmp_path)
        dienst = _dienst(modul, tmp_path, ("update",))
        mutation_id = _update_vorbereitet(modul, pid, {"job_title": "X"})
        with pytest.raises(MutationNotExecutable):
            dienst.claim(mutation_id, confirm_delete=True)


# ═══ D · Settle: Read-back, Tombstone, Idempotenz ══════════════════════════
class TestSettle:
    def _auftrag(self, modul, tmp_path, loeschen: bool):
        contact_id, pid = _angelegt(modul, tmp_path)
        ops = ("delete",) if loeschen else ("update",)
        dienst = _dienst(modul, tmp_path, ops)
        mutation_id = (_delete_vorbereitet(modul, pid) if loeschen
                       else _update_vorbereitet(modul, pid,
                                                {"job_title": "Neu"}))
        auftrag = dienst.claim(mutation_id, confirm_delete=loeschen)
        return dienst, mutation_id, auftrag, contact_id, pid

    def test_update_applied_fuehrt_den_spiegel_nach(self, modul, tmp_path):
        dienst, mid, auftrag, cid, pid = self._auftrag(modul, tmp_path, False)
        # Der Read-back zeigt den Zielzustand: Vorzustand plus Patch.
        nachher = dict(auftrag.canonical_payload["expectedPrevious"])
        nachher["jobTitle"] = "Neu"
        bericht = _bericht(auftrag, operation_type="update",
                           readback_contact=nachher, provider_identifier=pid)
        ergebnis = dienst.settle(mid, bericht, claim_token=auftrag.claim_token)
        assert ergebnis.state in (MutationState.SUCCEEDED,
                                  "provider_applied_pending_reconcile")
        with modul.unit_of_work() as uow:
            zeile = uow.execute("SELECT job_title FROM contacts WHERE id = ?",
                                (cid,)).fetchone()
        assert zeile["job_title"] == "Neu"

    def test_delete_applied_setzt_tombstone_und_haelt_die_identitaet(
            self, modul, tmp_path):
        dienst, mid, auftrag, cid, pid = self._auftrag(modul, tmp_path, True)
        bericht = _bericht(auftrag, operation_type="delete",
                           readback_contact=None, provider_identifier=pid,
                           readback_status="absent_confirmed")
        dienst.settle(mid, bericht, claim_token=auftrag.claim_token)
        with modul.unit_of_work() as uow:
            zeile = uow.execute(
                "SELECT is_tombstone, deleted_at FROM contacts WHERE id = ?",
                (cid,)).fetchone()
            identitaeten = uow.execute(
                "SELECT COUNT(*) n FROM contact_external_ids WHERE contact_id = ?",
                (cid,)).fetchone()["n"]
        assert zeile["is_tombstone"] == 1
        assert zeile["deleted_at"] is not None
        # Die Identität bleibt: sie ist der Beleg, wovon der Tombstone spricht.
        assert identitaeten == 1

    def test_ein_zweiter_gleicher_bericht_wirkt_nicht_erneut(
            self, modul, tmp_path):
        dienst, mid, auftrag, cid, pid = self._auftrag(modul, tmp_path, True)
        bericht = _bericht(auftrag, operation_type="delete",
                           readback_contact=None, provider_identifier=pid,
                           readback_status="absent_confirmed")
        with modul.unit_of_work() as uow:
            vorher = uow.execute(
                "SELECT COUNT(*) n FROM contacts_tombstones").fetchone()["n"]
        dienst.settle(mid, bericht, claim_token=auftrag.claim_token)
        zweit = dienst.settle(mid, bericht, claim_token=auftrag.claim_token)
        # Der zweite Aufruf meldet den **jetzigen** Stand, nicht den
        # Zwischenzustand des ersten — und wirkt nicht erneut. Genau das ist
        # Idempotenz: keine zweite Wirkung, nicht dieselbe Antwortzeichenkette.
        assert zweit.idempotent is True
        assert zweit.state == MutationState.SUCCEEDED
        with modul.unit_of_work() as uow:
            nachher = uow.execute(
                "SELECT COUNT(*) n FROM contacts_tombstones").fetchone()["n"]
        assert nachher == vorher + 1

    def test_ein_abweichender_zweiter_bericht_wird_abgelehnt(
            self, modul, tmp_path):
        from personaljarvis.contacts.application.app_execution import (
            SettleConflict,
        )
        dienst, mid, auftrag, cid, pid = self._auftrag(modul, tmp_path, True)
        erst = _bericht(auftrag, operation_type="delete",
                        readback_contact=None, provider_identifier=pid,
                        readback_status="absent_confirmed")
        dienst.settle(mid, erst, claim_token=auftrag.claim_token)
        anders = _bericht(auftrag, operation_type="delete",
                          outcome="outcome_unknown",
                          readback_status="failed", readback_contact=None)
        with pytest.raises(SettleConflict):
            dienst.settle(mid, anders, claim_token=auftrag.claim_token)

    def test_ohne_belegten_readback_wird_nichts_nachgefuehrt(
            self, modul, tmp_path):
        dienst, mid, auftrag, cid, pid = self._auftrag(modul, tmp_path, False)
        bericht = _bericht(auftrag, operation_type="update",
                           outcome="outcome_unknown",
                           readback_status="failed", readback_contact=None)
        ergebnis = dienst.settle(mid, bericht, claim_token=auftrag.claim_token)
        assert ergebnis.state == MutationState.OUTCOME_UNKNOWN
        with modul.unit_of_work() as uow:
            zeile = uow.execute(
                "SELECT job_title, is_tombstone FROM contacts WHERE id = ?",
                (cid,)).fetchone()
        # Weder Patch noch Tombstone: ohne Beleg wird nichts erfunden.
        assert zeile["job_title"] != "Neu"
        assert zeile["is_tombstone"] == 0

    def test_settle_ruft_keinen_provider(self, modul, tmp_path):
        dienst, mid, auftrag, cid, pid = self._auftrag(modul, tmp_path, True)
        bericht = _bericht(auftrag, operation_type="delete",
                           readback_contact=None, provider_identifier=pid,
                           readback_status="absent_confirmed")
        # `NieGerufenerProvider.apply` wirft; ein Settle, das ihn anfasste,
        # käme hier nicht durch.
        dienst.settle(mid, bericht, claim_token=auftrag.claim_token)


# ═══ E · Statische Schranken des nativen Pfads ═════════════════════════════
class TestNativeSchranken:
    def _shim(self) -> str:
        from pathlib import Path
        return (Path(__file__).resolve().parents[3]
                / "frontend/src-tauri/objc/JCContactsCreate.m").read_text(
                    encoding="utf-8")

    def _rust(self) -> str:
        from pathlib import Path
        return (Path(__file__).resolve().parents[3]
                / "frontend/src-tauri/src/contacts_create.rs").read_text(
                    encoding="utf-8")

    def test_der_shim_liest_das_ziel_nur_ueber_die_kennung(self):
        code = self._shim()
        assert "predicateForContactsWithIdentifiers" in code
        # Keine Namenssuche, in keiner Form.
        for verboten in ("predicateForContactsMatchingName",
                         "predicateForContactsMatchingEmailAddress",
                         "predicateForContactsMatchingPhoneNumber"):
            assert verboten not in code, verboten

    def test_der_shim_vergleicht_vor_dem_save(self):
        code = self._shim()
        vergleich = code.index("isEqualToDictionary:erwartetVorher")
        save = code.index("ops.save(kopie, kind")
        assert vergleich < save, "Der Vergleich muss vor dem Save stehen"

    def test_der_shim_schuetzt_die_me_karte_und_den_container(self):
        code = self._shim()
        assert "unifiedMeContactWithKeysToFetch" in code
        assert "JCContactsWriteOutcomeMeCardProtected" in code
        assert "JCContactsWriteOutcomeContainerMismatch" in code
        # Unbekannte Me-Karte heisst nein, nicht ja.
        assert "if (!meBekannt) {" in code

    def test_der_shim_patcht_statt_ein_vollobjekt_zu_schreiben(self):
        code = self._shim()
        assert "[gelesen mutableCopy]" in code
        assert "JCWriteApplyPatch" in code

    def test_der_shim_kennt_keine_notiz_und_kein_bild(self):
        code = self._shim()
        for verboten in ("CNContactNoteKey", "CNContactImageDataKey",
                         "CNContactThumbnailImageDataKey",
                         "CNContactSocialProfilesKey",
                         "CNContactInstantMessageAddressesKey",
                         "CNContactRelationsKey"):
            assert verboten not in code, verboten

    def test_nicht_lesbar_ist_kein_loeschbeweis(self):
        code = self._shim()
        anker = "if (kind == JCWriteKindDelete) {\n        if (!nachLesbar)"
        stelle = code.index(anker)
        assert "JCContactsWriteOutcomeAbsenceUnproven" in code[stelle:stelle + 400]

    def test_rust_weist_einen_ungebundenen_vorzustand_ab(self):
        code = self._rust()
        assert "fn vorzustand_ist_gebunden" in code
        assert 'ExecutionReportV1::not_sent(order, "digest_mismatch")' in code

    def test_rust_trennt_vor_und_nach_dem_send(self):
        code = self._rust()
        # Alles vor dem Save ist `not_sent`, alles danach `outcome_unknown`.
        for klasse in ("W_NOT_AUTHORIZED", "W_TARGET_NOT_FOUND",
                       "W_REVISION_CONFLICT", "W_ME_CARD_PROTECTED"):
            assert f"{klasse} => vor_dem_send(" in code
        assert 'W_SAVE_ERROR => {' in code
        assert 'bericht.outcome = "outcome_unknown".into();' in code

    def test_es_gibt_keinen_zweiten_versuch_im_nativen_pfad(self):
        code = self._rust() + self._shim()
        for verboten in ("retry", "Retry", "erneut senden", "for attempt"):
            assert verboten not in code, verboten


# ═══ F · Der Patch reist kanonisch (Livetest-Befund 2026-08-04) ═════════════
class TestPatchKanonisch:
    """Der native Pfad kennt nur die Schlüssel des Feldvertrags.

    Im ersten Update-Livetest trug die Nutzlast `family_name` statt
    `familyName`; der Torwächter wies sie korrekt als `unsupported_field`
    ab — **vor** jeder Übergabe. Der Fehler gehört aber in den Kern, nicht
    an die Providergrenze.
    """

    def test_api_namen_werden_zu_kanonischen_schluesseln(self):
        from personaljarvis.contacts.application.field_contract import (
            canonical_patch,
        )
        p = canonical_patch({"family_name": "Neu", "organization_name": "Org",
                             "job_title": "Titel"})
        assert p == {"familyName": "Neu", "organizationName": "Org",
                     "jobTitle": "Titel"}

    def test_listen_werden_kanonisch_und_behalten_die_reihenfolge(self):
        from personaljarvis.contacts.application.field_contract import (
            canonical_patch,
        )
        p = canonical_patch({"emails": [
            {"label": "work", "value": "a@example.invalid"},
            {"label": "home", "value": "b@example.invalid"}]})
        assert p["emails"] == [{"label": "work", "value": "a@example.invalid"},
                               {"label": "home", "value": "b@example.invalid"}]

    def test_ausdrueckliches_loeschen_bleibt_erhalten(self):
        """`null` und `[]` müssen den Digest erreichen — sonst hinge das
        Löschen an einer Auslassung."""
        from personaljarvis.contacts.application.field_contract import (
            canonical_patch,
        )
        p = canonical_patch({"family_name": None, "emails": [], "phones": None})
        assert p == {"familyName": None, "emails": [], "phones": []}

    def test_ein_typwechsel_wird_abgewiesen(self):
        from personaljarvis.contacts.application.errors import InvalidCommand
        from personaljarvis.contacts.application.field_contract import (
            canonical_patch,
        )
        with pytest.raises(InvalidCommand):
            canonical_patch({"contact_type": "organization"})

    def test_ein_unbekanntes_feld_wird_abgewiesen(self):
        from personaljarvis.contacts.application.errors import InvalidCommand
        from personaljarvis.contacts.application.field_contract import (
            canonical_patch,
        )
        with pytest.raises(InvalidCommand):
            canonical_patch({"note": "verboten"})

    def test_der_auftrag_traegt_nur_v1_schluessel(self, modul, tmp_path):
        """Ende zu Ende: Was der Claim herausgibt, akzeptiert der native Pfad."""
        from personaljarvis.contacts.application.field_contract import (
            CREATE_FIELDS,
            LIST_FIELDS,
            SCALAR_FIELDS,
        )
        contact_id, pid = _angelegt(modul, tmp_path)
        dienst = _dienst(modul, tmp_path, ("update",))
        mutation_id = _update_vorbereitet(
            modul, pid, {"family_name": "Neu", "organization_name": "Org",
                         "emails": [{"label": "work",
                                     "value": "neu@example.invalid"}]})
        auftrag = dienst.claim(mutation_id)
        erlaubt = (set(SCALAR_FIELDS.values())
                   | {s for s, _ in LIST_FIELDS.values()}
                   | {"contactType", "birthday"})
        assert set(auftrag.canonical_payload["fields"]) <= erlaubt
        assert "family_name" not in auftrag.canonical_payload["fields"]
        assert auftrag.canonical_payload["fields"]["familyName"] == "Neu"
        assert auftrag.payload_digest_matches()
        del CREATE_FIELDS      # nur zur Dokumentation der Vertragsquelle
