"""Auditspur **aller** Lese-Sync-Pfade. Kontaktfrei.

Anlass: Nach dem ARM64-Livelauf vom 2026-07-31 standen 115 importierte
Kontakte und zwei erfolgreiche Delta-Läufe in der Datenbank — in
`contacts_sync_audit` aber nur **ein** Eintrag, der des ursprünglichen
Voll-Diffs. Die Spur kannte nur den kontoweiten Pfad und die
Wiederherstellung; `initial_import`, `full_diff` je Container und
`delta_sync` schrieben nichts.

Das war genau dort blind, wo es wehtut: der Delta-Pfad ist derjenige, der auf
ein ausdrückliches Provider-`DELETE` hin einen Tombstone setzt. Eine Löschung
ohne Spur ist die Wiederholung des Vorfalls vom 2026-07-30 in klein.

Kein Test dieser Datei startet einen Sidecar, fragt TCC ab oder liest einen
echten Kontakt. Die Gegenstelle ist die Attrappe aus `test_sync.py`; alle
Daten sind erfunden.
"""

from __future__ import annotations

import pytest

from personaljarvis.contacts.bridge.errors import (
    BridgeOperationError,
    BridgeProcessError,
    ProcessDiagnostics,
    ProcessFailureClass,
)
from personaljarvis.contacts.bridge.models import ChangeEvent, ChangeEventType
from personaljarvis.contacts.bridge.protocol import ErrorCode
from personaljarvis.contacts.sync import SyncRunKind
from personaljarvis.contacts.sync.audit import container_ref

from .conftest import WORKSPACE
from .test_sync import ACCOUNT, CONTAINER, AttrappenBridge, roh_kontakt

# ── Fixtures ────────────────────────────────────────────────────────────────
#
# Die Attrappe wird aus `test_sync.py` uebernommen — eine zweite waere eine
# zweite Wahrheit ueber die Gegenstelle. Die beiden Fixtures stehen dagegen
# hier: importierte Fixtures wuerden von den gleichnamigen Testparametern
# ueberschattet, und genau das meldet Ruff als F811.


@pytest.fixture
def bridge():
    return AttrappenBridge(kontakte=(roh_kontakt("pid-1"),))


@pytest.fixture
def service(module, bridge):
    from personaljarvis.contacts.sync import ContactsSyncService

    return ContactsSyncService(bridge, module, workspace_id=WORKSPACE,
                               provider_account_id=ACCOUNT,
                               empty_recheck_pause=0.0)


# ── Hilfen ──────────────────────────────────────────────────────────────────
def laeufe(module) -> list[dict]:
    with module.unit_of_work() as uow:
        return [dict(z) for z in uow.execute(
            "SELECT * FROM contacts_sync_audit ORDER BY started_at").fetchall()]


def container_zeilen(module, run_id: str) -> list[dict]:
    with module.unit_of_work() as uow:
        return [dict(z) for z in uow.execute(
            "SELECT * FROM contacts_sync_audit_containers WHERE run_id = ? "
            "ORDER BY attempt", (run_id,)).fetchall()]


def einziger(module) -> dict:
    alle = laeufe(module)
    assert len(alle) == 1, [z["mode"] for z in alle]
    return alle[0]


def tombstones(module):
    with module.unit_of_work() as uow:
        return tuple(module.repositories(uow).tombstones.list_all())


def ereignis(typ: ChangeEventType, pid: str) -> ChangeEvent:
    return ChangeEvent(type=typ, provider_identifier=pid,
                       container_identifier=CONTAINER)


def mit_cursor(service, bridge):
    """Bringt den Container in den Delta-Zustand und raeumt die Spur ab."""
    service.initial_import(CONTAINER)
    with service._persistence.unit_of_work() as uow:  # noqa: SLF001
        uow.execute("DELETE FROM contacts_sync_audit_containers")
        uow.execute("DELETE FROM contacts_sync_audit")
    bridge.aufrufe.clear()


