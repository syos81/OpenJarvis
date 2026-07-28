#!/usr/bin/env python3
"""isolation_probe.py — SPIKE G3a (ADR-0016). Temporär, nicht produktiv.

AUSSCHLIESSLICH LESENDE Isolationsprüfung des Kontaktbestands im Testbenutzer.

Anlass: Der Enumerate-Probe-Lauf meldete `count=1`. Die Annahme eines völlig
leeren Testkontos gilt damit nicht mehr. Vor jeder Mutation muss geklärt sein,
ob dieser Datensatz eine „Meine Karte", ein älterer ZZZ-JarvisTest-Kontakt oder
ein fremder Kontakt ist.

PII-VERTRAG (verbindlich):
  * Die Klassifikation findet vollständig IM SIDECAR statt. Namensfelder und
    Identifier verlassen den Sidecar-Prozess NIEMALS — über das Protokoll gehen
    ausschliesslich Zahlen und Booleans.
  * Ausgegeben und gespeichert werden nur: authorizationStatus, Containeranzahl
    und -typen, totalContacts, prefixedTestContacts, foreignContacts,
    meCardPresent, meCardIncludedInEnumerate, duplicateIdentifiersDetected,
    mutationCount (immer 0), testPrefix.
  * Niemals: Namen, Identifier, E-Mails, Telefonnummern, Adressen, Geburtstage,
    Organisationen, Notizen, Bilddaten, vollständige Kontaktobjekte.

MUTATIONSSICHERHEIT:
  * ALLOWED_OPS erlaubt technisch nur lesende Operationen.
  * Kein `--allow-existing` und kein vergleichbarer Schalter.
  * Kein Retry.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from driver import DriverError, Sidecar, signal_name  # noqa: E402

# Harte Sperre: dieser Runner darf nichts anderes senden.
ALLOWED_OPS = frozenset({"caps", "isolationSummary", "shutdown"})

# Felder, die den Bericht verlassen duerfen — alles andere wird verworfen.
ALLOWED_RESULT_FIELDS = (
    "authorizationStatus", "containerCount", "containerTypes",
    "totalContacts", "prefixedTestContacts", "foreignContacts",
    "meCardPresent", "meCardIncludedInEnumerate",
    "duplicateIdentifiersDetected", "mutationCount", "testPrefix",
)

DEFAULT_RESULTS_DIR = Path("/Users/Shared/JarvisContactsSpike/results")


def results_dir() -> Path:
    return Path(os.environ.get("JARVIS_CONTACTS_SPIKE_RESULTS_DIR",
                               str(DEFAULT_RESULTS_DIR)))


def guarded_request(sc: Sidecar, op: str, params: dict | None = None,
                    timeout: float = 120.0) -> dict:
    if op not in ALLOWED_OPS:
        raise RuntimeError(f"Operation '{op}' ist im Isolations-Probe gesperrt.")
    return sc.request(op, params or {}, timeout=timeout)


def filter_result(result: dict) -> dict:
    """Zweite Verteidigungslinie: nur erlaubte Felder uebernehmen."""
    return {k: result[k] for k in ALLOWED_RESULT_FIELDS if k in result}


def classify(summary: dict) -> tuple[str, list[str]]:
    """Bewertung ohne jede Kontaktinformation."""
    total = summary.get("totalContacts")
    pref = summary.get("prefixedTestContacts")
    foreign = summary.get("foreignContacts")
    me = summary.get("meCardPresent")
    me_in = summary.get("meCardIncludedInEnumerate")
    notes: list[str] = []

    if total == 0:
        return "leer", ["Bestand leer — Mutationstest waere unbedenklich."]
    if foreign == 0 and pref:
        notes.append(f"{pref} Datensatz/Datensaetze mit Praefix "
                     f"{summary.get('testPrefix')} — Altbestand aus einem "
                     "frueheren Spike-Lauf.")
        notes.append("Ohne ausdrueckliche Freigabe wird davon nichts veraendert "
                     "oder geloescht.")
        return "nur-testkontakte", notes
    if foreign:
        notes.append(f"{foreign} FREMDER Datensatz/Datensaetze ohne Testpraefix.")
        if me is True and me_in is True and foreign == 1 and total == 1:
            notes.append("Der einzige Datensatz ist zugleich die 'Meine Karte' "
                         "— typisch fuer ein frisch angelegtes Benutzerkonto.")
            return "nur-me-card", notes
        if me is True:
            notes.append("Eine 'Meine Karte' ist gesetzt; ob sie zu den "
                         "Fremdkontakten zaehlt, zeigt meCardIncludedInEnumerate.")
        notes.append("phase_b.py wuerde hier VOR jeder Mutation abbrechen. "
                     "Das ist beabsichtigt.")
        return "fremdkontakte-vorhanden", notes
    return "unklar", ["Keine eindeutige Einordnung moeglich."]


def main() -> int:
    if "--allow-existing" in sys.argv:
        print("ABBRUCH: --allow-existing existiert in diesem Runner nicht. "
              "Er ist ausschliesslich lesend.", file=sys.stderr)
        return 2

    print("=== Isolationspruefung (ausschliesslich lesend) ===")
    sc = Sidecar()
    record: dict = {"probe": "isolation", "mutationCount": 0}
    try:
        ready = sc.start()
        if ready.get("authorizationStatus") != "authorized":
            print(f"  Nicht autorisiert ({ready.get('authorizationStatus')}). "
                  "Zuerst tools/authorize.py ausfuehren.")
            record["result"] = "not_authorized"
            record["authorizationStatus"] = ready.get("authorizationStatus")
            return 3
        r = guarded_request(sc, "isolationSummary")
        if not r.get("ok"):
            record["result"] = "error"
            record["error"] = r.get("error")
            print(f"  FEHLER: {json.dumps(r.get('error'))[:160]}")
            return 1
        summary = filter_result(r["result"])
        record["result"] = "ok"
        record["summary"] = summary
        verdict, notes = classify(summary)
        record["verdict"] = verdict
        record["notes"] = notes

        print(f"\n  Autorisierung           : {summary.get('authorizationStatus')}")
        print(f"  Container               : {summary.get('containerCount')} "
              f"({', '.join(summary.get('containerTypes') or [])})")
        print(f"  Kontakte gesamt         : {summary.get('totalContacts')}")
        print(f"  davon Testpraefix       : {summary.get('prefixedTestContacts')}")
        print(f"  davon FREMD             : {summary.get('foreignContacts')}")
        print(f"  Meine Karte vorhanden   : {summary.get('meCardPresent')}")
        print(f"  ... in Enumerate enthalten: "
              f"{summary.get('meCardIncludedInEnumerate')}")
        print(f"  Doppelte Identifier     : "
              f"{summary.get('duplicateIdentifiersDetected')}")
        print(f"  Mutationen              : {summary.get('mutationCount')}")
        print(f"\n  EINORDNUNG: {verdict}")
        for n in notes:
            print(f"    - {n}")
    except DriverError as e:
        record["result"] = "child_died"
        record["error_class"] = e.error_class
        record["child_signal"] = e.fields.get("child_signal") or signal_name(
            e.fields.get("child_exit_code"))
        record["diag_stages"] = e.fields.get("diag_stages")
        record["stderr_tail"] = e.fields.get("stderr_tail")
        print(f"\n  ABGEBROCHEN: {record['child_signal']} — kein Retry.")
        for line in record.get("stderr_tail") or []:
            print(f"    {line}")
        return 1
    finally:
        try:
            sc.shutdown(timeout=3)
        except Exception:
            pass
        d = results_dir()
        d.mkdir(parents=True, exist_ok=True)
        out = d / "isolation-probe.json"
        out.write_text(json.dumps(record, indent=2, ensure_ascii=False))
        print(f"\nBericht: {out}")
        print("Es wurde KEINE Mutation gesendet und KEIN Kontakt veraendert.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
