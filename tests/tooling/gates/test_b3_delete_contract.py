"""Der finale B3-DELETE-Gatevertrag (P3) — OID-Bindung und Pflichtevidenz.

Zwei Befunde aus dem laufenden Block sind hier mechanisch festgehalten:

1. Ein **erfundener** Commit-OID hätte als Integritätsbindung durchgehen
   können (2026-08-10). Neue B3-Evidenzartefakte binden deshalb nur noch
   vollständige, existierende Commit-Objekte.
2. Ein rein feststellender Korrekturvermerk ist wirkungslos, solange der
   effektive Resolver ihn nicht konsumiert. Der Live-Check liest ihn jetzt
   und lässt `platform-live` nicht mehr grün werden, solange der Vertrag
   ungültig ist oder die strukturierte Pflichtevidenz fehlt.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from tools.gates.runners import b3_checks

REPO_ROOT = Path(__file__).resolve().parents[3]


def _git(args):
    return subprocess.run(["git", "-C", str(REPO_ROOT), *args],
                          capture_output=True, text=True, check=False)


class TestOidBindung:
    """R18: keine Kurz-OID, kein Vervollständigen, kein Raten."""

    def test_echter_commit_wird_akzeptiert(self):
        head = _git(["rev-parse", "HEAD"]).stdout.strip()
        assert len(head) == 40
        assert b3_checks._commit_exists(head) is True

    def test_plausible_nicht_existierende_oid_faellt(self):
        # Wohlgeformt, 40 Hex, existiert nicht — genau der Befund.
        assert b3_checks._commit_exists("0" * 40) is False
        assert b3_checks._commit_exists("742709f" + "c" * 33) is False

    def test_existierendes_nicht_commit_objekt_faellt(self):
        # Ein Blob ist ein gültiges Objekt, aber kein Commit.
        blob = _git(["hash-object", "-w", "--stdin"])
        oid = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "hash-object", "-w", "--stdin"],
            input="b3-oid-negativtest\n", capture_output=True, text=True,
            check=False).stdout.strip()
        assert len(oid) == 40, blob.stderr
        assert b3_checks._commit_exists(oid) is False

    def test_kurz_oid_und_unfug_fallen(self):
        for wert in ("742709f", "", None, 42, "Z" * 40, "742709FC" + "1" * 32):
            assert b3_checks._commit_exists(wert) is False


class TestPflichtevidenz:
    """Der Live-Check erzwingt die strukturierten Bedingungen — Freitext
    ersetzt keine davon."""

    def test_alle_vertragsbedingungen_sind_deklariert(self):
        erwartet = {
            "pre_preview_control_read_success", "pre_preview_control_present",
            "pre_preview_control_identity_bound",
            "fingerprint_matched", "eligibility_digest_matched",
            "origin_continuity_proven", "restorability_proven",
            "pre_execute_control_read_success", "pre_execute_control_present",
            "pre_execute_control_identity_matched",
            "pre_execute_control_calendar_matched",
            "post_delete_read_operation_success",
            "post_delete_expected_calendar_read",
            "post_delete_target_absent", "post_delete_control_present",
            "post_delete_control_identity_matched",
        }
        assert set(b3_checks.DELETE_REQUIRED_EVIDENCE) == erwartet

    def test_der_korrekturvermerk_wird_wirklich_konsumiert(self):
        """Nicht die Datei allein zählt, sondern dass ein normaler Lauf sie
        liest: der aktuelle Zustand muss deshalb NICHT-pass sein."""
        pfad = REPO_ROOT / b3_checks.SUPERSESSION
        assert pfad.is_file(), "Korrekturvermerk fehlt"
        korrektur = json.loads(pfad.read_text(encoding="utf-8"))
        assert korrektur["platform_live"]["pl_b3_live_contract_valid"] is False
        # Der historische Record bleibt unangetastet grün gemeldet …
        assert korrektur["platform_live"]["pl_b3_live_original"] == "pass"
        # … und der effektive Lauf ist es nicht mehr.
        ergebnis = subprocess.run(
            [str(REPO_ROOT / ".venv" / "bin" / "python"),
             str(REPO_ROOT / "tools" / "gates" / "runners" / "b3_checks.py"),
             "--mode", "live"],
            capture_output=True, text=True, cwd=str(REPO_ROOT), check=False)
        assert json.loads(ergebnis.stdout)["outcome"] != "passed"

    def test_die_korrektur_bindet_einen_echten_commit(self):
        korrektur = json.loads(
            (REPO_ROOT / b3_checks.SUPERSESSION).read_text(encoding="utf-8"))
        assert b3_checks._commit_exists(korrektur["corrects"]["commit"])

    def test_historischer_record_bleibt_unveraendert_gefuehrt(self):
        """Nichts wird gelöscht oder gefälscht: der Live-Record trägt die
        drei Stufen weiterhin als ausgeführt und succeeded."""
        record = json.loads(
            (REPO_ROOT / b3_checks.LIVE_RECORD).read_text(encoding="utf-8"))
        stufen = {s["stage"]: s for s in record["stages"]}
        assert set(stufen) == {"create", "update", "delete"}
        for stufe in stufen.values():
            assert stufe["executed"] is True
            assert stufe["outcome"] == "succeeded"
        assert stufen["delete"]["readback_status"] == "absent_confirmed"
