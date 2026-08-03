"""Das Containerinventar ist ein eigener, überlebensfähiger Metadatenschritt.

**Kontaktfrei.** Kein Sidecar, kein `CNContactStore`, keine Autorisierung —
ausschliesslich Attrappen und temporäre SQLite-Datenbanken.

Anlass: am 2026-08-01 brach ein Lesesync mit `dropEverything` ab. Das Inventar
hatte die Art beider Ablageorte bereits geliefert, aber persistiert wurde sie
erst im erfolgreichen Abschluss — der nie kam. Öffentlich stand danach zweimal
`art=unknown`, und der geplante Create-Livetest musste abgebrochen werden, weil
sich der lokale Ablageort nicht mehr vom kontogebundenen unterscheiden liess.

Die Tests hier halten die neue Grenze fest: Metadaten des Inventars und
fachliche Kontakt-, Cursor- und Tombstone-Transaktionen sind getrennt. Was das
Inventar belegt hat, überlebt jeden späteren Abbruch — und behauptet zugleich
nie einen Lauf, den es nicht gab.
"""

from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from personaljarvis.contacts.api.routes import (
    DEFAULT_WORKSPACE_HEADER,
    PREFIX,
    create_contacts_router,
)
from personaljarvis.contacts.bridge.models import (
    ChangeEvent,
    ChangeEventType,
    ContainerInfo,
)
from personaljarvis.contacts.domain.enums import CircuitState, SyncMode
from personaljarvis.contacts.sync import ContactsSyncService
from personaljarvis.contacts.sync.containers import (
    CONTAINER_TYPE_UNKNOWN,
    SPECIFIC_CONTAINER_TYPES,
    is_specific_container_type,
    normalize_container_type,
    validate_inventory,
)
from personaljarvis.contacts.sync.errors import InventoryInvalid

from .conftest import WORKSPACE
from .test_sync import ACCOUNT, AttrappenBridge, roh_kontakt

#: Die Form aus der Live-Abnahme: zwei Ablageorte, einer lokal, einer am Konto.
#: Die Kennungen sind erfunden, die *Form* nicht.
LOKAL = "11111111-2222-3333-4444-555555555555:ABAccount"
KONTO = "66666666-7777-8888-9999-000000000000:ABAccount"


class InventarBridge(AttrappenBridge):
    """Wie die Attrappe aus `test_sync`, aber mit steuerbaren Arten.

    Die Basisattrappe meldet jeden Ablageort als `local`. Genau die
    Unterscheidung, um die es hier geht, wäre damit nicht prüfbar.
    """

    def __init__(self, arten: dict[str, str], **kw):
        super().__init__(container=tuple(arten), **kw)
        self.arten = dict(arten)
        #: Zusätzliche, absichtlich fehlerhafte Einträge.
        self.zusatz: tuple[ContainerInfo, ...] = ()

    def containers(self):
        self.aufrufe.append("containers")
        return tuple(ContainerInfo(identifier=i, name="", type=a)
                     for i, a in self.arten.items()) + self.zusatz


@pytest.fixture
def bridge():
    return InventarBridge({LOKAL: "local", KONTO: "cardDAV"},
                          kontakte=(roh_kontakt("pid-1"),))


@pytest.fixture
def service(module, bridge):
    return ContactsSyncService(bridge, module, workspace_id=WORKSPACE,
                               provider_account_id=ACCOUNT,
                               empty_recheck_pause=0.0)


@pytest.fixture
def client(module):
    app = FastAPI()
    app.include_router(create_contacts_router(module))
    return TestClient(app)


# ── Hilfen ──────────────────────────────────────────────────────────────────
def zustaende(module) -> dict:
    with module.unit_of_work() as uow:
        return {z.container_identifier: z
                for z in module.repositories(uow).sync_state.list_all()}


def arten(module) -> dict[str, str | None]:
    return {k: z.container_type for k, z in zustaende(module).items()}


def bestand(module) -> tuple[int, int]:
    """(aktive Kontakte, Tombstones) — die beiden Zahlen, die zählen."""
    with module.unit_of_work() as uow:
        aktiv = uow.execute(
            "SELECT COUNT(*) AS n FROM contacts WHERE deleted_at IS NULL"
        ).fetchone()["n"]
        tot = uow.execute(
            "SELECT COUNT(*) AS n FROM contacts_tombstones").fetchone()["n"]
    return aktiv, tot


def auditlaeufe(module) -> list[str]:
    with module.unit_of_work() as uow:
        return [r["outcome"] for r in uow.execute(
            "SELECT outcome FROM contacts_sync_audit ORDER BY rowid").fetchall()]


