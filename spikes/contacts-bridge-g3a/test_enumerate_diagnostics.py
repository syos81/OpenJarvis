#!/usr/bin/env python3
"""test_enumerate_diagnostics.py — SPIKE G3a (ADR-0016). Temporär, nicht produktiv.

Kontaktfreie Tests der Crash-Sanitisierung, der Enumerate-Diagnosestufen und
der gestuften Keysets.

Es werden AUSSCHLIESSLICH Fake-Sidecars, Textfixtures und Quelltextanalyse
verwendet. Kein echter Sidecar-Start gegen den Store, keine Contacts-Operation,
kein TCC-Dialog.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import driver  # noqa: E402
import enumerate_probe  # noqa: E402
from driver import DriverError, Sidecar, sanitize_crash_line, signal_name  # noqa: E402

RESULTS: list[tuple[str, bool, str]] = []
SRC = Path(__file__).resolve().parent / "src" / "sidecar.swift"
READY = ('{"type":"ready","protocol":1,"authorizationStatus":"authorized",'
         '"keySetVersion":1,"caps":["ping"],"limits":{"linkUnlinkSupported":false}}')

# Realistische Crashzeilen eines uncaught ObjC-Exception-Abbruchs.
REAL_CRASH = [
    "*** Terminating app due to uncaught exception "
    "'CNContactPropertyNotFetchedException', reason: 'A property was not "
    "requested when contact was fetched.'",
    "*** First throw call stack:",
    "0   CoreFoundation      0x00000001a2b3c4d5 __exceptionPreprocess + 160",
    "1   libobjc.A.dylib     0x00000001a1234567 objc_exception_throw + 60",
    "2   Contacts            0x00000001b0001234 -[CNContact "
    "_valueForProperty:] + 220",
    "3   jarvis-contacts     0x0000000100003abc $s4main3dtoySDySSypGSo9CNContactCF + 88",
    "libc++abi: terminating with uncaught exception of type NSException",
    "Abort trap: 6",
]
PII_LINES = [
    "Kontakt: Max Mustermann <max.mustermann@example.com> +49 151 12345678",
    "Datei /Users/jarvisspike/Library/Application Support/AddressBook/x.abcddb",
    "identifier 3F2504E0-4F89-11D3-9A0C-0305E82C3301:ABPerson",
    "ZZZ-JarvisTest-Alpha wurde geladen",
]


def check(name: str, cond: bool, detail: str = "") -> None:
    RESULTS.append((name, bool(cond), str(detail)[:200]))
    print(f"[{'PASS' if cond else 'FAIL'}] {name}  {str(detail)[:140]}")


def fake(tmp: Path, name: str, body: str) -> Path:
    p = tmp / name
    p.write_text("#!/usr/bin/env python3\nimport sys, os, json\n"
                 f"READY = {READY!r}\n" + body)
    p.chmod(0o755)
    return p


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="enumdiag-")).resolve()
    src = SRC.read_text()

    # ── 1) Signalauswertung ──────────────────────────────────────────────────
    check("01-sigabrt-erkannt", signal_name(-6) == "SIGABRT(6)", signal_name(-6))
    check("01b-weitere-signale",
          signal_name(-11) == "SIGSEGV(11)" and signal_name(-9) == "SIGKILL(9)"
          and signal_name(0) is None and signal_name(None) is None)

    # ── 2) Technische Crashinformation bleibt erkennbar ──────────────────────
    cleaned = [sanitize_crash_line(l) for l in REAL_CRASH]
    kept = [c for c in cleaned if c]
    joined = " ".join(kept)
    check("02-exception-klasse-erhalten",
          "CNContactPropertyNotFetchedException" in joined)
    check("02b-signal-erhalten", "Abort trap: 6" in joined)
    check("02c-framework-erhalten",
          "CoreFoundation" in joined and "Contacts" in joined and "libobjc" in joined)
    check("02d-symbol-erhalten",
          "objc_exception_throw" in joined and "_valueForProperty" in joined)
    check("02e-reason-erhalten", "reason:" in joined)
    check("02f-alle-crashzeilen-behalten", len(kept) == len(REAL_CRASH),
          f"{len(kept)}/{len(REAL_CRASH)}")

    # ── 3/4) PII wird entfernt ───────────────────────────────────────────────
    # Technische Zeile mit eingebetteter PII: bleibt erhalten, PII ersetzt.
    mixed = ("libobjc.A.dylib objc_exception_throw bei /Users/jarvisspike/x "
             "fuer max@example.com +49 151 12345678 "
             "3F2504E0-4F89-11D3-9A0C-0305E82C3301 ZZZ-JarvisTest-Alpha")
    m = sanitize_crash_line(mixed) or ""
    check("03-benutzerpfad-entfernt", "/Users/jarvisspike" not in m and "<PFAD>" in m, m[:90])
    check("04a-email-entfernt", "max@example.com" not in m and "<EMAIL>" in m)
    check("04b-telefon-entfernt", "151 12345678" not in m and "<TEL>" in m)
    check("04c-uuid-entfernt", "3F2504E0-4F89" not in m and "<UUID>" in m)
    check("04d-testkontakt-entfernt", "ZZZ-JarvisTest-Alpha" not in m)
    check("04e-technik-bleibt", "objc_exception_throw" in m)
    # Reine PII-Zeilen ohne technischen Marker werden verworfen.
    check("04f-reine-pii-verworfen",
          all(sanitize_crash_line(l) is None for l in PII_LINES[:1] + PII_LINES[2:]),
          "keine Weitergabe")

    # ── 5/6) Grenzen ─────────────────────────────────────────────────────────
    sc = Sidecar.__new__(Sidecar)
    sc.stderr_tail = [f"libobjc frame {i} objc_exception_throw" for i in range(60)]
    out = sc.safe_stderr()
    check("05-max-20-zeilen", len(out) <= 20, f"{len(out)} Zeilen")
    sc.stderr_tail = ["libobjc objc_exception_throw " + "A" * 500]
    out2 = sc.safe_stderr()
    check("06-max-200-zeichen", all(len(l) <= 200 for l in out2),
          f"max={max(len(l) for l in out2)}")
    # Kein Rohdatei-Dump
    check("06b-kein-rohes-stderr-gespeichert",
          "raw_stderr" not in Path(driver.__file__).read_text(),
          "keine Rohdatei")

    # ── 7) Enumerate-Diagnosestufen vollständig und PII-frei ─────────────────
    required = ["enumerate.received", "enumerate.validated", "enumerate.auth_ok",
                "enumerate.container_resolved", "enumerate.keys_begin",
                "enumerate.keys_complete", "enumerate.request_constructed",
                "enumerate.fetch_begin", "enumerate.callback_entered",
                "enumerate.fetch_returned", "enumerate.serialized",
                "enumerate.response_written"]
    missing = [s for s in required if f'"{s}"' not in src]
    check("07-alle-stufen-vorhanden", not missing, f"fehlend: {missing}")
    check("07b-symbolische-key-stufe",
          'stage("enumerate.key.\\(symbolicKeyName(k))")' in src,
          "enumerate.key.<symbolisch>")
    # symbolicKeyName liefert nur konstante Namen — keine Kontaktwerte
    names = re.findall(r'case CNContact\w+Key:\s*return "(\w+)"', src)
    check("07c-key-namen-konstant-und-pii-frei",
          len(names) >= 20 and all(re.fullmatch(r"[A-Za-z]+", n) for n in names),
          f"{len(names)} symbolische Namen")

    # ── 8/9) Minimal-Keyset ──────────────────────────────────────────────────
    stage1 = re.search(r"let kProbeStage1: \[String\] = \[(.*?)\]", src, re.S)
    s1 = stage1.group(1) if stage1 else ""
    check("08-minimal-ohne-note", "CNContactNoteKey" not in s1, s1.strip()[:80])
    check("09-minimal-ohne-bilder-und-sonderfelder",
          not any(k in s1 for k in ("ImageData", "Thumbnail", "Birthday", "Dates",
                                    "Relations", "SocialProfiles",
                                    "InstantMessage")),
          "nur Identifier/Given/Family")
    check("09b-minimal-genau-drei-keys", s1.count("CNContact") == 3,
          f"{s1.count('CNContact')} Keys")

    # ── 10) Key-Gruppen deterministisch ──────────────────────────────────────
    g2 = re.findall(r'\("([a-z-]+)", \[', src[src.index("kProbeStage2"):
                                              src.index("kProbeStage3")])
    g3s = src[src.index("kProbeStage3"):]
    g3 = re.findall(r'\("([a-z-]+)", \[', g3s[:g3s.index("\n]")])
    check("10-gruppen-deterministisch",
          g2 == enumerate_probe.STAGE2_GROUPS and g3 == enumerate_probe.STAGE3_GROUPS,
          f"stage2={g2} stage3={g3}")
    check("10b-note-in-stufe3-isoliert",
          '("note", [CNContactNoteKey])' in src, "eigene Gruppe")

    # ── 11) Kein automatischer Read-Retry nach Child-Abbruch ────────────────
    p = fake(tmp, "die.py", """
