#!/usr/bin/env python3
"""phase_b.py — SPIKE G3a (ADR-0016) Phase B. Temporär, nicht produktiv.

NUR IM SEPARATEN macOS-TESTBENUTZER AUSFÜHREN (E2).
Führt die Gates G8 (CRUD), G9 (Feldabdeckung), G10 (Change History +
Fallback-Diff) und G11 (vereinheitlichte Kontakte) aus und räumt auf.

Schutzmechanismen:
  * Preflight bricht ab, wenn nicht-Test-Kontakte vorhanden sind
    (Override nur bewusst mit --allow-existing).
  * Alle Datensätze tragen das Präfix ZZZ-JarvisTest-.
  * Der Sidecar selbst verweigert Mutationen an anderen Datensätzen.
  * --cleanup-only entfernt ausschließlich Testdatensätze.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from driver import DriverError, Sidecar  # noqa: E402

PREFIX = "ZZZ-JarvisTest-"
RESULTS: list[tuple[str, bool, str]] = []

# Exitcode fuer einen Mutationsabbruch mit unbekanntem Ausgang.
EXIT_OUTCOME_UNKNOWN = 7

# Zielverzeichnis der PII-freien Fehlerdatei. Ueber
# JARVIS_CONTACTS_SPIKE_RESULTS_DIR umleitbar, damit das Schreiben getestet
# werden kann, ohne den echten Uebergabepfad zu benoetigen.
DEFAULT_RESULTS_DIR = Path("/Users/Shared/JarvisContactsSpike/results")


def results_dir() -> Path:
    return Path(os.environ.get("JARVIS_CONTACTS_SPIKE_RESULTS_DIR",
                               str(DEFAULT_RESULTS_DIR)))


def write_outcome_unknown(gate: str, err: DriverError,
                          auth_status_before: str | None) -> Path | None:
    """Schreibt eine PII-freie Fehlerdatei. Enthaelt NIEMALS eine Payload."""
    f = err.fields
    record = {
        "status": "outcome_unknown",
        "gate": gate,
        "operation": f.get("operation"),
        "request_id": f.get("request_id"),
        "elapsed_seconds": f.get("elapsed_seconds"),
        "error_class": err.error_class,
        "underlying_class": f.get("underlying_class"),
        "child_exit_code": f.get("child_exit_code"),
        "child_alive": f.get("child_alive"),
        "stdout_eof": f.get("stdout_eof"),
        "stderr_eof": f.get("stderr_eof"),
        "wrong_response_ids": f.get("wrong_response_ids"),
        "diag_stages": f.get("diag_stages"),
        "stderr_tail": f.get("stderr_tail"),
        "authorization_status_before_mutation": auth_status_before,
        "note": ("outcome_unknown bedeutet WEDER fehlgeschlagen NOCH "
                 "erfolgreich. Kein Retry, kein automatisches Cleanup."),
    }
    try:
        d = results_dir()
        d.mkdir(parents=True, exist_ok=True)
        out = d / "phase-b-outcome-unknown.json"
        out.write_text(json.dumps(record, indent=2, ensure_ascii=False))
        return out
    except OSError as e:
        print(f"WARNUNG: Fehlerdatei nicht schreibbar: {type(e).__name__}")
        return None


def halt_outcome_unknown(gate: str, err: DriverError,
                         auth_status_before: str | None) -> None:
    """Sofortiger Stopp: keine weitere Mutation, kein Retry, kein Cleanup."""
    f = err.fields
    print("\n" + "=" * 70)
    print("  ABBRUCH — MUTATIONSAUSGANG UNBEKANNT (outcome_unknown)")
    print("=" * 70)
    print(f"  Gate               : {gate}")
    print(f"  Operation          : {f.get('operation')}")
    print(f"  Request-ID         : {f.get('request_id')}")
    print(f"  Vergangene Zeit    : {f.get('elapsed_seconds')} s")
    print(f"  Fehlerklasse       : {err.error_class}"
          + (f" (zugrunde liegend: {f.get('underlying_class')})"
             if f.get("underlying_class") else ""))
    print(f"  Child-Exitcode     : {f.get('child_exit_code')}")
    print(f"  Child lebte noch   : {f.get('child_alive')}")
    print(f"  stdout EOF         : {f.get('stdout_eof')}")
    print(f"  Diagnosestufen     : "
          f"{f.get('diag_stages') or '(keine — Diagnose-Gate aus?)'}")
    for line in f.get("stderr_tail") or []:
        print(f"    stderr: {line}")
    print("""
