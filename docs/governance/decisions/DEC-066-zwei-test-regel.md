---
DEC-ID: DEC-066
Titel: Zwei-Test-Regel für jede Änderung einer bestehenden Prüfregel
Status: accepted
Regel-Alias: zwei-test-regel
Registerpfad: refs/governance/dec-reservations
Block: B0g
---

# DEC-066 — Zwei-Test-Regel für jede Änderung einer bestehenden Prüfregel

## Kontext

Regeländerungen ohne Testpaar können unbemerkt Erkennung verlieren; seit B0a-4 führt config/guard/rule-changes.json jede Änderung mit Pflichtpaar und Verstoßmengenwirkung.

## Entscheidung (normativ)

Keine Änderung an einer bestehenden Prüfregel wird ohne deklariertes Testpaar angenommen: ein Schärfungstest, der den neu erkannten oder neu erlaubten Randfall abdeckt und vor der Änderung fehlschlägt, und ein Gegentest, der beweist, dass der ursprünglich abgewehrte Verstoß weiterhin erkannt und geblockt wird. Jede Änderung deklariert ihre Wirkung auf die Verstoßmenge; eine schrumpfende Verstoßmenge verlangt eine Eigentümerentscheidung.

## Geltungsbereich

Alle Guard-, Gate- und Governance-Prüfregeln dieses Repositorys.

## Ausdrücklich nicht geregelt

Neue Regeln ohne Vorgänger (sie brauchen reguläre Tests, kein Änderungspaar); die fachliche Wahl der Regeländerung.

## Mechanische Durchsetzung

tg-/of-rule-changes (tools/gates/runners/guard_checks.py, mode rule_changes: fehlendes Paar, nicht auflösbare Referenzen, undeklarierte Fixtures, Schrumpfen ohne Eigentümerentscheidung); Verstoßkorpus-Metagate; tests/tooling/guard/test_rule_metagates.py.

## Herkunft

description-Feld in config/guard/rule-changes.json (B0a-4, 02b775e). Das Feld war die einzige Normquelle und wurde von keinem Prüfer gelesen; seit B0g ist dieses Dokument die normative Quelle und das Feld reine Referenz.