# ═══ Delta ══════════════════════════════════════════════════════════════════
def test_delta_ohne_ereignisse_ist_ein_committed_lauf(service, module, bridge):
    """Der Befund des Livelaufs: zwei erfolgreiche Delta-Laeufe, null Spur.

    Ein Lauf ohne Ereignisse ist kein Nicht-Lauf. Er hat den Cursor
    fortgeschrieben, und genau das muss nachvollziehbar sein.
    """
    mit_cursor(service, bridge)
    bridge.ereignisse = []
    bridge.token = "tok-2"

    ergebnis = service.delta_sync(CONTAINER)

    assert ergebnis.succeeded
    spur = einziger(module)
    assert spur["mode"] == "delta"
    assert spur["outcome"] == "committed"
    assert spur["events_total"] == 0
    assert spur["cursor_before_present"] == 1
    assert spur["cursor_after_present"] == 1
    assert spur["full_diff_required"] == 0
    assert spur["tombstoned"] == 0
    assert spur["completed_at"]


def test_delta_add_wird_aggregiert_erfasst(service, module, bridge):
    mit_cursor(service, bridge)
    bridge.kontakte["pid-2"] = roh_kontakt("pid-2", given="Zwei")
    bridge.ereignisse = [ereignis(ChangeEventType.ADD, "pid-2")]

    service.delta_sync(CONTAINER)

    spur = einziger(module)
    assert spur["events_add"] == 1 and spur["events_total"] == 1
    assert spur["imported"] == 1
    assert spur["outcome"] == "committed"


def test_delta_update_wird_aggregiert_erfasst(service, module, bridge):
    mit_cursor(service, bridge)
    bridge.kontakte["pid-1"] = roh_kontakt("pid-1", given="Geaendert")
    bridge.ereignisse = [ereignis(ChangeEventType.UPDATE, "pid-1")]

    service.delta_sync(CONTAINER)

    spur = einziger(module)
    assert spur["events_update"] == 1
    assert spur["updated"] == 1
    assert spur["outcome"] == "committed"


def test_delta_delete_schreibt_tombstone_und_spur_atomar(service, module, bridge):
    """Der Kern: ein ausdrueckliches Provider-DELETE ist nachvollziehbar.

    Tombstone und Auditzeile entstehen in derselben Transaktion — es kann
    keinen Tombstone ohne Spur geben und keine Spur ohne Tombstone.
    """
    mit_cursor(service, bridge)
    bridge.ereignisse = [ereignis(ChangeEventType.DELETE, "pid-1")]

    service.delta_sync(CONTAINER)

    spur = einziger(module)
    assert spur["events_delete"] == 1
    assert spur["tombstoned"] == 1
    assert spur["outcome"] == "committed"
    (grab,) = tombstones(module)
    assert grab.reason == "provider_delete_event"
    # Und der Beleg traegt den Identifier, die Spur ausdruecklich nicht.
    assert "pid-1" not in str(spur.values())


def test_delta_gemischte_ereignisse(service, module, bridge):
    # Vorzustand ueber eine Enumeration, nicht ueber ein Delta: pid-2 und
    # pid-3 muessen lokal bekannt sein, damit `update` und `delete` sie
    # ueberhaupt treffen koennen.
    bridge.kontakte["pid-2"] = roh_kontakt("pid-2", given="Zwei")
    bridge.kontakte["pid-3"] = roh_kontakt("pid-3", given="Drei")
    mit_cursor(service, bridge)

    bridge.kontakte["pid-4"] = roh_kontakt("pid-4", given="Vier")
    bridge.kontakte["pid-2"] = roh_kontakt("pid-2", given="Zwei geaendert")
    bridge.ereignisse = [
        ereignis(ChangeEventType.ADD, "pid-4"),
        ereignis(ChangeEventType.UPDATE, "pid-2"),
        ereignis(ChangeEventType.DELETE, "pid-3"),
    ]

    service.delta_sync(CONTAINER)

    spur = einziger(module)
    assert (spur["events_add"], spur["events_update"],
            spur["events_delete"]) == (1, 1, 1)
    assert spur["events_total"] == 3
    assert spur["imported"] == 1 and spur["updated"] == 1 and spur["tombstoned"] == 1
    assert spur["outcome"] == "committed"