print(READY, flush=True)
for line in sys.stdin:
    os._exit(-6 & 0xff)
""")
    starts = {"n": 0}
    orig_start = Sidecar.start

    def counting_start(self, *a, **k):
        starts["n"] += 1
        return orig_start(self, *a, **k)

    Sidecar.start = counting_start
    try:
        rec = enumerate_probe.run_stage("t", {"stage": 1})
    finally:
        Sidecar.start = orig_start
    check("11-kein-auto-retry", starts["n"] == 1,
          f"{starts['n']} Sidecar-Start(s), Ergebnis={rec.get('result')}")

    # ── 12) Probe-Modus kann nicht mutieren ─────────────────────────────────
    for op in ("create", "update", "updateViaUnified", "delete"):
        check(f"12-mutation-gesperrt-{op}",
              op not in enumerate_probe.ALLOWED_OPS)
    blocked = False
    try:
        enumerate_probe.guarded_request(object(), "create", {})
    except RuntimeError:
        blocked = True
    except Exception:
        blocked = False
    check("12b-guarded-request-blockt", blocked, "RuntimeError bei create")
    check("12c-runner-sendet-nur-lesende-ops",
          enumerate_probe.ALLOWED_OPS == {"caps", "enumerateProbe", "shutdown"},
          str(sorted(enumerate_probe.ALLOWED_OPS)))

    # ── 13) Standardmodus unverändert, aber abgesichert ─────────────────────
    check("13-imagedataavailable-key-ergaenzt",
          "CNContactImageDataAvailableKey" in src.split("let fetchKeys")[1]
          .split("].map")[0],
          "in fetchKeys")
    check("13b-dto-nutzt-iskeyavailable",
          "func ifFetched" in src and "isKeyAvailable" in src,
          "ungefetchte Properties koennen nicht mehr abstuerzen")
    check("13c-note-nicht-im-standard-fetch",
          "CNContactNoteKey" not in src.split("let fetchKeys")[1].split("].map")[0],
          "Standard-Fetch ohne note")
    check("13d-notes-capability-gemeldet",
          '"notesSupported": false' in src and "missing-entitlement" in src,
          "notesSupported=false")

    # ── Zusatz: stdout bleibt reines Protokoll ──────────────────────────────
    check("14-stufen-gehen-nach-stderr",
          'func stage(' in src and 'diag("stage=' in src
          and "standardError" in src,
          "stage -> diag -> stderr")

    ok_n = sum(1 for _, c, _ in RESULTS if c)
    print(f"\n--- {ok_n}/{len(RESULTS)} bestanden")
    print("Kein echter Sidecar gegen den Store, keine Contacts-Operation, "
          "kein TCC-Dialog.")
    return 0 if ok_n == len(RESULTS) else 1


if __name__ == "__main__":
    sys.exit(main())
