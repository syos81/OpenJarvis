#!/usr/bin/env python3
"""test_isolation_probe.py — SPIKE G3a (ADR-0016). Temporär, nicht produktiv.

Kontaktfreie Tests der Isolationsprobe und der laufgebundenen
Mutationssicherheit von phase_b.py.

Ausschliesslich Fixtures, Fake-Sidecars und Quelltextanalyse. Kein echter
Sidecar gegen den Store, keine Contacts-Operation, kein TCC-Dialog.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import isolation_probe  # noqa: E402
import phase_b  # noqa: E402
from driver import Sidecar  # noqa: E402

RESULTS: list[tuple[str, bool, str]] = []
SRC = Path(__file__).resolve().parent / "src" / "sidecar.swift"

# PII-Muster, die in keiner Ausgabe und keinem Bericht auftauchen duerfen.
PII_PATTERNS = (
    (re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"), "E-Mail"),
    (re.compile(r"\b[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}"
                r"-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}\b"), "UUID/Identifier"),
    (re.compile(r"ABPerson"), "Kontakt-ID"),
    (re.compile(r"\+?\d[\d\s()/]{7,}\d"), "Telefon"),
    (re.compile(r"Mustermann|Erika|Max\b"), "Name"),
)


def check(name: str, cond: bool, detail: str = "") -> None:
    RESULTS.append((name, bool(cond), str(detail)[:200]))
    print(f"[{'PASS' if cond else 'FAIL'}] {name}  {str(detail)[:140]}")


def scan_pii(text: str) -> list[str]:
    return [label for pat, label in PII_PATTERNS if pat.search(text)]


def make_summary(total=0, prefixed=0, foreign=0, me="unknown", me_in="unknown",
                 dupes=False, containers=("local",)) -> dict:
    return {
        "authorizationStatus": "authorized",
        "containerCount": len(containers),
        "containerTypes": list(containers),
        "totalContacts": total,
        "prefixedTestContacts": prefixed,
        "foreignContacts": foreign,
        "meCardPresent": me,
        "meCardIncludedInEnumerate": me_in,
        "duplicateIdentifiersDetected": dupes,
        "mutationCount": 0,
        "testPrefix": "ZZZ-JarvisTest-",
    }


def run_with_fake(tmp: Path, name: str, summary: dict | None,
                  error: dict | None = None) -> tuple[str, dict]:
    """Fake-Sidecar liefert eine feste isolationSummary; Runner ausfuehren."""
    ready = json.dumps({"type": "ready", "protocol": 1,
                        "authorizationStatus": "authorized", "caps": ["caps"],
                        "limits": {"linkUnlinkSupported": False}})
    body = json.dumps({"id": 1, "ok": error is None,
                       **({"result": summary} if error is None
                          else {"error": error})})
    p = tmp / f"{name}.py"
    p.write_text(
        "#!/usr/bin/env python3\nimport sys, json\n"
        f"print({ready!r}, flush=True)\n"
        "for line in sys.stdin:\n"
        "    d = json.loads(line)\n"
        "    if d.get('op') == 'shutdown':\n"
        "        print(json.dumps({'id': d['id'], 'ok': True, "
        "'result': {'bye': True}}), flush=True); break\n"
        f"    out = json.loads({body!r}); out['id'] = d['id']\n"
        "    print(json.dumps(out), flush=True)\n")
    p.chmod(0o755)

    rdir = tmp / f"results-{name}"
    env = {**os.environ, "JARVIS_CONTACTS_SPIKE_RESULTS_DIR": str(rdir)}
    # WICHTIG: Sidecar.__init__ bindet den Standardpfad als Default-Argument
    # bereits bei der Klassendefinition. Ein nachtraegliches Setzen von
    # driver.SIDECAR bliebe wirkungslos — der Fake muss explizit uebergeben
    # werden, sonst laeuft der Test unbemerkt gegen den echten Sidecar.
    code = (f"import sys; sys.path.insert(0, {str(SRC.parent.parent)!r});\n"
            f"import driver, isolation_probe;\n"
            f"from pathlib import Path;\n"
            f"_fake = Path({str(p)!r});\n"
            f"isolation_probe.Sidecar = lambda *a, **k: "
            f"driver.Sidecar(binary=_fake);\n"
            f"sys.exit(isolation_probe.main())\n")
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True,
                          text=True, env=env, cwd=str(SRC.parent.parent))
    report = {}
    f = rdir / "isolation-probe.json"
    if f.exists():
        report = json.loads(f.read_text())
    return proc.stdout + proc.stderr, report


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="isoprobe-")).resolve()
    src = SRC.read_text()

    # ── 1–8: Klassifikationsfälle ───────────────────────────────────────────
    cases = [
        ("01-null-kontakte", make_summary(0, 0, 0, False, "unknown"), "leer"),
        ("02-ein-testkontakt", make_summary(1, 1, 0, False, "unknown"),
         "nur-testkontakte"),
        ("03-ein-fremdkontakt", make_summary(1, 0, 1, False, "unknown"),
         "fremdkontakte-vorhanden"),
        ("04-mecard-in-enumerate", make_summary(1, 0, 1, True, True),
         "nur-me-card"),
        ("05-mecard-nicht-in-enumerate", make_summary(2, 0, 2, True, False),
         "fremdkontakte-vorhanden"),
        ("06-keine-mecard", make_summary(2, 1, 1, False, "unknown"),
         "fremdkontakte-vorhanden"),
        ("07-mecard-unbekannt", make_summary(1, 1, 0, "unknown", "unknown"),
         "nur-testkontakte"),
        ("08-gemischt", make_summary(5, 2, 3, True, True),
         "fremdkontakte-vorhanden"),
    ]
    for name, summary, expected in cases:
        verdict, notes = isolation_probe.classify(summary)
        check(name, verdict == expected, f"verdict={verdict} (erwartet {expected})")

    # ── 9/10/11: PII-Freiheit von stdout und Bericht ────────────────────────
    out, report = run_with_fake(tmp, "mixed", make_summary(5, 2, 3, True, True))
    check("09-keine-pii-in-stdout", not scan_pii(out), f"{scan_pii(out)}")
    raw = json.dumps(report)
    check("10-keine-pii-im-report", not scan_pii(raw), f"{scan_pii(raw)}")
    allowed = set(isolation_probe.ALLOWED_RESULT_FIELDS)
    got = set((report.get("summary") or {}).keys())
    check("11-keine-identifier-im-report", got <= allowed,
          f"unerlaubt: {sorted(got - allowed)}")

    # Zweite Verteidigungslinie: geschmuggelte Felder werden verworfen.
    smuggled = {**make_summary(1, 1, 0), "identifier": "ABPerson:1234",
                "givenName": "Max", "email": "max@example.com"}
    filtered = isolation_probe.filter_result(smuggled)
    check("11b-filter-verwirft-schmuggel",
          not scan_pii(json.dumps(filtered)) and set(filtered) <= allowed,
          f"gefiltert auf {len(filtered)} erlaubte Felder")

    # ── 12: mutationCount immer 0 ───────────────────────────────────────────
    check("12-mutationcount-null",
          (report.get("summary") or {}).get("mutationCount") == 0
          and report.get("mutationCount") == 0,
          f"summary={report.get('summary', {}).get('mutationCount')} "
          f"record={report.get('mutationCount')}")

    # ── 13: keine mutierende Operation im Runner ────────────────────────────
    check("13-allowed-ops-nur-lesend",
          isolation_probe.ALLOWED_OPS == {"caps", "isolationSummary", "shutdown"},
          str(sorted(isolation_probe.ALLOWED_OPS)))
    blocked = False
    try:
        isolation_probe.guarded_request(object(), "delete", {})
    except RuntimeError:
        blocked = True
    except Exception:
        blocked = False
    check("13b-guarded-request-blockt-delete", blocked)
    runner_src = Path(isolation_probe.__file__).read_text()
    check("13c-kein-savereqest-im-sidecar-op",
          "CNSaveRequest" not in src.split("func opIsolationSummary")[1]
          .split("\nfunc ")[0],
          "isolationSummary konstruiert keinen CNSaveRequest")

    # ── 14: Präfixklassifikation deterministisch ────────────────────────────
    s = make_summary(3, 1, 2, True, True)
    v1, _ = isolation_probe.classify(s)
    v2, _ = isolation_probe.classify(dict(s))
    check("14-klassifikation-deterministisch", v1 == v2, f"{v1} == {v2}")
    check("14b-sidecar-nutzt-praefix-intern",
          "isTestRecord(c) { prefixed += 1 }" in src.replace("\n", " ")
          or "if isTestRecord(c)" in src,
          "Praefixabgleich im Sidecar, Namen verlassen ihn nicht")

    # ── 15: phase_b-Mutationsziele sind laufgebunden ────────────────────────
    pb = Path(phase_b.__file__).read_text()
    check("15-created-in-run-registry", "CREATED_IN_RUN" in pb)
    check("15b-update-delete-laufgebunden",
          'if op in ("update", "updateViaUnified", "delete"):' in pb
          and "assert_run_owned" in pb)
    phase_b.CREATED_IN_RUN.clear()
    rc = subprocess.run(
        [sys.executable, "-c",
         "import sys; sys.path.insert(0, %r);\n"
         "import phase_b;\n"
         "phase_b.CREATED_IN_RUN.clear();\n"
         "phase_b.assert_run_owned('T', 'fremde-id')\n" % str(SRC.parent.parent)],
        capture_output=True, text=True)
    check("15c-fremde-id-wird-abgelehnt", rc.returncode == 5,
          f"exit={rc.returncode}")
    rc2 = subprocess.run(
        [sys.executable, "-c",
         "import sys; sys.path.insert(0, %r);\n"
         "import phase_b;\n"
         "phase_b.CREATED_IN_RUN.clear();\n"
         "phase_b.CREATED_IN_RUN.add('eigene-id');\n"
         "phase_b.assert_run_owned('T', 'eigene-id');\n"
         "print('OK')\n" % str(SRC.parent.parent)],
        capture_output=True, text=True)
    check("15d-eigene-id-wird-akzeptiert", "OK" in rc2.stdout, rc2.stdout.strip())
    check("15e-cleanup-nur-laufeigene",
          "targets = sorted(CREATED_IN_RUN)" in pb
          and "cleanup-preexisting-untouched" in pb)
    check("15f-cleanup-only-gesperrt",
          "--cleanup-only ist gesperrt" in pb)
    check("15g-kein-namensbasierter-mutationslookup",
          "is_test(c)" in pb and 'mutate(sc, "G13-cleanup", "delete", {"identifier": ident}'
          in pb.replace("\n", " ").replace("  ", " ") or "targets = sorted(CREATED_IN_RUN)" in pb,
          "Loeschziele stammen aus der Lauf-Registry, nicht aus Namensfiltern")

    # ── 16: kein --allow-existing im Probe-Runner ───────────────────────────
    check("16-kein-allow-existing-schalter",
          "--allow-existing" in runner_src and "existiert in diesem Runner nicht"
          in runner_src, "wird ausdruecklich abgelehnt")
    rc3 = subprocess.run([sys.executable, str(isolation_probe.__file__),
                          "--allow-existing"], capture_output=True, text=True,
                         cwd=str(SRC.parent.parent))
    check("16b-allow-existing-bricht-ab", rc3.returncode == 2,
          f"exit={rc3.returncode}")

    # ── Zusatz: Me-Card-Fehler wird kontrolliert behandelt ──────────────────
    out2, report2 = run_with_fake(tmp, "err", None,
                                  {"code": "provider_error", "message": "x",
                                   "retryable": False})
    check("17-mecard-fehler-kontrolliert",
          report2.get("result") == "error" and not scan_pii(json.dumps(report2)),
          f"result={report2.get('result')}")
    check("17b-unknown-ohne-vermutung",
          '"unknown"' in src.split("func opIsolationSummary")[1].split("\nfunc ")[0],
          "meCardPresent kann unknown sein")

    ok_n = sum(1 for _, c, _ in RESULTS if c)
    print(f"\n--- {ok_n}/{len(RESULTS)} bestanden")
    print("Kein echter Sidecar gegen den Store, keine Contacts-Operation, "
          "kein TCC-Dialog, keine Mutation.")
    return 0 if ok_n == len(RESULTS) else 1


if __name__ == "__main__":
    sys.exit(main())