def test_drop_everything_wird_als_aborted_protokolliert(service, module, bridge):
    mit_cursor(service, bridge)
    bridge.ereignisse = [ChangeEvent(type=ChangeEventType.DROP_EVERYTHING,
                                     provider_identifier=None)]

    ergebnis = service.delta_sync(CONTAINER)

    assert not ergebnis.succeeded
    spur = einziger(module)
    assert spur["outcome"] == "aborted"
    assert spur["full_diff_required"] == 1
    assert spur["drop_everything_seen"] == 1
    assert spur["error_code"] == "drop_everything"
    assert spur["cursor_after_present"] == 0


def test_ungueltiger_cursor_wird_als_aborted_protokolliert(service, module, bridge):
    mit_cursor(service, bridge)
    bridge.changes_fehler = BridgeOperationError(ErrorCode.INVALID_TOKEN, "weg")

    ergebnis = service.delta_sync(CONTAINER)

    assert not ergebnis.succeeded
    spur = einziger(module)
    assert spur["outcome"] == "aborted"
    assert spur["error_class"] == "CursorRejected"
    assert spur["full_diff_required"] == 1
    assert spur["cursor_after_present"] == 0


def test_fehlender_container_wird_als_aborted_protokolliert(service, module,
                                                            bridge):
    mit_cursor(service, bridge)
    bridge.container_ids = ("ein-anderer",)

    ergebnis = service.delta_sync(CONTAINER)

    assert not ergebnis.succeeded
    spur = einziger(module)
    assert spur["outcome"] == "aborted"
    assert spur["error_code"] == "container_missing"
    assert spur["full_diff_required"] == 1


def test_untragfaehiger_cursor_traegt_die_eigene_kennung(service, module, bridge):
    """Drei Ursachen, eine Klasse — die Kennung unterscheidet sie."""
    # Ohne vorherigen Lauf gibt es keinen Cursor.
    ergebnis = service.delta_sync(CONTAINER)

    assert not ergebnis.succeeded
    spur = einziger(module)
    assert spur["outcome"] == "aborted"
    assert spur["error_class"] == "FullDiffRequired"
    assert spur["error_code"] == "cursor_unusable"
    assert spur["cursor_before_present"] == 0


def test_bridge_timeout_wird_als_aborted_protokolliert(service, module, bridge):
    mit_cursor(service, bridge)
    diagnose = ProcessDiagnostics(
        request_id=7, operation="changes", elapsed_seconds=30.0,
        child_exit_code=None, child_signal=None, child_alive=True,
        stdout_eof=False, stderr_eof=False, detail="ohne Antwort")
    bridge.changes_fehler = BridgeProcessError(
        ProcessFailureClass.REQUEST_TIMEOUT, diagnose)

    ergebnis = service.delta_sync(CONTAINER)

    assert not ergebnis.succeeded
    spur = einziger(module)
    assert spur["outcome"] == "aborted"
    assert spur["error_class"] == "BridgeProcessError"
    assert spur["error_code"] == "process:request_timeout"


def test_persistenzfehler_hinterlaesst_kein_falsches_committed(service, module,
                                                               bridge,
                                                               monkeypatch):
    """Der Grund, warum das committed **in** der Transaktion steht.

    Bricht das Schreiben nach den fachlichen Aenderungen ab, rollt alles
    zurueck — auch die Spur. Ein `committed`, das einen Rollback ueberlebt,
    behauptete einen Lauf, den es nie gab.
    """
    mit_cursor(service, bridge)
    bridge.kontakte["pid-2"] = roh_kontakt("pid-2", given="Zwei")
    bridge.ereignisse = [ereignis(ChangeEventType.ADD, "pid-2")]

    def kracht(*a, **k):
        raise RuntimeError("Datenbank weg")

    monkeypatch.setattr(type(service), "_upsert_state", kracht)

    with pytest.raises(RuntimeError):
        service.delta_sync(CONTAINER)

    assert laeufe(module) == [], "die Spur hat den Rollback ueberlebt"
    namen = {k.display_name for k in _kontakte(module)}
    assert "Zwei Eins" not in namen, "fachliche Aenderung ueberlebte den Rollback"


def _kontakte(module):
    with module.unit_of_work() as uow:
        return tuple(module.repositories(uow).contacts.list_by_workspace(WORKSPACE))


