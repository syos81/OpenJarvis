"""Auditspur, Null-Gegenprobe und Wiederbelebung. **Kontaktfrei.**

Alle Datenbanken sind temporär, die Gegenstelle ist eine Attrappe, alle
Kontaktdaten sind erfunden. Kein Sidecar, kein TCC, kein echter Kontakt.
"""

from __future__ import annotations

import pytest

from personaljarvis.contacts.bridge.errors import BridgeOperationError
from personaljarvis.contacts.bridge.models import EnumerationResult
from personaljarvis.contacts.bridge.protocol import ErrorCode
from personaljarvis.contacts.domain.models import ContactRole
from personaljarvis.contacts.sync import (
    ContactsRecoveryService,
    ContactsSyncService,
    container_ref,
)
from personaljarvis.contacts.sync.recovery import RECONCILED_REASON

from .conftest import WORKSPACE
from .test_sync import ACCOUNT, CONTAINER, AttrappenBridge, roh_kontakt


@pytest.fixture
def bridge():
    return AttrappenBridge(kontakte=(roh_kontakt("pid-1"), roh_kontakt("pid-2")))


@pytest.fixture
def service(module, bridge):
    return ContactsSyncService(bridge, module, workspace_id=WORKSPACE,
                               provider_account_id=ACCOUNT,
                               empty_recheck_pause=0.0)


def laeufe(module) -> list[dict]:
    with module.unit_of_work() as uow:
        zeilen = uow.execute(
            "SELECT * FROM contacts_sync_audit ORDER BY started_at").fetchall()
        return [dict(z) for z in zeilen]


def container_spuren(module) -> list[dict]:
    with module.unit_of_work() as uow:
        return [dict(z) for z in uow.execute(
            "SELECT * FROM contacts_sync_audit_containers "
            "ORDER BY container_ref, attempt").fetchall()]


def kontakte(module, *, mit_tombstones=False):
    with module.unit_of_work() as uow:
        return tuple(module.repositories(uow).contacts.list_by_workspace(
            WORKSPACE, include_tombstones=mit_tombstones))


# ═══ Auditspur ══════════════════════════════════════════════════════════════
def test_ein_erfolgreicher_lauf_wird_als_commit_protokolliert(service, module):
    service.initial_import(CONTAINER)
    service.full_diff_account([CONTAINER])

    (lauf,) = [z for z in laeufe(module) if z["mode"] == "full_diff_account"]
    assert lauf["outcome"] == "committed"
    assert lauf["container_count"] == 1
    assert lauf["completed_at"] and lauf["started_at"]
    assert lauf["workspace_id"] == WORKSPACE
    assert lauf["provider_account_id"] == ACCOUNT


def test_ein_abbruch_wird_als_aborted_protokolliert(service, module, bridge):
    service.initial_import(CONTAINER)
    bridge.enumeration_vollstaendig = False

    service.full_diff_account([CONTAINER])

    (lauf,) = [z for z in laeufe(module) if z["mode"] == "full_diff_account"]
    assert lauf["outcome"] == "aborted"
    assert lauf["error_class"] == "IncompleteEnumeration"
    assert lauf["full_diff_required"] == 1


def test_der_rollback_hinterlaesst_keinen_commit(service, module, bridge):
    """Ein zurückgerollter Lauf darf sich nicht als erfolgreich behaupten."""
    service.initial_import(CONTAINER)
    bridge.kontakte.clear()

    service.full_diff_account([CONTAINER])

    ausgaenge = {z["outcome"] for z in laeufe(module)
                 if z["mode"] == "full_diff_account"}
    assert "committed" not in ausgaenge


def test_containerzahlen_werden_maskiert_protokolliert(service, module):
    service.initial_import(CONTAINER)
    service.full_diff_account([CONTAINER])

    # Seit alle Lesepfade auditiert werden, schreibt auch der Initialimport
    # eine Containerzeile. Gemeint ist hier die des kontoweiten Laufs.
    konto = next(z["run_id"] for z in laeufe(module)
                 if z["mode"] == "full_diff_account")
    (spur,) = [z for z in container_spuren(module)
               if z["attempt"] == 1 and z["run_id"] == konto]
    assert spur["container_ref"] == container_ref(CONTAINER)
    assert CONTAINER not in spur["container_ref"]
    assert spur["reported_count"] == 2 and spur["received_count"] == 2
    assert spur["complete"] == 1 and spur["count_consistent"] == 1
    assert spur["duplicate_identifiers"] == 0


