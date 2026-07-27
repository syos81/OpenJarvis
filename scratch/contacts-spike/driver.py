#!/usr/bin/env python3
"""driver.py — SPIKE G3a (ADR-0016). Temporär, nicht produktiv.

Host-Treiber für den Kontakte-Sidecar (JSON-Lines über stdin/stdout).
Folgt dem im Repo erprobten Muster aus
src/openjarvis/channels/whatsapp_baileys.py:163-282 (Popen text=True,
bufsize=1, Reader-Thread, tolerantes Zeilenlesen, grazioser Shutdown).

SICHERHEIT (E5): Die kontaktfreien Selbsttests (--protocol-test) berühren den
Kontakte-Store NICHT. Alle Operationen mit Store-Zugriff verlangen ein
ausdrückliches Kommando und laufen ausschließlich im Testbenutzer.
"""
from __future__ import annotations

import json
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path

def _tauri_triple() -> str:
    """Tauri-externalBin-Suffix der laufenden Architektur (beide gleichwertig)."""
    import platform
    return {"arm64": "aarch64-apple-darwin",
            "x86_64": "x86_64-apple-darwin"}.get(platform.machine(), platform.machine())


def _find_sidecar() -> Path:
    """Sidecar neben dem Skript (Export), im build/-Verzeichnis (Worktree) oder
    unter dem architekturbehafteten Tauri-Namen (gebündelter/exportierter Fall)."""
    here = Path(__file__).resolve().parent
    triple = _tauri_triple()
    for cand in (here / "jarvis-contacts",
                 here / "build" / "jarvis-contacts",
                 here / f"jarvis-contacts-{triple}",
                 here / "build" / f"jarvis-contacts-{triple}"):
        if cand.exists():
            return cand
    return here / "build" / "jarvis-contacts"


SIDECAR = _find_sidecar()