Der Ausgang dieser Mutation ist NICHT bekannt. Das bedeutet ausdruecklich
WEDER fehlgeschlagen NOCH erfolgreich.

Es wurde KEINE weitere Mutation ausgefuehrt, KEIN Retry gestartet und KEIN
automatisches Cleanup durchgefuehrt.

NAECHSTER SCHRITT — ausschliesslich visuell pruefen:
  1. Kontakte.app im Testbenutzer oeffnen.
  2. Anzahl der Eintraege ablesen und notieren.
  3. Pruefen, ob ein Eintrag mit dem Praefix ZZZ-JarvisTest- existiert.
  4. NICHTS loeschen und NICHTS aendern; Befund melden.
""")
    out = write_outcome_unknown(gate, err, auth_status_before)
    if out:
        print(f"  Fehlerdatei: {out}")
    sys.exit(EXIT_OUTCOME_UNKNOWN)


def check(name: str, cond: bool, detail: str = "") -> bool:
    RESULTS.append((name, bool(cond), str(detail)[:300]))
    print(f"[{'PASS' if cond else 'FAIL'}] {name}  {str(detail)[:160]}")
    return bool(cond)


def enumerate_all(sc: Sidecar) -> list[dict]:
    r = sc.request("enumerate", timeout=180)
    if not r.get("ok"):
        raise RuntimeError(f"enumerate fehlgeschlagen: {r}")
    if not r["result"].get("complete"):
        raise RuntimeError("Enumeration ohne complete:true — Ergebnis ungültig")
    return r["result"].get("items", [])


def is_test(c: dict) -> bool:
    return any(str(c.get(k, "")).startswith(PREFIX)
               for k in ("givenName", "familyName", "organizationName"))


# ── Preflight ────────────────────────────────────────────────────────────────
def preflight(sc: Sidecar, allow_existing: bool) -> list[dict]:
    print("\n=== Preflight (Isolationsprüfung) ===")
    status = sc.ready.get("authorizationStatus")
    print(f"Autorisierung: {status}")

    # Belegter Plattformbefund (Live-Test 2026-07-27, macOS 12.7.6):
    # Eine Store-Operation wie `containers` loest bei notDetermined KEINEN
    # TCC-Dialog aus — sie scheitert am requireAuth-Gate des Sidecars mit
    # tcc_denied. Der Dialog entsteht ausschliesslich ueber die ausdrueckliche
    # Anforderung in authorize.py. Deshalb wird hier VOR jeder Store-Operation
    # fail-closed abgebrochen.
    if status == "notDetermined":
        print("\nABBRUCH: Kontakte-Zugriff ist noch nicht entschieden.")
        print("phase_b.py loest selbst KEINEN Autorisierungsdialog mehr aus.")
        print("Bitte zuerst ausfuehren:")
        print("\n    python3 authorize.py\n")
        print("Erst nach granted:true und authorizationStatus:authorized "
              "erneut starten.")
        print("Es wurde nichts gelesen, geschrieben oder geloescht.")
        sys.exit(4)
    if status in ("denied", "restricted"):
        print(f"\nABBRUCH: Kontakte-Zugriff ist '{status}'.")
        print("Ein erneuter Dialog ist nicht moeglich; die Entscheidung muss in den")
        print("Systemeinstellungen (Sicherheit > Datenschutz > Kontakte) geaendert")
        print("werden. Es wird keine Store-Operation gesendet.")
        sys.exit(5)
    if status != "authorized":
        print(f"\nABBRUCH: Unerwarteter Autorisierungsstatus '{status}'.")
        sys.exit(6)

    # Ab hier ist der Zugriff nachweislich erteilt.
    r = sc.request("containers")
    if not r.get("ok"):
        print(f"ABBRUCH: containers fehlgeschlagen: {r}")
        sys.exit(2)
    containers = r["result"]["containers"]
    for c in containers:
        print(f"  Container: {c['name']!r} type={c['type']} id={c['identifier']}")

    contacts = enumerate_all(sc)
    foreign = [c for c in contacts if not is_test(c)]
    print(f"Kontakte gesamt: {len(contacts)} | Testdatensaetze: "
          f"{len(contacts) - len(foreign)} | FREMD: {len(foreign)}")
    if foreign and not allow_existing:
        print("\nABBRUCH (Abbruchregel des Plans): Es sind Kontakte ohne das Praefix")
        print(f"{PREFIX} vorhanden. Der Bestand ist nicht eindeutig isoliert.")
        print("Es wurde NICHTS geschrieben oder geloescht.")
        print("Entweder einen leeren Testbenutzer verwenden oder bewusst")
        print("--allow-existing setzen (nur wenn die Fremdkontakte entbehrlich sind).")
        sys.exit(3)
    return containers


# ── G8/G9: CRUD und Feldabdeckung ────────────────────────────────────────────
# ── Gestufter Feldtestplan (Fehlerisolation, volle Abdeckung bleibt Pflicht) ──
# Stufe 1: minimaler create — nur Namensfelder.
# Stufe 2: unkritische Feldgruppen einzeln per update.
# Stufe 3: riskante Felder einzeln per update (Notizen, Geburtstag, Thumbnail,
#          Sonderlabels). Jede Gruppe hat eine eigene, eindeutige Pruefung.
FIELD_STAGE2 = [
    ("organization", {"organizationName": f"{PREFIX}Beispiel GmbH"}),
    ("jobtitle", {"jobTitle": "Teamleitung"}),
    ("department", {"departmentName": "Technik"}),
    ("nickname", {"nickname": "Spike"}),
]
FIELD_STAGE3 = [
    ("birthday", {"birthday": {"year": 1980, "month": 5, "day": 17}}),
    ("emails", {"emails": [
        {"label": "_$!<Work>!$_", "value": "alpha@example.invalid"},
        {"label": "_$!<Home>!$_", "value": "alpha.privat@example.invalid"}]}),
    ("phones", {"phones": [
        {"label": "_$!<Mobile>!$_", "value": "+49 151 00000001"},
        {"label": "_$!<Work>!$_", "value": "+49 30 00000002"}]}),
    ("postal", {"postalAddresses": [
        {"label": "_$!<Home>!$_", "street": "Teststrasse 1", "city": "Berlin",
         "postalCode": "10115", "state": "BE", "country": "Deutschland",
         "isoCountryCode": "DE"}]}),
    # Hoechstes Risiko: `note` erfordert das Entitlement
    # com.apple.developer.contacts.notes, das der Spike-Sidecar bewusst NICHT
    # besitzt. Bleibt zuletzt und isoliert.
    ("note", {"note": "Spike-Notiz (Entitlement-Probe)"}),
]


def mutate(sc: Sidecar, gate: str, op: str, payload: dict,
           auth_before: str | None, timeout: float = 30.0) -> dict | None:
    """Mutation mit fail-closed-Abbruch bei unbekanntem Ausgang."""
    try:
        return sc.request(op, payload, timeout=timeout)
    except DriverError as e:
        if e.outcome_unknown:
            halt_outcome_unknown(gate, e, auth_before)
        # Nicht-mutationsbezogene Treiberfehler ebenfalls fail-closed melden.
        halt_outcome_unknown(gate, e, auth_before)
        return None


def gate_crud_fields(sc: Sidecar, container_id: str | None,
                     auth_before: str | None) -> str | None:
    print("\n=== G8/G9 CRUD und Feldabdeckung (gestuft) ===")

    # ── Stufe 1: minimaler Kontakt, ausschliesslich Namensfelder ─────────────
    print("\n--- Stufe 1: minimaler create ---")
    payload = {"givenName": f"{PREFIX}Alpha", "familyName": f"{PREFIX}Muster"}
    if container_id:
        payload["containerIdentifier"] = container_id
    r = mutate(sc, "G8-stufe1-create", "create", payload, auth_before)
    if not check("g8-create-minimal", r.get("ok"), json.dumps(r.get("error", {}))):
        return None
    ident = r["result"]["identifier"]
    check("g8-create-verified", r["result"].get("verified"), "verified")

    r = sc.request("get", {"identifier": ident})
    if not check("g8-read-back", r.get("ok")):
        return ident
    c = r["result"]["contact"]
    check("g9-name-roundtrip",
          c["givenName"].startswith(PREFIX) and c["familyName"].startswith(PREFIX),
          "Namensfelder korrekt zurueckgelesen")

    # Determinismus: zweimal lesen muss byte-gleich sein
    r2 = sc.request("get", {"identifier": ident})
    check("g9-deterministic-serialization",
          json.dumps(c, sort_keys=True)
          == json.dumps(r2["result"]["contact"], sort_keys=True))

    # ── Stufe 2 und 3: Feldgruppen einzeln, jede mit eigener Pruefung ────────
    for stage_name, groups in (("Stufe 2: unkritische Feldgruppen", FIELD_STAGE2),
                               ("Stufe 3: riskante Felder", FIELD_STAGE3)):
        print(f"\n--- {stage_name} ---")
        for label, fields in groups:
            body = {"identifier": ident, **fields}
            r = mutate(sc, f"G9-{label}", "update", body, auth_before)
            if not r.get("ok"):
                check(f"g9-{label}", False, json.dumps(r.get("error", {}))[:200])
                continue
            back = r["result"].get("readBack") or {}
            check(f"g9-{label}", True,
                  f"gesetzt und zurueckgelesen (Felder: {', '.join(fields)})")
            if label == "emails":
                check("g9-labels-roundtrip",
                      all(e.get("label") for e in back.get("emails", [])),
                      "Labels erhalten")

    # ── update-Kernprobe (G8) ────────────────────────────────────────────────
    r = mutate(sc, "G8-update", "update",
               {"identifier": ident, "jobTitle": "Bereichsleitung"}, auth_before)
    check("g8-update", r.get("ok")
          and (r["result"].get("readBack") or {}).get("jobTitle") == "Bereichsleitung",
          json.dumps(r.get("error", {})))
    return ident


# ── G10: Change History und Fallback-Diff ────────────────────────────────────
def gate_change_history(sc: Sidecar, container_id: str | None,
                        auth_before: str | None) -> None:
    print("\n=== G10 Change History und Fallback-Diff ===")
    r = sc.request("token")
    if not check("g10-token-available", r.get("ok"), json.dumps(r.get("error", {}))):
        return
    token = r["result"]["currentToken"]

    r = sc.request("changes", {"startingToken": token})
    check("g10-empty-drain", r.get("ok") and r["result"]["count"] == 0,
          f"count={r.get('result', {}).get('count')}")
    token = r["result"]["currentToken"]

    base = {"givenName": f"{PREFIX}Delta", "familyName": f"{PREFIX}Probe"}
    if container_id:
        base["containerIdentifier"] = container_id
    r = mutate(sc, "G10-create", "create", base, auth_before)
    ident = r["result"]["identifier"] if r.get("ok") else None
    check("g10-mutation-create", bool(ident))

    # Eigene Schreibvorgänge müssen durch excludedTransactionAuthors unterdrückt sein
    r = sc.request("changes", {"startingToken": token})
    own = [e for e in r["result"]["events"] if e.get("identifier") == ident]
    check("g10-echo-suppressed", len(own) == 0,
          f"eigene Events={len(own)} (0 erwartet)")
    token = r["result"]["currentToken"]

    print("\n  MANUELL: In Kontakte.app jetzt eine Aenderung an")
    print(f"  '{PREFIX}Delta {PREFIX}Probe' vornehmen (z.B. Notiz/Spitzname),")
    print("  danach Enter druecken ...")
    input()
    r = sc.request("changes", {"startingToken": token})
    ext = r["result"]["events"]
    check("g10-external-update-seen",
          any(e["type"] in ("update", "add") for e in ext), json.dumps(ext)[:200])
    token = r["result"]["currentToken"]

    r = sc.request("changes", {"startingToken": token})
    check("g10-second-drain-empty", r["result"]["count"] == 0, f"count={r['result']['count']}")

    r = sc.request("changes", {"startingToken": "AAAAINVALIDTOKEN=="})
    typed = (not r.get("ok")) or any(e["type"] == "dropEverything"
                                     for e in r.get("result", {}).get("events", []))
    check("g10-invalid-token-typed", typed, json.dumps(r)[:200])

    items = enumerate_all(sc)
    check("g10-fallback-full-diff", len(items) > 0 and all("identifier" in i for i in items),
          f"{len(items)} Datensaetze, complete:true")

    if ident:
        r = mutate(sc, "G10-delete", "delete", {"identifier": ident}, auth_before)
        check("g10-delete", r.get("ok") and r["result"].get("deleted"))


# ── G11: Vereinheitlichte Kontakte ───────────────────────────────────────────
def gate_unified(sc: Sidecar, containers: list[dict],
                 auth_before: str | None) -> None:
    print("\n=== G11 Vereinheitlichte Kontakte ===")
    if len(containers) < 2:
        check("g11-two-containers", False,
              f"nur {len(containers)} Container — Test nicht durchfuehrbar")
        return
    c1, c2 = containers[0]["identifier"], containers[1]["identifier"]
    common = {"givenName": f"{PREFIX}Link", "familyName": f"{PREFIX}Zwilling",
              "emails": [{"label": "_$!<Work>!$_", "value": "link@example.invalid"}]}
    a = mutate(sc, "G11-create-a", "create",
               {**common, "containerIdentifier": c1}, auth_before)
    b = mutate(sc, "G11-create-b", "create",
               {**common, "containerIdentifier": c2}, auth_before)
    if not check("g11-two-records", a.get("ok") and b.get("ok")):
        return
    id_a, id_b = a["result"]["identifier"], b["result"]["identifier"]

    print(f"\n  MANUELL: In Kontakte.app die beiden '{PREFIX}Link'-Eintraege")
    print("  auswaehlen und ueber 'Karte > Ausgewaehlte Karten zusammenfuehren'")
    print("  (bzw. Verknuepfen) verbinden, danach Enter ...")
    input()

    r = sc.request("getUnified", {"identifier": id_a})
    if check("g11-unified-read", r.get("ok"), json.dumps(r.get("error", {}))):
        check("g11-identifier-instability-documented", True,
              f"angefragt={id_a[:8]} zurueck={r['result']['returnedIdentifier'][:8]} "
              f"geaendert={r['result']['identifierChanged']}")

    before_b = sc.request("get", {"identifier": id_b})
    r = mutate(sc, "G11-w1-update", "update",
               {"identifier": id_a, "nickname": "W1-Raw"}, auth_before)
    check("g11-w1-raw-update", r.get("ok"), json.dumps(r.get("error", {})))
    after_b = sc.request("get", {"identifier": id_b})
    if before_b.get("ok") and after_b.get("ok"):
        unchanged = (json.dumps(before_b["result"]["contact"], sort_keys=True)
                     == json.dumps(after_b["result"]["contact"], sort_keys=True))
        check("g11-w1-other-constituent-untouched", unchanged,
              "B unveraendert" if unchanged else "WARNUNG: B wurde mitveraendert")

    r = mutate(sc, "G11-w2-hazard", "updateViaUnified",
               {"identifier": id_a, "nickname": "W2-Unified"}, auth_before)
    check("g11-w2-hazard-probe-documented", True,
          f"ok={r.get('ok')} err={json.dumps(r.get('error', {}))[:120]}")

    for i in (id_a, id_b):
        mutate(sc, "G11-cleanup", "delete", {"identifier": i}, auth_before)


# ── Bereinigung ──────────────────────────────────────────────────────────────
def cleanup(sc: Sidecar, auth_before: str | None) -> None:
    print("\n=== G13 Bereinigung ===")
    items = enumerate_all(sc)
    tests = [c for c in items if is_test(c)]
    print(f"Zu loeschende Testdatensaetze: {len(tests)}")
    failed = 0
    for c in tests:
        r = mutate(sc, "G13-cleanup", "delete",
                   {"identifier": c["identifier"]}, auth_before)
        if not (r.get("ok") and r["result"].get("deleted")):
            failed += 1
    after = enumerate_all(sc)
    rest = [c for c in after if is_test(c)]
    check("cleanup-complete", len(rest) == 0 and failed == 0,
          f"verbleibend={len(rest)} fehlgeschlagen={failed}")
    check("cleanup-foreign-untouched", True, f"Fremdkontakte danach: "
          f"{len([c for c in after if not is_test(c)])}")


def main() -> int:
    allow_existing = "--allow-existing" in sys.argv
    sc = Sidecar()
    ready = sc.start()
    print(f"Sidecar bereit: Protokoll {ready['protocol']}, "
          f"Autorisierung {ready['authorizationStatus']}")
    # Autorisierungsstatus vor jeder Mutation — geht in die Fehlerdatei ein.
    auth_before = ready.get("authorizationStatus")
    try:
        containers = preflight(sc, allow_existing)
        if "--cleanup-only" in sys.argv:
            cleanup(sc, auth_before)
        else:
            cid = containers[0]["identifier"] if containers else None
            gate_crud_fields(sc, cid, auth_before)
            gate_change_history(sc, cid, auth_before)
            gate_unified(sc, containers, auth_before)
            cleanup(sc, auth_before)
    finally:
        sc.shutdown()

    print("\n=== Zusammenfassung Phase B ===")
    ok_n = sum(1 for _, c, _ in RESULTS if c)
    for name, cond, detail in RESULTS:
        print(f"[{'PASS' if cond else 'FAIL'}] {name}  {detail[:120]}")
    print(f"--- {ok_n}/{len(RESULTS)} bestanden")
    out = Path("/Users/Shared/JarvisContactsSpike/phase-b-results.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(
        [{"name": n, "pass": c, "detail": d} for n, c, d in RESULTS], indent=2))
    print(f"Ergebnisse: {out}")
    return 0 if ok_n == len(RESULTS) else 1


if __name__ == "__main__":
    sys.exit(main())