def test_die_auditspur_traegt_keine_personenbezogenen_daten(service, module,
                                                             bridge):
    service.initial_import(CONTAINER)
    service.full_diff_account([CONTAINER])

    text = str(laeufe(module)) + str(container_spuren(module))
    for verboten in ("pid-1", "pid-2", "Erfunden", "eins@example.invalid",
                     bridge.token, CONTAINER):
        assert verboten not in text, verboten


def test_der_cursor_erscheint_nur_als_wahrheitswert(service, module):
    service.initial_import(CONTAINER)
    service.full_diff_account([CONTAINER])

    (lauf,) = [z for z in laeufe(module) if z["mode"] == "full_diff_account"]
    assert lauf["cursor_after_present"] in (0, 1)
    assert lauf["cursor_before_present"] in (0, 1)
    assert "tok" not in str(lauf)


# ═══ Null-Gegenprobe ════════════════════════════════════════════════════════
class Skript(AttrappenBridge):
    """Liefert für `enumerate` eine vorher festgelegte Folge von Antworten.

    Damit lassen sich Erstimport und Gegenprobe unabhängig steuern — sonst
    verbraucht schon der Import die Antwort, die für die Probe gedacht war.
    """

    def __init__(self, kontakte):
        super().__init__(kontakte=kontakte)
        self.folge: list = []          # leer = immer der volle Bestand

    def voll(self) -> EnumerationResult:
        werte = tuple(self.kontakte.values())
        return EnumerationResult(contacts=werte, count=len(werte),
                                 complete=True, key_set_version=1)

    @staticmethod
    def leer() -> EnumerationResult:
        return EnumerationResult(contacts=(), count=0, complete=True,
                                 key_set_version=1)

    def enumerate(self, *, container_identifier=None, timeout=300.0):
        self.aufrufe.append("enumerate")
        if not self.folge:
            return self.voll()
        naechste = self.folge.pop(0)
        if isinstance(naechste, Exception):
            raise naechste
        return naechste


def _dienst(module, bridge):
    return ContactsSyncService(bridge, module, workspace_id=WORKSPACE,
                               provider_account_id=ACCOUNT,
                               empty_recheck_pause=0.0)


def _mit_bestand(module, anzahl: int) -> tuple[Skript, ContactsSyncService]:
    """Importiert `anzahl` Datensätze und gibt Attrappe und Dienst zurück."""
    bridge = Skript(tuple(roh_kontakt(f"p{i}") for i in range(anzahl)))
    dienst = _dienst(module, bridge)
    dienst.initial_import(CONTAINER)
    bridge.aufrufe.clear()
    return bridge, dienst


def test_null_dann_bestand_ist_ein_augenblickszustand(module):
    """116 → 0 → 116: kein Tombstone, der Lauf endet trotzdem."""
    bridge, dienst = _mit_bestand(module, 116)
    assert len(kontakte(module)) == 116

    bridge.folge = [bridge.leer()]        # erster Lauf null, Probe voll
    ergebnis = dienst.full_diff_account([CONTAINER])

    assert not ergebnis.succeeded
    assert ergebnis.error_class == "TransientEmptySnapshot"
    assert ergebnis.tombstoned == 0
    assert len(kontakte(module)) == 116, "der Bestand bleibt unangetastet"


def test_zweimal_null_bleibt_verdaechtig(module):
    """116 → 0 → 0: immer noch kein Löschbeleg."""
    bridge, dienst = _mit_bestand(module, 116)

    bridge.folge = [bridge.leer(), bridge.leer()]
    ergebnis = dienst.full_diff_account([CONTAINER])

    assert ergebnis.error_class == "SuspiciousEmptyEnumeration"
    assert ergebnis.tombstoned == 0
    assert len(kontakte(module)) == 116


