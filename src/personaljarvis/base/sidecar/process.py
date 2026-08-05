"""Prozessmanagement nativer Sidecars (Deadlock-/Zombie-Risiko).

Gehoben aus `contacts.bridge.process` (2026-08-04), als der Kalender denselben
Prozessvertrag brauchte. Verhalten unverändert; kontaktspezifisch war daran
nur der Operationssatz und der stderr-Marker — beides kommt jetzt als
`SidecarContract` herein.

Verbindliche Eigenschaften — jede ist aus dem Kontakte-Spike belegt oder aus
einem dort beobachteten Fehler abgeleitet:

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
import queue
import re
import subprocess
import threading
import time
from types import TracebackType
from typing import Any, Protocol

from personaljarvis.base.sidecar import envelope
from personaljarvis.base.sidecar.envelope import SidecarContract
from personaljarvis.base.sidecar.errors import (
    BridgeProcessError,
    BridgeProtocolError,
    MutationOutcomeUnknown,
    ProcessDiagnostics,
    ProcessFailureClass,
)

__all__ = ["SidecarProcess", "HandshakeParser", "DEFAULT_REQUEST_TIMEOUT"]

DEFAULT_REQUEST_TIMEOUT = 30.0
_START_TIMEOUT = 15.0
_TERMINATE_GRACE = 3.0
_KILL_GRACE = 3.0

_STDERR_MAX_LINES = 20
_STDERR_MAX_LEN = 200

# ── Ungefangene Objective-C-Ausnahmen ────────────────────────────────────────
#
# Warum es diese zweite Erkennung gibt: Stirbt ein Sidecar an einer nicht
# abgefangenen ObjC-Ausnahme, schreibt die Laufzeit einen mehrzeiligen Dump
# nach stderr — und **keine** dieser Zeilen trägt den eigenen Marker. Die
# Allowlist ersetzte deshalb den gesamten technischen Befund durch identische
# Platzhalter. Beim Kontakte-Create-Livetest am 2026-08-01 blieb von einem
# SIGABRT mitten in Apples Save-Pfad nichts übrig; die Ursache liess sich nur
# noch aus dem Absturzbericht des Systems rekonstruieren.
#
# Erhalten bleibt deshalb **die Ausnahmeklasse** — sie ist ein Bezeichner aus
# Apples Typsystem und trägt keine Nutzdaten. Der `reason` dagegen ist
# Freitext, den Apple mit beliebigen Werten füllen darf: er wird nicht
# übernommen, sondern nur als vorhanden gemeldet.
_OBJC_EXCEPTION = re.compile(
    r"uncaught exception(?: of type)?\s+'?(?P<klasse>[A-Za-z_][\w:.]*)'?")
#: Der Abschluss-Marker der C++-Laufzeit. Er trägt nie Nutzdaten.
_OBJC_TERMINATING = re.compile(r"^(?:libc\+\+abi|\*\*\* Terminating app)")
#: Eine Stapelzeile: laufende Nummer, Abbildname, Adresse, Symbol. Übernommen
#: werden ausschliesslich Abbildname und Symbol — Adressen sind wertlos und
#: der Rest der Zeile könnte alles enthalten. Die Zeichenklasse des Symbols
#: lässt Objective-C-Selektoren zu (`-[Klasse methode:]`), aber bewusst
#: **kein** `/`: damit kann keine Pfadangabe als Symbol durchrutschen.
_OBJC_FRAME = re.compile(
    r"^\s*\d+\s+(?P<bild>[\w.+-]+)\s+0x[0-9a-fA-F]+\s+"
    r"(?P<symbol>[\w:.$+\-\[\] ]{1,80})")


def _technische_stderr_zeile(line: str) -> str | None:
    """Der technische Kern einer nativen Absturzzeile — oder `None`.

    Gibt niemals Freitext des Systems zurück, sondern ausschliesslich
    zusammengesetzte Angaben aus geprüften Bestandteilen.
    """
    treffer = _OBJC_EXCEPTION.search(line)
    if treffer:
        grund = "reason vorhanden" if "reason:" in line else "ohne reason"
        return f"[nativ] uncaught {treffer.group('klasse')} ({grund})"
    if _OBJC_TERMINATING.match(line):
        return "[nativ] Laufzeit beendet den Prozess (uncaught exception)"
    rahmen = _OBJC_FRAME.match(line)
    if rahmen:
        symbol = rahmen.group("symbol").strip()
        return f"[nativ] frame {rahmen.group('bild')} {symbol}"[:_STDERR_MAX_LEN]
    return None


_EOF = object()


class HandshakeParser(Protocol):
    """Wandelt die `ready`-Zeile in das Handshake-Objekt des Moduls."""

    def __call__(self, message: dict[str, Any]) -> Any: ...


class SidecarProcess:
    """Besitzt genau einen Sidecar-Kindprozess.

    `binary_path` ist ein bereits geprüfter Pfad (siehe `resolver`);
    `contract` liefert Operationssatz und stderr-Marker; `parse_handshake`
    erzeugt das modulspezifische Handshake-Objekt. Der Prozess selbst kennt
    keine Fachlichkeit.
    """

    def __init__(self, binary_path: str, contract: SidecarContract,
                 parse_handshake: HandshakeParser, *,
                 env: dict[str, str] | None = None) -> None:
        self._binary_path = str(binary_path)
        self._contract = contract
        self._parse_handshake = parse_handshake
        self._stderr_allowed = re.compile(
            r"^\[" + re.escape(contract.stderr_prefix) + r"\][^@]*$")
        self._env = env
        self._proc: subprocess.Popen[str] | None = None
        self._inbox: queue.Queue[Any] = queue.Queue()
        self._stderr_tail: list[str] = []
        self._stdout_eof = threading.Event()
        self._stderr_eof = threading.Event()
        self._next_id = 0
        self._handshake: Any | None = None
        self._lock = threading.Lock()

    # ── Zustand ─────────────────────────────────────────────────────────────
    @property
    def handshake(self) -> Any | None:
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
        """stderr in diagnosetauglicher, PII-freier Form.

        Drei Klassen, in dieser Reihenfolge: eigene Marker-Zeilen unverändert
        (sie sind schon technisch), native Absturzzeilen in zusammengesetzter
        Form (siehe `_technische_stderr_zeile`), alles Übrige redigiert. Es
        wird nie eine fremde Zeile wörtlich übernommen.
        """
        out = []
        for line in self._stderr_tail[-_STDERR_MAX_LINES:]:
            if self._stderr_allowed.match(line):
                out.append(line[:_STDERR_MAX_LEN])
                continue
            technisch = _technische_stderr_zeile(line)
            out.append(technisch if technisch is not None
                       else "[redigiert: nicht-technische stderr-Zeile]")
        return tuple(out)

    # ── Start / Stop ────────────────────────────────────────────────────────
    def start(self, timeout: float = _START_TIMEOUT) -> Any:
        """Startet den Sidecar und liest den Handshake.

        Der Start berührt den Provider-Store **nicht**: der Sidecar meldet nur
        den bereits bekannten Autorisierungsstatus.
        """
        if self._proc is not None:
            assert self._handshake is not None
            return self._handshake

        self._proc = subprocess.Popen(
            [self._binary_path],                 # feste Argumentliste
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

        handshake = self._parse_handshake(message)
        if handshake.protocol_version != self._contract.protocol_version:
            self._shutdown_child()
            raise BridgeProtocolError(
                f"Inkompatible Protokollversion {handshake.protocol_version} "
                f"(erwartet {self._contract.protocol_version})"
            )
        self._handshake = handshake
        return handshake

    def stop(self) -> None:
        """Graziöser Shutdown; mehrfacher Aufruf ist harmlos."""
        if self._proc is None:
            return
        if self._proc.poll() is None:
            try:
                self.request(self._contract.shutdown_operation, timeout=3.0)
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
                    self._inbox.put(envelope.decode_line(line))
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
        if op in self._contract.mutating_operations and failure_class in (
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
                    envelope.encode_request(
                        rid, operation, payload,
                        protocol_version=self._contract.protocol_version) + "\n")
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
                        raise self._fail(
                            self._exit_class(), rid, operation, started,
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
                if version is not None and version != self._contract.protocol_version:
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
                if envelope.is_stream_item(message):
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