def status(client) -> list[dict]:
    antwort = client.get(f"{PREFIX}/sync/status",
                         headers={DEFAULT_WORKSPACE_HEADER: WORKSPACE,
                                  "X-Personal-Actor": "lukas"})
    assert antwort.status_code == 200
    return antwort.json()


# ═══ A · Delta erfolgreich ══════════════════════════════════════════════════
def test_a_erfolgreicher_lauf_traegt_die_arten_bis_in_die_api(
        service, module, bridge, client):
    """Der gute Fall: Inventar zuerst, Delta danach, Arten öffentlich sichtbar."""
    service.inventory_containers()
    assert arten(module) == {LOKAL: "local", KONTO: "cardDAV"}

    # Erst ein Snapshot je Ablageort, dann ein Delta — der reguläre Weg.
    for kennung in (LOKAL, KONTO):
        assert service.initial_import(kennung).succeeded
    bridge.ereignisse = []
    ergebnis = service.delta_sync(LOKAL)
    assert ergebnis.succeeded

    # Das Delta hat die Arten nicht angetastet.
    assert arten(module) == {LOKAL: "local", KONTO: "cardDAV"}
    oeffentlich = {z["container_type"] for z in status(client)}
    assert oeffentlich == {"local", "cardDAV"}


def test_a_inventar_laeuft_vor_jedem_kontaktzugriff(service, bridge, module):
    """Die Reihenfolge ist der ganze Punkt — sie wird hier bewiesen."""
    service.inventory_containers()
    # `containers` kam, `enumerate`/`changes`/`get` nicht.
    assert "containers" in bridge.aufrufe
    assert not {"enumerate", "changes", "get"} & set(bridge.aufrufe)
    assert bestand(module) == (0, 0)


# ═══ B · dropEverything nach erfolgreichem Inventar ═════════════════════════
def test_b_drop_everything_behaelt_die_arten(service, module, bridge, client):
    """Der Fall vom 2026-08-01, jetzt mit dem richtigen Ausgang."""
    service.inventory_containers()
    for kennung in (LOKAL, KONTO):
        assert service.initial_import(kennung).succeeded
    vorher_bestand = bestand(module)
    assert vorher_bestand[0] > 0 and vorher_bestand[1] == 0

    # Ein neuer Lauf: Inventar erneut, dann verwirft der Provider die Historie.
    service.inventory_containers()
    bridge.ereignisse = [ChangeEvent(type=ChangeEventType.DROP_EVERYTHING,
                                     provider_identifier=None)]
    ergebnisse = [service.delta_sync(k) for k in (LOKAL, KONTO)]

    assert [e.succeeded for e in ergebnisse] == [False, False]
    assert [e.error_class for e in ergebnisse] == ["FullDiffRequired"] * 2
    assert [e.requires_full_diff for e in ergebnisse] == [True, True]

    # 1. Die Arten stehen noch — genau das ging vorher verloren.
    assert arten(module) == {LOKAL: "local", KONTO: "cardDAV"}
    assert {z["container_type"] for z in status(client)} == {"local", "cardDAV"}
    # 2. Beide Zustände auf Voll-Diff, beide Cursor verworfen.
    for z in zustaende(module).values():
        assert z.mode == SyncMode.FULL_DIFF_REQUIRED.value
        assert z.cursor_token is None and z.cursor_taken_at is None
    assert all(z["requires_full_diff"] for z in status(client))
    assert not any(z["cursor_present"] for z in status(client))
    # 3. Kein Kontakt angefasst, kein Tombstone.
    assert bestand(module) == vorher_bestand


def test_b_der_erfolgsstempel_ueberlebt_den_abbruch(service, module):
    """Ein Abbruch macht aus einem synchronisierten Ort keinen unbekannten."""
    service.inventory_containers()
    assert service.initial_import(LOKAL).succeeded
    stempel = zustaende(module)[LOKAL].last_full_diff_at
    assert stempel is not None

    service._client.ereignisse = [
        ChangeEvent(type=ChangeEventType.DROP_EVERYTHING,
                    provider_identifier=None)]
    service.delta_sync(LOKAL)
    assert zustaende(module)[LOKAL].last_full_diff_at == stempel