def test_auch_ein_einziger_kontakt_bekommt_die_gegenprobe(module):
    bridge, dienst = _mit_bestand(module, 1)

    bridge.folge = [bridge.leer()]
    ergebnis = dienst.full_diff_account([CONTAINER])

    assert ergebnis.error_class == "TransientEmptySnapshot"
    assert len(kontakte(module)) == 1


def test_es_gibt_genau_eine_gegenprobe(module):
    bridge, dienst = _mit_bestand(module, 1)
    bridge.folge = [bridge.leer(), bridge.leer()]

    dienst.full_diff_account([CONTAINER])

    assert bridge.aufrufe.count("enumerate") == 2, "kein dritter Versuch"


def test_beide_versuche_stehen_in_der_auditspur(module):
    bridge, dienst = _mit_bestand(module, 1)
    bridge.folge = [bridge.leer(), bridge.leer()]

    dienst.full_diff_account([CONTAINER])

    versuche = [z for z in container_spuren(module)
                if z["previous_count"] == 1]
    assert sorted(v["attempt"] for v in versuche) == [1, 2]
    assert versuche[0]["received_count"] == 0 and versuche[1]["received_count"] == 0
    (lauf,) = [z for z in laeufe(module) if z["mode"] == "full_diff_account"]
    assert lauf["suspicious_empty"] == 1


def test_gegenprobe_mit_zeitueberlauf_loescht_nichts(module):
    bridge, dienst = _mit_bestand(module, 1)
    bridge.folge = [bridge.leer(),
                    BridgeOperationError(ErrorCode.INTERNAL, "Zeitueberlauf")]

    ergebnis = dienst.full_diff_account([CONTAINER])

    assert not ergebnis.succeeded and ergebnis.tombstoned == 0
    assert len(kontakte(module)) == 1


def test_gegenprobe_mit_zaehlabweichung_loescht_nichts(module):
    bridge, dienst = _mit_bestand(module, 1)
    bridge.folge = [bridge.leer(),
                    EnumerationResult(contacts=(roh_kontakt("p1"),), count=99,
                                      complete=True, key_set_version=1)]

    ergebnis = dienst.full_diff_account([CONTAINER])

    assert ergebnis.error_class == "IncompleteEnumeration"
    assert len(kontakte(module)) == 1


def test_unvollstaendige_gegenprobe_loescht_nichts(module):
    bridge, dienst = _mit_bestand(module, 1)
    bridge.folge = [bridge.leer(),
                    EnumerationResult(contacts=(), count=0, complete=False,
                                      key_set_version=1)]

    ergebnis = dienst.full_diff_account([CONTAINER])

    assert ergebnis.error_class == "IncompleteEnumeration"
    assert len(kontakte(module)) == 1


def test_kein_cursorfortschritt_bei_der_gegenprobe(module):
    bridge, dienst = _mit_bestand(module, 1)
    with module.unit_of_work() as uow:
        vorher = module.repositories(uow).sync_state.get(ACCOUNT, CONTAINER)
    bridge.token = "tok-neu"
    bridge.folge = [bridge.leer(), bridge.leer()]

    dienst.full_diff_account([CONTAINER])

    with module.unit_of_work() as uow:
        nachher = module.repositories(uow).sync_state.get(ACCOUNT, CONTAINER)
    assert nachher.cursor_token == vorher.cursor_token


# ═══ Wiederbelebung ═════════════════════════════════════════════════════════
def _vorfall(module, anzahl: int = 116):
    """Stellt den Zustand vom 2026-07-30 her: alles lokal getombstonet.

    `confirm_empty=True` umgeht die Gegenprobe — genau das, was der damalige
    Code ohne jede Bestätigung tat.
    """
    bridge, dienst = _mit_bestand(module, anzahl)
    bridge.folge = [bridge.leer()]
    dienst.full_diff_account([CONTAINER], confirm_empty=True)   # der Irrtum
    bridge.folge = []                                           # wieder voll
    bridge.aufrufe.clear()
    return bridge, dienst


def test_der_vorfall_laesst_sich_herstellen(module):
    bridge, _ = _vorfall(module, 5)
    assert kontakte(module) == ()
    assert len(kontakte(module, mit_tombstones=True)) == 5


