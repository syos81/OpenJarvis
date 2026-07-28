"""Prozessmanagement des Sidecars (Plan §15, Deadlock-/Zombie-Risiko).

Verbindliche Eigenschaften — jede ist aus dem Spike belegt oder aus einem dort
beobachteten Fehler abgeleitet:

* **Feste Argumentliste, kein Shell-String.** Kein `shell=True`.
* **Beide Drainer starten vor dem ersten Write** (Deadlock-Vermeidung).
* **Absolute Deadline je Request** — nie ein sich verlängerndes Zeitfenster.
* Ein Request endet **nie** als nacktes `queue.Empty`: jeder Ausgang trägt
  eine Fehlerklasse und PII-freie Diagnose.
* Child-Tod, Signalabbruch (z. B. SIGABRT), stdout-EOF, fremde Request-ID,
  ungültiges JSON und Protokollversionsfehler werden **unterschieden**.
* `terminate` → Frist → `kill` → Frist. Kein Zombie.
* **Kein automatischer Retry** — schon gar nicht bei Mutationen.
"""

from __future__ import annotations

import json
import os
import queue
import re
import signal
import subprocess
import threading
import time
from pathlib import Path
from types import TracebackType
from typing import Any

from personaljarvis.contacts.bridge import protocol
from personaljarvis.contacts.bridge.errors import (
    BridgeProcessError,
    BridgeProtocolError,
    MutationOutcomeUnknown,
    ProcessDiagnostics,
    ProcessFailureClass,
)
from personaljarvis.contacts.bridge.models import Handshake
from personaljarvis.contacts.bridge.resolver import SidecarLocation

__all__ = ["SidecarProcess", "DEFAULT_REQUEST_TIMEOUT"]

DEFAULT_REQUEST_TIMEOUT = 30.0
_START_TIMEOUT = 15.0
_TERMINATE_GRACE = 3.0
_KILL_GRACE = 3.0

# stderr wird begrenzt und gefiltert übernommen: selbst bei Fehlverhalten des
# Sidecars darf keine PII in Diagnosen oder Logs gelangen.
_STDERR_ALLOWED = re.compile(r"^\[contacts-bridge\][^@]*$")
_STDERR_MAX_LINES = 20
_STDERR_MAX_LEN = 200

_EOF = object()