# ═══ C · Voll-Diff bricht nach erfolgreichem Inventar ab ════════════════════
def test_c_abgebrochener_voll_diff_behaelt_die_arten(service, module, bridge):
    """Der kontoweite Pfad fällt aus — die Metadaten bleiben trotzdem."""
    service.inventory_containers()
    assert arten(module) == {LOKAL: "local", KONTO: "cardDAV"}
    laeufe_vorher = len(auditlaeufe(module))

    # Unvollständige Enumeration: der Lauf darf nichts übernehmen.
    bridge.enumeration_vollstaendig = False
    ergebnis = service.full_diff_account([LOKAL, KONTO])

    assert not ergebnis.succeeded
    assert ergebnis.error_class == "IncompleteEnumeration"
    # 1. Arten unverändert.
    assert arten(module) == {LOKAL: "local", KONTO: "cardDAV"}
    # 2. Keine fachliche Teilübernahme, keine Tombstones.
    assert bestand(module) == (0, 0)
    # 3. Genau ein neuer Auditlauf, und der ist `aborted`.
    neu = auditlaeufe(module)[laeufe_vorher:]
    assert neu == ["aborted"]


def test_c_der_inventarschritt_schreibt_keinen_auditlauf(service, module):
    """Ein Metadatenschritt ist kein Lauf — er behauptet auch keinen."""
    assert auditlaeufe(module) == []
    service.inventory_containers()
    assert auditlaeufe(module) == []


# ═══ D · Inventar selbst fehlerhaft ═════════════════════════════════════════
def test_d_leere_kennung_wird_fail_closed_abgewiesen(service, module, bridge):
    bridge.zusatz = (ContainerInfo(identifier="  ", name="", type="local"),)
    with pytest.raises(InventoryInvalid) as exc:
        service.inventory_containers()
    assert exc.value.code == "inventory_missing_identifier"
    assert zustaende(module) == {}
    assert bestand(module) == (0, 0)


def test_d_widerspruechliche_art_wird_fail_closed_abgewiesen(
        service, module, bridge):
    bridge.zusatz = (ContainerInfo(identifier=LOKAL, name="", type="exchange"),)
    with pytest.raises(InventoryInvalid) as exc:
        service.inventory_containers()
    assert exc.value.code == "inventory_ambiguous_type"
    # **Nichts** wurde geschrieben — auch nicht der unstrittige zweite Ort.
    assert zustaende(module) == {}


def test_d_ein_fehlerhaftes_inventar_aendert_bekannte_arten_nicht(
        service, module, bridge):
    service.inventory_containers()
    assert arten(module) == {LOKAL: "local", KONTO: "cardDAV"}

    bridge.zusatz = (ContainerInfo(identifier=KONTO, name="", type="local"),)
    with pytest.raises(InventoryInvalid):
        service.inventory_containers()
    assert arten(module) == {LOKAL: "local", KONTO: "cardDAV"}


def test_d_wortgleiche_doppelnennung_ist_kein_fehler(service, module, bridge):
    """Redundant ist nicht mehrdeutig — nur das Zweite ist ein Fehler."""
    bridge.zusatz = (ContainerInfo(identifier=LOKAL, name="", type="local"),)
    service.inventory_containers()
    assert arten(module) == {LOKAL: "local", KONTO: "cardDAV"}


def test_d_ein_fehlerhaftes_inventar_bricht_den_ganzen_lauf_ab(
        service, module, bridge):
    """`InventoryInvalid` ist ein `SyncError` — die Aufrufer fangen ihn bereits."""
    from personaljarvis.contacts.sync.errors import SyncError

    assert issubclass(InventoryInvalid, SyncError)
    bridge.zusatz = (ContainerInfo(identifier="", name="", type="local"),)
    with pytest.raises(SyncError):
        service.inventory_containers()
    assert not {"enumerate", "changes"} & set(bridge.aufrufe)


# ═══ E · Bekannter Typ gegen unknown/NULL ═══════════════════════════════════
@pytest.mark.parametrize("art", sorted(SPECIFIC_CONTAINER_TYPES))
def test_e_eine_erhobene_art_wird_nie_durch_unknown_ersetzt(
        module, art):
    bruecke = InventarBridge({LOKAL: art})
    dienst = ContactsSyncService(bruecke, module, workspace_id=WORKSPACE,
                                 provider_account_id=ACCOUNT)
    dienst.inventory_containers()
    assert arten(module) == {LOKAL: art}

    # Der Provider meldet die Art plötzlich nicht mehr.
    bruecke.arten = {LOKAL: "etwas-voellig-anderes"}
    dienst.inventory_containers()
    assert arten(module) == {LOKAL: art}


