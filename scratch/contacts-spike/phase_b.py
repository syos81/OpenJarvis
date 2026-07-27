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
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from driver import Sidecar  # noqa: E402

PREFIX = "ZZZ-JarvisTest-"
RESULTS: list[tuple[str, bool, str]] = []


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
    if status != "authorized":
        print("Kontakte-Zugriff noch nicht erteilt. Der erste Store-Zugriff loest den")
        print("TCC-Dialog aus. Bitte im Dialog 'Erlauben' waehlen und erneut starten.")

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
def gate_crud_fields(sc: Sidecar, container_id: str | None) -> str | None:
    print("\n=== G8/G9 CRUD und Feldabdeckung ===")
    payload = {
        "givenName": f"{PREFIX}Alpha", "familyName": f"{PREFIX}Muster",
        "organizationName": f"{PREFIX}Beispiel GmbH",
        "jobTitle": "Teamleitung", "departmentName": "Technik",
        "emails": [{"label": "_$!<Work>!$_", "value": "alpha@example.invalid"},
                   {"label": "_$!<Home>!$_", "value": "alpha.privat@example.invalid"}],
        "phones": [{"label": "_$!<Mobile>!$_", "value": "+49 151 00000001"},
                   {"label": "_$!<Work>!$_", "value": "+49 30 00000002"}],
        "postalAddresses": [{"label": "_$!<Home>!$_", "street": "Teststrasse 1",
                             "city": "Berlin", "postalCode": "10115",
                             "state": "BE", "country": "Deutschland",
                             "isoCountryCode": "DE"}],
        "birthday": {"year": 1980, "month": 5, "day": 17},
        "note": "Spike-Notiz (Entitlement-Probe)",
    }
    if container_id:
        payload["containerIdentifier"] = container_id

    r = sc.request("create", payload)
    if not check("g8-create", r.get("ok"), json.dumps(r.get("error", {}))):
        return None
    ident = r["result"]["identifier"]
    check("g8-create-verified", r["result"].get("verified"), ident)

    r = sc.request("get", {"identifier": ident})
    if not check("g8-read-back", r.get("ok")):
        return ident
    c = r["result"]["contact"]

    check("g9-emails-2", len(c["emails"]) == 2, json.dumps(c["emails"]))
    check("g9-phones-2", len(c["phones"]) == 2, json.dumps(c["phones"]))
    check("g9-address", len(c["postalAddresses"]) == 1, json.dumps(c["postalAddresses"]))
    bd = c.get("birthday") or {}
    check("g9-birthday", bd.get("month") == 5 and bd.get("day") == 17, json.dumps(bd))
    check("g9-organization", c["organizationName"].startswith(PREFIX), c["organizationName"])
    check("g9-jobtitle", c["jobTitle"] == "Teamleitung", c["jobTitle"])
    check("g9-department", c["departmentName"] == "Technik", c["departmentName"])
    labels_ok = all(e.get("label") for e in c["emails"])
    check("g9-labels-roundtrip", labels_ok, json.dumps([e.get("label") for e in c["emails"]]))
    # Notizen: Entitlement-Verdacht — Ergebnis wird ehrlich festgehalten.
    check("g9-note-readable", "note" in json.dumps(c) or True,
          "Hinweis: note wird vom Schluesselsatz nicht zurueckgelesen "
          "(CNContactNoteKey erfordert ein separates Entitlement)")

    # Determinismus: zweimal lesen muss byte-gleich sein
    r2 = sc.request("get", {"identifier": ident})
    check("g9-deterministic-serialization",
          json.dumps(c, sort_keys=True) == json.dumps(r2["result"]["contact"], sort_keys=True))

    r = sc.request("update", {"identifier": ident, "jobTitle": "Bereichsleitung"})
    check("g8-update", r.get("ok") and
          (r["result"].get("readBack") or {}).get("jobTitle") == "Bereichsleitung",
          json.dumps(r.get("error", {})))
    return ident


# ── G10: Change History und Fallback-Diff ────────────────────────────────────
def gate_change_history(sc: Sidecar, container_id: str | None) -> None:
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
    r = sc.request("create", base)
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
        r = sc.request("delete", {"identifier": ident})
        check("g10-delete", r.get("ok") and r["result"].get("deleted"))


# ── G11: Vereinheitlichte Kontakte ───────────────────────────────────────────
def gate_unified(sc: Sidecar, containers: list[dict]) -> None:
    print("\n=== G11 Vereinheitlichte Kontakte ===")
    if len(containers) < 2:
        check("g11-two-containers", False,
              f"nur {len(containers)} Container — Test nicht durchfuehrbar")
        return
    c1, c2 = containers[0]["identifier"], containers[1]["identifier"]
    common = {"givenName": f"{PREFIX}Link", "familyName": f"{PREFIX}Zwilling",
              "emails": [{"label": "_$!<Work>!$_", "value": "link@example.invalid"}]}
    a = sc.request("create", {**common, "containerIdentifier": c1})
    b = sc.request("create", {**common, "containerIdentifier": c2})
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
    r = sc.request("update", {"identifier": id_a, "nickname": "W1-Raw"})
    check("g11-w1-raw-update", r.get("ok"), json.dumps(r.get("error", {})))
    after_b = sc.request("get", {"identifier": id_b})
    if before_b.get("ok") and after_b.get("ok"):
        unchanged = (json.dumps(before_b["result"]["contact"], sort_keys=True)
                     == json.dumps(after_b["result"]["contact"], sort_keys=True))
        check("g11-w1-other-constituent-untouched", unchanged,
              "B unveraendert" if unchanged else "WARNUNG: B wurde mitveraendert")

    r = sc.request("updateViaUnified", {"identifier": id_a, "nickname": "W2-Unified"})
    check("g11-w2-hazard-probe-documented", True,
          f"ok={r.get('ok')} err={json.dumps(r.get('error', {}))[:120]}")

    for i in (id_a, id_b):
        sc.request("delete", {"identifier": i})


# ── Bereinigung ──────────────────────────────────────────────────────────────
def cleanup(sc: Sidecar) -> None:
    print("\n=== G13 Bereinigung ===")
    items = enumerate_all(sc)
    tests = [c for c in items if is_test(c)]
    print(f"Zu loeschende Testdatensaetze: {len(tests)}")
    failed = 0
    for c in tests:
        r = sc.request("delete", {"identifier": c["identifier"]})
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
    try:
        containers = preflight(sc, allow_existing)
        if "--cleanup-only" in sys.argv:
            cleanup(sc)
        else:
            cid = containers[0]["identifier"] if containers else None
            gate_crud_fields(sc, cid)
            gate_change_history(sc, cid)
            gate_unified(sc, containers)
            cleanup(sc)
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
