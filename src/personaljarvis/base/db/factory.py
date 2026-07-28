"""DatabaseConnectionFactory — die einzige Stelle, die Verbindungen zur
kanonischen `personal/jarvis.db` erzeugt (07 §1, ADR-0003).

Kein anderer Codepfad öffnet die Datenbank. Es gibt bewusst **keine** globale
Singleton-Verbindung: jede Factory-Instanz wird injiziert, jede Verbindung hat
einen Eigentümer.
"""

from __future__ import annotations

import sqlite3
import stat
from pathlib import Path

from personaljarvis.errors import ConfigurationError, DatabaseError

__all__ = ["ConnectionFactory", "default_database_path", "MIN_SQLITE_VERSION"]

# STRICT-Tabellen (verwendet in allen Migrationen) verlangen SQLite ≥ 3.37.
MIN_SQLITE_VERSION = (3, 37, 0)

_BUSY_TIMEOUT_MS = 5_000
_REQUIRED_FILE_MODE = 0o600


def default_database_path() -> Path:
    """`<OpenJarvis-Datenverzeichnis>/personal/jarvis.db` (06 §2).

    Der Import geschieht bewusst erst hier: `import personaljarvis` darf kein
    Verzeichnis anlegen und keinen Pfad auflösen.
    """
    from openjarvis.core.paths import get_data_dir

    return get_data_dir() / "personal" / "jarvis.db"


def _is_memory(path: Path | str) -> bool:
    return str(path) == ":memory:" or str(path).startswith("file::memory:")


class ConnectionFactory:
    """Erzeugt vorbereitete Verbindungen zur kanonischen Datenbank.

    Verbindlich je Verbindung (07 §1): Dateirechte 0600, WAL, `busy_timeout`,
    `PRAGMA foreign_keys=ON`, `sqlite3.Row` als `row_factory`.

    `:memory:` ist ausschließlich für Tests vorgesehen. Dort ist **WAL
    technisch nicht verfügbar** — SQLite liefert für In-Memory-Datenbanken
    `journal_mode=memory`. Das ist keine Abweichung von der Regel, sondern
    deren Grenze; Dateirechte entfallen aus demselben Grund.
    """

    def __init__(self, database_path: Path | str | None = None) -> None:
        self._path: Path | str = (
            database_path if database_path is not None else default_database_path()
        )
        self._memory = _is_memory(self._path)
        self._memory_connection: sqlite3.Connection | None = None
        # Genau eine offene UnitOfWork je Factory. Ohne diesen Zähler würde
        # eine verschachtelte UoW auf einer Dateidatenbank eine ZWEITE
        # Verbindung öffnen und im Schreib-Lock hängen statt sauber zu
        # scheitern (belegt durch den Verschachtelungstest).
        self._active_unit_of_work = False

    @property
    def database_path(self) -> Path | str:
        return self._path

    @property
    def is_memory(self) -> bool:
        return self._memory

    # ── Vorbereitung ────────────────────────────────────────────────────────
    def ensure_ready(self) -> None:
        """Verzeichnis anlegen und Dateirechte auf 0600 bringen.

        Ausdrücklich getrennt vom Konstruktor: das Erzeugen der Factory hat
        keine Nebenwirkung im Dateisystem.
        """
        if self._memory:
            return
        path = Path(self._path)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            if not path.exists():
                path.touch(mode=_REQUIRED_FILE_MODE)
            path.chmod(_REQUIRED_FILE_MODE)
        except OSError as exc:
            raise ConfigurationError(
                f"Datenbankverzeichnis nicht benutzbar ({type(exc).__name__})"
            ) from exc

    def _check_permissions(self, path: Path) -> None:
        mode = stat.S_IMODE(path.stat().st_mode)
        if mode != _REQUIRED_FILE_MODE:
            raise DatabaseError(
                f"Dateirechte der kanonischen Datenbank sind {oct(mode)}, "
                f"erwartet {oct(_REQUIRED_FILE_MODE)}"
            )

    def _prepare(self, conn: sqlite3.Connection) -> sqlite3.Connection:
        version = tuple(int(p) for p in sqlite3.sqlite_version.split("."))
        if version < MIN_SQLITE_VERSION:
            conn.close()
            raise ConfigurationError(
                "SQLite "
                + ".".join(str(p) for p in MIN_SQLITE_VERSION)
                + f" oder neuer erforderlich, gefunden {sqlite3.sqlite_version}"
            )
        conn.row_factory = sqlite3.Row
        # Reihenfolge ist wichtig: `PRAGMA foreign_keys` ist innerhalb einer
        # Transaktion wirkungslos (empirisch geprüft). isolation_level=None
        # hält uns im Autocommit, bis die UnitOfWork ausdrücklich BEGINnt.
        conn.execute(f"PRAGMA busy_timeout = {_BUSY_TIMEOUT_MS}")
        conn.execute("PRAGMA foreign_keys = ON")
        if not self._memory:
            mode = conn.execute("PRAGMA journal_mode = WAL").fetchone()[0]
            if str(mode).lower() != "wal":
                conn.close()
                raise DatabaseError(f"WAL nicht aktivierbar, journal_mode={mode}")
        if conn.execute("PRAGMA foreign_keys").fetchone()[0] != 1:
            conn.close()
            raise DatabaseError("foreign_keys konnte nicht aktiviert werden")
        return conn

    # ── Verbindungen ────────────────────────────────────────────────────────
    def connect(self) -> sqlite3.Connection:
        """Schreibfähige Verbindung.

        Für `:memory:` wird dieselbe Verbindung wiederverwendet — andernfalls
        wäre jede Testverbindung eine eigene, leere Datenbank.
        """
        if self._memory:
            if self._memory_connection is None:
                self._memory_connection = self._prepare(
                    sqlite3.connect(":memory:", isolation_level=None)
                )
            return self._memory_connection
        path = Path(self._path)
        if not path.exists():
            raise DatabaseError(
                "Kanonische Datenbank fehlt; ensure_ready() wurde nicht aufgerufen"
            )
        self._check_permissions(path)
        return self._prepare(sqlite3.connect(str(path), isolation_level=None))

    def connect_readonly(self) -> sqlite3.Connection:
        """Nur lesende Verbindung (`mode=ro`).

        Für In-Memory-Datenbanken existiert kein Nur-Lese-Modus; dort wird die
        Schreibverbindung zurückgegeben und das ist ausdrücklich dokumentiert.
        """
        if self._memory:
            return self.connect()
        path = Path(self._path)
        if not path.exists():
            raise DatabaseError("Kanonische Datenbank fehlt")
        self._check_permissions(path)
        uri = f"file:{path}?mode=ro"
        return self._prepare(sqlite3.connect(uri, uri=True, isolation_level=None))

    # ── UnitOfWork-Buchführung ──────────────────────────────────────────────
    @property
    def has_active_unit_of_work(self) -> bool:
        return self._active_unit_of_work

    def mark_unit_of_work_open(self) -> None:
        self._active_unit_of_work = True

    def mark_unit_of_work_closed(self) -> None:
        self._active_unit_of_work = False

    def close(self) -> None:
        """Gibt die In-Memory-Verbindung frei. Für Dateidatenbanken ohne Wirkung."""
        if self._memory_connection is not None:
            self._memory_connection.close()
            self._memory_connection = None
