---
DEC-ID: DEC-060
Titel: Jede deklarierte Phase läuft gegen den neuen Prüfumfang
Status: accepted
Regel-Alias: R5
Registerpfad: refs/governance/dec-reservations
Block: B0g
---

# DEC-060 — Jede deklarierte Phase läuft gegen den neuen Prüfumfang

## Kontext

Seit B0d führen die Commit-Pläne die Grünbedingung je Commit; ohne sie könnte ein Commit grün erscheinen, obwohl deklarierte Phasen nie gegen den geänderten Gegenstand liefen.

## Entscheidung (normativ)

Ein Commit gilt nur dann als grün, wenn für jeden von ihm geänderten Gegenstand jede Phase, die das zuständige Blockmanifest deklariert, gegen den neuen Prüfumfang gelaufen ist. Ein Commit, der ein Blockmanifest einführt oder ändert, ist nur grün, wenn jede von diesem Manifest deklarierte Phase gegen es gelaufen ist.

## Geltungsbereich

Alle Branch-Commits mit Gate-Bezug; Manifeständerungen.

## Ausdrücklich nicht geregelt

Die Auswahl der Checks innerhalb einer Phase (Manifestsache); die Reihenfolge normativer und feststellender Commits (DEC-067).

## Mechanische Durchsetzung

Bislang prozedural über die Commit-Pläne (condition_per_commit) erzwungen; kein eigener maschineller Prüfer — als ehrlicher Durchsetzungsgap im Authority-Modell und B0g-Korrekturvermerk dokumentiert.

## Herkunft

condition_per_commit in config/gates/history/b0d-commit-plan.json (B0d), wortgleich in B0e/B0f fortgeführt; die Formel dieses Dokuments übernimmt beide Sätze wörtlich und fügt nichts hinzu.
