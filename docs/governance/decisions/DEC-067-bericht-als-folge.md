---
DEC-ID: DEC-067
Titel: Der Bericht ist Folge der Definition, nie ihre Schwester
Status: accepted
Regel-Alias: bericht-als-folge
Registerpfad: refs/governance/dec-reservations
Block: B0g
---

# DEC-067 — Der Bericht ist Folge der Definition, nie ihre Schwester

## Kontext

Der Eigentümer trennte in B0b den Abschluss: der normative Commit trägt die Definition, der feststellende erzeugt den Bericht aus einem Gate-Lauf — der Bericht folgt der Definition, statt sie zu begleiten (config/gates/history/b0b-commit-plan.json, plan_change). Seit B0c ist die Trennung in jedem Commit-Plan deklariert.

## Entscheidung (normativ)

Ein Bericht oder Abschlussartefakt entsteht ausschließlich nach und ausschließlich aus bereits fixierten überprüfbaren Quellen — maschinelle Gate-Ergebnisse, sanitierte Evidenz, Git- und Manifestdaten — in einem feststellenden Commit, der dem normativen Commit folgt, den er beschreibt; nie im selben Commit und nie als unabhängig verfasste Paralleldarstellung. Feststellende Commits ändern keine Entscheidung, Regel, Fixture oder Gatebedingung. Ein während der Feststellung gefundener normativer Fehler erzeugt einen neuen normativen Commit mit maschinenlesbarer Begründung und einen vollständigen neuen Lauf; kein Amend. Maschinelle Ergebnisse werden wörtlich übernommen: keine Umdeutung, keine Abschwächung, kein grüner Abschluss bei fail oder blocked, kein manueller Lauf als Ersatz für ein fehlendes Gate-Ergebnis; vor jedem Abschluss läuft die Merkmalsvollständigkeitsprüfung gegen den unmittelbaren Vorgänger.

## Geltungsbereich

Alle Handoffs, Abschlussberichte, Abnahmerecords und feststellenden Commits.

## Ausdrücklich nicht geregelt

Der Berichtsstil (kurz, deltaorientiert — Bedienhinweis, nicht Norm); die Werkzeugwahl des Skills.

## Mechanische Durchsetzung

Merkmalsvollständigkeit über of-/mf-feature-lineage (tools/gates/features.py); Skill .claude/skills/handoff-report/SKILL.md als Durchsetzungsartefakt der Quellendisziplin; Kommissionsordnung prozedural über die Commit-Pläne. Durchsetzungsgap: die Reihenfolgehälfte (split_justification) wird von keinem Prüfer konsumiert — dokumentiert im Authority-Modell.

## Herkunft

plan_change in config/gates/history/b0b-commit-plan.json (Eigentümerentscheidung B0b, wörtlich: the report follows the definition instead of accompanying it), verallgemeinert in den split_justification-Feldern seit B0c; Quellendisziplin aus .claude/skills/handoff-report/SKILL.md (B0a-1) und CLAUDE.md-Altabschnitten. Der Name Bericht-ist-Folge-und-nicht-Schwester ist die Lesebezeichnung dieser bestehenden Entscheidung.