def test_wiederbelebung_reaktiviert_dieselben_datensaetze(module):
    bridge, dienst = _vorfall(module, 116)
    vorher_ids = {k.id for k in kontakte(module, mit_tombstones=True)}

    ergebnis = ContactsRecoveryService(
        dienst, module, workspace_id=WORKSPACE,
        provider_account_id=ACCOUNT).recover()

    assert ergebnis.succeeded and ergebnis.reactivated == 116
    aktiv = kontakte(module)
    assert len(aktiv) == 116
    assert {k.id for k in aktiv} == vorher_ids, "keine neuen lokalen Kennungen"
    assert len(kontakte(module, mit_tombstones=True)) == 116, "kein Duplikat"


def test_tombstones_werden_abgeglichen_statt_geloescht(module):
    bridge, dienst = _vorfall(module, 3)

    ergebnis = ContactsRecoveryService(
        dienst, module, workspace_id=WORKSPACE,
        provider_account_id=ACCOUNT).recover()

    with module.unit_of_work() as uow:
        gruende = [z[0] for z in uow.execute(
            "SELECT reason FROM contacts_tombstones").fetchall()]
    assert len(gruende) == 3, "keine harte Loeschung"
    assert set(gruende) == {RECONCILED_REASON}
    assert ergebnis.tombstones_reconciled == 3
    assert ergebnis.still_absent == 0


def test_lokale_rollen_ueberleben_die_wiederbelebung(module):
    bridge, dienst = _vorfall(module, 2)
    ziel = kontakte(module, mit_tombstones=True)[0]
    with module.unit_of_work() as uow:
        module.repositories(uow).roles.set_roles(
            ziel.id, (ContactRole(workspace_id=WORKSPACE, role="Privat"),))

    ContactsRecoveryService(dienst, module, workspace_id=WORKSPACE,
                            provider_account_id=ACCOUNT).recover()

    with module.unit_of_work() as uow:
        rollen = module.repositories(uow).roles.list_for_contact(ziel.id)
    assert [r.role for r in rollen] == ["Privat"]


def test_unvollstaendige_enumeration_repariert_nichts(module):
    bridge, dienst = _vorfall(module, 3)
    # Der Provider antwortet, aber nicht vollständig — keine Grundlage für
    # eine Reparatur.
    bridge.folge = [EnumerationResult(contacts=(), count=0, complete=False,
                                      key_set_version=1)]

    ergebnis = ContactsRecoveryService(
        dienst, module, workspace_id=WORKSPACE,
        provider_account_id=ACCOUNT).recover()

    assert not ergebnis.succeeded
    assert kontakte(module) == (), "nichts reaktiviert"


def test_ein_fehler_rollt_alles_zurueck(module):
    bridge, dienst = _vorfall(module, 3)

    def bricht_ab(*a, **k):
        raise BridgeOperationError(ErrorCode.PROVIDER_ERROR, "weg")

    bridge.enumerate = bricht_ab
    ergebnis = ContactsRecoveryService(
        dienst, module, workspace_id=WORKSPACE,
        provider_account_id=ACCOUNT).recover()

    assert not ergebnis.succeeded
    assert kontakte(module) == ()
    with module.unit_of_work() as uow:
        gruende = {z[0] for z in uow.execute(
            "SELECT reason FROM contacts_tombstones").fetchall()}
    assert RECONCILED_REASON not in gruende, "kein Teil-Commit"


def test_der_cursor_wird_erst_nach_dem_commit_gesetzt(module):
    bridge, dienst = _vorfall(module, 2)

    ContactsRecoveryService(dienst, module, workspace_id=WORKSPACE,
                            provider_account_id=ACCOUNT).recover()

    with module.unit_of_work() as uow:
        zustand = module.repositories(uow).sync_state.get(ACCOUNT, CONTAINER)
    # Bewusst kein Cursor: der naechste gewoehnliche Lauf soll auf einem
    # frisch geprueften Bestand aufsetzen.
    assert zustand.cursor_token is None
    assert zustand.mode == "full_diff_required"


