---
DEC-ID: DEC-058
Titel: Kein stilles not_applicable für garantiert vorhandene Artefakte
Status: accepted
Regel-Alias: R3
Registerpfad: refs/governance/dec-reservations
Block: B0g
---

# DEC-058 — Kein stilles not_applicable für garantiert vorhandene Artefakte

## Kontext

Drei Abnahmerecords erklärten fehlende Laufzeitevidenz per Vorgabe zu not_applicable; B0b band die Evidenz als committete Schnappschüsse und verschärfte die Vorgabe auf fail (config/gates/history/r3-not-applicable-review.json).

## Entscheidung (normativ)

Ein Gate-Ergebnis not_applicable entsteht ausschließlich aus einer deklarativen Manifestregel mit sachlicher Begründung und niemals als Vorgabe für ein Artefakt, das garantiert existiert. Eine fehlende Voraussetzung ist blocked, nie not_applicable und nie pass.

## Geltungsbereich

Alle Gate-Ergebnisse, Manifest-Phasendeklarationen und Reexecution-Vorgaben.

## Ausdrücklich nicht geregelt

Die Entscheidung, welche Phasen ein Block fachlich deklariert; die Baseline-Semantik (pass_with_baseline).

## Mechanische Durchsetzung

of-not-applicable-review (tools/gates/runners/history_checks.py, mode not_applicable_review) über alle Abnahmerecords, inklusive der B0e-Verschärfungen (runtime_evidence_undeclared); Manifestvalidierung erzwingt declared_result nur bei applicable:false mit Begründung.

## Herkunft

config/gates/history/r3-not-applicable-review.json (29fc013, B0b). Die abweichend engere Checkbeschreibung im B0d-Manifest ist Beschreibungsdrift, keine zweite Norm; beide Registerquellen (r3-Review und CLAUDE.md-Alttext) fordern kumulativ Manifestregel und Garantieverbot.
