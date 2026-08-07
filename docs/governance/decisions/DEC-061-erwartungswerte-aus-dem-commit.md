---
DEC-ID: DEC-061
Titel: Eigentümer-Erwartungswerte reproduzierbar aus genau dem benannten Commit
Status: accepted
Regel-Alias: R6
Registerpfad: refs/governance/dec-reservations
Block: B0g
---

# DEC-061 — Eigentümer-Erwartungswerte reproduzierbar aus genau dem benannten Commit

## Kontext

Ein veröffentlichter --expect-hash gehörte zu keinem Commit; B0c korrigierte das (config/gates/history/b0c-expectation-correction.json) und band Erwartungswerte an ihre Quelle.

## Entscheidung (normativ)

Jeder Erwartungswert, der dem Eigentümer für eine Eigentümerhandlung übergeben wird, ist reproduzierbar aus genau dem Commit und dem Artefakt ableitbar, auf die sich die Handlung bezieht; die Ableitung gehört zur Abnahmeevidenz. Ein bloß aus einer früheren Ableitung wiederholter Wert ist kein Erwartungswert.

## Geltungsbereich

Alle Erwartungswerte für Eigentümerhandlungen (Guard-Aktivierung, Register-OIDs, Digeste).

## Ausdrücklich nicht geregelt

Werte ohne Eigentümerhandlungsbezug; rein beschreibende Metadaten (DEC-062 regelt deren Bindungspflichtgrenze).

## Mechanische Durchsetzung

pf-/tg-/of-owner-expectations (tools/gates/expectations.py über config/governance/owner-expectations.json); RC-013-Testpaar in tests/tooling/gates/test_expectations.py.

## Herkunft

statement-Feld in config/governance/owner-expectations.json und Korrekturrecord (f3dd0f4, B0c §10).
