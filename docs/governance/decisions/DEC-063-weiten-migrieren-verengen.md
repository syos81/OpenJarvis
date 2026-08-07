---
DEC-ID: DEC-063
Titel: Konfigurationsmigrationen laufen als weiten, migrieren, verengen
Status: accepted
Regel-Alias: R8
Registerpfad: refs/governance/dec-reservations
Block: B0g
---

# DEC-063 — Konfigurationsmigrationen laufen als weiten, migrieren, verengen

## Kontext

R7 in R4-Reihenfolge angewandt erzeugte zwischen zwei Schreibvorgängen einen ungültigen Zustand, und der repositoryseitige Hook sperrte die Sitzung in diesem Fenster (RC-015, finding_origin).

## Entscheidung (normativ)

Eine Formatänderung an einer Konfiguration, die der aktive Guard lädt, geschieht in drei Schritten: die akzeptierte Versionsmenge wird geweitet, die Daten werden migriert, danach wird die Menge verengt. Jeder Zwischenzustand ist gültig, egal welche Datei zuerst geschrieben wird. Außerhalb einer Migration hält die Menge genau einen Eintrag.

## Geltungsbereich

Konfigurationen, die der aktive Guard oder ein gleichartig fail-closed arbeitender Leser lädt; sinngemäß jede R4-gebundene Formatmigration.

## Ausdrücklich nicht geregelt

Migrationsentscheidungen selbst (was migriert wird); Nicht-Konfigurationsdaten.

## Mechanische Durchsetzung

ACCEPTED_CONFIG_VERSIONS-Mechanik in tools/guard/rules.py; RC-015-Testpaar tests/tooling/gates/test_field_binding.py::TestR8Migration (geweiteter Leser akzeptiert beide Formen, verengter weist die ausgehende ab, aktuell genau eine Form).

## Herkunft

RC-015-Summary in config/guard/rule-changes.json und Regelkommentar in tools/guard/rules.py (d3f9337, B0d); der präziseste Text war ein Python-Kommentar — seit B0g ist dieses Dokument die normative Quelle.