def test_die_wiederbelebung_wird_auditiert(module):
    bridge, dienst = _vorfall(module, 4)

    ContactsRecoveryService(dienst, module, workspace_id=WORKSPACE,
                            provider_account_id=ACCOUNT).recover()

    (lauf,) = [z for z in laeufe(module) if z["mode"] == "recovery"]
    assert lauf["outcome"] == "committed" and lauf["reactivated"] == 4
    assert "p0" not in str(lauf) and CONTAINER not in str(lauf)


def test_die_wiederbelebung_laeuft_nicht_von_selbst(module):
    bridge, dienst = _vorfall(module, 2)
    bridge.aufrufe.clear()

    ContactsRecoveryService(dienst, module, workspace_id=WORKSPACE,
                            provider_account_id=ACCOUNT)

    assert bridge.aufrufe == [], "das Bauen allein darf nichts ausloesen"


# ═══ Der produktive Auslöseweg ══════════════════════════════════════════════
#
# Der Endpunkt ist bewusst eng: er beantwortet einen konkret erkannten
# Fehlerzustand und ist keine gewöhnliche Benutzeraktion.
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from personaljarvis.contacts.api.routes import (  # noqa: E402
    DEFAULT_WORKSPACE_HEADER,
    PREFIX,
    create_contacts_router,
)

WEG = f"{PREFIX}/recovery/suspicious-empty"
KOPF = {DEFAULT_WORKSPACE_HEADER: WORKSPACE}
GUELTIG = {"user_initiated": True, "confirm_reactivation": True}


class ModulHuelle:
    """Reicht die echte Persistenz durch und trägt die beiden Dienste."""

    def __init__(self, module, recovery=None, live=None) -> None:
        self._module = module
        self.recovery_service = recovery
        self.live_service = live

    def unit_of_work(self):
        return self._module.unit_of_work()

    def repositories(self, uow):
        return self._module.repositories(uow)


def _client(module, recovery=None, live=None) -> TestClient:
    app = FastAPI()
    app.include_router(create_contacts_router(ModulHuelle(module, recovery, live)))
    return TestClient(app)


def _recovery(module, dienst):
    from personaljarvis.contacts.sync import ContactsRecoveryService

    return ContactsRecoveryService(dienst, module, workspace_id=WORKSPACE,
                                   provider_account_id=ACCOUNT)


# ── Eingabevertrag ──────────────────────────────────────────────────────────
def test_der_endpunkt_ist_post_und_verlangt_beide_bestaetigungen(module):
    bridge, dienst = _vorfall(module, 2)
    client = _client(module, _recovery(module, dienst))

    assert client.get(WEG, headers=KOPF).status_code == 405
    for koerper in ({}, {"user_initiated": True},
                    {"confirm_reactivation": True},
                    {"user_initiated": False, "confirm_reactivation": True},
                    {"user_initiated": True, "confirm_reactivation": False}):
        assert client.post(WEG, json=koerper, headers=KOPF).status_code == 422, koerper
    assert bridge.aufrufe == [], "keine dieser Anfragen darf etwas ausloesen"


def test_ein_fremdes_feld_wird_abgewiesen(module):
    _, dienst = _vorfall(module, 2)
    client = _client(module, _recovery(module, dienst))
    antwort = client.post(WEG, json={**GUELTIG, "workspace": "fremd"},
                          headers=KOPF)
    assert antwort.status_code == 422


def test_ohne_konfigurierten_dienst_passiert_nichts(module):
    client = _client(module)
    assert client.post(WEG, json=GUELTIG, headers=KOPF).status_code == 503


# ── Lokale Vorbedingungen: fail-closed vor jedem Store-Zugriff ──────────────
def test_ohne_tombstones_kein_sidecar(module):
    bridge, dienst = _mit_bestand(module, 3)
    client = _client(module, _recovery(module, dienst))

    antwort = client.post(WEG, json=GUELTIG, headers=KOPF)

    assert antwort.status_code == 409
    assert antwort.json()["detail"]["technical_code"] == "no_tombstones"
    assert bridge.aufrufe == [], "kein Sidecar, keine Enumeration"