def test_e_eine_erhobene_art_wird_nie_durch_null_ersetzt(module, service):
    """Auch der Schreibweg der Wiederherstellung kann sie nicht löschen."""
    from dataclasses import replace

    service.inventory_containers()
    with module.unit_of_work() as uow:
        repos = module.repositories(uow)
        vorher = repos.sync_state.get(ACCOUNT, LOKAL)
        repos.sync_state.upsert(replace(vorher, container_type=None))
    assert arten(module)[LOKAL] == "local"


def test_e_ein_lauf_ohne_inventar_verschlechtert_nichts(module, service):
    """Der Zustandsschreiber eines Laufs kennt die Art vielleicht nicht."""
    service.inventory_containers()
    # Ein frischer Dienst hat in diesem Lauf kein Inventar gesehen — sein
    # Zustandsschreiber kennt die Art also nicht.
    blind = ContactsSyncService(service._client, module, workspace_id=WORKSPACE,
                                provider_account_id=ACCOUNT,
                                empty_recheck_pause=0.0)
    assert blind.initial_import(LOKAL).succeeded
    assert arten(module)[LOKAL] == "local"


# ═══ F · Tatsächliche Typänderung ═══════════════════════════════════════════
def test_f_eine_echte_typaenderung_wird_uebernommen(module, service, bridge):
    service.inventory_containers()
    assert service.initial_import(LOKAL).succeeded
    vorher = zustaende(module)[LOKAL]

    bridge.arten[LOKAL] = "exchange"
    service.inventory_containers()

    nachher = zustaende(module)[LOKAL]
    assert nachher.container_type == "exchange"
    # Alles andere bleibt, wie der Lauf es hinterlassen hat.
    assert nachher.mode == vorher.mode
    assert nachher.cursor_token == vorher.cursor_token
    assert nachher.cursor_taken_at == vorher.cursor_taken_at
    assert nachher.last_full_diff_at == vorher.last_full_diff_at
    assert nachher.circuit_state == vorher.circuit_state
    assert nachher.key_set_version == vorher.key_set_version
    assert bestand(module) == (1, 0)


def test_f_eine_unveraenderte_art_schreibt_nicht(module, service):
    service.inventory_containers()
    vorher = zustaende(module)[LOKAL].updated_at
    service.inventory_containers()
    assert zustaende(module)[LOKAL].updated_at == vorher


# ═══ G · Neuer Container ════════════════════════════════════════════════════
def test_g_ein_neuer_ablageort_bekommt_genau_eine_zeile(module, service, bridge):
    service.inventory_containers()
    assert service.initial_import(LOKAL).succeeded
    vorher = zustaende(module)[LOKAL]

    dritter = "99999999-AAAA-BBBB-CCCC-DDDDDDDDDDDD:ABAccount"
    bridge.arten[dritter] = "exchange"
    neu = service.inventory_containers()
    assert len(neu) == 3

    zust = zustaende(module)
    assert set(zust) == {LOKAL, KONTO, dritter}
    z = zust[dritter]
    assert z.container_type == "exchange"
    assert z.mode == SyncMode.FULL_DIFF_REQUIRED.value
    assert z.cursor_token is None and z.cursor_taken_at is None
    assert z.last_full_diff_at is None
    assert z.circuit_state == CircuitState.CLOSED.value
    # Weder Kontakte noch Tombstones, und der bekannte Ort bleibt unberührt.
    assert bestand(module) == (1, 0)
    assert zust[LOKAL] == vorher


def test_g_eine_reine_inventarzeile_ist_kein_anlageziel(module, service):
    """Ohne vollständigen Lauf fehlen Fähigkeiten und Feldzustände."""
    from personaljarvis.contacts.api.redaction import container_ref
    from personaljarvis.contacts.application.errors import ContainerNotAvailable
    from personaljarvis.contacts.application.queries import ContactsQueryService

    service.inventory_containers()
    abfragen = ContactsQueryService(module)
    with pytest.raises(ContainerNotAvailable):
        abfragen.resolve_container_ref(container_ref(LOKAL))

    assert service.initial_import(LOKAL).succeeded
    assert abfragen.resolve_container_ref(container_ref(LOKAL)) == (ACCOUNT, LOKAL)


def test_g_ein_fehlender_ablageort_wird_nicht_entfernt(module, service, bridge):
    """Sein Verschwinden ist eine Aussage über den Provider, nicht über uns."""
    service.inventory_containers()
    assert service.initial_import(KONTO).succeeded

    del bridge.arten[KONTO]
    service.inventory_containers()

    assert set(zustaende(module)) == {LOKAL, KONTO}
    assert arten(module)[KONTO] == "cardDAV"
    assert bestand(module) == (1, 0)