class SidecarProcess:
    """Besitzt genau einen Sidecar-Kindprozess."""

    def __init__(self, location: SidecarLocation, *,
                 env: dict[str, str] | None = None) -> None:
        self._location = location
        self._env = env
        self._proc: subprocess.Popen[str] | None = None
        self._inbox: queue.Queue[Any] = queue.Queue()
        self._stderr_tail: list[str] = []
        self._stdout_eof = threading.Event()
        self._stderr_eof = threading.Event()
        self._next_id = 0
        self._handshake: Handshake | None = None
        self._lock = threading.Lock()

    # ── Zustand ─────────────────────────────────────────────────────────────
    @property
    def handshake(self) -> Handshake | None:
        return self._handshake

    @property
    def is_running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def _exit_code(self) -> int | None:
        return self._proc.poll() if self._proc else None

    def _exit_signal(self) -> int | None:
        """Signalnummer, falls der Child durch ein Signal endete (z. B. SIGABRT)."""
        code = self._exit_code()
        if code is None or code >= 0:
            return None
        return -code

    def safe_stderr(self) -> tuple[str, ...]:
        out = []
        for line in self._stderr_tail[-_STDERR_MAX_LINES:]:
            out.append(line[:_STDERR_MAX_LEN] if _STDERR_ALLOWED.match(line)
                       else "[redigiert: nicht-technische stderr-Zeile]")
        return tuple(out)

    # ── Start / Stop ────────────────────────────────────────────────────────
    def start(self, timeout: float = _START_TIMEOUT) -> Handshake:
        """Startet den Sidecar und liest den Handshake.

        Der Start berührt den Kontakte-Store **nicht**: der Sidecar meldet nur
        den bereits bekannten Autorisierungsstatus.
        """
        if self._proc is not None:
            assert self._handshake is not None
            return self._handshake

        self._proc = subprocess.Popen(
            [str(self._location.path)],          # feste Argumentliste
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, bufsize=1, env=self._env, shell=False,
        )
        # Beide Drainer VOR dem ersten Write.
        threading.Thread(target=self._drain_stdout, daemon=True).start()
        threading.Thread(target=self._drain_stderr, daemon=True).start()

        try:
            message = self._inbox.get(timeout=timeout)
        except queue.Empty:
            self._shutdown_child()
            raise BridgeProtocolError(
                "Sidecar hat keinen Handshake gesendet") from None
        if message is _EOF:
            self._shutdown_child()
            raise BridgeProtocolError("Sidecar endete vor dem Handshake")
        if not isinstance(message, dict) or message.get("type") != "ready":
            self._shutdown_child()
            raise BridgeProtocolError("Erste Zeile ist kein Handshake")

        handshake = Handshake.parse(message)
        if handshake.protocol_version != protocol.PROTOCOL_VERSION:
            self._shutdown_child()
            raise BridgeProtocolError(
                f"Inkompatible Protokollversion {handshake.protocol_version} "
                f"(erwartet {protocol.PROTOCOL_VERSION})"
            )
        self._handshake = handshake
        return handshake

    def stop(self) -> None:
        """Graziöser Shutdown; mehrfacher Aufruf ist harmlos."""
        if self._proc is None:
            return
        if self._proc.poll() is None:
            try:
                self.request(protocol.Operation.SHUTDOWN, timeout=3.0)
            except Exception:
                pass
        self._shutdown_child()

    def _shutdown_child(self) -> None:
        """terminate → Frist → kill → Frist. Hinterlässt keinen Zombie."""
        proc, self._proc = self._proc, None
        self._handshake = None
        if proc is None:
            return
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=_TERMINATE_GRACE)
            except subprocess.TimeoutExpired:
                proc.kill()
                try:
                    proc.wait(timeout=_KILL_GRACE)
                except subprocess.TimeoutExpired:
                    pass
        for stream in (proc.stdin, proc.stdout, proc.stderr):
            try:
                if stream is not None:
                    stream.close()
            except OSError:
                pass
        # `wait()` reapt den Prozess endgültig.
        try:
            proc.wait(timeout=_KILL_GRACE)
        except subprocess.TimeoutExpired:
            pass

    # ── Drainer ─────────────────────────────────────────────────────────────
    def _drain_stdout(self) -> None:
        assert self._proc and self._proc.stdout
        try:
            for raw in self._proc.stdout:
                line = raw.strip()
                if not line:
                    continue
                try:
                    self._inbox.put(protocol.decode_line(line))
                except (json.JSONDecodeError, ValueError):
                    self._inbox.put({"__invalid_json__": True})
        except (ValueError, OSError):
            pass
        finally:
            self._stdout_eof.set()
            self._inbox.put(_EOF)

    def _drain_stderr(self) -> None:
        assert self._proc and self._proc.stderr
        try:
            for raw in self._proc.stderr:
                self._stderr_tail.append(raw.rstrip())
                del self._stderr_tail[:-100]
        except (ValueError, OSError):
            pass
        finally:
            self._stderr_eof.set()

    # ── Request ─────────────────────────────────────────────────────────────
    def _diagnostics(self, rid: int, op: str, started: float,
                     wrong_ids: list[int | None], detail: str) -> ProcessDiagnostics:
        return ProcessDiagnostics(
            request_id=rid, operation=op,
            elapsed_seconds=round(time.time() - started, 3),
            child_exit_code=self._exit_code(), child_signal=self._exit_signal(),
            child_alive=self.is_running,
            stdout_eof=self._stdout_eof.is_set(),
            stderr_eof=self._stderr_eof.is_set(),
            wrong_response_ids=tuple(wrong_ids[:10]),
            stderr_tail=self.safe_stderr(), detail=detail,
        )

    def _fail(self, failure_class: str, rid: int, op: str, started: float,
              wrong_ids: list[int | None], detail: str) -> BridgeProcessError:
        """Erzeugt den typisierten Fehler und beendet den Child zuverlässig.

        Für mutierende Operationen wird auf `mutation_outcome_unknown`
        angehoben — **weder Erfolg noch Fehlschlag**, niemals ein Retry.
        """
        diag = self._diagnostics(rid, op, started, wrong_ids, detail)
        self._shutdown_child()
        if op in protocol.MUTATING_OPERATIONS and failure_class in (
            ProcessFailureClass.REQUEST_TIMEOUT,
            ProcessFailureClass.CHILD_EXITED,
            ProcessFailureClass.CHILD_SIGNALLED,
            ProcessFailureClass.STDOUT_EOF,
        ):
            return MutationOutcomeUnknown(failure_class, diag)
        return BridgeProcessError(failure_class, diag)

    def request(self, operation: str, payload: dict[str, Any] | None = None, *,
                timeout: float = DEFAULT_REQUEST_TIMEOUT) -> dict[str, Any]:
        """Sendet eine Anfrage und liefert die Antworthülle.

        Streaming-Antworten werden gesammelt und unter `result["items"]`
        zurückgegeben. Scheitert **immer** typisiert.
        """
        with self._lock:
            if self._proc is None or self._proc.stdin is None:
                raise BridgeProcessError(
                    ProcessFailureClass.CHILD_EXITED,
                    ProcessDiagnostics(
                        request_id=-1, operation=operation, elapsed_seconds=0.0,
                        child_exit_code=self._exit_code(), child_signal=None,
                        child_alive=False, stdout_eof=True, stderr_eof=True,
                        detail="Sidecar laeuft nicht"),
                )
            self._next_id += 1
            rid = self._next_id
            started = time.time()
            wrong_ids: list[int | None] = []
            try:
                self._proc.stdin.write(
                    protocol.encode_request(rid, operation, payload) + "\n")
                self._proc.stdin.flush()
            except (BrokenPipeError, OSError) as exc:
                raise self._fail(ProcessFailureClass.CHILD_EXITED, rid, operation,
                                 started, wrong_ids,
                                 f"stdin nicht beschreibbar: {exc.__class__.__name__}")

            stream: list[dict[str, Any]] = []
            deadline = started + timeout
            while True:
                remaining = deadline - time.time()
                if remaining <= 0:
                    raise self._fail(ProcessFailureClass.REQUEST_TIMEOUT, rid,
                                     operation, started, wrong_ids,
                                     f"keine Antwort binnen {timeout} s")
                try:
                    message = self._inbox.get(timeout=remaining)
                except queue.Empty:
                    if not self.is_running:
                        raise self._fail(self._exit_class(), rid, operation, started,
                                         wrong_ids, "Child beendet, keine Antwort") from None
                    raise self._fail(ProcessFailureClass.REQUEST_TIMEOUT, rid,
                                     operation, started, wrong_ids,
                                     f"keine Antwort binnen {timeout} s") from None

                if message is _EOF:
                    if not self.is_running:
                        raise self._fail(self._exit_class(), rid, operation, started,
                                         wrong_ids, "stdout EOF und Child beendet")
                    raise self._fail(ProcessFailureClass.STDOUT_EOF, rid, operation,
                                     started, wrong_ids,
                                     "stdout EOF bei laufendem Child")
                if not isinstance(message, dict):
                    continue
                if message.get("__invalid_json__"):
                    raise self._fail(ProcessFailureClass.PROTOCOL_ERROR, rid,
                                     operation, started, wrong_ids,
                                     "nicht parsebare Zeile auf stdout")
                version = message.get("protocolVersion")
                if version is not None and version != protocol.PROTOCOL_VERSION:
                    raise self._fail(ProcessFailureClass.PROTOCOL_VERSION_MISMATCH,
                                     rid, operation, started, wrong_ids,
                                     f"Antwort mit Protokollversion {version}")
                if message.get("requestId") != rid:
                    wrong_ids.append(message.get("requestId"))
                    if len(wrong_ids) > 50:
                        raise self._fail(ProcessFailureClass.RESPONSE_ID_MISMATCH,
                                         rid, operation, started, wrong_ids,
                                         "zu viele fremde Antwort-IDs")
                    continue
                if protocol.is_stream_item(message):
                    stream.append(message["item"])
                    continue
                if stream:
                    message.setdefault("result", {})["items"] = stream
                return message

    def _exit_class(self) -> str:
        return (ProcessFailureClass.CHILD_SIGNALLED if self._exit_signal() is not None
                else ProcessFailureClass.CHILD_EXITED)

    # ── Kontextmanager ──────────────────────────────────────────────────────
    def __enter__(self) -> "SidecarProcess":
        self.start()
        return self

    def __exit__(self, exc_type: type[BaseException] | None,
                 exc: BaseException | None, tb: TracebackType | None) -> None:
        self.stop()