def test_ein_fremder_loeschgrund_blockiert(module):
    """Ein echtes Löschereignis darf nicht mitrepariert werden."""
    bridge, dienst = _vorfall(module, 2)
    with module.unit_of_work() as uow:
        uow.execute("UPDATE contacts_tombstones SET reason = ? "
                    "WHERE rowid = (SELECT MIN(rowid) FROM contacts_tombstones)",
                    ("provider_delete_event",))
    bridge.aufrufe.clear()
    client = _client(module, _recovery(module, dienst))

    antwort = client.post(WEG, json=GUELTIG, headers=KOPF)

    assert antwort.status_code == 409
    assert antwort.json()["detail"]["technical_code"] == "unexpected_tombstone_reason"
    assert bridge.aufrufe == []


def test_bereits_abgeglichen_laeuft_nicht_erneut(module):
    bridge, dienst = _vorfall(module, 2)
    client = _client(module, _recovery(module, dienst))
    assert client.post(WEG, json=GUELTIG, headers=KOPF).status_code == 200
    bridge.aufrufe.clear()

    zweite = client.post(WEG, json=GUELTIG, headers=KOPF)

    assert zweite.status_code == 409
    assert zweite.json()["detail"]["technical_code"] in (
        "already_reconciled", "already_recovered")
    assert bridge.aufrufe == [], "kein zweiter Store-Zugriff"


def test_ein_laufender_sync_blockiert(module):
    class LaufenderSync:
        def is_running(self, workspace_id):
            return True

    bridge, dienst = _vorfall(module, 2)
    client = _client(module, _recovery(module, dienst), live=LaufenderSync())

    antwort = client.post(WEG, json=GUELTIG, headers=KOPF)

    assert antwort.status_code == 409
    assert antwort.json()["detail"]["technical_code"] == "sync_in_progress"
    assert bridge.aufrufe == []


def test_ein_paralleler_lauf_wird_abgewiesen(module):
    bridge, dienst = _vorfall(module, 2)
    recovery = _recovery(module, dienst)
    client = _client(module, recovery)
    recovery._riegel.acquire()
    try:
        antwort = client.post(WEG, json=GUELTIG, headers=KOPF)
    finally:
        recovery._riegel.release()

    assert antwort.status_code == 409
    assert antwort.json()["detail"]["retryable"] is True
    assert bridge.aufrufe == []


def test_ohne_autorisierung_wird_nicht_aufgezaehlt(module):
    from personaljarvis.contacts.bridge.models import AuthorizationStatus

    bridge, dienst = _vorfall(module, 2)
    bridge.status = AuthorizationStatus.NOT_DETERMINED
    bridge.aufrufe.clear()
    client = _client(module, _recovery(module, dienst))

    antwort = client.post(WEG, json=GUELTIG, headers=KOPF)

    assert antwort.json()["status"] == "failed"
    assert "enumerate" not in bridge.aufrufe
    assert kontakte(module) == (), "nichts reaktiviert"


# ── Erfolgreicher Lauf ──────────────────────────────────────────────────────
def test_der_vorfall_wird_vollstaendig_zurueckgenommen(module):
    bridge, dienst = _vorfall(module, 116)
    vorher_ids = {k.id for k in kontakte(module, mit_tombstones=True)}
    client = _client(module, _recovery(module, dienst))

    daten = client.post(WEG, json=GUELTIG, headers=KOPF).json()

    assert daten["status"] == "recovered"
    assert daten["reactivated"] == 116
    assert daten["tombstones_reconciled"] == 116
    assert daten["still_absent"] == 0
    assert daten["local_ids_preserved"] is True
    assert daten["mutations_performed"] is False
    assert daten["full_diff_required"] is True
    assert daten["cursor_present"] is False
    assert {k.id for k in kontakte(module)} == vorher_ids


def test_die_antwort_traegt_nur_zahlen(module):
    bridge, dienst = _vorfall(module, 3)
    client = _client(module, _recovery(module, dienst))

    daten = client.post(WEG, json=GUELTIG, headers=KOPF).json()

    # Gegen die **Werte**, nicht gegen die Feldnamen: `local_ids_preserved`
    # enthaelt zwangslaeufig "local".
    werte = " ".join(str(w) for w in daten.values())
    for verboten in ("p0", "p1", "Erfunden", "eins@example.invalid",
                     CONTAINER, bridge.token, "/Users/"):
        assert verboten not in werte, verboten


