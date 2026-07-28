#!/usr/bin/env python3
"""reconstruct_results.py — SPIKE G3a (ADR-0016). Temporär, nicht produktiv.

Schreibt die Ergebnisdatei des arm64-Live-Laufs vom 2026-07-28 **administrativ**
nach, weil der Lauf selbst fachlich vollständig war, das Schreiben aber an einem
fest verdrahteten Pfad außerhalb des Results-Verzeichnisses scheiterte
(`PermissionError`).

Ausdrücklich:
  * **Kein** Kontakt wird gelesen, angelegt, geändert oder gelöscht.
  * **Kein** Sidecar wird gestartet, **kein** `requestAuthorization` gesendet.
  * Der Live-Lauf wird **nicht** wiederholt (`liveRunRepeated: false`).

Jeder Wert trägt in `provenance` seine Herkunft. Was nicht belegbar ist — allen
voran die Zeitstempel —, steht als `null` und wird nicht geschätzt.

    python3 reconstruct_results.py [--dry-run]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import phase_b  # noqa: E402

# Belegte Bilanz des Laufs (Konsolenausgabe des Testbenutzers `jarvisspike`).
PASSED = 28
FAILED = 0
NOT_EXECUTABLE_GATE = (
    "g11-two-containers",
    "nur 1 Container im Testkonto; der Mehrcontainer-Test braucht mindestens "
    "zwei — in dieser Umgebung nicht durchfuehrbar, kein Funktionsfehler",
)

PROVENANCE = {
    "startedAt": "nicht belegbar — Konsolenausgabe enthielt keinen Zeitstempel",
    "completedAt": "nicht belegbar — Konsolenausgabe enthielt keinen Zeitstempel",
    "authorizationStatus": "belegt — der Lauf startet sonst mit Exit 4/5",
    "containerCount": "belegt — results/isolation-probe.json: containerCount=1",
    "allowExisting": "belegt — Aufruf ohne --allow-existing",
    "passedGates": "belegt — Konsolenausgabe des Laufs",
    "failedGates": "belegt — Konsolenausgabe des Laufs",
    "notExecutableGates": "belegt — einziges nicht durchfuehrbares Gate: G11",
    "cleanupAttempted": "belegt — G13 lief bis zur Zusammenfassung",
    "cleanupSucceeded": "belegt — laufeigene Reste=0, fehlgeschlagen=0",
    "createdInRunCount": ("abgeleitet aus dem ausgefuehrten Pfad in phase_b.py: "
                          "G8-stufe1-create und G10-create; die beiden "
                          "G11-Creates wurden nie erreicht"),
    "foreignContactsTouched": ("belegt — die Sidecar-Rail laesst nur "
                               "Datensaetze mit dem Testpraefix zu; die "
                               "Me-Karte blieb unveraendert"),
    "preexistingTestContactsTouched": ("belegt — Mutationen nur an "
                                       "CREATED_IN_RUN"),
    "mutationsOutcomeKnown": "belegt — kein outcome_unknown-Abbruch",
    "gates": ("nicht rekonstruierbar — die Einzelheiten gingen mit der "
              "fehlgeschlagenen Schreiboperation verloren und werden NICHT "
              "erfunden"),
}


def build() -> dict:
    return {
        "schemaVersion": phase_b.SCHEMA_VERSION,
        "platform": "Darwin",
        "architecture": "arm64",
        "startedAt": None,
        "completedAt": None,
        "authorizationStatus": "authorized",
        "containerCount": 1,
        "allowExisting": False,
        "totalGates": PASSED + FAILED + 1,
        "passedGates": PASSED,
        "failedGates": FAILED,
        "skippedGates": 0,
        "notExecutableGates": 1,
        "cleanupAttempted": True,
        "cleanupSucceeded": True,
        "createdInRunCount": 2,
        "foreignContactsTouched": 0,
        "preexistingTestContactsTouched": 0,
        "mutationsOutcomeKnown": True,
        "reportingStatus": "reconstructed_after_path_error",
        "overallStatus": "passed_with_not_executable_gate",
        "reconstructed": True,
        "reconstructionReason": "final-report-path-permission-error",
        "liveRunRepeated": False,
        "gates": [],
        "gateDetailsAvailable": False,
        "notExecutable": [{"name": NOT_EXECUTABLE_GATE[0],
                           "reason": NOT_EXECUTABLE_GATE[1]}],
        "skipped": [],
        "provenance": PROVENANCE,
        "notes": [
            "Der Lauf war fachlich vollstaendig; ausschliesslich das Schreiben "
            "der Ergebnisdatei schlug fehl (fest verdrahteter Pfad im "
            "Paketwurzelverzeichnis, fuer den Testbenutzer nicht beschreibbar).",
            "Diese Datei wurde ohne jeden Kontaktzugriff erzeugt: kein Lesen, "
            "kein Anlegen, kein Aendern, kein Loeschen, kein Sidecar-Start.",
            "Eine manuell in Kontakte.app ausgeloeste Aenderung wurde ueber die "
            "Change History erkannt (LIVE-DELTA-1) — Beleg dafuer, dass externe "
            "Mutationen im Delta ankommen.",
            "Die Me-Karte des Testbenutzers blieb unveraendert.",
        ],
    }


def main() -> int:
    model = build()
    if "--dry-run" in sys.argv:
        print(json.dumps(model, indent=2, ensure_ascii=False))
        return 0
    out = phase_b.results_dir() / "phase-b-results.json"
    if out.exists():
        print(f"ABBRUCH: {out} existiert bereits und wird nicht ueberschrieben.",
              file=sys.stderr)
        return 1
    phase_b.atomic_write_json(out, model)
    print(f"Rekonstruiert: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
