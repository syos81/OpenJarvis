---
DEC-ID: DEC-062
Titel: Jedes normative Feld ist mechanisch an seinen Gegenstand gebunden
Status: accepted
Regel-Alias: R7
Registerpfad: refs/governance/dec-reservations
Block: B0g
---

# DEC-062 — Jedes normative Feld ist mechanisch an seinen Gegenstand gebunden

## Kontext

Ein Feld, das den Konfigurationsformatstand benannte, wurde mit nichts verglichen; B0d band config_version an eine Signatur über die Feldmengen des Laders und prüfte den Bestand (config/governance/field-binding.json).

## Entscheidung (normativ)

Jedes normative, entscheidungs-, versions- oder integritätsrelevante Feld ist mechanisch an seinen Gegenstand gebunden oder wird gegen ihn geprüft. Ein Feld, das weder das eine noch das andere ist, wird entfernt statt gepflegt: eine Aussage, die nichts prüft und von nichts geprüft wird, ist schlechter als keine, weil sie Verlässlichkeit vortäuscht. Rein beschreibende Metadaten ohne Verlässlichkeitsanspruch sind ausgenommen, und die Ausnahme ist deklariert.

## Geltungsbereich

Alle Felder mit Norm-, Entscheidungs-, Versions- oder Integritätsanspruch, universell — die engeren Formulierungen in Lineage und RC-014 sind Instanzen, keine Einschränkung.

## Ausdrücklich nicht geregelt

Der Inhalt der gebundenen Felder; Präsenzprüfungen als solche (sie genügen nicht als Bindung).

## Mechanische Durchsetzung

Feldbindungs-Review config/governance/field-binding.json (21 geprüfte Felder); RC-014-Testpaar in tests/tooling/gates/test_field_binding.py; Formatsignatur in tools/guard/rules.py. Durchsetzungsgap vor B0g: das statement-Feld selbst wurde von keinem Prüfer gelesen — seit B0g bindet das Authority-Modell es als derived_enforcement mit Zitatpflicht.

## Herkunft

statement- und method-Feld in config/governance/field-binding.json (d3f9337, B0d).