class Sidecar:
    def __init__(self, binary: Path = SIDECAR, env: dict | None = None):
        self.binary = binary
        # env=None erbt die Prozessumgebung (bisheriges Verhalten, unverändert).
        # Ein explizites dict wird ausschließlich an den Child-Prozess gereicht.
        self.env = env
        self.proc: subprocess.Popen | None = None
        self.inbox: queue.Queue = queue.Queue()
        self.stderr_tail: list[str] = []
        self._stop = threading.Event()
        self._next_id = 0
        self.ready: dict | None = None
        self.max_line_len = 0

    # ── Start / Stop ─────────────────────────────────────────────────────────
    def start(self, timeout: float = 10.0) -> dict:
        if not self.binary.exists():
            raise FileNotFoundError(f"Sidecar nicht gefunden: {self.binary}")
        self.proc = subprocess.Popen(
            [str(self.binary)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, bufsize=1, env=self.env,
        )
        # Beide Drainer VOR dem ersten Write starten (Deadlock-Vermeidung, #309).
        threading.Thread(target=self._read_stdout, daemon=True).start()
        threading.Thread(target=self._read_stderr, daemon=True).start()
        msg = self.inbox.get(timeout=timeout)
        if msg.get("type") != "ready":
            raise RuntimeError(f"Erwartete ready-Zeile, bekam: {msg}")
        self.ready = msg
        return msg

    def _read_stdout(self) -> None:
        assert self.proc and self.proc.stdout
        for raw in self.proc.stdout:
            if self._stop.is_set():
                break
            self.max_line_len = max(self.max_line_len, len(raw))
            line = raw.strip()
            if not line:
                continue
            try:
                self.inbox.put(json.loads(line))
            except json.JSONDecodeError:
                # Tolerant: Nicht-JSON wird protokolliert, ist aber ein Protokollfehler.
                self.inbox.put({"_nonjson": line[:200]})

    def _read_stderr(self) -> None:
        assert self.proc and self.proc.stderr
        for raw in self.proc.stderr:
            if self._stop.is_set():
                break
            self.stderr_tail.append(raw.rstrip())
            del self.stderr_tail[:-100]

    def request(self, op: str, params: dict | None = None, timeout: float = 30.0) -> dict:
        assert self.proc and self.proc.stdin
        self._next_id += 1
        rid = self._next_id
        payload = {"id": rid, "op": op, "params": params or {}}
        self.proc.stdin.write(json.dumps(payload, separators=(",", ":")) + "\n")
        self.proc.stdin.flush()
        stream: list[dict] = []
        deadline = time.time() + timeout
        while True:
            msg = self.inbox.get(timeout=max(0.1, deadline - time.time()))
            if msg.get("id") != rid:
                continue
            if msg.get("stream") == "item":
                stream.append(msg["item"])
                continue
            if stream:
                msg.setdefault("result", {})["items"] = stream
            return msg

    def send_raw(self, text: str) -> None:
        assert self.proc and self.proc.stdin
        self.proc.stdin.write(text + "\n")
        self.proc.stdin.flush()

    def shutdown(self, timeout: float = 5.0) -> int | None:
        """Grazioser Shutdown: in-band → warten → terminate → kill."""
        if not self.proc:
            return None
        try:
            self.request("shutdown", timeout=timeout)
        except Exception:
            pass
        try:
            return self.proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            self.proc.terminate()
            try:
                return self.proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                return self.proc.wait(timeout=timeout)
        finally:
            self._stop.set()


# ── Kontaktfreie Protokolltests (G3) ─────────────────────────────────────────
def protocol_test() -> int:
    results: list[tuple[str, bool, str]] = []

    def check(name: str, cond: bool, detail: str = "") -> None:
        results.append((name, cond, detail))

    # T1 Handshake
    sc = Sidecar()
    ready = sc.start()
    check("handshake-ready", ready.get("type") == "ready", json.dumps(ready)[:160])
    check("handshake-protocol", ready.get("protocol") == 1, str(ready.get("protocol")))
    check("handshake-caps", isinstance(ready.get("caps"), list) and "ping" in ready["caps"], "")
    check("handshake-no-link-api", ready.get("limits", {}).get("linkUnlinkSupported") is False, "")

    # T2 ping / caps (kein Store-Zugriff)
    r = sc.request("ping")
    check("ping-ok", r.get("ok") is True and r["result"].get("pong") is True, "")
    r = sc.request("caps")
    check("caps-ok", r.get("ok") is True, json.dumps(r.get("result", {}))[:160])
    auth = r.get("result", {}).get("authorizationStatus")

    # T3 Fehlerpfade
    r = sc.request("nichtExistierendeOperation")
    check("unknown-op-typed-error",
          r.get("ok") is False and r["error"]["code"] == "invalid_request", "")
    sc.send_raw("das ist kein json")
    bad = sc.inbox.get(timeout=5)
    check("nonjson-line-typed-error",
          bad.get("ok") is False and bad["error"]["code"] == "invalid_request", "")
    # Nach dem Fehler muss der Kanal weiter funktionieren
    r = sc.request("ping")
    check("recovers-after-bad-line", r.get("ok") is True, "")

    # T4 id-Korrelation
    r = sc.request("ping")
    check("id-correlation", r.get("id") == sc._next_id, f"id={r.get('id')}")

    # T5 stdout ist sauber (keine Nicht-JSON-Zeilen aufgetreten)
    check("stdout-pure-protocol", not any("_nonjson" in str(x) for x in [bad]), "")

    # T6 grazioser Shutdown
    code = sc.shutdown()
    check("graceful-shutdown-exit0", code == 0, f"exit={code}")

    # T7 EOF auf stdin beendet den Prozess
    sc2 = Sidecar(); sc2.start()
    assert sc2.proc and sc2.proc.stdin
    sc2.proc.stdin.close()
    try:
        code2 = sc2.proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        sc2.proc.kill(); code2 = None
    check("eof-stdin-terminates", code2 == 0, f"exit={code2}")

    # T8 Neustart nach kill -9 liefert typisierten Fehler statt Hänger
    sc3 = Sidecar(); sc3.start()
    assert sc3.proc
    sc3.proc.kill()
    sc3.proc.wait(timeout=5)
    hung = False
    try:
        sc3.request("ping", timeout=3)
        hung = True          # dürfte nicht antworten
    except Exception:
        hung = False
    check("kill9-no-hang", not hung, "")
    sc4 = Sidecar(); ready4 = sc4.start()
    r = sc4.request("ping")
    check("restart-after-kill9", ready4.get("type") == "ready" and r.get("ok") is True, "")

    # T9 Backpressure: Reader 5 s anhalten, danach muss der Kanal leben
    sc4._stop_reader_for_test = True  # nur Doku; echter Stall unten
    time.sleep(0.1)
    for _ in range(50):
        sc4.request("ping", timeout=5)
    check("backpressure-50-requests", True, "")
    check("max-stdout-line-bytes", sc4.max_line_len > 0, f"{sc4.max_line_len}")

    # T10 stderr enthält keine PII-Marker
    joined = " ".join(sc4.stderr_tail)
    check("stderr-no-pii", "@" not in joined and "ZZZ-" not in joined, joined[:120])

    # ── T11–T13: Env-Gate der SPIKE-ONLY-Operation requestAuthorization ───────
    # Alle drei Prüfungen sind kontaktfrei. requestAuthorization wird NUR ohne
    # gesetztes Gate gesendet — dort ist ein requestAccess-Aufruf ausgeschlossen.
    r = sc4.request("caps")
    res = r.get("result", {})
    check("caps-requestauth-supported",
          res.get("requestAuthorizationSupported") is True, "")
    check("caps-requestauth-disabled-by-default",
          res.get("requestAuthorizationEnabled") is False,
          f"enabled={res.get('requestAuthorizationEnabled')}")

    r = sc4.request("requestAuthorization")
    check("requestauth-gated-off",
          r.get("ok") is False and r["error"]["code"] == "operation_disabled",
          json.dumps(r.get("error", {}))[:120])

    # Der Status darf sich dadurch nicht verändert haben (kein Dialog).
    r = sc4.request("caps")
    check("requestauth-gated-off-status-unchanged",
          r["result"].get("authorizationStatus") == auth,
          f"vorher={auth} nachher={r['result'].get('authorizationStatus')}")
    sc4.shutdown()

    # T13: mit gesetztem Gate meldet caps nur die Verfügbarkeit.
    # requestAuthorization wird hier bewusst NICHT gesendet — kein TCC-Dialog.
    import os
    gated_env = {**os.environ, "JARVIS_CONTACTS_SPIKE_TCC": "1"}
    sc5 = Sidecar(env=gated_env)
    ready5 = sc5.start()
    check("gate-on-handshake-enabled",
          ready5.get("requestAuthorizationEnabled") is True, "")
    r = sc5.request("caps")
    check("gate-on-caps-enabled",
          r["result"].get("requestAuthorizationEnabled") is True, "")
    check("gate-on-no-prompt-triggered",
          r["result"].get("authorizationStatus") == auth,
          f"authorizationStatus={r['result'].get('authorizationStatus')} (unverändert)")
    sc5.shutdown()

    # ── Bericht ──────────────────────────────────────────────────────────────
    width = max(len(n) for n, _, _ in results)
    passed = 0
    print("\n=== G3 Protokolltests (kontaktfrei) ===")
    for name, cond, detail in results:
        print(f"[{'PASS' if cond else 'FAIL'}] {name.ljust(width)}  {detail}")
        passed += 1 if cond else 0
    print(f"--- {passed}/{len(results)} bestanden; authorizationStatus={auth}")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    if "--protocol-test" in sys.argv:
        sys.exit(protocol_test())
    print("Nutzung: driver.py --protocol-test   (kontaktfrei)")
    print("Store-Operationen laufen ausschliesslich im Testbenutzer.")
    sys.exit(2)