# ═══ H · Datenschutz ════════════════════════════════════════════════════════
def test_h_der_status_bleibt_frei_von_rohen_kennungen(service, client):
    service.inventory_containers()
    text = json.dumps(status(client))
    assert LOKAL not in text and KONTO not in text
    assert "ABAccount" not in text
    assert ACCOUNT not in text
    assert "container_identifier" not in text
    assert "provider_account_id" not in text


def test_h_die_art_ist_generisch_und_maskiert_daneben(service, client):
    service.inventory_containers()
    zeilen = status(client)
    assert {z["container_type"] for z in zeilen} == {"local", "cardDAV"}
    for z in zeilen:
        assert z["container_ref"].startswith("C-") and len(z["container_ref"]) == 8
        assert z["account_ref"].startswith("A-")
        assert z["provider_type"] == "unknown"      # `acct-test` ist kein Apple-Konto


def test_h_ein_fremder_rohwert_verlaesst_die_anwendung_nie(module, client):
    """Zweiter Riegel am Austritt — auch gegen eine Zeile aus der Zukunft."""
    from personaljarvis.contacts.domain.models import ContactSyncState
    from personaljarvis.contacts.repositories.sqlite import (
        SqliteSyncStateRepository,
    )

    with module.unit_of_work() as uow:
        SqliteSyncStateRepository(uow).upsert(ContactSyncState(
            provider_account_id=ACCOUNT, container_identifier=LOKAL,
            key_set_version="v1", mode="delta",
            container_type="ABSuperGeheimesKonto"))
    zeilen = status(client)
    assert zeilen[0]["container_type"] == CONTAINER_TYPE_UNKNOWN
    assert "ABSuperGeheim" not in json.dumps(zeilen)


# ═══ Der Typvertrag selbst ══════════════════════════════════════════════════
def test_der_typvorrat_ist_geschlossen():
    for art in SPECIFIC_CONTAINER_TYPES:
        assert normalize_container_type(art) == art
        assert is_specific_container_type(art)
    for fremd in (None, "", "  ", "LOCAL", "carddav", "icloud", "google"):
        assert normalize_container_type(fremd) == CONTAINER_TYPE_UNKNOWN
        assert not is_specific_container_type(fremd)
    assert not is_specific_container_type(CONTAINER_TYPE_UNKNOWN)


def test_die_schreibweise_ist_zwischen_sidecar_und_kern_identisch():
    """Eine Abweichung wäre ein stiller Ausfall der Zielwahl."""
    from pathlib import Path

    quelle = Path(__file__).resolve().parents[3] / (
        "native/contacts-bridge/src/sidecar.swift")
    text = quelle.read_text(encoding="utf-8")
    for art in SPECIFIC_CONTAINER_TYPES:
        assert f'type = "{art}"' in text, art


def test_die_schreibweise_ist_zwischen_kern_und_oberflaeche_identisch():
    from pathlib import Path

    # Seit dem Apple-Neuaufbau (2026-08-02) lebt die Ablageort-Beschriftung
    # im Anlage-Dialog des Kontakte-Moduls, nicht mehr im Seitenmonolithen.
    quelle = Path(__file__).resolve().parents[3] / (
        "frontend/src/personal/contacts/editor/dialogs.tsx")
    text = quelle.read_text(encoding="utf-8")
    block = text.split("const CONTAINER_ART", 1)[1].split("};", 1)[0]
    for art in SPECIFIC_CONTAINER_TYPES | {CONTAINER_TYPE_UNKNOWN}:
        assert f"{art}:" in block, art
    # Und die lokale Ablage trägt genau den Wortlaut, an dem sie erkannt wird.
    assert "local: 'Lokal · Auf meinem Mac'" in block


def test_validate_inventory_liefert_uebersetzte_arten():
    arten = validate_inventory([
        ContainerInfo(identifier=LOKAL, name="", type="local"),
        ContainerInfo(identifier=KONTO, name="", type="etwas-neues"),
    ])
    assert arten == {LOKAL: "local", KONTO: CONTAINER_TYPE_UNKNOWN}


def test_ein_leeres_inventar_ist_hier_kein_fehler(module):
    """Ob ein Konto ohne Ablageort ein Problem ist, entscheidet der Lauf."""
    bruecke = InventarBridge({})
    dienst = ContactsSyncService(bruecke, module, workspace_id=WORKSPACE,
                                 provider_account_id=ACCOUNT)
    assert dienst.inventory_containers() == ()
    assert zustaende(module) == {}
