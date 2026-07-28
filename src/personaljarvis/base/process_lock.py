"""Exklusive Prozesssperre `personal/serve.lock` (04 §1 Schritt 1, 07 §5, AV-21).

Genau **ein** Schreibprozess darf die kanonische Datenbank bedienen — auch im
CLI-In-Process-Modus. Die Sperre wird als Erstes im Bootstrap erworben und als
Letztes freigegeben.

Mechanik: `fcntl.flock(LOCK_EX | LOCK_NB)`. Die Sperre hängt am **offenen
Dateideskriptor**, nicht am Dateinamen. Daraus folgen zwei Eigenschaften, die
diese Klasse ausdrücklich zusichert:

* Eine zurückgebliebene Lockdatei blockiert **nichts**. Nur eine aktiv
  gehaltene Sperre verweigert den zweiten Erwerb — ein abgestürzter Prozess
  hinterlässt daher keine Blockade (kein manuelles Aufräumen nötig).
* Die Sperre gilt prozessübergreifend **und** innerhalb desselben Prozesses,
  weil jeder Erwerb einen eigenen Deskriptor öffnet.

**Inhalt der Datei ist reine Technik** (04 §1, 09 §1: Port-Discovery): PID,
Startzeit, optionaler Port. Niemals Kontaktdaten, Benutzernamen, Pfade des
Heimatverzeichnisses oder Geheimnisse.
"""

from __future__ import annotations

import errno
import fcntl
import json
import os
import stat
import time
from pathlib import Path
from types import TracebackType

from personaljarvis.errors import ConfigurationError, PersonalJarvisError

__all__ = ["ProcessLock", "ProcessLockError", "default_lock_path", "LOCK_FILENAME"]

LOCK_FILENAME = "serve.lock"

_DIR_MODE = 0o700
_FILE_MODE = 0o600


class ProcessLockError(PersonalJarvisError):
    """Die exklusive Sperre konnte nicht erworben werden (fail-closed)."""


def default_lock_path() -> Path:
    """`<OpenJarvis-Datenverzeichnis>/personal/serve.lock`.

    Der Import geschieht bewusst erst hier, damit `import personaljarvis`
    weiterhin ohne jede Nebenwirkung bleibt. **Kein hartkodierter
    Benutzerpfad** — der Ort kommt ausschließlich aus der Konfiguration.
    """
    from openjarvis.core.paths import get_data_dir

    return get_data_dir() / "personal" / LOCK_FILENAME


class ProcessLock:
    """Exklusive, nicht blockierende Dateisperre mit technischen Metadaten.

    Verwendung als Kontextmanager oder über `acquire()`/`release()`.
    `release()` ist idempotent; ein doppelter Aufruf ist harmlos.
    """

    def __init__(self, lock_path: Path | str | None = None, *, port: int | None = None) -> None:
        self._path = Path(lock_path) if lock_path is not None else None
        self._port = port
        self._fd: int | None = None

    # ── Zustand ─────────────────────────────────────────────────────────────
    @property
    def path(self) -> Path:
        if self._path is None:
            self._path = default_lock_path()
        return self._path

    @property
    def is_held(self) -> bool:
        return self._fd is not None

    # ── Erwerb / Freigabe ───────────────────────────────────────────────────
    def acquire(self) -> "ProcessLock":
        """Erwirbt die Sperre oder scheitert sofort — es wird nie gewartet."""
        if self._fd is not None:
            return self

        path = self.path
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            # Verzeichnisrechte hart setzen: die Sperre liegt neben der
            # kanonischen Datenbank, das Verzeichnis gehört ausschliesslich
            # dem Eigentuemer.
            os.chmod(path.parent, _DIR_MODE)
        except OSError as exc:
            raise ConfigurationError(
                f"Sperrverzeichnis nicht benutzbar: {exc.__class__.__name__}"
            ) from exc

        try:
            fd = os.open(path, os.O_RDWR | os.O_CREAT, _FILE_MODE)
        except OSError as exc:
            raise ConfigurationError(
                f"Sperrdatei nicht anlegbar: {exc.__class__.__name__}"
            ) from exc

        try:
            os.fchmod(fd, _FILE_MODE)
        except OSError:
            # Auf manchen Dateisystemen nicht unterstützt — die Sperre selbst
            # bleibt gültig, daher kein fail-closed an dieser Stelle.
            pass

        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            os.close(fd)
            if exc.errno in (errno.EACCES, errno.EAGAIN, errno.EWOULDBLOCK):
                raise ProcessLockError(
                    "Ein anderer Personal-Jarvis-Prozess haelt die exklusive "
                    "Sperre. Es wird kein zweiter Schreibprozess gestartet."
                ) from exc
            raise ProcessLockError(
                f"Sperre nicht erwerbbar: {exc.__class__.__name__}"
            ) from exc

        self._fd = fd
        self._write_metadata()
        return self

    def release(self) -> None:
        """Gibt die Sperre frei. Mehrfacher Aufruf ist harmlos."""
        fd, self._fd = self._fd, None
        if fd is None:
            return
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        except OSError:
            pass
        finally:
            try:
                os.close(fd)
            except OSError:
                pass
        # Die Datei bleibt bewusst liegen: sie blockiert niemanden (die Sperre
        # haengt am Deskriptor) und dient der Port-Discovery bis zum naechsten
        # Start.

    # ── Metadaten ───────────────────────────────────────────────────────────
    def _write_metadata(self) -> None:
        """Schreibt ausschliesslich technische, PII-freie Metadaten."""
        assert self._fd is not None
        payload = {
            "pid": os.getpid(),
            "started_at": time.time(),
            "port": self._port,
        }
        blob = json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n"
        try:
            os.ftruncate(self._fd, 0)
            os.lseek(self._fd, 0, os.SEEK_SET)
            os.write(self._fd, blob.encode("utf-8"))
            os.fsync(self._fd)
        except OSError:
            # Metadaten sind Diagnose, nicht Vertrag — ihr Fehlschlag darf die
            # bereits gehaltene Sperre nicht entwerten.
            pass

    def read_metadata(self) -> dict[str, object] | None:
        """Liest die Metadaten der Sperrdatei; `None`, wenn unlesbar."""
        try:
            raw = self.path.read_text(encoding="utf-8").strip()
        except OSError:
            return None
        if not raw:
            return None
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return None
        return data if isinstance(data, dict) else None

    def file_mode(self) -> int:
        """Effektive Dateirechte der Sperrdatei (für Tests und Diagnose)."""
        return stat.S_IMODE(self.path.stat().st_mode)

    # ── Kontextmanager ──────────────────────────────────────────────────────
    def __enter__(self) -> "ProcessLock":
        return self.acquire()

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.release()
