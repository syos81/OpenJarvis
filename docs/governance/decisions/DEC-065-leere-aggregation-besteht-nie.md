---
DEC-ID: DEC-065
Titel: Eine Aggregation über eine leere Menge meldet nie pass
Status: accepted
Regel-Alias: R10
Registerpfad: refs/governance/dec-reservations
Block: B0g
---

# DEC-065 — Eine Aggregation über eine leere Menge meldet nie pass

## Kontext

mf-evidence verifizierte null Rohlogs einer entzogenen Phase und meldete evidence_complete; der leere Lauf war byteidentisch mit einem sauberen (B0d-Abschluss). B0e fand dieselbe Redewendung elffach in den Prüfern, B0f schloss weitere Vakuitätspfade.

## Entscheidung (normativ)

Eine Prüfung, die über eine Menge aggregiert, meldet nur dann pass, wenn sie mindestens ein Element tatsächlich geprüft hat oder wenn die Leere selbst die unabhängig vom Durchlauf hergeleitete Soll-Eigenschaft ist (derived_empty_set). Andernfalls entsteht der Nicht-Nachweis-Zustand blocked/aggregation_set_empty, den die Aggregationsrangfolge nie in ein grünes Ergebnis aufnehmen kann. Statisch gilt dasselbe: ein fehlender Eingang wird nie still zu einem leeren Container normalisiert, aus dessen Lauf ein positives Urteil wachsen kann.

## Geltungsbereich

Laufzeitaggregationen der Engine (mf-evidence, mf-phase-results, Review-Konsumption) und der statische Bestand über die R10-Kandidatenklassen des Dispositionsregisters. Beide Hälften sind eine Entscheidung mit zwei Durchsetzungsarmen.

## Ausdrücklich nicht geregelt

Deklarierte leere Sollzustände; Diagnostik ohne Urteilseinfluss (kategorisiert im Register).

## Mechanische Durchsetzung

tools/gates/emptyset.py (verdict/require_non_empty) in den Abschlussprüfungen; B0e-/B0f-Sweeps mit Kategorien; RC-023/024/027/029/030/031-Testpaare.

## Herkunft

Laufzeithälfte: Moduldokumentation tools/gates/emptyset.py und RC-023 (8c1e567, B0d-Abschluss, docs/governance/b0d-handoff.md §10); statische Hälfte: rules.R10 in config/governance/ast-dispositions.json (B0e/B0f). Dieses Dokument ist seit B0g die eine normative Quelle beider Hälften.
