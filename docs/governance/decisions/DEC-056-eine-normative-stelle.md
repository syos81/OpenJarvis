---
DEC-ID: DEC-056
Titel: Genau eine normative Stelle je Sachverhalt
Status: accepted
Regel-Alias: R1
Registerpfad: refs/governance/dec-reservations
Block: B0g
---

# DEC-056 — Genau eine normative Stelle je Sachverhalt

## Kontext

Mehrere Träger derselben Regel drifteten auseinander; B0a-3 löste die Entscheidungs-Kollisionen der zwei Linien auf und führte das Register der normativen Stellen ein (config/governance/normative-sources.json).

## Entscheidung (normativ)

Für jeden Sachverhalt existiert genau eine normative Stelle. Jeder andere Träger ist eine deklarierte Projektion, ein deklariert-historisches Dokument mit unübersehbarer Kennzeichnung (mechanisch von normativen Auswertungen ausgeschlossen) oder eine Mechanikdatei, deren Suchmuster Regeldefinition und kein Verweis sind. Historische Auflösungsnachweise dürfen Alt-IDs führen, sind als solche deklariert und zählen nie als aktuelle Doppelvergabe.

## Geltungsbereich

Alle normativen Aussagen dieses Repositorys: Governance-Register, Konfigurationen, CLAUDE.md, Handbücher.

## Ausdrücklich nicht geregelt

Die inhaltliche Richtigkeit einzelner Entscheidungen; die Wahl des Dokumentformats; historische Stände (Korrektur statt Eingriff).

## Mechanische Durchsetzung

of-single-normative-source (tools/gates/runners/integration_checks.py, mode single-normative-source) für den Kollisionssachverhalt; ab B0g zusätzlich das Authority-Modell config/governance/decision-authority.json mit Validator (genau eine authoritative-Bindung je Entscheidung). Durchsetzungsgap vor B0g: der Check lief nur im B0a-3-Manifest; dokumentiert im B0g-Korrekturvermerk.

## Herkunft

Regel-Feld in config/governance/normative-sources.json (eingeführt mit a093687, B0a-3). Die Bindung des Alias R1 an diesen Satz ist eine dokumentierte Inferenz aus der Registrierungsliste docs/governance/b0c-handoff.md §9 (R1–R4), in der R2/R3/R4 anderweitig belegt sind; keine Quelle widerspricht ihr.
