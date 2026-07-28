"""ConnectionFactory und UnitOfWork (07 §1/§2). Kontaktfrei."""

from __future__ import annotations

import sqlite3
import stat

import pytest

from pathlib import Path

import personaljarvis.base.db.factory as factory_module
from personaljarvis.base.db.factory import ConnectionFactory, default_database_path
from personaljarvis.base.db.unit_of_work import UnitOfWork
from personaljarvis.errors import ConfigurationError, DatabaseError, TransactionError


# ── ConnectionFactory ────────────────────────────────────────────────────────
def test_foreign_keys_sind_aktiv(factory):
    conn = factory.connect()
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1


def test_wal_bei_dateidatenbank(factory):
    conn = factory.connect()
    assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"


def test_in_memory_hat_kein_wal_und_das_ist_dokumentiert():
    """SQLite kann für `:memory:` kein WAL — belegte Grenze, keine Abweichung."""
    f = ConnectionFactory(":memory:")
    f.ensure_ready()
    conn = f.connect()
    assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "memory"
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    f.close()


def test_busy_timeout_gesetzt(factory):
    conn = factory.connect()
    assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 5000


def test_row_factory_liefert_benannte_spalten(factory):
    conn = factory.connect()
    row = conn.execute("SELECT 1 AS eins, 2 AS zwei").fetchone()
    assert isinstance(row, sqlite3.Row)
    assert row["eins"] == 1 and row["zwei"] == 2


def test_dateirechte_sind_0600(factory, db_path):
    assert stat.S_IMODE(db_path.stat().st_mode) == 0o600


def test_zu_offene_dateirechte_werden_abgelehnt(factory, db_path):
    db_path.chmod(0o644)
    with pytest.raises(DatabaseError, match="Dateirechte"):
        factory.connect()


def test_readonly_verbindung_verweigert_schreiben(migrated_factory):
    conn = migrated_factory.connect_readonly()
    with pytest.raises(sqlite3.OperationalError):
        conn.execute("CREATE TABLE darf_nicht (a INTEGER)")


def test_readonly_verbindung_darf_lesen(migrated_factory):
    conn = migrated_factory.connect_readonly()
    assert conn.execute("SELECT count(*) FROM contacts").fetchone()[0] == 0


def test_pfad_ist_injizierbar(tmp_path):
    ziel = tmp_path / "eigener" / "ort.db"
    f = ConnectionFactory(ziel)
    f.ensure_ready()
    assert f.database_path == ziel
    assert ziel.exists()
    f.close()


def test_kein_hartkodierter_benutzerpfad_im_quelltext():
    """Der Standardpfad wird aus der OpenJarvis-Konvention abgeleitet.

    Geprüft wird der Quelltext, nicht der aufgelöste Wert: dass der
    aufgelöste Pfad unter dem Heimatverzeichnis liegt, ist richtig und gewollt
    — verboten ist ein im Code festverdrahteter Benutzer- oder Paketpfad.
    """
    quelle = Path(factory_module.__file__).read_text()
    assert "get_data_dir" in quelle
    assert "/Users/" not in quelle
    assert "/Users/Shared" not in quelle
    assert str(default_database_path()).endswith("personal/jarvis.db")


def test_konstruktor_hat_keine_dateisystem_nebenwirkung(tmp_path):
    ziel = tmp_path / "noch-nicht" / "da.db"
    ConnectionFactory(ziel)
    assert not ziel.parent.exists()


def test_verbindung_ohne_ensure_ready_scheitert(tmp_path):
    f = ConnectionFactory(tmp_path / "fehlt.db")
    with pytest.raises(DatabaseError, match="fehlt"):
        f.connect()


def test_nicht_beschreibbares_verzeichnis_meldet_konfigurationsfehler(tmp_path):
    gesperrt = tmp_path / "gesperrt"
    gesperrt.mkdir(mode=0o500)
    try:
        f = ConnectionFactory(gesperrt / "unter" / "x.db")
        with pytest.raises(ConfigurationError):
            f.ensure_ready()
    finally:
        gesperrt.chmod(0o700)


def test_keine_globale_singleton_verbindung(migrated_factory):
    a = migrated_factory.connect()
    b = migrated_factory.connect()
    assert a is not b


# ── UnitOfWork ───────────────────────────────────────────────────────────────
def _tabelle(conn) -> None:
    conn.execute("CREATE TABLE IF NOT EXISTS probe (a INTEGER)")


def test_commit_bei_erfolg(migrated_factory):
    conn = migrated_factory.connect()
    _tabelle(conn)
    with UnitOfWork(migrated_factory) as uow:
        uow.execute("INSERT INTO probe VALUES (1)")
    assert conn.execute("SELECT count(*) FROM probe").fetchone()[0] == 1


def test_rollback_bei_fehler(migrated_factory):
    conn = migrated_factory.connect()
    _tabelle(conn)
    with pytest.raises(RuntimeError):
        with UnitOfWork(migrated_factory) as uow:
            uow.execute("INSERT INTO probe VALUES (1)")
            raise RuntimeError("Abbruch")
    assert conn.execute("SELECT count(*) FROM probe").fetchone()[0] == 0


def test_kein_teil_commit(migrated_factory):
    """Zwei Schreibvorgänge, der zweite scheitert ⇒ auch der erste ist weg."""
    conn = migrated_factory.connect()
    _tabelle(conn)
    with pytest.raises(sqlite3.OperationalError):
        with UnitOfWork(migrated_factory) as uow:
            uow.execute("INSERT INTO probe VALUES (1)")
            uow.execute("INSERT INTO gibt_es_nicht VALUES (2)")
    assert conn.execute("SELECT count(*) FROM probe").fetchone()[0] == 0


def test_verschachtelung_wird_fail_closed_abgelehnt(migrated_factory):
    with UnitOfWork(migrated_factory):
        with pytest.raises(TransactionError, match="Verschachtelung"):
            with UnitOfWork(migrated_factory):
                pass


def test_erneutes_betreten_derselben_uow_abgelehnt(migrated_factory):
    uow = UnitOfWork(migrated_factory)
    with uow:
        with pytest.raises(TransactionError, match="bereits geöffnet"):
            uow.__enter__()


def test_zugriff_ohne_offene_uow_abgelehnt(migrated_factory):
    uow = UnitOfWork(migrated_factory)
    with pytest.raises(TransactionError, match="nicht geöffnet"):
        _ = uow.connection


def test_doppelter_commit_abgelehnt(migrated_factory):
    conn = migrated_factory.connect()
    _tabelle(conn)
    uow = UnitOfWork(migrated_factory)
    with uow:
        uow.execute("INSERT INTO probe VALUES (1)")
        uow.commit()
        with pytest.raises(TransactionError, match="bereits abgeschlossen"):
            uow.commit()


def test_keine_stille_autocommit_semantik(migrated_factory):
    """Ohne offene UoW schreibt niemand — die Verbindung ist im Autocommit,
    aber jeder Schreibpfad des Moduls geht durch die UnitOfWork."""
    conn = migrated_factory.connect()
    assert conn.in_transaction is False
    with UnitOfWork(migrated_factory) as uow:
        assert uow.connection.in_transaction is True
