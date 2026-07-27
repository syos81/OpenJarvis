#!/usr/bin/env python3
"""test_driver_failmodes.py — SPIKE G3a (ADR-0016). Temporär, nicht produktiv.

Kontaktfreie Tests der Fail-closed-Semantik von driver.py und phase_b.py.

Es wird AUSSCHLIESSLICH gegen Fake-Sidecars (kleine Python-Skripte) getestet.
Der echte Kontakte-Sidecar wird nicht gestartet, es gibt keine
Contacts-Operation, keinen TCC-Dialog und keinen Zugriff auf echte Kontakte.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import driver  # noqa: E402
import phase_b  # noqa: E402
from driver import DriverError, Sidecar  # noqa: E402

RESULTS: list[tuple[str, bool, str]] = []
READY = ('{"type":"ready","protocol":1,"authorizationStatus":"notDetermined",'
         '"keySetVersion":1,"caps":["ping"],"limits":{"linkUnlinkSupported":false}}')


def check(name: str, cond: bool, detail: str = "") -> None:
    RESULTS.append((name, bool(cond), str(detail)[:200]))
    print(f"[{'PASS' if cond else 'FAIL'}] {name}  {str(detail)[:150]}")


def fake(tmp: Path, name: str, body: str) -> Path:
    """Erzeugt einen ausfuehrbaren Fake-Sidecar."""
    p = tmp / name
    p.write_text("#!/usr/bin/env python3\n"
                 "import sys, time, json\n"
                 f"READY = {READY!r}\n" + body)
    p.chmod(0o755)
    return p


def start(p: Path) -> Sidecar:
    sc = Sidecar(binary=p)
    sc.start()
    return sc


def expect_error(name: str, sc: Sidecar, op: str, klass: str,
                 timeout: float = 1.5, params: dict | None = None) -> DriverError | None:
    try:
        sc.request(op, params or {}, timeout=timeout)
    except DriverError as e:
        check(name, e.error_class == klass,
              f"{e.error_class} (erwartet {klass}), "
              f"elapsed={e.fields.get('elapsed_seconds')}s")
        return e
    except Exception as e:                                    # pragma: no cover
        check(name, False, f"falscher Ausnahmetyp {type(e).__name__}: {e}")
        return None
    check(name, False, f"kein Fehler — erwartet {klass}")
    return None


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="failmodes-")).resolve()

    # 1) Normale Antwort
    p = fake(tmp, "ok.py", """
print(READY, flush=True)
for line in sys.stdin:
    d = json.loads(line)
    print(json.dumps({"id": d["id"], "ok": True, "result": {"pong": True}}), flush=True)
""")
    sc = start(p)
    r = sc.request("ping", timeout=5)
    check("01-normale-antwort", r.get("ok") is True and r["result"]["pong"] is True)
    sc.shutdown()

    # 2) Sidecar antwortet nie -> request_timeout (Child lebt)
    p = fake(tmp, "silent.py", """
print(READY, flush=True)
time.sleep(600)
""")
    sc = start(p)
    e = expect_error("02-keine-antwort-timeout", sc, "ping", driver.ERR_REQUEST_TIMEOUT)
    check("02b-child-wurde-beendet", e is not None and e.fields.get("child_alive") is True,
          f"child_alive vor kill={e.fields.get('child_alive') if e else '?'}")

    # 3) Sidecar beendet sich vor der Antwort -> child_exited
    p = fake(tmp, "exiter.py", """
print(READY, flush=True)
sys.stdin.readline()
sys.exit(3)
""")
    sc = start(p)
    e = expect_error("03-child-exited", sc, "ping", driver.ERR_CHILD_EXITED, timeout=5)
    check("03b-exitcode-erfasst", e is not None and e.fields.get("child_exit_code") == 3,
          f"exit={e.fields.get('child_exit_code') if e else '?'}")

    # 4) stdout EOF vor der Antwort, Child laeuft weiter -> stdout_eof
    # os.close(1): sys.stdout.close() allein erzeugt beim Elternprozess KEIN
    # EOF, weil der Interpreter den Deskriptor offen haelt.
    p = fake(tmp, "eof.py", """
import os
print(READY, flush=True)
sys.stdin.readline()
os.close(1)
time.sleep(600)
""")
    sc = start(p)
    e = expect_error("04-stdout-eof", sc, "ping", driver.ERR_STDOUT_EOF, timeout=5)
    check("04b-stdout-eof-flag", e is not None and e.fields.get("stdout_eof") is True)

    # 5) stderr wird begrenzt und gefiltert
    p = fake(tmp, "noisy.py", r"""
print(READY, flush=True)
sys.stdin.readline()
for i in range(200):
    print("[sidecar] stage=probe%d" % i, file=sys.stderr, flush=True)
print("geheim: max@example.invalid", file=sys.stderr, flush=True)
time.sleep(600)
""")
    sc = start(p)
    e = expect_error("05-stderr-begrenzt", sc, "ping", driver.ERR_REQUEST_TIMEOUT)
    tail = e.fields.get("stderr_tail") if e else []
    check("05b-stderr-max-20-zeilen", len(tail) <= 20, f"{len(tail)} Zeilen")
    check("05c-stderr-pii-redigiert",
          not any("@" in l for l in tail) and any("redigiert" in l for l in tail),
          "E-Mail-artige Zeile wurde redigiert")

    # 6) Falsche Request-ID -> response_id_mismatch, IDs festgehalten
    p = fake(tmp, "wrongid.py", """
print(READY, flush=True)
for line in sys.stdin:
    for k in range(60):
        print(json.dumps({"id": 9000 + k, "ok": True, "result": {}}), flush=True)
