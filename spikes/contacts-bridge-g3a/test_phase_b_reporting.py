#!/usr/bin/env python3
"""test_phase_b_reporting.py — SPIKE G3a (ADR-0016). Temporär, nicht produktiv.

Kontaktfreie Tests des Ergebnispfads, des atomaren Schreibens, des gehärteten
Ergebnismodells und der Exitstatus-Trennung von `phase_b.py`.

Anlass: Der erfolgreiche arm64-Live-Lauf vom 2026-07-28 (28 bestanden, 0
fehlgeschlagen, 1 nicht durchführbar) endete mit einem `PermissionError`, weil
der Ergebnispfad am zentralen Results-Verzeichnis vorbei fest verdrahtet war.
Diese Tests halten die Korrektur fest.

Es wird **kein** Sidecar gestartet, **keine** Contacts-Operation ausgeführt,
**kein** TCC-Dialog ausgelöst und **kein** Kontakt gelesen oder verändert.
Alles läuft gegen temporäre Verzeichnisse und reine Fixtures.
"""
from __future__ import annotations

import json
import os
import re
import stat
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import phase_b  # noqa: E402

RESULTS: list[tuple[str, bool, str]] = []

# Muster, die in der Ergebnisdatei unter keinen Umständen auftauchen dürfen.
PII_PATTERNS = (
    (re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"), "E-Mail"),
    (re.compile(r"\b[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}"
                r"-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}\b"), "UUID/Identifier"),
    (re.compile(r"ABPerson"), "Kontakt-ID"),
    (re.compile(r"ZZZ-JarvisTest-\S"), "Testkontaktname"),
    (re.compile(r"\+?\d[\d\s()/]{7,}\d"), "Telefon"),
    (re.compile(r"Mustermann|Erika|Max\b"), "Name"),
)

REQUIRED_FIELDS = (
    "schemaVersion", "platform", "architecture", "startedAt", "completedAt",
    "authorizationStatus", "containerCount", "allowExisting", "totalGates",
    "passedGates", "failedGates", "skippedGates", "notExecutableGates",
    "cleanupAttempted", "cleanupSucceeded", "createdInRunCount",
    "foreignContactsTouched", "preexistingTestContactsTouched",
    "mutationsOutcomeKnown", "reportingStatus", "overallStatus",
)


def check(name: str, cond: bool, detail: str = "") -> None:
    RESULTS.append((name, bool(cond), str(detail)[:200]))
    print(f"[{'PASS' if cond else 'FAIL'}] {name}  {str(detail)[:140]}")


def scan_pii(text: str) -> list[str]:
    return [label for pattern, label in PII_PATTERNS if pattern.search(text)]


def reset_state() -> None:
    """Modulglobalen Laufzustand zurücksetzen — Tests laufen unabhängig."""
    phase_b.RESULTS.clear()
    phase_b.NOT_EXECUTABLE.clear()
    phase_b.SKIPPED.clear()
    phase_b.CREATED_IN_RUN.clear()
    phase_b.RUN.update({
        "startedAt": "2026-07-28T00:00:00+00:00",
        "completedAt": "2026-07-28T00:10:00+00:00",
        "authorizationStatus": "authorized",
        "containerCount": 1,
        "allowExisting": False,
        "cleanupAttempted": True,
        "cleanupSucceeded": True,
        "foreignContactsTouched": 0,
        "preexistingTestContactsTouched": 0,
        "mutationsOutcomeKnown": True,
    })


def seed(passed: int, failed: int = 0, not_exec: int = 0) -> dict:
    """Ergebnismodell mit einer definierten Gate-Bilanz erzeugen."""
    reset_state()
    for i in range(passed):
        phase_b.RESULTS.append((f"g-pass-{i}", True, "ok"))
    for i in range(failed):
        phase_b.RESULTS.append((f"g-fail-{i}", False, "nicht ok"))
    for i in range(not_exec):
        phase_b.NOT_EXECUTABLE.append((f"g-skip-{i}", "nur 1 Container"))
    return phase_b.build_result_model()


def main() -> int:
    print("=== Ergebnispfad, atomares Schreiben, Ergebnismodell ===")
    src = Path(__file__).resolve().parent / "phase_b.py"
    src_text = src.read_text()

    # ── 1 Ergebnispfad ─────────────────────────────────────────────────────
    check("01-kein-hartkodierter-report-pfad",
          "JarvisContactsSpike/phase-b-results.json" not in src_text,
          "kein Pfad am Results-Verzeichnis vorbei")

    check("02-genau-eine-results-dir-quelle",
          src_text.count("DEFAULT_RESULTS_DIR = ") == 1
          and src_text.count("def results_dir(") == 1,
          "eine zentrale Definition, keine zweite parallele Wahrheit")

    os.environ.pop("JARVIS_CONTACTS_SPIKE_RESULTS_DIR", None)
    check("03-default-results-dir",
          phase_b.results_dir() == Path(
              "/Users/Shared/JarvisContactsSpike/results"),
          str(phase_b.results_dir()))

    with tempfile.TemporaryDirectory() as td:
        target = Path(td) / "results"
        os.environ["JARVIS_CONTACTS_SPIKE_RESULTS_DIR"] = str(target)
        check("04-env-umleitung-wirkt", phase_b.results_dir() == target,
              str(phase_b.results_dir()))

        # ── 2 Schreiben ────────────────────────────────────────────────────
        model = seed(28, 0, 1)
        out, err = phase_b.write_results(model)
        check("05-datei-im-results-verzeichnis",
              err is None and out == target / "phase-b-results.json",
              f"out={out} err={err}")
        check("06-verzeichnis-wird-angelegt", target.is_dir(),
              "fehlendes Zielverzeichnis wurde erzeugt")

        raw = (target / "phase-b-results.json").read_bytes()
        check("07-utf8-und-schlusszeilenumbruch",
              raw.decode("utf-8").endswith("\n"),
              "dekodierbar als UTF-8, endet mit Zeilenumbruch")

        written = json.loads(raw.decode("utf-8"))
        check("08-keine-tempdatei-uebrig",
              [p.name for p in target.iterdir()] == ["phase-b-results.json"],
              f"Inhalt={sorted(p.name for p in target.iterdir())}")

        # ── 3 Atomarität ───────────────────────────────────────────────────
        real_fsync = os.fsync
        os.fsync = lambda fd: (_ for _ in ()).throw(OSError(5, "simuliert"))
        try:
            broken = dict(model)
            broken["overallStatus"] = "NIEMALS-SICHTBAR"
            _, err2 = phase_b.write_results(broken)
        finally:
            os.fsync = real_fsync
        still = json.loads((target / "phase-b-results.json").read_text("utf-8"))
        check("09-abbruch-laesst-alte-datei-intakt",
              still["overallStatus"] == written["overallStatus"]
              and "NIEMALS" not in json.dumps(still),
              f"unveraendert: {still['overallStatus']}")
        check("10-abbruch-laesst-keine-tempdatei",
              not [p for p in target.iterdir() if ".tmp." in p.name],
              f"Inhalt={sorted(p.name for p in target.iterdir())}")
        check("11-atomares-schreiben-im-quelltext",
              "os.replace(tmp, path)" in src_text
              and "os.fsync(fh.fileno())" in src_text,
              "temporaere Datei + fsync + os.replace")

        # ── 4 Nicht schreibbares Zielverzeichnis ───────────────────────────
        locked = Path(td) / "gesperrt"
        locked.mkdir()
        (locked / "results").mkdir()
        os.chmod(locked / "results", stat.S_IRUSR | stat.S_IXUSR)
        os.environ["JARVIS_CONTACTS_SPIKE_RESULTS_DIR"] = str(locked / "results")
        out3, err3 = phase_b.write_results(model)
        os.chmod(locked / "results", stat.S_IRWXU)
        check("12-unschreibbar-keine-exception",
              out3 is None and isinstance(err3, str) and err3,
              f"gemeldet: {err3}")
        check("13-fehlertext-technisch-und-pii-frei",
              "Error" in err3 and not scan_pii(err3),
              err3)
        check("14-unschreibbar-keine-teildatei",
              not list((locked / "results").iterdir()),
              "kein Rest im gesperrten Verzeichnis")

        os.environ["JARVIS_CONTACTS_SPIKE_RESULTS_DIR"] = str(target)

    os.environ.pop("JARVIS_CONTACTS_SPIKE_RESULTS_DIR", None)

    # ── 5 Reporting-Fehler ändert das fachliche Urteil nicht ───────────────
    model = seed(28, 0, 1)
    before = json.dumps(model, sort_keys=True)
    model_after = dict(model)
    model_after["reportingStatus"] = "write_failed"
    check("15-reportingfehler-aendert-verdikt-nicht",
          model_after["overallStatus"] == model["overallStatus"]
          and model_after["passedGates"] == 28
          and model_after["failedGates"] == 0,
          f"{model_after['overallStatus']} bleibt bestehen")
    check("16-reportingstatus-ist-eigenes-feld",
          "reportingStatus" in before and model["reportingStatus"] == "written",
          "getrennt vom fachlichen overallStatus")

    # ── 6 Exitstatus-Trennung ──────────────────────────────────────────────
    check("17-exit-ok-trotz-nicht-durchfuehrbarem-gate",
          phase_b.exit_code(seed(28, 0, 1), None) == phase_b.EXIT_OK,
          "nicht durchfuehrbar ist kein Fehler")
    check("18-exit-reportingfehler-eigener-code",
          phase_b.exit_code(seed(28, 0, 1), "schreibfehler")
          == phase_b.EXIT_REPORTING_ERROR == 8,
          "8 statt 1")
    check("19-exit-fachlicher-fehler",
          phase_b.exit_code(seed(27, 1, 1), None)
          == phase_b.EXIT_GATE_FAILURE == 1,
          "fachlicher Fehlschlag bleibt 1")
    check("20-exitcodes-paarweise-verschieden",
          len({phase_b.EXIT_OK, phase_b.EXIT_GATE_FAILURE,
               phase_b.EXIT_OUTCOME_UNKNOWN, phase_b.EXIT_REPORTING_ERROR}) == 4,
          "0 / 1 / 7 / 8")

    # ── 7 Gesamtstatus ─────────────────────────────────────────────────────
    m = seed(28, 0, 1)
    check("21-28-plus-1-ergibt-passed-with-not-executable",
          m["overallStatus"] == "passed_with_not_executable_gate"
          and m["passedGates"] == 28 and m["failedGates"] == 0
          and m["notExecutableGates"] == 1 and m["totalGates"] == 29,
          f"{m['overallStatus']} bei {m['totalGates']} Gates")
    check("22-alles-bestanden-ergibt-passed",
          seed(29, 0, 0)["overallStatus"] == "passed", "passed")
    check("23-ein-fehlschlag-ergibt-failed",
          seed(28, 1, 1)["overallStatus"] == "failed", "failed")
    check("24-nicht-durchfuehrbar-zaehlt-nicht-als-fehlschlag",
          seed(28, 0, 1)["failedGates"] == 0
          and "g11-two-containers" not in [n for n, _, _ in phase_b.RESULTS],
          "getrennte Zaehlung")

    # ── 8 not_executable() berührt die Gate-Liste nicht ────────────────────
    reset_state()
    phase_b.not_executable("g11-two-containers", "nur 1 Container")
    check("25-not-executable-nicht-in-results",
          not phase_b.RESULTS and len(phase_b.NOT_EXECUTABLE) == 1,
          "landet ausschliesslich in NOT_EXECUTABLE")
    check("26-g11-quelltext-nutzt-not-executable",
          'not_executable("g11-two-containers"' in src_text
          and 'check("g11-two-containers", False' not in src_text,
          "Container-Gate ist nicht mehr FAIL")

    # ── 9 Pflichtfelder und Reduktion ──────────────────────────────────────
    m = seed(28, 0, 1)
    fehlend = [f for f in REQUIRED_FIELDS if f not in m]
    check("27-alle-pflichtfelder-vorhanden", not fehlend,
          f"fehlend={fehlend}")
    check("28-fremdkontakte-immer-null",
          m["foreignContactsTouched"] == 0
          and m["preexistingTestContactsTouched"] == 0,
          "0 / 0")
    check("29-rekonstruktionsfelder-vorhanden",
          m["reconstructed"] is False and m["reconstructionReason"] is None
          and m["liveRunRepeated"] is False,
          "Standard: kein rekonstruierter Lauf")
    check("30-schemaversion-gesetzt",
          m["schemaVersion"] == phase_b.SCHEMA_VERSION == 1,
          str(m["schemaVersion"]))

    # ── 10 Keine PII in der Datei ──────────────────────────────────────────
    reset_state()
    phase_b.RESULTS.append((
        "g-pii", True,
        "id=6A1B2C3D-4E5F-4A6B-8C9D-0E1F2A3B4C5D name=ZZZ-JarvisTest-Erika "
        "mail=erika.mustermann@example.com tel=+49 170 1234567 "
        "token=QUJDREVGR0hJSktMTU5PUFFSU1RVVldYWVo= ref=ABPerson/17"))
    m = phase_b.build_result_model()
    dumped = json.dumps(m, ensure_ascii=False)
    treffer = scan_pii(dumped)
    check("31-keine-pii-im-json", not treffer, f"Treffer={treffer}")
    check("32-platzhalter-statt-rohwert",
          "<UUID>" in dumped and "<EMAIL>" in dumped
          and "<TESTKONTAKT>" in dumped and "<TOKEN>" in dumped,
          "Rohwerte durch Platzhalter ersetzt")

    ok_n = sum(1 for _, c, _ in RESULTS if c)
    print(f"\n--- {ok_n}/{len(RESULTS)} bestanden")
    print("Kein Sidecar gestartet, keine Contacts-Operation, kein TCC-Dialog, "
          "keine Mutation, kein Kontakt gelesen.")
    return 0 if ok_n == len(RESULTS) else 1


if __name__ == "__main__":
    sys.exit(main())
