"""Kanonische Bestandsaggregate. **Kontaktfrei, temporäre Datenbanken.**

Anlass: Ein Abnahmebericht zählte `SELECT COUNT(*) FROM contacts_tombstones`
und nannte das Ergebnis „offene Tombstones". Die Tabelle ist aber eine
Historie — abgeschlossene Grabsteine bleiben darin stehen. Diese Tests
halten die Unterscheidung fest, damit derselbe Fehler nicht zurückkommt.
"""

from __future__ import annotations

from personaljarvis.contacts.diagnostics import (
    TERMINALE_MUTATIONSZUSTAENDE,
    bestandsaggregate,
)
from personaljarvis.contacts.sync.recovery import RECONCILED_REASON

from .conftest import new_id

KONTO = "acc-diagnose"


def _tombstone(uow, identifier: str, reason: str, konto: str = KONTO) -> None:
    uow.execute(
        "INSERT INTO contacts_tombstones (provider_account_id, "
        "provider_identifier, contact_id, deleted_at, reason, retain_until) "
        "VALUES (?,?,?,?,?,?)",
        (konto, identifier, None, "2026-08-03T00:00:00Z", reason, None))


def _kontakt(uow, contact_id: str, *, tombstone: int = 0,
             deleted_at: str | None = None) -> None:
    uow.execute(
        "INSERT INTO contacts (id, workspace_id, display_name, contact_type, "
        "is_me_card, is_tombstone, deleted_at, local_revision, sync_state, "
        "field_completeness, created_at, updated_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (contact_id, "ws-test", "Testperson Alpha", "person", 0, tombstone,
         deleted_at, 1, "in_sync", "full",
         "2026-08-03T00:00:00Z", "2026-08-03T00:00:00Z"))


# ═══ E · Tombstone-Semantik ═════════════════════════════════════════════════
def test_abgeschlossene_tombstones_gelten_nicht_als_offen(uow):
    """Der exakte Fehler des Berichts: Historie ist nicht „offen"."""
    for i in range(116):
        _tombstone(uow, f"pid-{i}", RECONCILED_REASON)

    a = bestandsaggregate(uow.connection)

    assert a.tombstone_zeilen_gesamt == 116
    assert a.abgeschlossene_tombstones == 116
    assert a.offene_tombstones == 0


def test_offene_tombstones_werden_gezaehlt(uow):
    _tombstone(uow, "pid-offen-1", "missing_in_enumeration")
    _tombstone(uow, "pid-offen-2", "deleted_by_provider")
    _tombstone(uow, "pid-zu", RECONCILED_REASON)

    a = bestandsaggregate(uow.connection)

    assert a.tombstone_zeilen_gesamt == 3
    assert a.offene_tombstones == 2
    assert a.abgeschlossene_tombstones == 1


def test_aktive_kontakte_zaehlen_nie_als_tombstones(uow):
    """Die zweite Verwechslungsgefahr: Kontaktzeile vs. Löschnachweis."""
    for _ in range(5):
        _kontakt(uow, new_id())
    # Schema-Invariante: `is_tombstone = 0 OR deleted_at IS NOT NULL` — eine
    # Grabsteinzeile traegt immer einen Loeschzeitpunkt.
    _kontakt(uow, new_id(), tombstone=1, deleted_at="2026-08-03T00:00:00Z")
    _kontakt(uow, new_id(), deleted_at="2026-08-03T00:00:00Z")
    _tombstone(uow, "pid-1", RECONCILED_REASON)

    a = bestandsaggregate(uow.connection)

    assert a.aktive_kontakte == 5
    assert a.getombstonete_kontakte == 1
    # Weder aktive noch gelöschte Kontakte tauchen in den Tombstone-Zahlen auf.
    assert a.tombstone_zeilen_gesamt == 1
    assert a.offene_tombstones == 0


def test_leerer_bestand_ergibt_lauter_nullen(uow):
    a = bestandsaggregate(uow.connection)
    assert a.as_dict() == {
        "aktive_kontakte": 0, "getombstonete_kontakte": 0,
        "externe_identitaeten": 0, "tombstone_zeilen_gesamt": 0,
        "offene_tombstones": 0, "abgeschlossene_tombstones": 0,
        "mutationen_gesamt": 0, "mutationen_terminal": 0,
        "freigaben": 0, "audit_ereignisse": 0, "sync_laeufe": 0,
    }


def test_kontofilter_trennt_die_tombstones(uow):
    _tombstone(uow, "pid-a", "missing_in_enumeration", konto=KONTO)
    _tombstone(uow, "pid-b", "missing_in_enumeration", konto="acc-anderes")

    eigen = bestandsaggregate(uow.connection, provider_account_id=KONTO)
    alle = bestandsaggregate(uow.connection)

    assert eigen.offene_tombstones == 1
    assert alle.offene_tombstones == 2


# ═══ Definition kommt aus dem Produktivcode, nicht aus einer Kopie ══════════
def test_die_definition_ist_die_des_wiederherstellungsdienstes():
    from pathlib import Path

    modul = Path(
        "src/personaljarvis/contacts/diagnostics.py").read_text(encoding="utf-8")
    # Der Abschlussgrund wird importiert, nicht als Zeichenkette wiederholt.
    einfuhr = ("from personaljarvis.contacts.sync.recovery "
               "import RECONCILED_REASON")
    assert einfuhr in modul
    assert '"reconciled_after_suspicious_empty_enumeration"' not in modul

    dienst = Path(
        "src/personaljarvis/contacts/sync/recovery.py").read_text(encoding="utf-8")
    # Beide filtern gleich: alles ausser dem Abschlussgrund gilt als offen.
    assert "reason != ?" in dienst
    assert "reason != ?" in modul


def test_terminale_zustaende_decken_den_zustandsvorrat_korrekt_ab():
    from personaljarvis.contacts.domain.enums import MutationState

    vorrat = {z.value for z in MutationState}
    assert set(TERMINALE_MUTATIONSZUSTAENDE) <= vorrat
    # Offene Zustände dürfen nie als terminal gelten — sonst meldet ein
    # Bericht einen abgeschlossenen Vorgang, der noch senden kann.
    for offen in ("prepared", "awaiting_approval", "approved", "executing",
                  "outcome_unknown", "reconcile_required",
                  "manual_decision_required",
                  "provider_applied_pending_reconcile"):
        assert offen not in TERMINALE_MUTATIONSZUSTAENDE


def test_diagnostik_enthaelt_keine_schreibende_anweisung():
    """Read-only als Eigenschaft der Quelle, nicht nur als Absicht."""
    from pathlib import Path

    modul = Path(
        "src/personaljarvis/contacts/diagnostics.py").read_text(encoding="utf-8")
    for verboten in ("INSERT ", "UPDATE ", "DELETE ", "DROP ", "ALTER ",
                     "CREATE ", "REPLACE ", ".commit(", ".executescript("):
        assert verboten not in modul, verboten
