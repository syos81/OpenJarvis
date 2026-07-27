---
Status: normativ
Architektur-Baseline: v3
Freigabedatum: 2026-07-27
Baseline-Tag: openjarvis-baseline-2026-07-27
Maßgebliche AV-Regeln: AV-17, AV-18, AV-19
Zugehörige ADRs: ADR-0005, ADR-0007, ADR-0010
Verwandte DEC-Einträge: DEC-005, DEC-023; offen: DEC-D06
---

# ADR-0006: Risikomodell R0/R1/R2

- **ADR-Status:** accepted
- **Datum:** 2026-07-27

## Kontext

Der Audit belegte, dass Upstream-Sicherheitsmechanismen existieren, aber default-inert sind (Sandbox aus, Capability-Gates aus, unbestätigte Codeausführung). Ein persönlicher Assistent mit Mail-Versand, Kalender-Schreibzugriff und perspektivisch Trading braucht ein verhältnismäßiges, deklaratives Risikomodell — insbesondere eine harte Grenze für Finanzoperationen.

## Entscheidung

1. Jede Capability-Operation deklariert ihre Klasse: **R0** (lokal/extern lesend, ohne Zustandsänderung), **R1** (extern schreibend/versendend/verändernd), **R2** (finanziell, irreversibel, sicherheitskritisch oder mit erheblichen Folgen).
2. **R1:** Capability-Prüfung, verständliche Vorschau, explizite Bestätigung (Initiation-Kontexte, ADR-0005), Audit-Log, Ergebnisverifikation.
3. **R2 zusätzlich:** dauerhafter Approval-Datensatz, **deterministische RiskEngine** (rein Code; Regeländerungen selbst R2), erneute Zustandsprüfung unmittelbar vor Ausführung, eindeutiger Not-Aus/Abbruchpfad, unveränderliche Ausführungs- und Ergebnisprotokollierung.
4. **Trading-Orders sind immer R2; ein Sprachmodell platziert niemals Orders und verändert niemals Risikoregeln.**
5. **Getrennte Executor-Bereiche:** Sync/R1-Outbox vs. separater R2-Executor mit eigenem globalem Kill-Switch; zusätzlich konto-/capabilitybezogene Sperren. Ein R2-Not-Aus stoppt nie Sync/R1.
6. Umsetzung über die Personal-Basisdienste (ActionPipeline, ApprovalIntents, AuditTrail); der fragmentierte Upstream-ApprovalStore wird nicht genutzt.

## Geprüfte Alternativen

- **Globale Maximal-Härtung** (alles überall bestätigungspflichtig) — verworfen: unverhältnismäßige Reibung, Gefahr späterer Pauschal-Abschaltung.
- **Politik nur je Preset/Konfiguration** — verworfen: exakt der Weg, auf dem Upstream inkonsistent wurde.
- **Gemeinsamer Executor mit globalem Not-Aus** — verworfen: ein Trading-Stopp dürfte nie die Kalender-Synchronisation anhalten.

## Konsequenzen

Risikoklassen werden Bestandteil jedes Capability-Vertrags und jeder Modul-Abnahme; die R2-Maschinerie (RiskEngine, Approval-Center, R2-Executor) entsteht erst mit dem ersten R2-Modul (AV-33); eine optionale native Zweitbestätigung bleibt offen (DEC-D06).

## Verweise

Primärdokument: 10. Regeln: AV-17–AV-19.