""")
    sc = start(p)
    e = expect_error("06-falsche-request-id", sc, "ping",
                     driver.ERR_RESPONSE_ID_MISMATCH, timeout=5)
    check("06b-fremde-ids-festgehalten",
          bool(e and e.fields.get("wrong_response_ids")),
          f"{(e.fields.get('wrong_response_ids') or [])[:3]}...")

    # 7) Ungueltige JSON-Antwort -> protocol_error
    p = fake(tmp, "badjson.py", """
print(READY, flush=True)
sys.stdin.readline()
print("das ist kein json", flush=True)
time.sleep(600)
""")
    sc = start(p)
    expect_error("07-ungueltiges-json", sc, "ping", driver.ERR_PROTOCOL_ERROR, timeout=5)

    # 8) Mutationstimeout -> mutation_outcome_unknown
    p = fake(tmp, "silent2.py", """
print(READY, flush=True)
time.sleep(600)
""")
    sc = start(p)
    e = expect_error("08-mutation-outcome-unknown", sc, "create",
                     driver.ERR_MUTATION_OUTCOME_UNKNOWN,
                     params={"givenName": "ZZZ-JarvisTest-X"})
    check("08b-zugrundeliegende-klasse",
          e is not None and e.fields.get("underlying_class") == driver.ERR_REQUEST_TIMEOUT,
          f"underlying={e.fields.get('underlying_class') if e else '?'}")
    check("08c-outcome-unknown-flag", e is not None and e.outcome_unknown)

    # 9) Kein Mutation-Retry: genau EIN create erreicht den Sidecar
    counter = tmp / "createcount.txt"
    p = fake(tmp, "counter.py", f"""
print(READY, flush=True)
CNT = {str(counter)!r}
for line in sys.stdin:
    d = json.loads(line)
    if d.get("op") == "create":
        with open(CNT, "a") as fh:
            fh.write("x")
    time.sleep(600)
""")
    sc = start(p)
    try:
        sc.request("create", {"givenName": "ZZZ-JarvisTest-X"}, timeout=1.5)
    except DriverError:
        pass
    n = len(counter.read_text()) if counter.exists() else 0
    check("09-kein-mutation-retry", n == 1, f"create-Aufrufe beim Sidecar: {n}")

    # 10) Kein automatisches Cleanup: halt_outcome_unknown beendet sofort
    #     und sendet danach keine Operation mehr.
    err = DriverError(driver.ERR_MUTATION_OUTCOME_UNKNOWN, operation="create",
                      request_id=1, elapsed_seconds=1.0, child_exit_code=None,
                      child_alive=True, stdout_eof=False, stderr_eof=False,
                      wrong_response_ids=[], diag_stages=["create.save_begin"],
                      stderr_tail=["[sidecar] stage=create.save_begin"],
                      underlying_class=driver.ERR_REQUEST_TIMEOUT)
    os.environ["JARVIS_CONTACTS_SPIKE_RESULTS_DIR"] = str(tmp / "results")
    try:
        phase_b.halt_outcome_unknown("G8-test", err, "authorized")
        check("10-kein-auto-cleanup", False, "kein SystemExit")
    except SystemExit as ex:
        check("10-kein-auto-cleanup", ex.code == phase_b.EXIT_OUTCOME_UNKNOWN,
              f"exit={ex.code} (eigener Exitcode, sofortiger Stopp)")

    # 14) Fehlerdatei enthaelt nur erlaubte technische Werte
    f = tmp / "results" / "phase-b-outcome-unknown.json"
    check("14-fehlerdatei-geschrieben", f.is_file(), str(f.name))
    if f.is_file():
        rec = json.loads(f.read_text())
        allowed = {"status", "gate", "operation", "request_id", "elapsed_seconds",
                   "error_class", "underlying_class", "child_exit_code",
                   "child_alive", "stdout_eof", "stderr_eof", "wrong_response_ids",
                   "diag_stages", "stderr_tail",
                   "authorization_status_before_mutation", "note"}
        check("14b-nur-erlaubte-felder", set(rec) <= allowed,
              f"unerwartet: {set(rec) - allowed or 'keine'}")
        blob = json.dumps(rec)
        check("14c-keine-payload-oder-pii",
              "@" not in blob and "givenName" not in blob and "ZZZ-JarvisTest-" not in blob,
              "keine Kontakt-Payload, keine PII-Marker")
        check("14d-auth-status-erfasst",
              rec.get("authorization_status_before_mutation") == "authorized")

    # 15) Gestufter Payload beginnt minimal
    src = Path(__file__).resolve().parent / "phase_b.py"
    t = src.read_text()
    i = t.index("--- Stufe 1: minimaler create ---")
    j = t.index('mutate(sc, "G8-stufe1-create"', i)
    seg = t[i:j]
    check("15-stufe1-minimal",
          'payload = {"givenName"' in seg and "familyName" in seg
          and "emails" not in seg and "note" not in seg and "birthday" not in seg,
          "Stufe-1-Payload enthaelt nur Namensfelder")
    check("15b-note-zuletzt-und-isoliert",
          t.index('("note", {"note"') > t.index('("emails", {"emails"'),
          "note steht als letzte, isolierte Feldgruppe in Stufe 3")

    shutil_rm(tmp)
    ok = sum(1 for _, c, _ in RESULTS if c)
    print(f"\n--- {ok}/{len(RESULTS)} bestanden")
    return 0 if ok == len(RESULTS) else 1


def shutil_rm(p: Path) -> None:
    import shutil
    shutil.rmtree(p, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
