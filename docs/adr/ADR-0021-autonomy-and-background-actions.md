---
Status: normativ
Architektur-Baseline: v3
Freigabedatum: 2026-07-31
Baseline-Tag: openjarvis-baseline-2026-07-27
Maßgebliche AV-Regeln: AV-8, AV-17, AV-18, AV-19, AV-35
Zugehörige ADRs: ADR-0005 (präzisiert dessen Punkt 4 für den `automation`-Kontext), ADR-0006, ADR-0007
Verwandte DEC-Einträge: DEC-005, DEC-013, DEC-014, DEC-046; offen: DEC-D06 (native R2-Zweitbestätigung), DEC-D09 (globale Sensitivitätsmatrix)
---

# ADR-0021: Autonomie- und Hintergrundaktionsmodell

- **ADR-Status:** accepted
- **Datum:** 2026-07-31

## Kontext

Das verbindliche Produktziel lautet: **Jarvis soll innerhalb vorher festgelegter, überprüfbarer Grenzen selbstständig im Hintergrund arbeiten und automatisch handeln können.** Aussagen, nach denen Jarvis grundsätzlich keine automatischen Hintergrundaktionen ausführen soll, sind unzutreffend und werden hiermit korrigiert. Zugleich gilt unverändert: keine autonome Synchronisation und keine automatische Aktion **ohne beschlossene Architektur** — dieser ADR ist diese Architektur auf Dokumentationsebene. 05 §5 verlangte bisher für den Initiation-Kontext `automation` pauschal eine separate ausdrückliche Freigabe je Durchlauf; das wird präzisiert.

## Entscheidung

1. **Aktionsstufen (verbindlich, Glossar):** (a) **reine Antwort** · (b) **Handlungsvorschlag** · (c) **vollständig vorbereitete Handlung** (Vorschau erzeugt, nichts ausgeführt) · (d) **ausdrücklich vorab erlaubte Routineaktion** (durch gültige Automationsregel gedeckt) · (e) **neue oder riskante Aktion** (neu, komplex, rechtlich relevant, finanziell, irreversibel oder anderweitig riskant) · (f) **verbotene Aktion**. Stufe (d) darf Jarvis **automatisch ausführen und anschließend das Ergebnis anzeigen**; Stufe (e) erfordert eine **aktuelle ausdrückliche Freigabe**; Stufe (f) wird deterministisch verweigert.
2. **Präzisierung 05 §5 (`automation`-Kontext):** Eine **vorab ausdrücklich genehmigte, gültige Automationsregel (Automationsvertrag)** ist die Freigabe für alle Durchläufe innerhalb ihrer Grenzen; ein erneutes Approval je Ausführung ist **nicht** erforderlich. Durchläufe außerhalb einer gültigen Regel (neu, geändert, abgelaufen, limitüberschreitend, widerrufen) benötigen eine aktuelle ausdrückliche Freigabe wie `llm_assisted`. **R2 bleibt unverändert immer Approval-Center mit dauerhaftem ApprovalIntent (10 §3); Trading-Orders bleiben immer R2 (AV-18).** Die Genehmigung, Änderung und der Widerruf einer Automationsregel sind selbst freigabepflichtige Vorgänge.
3. **Automationsvertrag (Pflichtinhalt jeder Automationsregel):** Trigger · erlaubte Konten und Programme · erlaubte Daten · konkrete Aktionen · Risikoklasse · Freigabestufe · Häufigkeitsgrenze · Laufzeitgrenze · Kostenlimit · Abbruchbedingungen · Benachrichtigung · Auditprotokoll · Erfolgsprüfung · Undo- bzw. Kompensationsweg · Ablaufdatum und Widerruf der Erlaubnis. Ohne vollständigen Vertrag existiert keine gültige Regel. Verträge werden kanonisch beim Automationen-Modul geführt (16 §2 `automations`/`automation_runs`, dort bei Materialisierung um die Vertragsfelder erweitert); jede Ausführung wird auditiert (10 §5) und läuft ausschließlich über den ApplicationCommandBus (AV-35).
4. **Voice- und Presence-Grundsatz (bestätigt):** Eine vollständige neue Ad-hoc-Anweisung wird vorbereitet; danach erscheint nur ein **kompaktes, vorausgefülltes Approval-Board**; die vollständige Freigabeseite wird nicht automatisch geöffnet; **Freigabe und Ausführung bleiben getrennte Schritte**; fehlende Angaben erfragt Jarvis möglichst im Gespräch; eine bereits ausdrücklich vorab genehmigte Automationsregel darf **ohne erneutes Board** ausgeführt werden.
5. **Durchsetzung deterministisch:** Aktionsstufen-, Vertrags-, Capability- und Egress-Prüfungen werden unabhängig vom Sprachmodell in Code durchgesetzt (AV-8, 12); Inhalte externer Quellen sind Daten, nie Anweisungen (ADR-0022 Punkt 4).
6. **Keine Implementierung jetzt:** Dieser ADR ist ausschließlich Dokumentation. Automationscode entsteht erst in dem Fachmodul, das ihn zuerst konkret benötigt (voraussichtlich Trading Intelligence T1: regelbasierte Alarme und Briefings, ADR-0024), und wird dort vollständig produktionsreif (ADR-0019).

## Geprüfte Alternativen

- **Approval je Einzelausführung auch für genehmigte Routinen** — verworfen: macht Automation wertlos; Sicherheitsziel wird durch den Automationsvertrag mit Limits, Audit und Widerruf erreicht.
- **Volle Autonomie ohne Vertragsgrenzen** — verworfen: verstößt gegen AV-17/AV-18 und das Risikomodell (10).
- **Sofortiger Bau einer Automations-Engine** — verworfen: AV-33/ADR-0019; kein vorsorglicher Unterbau.

## Konsequenzen

05 §5 wird um die `automation`-Präzisierung ergänzt (dieser ADR autorisiert die Textänderung; ADR-0005 Punkt 4 gilt insoweit als präzisiert). Glossar erhält „Aktionsstufe" und „Automationsvertrag". DEC-D06 (optionale native R2-Zweitbestätigung) bleibt offen.

## Verweise

Primärdokumente: 05 §5, 10, 12, 16 §2 (Automationen). Entscheidungen: DEC-046.