def test_cursor_erscheint_nur_als_wahrheitswert(service, module, bridge):
    mit_cursor(service, bridge)
    bridge.token = "tok-geheim-42"
    bridge.ereignisse = []

    service.delta_sync(CONTAINER)

    spur = einziger(module)
    assert spur["cursor_after_present"] in (0, 1)
    assert "tok-geheim-42" not in str(spur.values())


def test_die_deltaspur_traegt_keine_identifier_oder_werte(service, module,
                                                           bridge):
    mit_cursor(service, bridge)
    bridge.kontakte["pid-2"] = roh_kontakt(
        "pid-2", given="Geheim", family="Person",
        emails=("geheim@example.invalid",))
    bridge.ereignisse = [ereignis(ChangeEventType.ADD, "pid-2")]

    service.delta_sync(CONTAINER)

    spur = einziger(module)
    blob = " ".join(str(w) for w in spur.values())
    for verboten in ("pid-2", "Geheim", "Person", "geheim@example.invalid",
                     "tok-", CONTAINER):
        assert verboten not in blob, verboten


# ═══ Initialimport und Snapshot ═════════════════════════════════════════════
def test_initialimport_schreibt_genau_einen_lauf(service, module, bridge):
    ergebnis = service.initial_import(CONTAINER)

    assert ergebnis.succeeded
    spur = einziger(module)
    assert spur["mode"] == "initial_import"
    assert spur["outcome"] == "committed"
    assert spur["imported"] == 1
    assert spur["tombstoned"] == 0, "ein Initialimport loescht nie"
    assert spur["cursor_before_present"] == 0
    assert spur["cursor_after_present"] == 1

    (zeile,) = container_zeilen(module, spur["run_id"])
    assert zeile["container_ref"] == container_ref(CONTAINER)
    assert zeile["reported_count"] == 1 and zeile["received_count"] == 1
    assert zeile["complete"] == 1 and zeile["count_consistent"] == 1
    assert zeile["duplicate_identifiers"] == 0
    assert zeile["attempt"] == 1


def test_echter_leerer_erstimport_ist_committed(module):
    """Ein wirklich leeres Adressbuch ist ein gueltiges Ergebnis.

    Der Nullbefund ist hier unverdaechtig: es gab vorher nichts, was
    verschwinden koennte (`previous_count == 0`).
    """
    from personaljarvis.contacts.sync import ContactsSyncService

    leer = AttrappenBridge(kontakte=())
    dienst = ContactsSyncService(leer, module, workspace_id=WORKSPACE,
                                 provider_account_id=ACCOUNT,
                                 empty_recheck_pause=0.0)

    ergebnis = dienst.initial_import(CONTAINER)

    assert ergebnis.succeeded
    spur = einziger(module)
    assert spur["outcome"] == "committed"
    assert spur["imported"] == 0 and spur["tombstoned"] == 0
    (zeile,) = container_zeilen(module, spur["run_id"])
    assert zeile["received_count"] == 0 and zeile["previous_count"] == 0


def test_unvollstaendige_enumeration_wird_als_aborted_protokolliert(service,
                                                                    module,
                                                                    bridge):
    bridge.enumeration_vollstaendig = False

    ergebnis = service.initial_import(CONTAINER)

    assert not ergebnis.succeeded
    spur = einziger(module)
    assert spur["outcome"] == "aborted"
    assert spur["error_class"] == "IncompleteEnumeration"
    assert spur["imported"] == 0 and spur["tombstoned"] == 0
    # Die Zahlen des verworfenen Laufs bleiben trotzdem sichtbar.
    (zeile,) = container_zeilen(module, spur["run_id"])
    assert zeile["complete"] == 0


def test_zaehlabweichung_wird_als_aborted_protokolliert(service, module, bridge):
    bridge.enumeration_count_override = 99

    ergebnis = service.initial_import(CONTAINER)

    assert not ergebnis.succeeded
    spur = einziger(module)
    assert spur["outcome"] == "aborted"
    (zeile,) = container_zeilen(module, spur["run_id"])
    assert zeile["reported_count"] == 99 and zeile["received_count"] == 1
    assert zeile["count_consistent"] == 0


