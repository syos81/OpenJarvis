#!/usr/bin/env python3
"""enumerate_probe.py — SPIKE G3a (ADR-0016). Temporär, nicht produktiv.

Gestufter, AUSSCHLIESSLICH LESENDER Probe-Lauf zur Eingrenzung des
arm64-SIGABRT im enumerate-Pfad.

NUR IM SEPARATEN macOS-TESTBENUTZER `jarvisspike` AUSFÜHREN.

Sicherheitszusagen:
  * Sendet ausschließlich `caps` und `enumerateProbe`.
  * Kann technisch KEINE Mutation senden — `create`, `update`,
    `updateViaUnified` und `delete` sind hart gesperrt (ALLOWED_OPS).
  * Kein automatischer Retry: Stirbt der Child, endet der Lauf sofort.
  * Jede Stufe startet einen frischen Sidecar, damit ein Absturz die
    Folgestufen nicht verfälscht.
  * Schreibt einen PII-freien Bericht nach results/.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from driver import DriverError, Sidecar, signal_name  # noqa: E402

# Harte Sperre: dieser Runner darf nichts anderes senden.
ALLOWED_OPS = frozenset({"caps", "enumerateProbe", "shutdown"})

STAGE2_GROUPS = ["names-extended", "organization", "contact-type",
                 "emails", "phones", "postal"]
STAGE3_GROUPS = ["image-available", "thumbnail", "image-data", "birthday",
                 "dates", "relations", "social-profiles", "instant-messages",
                 "note"]

DEFAULT_RESULTS_DIR = Path("/Users/Shared/JarvisContactsSpike/results")


def results_dir() -> Path:
    return Path(os.environ.get("JARVIS_CONTACTS_SPIKE_RESULTS_DIR",
                               str(DEFAULT_RESULTS_DIR)))


def guarded_request(sc: Sidecar, op: str, params: dict | None = None,
                    timeout: float = 60.0) -> dict:
    if op not in ALLOWED_OPS:
        raise RuntimeError(f"Operation '{op}' ist im Probe-Modus gesperrt.")
    return sc.request(op, params or {}, timeout=timeout)


def run_stage(label: str, params: dict) -> dict:
    """Eine Stufe in einem frischen Sidecar. Kein Retry."""
    record: dict = {"stage": label, "params": params}
    sc = Sidecar()
    try:
        ready = sc.start()
        record["authorizationStatus"] = ready.get("authorizationStatus")
        if ready.get("authorizationStatus") != "authorized":
            record["result"] = "skipped"
            record["reason"] = "nicht autorisiert"
            return record
        r = guarded_request(sc, "enumerateProbe", params)
        if r.get("ok"):
            record["result"] = "ok"
            record["count"] = r["result"].get("count")
            record["keys"] = r["result"].get("keys")
            record["keysPresent"] = [i.get("keysPresent")
                                     for i in r["result"].get("items", [])][:1]
        else:
            record["result"] = "error"
            record["error"] = r.get("error")
    except DriverError as e:
        # Kein Retry. Der Lauf endet hier.
        record["result"] = "child_died"
        f = e.fields
        record["error_class"] = e.error_class
        record["child_exit_code"] = f.get("child_exit_code")
        record["child_signal"] = f.get("child_signal") or signal_name(
            f.get("child_exit_code"))
        record["elapsed_seconds"] = f.get("elapsed_seconds")
        record["diag_stages"] = f.get("diag_stages")
        record["stderr_tail"] = f.get("stderr_tail")
    finally:
        try:
            sc.shutdown(timeout=3)
        except Exception:
            pass
    return record


def main() -> int:
    if not os.environ.get("JARVIS_CONTACTS_SPIKE_DIAGNOSTICS") == "1":
        print("HINWEIS: ohne JARVIS_CONTACTS_SPIKE_DIAGNOSTICS=1 fehlen die "
              "Stufenmarken. Empfohlen:\n"
              "  JARVIS_CONTACTS_SPIKE_DIAGNOSTICS=1 python3 tools/enumerate_probe.py")

    plan: list[tuple[str, dict]] = [("stage1-minimal", {"stage": 1})]
    plan += [(f"stage2-{g}", {"stage": 2, "group": g}) for g in STAGE2_GROUPS]
    plan += [(f"stage3-{g}", {"stage": 3, "group": g}) for g in STAGE3_GROUPS]

    print("=== Enumerate-Probe (ausschliesslich lesend) ===")
    print(f"  Stufen: {len(plan)}   Mutationen: technisch gesperrt\n")

    records: list[dict] = []
    for label, params in plan:
        rec = run_stage(label, params)
        records.append(rec)
        res = rec.get("result")
        if res == "ok":
            print(f"[OK      ] {label}: count={rec.get('count')} "
                  f"keys={','.join(rec.get('keys') or [])}")
        elif res == "skipped":
            print(f"[SKIP    ] {label}: {rec.get('reason')}")
        elif res == "error":
            print(f"[ERROR   ] {label}: {json.dumps(rec.get('error'))[:120]}")
        else:
            print(f"\n[ABGEBROCHEN] {label}")
            print(f"  Signal        : {rec.get('child_signal')} "
                  f"(exit {rec.get('child_exit_code')})")
            print(f"  Dauer         : {rec.get('elapsed_seconds')} s")
            print(f"  Letzte Stufen : {(rec.get('diag_stages') or [])[-6:]}")
            print("  stderr (bereinigt):")
            for line in rec.get("stderr_tail") or []:
                print(f"    {line}")
            print("\n  ABSTURZGRENZE GEFUNDEN — kein Retry, Lauf endet hier.")
            break

    d = results_dir()
    d.mkdir(parents=True, exist_ok=True)
    out = d / "enumerate-probe.json"
    out.write_text(json.dumps(records, indent=2, ensure_ascii=False))
    print(f"\nBericht: {out}")
    print("Es wurde KEINE Mutation gesendet und KEIN Kontakt veraendert.")
    return 0 if all(r.get("result") in ("ok", "skipped") for r in records) else 1


if __name__ == "__main__":
    sys.exit(main())