def test_kein_automatischer_folgesync(module):
    bridge, dienst = _vorfall(module, 2)
    client = _client(module, _recovery(module, dienst))

    client.post(WEG, json=GUELTIG, headers=KOPF)

    assert "changes" not in bridge.aufrufe, "kein Delta im Anschluss"
    with module.unit_of_work() as uow:
        zustand = module.repositories(uow).sync_state.get(ACCOUNT, CONTAINER)
    assert zustand.mode == "full_diff_required" and zustand.cursor_token is None


def test_der_sidecar_geht_auf_jedem_pfad(module):
    """Der Dienst startet ihn nicht selbst — der Aufrufer haelt ihn."""
    bridge, dienst = _vorfall(module, 2)
    client = _client(module, _recovery(module, dienst))
    client.post(WEG, json=GUELTIG, headers=KOPF)
    assert bridge.aufrufe.count("enumerate") >= 1


def test_unvollstaendige_enumeration_rollt_vollstaendig_zurueck(module):
    bridge, dienst = _vorfall(module, 5)
    bridge.folge = [EnumerationResult(contacts=(), count=0, complete=False,
                                      key_set_version=1)]
    client = _client(module, _recovery(module, dienst))

    daten = client.post(WEG, json=GUELTIG, headers=KOPF).json()

    assert daten["status"] == "failed" and daten["reactivated"] == 0
    assert kontakte(module) == ()
    with module.unit_of_work() as uow:
        gruende = {z[0] for z in uow.execute(
            "SELECT reason FROM contacts_tombstones").fetchall()}
    assert RECONCILED_REASON not in gruende


def test_ein_bridge_abbruch_repariert_nichts(module):
    bridge, dienst = _vorfall(module, 5)
    bridge.folge = [BridgeOperationError(ErrorCode.INTERNAL, "Zeitueberlauf")]
    client = _client(module, _recovery(module, dienst))

    daten = client.post(WEG, json=GUELTIG, headers=KOPF).json()

    assert daten["status"] == "failed" and daten["retryable"] is True
    assert kontakte(module) == ()


def test_eine_leere_enumeration_belebt_nichts_wieder(module):
    """Findet der Provider nichts, wird auch nichts reaktiviert.

    Die Null-Gegenprobe kann hier gar nicht greifen: sie schuetzt vor
    Loeschungen, und beim Wiederherstellen gibt es lokal nichts mehr zu
    loeschen — `previous_count` ist null. Der Schutz liegt hier woanders und
    ist ebenso wirksam: ohne wiedergefundenen Provider-Identifier passiert
    schlicht nichts, und die Tombstones bleiben, wie sie sind.
    """
    bridge, dienst = _vorfall(module, 4)
    bridge.folge = [bridge.leer()]
    client = _client(module, _recovery(module, dienst))

    daten = client.post(WEG, json=GUELTIG, headers=KOPF).json()

    assert daten["reactivated"] == 0
    assert daten["tombstones_reconciled"] == 0
    assert daten["still_absent"] == 4, "die offenen Loeschungen bleiben sichtbar"
    assert kontakte(module) == ()
    with module.unit_of_work() as uow:
        gruende = {z[0] for z in uow.execute(
            "SELECT reason FROM contacts_tombstones").fetchall()}
    assert RECONCILED_REASON not in gruende


def test_der_endpunkt_steht_in_keiner_agenten_oder_toolflaeche():
    """Er ist eine kontrollierte Recovery-Funktion, kein Werkzeug.

    Durchsucht wird nur der **produktive** Baum: diese Datei ruft den Pfad
    selbst auf, und ein Testaufruf ist keine Werkzeugregistrierung. Frueher
    stand stattdessen eine Allowlist, die eine der beiden pruefenden
    Testdateien nannte und die andere vergass — beide fielen dadurch um.
    """
    import subprocess
    from pathlib import Path

    repo = Path(__file__).resolve().parents[3]
    treffer = subprocess.run(
        ["git", "grep", "-l", "recovery/suspicious-empty",
         "--", "src/", "frontend/src"],
        cwd=repo, capture_output=True, text=True, timeout=60).stdout.split()
    assert set(treffer) == {"src/personaljarvis/contacts/api/routes.py"}, treffer