def test_voll_diff_je_container_wird_auditiert_und_loescht_nicht(service, module,
                                                                  bridge):
    """`full_diff` ist ueber `sync()` produktiv erreichbar — also auditiert.

    Er bleibt dabei ohne Loeschmenge: die Abwesenheit in *einem* Container
    beweist nichts ueber die anderen.
    """
    mit_cursor(service, bridge)
    bridge.kontakte.clear()

    ergebnis = service.full_diff(CONTAINER)

    assert ergebnis.succeeded and ergebnis.tombstoned == 0
    spur = einziger(module)
    assert spur["mode"] == "full_diff"
    assert spur["outcome"] == "committed"
    assert spur["tombstoned"] == 0
    assert tombstones(module) == ()


# ═══ Komposition: genau ein Lauf je oeffentlichem Aufruf ════════════════════
@pytest.mark.parametrize("modus", ["initial_import", "delta", "full_diff"])
def test_ein_oeffentlicher_aufruf_erzeugt_genau_einen_lauf(service, module,
                                                           bridge, modus):
    if modus == "initial_import":
        service.sync(CONTAINER)
    elif modus == "delta":
        mit_cursor(service, bridge)
        service.sync(CONTAINER)
    else:
        mit_cursor(service, bridge)
        service.full_diff(CONTAINER)

    alle = laeufe(module)
    assert len(alle) == 1, [z["mode"] for z in alle]
    assert alle[0]["mode"] == ("initial_import" if modus == "initial_import"
                               else modus)


def test_full_diff_account_erzeugt_keine_verschachtelten_laeufe(service, module,
                                                                 bridge):
    """Der kontoweite Pfad ruft keine der einzelnen Laufmethoden auf."""
    mit_cursor(service, bridge)

    service.full_diff_account([CONTAINER])

    alle = laeufe(module)
    assert len(alle) == 1, [z["mode"] for z in alle]
    assert alle[0]["mode"] == "full_diff_account"


def test_die_dispatchmethode_zaehlt_nicht_doppelt(service, module, bridge):
    """`sync()` waehlt nur aus — sie ist selbst kein zusaetzlicher Lauf."""
    service.sync(CONTAINER)          # initial_import
    service.sync(CONTAINER)          # delta
    service.sync(CONTAINER)          # delta

    moden = [z["mode"] for z in laeufe(module)]
    assert moden == ["initial_import", "delta", "delta"]


def test_kein_lauf_ohne_aufruf(module):
    """Weder das Bereitstellen des Dienstes noch ein Seitenaufruf laeuft."""
    dienst = module.sync_service(
        AttrappenBridge(kontakte=(roh_kontakt("pid-1"),)),
        workspace_id=WORKSPACE, provider_account_id=ACCOUNT)
    assert dienst is not None
    assert laeufe(module) == []


def test_jeder_lauf_hat_eine_eigene_run_id(service, module, bridge):
    service.sync(CONTAINER)
    service.sync(CONTAINER)

    ids = [z["run_id"] for z in laeufe(module)]
    assert len(ids) == len(set(ids)) == 2


def test_die_modi_stammen_aus_der_geschlossenen_menge(service, module, bridge):
    """Ein Modus ausserhalb der CHECK-Menge liesse die Migration scheitern."""
    erlaubt = {"initial_import", "delta", "full_diff", "full_diff_account",
               "recovery"}
    service.sync(CONTAINER)
    service.sync(CONTAINER)
    service.full_diff(CONTAINER)
    service.full_diff_account([CONTAINER])

    assert {z["mode"] for z in laeufe(module)} <= erlaubt
    assert {z["outcome"] for z in laeufe(module)} <= {
        "committed", "rolled_back", "aborted", "running"}


def test_die_laufarten_decken_alle_oeffentlichen_pfade_ab():
    """Statisch: keine oeffentliche Laufart ohne Modus in der CHECK-Menge."""
    erlaubt = {"initial_import", "delta", "full_diff", "full_diff_account",
               "recovery"}
    assert {k.value for k in SyncRunKind} <= erlaubt | {"recovery"}
