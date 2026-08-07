---
DEC-ID: DEC-064
Titel: Eine absichtliche Einwirkung wird vor der Erwartung mechanisch belegt
Status: accepted
Regel-Alias: R9
Registerpfad: refs/governance/dec-reservations
Block: B0g
---

# DEC-064 — Eine absichtliche Einwirkung wird vor der Erwartung mechanisch belegt

## Kontext

Ein Test zerstörte eine Installation per Literalersetzung; nach einer Migration existierte das Literal nicht mehr, die Einwirkung blieb aus, der Test blieb grün (B0D-N1). B0e siebte den gesamten Prüfbestand per Syntaxbaum, B0f falsifizierte vier weitere Ausschlüsse per Ausführungsprobe.

## Entscheidung (normativ)

Ein Test oder Validator, dessen Aussage auf einer absichtlichen Mutation, Störung, Beschädigung oder einem Entzug beruht, belegt mechanisch vor seiner eigentlichen Erwartung, dass die Einwirkung tatsächlich stattgefunden hat; bleibt die Einwirkung aus, fällt der Test, nicht sein Gegenstand. Gewöhnliche Vorbereitung ist nicht gemeint: die Regel gilt, wo die herbeigeführte Wirkung Gegenstand der Erwartung ist. Für die Bestandssiebung gilt: die normative Entscheidung ist die Disposition, nie der Detektor.

## Geltungsbereich

Alle Tests und Validatoren des hergeleiteten Prüfbestands; deklarierte Einwirkungstests; die R9-Kandidatenklassen des Registers config/governance/ast-dispositions.json.

## Ausdrücklich nicht geregelt

Vorbereitungs- und Aufräumschritte ohne Störungssemantik; die Einheitenlokalität der Siebung (offener Methodenbefund aus B0f, außerhalb).

## Mechanische Durchsetzung

tg-/of-effect-evidence (tools/gates/effectevidence.py: erste Zusicherung ist die deklarierte Wirkungszusicherung); B0e-Sweep (tools/gates/astscan.py) und B0f-Kategorien inkl. Neutralisierungsprobe (tools/gates/astcat.py, b0fneuter.py); RC-022/025/026-Testpaare.

## Herkunft

statement/method in config/governance/effect-evidence.json (5fe885a, B0d); Subjekterweiterung auf Validatoren und Dispositionsvorrang aus config/governance/ast-dispositions.json (B0e/B0f, mechanisch durchgesetzt) — dieses Dokument führt beide zusammen, ohne neue Semantik.
