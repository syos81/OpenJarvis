"""UnitOfWork — genau eine Transaktion, genau ein Abschluss (07 §2).

Ein Orchestrator öffnet die UoW, Repositories arbeiten auf **derselben**
Verbindung, Commit oder Rollback erfolgt genau einmal am Ende. Es gibt keine
stille Autocommit-Semantik und keinen Teil-Commit.

Verschachtelung wird **fail-closed abgelehnt** statt stillschweigend auf einen
Savepoint abgebildet: ein zweites `BEGIN` auf derselben Verbindung würde die
Zusicherung „ein Commit am Ende" unbemerkt aushebeln.
"""

from __future__ import annotations

import sqlite3
from types import TracebackType

from personaljarvis.base.db.factory import ConnectionFactory
from personaljarvis.errors import TransactionError

__all__ = ["UnitOfWork"]


class UnitOfWork:
    """Transaktionskontext über einer Verbindung der ConnectionFactory."""

    def __init__(self, factory: ConnectionFactory) -> None:
        self._factory = factory
        self._connection: sqlite3.Connection | None = None
        self._entered = False
        self._settled = False

    # ── Kontextmanager ──────────────────────────────────────────────────────
    def __enter__(self) -> UnitOfWork:
        if self._entered:
            raise TransactionError(
                "UnitOfWork ist bereits geöffnet; Verschachtelung ist nicht zulässig"
            )
        if self._factory.has_active_unit_of_work:
            raise TransactionError(
                "Es läuft bereits eine UnitOfWork auf dieser Datenbank; "
                "Verschachtelung ist nicht zulässig"
            )
        conn = self._factory.connect()
        if conn.in_transaction:
            raise TransactionError(
                "Auf dieser Verbindung läuft bereits eine Transaktion"
            )
        # BEGIN IMMEDIATE erwirbt die Schreibsperre sofort statt beim ersten
        # Schreibzugriff — das macht Konflikte deterministisch sichtbar.
        conn.execute("BEGIN IMMEDIATE")
        self._factory.mark_unit_of_work_open()
        self._connection = conn
        self._entered = True
        self._settled = False
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> bool:
        if exc_type is not None:
            self.rollback()
            return False
        if not self._settled:
            self.commit()
        return False

    # ── Zugriff ─────────────────────────────────────────────────────────────
    @property
    def connection(self) -> sqlite3.Connection:
        if self._connection is None or not self._entered:
            raise TransactionError("UnitOfWork ist nicht geöffnet")
        return self._connection

    def execute(self, sql: str, parameters: tuple | dict = ()) -> sqlite3.Cursor:
        return self.connection.execute(sql, parameters)

    def executemany(self, sql: str, seq) -> sqlite3.Cursor:
        return self.connection.executemany(sql, seq)

    # ── Abschluss ───────────────────────────────────────────────────────────
    def _settle(self) -> None:
        """Gemeinsamer Abschluss: Buchführung schließen und die eigene
        Datei-Verbindung deterministisch freigeben.

        Die In-Memory-Verbindung gehört der Factory (geteilt über alle
        Aufrufer) und wird ausdrücklich **nicht** geschlossen. Für
        Dateidatenbanken wäre ein Verlass auf den Garbage Collector keine
        Freigabe-Garantie — ein festgehaltenes Traceback hielte Verbindung
        und WAL-Handle beliebig lange offen.
        """
        self._settled = True
        self._entered = False
        self._factory.mark_unit_of_work_closed()
        if self._connection is not None and not self._factory.is_memory:
            self._connection.close()
        self._connection = None

    def commit(self) -> None:
        # Reihenfolge: erst der abgeschlossene Fall, sonst meldet ein zweiter
        # Commit irreführend „ohne offene UnitOfWork".
        if self._settled:
            raise TransactionError("UnitOfWork wurde bereits abgeschlossen")
        if not self._entered:
            raise TransactionError("Commit ohne offene UnitOfWork")
        assert self._connection is not None
        try:
            self._connection.execute("COMMIT")
        except Exception:
            # Ein fehlgeschlagener Commit darf keine offene Transaktion und
            # keine offene Verbindung zurücklassen.
            try:
                if self._connection.in_transaction:
                    self._connection.execute("ROLLBACK")
            finally:
                self._settle()
            raise
        self._settle()

    def rollback(self) -> None:
        if not self._entered:
            return
        assert self._connection is not None
        try:
            if self._connection.in_transaction:
                self._connection.execute("ROLLBACK")
        finally:
            self._settle()
